import type { TestInfo } from '@playwright/test';

export const UPSTREAM_CONTROL_BASE =
  process.env.E2E_UPSTREAM_CONTROL_URL ?? 'http://127.0.0.1:9402';

export const UPSTREAM_INTERNAL_BASE =
  process.env.E2E_UPSTREAM_INTERNAL_URL ?? 'http://e2e-upstream:8080';

export type FaultName =
  | 'dead-air'
  | 'slow-trickle'
  | 'disconnect'
  | 'not-found'
  | 'auth-failure'
  | 'connection-limit'
  | 'redirect-chain'
  | 'non-ts-bytes';

export interface FaultOptions {
  channel?: number;
  rate?: number;
  clean?: boolean;
  afterBytes?: number;
  depth?: number;
}

export interface FaultResult {
  fault: FaultName;
  active: boolean;
  /**
   * How many *live* connections the fault reached. Five of the eight faults
   * can only affect the next request — headers are already sent on an open
   * response — so 0 is correct and expected for them. Arming `not-found` for
   * a reconnect that has not happened yet is a normal test. Assert on this
   * value when your test means to disrupt something already streaming; do
   * not assume it is always positive.
   */
  appliedTo: number;
}

export interface UpstreamChannel {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
}

export interface ScenarioRequest {
  channels?: number | UpstreamChannel[];
  username?: string;
  password?: string;
  maxConnections?: number;
  rate?: number;
}

export interface UpstreamScenario {
  id: string;
  /** Origin Dispatcharr resolves. Hand these URLs to the product. */
  internal: string;
  /** Origin Playwright resolves. Hand these to fetch/streamClient. */
  control: string;
  credentialQuery: string;
  channels: UpstreamChannel[];
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

export class UpstreamClient {
  readonly created: UpstreamScenario[] = [];

  constructor(private readonly controlBase: string = UPSTREAM_CONTROL_BASE) {}

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.controlBase}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
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
   */
  toControl(url: string): string {
    if (!url.startsWith(UPSTREAM_INTERNAL_BASE)) {
      throw new Error(
        `toControl() expected a URL under ${UPSTREAM_INTERNAL_BASE}, got ${url}`
      );
    }
    return this.controlBase + url.slice(UPSTREAM_INTERNAL_BASE.length);
  }

  /** Attaches every scenario's log to the report. Called by the fixture on failure. */
  async attachLogs(testInfo: TestInfo): Promise<void> {
    for (const scenario of this.created) {
      await testInfo.attach(`upstream-log-${scenario.id}`, {
        body: JSON.stringify(await this.log(scenario), null, 2),
        contentType: 'application/json',
      });
    }
  }
}
