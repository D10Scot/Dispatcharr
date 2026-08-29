import type { IncomingMessage, ServerResponse } from 'node:http';
import type { CategorySpec, Scenario } from '../scenario.js';
import type { ServeOptions } from '../vod-asset.js';
import type { FaultStore } from '../faults.js';
import { renderAccountEnvelope, renderDisabledAccountEnvelope } from './envelope.js';
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
import {
  ACCEPTED_TIMESTAMP_SHAPES,
  CatchupDecodeError,
  parseCatchupPath,
  parseCatchupQuery,
} from './catchup.js';

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
   * The same module-level `FaultStore` `server.ts` already threads through
   * `serveChannelStream` — passed in, not imported, for the same reason as
   * `serveChannelStream`/`serveVodAsset` below: `server.ts` already imports
   * this module, so an import back would be a cycle.
   */
  faults: FaultStore;
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
  /**
   * `serveFiniteAsset` with the VOD asset already bound — passed in for the
   * same reason as `serveChannelStream`: the router never sees a file path,
   * and `server.ts` stays the only module that resolves `UPSTREAM_VOD_ASSET`.
   * Returns the status sent, for `log()`.
   */
  serveVodAsset(res: ServerResponse, options: ServeOptions): number;
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
    // Checked before the credential check, exactly as the playlist and
    // stream routes do (server.ts's `/s/<id>/playlist.m3u` and
    // `serveChannelStream`'s own step 2): auth-failure models valid
    // credentials that stop being accepted, which must win over a 401 that
    // would otherwise read as "the credentials were always wrong".
    if (context.faults.isActive(scenario.id, 'auth-failure')) {
      log(401);
      sendJson(401, { error: 'fault: auth-failure' });
      return true;
    }

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
      // xc-auth-envelope: a 200 whose user_info describes a disabled
      // account, deliberately not a 401 — see renderDisabledAccountEnvelope.
      sendJson(
        200,
        context.faults.isActive(scenario.id, 'xc-auth-envelope')
          ? renderDisabledAccountEnvelope(scenario, new Date(), host)
          : renderAccountEnvelope(scenario, new Date(), host)
      );
      return true;
    }

    const listActions: Record<string, () => unknown[]> = {
      get_live_categories: () => renderLiveCategories(scenario),
      get_live_streams: () =>
        renderLiveStreams(scenario, categoryId, {
          tvArchive: (channelId) => !context.faults.isActive(scenario.id, 'no-tv-archive', channelId),
        }),
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

  // One handler for both `/movie/` and `/series/`: they differ only in which
  // catalogue the id is looked up against, and both serve the same finite
  // asset once membership is established.
  const vodMatch = /^\/(movie|series)\/([^/]+)\/([^/]+)\/(\d+)\.[A-Za-z0-9]+$/.exec(subPath);
  if (vodMatch) {
    const [, kind, rawUsername, rawPassword, rawId] = vodMatch;

    // Same per-field decode guard as the `/live/` route above, and for the
    // same reason: a malformed percent-escape here must 400 naming the
    // field, not fall through to the generic handler's 500.
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

    const wanted = Number(rawId);
    const known =
      kind === 'movie'
        ? scenario.vod.some((movie) => movie.id === wanted)
        : scenario.series.some((series) =>
            series.seasons.some((season) => season.episodes.some((episode) => episode.id === wanted))
          );
    if (!known) {
      log(404);
      sendJson(404, { error: `scenario ${scenario.id} declares no ${kind} with id ${wanted}` });
      return true;
    }

    // Scenario-wide only: a VOD id is not a channel id, so `range-unsupported`
    // has no `channel` scope to narrow to — see the README's fault table.
    const status = context.serveVodAsset(context.res, {
      rangeHeader: context.req.headers.range,
      head: context.req.method === 'HEAD',
      ignoreRange: context.faults.isActive(scenario.id, 'range-unsupported'),
    });
    log(status);
    return true;
  }

  // Both catch-up layouts share one tail from here, so the two cannot
  // diverge in anything but how the request was parsed off the wire. The
  // PATH form is tried first (it's the more specific match — QUERY only
  // fires on the one fixed `/streaming/timeshift.php` path), and a
  // malformed percent-escape in a PATH segment is caught here rather than
  // in `parseCatchupPath` itself, the same split the `/live/` and
  // `/movie|series/` routes above use: the parse function stays a pure
  // "does this shape match", and the router owns turning a decode failure
  // into a 400 naming the field.
  let catchup;
  try {
    catchup =
      parseCatchupPath(subPath) ??
      (subPath === '/streaming/timeshift.php' ? parseCatchupQuery(url) : undefined);
  } catch (error) {
    if (error instanceof CatchupDecodeError) {
      log(400);
      sendJson(400, { error: error.message });
      return true;
    }
    throw error;
  }

  // The QUERY layout's fixed path matched, but `parseCatchupQuery` came
  // back `undefined` because one of the four required parameters is
  // missing — not reachable from Dispatcharr (`build_timeshift_url_format_a`
  // always emits all four), only from a hand-built G10 URL. Without this,
  // that request falls through to the generic handler's `no route for …`
  // 404 with no `log()` call at all — the exact shape Task 4 fixed on
  // `/live/`, reappearing here on a different route and a different status.
  if (!catchup && subPath === '/streaming/timeshift.php') {
    const missing = ['username', 'password', 'stream', 'start'].filter(
      (param) => url.searchParams.get(param) === null
    );
    log(400);
    sendJson(400, {
      error: `'/streaming/timeshift.php' request is missing required parameter(s): ${missing.join(', ')}`,
    });
    return true;
  }

  if (catchup) {
    if (!xcCredentialsMatch(scenario, catchup.username, catchup.password)) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }
    // catchup-layout-404: 404s only the named layout, so a cascade test can
    // watch a client that tries both layouts fall through candidate by
    // candidate rather than dying on the first one. `configOf`'s `layout`
    // check (not just `isActive`) is what makes this layout-specific — an
    // active fault armed for the *other* layout must not block this one.
    if (
      context.faults.isActive(scenario.id, 'catchup-layout-404', catchup.streamId) &&
      context.faults.configOf(scenario.id, 'catchup-layout-404', catchup.streamId)?.layout === catchup.layout
    ) {
      log(404);
      sendJson(404, { error: `fault: catchup-layout-404 (${catchup.layout})` });
      return true;
    }
    if (catchup.startIso === null) {
      // Named, because a bare 400 here is indistinguishable from a cascade
      // step legitimately failing — and this provider must never be the
      // reason a cascade test reports the wrong shape as unsupported.
      log(400);
      sendJson(400, {
        error: `unrecognised catch-up timestamp '${catchup.start}'; this provider accepts ${ACCEPTED_TIMESTAMP_SHAPES}`,
      });
      return true;
    }
    if (!scenario.channels.some((channel) => channel.id === catchup.streamId)) {
      log(404);
      sendJson(404, { error: `scenario ${scenario.id} declares no channel ${catchup.streamId}` });
      return true;
    }
    // The archive is not time-addressable: the same loop is served whatever
    // `start` asked for. That is a stated, deliberate gap — G10 can prove
    // Dispatcharr asked for the right moment, never that it received it.
    await context.serveChannelStream(scenario, catchup.streamId, context.req, context.res, url, {
      credentialsAlreadyVerified: true,
    });
    return true;
  }

  return false;
}
