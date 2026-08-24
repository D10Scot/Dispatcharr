import type { APIRequestContext, APIResponse } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { accessTokenOf } from '../setup/login';
import { AUTH_DIR, writeAuthFileAtomically } from '../setup/auth-files';

const TOKENS_FILE = path.join(AUTH_DIR, 'tokens.json');

/**
 * How close to `exp` an access token may be before `freshAccessToken()`
 * refreshes it. Generous: a refresh costs nothing (TokenRefreshView is not
 * throttled) and a token that expires mid-test costs a 30-second hang.
 */
const TOKEN_EXPIRY_MARGIN_SECONDS = 120;

type Tokens = {
  access: string;
  refresh: string;
  username: string;
  password: string;
  email: string;
};

/** The `exp` claim in unix seconds, or undefined if this isn't a readable JWT. */
function jwtExp(accessToken: string): number | undefined {
  try {
    const payload = accessToken.split('.')[1];
    const exp = JSON.parse(Buffer.from(payload, 'base64').toString('utf8')).exp;
    return typeof exp === 'number' ? exp : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Authenticated HTTP client. Retries once through a token refresh on 401,
 * because SIMPLE_JWT.ACCESS_TOKEN_LIFETIME is 30 minutes and suites outlive it.
 */
export class ApiClient {
  private tokens: Tokens;
  /**
   * Whether a refreshed access token is written back to `tokens.json`.
   *
   * True only while this client still holds the bootstrap admin's pair, i.e.
   * the pair that file describes. `useTokens()` re-points a client at another
   * principal, and writing *that* principal's token into the file the whole
   * suite reads would silently run everything as them.
   */
  private persistsTokens = true;

  constructor(private ctx: APIRequestContext) {
    this.tokens = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
  }

  /** Test hook: corrupt the access token so the next call takes the 401 path. */
  expireAccessTokenForTest(): void {
    this.tokens.access = 'expired.invalid.token';
  }

  /** Re-point this client at a different principal's tokens. */
  useTokens(tokens: { access: string; refresh: string }): void {
    this.tokens = { ...this.tokens, ...tokens };
    this.persistsTokens = false;
  }

  /**
   * An access token guaranteed to have life left in it, refreshing first if
   * it doesn't. For handing to a reader that cannot refresh on its own —
   * `WsListener`, whose auth is a query parameter fixed at connect time.
   */
  async freshAccessToken(): Promise<string> {
    const exp = jwtExp(this.tokens.access);
    if (exp === undefined || exp - TOKEN_EXPIRY_MARGIN_SECONDS <= Date.now() / 1000) {
      await this.refresh();
    }
    return this.tokens.access;
  }

  /**
   * Persist the current pair, so every *other* reader of this file — the next
   * `ws` fixture, and the next run's bootstrap reuse check — sees a live
   * access token rather than the bootstrap one from up to 30 minutes ago.
   * Written through a temp file and renamed: parallel workers refresh
   * concurrently, and a reader must never catch a half-written file. The temp
   * name carries the pid so two workers don't collide on it, and the file
   * lands at 0600 — see `setup/auth-files.ts`.
   */
  private persistTokens(): void {
    if (!this.persistsTokens) return;
    try {
      writeAuthFileAtomically(
        TOKENS_FILE,
        JSON.stringify(this.tokens, null, 2) + os.EOL
      );
    } catch {
      // Best-effort: a client that refreshed in memory is still usable, and
      // failing a test over an unwritable auth directory would be a worse
      // outcome than the staleness this write-back exists to avoid.
    }
  }

  private async refresh(): Promise<void> {
    const res = await this.ctx.post('/api/accounts/token/refresh/', {
      data: { refresh: this.tokens.refresh },
    });
    if (!res.ok()) {
      throw new Error(
        `token refresh failed: ${res.status()} ${await res.text()}`
      );
    }
    // Narrowed rather than destructured off `any`: a 200 carrying no string
    // `access` would otherwise install `Bearer undefined` on this client and
    // surface as 401s from every later call.
    const access = accessTokenOf(await res.json());
    if (access === undefined) {
      throw new Error(
        'token refresh returned 200 with no string `access` field; the ' +
          'refresh endpoint answered something unexpected.'
      );
    }
    this.tokens.access = access;
    this.persistTokens();
  }

  private async send(
    method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
    url: string,
    data?: unknown
  ): Promise<APIResponse> {
    const options = () => ({
      method,
      headers: { Authorization: `Bearer ${this.tokens.access}` },
      ...(data === undefined ? {} : { data }),
    });

    let res = await this.ctx.fetch(url, options());
    if (res.status() === 401) {
      await this.refresh();
      res = await this.ctx.fetch(url, options());
    }
    return res;
  }

  get(url: string) {
    return this.send('GET', url);
  }
  post(url: string, data: unknown) {
    return this.send('POST', url, data);
  }
  patch(url: string, data: unknown) {
    return this.send('PATCH', url, data);
  }
  delete(url: string) {
    return this.send('DELETE', url);
  }

  /** JSON body of a call asserted to have succeeded. */
  async json<T = any>(res: APIResponse, context: string): Promise<T> {
    if (!res.ok()) {
      throw new Error(`${context}: ${res.status()} ${await res.text()}`);
    }
    return res.json();
  }
}
