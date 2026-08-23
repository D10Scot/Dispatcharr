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

/** `M3UAccount.Status` values a refresh passes through while it is running. */
const M3U_IN_FLIGHT_STATUSES = ['fetching', 'parsing'];

/** `M3UAccount.Status` values a finished refresh comes to rest in. */
const M3U_TERMINAL_STATUSES = ['success', 'error'];

export type M3uRefreshWaitOptions = WaitOptions & {
  /**
   * Budget for the refresh to *start*, separate from `timeoutMs`, which
   * budgets the (much longer) fetch and parse.
   */
  startTimeoutMs?: number;
};

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

  /**
   * An M3U account whose most recent refresh has both **started** and
   * **finished**. Call it after triggering the refresh.
   *
   * Two phases, because one is not enough:
   *
   * 1. **Started** — wait for `fetching` or `parsing`, the two statuses
   *    `apps/m3u/tasks.py` treats as in-flight (`_NON_TERMINAL_REFRESH_STATUSES`).
   *    `POST /api/m3u/refresh/<id>/` only queues the Celery task and returns
   *    202 immediately (`apps/m3u/api_views.py`, `RefreshSingleM3UAPIView`);
   *    the status changes to `fetching` inside the worker. So the first poll
   *    of a single-phase wait sees the *pre-refresh* status — `idle`, or
   *    `pending_setup` on a freshly created account — and reports a refresh
   *    that has not begun as complete. This phase has its own budget
   *    (`startTimeoutMs`) so a refresh that never runs at all — no Celery
   *    worker, or the task lock still held by an earlier refresh — fails
   *    saying exactly that instead of consuming the whole timeout.
   * 2. **Finished** — wait for `success` or `error`, asserted positively
   *    rather than as "not in flight". The task's `finally` calls
   *    `_ensure_m3u_refresh_terminal_status`, which forces `error` if it
   *    exits still in flight, so one of the two always arrives. `error`
   *    resolves this wait: the refresh finished, and whether it *succeeded*
   *    is the caller's assertion to make, not the waiter's.
   *
   * `timeoutMs` bounds phase 2; `startTimeoutMs` bounds phase 1. The trade
   * for never passing early: a refresh that starts and finishes entirely
   * within one poll interval would fail phase 1. No real fetch-and-parse
   * does, and phase 1 polls four times as fast as the default to shrink that
   * window further.
   */
  async m3uRefreshComplete(
    accountId: number,
    { startTimeoutMs = 30_000, ...options }: M3uRefreshWaitOptions = {}
  ) {
    const url = `/api/m3u/accounts/${accountId}/`;

    await this.resource(
      url,
      (body: any) => M3U_IN_FLIGHT_STATUSES.includes(body.status),
      {
        description:
          `M3U account ${accountId} refresh to start ` +
          `(status ${M3U_IN_FLIGHT_STATUSES.join(' or ')})`,
        timeoutMs: startTimeoutMs,
        intervalMs: 250,
      }
    );

    return this.resource(
      url,
      (body: any) => M3U_TERMINAL_STATUSES.includes(body.status),
      {
        description:
          `M3U account ${accountId} refresh to finish ` +
          `(status ${M3U_TERMINAL_STATUSES.join(' or ')})`,
        timeoutMs: 180_000,
        ...options,
      }
    );
  }
}
