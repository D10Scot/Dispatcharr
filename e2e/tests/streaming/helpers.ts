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

/**
 * Race `work` against a timeout so a hang reports a named cause in seconds
 * instead of a project-level `Test timeout of 300000ms exceeded` minutes
 * later. `readPackets` only throws when a stream *ends* — it hangs forever
 * when the stream stays open but stops delivering, which is exactly what a
 * vanished channel post-failover looks like. `ms` should sit comfortably
 * under the calling project's own timeout.
 */
export async function withDeadline<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const guard = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () => reject(new Error(`${what} did not settle within ${ms}ms.`)),
      ms
    );
  });
  try {
    return await Promise.race([work, guard]);
  } finally {
    clearTimeout(timer);
  }
}
