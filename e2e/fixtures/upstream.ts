import type { TestInfo } from '@playwright/test';
import type { UpstreamCategory, UpstreamMovie, UpstreamSeries } from './types';

export const UPSTREAM_CONTROL_BASE =
  process.env.E2E_UPSTREAM_CONTROL_URL ?? 'http://127.0.0.1:9402';

export const UPSTREAM_INTERNAL_BASE =
  process.env.E2E_UPSTREAM_INTERNAL_URL ?? 'http://e2e-upstream:8080';

/**
 * The original eight (`dead-air` … `non-ts-bytes`) are documented on
 * `upstream.fault()` in `index.ts`. The four G8 additions each carry a
 * scoping quirk worth knowing before arming one:
 *  - `xc-auth-envelope` — scenario-wide only; a `channel` in
 *    {@link FaultOptions} is **rejected** (400). Armed, `player_api.php`'s
 *    no-`action` handshake answers 200 with `user_info.auth: 0,
 *    status: 'Disabled'` — never a 401.
 *  - `no-tv-archive` — channel-scoped, like the original eight. Armed,
 *    `get_live_streams` omits `tv_archive`/`tv_archive_duration` for the
 *    reached channel(s).
 *  - `catchup-layout-404` — channel-scoped; see {@link FaultOptions.layout}.
 *  - `range-unsupported` — scenario-wide only; a `channel` is **rejected**
 *    (400) — a VOD id isn't a channel id. Armed, `/movie|series/` answers 200
 *    with the whole asset, no `Accept-Ranges`, and `Range` is ignored.
 */
export type FaultName =
  | 'dead-air'
  | 'slow-trickle'
  | 'disconnect'
  | 'not-found'
  | 'auth-failure'
  | 'connection-limit'
  | 'redirect-chain'
  | 'non-ts-bytes'
  | 'xc-auth-envelope'
  | 'no-tv-archive'
  | 'catchup-layout-404'
  | 'range-unsupported';

export interface FaultOptions {
  channel?: number;
  rate?: number;
  clean?: boolean;
  afterBytes?: number;
  /**
   * Required to arm `catchup-layout-404` — rejected with a 400 naming
   * `'layout'` if missing or not `'path'`/`'query'`. Not required to clear
   * it (a value given to clear must still be valid). Rejected on every
   * other fault.
   */
  layout?: 'path' | 'query';
  depth?: number;
}

export interface FaultResult {
  fault: FaultName;
  active: boolean;
  /**
   * How many *live* connections the fault reached. Nine of the twelve
   * faults can only affect the next request — headers are already sent on
   * an open response — so 0 is correct and expected for them: the original
   * five (`not-found`, `auth-failure`, `connection-limit`, `redirect-chain`,
   * `non-ts-bytes`) plus all four G8 additions (`xc-auth-envelope`,
   * `no-tv-archive`, `catchup-layout-404`, `range-unsupported`), none of
   * which act on an open long-lived stream — `player_api.php`, catalogue
   * listing, catch-up and VOD are all single-shot requests. Arming
   * `not-found` for a reconnect that has not happened yet is a normal test.
   * Assert on this value when your test means to disrupt something already
   * streaming; do not assume it is always positive.
   */
  appliedTo: number;
}

export interface UpstreamChannel {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
  /**
   * Optional — mirrors the provider's `ChannelSpec.categoryId` (G8 task 1).
   * When omitted, the provider defaults it to the scenario's first declared
   * live category. Kept optional rather than required: making it required
   * would break the channel literals already committed in
   * `e2e/tests/seeded/upstream-ingest.spec.ts`, which predate categories.
   */
  categoryId?: number;
}

/** Fields every scenario request carries, XC or not. */
interface ScenarioRequestBase {
  channels?: number | UpstreamChannel[];
  maxConnections?: number;
  rate?: number;
}

/**
 * A plain scenario — no XC surface. Deliberately does **not** offer
 * `liveCategories`/`vodCategories`/`seriesCategories`/`vod`/`series`/`account`:
 * the provider serves none of them without `xc: true` (`server.ts`'s
 * `!scenario.xc` guard 404s every `/s/<id>/…` XC route by name, naming the
 * omission), so a request that could declare a full catalogue here would
 * compile, echo that catalogue back on the created `UpstreamScenario`
 * looking entirely correct, and only fail once a test actually drove the XC
 * surface — the exact silent-no-op shape this fixture exists to prevent.
 * Making the combination unrepresentable, rather than validating it at the
 * door, closes it at compile time instead of at first use.
 */
export interface NonXcScenarioRequest extends ScenarioRequestBase {
  xc?: false;
  username?: string;
  password?: string;
}

/**
 * An Xtream Codes scenario (G8 task 1). `xc: true` is the discriminant that
 * unlocks the catalogue fields below. `username`/`password` are **required**
 * here, not optional — the provider's own door (`scenario.ts`) rejects
 * `xc: true` with only one of the two, for the same reason `seed.xcAccount`
 * throws rather than falling back to `null`/`''`: an XC provider with no
 * credentials would authenticate every request vacuously, and an empty
 * password can never match the `/live/` path form.
 */
