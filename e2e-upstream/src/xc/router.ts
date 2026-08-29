import type { IncomingMessage, ServerResponse } from 'node:http';
import type { CategorySpec, Scenario } from '../scenario.js';
import { renderAccountEnvelope } from './envelope.js';
import {
  renderLiveCategories,
  renderLiveStreams,
  renderSeries,
  renderSeriesCategories,
  renderSeriesInfo,
  renderVodCategories,
  renderVodInfo,
  renderVodStreams,
} from './catalogue.js';

export interface XcContext {
  scenario: Scenario;
  req: IncomingMessage;
  res: ServerResponse;
  url: URL;
  /** The path with `/s/<id>` already stripped, e.g. `/player_api.php`. */
  subPath: string;
  /** Records a `request` entry against this scenario. */
  log(status: number): void;
  sendJson(status: number, body: unknown): void;
  /**
   * Passed in rather than imported: `src/server.ts` already imports
   * `src/xc/router.ts` (for `handleXc`/`looksLikeXcRoute`), so importing
   * `serveChannelStream` back from `server.ts` here would be a cycle — the
   * same reasoning that put `BadRequestError` in its own leaf module.
   */
  serveChannelStream(
    scenario: Scenario,
    channelId: number,
    req: IncomingMessage,
    res: ServerResponse,
    url: URL,
    options?: { credentialsAlreadyVerified?: boolean }
  ): Promise<void>;
}

/**
 * Every path this module owns. `server.ts` uses it to tell "an XC route on a
 * scenario that never opted in" apart from "a typo" — the first gets a 404
 * naming the missing `xc: true`, the second falls through to the generic 404
 * naming the path.
 */
const XC_PATHS = [
  /^\/player_api\.php$/,
  /^\/live\/[^/]+\/[^/]+\/\d+\.ts$/,
  /^\/movie\/[^/]+\/[^/]+\/\d+\.[A-Za-z0-9]+$/,
  /^\/series\/[^/]+\/[^/]+\/\d+\.[A-Za-z0-9]+$/,
  /^\/timeshift\/[^/]+\/[^/]+\/[^/]+\/[^/]+\/\d+\.ts$/,
  /^\/streaming\/timeshift\.php$/,
];

export function looksLikeXcRoute(subPath: string): boolean {
  return XC_PATHS.some((pattern) => pattern.test(subPath));
}

/** Credentials as XC sends them: query params on the API, path segments on playback. */
export function xcCredentialsMatch(
  scenario: Scenario,
  username: string | null,
  password: string | null
): boolean {
  return username === (scenario.username ?? '') && password === (scenario.password ?? '');
}

/**
 * Missing or non-numeric resolves to `NaN`, never `Number(null) === 0` — a
 * request that omits `vod_id`/`series_id` entirely must not accidentally
 * match a scenario's id-0 movie or series (`id: 0` is a valid id everywhere
 * else in this codebase, and `NaN` matches no real id via `===`).
 */
function parseRequiredId(raw: string | null): number {
  return raw === null || !/^\d+$/.test(raw) ? NaN : Number(raw);
}

