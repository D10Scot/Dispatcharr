import { expect } from '@playwright/test';
import { StreamClient } from '../../fixtures';
import type { ApiClient, StreamProfile } from '../../fixtures';

/** Find a locked built-in Stream Profile by name. Never assert on a count. */
export async function lockedProfile(api: ApiClient, name: string): Promise<StreamProfile> {
  const page = await api.json<{ results?: StreamProfile[] } | StreamProfile[]>(
    await api.get('/api/core/streamprofiles/'),
    'stream profiles'
  );
  const all = Array.isArray(page) ? page : (page.results ?? []);
  const found = all.find((p) => p.name === name);
  expect(found, `the locked "${name}" stream profile should ship`).toBeDefined();
  return found!;
}

/**
 * A second, third, ... StreamClient. The `streamClient` fixture provides
 * exactly one per test; rows that assert on upstream *sharing* need several.
 * The caller owns closing each one.
 */
export function newStreamClient(): StreamClient {
  return new StreamClient(process.env.E2E_BASE_URL ?? 'http://localhost:9191');
}