export interface XcScenarioRequest extends ScenarioRequestBase {
  xc: true;
  username: string;
  password: string;
  liveCategories?: UpstreamCategory[];
  vodCategories?: UpstreamCategory[];
  seriesCategories?: UpstreamCategory[];
  vod?: number | UpstreamMovie[];
  series?: number | UpstreamSeries[];
  /**
   * Raw overrides merged into the XC `player_api.php` handshake's
   * `user_info`/`server_info` objects (G8 task 1). No fixture reads this —
   * it exists only to let a test declare a garbage `exp_date`/`timezone` on
   * the account envelope. Left as a pass-through `Record`, not a named
   * type, for the same reason: nothing here has a use for its contents yet.
   */
  account?: { userInfo?: Record<string, unknown>; serverInfo?: Record<string, unknown> };
}

export type ScenarioRequest = NonXcScenarioRequest | XcScenarioRequest;

export interface UpstreamScenario {
  id: string;
  /** Origin Dispatcharr resolves. Hand these URLs to the product. */
  internal: string;
  /** Origin Playwright resolves. Hand these to fetch/streamClient. */
  control: string;
  credentialQuery: string;
  channels: UpstreamChannel[];
  /**
   * Echoed by the provider and typed here because an XC account needs the two
   * values *separately*: `credentialQuery` is the pre-formatted query string,
   * which is exactly what an XC `server_url` must not carry (the product's
   * `normalize_server_url` strips the query, so they would silently vanish).
   *
   * As `e2e-upstream/README.md` already warns for `credentialQuery`, these are
   * not secret from the control API or from an attached test report. They are
   * per-test throwaways; do not reuse a meaningful credential here.
   */
  username?: string;
  password?: string;
  liveCategories: UpstreamCategory[];
  vodCategories: UpstreamCategory[];
  seriesCategories: UpstreamCategory[];
  vod: UpstreamMovie[];
  series: UpstreamSeries[];
}

export interface LogEntry {
  at: string;
  kind: 'request' | 'open' | 'close' | 'fault';
  method?: string;
  path?: string;
  status?: number;
  channelId?: number;
  bytes?: number;
  durationMs?: number;
  fault?: string;
  detail?: string;
}

/**
 * The single most common mistake a test author makes with this fixture is
 * running the suite without first bringing up the fake provider — and
 * without this, the failure that produces is a bare `TypeError: fetch
 * failed`, from a fixture whose entire purpose is making failures legible.
 * Mirrors `stream-client.ts`'s `describeFetchFailure`: name what's known,
 * fall through to a generic message for anything not confidently
 * identifiable rather than mislabelling it.
 */
/** Trailing slashes break every `base + '/path'` concatenation below. */
function stripTrailingSlash(base: string): string {
  return base.replace(/\/+$/, '');
}

function describeControlFetchFailure(controlBase: string, cause: unknown): string {
  const code = (cause as { cause?: { code?: string } })?.cause?.code;

  if (code === 'ECONNREFUSED') {
    return (
      `upstream control fetch failed: nothing is listening at ${controlBase}. ` +
      `The fake upstream provider isn't running — start it (and Dispatcharr) ` +
      `with ./scripts/e2e_up.sh.`
    );
  }
  if (code === 'ENOTFOUND' || code === 'EAI_AGAIN') {
    return (
      `upstream control fetch failed: cannot resolve the host in ${controlBase}. ` +
      `E2E_UPSTREAM_CONTROL_URL is likely misconfigured — the default, ` +
      `http://127.0.0.1:9402, needs no override for the local topology ` +
      `scripts/e2e_up.sh brings up.`
    );
  }
  return `upstream control fetch failed against ${controlBase}: ${String(cause)}`;
}

export class UpstreamClient {
  readonly created: UpstreamScenario[] = [];

  private readonly controlBase: string;
  private readonly internalBase: string;

