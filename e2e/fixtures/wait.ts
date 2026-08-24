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
   * Budget for the refresh to *engage* — either observed in flight, or
   * (see the method doc comment) inferred from a terminal status that has
   * genuinely changed since the pre-trigger baseline. Separate from
   * `timeoutMs`, which budgets a refresh already confirmed to be running.
   */
  startTimeoutMs?: number;
  /**
   * How the refresh is triggered. Defaults to
   * `POST /api/m3u/refresh/<accountId>/` (`RefreshSingleM3UAPIView`), the
   * only trigger this harness needs today. Override when a test drives the
   * refresh some other way (a UI click, say) and still wants to wait on it
   * here: whatever you pass runs *after* the baseline read below, which is
   * what closes the race the method doc comment describes — the baseline
   * must happen-before the trigger, and only this method can guarantee
   * that ordering.
   */
  trigger?: () => Promise<unknown>;
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
   * Triggers an M3U account refresh and waits for it to both **start** and
   * **finish**. This method owns the trigger (see `trigger` on
   * `M3uRefreshWaitOptions`) — call it instead of POSTing the refresh
   * yourself, so the pre-trigger baseline read below always happens first.
   *
   * Two phases, because one is not enough, plus a fallback for when even
   * two isn't:
   *
   * 1. **Started** — wait for `fetching` or `parsing`, the two statuses
   *    `apps/m3u/tasks.py` treats as in-flight (`_NON_TERMINAL_REFRESH_STATUSES`).
   *    `POST /api/m3u/refresh/<id>/` only queues the Celery task and returns
   *    202 immediately (`apps/m3u/api_views.py`, `RefreshSingleM3UAPIView`);
   *    the status changes to `fetching` inside the worker. So a naive
   *    single-phase wait can see the *pre-refresh* status — `idle`, or
   *    `pending_setup` on a freshly created account — on its first poll and
   *    report a refresh that has not begun as complete. This phase has its
   *    own budget (`startTimeoutMs`) so a refresh that never runs at all
   *    fails saying exactly that instead of consuming the whole timeout.
   *    The likeliest cause of that in this harness: the account is
   *    inactive. `_get_active_m3u_account()` (`apps/m3u/tasks.py`) queries
   *    `is_active=True` and raises `DoesNotExist` before the status is ever
   *    set to `fetching` — caught inside `_refresh_single_m3u_account_impl`,
   *    which logs "not found or inactive" and returns without raising, so
   *    the status is left exactly where it started (`idle`/`pending_setup`)
   *    and *never* reaches `fetching`/`parsing` **or** `error`:
   *    `_ensure_m3u_refresh_terminal_status`'s force-to-`error` only fires
   *    when the status is still in `_NON_TERMINAL_REFRESH_STATUSES`, which a
   *    never-started refresh never was — and the fallback below never fires
   *    either, since the status never changes from the baseline at all.
   *    Both phases would hang forever, not just this one.
   *    `seed.m3uAccount()` and `seed.epgSource()` both default to
   *    `is_active: false` — pass `{ is_active: true }` when seeding an
   *    account you intend to refresh. Other causes: no Celery worker, or the
   *    task lock still held by an earlier refresh.
   * 2. **Finished** — wait for `success` or `error`, asserted positively
   *    rather than as "not in flight". The task's `finally` calls
   *    `_ensure_m3u_refresh_terminal_status`, which forces `error` if it
   *    exits still in flight, so one of the two always arrives. `error`
   *    resolves this wait: the refresh finished, and whether it *succeeded*
   *    is the caller's assertion to make, not the waiter's.
   *
   * **The fallback, and why it exists.** A fast enough failure — a
   * dead-port connect refusal, say — can transit `fetching` -> `error`
   * between two 250ms polls, so phase 1 never observes the in-flight status
   * at all. A version of this method that only implemented phases 1 and 2
   * above would burn the *entire* `startTimeoutMs` budget waiting for
   * something that already happened, then report a start-timeout for a
   * refresh that in fact ran and failed.
   *
   * The fix is not comparing `updated_at`, even though that reads like the
   * obvious fresh-since-baseline signal: `apps/m3u/tasks.py` only bumps it
   * on the success path (search the file for `account.updated_at =`, one
   * hit, right before the terminal `save(update_fields=[..., "updated_at"])`
   * near the end of `_refresh_single_m3u_account_impl`). Every error path —
   * `fetch_m3u_lines`'s several `account.save(update_fields=["status",
   * "last_message"])` calls, `_set_m3u_account_status`, and
   * `_ensure_m3u_refresh_terminal_status`'s forced-error `.update(...)` —
   * never lists `updated_at`, and `M3UAccount.save()`
   * (`apps/m3u/models.py:141-153`) deliberately strips `updated_at` from
   * `update_fields` unless it's explicitly present ("Prevent auto_now
   * behavior by handling updated_at manually"). A fast failure — exactly
   * the case this fallback exists for — never advances it at all.
   *
   * Instead: phase 1 also accepts a **terminal status that differs from a
   * baseline read strictly before the trigger fires** (`status` changing at
   * all, or `last_message` changing — the latter mostly redundant since
   * `status` alone already flips `idle`/`pending_setup` -> `error` on a
   * fresh account, but cheap insurance against a re-refresh landing on the
   * same status). That baseline read is why this method must own the
   * trigger: reading it *inside* the method but after an *externally*
   * triggered refresh would race that refresh — on a fast enough failure,
   * the "baseline" read could itself land after completion, making the
   * diff-check compare a post-refresh state against itself and never fire.
   * The one gap this doesn't close: re-triggering a refresh on an account
   * already sitting in the exact same terminal status from an earlier,
   * unrelated failure, where the new attempt fails with byte-identical
   * status *and* `last_message`. No REST-polling fix closes that — there is
   * no monotonic completion marker in the product for the error path — and
   * it's narrow enough (identical failure, twice, back to back) not to be
   * worth a bigger contract change for.
   *
   * `timeoutMs` bounds phase 2; `startTimeoutMs` bounds phase 1 (including
   * the fallback above — both are checked on the same poll). The trade for
   * never passing early: a refresh that starts and finishes entirely within
   * one poll interval, without the fallback catching it (i.e. it happens to
   * land back on its own baseline status), would fail phase 1. No real
   * fetch-and-parse does, and phase 1 polls four times as fast as the
   * default to shrink that window further.
   */
  async m3uRefreshComplete(
    accountId: number,
    { startTimeoutMs = 30_000, trigger, ...options }: M3uRefreshWaitOptions = {}
  ) {
    const url = `/api/m3u/accounts/${accountId}/`;

    const baselineRes = await this.api.get(url);
    const baseline = await this.api.json<any>(
      baselineRes,
      `m3uRefreshComplete baseline read for account ${accountId}`
    );

    await (trigger ?? (() => this.api.post(`/api/m3u/refresh/${accountId}/`, {})))();

    let sawInFlight = false;

    const firstObserved = await this.resource(
      url,
      (body: any) => {
        if (M3U_IN_FLIGHT_STATUSES.includes(body.status)) {
          sawInFlight = true;
          return true;
        }
        return (
          M3U_TERMINAL_STATUSES.includes(body.status) &&
          (body.status !== baseline.status || body.last_message !== baseline.last_message)
        );
      },
      {
        description:
          `M3U account ${accountId} refresh to start ` +
          `(status ${M3U_IN_FLIGHT_STATUSES.join(' or ')}, or a terminal status ` +
          `that differs from its pre-trigger baseline of '${baseline.status}')`,
        timeoutMs: startTimeoutMs,
        intervalMs: 250,
      }
    );

    if (!sawInFlight) {
      // The fallback above already proved this terminal status is the
      // trigger's own outcome — no second poll needed.
      return firstObserved;
    }

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
