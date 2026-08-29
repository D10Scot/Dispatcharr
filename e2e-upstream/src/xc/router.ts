import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Scenario } from '../scenario.js';
import { renderAccountEnvelope } from './envelope.js';

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
    const host = context.req.headers.host ?? 'e2e-upstream:8080';
    log(200);
    sendJson(200, renderAccountEnvelope(scenario, new Date(), host));
    return true;
  }

  return false;
}