export async function handleXc(context: XcContext): Promise<boolean> {
  const { scenario, url, subPath, log, sendJson } = context;

  if (subPath === '/player_api.php') {
    if (
      !xcCredentialsMatch(
        scenario,
        url.searchParams.get('username'),
        url.searchParams.get('password')
      )
    ) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }

    const action = url.searchParams.get('action');
    const categoryId = url.searchParams.get('category_id');

    if (action === null) {
      const host = context.req.headers.host ?? 'e2e-upstream:8080';
      log(200);
      sendJson(200, renderAccountEnvelope(scenario, new Date(), host));
      return true;
    }

    // The tvArchive predicate is a function, not a boolean, because the
    // `no-tv-archive` fault is channel-scopable — Task 7 replaces this
    // always-true stub with a FaultStore lookup.
    const listActions: Record<string, () => unknown[]> = {
      get_live_categories: () => renderLiveCategories(scenario),
      get_live_streams: () => renderLiveStreams(scenario, categoryId, { tvArchive: () => true }),
      get_vod_categories: () => renderVodCategories(scenario),
      get_vod_streams: () => renderVodStreams(scenario, categoryId),
      get_series_categories: () => renderSeriesCategories(scenario),
      get_series: () => renderSeries(scenario, categoryId),
    };

    // Only the three actions that accept `category_id` need it validated;
    // the category-*listing* actions ignore the parameter entirely. Fixed
    // key set, not a `[action]` lookup keyed by the same untrusted `action`
    // string that motivated `Object.hasOwn` below — this table is only ever
    // indexed by one of `listActions`' own six literal keys.
    const categoriesByAction: Partial<Record<string, CategorySpec[]>> = {
      get_live_streams: scenario.liveCategories,
      get_vod_streams: scenario.vodCategories,
      get_series: scenario.seriesCategories,
    };

    // `Object.hasOwn`, never `listActions[action]`'s truthiness: an object
    // literal's bracket lookup also resolves `Object.prototype` members, so
    // `?action=valueOf`/`hasOwnProperty` would return a truthy function that
    // throws when invoked with no receiver (`TypeError`, surfacing as an
    // opaque 500), and `?action=constructor`/`toString` would return a 200
    // with a nonsense body instead of the intended 400.
    if (Object.hasOwn(listActions, action)) {
      const categories = categoriesByAction[action];
      // A `category_id` naming no declared category can only be a
      // hand-written typo — Dispatcharr's own category-filtered calls
      // always reuse an id this same provider listed via
      // get_*_categories — and it fails *quietly*: `200 []` reads exactly
      // like the symptom of a real product bug (an empty category), not a
      // scenario mistake. A `category_id` naming a declared category still
      // legitimately empties to `200 []` when nothing in it matches.
      if (categoryId !== null && categories !== undefined && !categories.some((c) => String(c.id) === categoryId)) {
        log(400);
        sendJson(400, {
          error: `'category_id' ${categoryId} names no declared category; known ids are ${categories
            .map((c) => c.id)
            .join(', ')}`,
        });
        return true;
      }

      // Computed before `log`/`sendJson`, not after: if this ever throws,
      // the log must not already claim 200 for a request whose actual
      // response was a 500.
      const body = listActions[action]();
      log(200);
      sendJson(200, body);
      return true;
    }

    if (action === 'get_vod_info') {
      const info = renderVodInfo(scenario, parseRequiredId(url.searchParams.get('vod_id')));
      log(info ? 200 : 404);
      // `Client.get_vod_info` requires a dict, so a 404 body is a dict too —
      // the product surfaces the HTTPError, not a shape error.
      sendJson(info ? 200 : 404, info ?? { error: 'no such vod_id' });
      return true;
    }

    if (action === 'get_series_info') {
      const info = renderSeriesInfo(scenario, parseRequiredId(url.searchParams.get('series_id')));
      log(info ? 200 : 404);
      sendJson(info ? 200 : 404, info ?? { error: 'no such series_id' });
      return true;
    }

    // An unrecognised action is a test author's typo, not a provider state.
    // Naming the valid set is the same courtesy parseFaultRequest extends.
    log(400);
    sendJson(400, {
      error: `unknown action '${action}'; this provider serves ${Object.keys(listActions)
        .concat('get_vod_info', 'get_series_info')
        .join(', ')} and the no-action handshake`,
    });
    return true;
  }

  const liveMatch = /^\/live\/([^/]+)\/([^/]+)\/(\d+)\.ts$/.exec(subPath);
  if (liveMatch) {
    const [, rawUsername, rawPassword, rawId] = liveMatch;

    // `decodeURIComponent` throws `URIError` on a malformed percent-escape
    // (e.g. a lone `%` or `%ZZ`) — a scenario author's typo in a hand-built
    // test URL, not a server fault, so it gets a 400 naming the offending
    // segment rather than falling through to the generic handler's 500.
    // Decoded (and logged) individually so the error names exactly which
    // segment is malformed.
    let username: string;
    try {
      username = decodeURIComponent(rawUsername);
    } catch {
      log(400);
      sendJson(400, { error: `'username' path segment '${rawUsername}' is not validly percent-encoded` });
      return true;
    }
    let password: string;
    try {
      password = decodeURIComponent(rawPassword);
    } catch {
      log(400);
      sendJson(400, { error: `'password' path segment '${rawPassword}' is not validly percent-encoded` });
      return true;
    }

    if (!xcCredentialsMatch(scenario, username, password)) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }
    const channelId = Number(rawId);
    if (!scenario.channels.some((channel) => channel.id === channelId)) {
      log(404);
      sendJson(404, { error: `scenario ${scenario.id} declares no channel ${channelId}` });
      return true;
    }
    // `credentialsAlreadyVerified: true` — credentials are already checked
    // above, via the path-segment form `xcCredentialsMatch` expects, not the
    // query-string form `serveChannelStream`'s own step 3 reads. Passing the
    // original `url` unmodified (rather than rewriting it to carry
    // `?username=`/`?password=` just to satisfy that check) means
    // `logRequest` inside `serveChannelStream` records the URL the client
    // actually sent.
    await context.serveChannelStream(scenario, channelId, context.req, context.res, url, {
      credentialsAlreadyVerified: true,
    });
    return true;
  }

  return false;
}
