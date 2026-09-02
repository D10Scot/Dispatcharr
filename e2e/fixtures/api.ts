import type { APIRequestContext, APIResponse } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { hasLifeLeft, refreshAccessToken } from '../setup/login';
import type { TokenPair } from '../setup/login';
import { AUTH_DIR, writeAuthFileAtomically } from '../setup/auth-files';

const TOKENS_FILE = path.join(AUTH_DIR, 'tokens.json');

/**
 * A Playwright `multipart` value: a plain form field, or a file part built
 * from an in-memory buffer (no fixture file on disk is required).
 *
 * Narrower than Playwright's own multipart value type, which also accepts
 * `number`, `boolean` and `fs.ReadStream`. Deliberate, not an oversight: every
 * caller here is a small in-memory field or file, the product caps uploads at
 * 5MB (`dispatcharr/utils.py:56-57`) so a `Buffer` is always cheap enough, and
 * a numeric field costs nothing more than `String()` at the call site. Widen
 * this for a native number/boolean part, but not for a stream:
 * `fetchWithRefresh()` replays the request by calling the options factory
 * again on a 401, and a once-consumed `fs.ReadStream` would replay as an
 * empty part — a stream needs a re-openable factory, not a handle.
 */
export type MultipartValue =
  | string
  | { name: string; mimeType: string; buffer: Buffer };

/**
 * What `bootstrap` writes to `tokens.json`: the admin's pair, beside the
 * credentials that minted it (`{ access, refresh, ...ADMIN }`).
 *
 * The credential fields are optional because a client handed a pair directly
 * has none — and never needs them. Nothing here reads them; they are carried so
 * `persistTokens()` writes the file back whole rather than truncating it to the
 * pair, and that path only runs for the client that read the file.
 */
type Tokens = TokenPair & {
  username?: string;
  password?: string;
  email?: string;
};

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
  private persistsTokens: boolean;

  /**
   * With no `tokens`, this is the bootstrap admin's client and the pair comes
   * from `tokens.json` — which requires `bootstrap` to have run.
   *
   * Pass a pair to build a client for anybody else **without** that
   * requirement. `fixtures/auth.ts` documents that a project with no
   * `dependencies: ['bootstrap']` can still call `makeUserClient`, and
   * `loadPrincipals()` is lazy specifically to keep that true — but an
   * unconditional read here made the constructor throw `ENOENT` in exactly that
   * case, before the freshly-minted pair could be installed. The contract and
   * the code now agree.
   *
   * A client holding a pair it was handed never writes `tokens.json`: that file
   * describes the admin, and persisting another principal's token into it would
   * silently run the rest of the suite as them.
   */
  constructor(private ctx: APIRequestContext, tokens?: TokenPair) {
    if (tokens) {
      this.tokens = { ...tokens };
      this.persistsTokens = false;
    } else {
      this.tokens = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
      this.persistsTokens = true;
    }
  }

  /** Test hook: corrupt the access token so the next call takes the 401 path. */
  expireAccessTokenForTest(): void {
    this.tokens.access = 'expired.invalid.token';
  }

  /**
   * Test hook: the raw refresh token this client holds. Only issue #12's
   * regression test needs it — it must present a refresh token to the
   * endpoint directly, after deleting the user it names.
   */
  freshRefreshTokenForTest(): string {
    return this.tokens.refresh;
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
    if (!hasLifeLeft(this.tokens.access)) {
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
    // The narrowing lives in `refreshAccessToken` — a 200 carrying no string
    // `access` comes back as a failure rather than installing
    // `Bearer undefined` on this client and surfacing as 401s from every later
    // call. On the worker side a miss is fatal: unlike the setup paths, there
    // is no login to fall back to inside the throttle budget.
    const result = await refreshAccessToken(this.ctx, this.tokens.refresh);
    if (result.access === undefined) {
      throw new Error(
        result.status === 200
          ? 'token refresh returned 200 with no string `access` field; the ' +
            `refresh endpoint answered something unexpected: ${result.detail}`
          : `token refresh failed: ${result.status} ${result.detail}`
      );
    }
    this.tokens.access = result.access;
    this.persistTokens();
  }

  /**
   * Issue a request built by `options`, refreshing and retrying once on 401.
   * `options` is a factory rather than a value because it is called again
   * after `refresh()` picks up a new access token — a plain value would
   * retry with the same stale header. Shared by `send()` and `upload()` so
   * the two request shapes cannot drift on refresh semantics; each builds
   * its own options because a JSON body (`data`) and a multipart body
   * (`multipart`) are different, mutually exclusive `fetch()` options.
   */
  private async fetchWithRefresh(
    url: string,
    options: () => Parameters<APIRequestContext['fetch']>[1]
  ): Promise<APIResponse> {
    let res = await this.ctx.fetch(url, options());
    if (res.status() === 401) {
      await this.refresh();
      res = await this.ctx.fetch(url, options());
    }
    return res;
  }

  private async send(
    method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
    url: string,
    data?: unknown
  ): Promise<APIResponse> {
    return this.fetchWithRefresh(url, () => ({
      method,
      headers: { Authorization: `Bearer ${this.tokens.access}` },
      ...(data === undefined ? {} : { data }),
    }));
  }

  /**
   * A `multipart/form-data` POST. `LogoViewSet` is the only *viewset* that
   * declares `MultiPartParser`; the product has two other multipart write
   * paths, both non-viewset — `ComskipConfigAPIView`
   * (`apps/channels/api_views.py:3949`) and `upload_backup`
   * (`apps/backups/api_views.py:259`) — so this helper already has two more
   * potential callers, not zero.
   *
   * A separate method from `send()`, not a special case inside it: Playwright's
   * `multipart` is a distinct `fetch()` option from `data`, mutually exclusive
   * with it, so the two need their own options factories. Both factories go
   * through the same `fetchWithRefresh()`, so this still gets the 401 retry
   * every other call path gets.
   */
  async upload(
    url: string,
    multipart: Record<string, MultipartValue>
  ): Promise<APIResponse> {
    return this.fetchWithRefresh(url, () => ({
      method: 'POST' as const,
      headers: { Authorization: `Bearer ${this.tokens.access}` },
      multipart,
    }));
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
  /**
   * `data` matters here: `DELETE /api/channels/channels/bulk-delete/` carries
   * `channel_ids` in the body
   * (`apps/channels/api_views.py:BulkDeleteChannelsAPIView.delete`). Routing
   * that through a raw `ctx.fetch()` call instead would lose `ApiClient`'s
   * 401 refresh-and-retry. Backward compatible — every existing caller passes
   * one argument.
   */
  delete(url: string, data?: unknown) {
    return this.send('DELETE', url, data);
  }

  /**
   * JSON body of a call asserted to have succeeded.
   *
   * `T` defaults to `unknown`, not `any`: this is the harness's single
   * response boundary, and an `any` here would let one caller who forgot the
   * type argument reopen the hole the typed fixtures exist to close. Name the
   * shape — `api.json<Channel>(res, 'read-back')` — or narrow the `unknown`.
   */
  async json<T = unknown>(res: APIResponse, context: string): Promise<T> {
    if (!res.ok()) {
      throw new Error(`${context}: ${res.status()} ${await res.text()}`);
    }
    return res.json();
  }
}
