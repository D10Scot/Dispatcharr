import type { APIRequestContext } from '@playwright/test';
import { ApiClient } from './api';

/**
 * An ApiClient authenticated as an arbitrary user rather than the bootstrap
 * admin. Tokens are held in memory; nothing is written to the auth files.
 */
export async function makeUserClient(
  ctx: APIRequestContext,
  username: string,
  password: string
): Promise<ApiClient> {
  const res = await ctx.post('/api/accounts/token/', {
    data: { username, password },
  });
  if (!res.ok()) {
    throw new Error(
      `login as ${username} failed: ${res.status()} ${await res.text()}`
    );
  }
  const { access, refresh } = await res.json();

  const client = new ApiClient(ctx);
  client.useTokens({ access, refresh });
  return client;
}
