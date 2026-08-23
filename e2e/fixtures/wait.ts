import type { ApiClient } from './api';

export type WaitOptions = {
  timeoutMs?: number;
  intervalMs?: number;
  description?: string;
};

/**
 * REST polling. The default way to wait for Celery-backed work: the HTTP call
 * that triggers it returns 200 immediately and completes much later.
 */
export class Waiter {
  constructor(private api: ApiClient) {}

  async condition(
    predicate: () => Promise<boolean>,
    { timeoutMs = 60_000, intervalMs = 1_000, description = 'condition' }: WaitOptions = {}
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

    throw new Error(
      `timed out after ${timeoutMs}ms waiting for ${description}` +
        (lastError ? ` (last error: ${lastError})` : '')
    );
  }

  async resource<T = any>(
    url: string,
    predicate: (body: T) => boolean,
    options: WaitOptions = {}
  ): Promise<T> {
    let latest: T | undefined;

    await this.condition(
      async () => {
        const res = await this.api.get(url);
        if (!res.ok()) return false;
        latest = await res.json();
        return predicate(latest as T);
      },
      { description: `${url} to satisfy predicate`, ...options }
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
