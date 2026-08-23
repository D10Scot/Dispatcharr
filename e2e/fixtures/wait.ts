import type { ApiClient } from './api';

export type WaitOptions = {
  timeoutMs?: number;
  intervalMs?: number;
  description?: string;
  /**
   * Called once, only if the wait times out, to describe the last observed
   * state for the error message. Kept separate from the predicate because
   * `condition()` has no notion of a "state" — only `resource()` does.
   */
  describeLast?: () => string | undefined;
};

const DESCRIBE_LAST_MAX_LENGTH = 300;

function truncate(value: string, maxLength = DESCRIBE_LAST_MAX_LENGTH): string {
  return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
}

/**
 * REST polling. The default way to wait for Celery-backed work: the HTTP call
 * that triggers it returns 200 immediately and completes much later.
 */
export class Waiter {
  constructor(private api: ApiClient) {}

  async condition(
    predicate: () => Promise<boolean>,
    {
      timeoutMs = 60_000,
      intervalMs = 1_000,
      description = 'condition',
      describeLast,
    }: WaitOptions = {}
  ): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    let lastError: unknown;

    while (Date.now() < deadline) {
      try {
        if (await predicate()) return;
      } catch (error) {
        lastError = error;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    const lastObserved = describeLast?.();
    throw new Error(
      `timed out after ${timeoutMs}ms waiting for ${description}` +
        (lastObserved ? ` (last observed: ${lastObserved})` : '') +
        (lastError ? ` (last error: ${lastError})` : '')
    );
  }

  async resource<T = any>(
    url: string,
    predicate: (body: T) => boolean,
    options: WaitOptions = {}
  ): Promise<T> {
    let latest: T | undefined;
    // Distinct from `latest`: a non-OK response never reaches res.json(), so
    // without this a persistently-failing endpoint describes nothing at
    // timeout — less signal than the not-yet-matching case above it.
    let lastFailure: string | undefined;

    await this.condition(
      async () => {
        const res = await this.api.get(url);
        if (!res.ok()) {
          lastFailure = `HTTP ${res.status()}: ${truncate(await res.text())}`;
          return false;
        }
        lastFailure = undefined;
        latest = await res.json();
        return predicate(latest as T);
      },
      {
        description: `${url} to satisfy predicate`,
        describeLast: () =>
          lastFailure ?? (latest === undefined ? undefined : truncate(JSON.stringify(latest))),
        ...options,
      }
    );

    return latest as T;
  }

  /** An M3U account whose most recent refresh has finished. */
  async m3uRefreshComplete(accountId: number, options: WaitOptions = {}) {
    return this.resource(
      `/api/m3u/accounts/${accountId}/`,
      (body: any) => body.status !== 'fetching' && body.status !== 'parsing',
      { description: `M3U account ${accountId} refresh`, timeoutMs: 180_000, ...options }
    );
  }
}