  constructor(
    controlBase: string = UPSTREAM_CONTROL_BASE,
    /** Overridable for tests; production callers always take the default. */
    internalBase: string = UPSTREAM_INTERNAL_BASE
  ) {
    // Normalised here rather than at each use site, because *both* consumers
    // concatenate a '/'-prefixed path onto these: `call()` builds
    // `${controlBase}${path}` and `toControl()` builds
    // `controlBase + parsed.pathname`. A trailing slash therefore yields
    // '//scenarios', which is a *scheme-relative* URL — the provider's
    // `new URL(req.url, 'http://placeholder')` reads host 'scenarios' and
    // path '/', so every route 404s with a message pointing at the provider
    // rather than at the misconfigured E2E_UPSTREAM_CONTROL_URL.
    this.controlBase = stripTrailingSlash(controlBase);
    this.internalBase = stripTrailingSlash(internalBase);
  }

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.controlBase}${path}`, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      });
    } catch (cause) {
      throw new Error(describeControlFetchFailure(this.controlBase, cause), { cause });
    }
    if (!res.ok) {
      throw new Error(
        `upstream control ${init?.method ?? 'GET'} ${path} failed: ` +
          `${res.status} ${res.statusText} — ${await res.text()}`
      );
    }
    return (await res.json()) as T;
  }

  async scenario(request: ScenarioRequest = {}): Promise<UpstreamScenario> {
    const scenario = await this.call<UpstreamScenario>('/scenarios', {
      method: 'POST',
      body: JSON.stringify(request),
    });
    // The provider echoes `control` from the request's Host header, which is
    // the base this client used — so it already points at the published port.
    this.created.push(scenario);
    return scenario;
  }

  fault(
    scenario: UpstreamScenario,
    fault: FaultName,
    options: FaultOptions = {}
  ): Promise<FaultResult> {
    return this.call<FaultResult>(`/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault, active: true, ...options }),
    });
  }

  clearFault(
    scenario: UpstreamScenario,
    fault: FaultName,
    options: FaultOptions = {}
  ): Promise<FaultResult> {
    return this.call<FaultResult>(`/s/${scenario.id}/fault`, {
      method: 'POST',
      body: JSON.stringify({ fault, active: false, ...options }),
    });
  }

  rate(scenario: UpstreamScenario, rate: number): Promise<{ rate: number }> {
    return this.call(`/s/${scenario.id}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rate }),
    });
  }

  log(scenario: UpstreamScenario): Promise<LogEntry[]> {
    return this.call<LogEntry[]>(`/s/${scenario.id}/log`);
  }

  connections(
    scenario: UpstreamScenario
  ): Promise<{ live: number; maxConnections: number | null; channels: number[] }> {
    return this.call(`/s/${scenario.id}/connections`);
  }

  playlistUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/playlist.m3u${scenario.credentialQuery}`;
  }

  epgUrl(scenario: UpstreamScenario): string {
    return `${scenario.internal}/epg.xml${scenario.credentialQuery}`;
  }

  // Mirrored by Seeder.upstreamStreamUrl() (private, in seed.ts) — that
  // duplicate exists only because importing UpstreamClient there would
  // create a fixture cycle. Keep both in sync if this shape changes.
  streamUrl(scenario: UpstreamScenario, channelId: number): string {
    return `${scenario.internal}/stream/${channelId}.ts${scenario.credentialQuery}`;
  }

  /**
   * Rewrites a container-internal upstream URL to one the Playwright host can
   * reach.
   *
   * Needed because `validate_stream_url()` follows redirects server-side but
   * returns the URL it was *given*, and `views.py` then 302s the client to
   * that — i.e. to `http://e2e-upstream:8080/...`, a name that resolves only
   * inside the Docker network. A Redirect-profile test therefore opens with
   * `redirect: 'manual'`, reads `Location`, and walks the chain itself,
   * passing each hop through here.
   *
   * Throws rather than returning the input unchanged: silently passing an
   * unrecognised URL through is how a test ends up making a real outbound
   * request to whatever the URL happens to name.
   *
   * Compares parsed *origins*, not string prefixes: `startsWith` would let
   * `http://e2e-upstream:8080@evil.com/x` through — a string prefix of the
   * internal base, but an entirely different origin once `@` is read as a
   * userinfo separator — and would mishandle a trailing slash on the
   * configured base by dropping the leading `/` of the rewritten path.
   * `toControl()` throwing on anything unrecognised is a safety property (a
   * test must never be able to accidentally make a real outbound request to
   * whatever a URL happens to name), so it has to hold structurally rather
   * than by luck of how the strings happen to line up.
   */
  toControl(url: string): string {
    const internalOrigin = new URL(this.internalBase).origin;
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      throw new Error(`toControl() expected a URL under ${this.internalBase}, got ${url}`);
    }
    if (parsed.origin !== internalOrigin) {
      throw new Error(`toControl() expected a URL under ${this.internalBase}, got ${url}`);
    }
    return this.controlBase + parsed.pathname + parsed.search + parsed.hash;
  }

  /**
   * Attaches every scenario's log to the report. Called by the fixture on
   * failure. Each scenario's fetch is wrapped separately: if the provider is
   * unreachable — plausible exactly when a test just failed for a
   * provider-side reason — this must attach a note explaining that rather
   * than throw during teardown, which would bury the test's real failure
   * under an unrelated one.
   */
  async attachLogs(testInfo: TestInfo): Promise<void> {
    for (const scenario of this.created) {
      let body: string;
      let contentType = 'application/json';
      try {
        body = JSON.stringify(await this.log(scenario), null, 2);
      } catch (error) {
        body = `could not retrieve upstream log for ${scenario.id}: ${String(error)}`;
        contentType = 'text/plain';
      }
      await testInfo.attach(`upstream-log-${scenario.id}`, { body, contentType });
    }
  }
}
