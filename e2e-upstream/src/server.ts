import http from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { ScenarioRegistry, parseScenarioRequest } from './scenario.js';
import type { Scenario } from './scenario.js';
import { BadRequestError } from './errors.js';
import { renderPlaylist, credentialQuery, PLAYLIST_CONTENT_TYPE } from './playlist.js';
import { renderXmltv, XMLTV_CONTENT_TYPE } from './xmltv.js';
import { loadAsset } from './asset.js';
import type { LoadedAsset } from './asset.js';
import { ConnectionRegistry } from './connections.js';
import type { LiveConnection } from './connections.js';
import { streamLoop, STREAM_CONTENT_TYPE } from './stream.js';
import { FaultStore, DEFAULT_REDIRECT_DEPTH, parseFaultRequest } from './faults.js';
import { ScenarioLog } from './log.js';
import { handleXc, looksLikeXcRoute } from './xc/router.js';

export interface RunningServer {
  close(): Promise<void>;
  port: number;
}

export function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

export const registry = new ScenarioRegistry();
export const connections = new ConnectionRegistry();
export const faults = new FaultStore();
export const scenarioLog = new ScenarioLog();

/**
 * Loaded on first use, not at module scope. `readFileSync` on
 * `UPSTREAM_ASSET` (`/app/assets/loop.ts` by default) only succeeds inside
 * the Docker image, where `make-asset.sh` put it there at build time — it
 * does not exist in the environment this test suite runs in. Every test
 * that imports this module for the scenario/playlist/EPG routes would fail
 * at import time if this ran eagerly, long before any test ever exercises
 * the stream route itself.
 */
let asset: LoadedAsset | undefined;
function getAsset(): LoadedAsset {
  if (!asset) {
    asset = loadAsset(process.env.UPSTREAM_ASSET ?? '/app/assets/loop.ts');
  }
  return asset;
}

// A 5,000-channel scenario body is genuinely large; 1 MB is comfortable
// headroom above that without being large enough to matter as a resource
// exhaustion vector.
const MAX_BODY_BYTES = 1024 * 1024;
// Short enough that a client that opens a connection and never finishes its
// body (accidentally or as a deliberate probe) doesn't leak that request
// forever — readRawBody previously had no bound on either size or time.
const BODY_READ_TIMEOUT_MS = 10_000;

interface ReadBodyOptions {
  maxBytes?: number;
  timeoutMs?: number;
}

function readRawBody(req: IncomingMessage, options: ReadBodyOptions = {}): Promise<string> {
  const maxBytes = options.maxBytes ?? MAX_BODY_BYTES;
  const timeoutMs = options.timeoutMs ?? BODY_READ_TIMEOUT_MS;

  // Event-based rather than `for await (const chunk of req)`: the timeout
  // and the byte cap both need to cut the read short from outside the
  // iteration, without destroying the underlying socket (see the comment on
  // `finish` below) — a bare `for await` loop has no way to stop early
  // except by destroying the stream it's iterating.
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;

    const finish = (error: Error | undefined, value?: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.removeListener('data', onData);
      req.removeListener('end', onEnd);
      req.removeListener('error', onError);
      if (error) reject(error);
      else resolve(value ?? '');
    };

    // Deliberately doesn't call `req.destroy()` here: an IncomingMessage's
    // `destroy()` tears down the *socket* it shares with the response, so
    // calling it before `sendJson` writes the 400 would kill the connection
    // the client is waiting on — the client sees a bare connection reset
    // instead of the error body naming what limit it hit. Removing the
    // listeners is enough to stop this handler from accumulating any more
    // memory and to let the promise settle; the socket itself is reclaimed
    // once the response finishes (or by Node's own connection timeout if
    // the client never stops sending).
    //
    // Idle-based, not a wall-clock deadline from read-start: it resets on
    // every chunk, so it only fires when the body genuinely stalls. A
    // fixed deadline from read-start would reject a large-but-progressing
    // body (a 5,000-channel scenario on a loaded CI runner) even though
    // nothing ever stalled — a false positive in exactly the failure class
    // this goal exists to eliminate.
    let timer = setTimeout(onStall, timeoutMs);
    function onStall() {
      finish(new BadRequestError(`request body stalled for longer than ${timeoutMs}ms`));
    }

    const onData = (chunk: Buffer) => {
      clearTimeout(timer);
      timer = setTimeout(onStall, timeoutMs);

      total += chunk.byteLength;
      if (total > maxBytes) {
        finish(new BadRequestError(`request body exceeds ${maxBytes} bytes`));
        return;
      }
      chunks.push(chunk);
    };
    const onEnd = () => finish(undefined, Buffer.concat(chunks).toString('utf8'));
    const onError = (error: Error) => finish(error);

    req.on('data', onData);
    req.on('end', onEnd);
    req.on('error', onError);
  });
}

