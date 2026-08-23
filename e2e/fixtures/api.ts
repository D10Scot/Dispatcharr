import type { APIRequestContext, APIResponse } from '@playwright/test';
import fs from 'node:fs';

const TOKENS_FILE = 'playwright/.auth/tokens.json';

type Tokens = {
  access: string;
  refresh: string;
  username: string;
  password: string;
  email: string;
};

/**
 * Authenticated HTTP client. Retries once through a token refresh on 401,
 * because SIMPLE_JWT.ACCESS_TOKEN_LIFETIME is 30 minutes and suites outlive it.
 */
export class ApiClient {
  private tokens: Tokens;

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
    this.tokens.access = (await res.json()).access;
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
