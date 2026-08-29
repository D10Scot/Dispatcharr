import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Scenario } from '../scenario.js';
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

    const list = listActions[action];
    if (list) {
      log(200);
      sendJson(200, list());
      return true;
    }

    if (action === 'get_vod_info') {
      const info = renderVodInfo(scenario, Number(url.searchParams.get('vod_id')));
      log(info ? 200 : 404);
      // `Client.get_vod_info` requires a dict, so a 404 body is a dict too —
      // the product surfaces the HTTPError, not a shape error.
      sendJson(info ? 200 : 404, info ?? { error: 'no such vod_id' });
      return true;
    }

    if (action === 'get_series_info') {
      const info = renderSeriesInfo(scenario, Number(url.searchParams.get('series_id')));
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

  return false;
}