/**
 * Reads and parses a JSON request body, guaranteeing the result is a plain
 * object (never null, an array, or a primitive) so callers can spread or
 * index into it without a runtime crash disguising itself as a 500. An empty
 * body is deliberately treated as `{}` — that's how `POST /scenarios` with no
 * body creates a default scenario — but any non-empty, non-object body is
 * rejected with `BadRequestError` rather than silently coerced.
 */
export async function readJsonObject(
  req: IncomingMessage,
  options?: ReadBodyOptions
): Promise<Record<string, unknown>> {
  const raw = await readRawBody(req, options);
  if (raw.length === 0) return {};

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new BadRequestError('request body is not valid JSON');
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new BadRequestError('request body must be a JSON object');
  }

  return parsed as Record<string, unknown>;
}

/**
 * `internal` is what Dispatcharr is given; `control` is what the Playwright
 * host calls. They are never interchangeable — see "Two base URLs" in the
 * spec. INTERNAL_ORIGIN is what resolves inside the Docker network; the
 * control origin is echoed from the request's own Host header, so it is
 * correct whatever port the caller published.
 */
const INTERNAL_ORIGIN =
  process.env.UPSTREAM_INTERNAL_ORIGIN ?? 'http://e2e-upstream:8080';

function scenarioUrls(scenario: Scenario, req: IncomingMessage) {
  // HTTP/1.1 requires Host; a request missing it is pathological, and a
  // fabricated fallback would produce a `control` URL that is silently
  // wrong — the one outcome worse than failing loudly, since the whole point
  // of the internal/control split is that the two are never interchangeable.
  const host = req.headers.host;
  if (!host) {
    throw new BadRequestError('request has no Host header');
  }

  return {
    internal: `${INTERNAL_ORIGIN}/s/${scenario.id}`,
    control: `http://${host}/s/${scenario.id}`,
    credentialQuery: credentialQuery(scenario),
  };
}

/**
 * Records one `'request'` log entry once a route has decided a resolved
 * scenario's response status. Never called before a scenario is found — an
 * unresolved scenario id has nowhere to log to — so the bare "no scenario"
 * 404s above are deliberately not logged here.
 *
 * `path` carries the search string as well as the pathname: the XC routes
 * (G8) put everything that identifies a request — `stream=1`, `duration=65`,
 * `username=...` — in query parameters rather than PATH segments, so a log
 * entry that dropped the query would be unable to name what was asked for.
 */
function logRequest(scenario: Scenario, req: IncomingMessage, url: URL, status: number): void {
  scenarioLog.record(scenario.id, {
    kind: 'request',
    method: req.method,
    path: url.pathname + url.search,
    status,
  });
}

/**
 * Real credential validation, when the scenario declares any. Applied
 * identically to the playlist, EPG and stream routes: the fixture's
 * `playlistUrl()`/`epgUrl()` append the same `credentialQuery` the stream
 * route checks, and a refresh is exactly the request those credentials are
 * meant to gate. `auth-failure` above models something different — valid
 * credentials that stop being accepted — so it's not a substitute for this
 * check on the never-valid or wrong-from-the-start case.
 */
function credentialsMatch(scenario: Scenario, url: URL): boolean {
  if (scenario.username === undefined) return true;
  const givenUser = url.searchParams.get('username');
  const givenPass = url.searchParams.get('password');
  return givenUser === scenario.username && givenPass === (scenario.password ?? '');
}

/**
 * Serves one channel's paced TS loop, with the full fault and admission
 * pipeline. Extracted from the `/s/<id>/stream/<n>.ts` route so the XC
 * `/live/<user>/<pass>/<n>.ts` route and the two catch-up routes serve
 * byte-identical streams through byte-identical fault handling. Three copies
 * of this pipeline would drift, and the drift would look like a product bug.
 *
 * Does NOT check that the channel id is one the scenario declared: the
 * pre-existing `/stream/<n>.ts` route deliberately serves any numeric id, and
 * G4 tests rely on that. The XC routes check membership themselves, before
 * calling this.
 */
export interface ServeChannelStreamOptions {
  /**
   * Set by a caller that has already authenticated the request through a
   * different credential transport than step 3's query-string check below —
   * the XC `/live/<user>/<pass>/<n>.ts` route carries `username`/`password`
   * as path segments (via `xcCredentialsMatch`), not `?username=`. Without
   * this, step 3 would 401 every XC live request (an `xc: true` scenario
   * always has both fields set — `scenario.ts` enforces it — and a `/live/`
   * URL never carries a query string), since `logRequest` must record the
   * URL the client actually sent, not one rewritten to carry credentials in
   * the query string just to satisfy this check.
   */
  credentialsAlreadyVerified?: boolean;
}

export async function serveChannelStream(
  scenario: Scenario,
  channelId: number,
  req: IncomingMessage,
  res: ServerResponse,
  url: URL,
  options: ServeChannelStreamOptions = {}
): Promise<void> {
  // Fault checks run before tryAcquire and before the HEAD/GET branch
  // below, in the order a real provider's own failure modes would
  // actually short-circuit a request. A request rejected by a fault must
  // not consume a connection slot — a maxConnections: 1 scenario with
  // `not-found` armed would otherwise leak its one slot on the first
  // rejected attempt, and every later assertion about the limit would be
  // wrong for a reason that looks like broken accounting.

  // 1. not-found: nothing else can happen if the URL 404s.
  if (faults.isActive(scenario.id, 'not-found', channelId)) {
    logRequest(scenario, req, url, 404);
    sendJson(res, 404, { error: 'fault: not-found' });
    return;
  }

  // 2. auth-failure: credentials that were valid stop being accepted.
  if (faults.isActive(scenario.id, 'auth-failure', channelId)) {
    logRequest(scenario, req, url, 401);
    sendJson(res, 401, { error: 'fault: auth-failure' });
    return;
  }

  // 3. Real credential validation, when the scenario declares any. Skipped
  // when the caller already verified credentials through a different
  // transport (see `ServeChannelStreamOptions`) — in that case this check
  // would either be a tautology (fed the right answer just to pass it) or,
  // for a query-string-free request like XC's `/live/`, wrongly reject an
  // already-authenticated caller. A future divergence between the two
  // credential predicates (this one and `xcCredentialsMatch`) would be
  // silent under that bypass; both currently compare the same two
  // `scenario` fields, so today they can't disagree.
  if (!options.credentialsAlreadyVerified && !credentialsMatch(scenario, url)) {
    logRequest(scenario, req, url, 401);
    sendJson(res, 401, { error: 'bad credentials' });
    return;
  }

  // 4. redirect-chain: a chain of 302s that finally lands on this same
  //    URL with ?chain=0, so the payload stays reachable by following it.
  //    The chain param is layered onto the existing query string, so the
  //    credential query above survives every hop.
  const chainConfig = faults.configOf(scenario.id, 'redirect-chain', channelId);
  if (chainConfig && faults.isActive(scenario.id, 'redirect-chain', channelId)) {
    const remaining = Number(
      url.searchParams.get('chain') ?? (chainConfig.depth ?? DEFAULT_REDIRECT_DEPTH)
    );
    if (remaining > 0) {
      const next = new URL(url.pathname + url.search, INTERNAL_ORIGIN);
      next.searchParams.set('chain', String(remaining - 1));
      logRequest(scenario, req, url, 302);
      res.writeHead(302, { Location: next.toString() });
      res.end();
      return;
    }
    // remaining <= 0: the chain is exhausted, so fall through and serve
    // the real thing instead of redirecting again.
  }

  // 5. non-ts-bytes: 200 with an HTML error page, which is what a
  //    provider actually sends when it is unhappy. buffer.py's
  //    realignment is the code this exercises.
  if (faults.isActive(scenario.id, 'non-ts-bytes', channelId)) {
    const body = '<html><body><h1>502 Bad Gateway</h1></body></html>';
    logRequest(scenario, req, url, 200);
    res.writeHead(200, {
      'Content-Type': 'text/html',
      'Content-Length': Buffer.byteLength(body),
    });
    res.end(body);
    return;
  }

  // 6. connection-limit as a fault forces rejection regardless of the
  //    real count — armed so a client hits the limit without needing to
  //    actually saturate it.
  if (faults.isActive(scenario.id, 'connection-limit', channelId)) {
    logRequest(scenario, req, url, 429);
    sendJson(res, 429, { error: 'fault: connection-limit' });
    return;
  }

  // validate_stream_url() probes with HEAD before streaming. It must
  // succeed, and it must not consume a connection slot — a
  // maxConnections:1 scenario would otherwise reject the real client that
  // follows. Logged with its method so this probe never reads as a real
  // viewer connecting (see ScenarioLog).
  if (req.method === 'HEAD') {
    logRequest(scenario, req, url, 200);
    res.writeHead(200, { 'Content-Type': STREAM_CONTENT_TYPE });
    res.end();
    return;
  }

  if (req.method !== 'GET') {
    logRequest(scenario, req, url, 405);
    sendJson(res, 405, { error: `${req.method} not allowed on a stream` });
    return;
  }

  // Resolved before tryAcquire, deliberately: admission doesn't depend on
  // the asset, and acquiring the slot first would leak it if getAsset()
  // throws (missing or corrupt UPSTREAM_ASSET) — the slot would never be
  // released, and since a failed load isn't cached, every retry leaks
  // another one until maxConnections is permanently exhausted.
  const asset = getAsset();

  // Admission is decided, and must be decided, before streamLoop writes
  // any header — a rejected client must never see a 200 first. The
  // connection object is built here with placeholder methods and handed
  // to streamLoop, which replaces them with the real ones once admitted;
  // the identity tryAcquire recorded is the identity a fault handler
  // later calls back into.
  const connection: LiveConnection = {
    scenarioId: scenario.id,
    channelId,
    setDeadAir: () => {},
    setRate: () => {},
    disconnect: () => {},
    refreshRate: () => {},
  };

  if (!connections.tryAcquire(scenario, connection)) {
    logRequest(scenario, req, url, 429);
    sendJson(res, 429, { error: 'connection limit reached' });
    return;
  }

  logRequest(scenario, req, url, 200);
  // dead-air and slow-trickle apply to "live + new" connections; `apply`
  // only reaches connections that are already open at the moment a fault
  // is armed, so a connection opened afterward needs to start already in
  // that state rather than clean — see FaultStore.initialStateFor.
  const initialState = faults.initialStateFor(scenario.id, channelId);
  await streamLoop(
    res,
    asset,
    {
      scenarioRate: () => scenario.rate,
      onConnection: () => scenarioLog.record(scenario.id, { kind: 'open', channelId }),
      onClosed: (stats) => {
        connections.release(connection);
        scenarioLog.record(scenario.id, { kind: 'close', channelId, ...stats });
      },
    },
    connection,
    initialState
  );
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? '/', 'http://placeholder');

  if (url.pathname === '/scenarios' && req.method === 'GET') {
    sendJson(res, 200, registry.list().map((s) => ({ ...s, ...scenarioUrls(s, req) })));
    return;
  }

  if (url.pathname === '/scenarios' && req.method === 'POST') {
    const body = await readJsonObject(req);
    const scenario = registry.create(parseScenarioRequest(body));
    sendJson(res, 201, { ...scenario, ...scenarioUrls(scenario, req) });
    return;
  }

  const scenarioMatch = /^\/scenarios\/([^/]+)$/.exec(url.pathname);
  if (scenarioMatch && req.method === 'DELETE') {
    const existed = registry.delete(scenarioMatch[1]);

    // Without this, a deleted scenario's clients keep receiving TS
    // indefinitely: each streamLoop holds the scenario alive through its
    // `scenarioRate` closure, and nothing else ever touched
    // ConnectionRegistry on delete — `/connections`, `/fault` and `/rate`
    // all 404 on the now-gone id, so a leaked stream couldn't even be
    // observed or driven afterward, only left to run forever. Abrupt, not
    // clean: a deleted scenario is not a graceful end-of-stream, and the
    // client should see an error. `matching` is read before `dropScenario`
    // removes the very list it returns.
    for (const connection of connections.matching(scenarioMatch[1])) {
      connection.disconnect({ clean: false });
    }
    connections.dropScenario(scenarioMatch[1]);

    // All three are harmless no-ops on an id with no state, so this runs
    // unconditionally rather than only when `existed`. Without it, every
    // scenario ever created leaves its log and fault state behind
    // permanently — bounded per scenario, but not across a long CI run
    // creating thousands of them.
    scenarioLog.clear(scenarioMatch[1]);
    faults.clearAll(scenarioMatch[1]);
    sendJson(res, existed ? 204 : 404, {});
    return;
  }

  const playlistMatch = /^\/s\/([^/]+)\/playlist\.m3u$/.exec(url.pathname);
  if (playlistMatch && req.method === 'GET') {
    const scenario = registry.get(playlistMatch[1]);
    if (!scenario) {
      sendJson(res, 404, { error: `no scenario ${playlistMatch[1]}` });
      return;
    }
    // A playlist refresh has no single channel in play, so only a
    // scenario-wide fault (no `channel` in the armed request) can fail it —
    // see FaultStore.isActive.
    if (faults.isActive(scenario.id, 'not-found')) {
      logRequest(scenario, req, url, 404);
      sendJson(res, 404, { error: 'fault: not-found' });
      return;
    }
    if (faults.isActive(scenario.id, 'auth-failure')) {
      logRequest(scenario, req, url, 401);
      sendJson(res, 401, { error: 'fault: auth-failure' });
      return;
    }
    if (!credentialsMatch(scenario, url)) {
      logRequest(scenario, req, url, 401);
      sendJson(res, 401, { error: 'bad credentials' });
      return;
    }
    const body = renderPlaylist(scenario, INTERNAL_ORIGIN);
    logRequest(scenario, req, url, 200);
    res.writeHead(200, {
      'Content-Type': PLAYLIST_CONTENT_TYPE,
      'Content-Length': Buffer.byteLength(body),
    });
    res.end(body);
    return;
  }

  const epgMatch = /^\/s\/([^/]+)\/epg\.xml$/.exec(url.pathname);
  if (epgMatch && req.method === 'GET') {
    const scenario = registry.get(epgMatch[1]);
    if (!scenario) {
      sendJson(res, 404, { error: `no scenario ${epgMatch[1]}` });
      return;
    }
    if (faults.isActive(scenario.id, 'not-found')) {
      logRequest(scenario, req, url, 404);
      sendJson(res, 404, { error: 'fault: not-found' });
      return;
    }
    if (faults.isActive(scenario.id, 'auth-failure')) {
      logRequest(scenario, req, url, 401);
      sendJson(res, 401, { error: 'fault: auth-failure' });
      return;
    }
    if (!credentialsMatch(scenario, url)) {
      logRequest(scenario, req, url, 401);
      sendJson(res, 401, { error: 'bad credentials' });
      return;
    }
    const body = renderXmltv(scenario, new Date());
    logRequest(scenario, req, url, 200);
    res.writeHead(200, {
      'Content-Type': XMLTV_CONTENT_TYPE,
      'Content-Length': Buffer.byteLength(body),
    });
    res.end(body);
    return;
  }

  const streamMatch = /^\/s\/([^/]+)\/stream\/(\d+)\.ts$/.exec(url.pathname);
  if (streamMatch) {
    const scenario = registry.get(streamMatch[1]);
    if (!scenario) {
      sendJson(res, 404, { error: `no scenario ${streamMatch[1]}` });
      return;
    }
    const channelId = Number(streamMatch[2]);
    await serveChannelStream(scenario, channelId, req, res, url);
    return;
  }

  const faultMatch = /^\/s\/([^/]+)\/fault$/.exec(url.pathname);
  if (faultMatch && req.method === 'POST') {
    const scenario = registry.get(faultMatch[1]);
    if (!scenario) {
      sendJson(res, 404, { error: `no scenario ${faultMatch[1]}` });
      return;
    }
    const body = await readJsonObject(req);
    const request = parseFaultRequest(body);
    const result = faults.apply(scenario.id, request, connections);
    // appliedTo: 0 is a real, common outcome — see FaultStore's own
    // documentation of the five faults that can only affect the next
    // request. Logging it either way is what lets a 2am reader tell "the
    // fault was applied and reached nobody" apart from "the fault was never
    // applied".
    scenarioLog.record(scenario.id, {
      kind: 'fault',
      fault: request.fault,
      detail: JSON.stringify(result),
    });
    sendJson(res, 200, result);
    return;
  }

  const rateMatch = /^\/s\/([^/]+)\/rate$/.exec(url.pathname);
  if (rateMatch && req.method === 'POST') {
    const scenario = registry.get(rateMatch[1]);
    if (!scenario) {
      sendJson(res, 404, { error: `no scenario ${rateMatch[1]}` });
      return;
    }
    const body = await readJsonObject(req);
    if (typeof body.rate !== 'number' || !(body.rate > 0)) {
      throw new BadRequestError("'rate' must be a number greater than 0");
    }
    scenario.rate = body.rate;
    // Every live connection already reads this back live through
    // `control.scenarioRate()` — the only thing missing is a nudge to make
    // one parked in a sleep or the drain wait notice now, rather than
    // whenever it next elapses on its own. `refreshRate` (not `setRate`)
    // deliberately touches no state: a connection currently overridden by a
    // fault (e.g. slow-trickle) must keep following that override, not this
    // baseline, until the fault itself clears it.
    for (const connection of connections.matching(scenario.id)) {
      connection.refreshRate();
    }
    sendJson(res, 200, { rate: scenario.rate });
    return;
  }

  const logMatch = /^\/s\/([^/]+)\/log$/.exec(url.pathname);
  if (logMatch && req.method === 'GET') {
    // Every sibling `/s/<id>/*` route 404s on an unresolved scenario id
    // before doing anything else; this one didn't, so a typo'd id silently
    // read as "the provider recorded nothing" — a far worse diagnostic than
    // "no such scenario" — instead of naming the actual mistake.
    if (!registry.get(logMatch[1])) {
      sendJson(res, 404, { error: `no scenario ${logMatch[1]}` });
      return;
    }
    sendJson(res, 200, scenarioLog.entries(logMatch[1]));
    return;
  }

  const connectionsMatch = /^\/s\/([^/]+)\/connections$/.exec(url.pathname);
  if (connectionsMatch && req.method === 'GET') {
    const scenario = registry.get(connectionsMatch[1]);
    if (!scenario) {
      sendJson(res, 404, { error: `no scenario ${connectionsMatch[1]}` });
      return;
    }
    sendJson(res, 200, {
      live: connections.count(scenario.id),
      maxConnections: scenario.maxConnections,
      channels: connections.matching(scenario.id).map((connection) => connection.channelId),
    });
    return;
  }

  // The XC surface (G8). Deliberately last: every pre-existing `/s/<id>/*`
  // route above — including the four control routes — must match before this
  // sees the path, or a scenario id containing an unlucky segment would have
  // its control calls answered by the XC router.
  const xcMatch = /^\/s\/([^/]+)(\/.*)$/.exec(url.pathname);
  if (xcMatch) {
    const scenario = registry.get(xcMatch[1]);
    if (scenario && looksLikeXcRoute(xcMatch[2])) {
      if (!scenario.xc) {
        // Named, not bare: without this a G9 author who forgot `xc: true`
        // reads a 404 and starts debugging Dispatcharr's XC client.
        logRequest(scenario, req, url, 404);
        sendJson(res, 404, {
          error: `scenario ${scenario.id} was not created with xc: true, so ${xcMatch[2]} is not served`,
        });
        return;
      }
      const handled = await handleXc({
        scenario,
        req,
        res,
        url,
        subPath: xcMatch[2],
        log: (status) => logRequest(scenario, req, url, status),
        sendJson: (status, body) => sendJson(res, status, body),
        serveChannelStream,
      });
      if (handled) return;
    }
  }

  sendJson(res, 404, { error: `no route for ${req.method} ${url.pathname}` });
}

// Exported so a test can exercise the catch path directly, without needing
// `handle()` to throw over a real socket. Behaviourally identical to inlining
// this in the `createServer` callback below.
export async function requestListener(req: IncomingMessage, res: ServerResponse): Promise<void> {
  try {
    await handle(req, res);
  } catch (error: unknown) {
    // Without this the process dies on a handler throw and the container
    // restarts silently mid-test, which reads as a network flake.
    if (!res.headersSent) {
      if (error instanceof BadRequestError) {
        sendJson(res, 400, { error: error.message });
      } else {
        sendJson(res, 500, { error: String(error) });
      }
    } else {
      res.destroy();
    }
  }
}

export function startServer(port: number): Promise<RunningServer> {
  const server = http.createServer((req, res) => {
    requestListener(req, res).catch(() => {
      // requestListener above already swallows every error `handle()` can
      // throw; this is a backstop in case that swallowing logic itself
      // ever throws, so a bug there can't take the whole process down.
      res.destroy();
    });
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '0.0.0.0', () => {
      // The `once('error', reject)` above only covers the listen attempt.
      // Once we're up, a later socket error (e.g. ECONNRESET on an
      // in-flight connection) has no listener left and would otherwise
      // crash the process — fatal today, and much more likely once
      // streaming sockets are added. Log and keep serving instead.
      server.on('error', (error: unknown) => {
        console.error('e2e-upstream server error:', error);
      });
      resolve({
        port: (server.address() as AddressInfo).port,
        close: () =>
          new Promise<void>((done, fail) =>
            server.close((err) => (err ? fail(err) : done()))
          ),
      });
    });
  });
}
