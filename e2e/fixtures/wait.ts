import type { ApiClient } from './api';
import type { EpgSource, M3uAccount, M3uAccountStatus } from './types';

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
const M3U_IN_FLIGHT_STATUSES: readonly M3uAccountStatus[] = ['fetching', 'parsing'];

/** `M3UAccount.Status` values a finished refresh comes to rest in. */
const M3U_TERMINAL_STATUSES: readonly M3uAccountStatus[] = ['success', 'error'];

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
 * How long `epgRefreshComplete()` requires `EPGSource.updated_at` to hold
 * one value, once it has changed from the baseline, before treating it as
 * settled. Chosen as a multiple of the ~165ms+ gap observed in this
 * harness's own container (see that method's doc comment) — a deliberate
 * margin over a measured floor, not a derived bound: the gap it is
 * covering is not itself bounded. See the doc comment for what that means
 * for this constant's reliability.
 */
const EPG_UPDATED_AT_SETTLE_MS = 1_000;

export type EpgRefreshWaitOptions = WaitOptions & {
  /**
   * A read taken strictly *before* the refresh was triggered. Required for the
   * create path: `trigger_refresh_on_new_epg_source` (a `post_save` receiver)
   * fires `refresh_epg_data.delay()` the moment an active non-dummy source is
   * created, so by the time this method could take its own baseline the
   * refresh may already have finished. Pass the create response.
   */
  baseline?: EpgSource;
  /**
   * How the refresh is triggered. Defaults to `POST /api/epg/import/` with
   * `{ id }` — note the id travels in the **body**; there is no
   * `/api/epg/sources/<id>/refresh/` route. Pass `async () => {}` when the
   * refresh has already been started for you (the create path above): a second
   * `/api/epg/import/` finds `refresh_epg_data`'s lock held, returns without
   * touching a single field, and would leave this wait with nothing to see.
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

  /**
   * Polls `url` until its body satisfies `predicate`, and resolves with that
   * body.
   *
   * `T` has no default: the body is whatever that endpoint returns, and
   * inferring `any` let `(body) => body.nmae === x` poll forever against a
   * typo. Supply the response type — `waitFor.resource<Channel>(...)` — and
   * both the predicate and the return value are checked. `unknown` is the
   * honest answer for an endpoint this harness has no type for; narrow it in
   * the predicate.
   */
  async resource<T>(
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
   *    which logs that the account was not found and it is cleaning up an
   *    orphaned task, then returns without raising, so the status is left
   *    exactly where it started (`idle`/`pending_setup`) and *never* reaches
   *    `fetching`/`parsing` **or** `error`:
   *    `_ensure_m3u_refresh_terminal_status`'s force-to-`error` only fires
   *    when the status is still in `_NON_TERMINAL_REFRESH_STATUSES`, which a
   *    never-started refresh never was — and the fallback below never fires
   *    either, since the status never changes from the baseline at all.
   *    Phase 1 still fails cleanly on its own budget (`startTimeoutMs`),
   *    with a timeout error naming the account; phase 2 never starts.
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
   * **A second, distinct gap this closes as of D10Scot/Dispatcharr#59**: a
   * trigger that lands while `refresh_single_m3u_account`'s own task lock
   * from an *immediately preceding* refresh on the same account is still
   * held (`apps/m3u/tasks.py:3345` vs. the `finally`-scoped release at
   * `:3374`, well after the terminal `status` write at `:3865`) is silently
   * dropped — the task discovers the lock held and returns having written
   * nothing, indistinguishable from "not picked up yet". Phase 1 re-fires
   * the trigger every 5s it spends still waiting, which is what actually
   * recovers: by the retry, the earlier refresh has almost always released
   * its lock. This is orthogonal to the identical-back-to-back-failure gap
   * above — that gap is a write that *does* happen but reads the same as the
   * baseline; this one is a trigger that writes nothing at all, and retrying
   * is exactly what a silent no-op needs and a byte-identical failure does
   * not (retrying that just produces the same indistinguishable write again).
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
  ): Promise<M3uAccount> {
    const url = `/api/m3u/accounts/${accountId}/`;

    const baselineRes = await this.api.get(url);
    const baseline = await this.api.json<M3uAccount>(
      baselineRes,
      `m3uRefreshComplete baseline read for account ${accountId}`
    );

    // Extracted so phase 1 below can call it again — see D10Scot/Dispatcharr#59
    // just below.
    const fire = async (): Promise<void> => {
      if (trigger) {
        await trigger();
        return;
      }
      // Checked rather than discarded. `RefreshSingleM3UAPIView` is an
      // unconditional 202 today, so this effectively cannot fire — but a
      // broker-down 500, or a future validation change, would otherwise be
      // invisible: the failure would surface `startTimeoutMs` later as "the
      // refresh never started", naming the account and not the POST that never
      // landed. Only the default trigger can be checked this way — a custom
      // one returns whatever it likes, a UI click returning nothing at all.
      const triggered = await this.api.post(`/api/m3u/refresh/${accountId}/`, {});
      if (!triggered.ok()) {
        throw new Error(
          `triggering the refresh of M3U account ${accountId} failed: ` +
            `${triggered.status()} ${await triggered.text()}. No refresh was ` +
            'queued, so there was nothing to wait for.'
        );
      }
    };

    await fire();

    let sawInFlight = false;
    // D10Scot/Dispatcharr#59: `refresh_single_m3u_account` only releases its
    // Redis task lock in a `finally` (`apps/m3u/tasks.py:3374`), well after
    // `_refresh_single_m3u_account_impl` has already written a terminal
    // `status` (`:3865`) — auto-sync, a system-event log, a WS push and cache
    // cleanup all still run in between, `acquire_task_lock` at `:3345`. A
    // trigger landing in that window finds the lock held, logs "Task already
    // running" and returns having written nothing at all — but
    // `POST /api/m3u/refresh/<id>/` already answered 202, so from here that
    // is indistinguishable from "not picked up yet": the account just sits at
    // its pre-trigger baseline forever and phase 1 below would otherwise burn
    // its whole `startTimeoutMs` on a trigger that never had a chance to run.
    // Re-firing periodically is what actually recovers: by the time a retry
    // goes out, the earlier refresh's lock has almost always cleared (Task 3's
    // own workaround for this same issue found ~2s enough in this container —
    // `m3u-refresh-failure.spec.ts`). A refresh that is instead just slow to
    // be picked up (no competing lock at all) receives a harmless duplicate
    // POST — the resulting second queued run finds *its own* predecessor's
    // lock held and is dropped the same cheap way.
    const RETRIGGER_INTERVAL_MS = 5_000;
    let lastFireAt = Date.now();

    const firstObserved = await this.resource<M3uAccount>(
      url,
      (body) => {
        if (M3U_IN_FLIGHT_STATUSES.includes(body.status)) {
          sawInFlight = true;
          return true;
        }
        if (
          M3U_TERMINAL_STATUSES.includes(body.status) &&
          (body.status !== baseline.status || body.last_message !== baseline.last_message)
        ) {
          return true;
        }
        if (Date.now() - lastFireAt >= RETRIGGER_INTERVAL_MS) {
          lastFireAt = Date.now();
          // Best-effort and logged immediately rather than folded into
          // `description` (fixed at call time, before any retry has had a
          // chance to run — a mutable value read from inside it would never
          // actually appear) or `describeLast` (would replace, not augment,
          // `resource()`'s own — more useful — last-observed-body default). A
          // retry that itself fails to queue should not abort a wait that
          // might still succeed from an earlier, successfully-queued attempt.
          fire().catch((error) => {
            console.warn(
              `m3uRefreshComplete: re-trigger for account ${accountId} failed: ${String(error)}`
            );
          });
        }
        return false;
      },
      {
        description:
          `M3U account ${accountId} refresh to start ` +
          `(status ${M3U_IN_FLIGHT_STATUSES.join(' or ')}, or a terminal status ` +
          `that differs from its pre-trigger baseline of '${baseline.status}'; ` +
          `re-triggered every ${RETRIGGER_INTERVAL_MS}ms in case an earlier ` +
          'attempt landed on a still-held refresh lock — D10Scot/Dispatcharr#59)',
        timeoutMs: startTimeoutMs,
        intervalMs: 250,
      }
    );

    if (!sawInFlight) {
      // The fallback above already proved this terminal status is the
      // trigger's own outcome — no second poll needed.
      return firstObserved;
    }

    return this.resource<M3uAccount>(
      url,
      (body) => M3U_TERMINAL_STATUSES.includes(body.status),
      {
        description:
          `M3U account ${accountId} refresh to finish ` +
          `(status ${M3U_TERMINAL_STATUSES.join(' or ')})`,
        timeoutMs: 180_000,
        ...options,
      }
    );
  }

  /**
   * Waits for an `EPGSource` refresh to finish, and returns a row whose
   * `updated_at` is settled to a high probability — usually safe to pass
   * straight back in as a later call's `options.baseline`. Read
   * "**Not a guarantee**" below before relying on that for anything where
   * being wrong is expensive.
   *
   * **This is deliberately not a copy of {@link m3uRefreshComplete}, and the
   * difference is the whole point.** An XMLTV refresh reaches `status:
   * 'success'` **twice**: `parse_channels_only` sets it — with
   * `last_message = "Successfully parsed N channels"` — before
   * `parse_programs_for_source` has even started, and nothing sets it back to
   * `parsing`. A wait for a terminal status therefore resolves mid-refresh,
   * with `EPGData` rows present and zero `ProgramData`.
   *
   * So this polls `updated_at` instead. `EPGSource.updated_at` is
   * `null=True` with no `auto_now`, and `null` on a fresh row. On the paths
   * this harness exercises it is written:
   *  - **once**, by `_refresh_epg_data_impl`'s final unconditional
   *    `.update()` (`apps/epg/tasks.py:523`) — when no channel is mapped to
   *    the source yet, `parse_programs_for_source`'s early-return branch for
   *    that case (`:2126-2129`) never touches `updated_at` at all, so `:523`
   *    is the only write.
   *  - **twice**, once a channel *is* mapped: `parse_programs_for_source`'s
   *    own success path (`:2377-2378`) writes it the moment programmes are
   *    actually swapped in, and then `_refresh_epg_data_impl`'s same final
   *    `.update()` at `:523` writes it *again* — after the file lock is
   *    released — once execution gets back there.
   *
   * A version of this method that resolved on the first observed change
   * would, on the mapped path, sometimes return the row from the `:2377`
   * write — whose `updated_at` the still-pending `:523` write is about to
   * advance past. A caller that took that row as a later call's `baseline`
   * would then see `updated_at` differ on its very first poll, before any
   * new refresh had even been triggered — the same "resolves on a stale
   * write" hazard {@link m3uRefreshComplete}'s phase 2 has, one layer down.
   *
   * **Not a guarantee — read this before reusing a returned row.** Between
   * the two writes, `parse_programs_for_source` runs: `log_system_event`
   * (`:2381`), whose `_dispatch_system_event_integrations`
   * (`core/utils.py:835-868`) runs **synchronously** on a Celery prefork
   * worker — the kind of worker this refresh always runs on — meaning any
   * Connect webhook or script a user has configured executes as *inline
   * network I/O* right there; a channel-layer send (`:2391`); a DB query
   * plus N Celery dispatches for late-mapped channels
   * (`_dispatch_late_mapped_epg_parses`, `:2399`); two forced full GC passes
   * and a psutil RSS read (`:2420-2430`); and, back in
   * `_refresh_epg_data_impl`, a lock-renewer thread join with a 5s timeout
   * (`:512-513`) before the unconditional `:523` write. **None of that is
   * bounded** — a slow or hanging Connect webhook can stretch the gap
   * arbitrarily far. So this method does not resolve the instant
   * `updated_at` changes: once it has changed from the baseline, it keeps
   * polling and only resolves once that value has held for
   * {@link EPG_UPDATED_AT_SETTLE_MS} (1000ms) straight — a deliberate
   * multiple of what mutation testing measured as the *typical* gap on this
   * harness's own container (this method's pre-fix, no-settling shape
   * resolved on the stale `:2377` value in 2 of 3 runs at a 250ms poll
   * interval, putting the observed floor at roughly 165ms+), not a derived
   * bound on the true one. On a source with no Connect integration
   * configured — everything this test suite seeds — 1000ms comfortably
   * covers what was measured. On a source that *does* have one, this can
   * still return early relative to the true settle point, precisely because
   * no fixed window can dominate an unbounded wait. A caller who needs
   * certainty rather than a strong default should not reuse a returned
   * row's `updated_at` as proof of finality; assert on the data the refresh
   * was actually supposed to produce instead (e.g. poll
   * `/api/epg/programs/search/?channel_id=` for a programme count, not
   * `updated_at`).
   *
   * `status === 'error'` resolves the wait immediately, with no settling
   * wait, whenever `status` or `last_message` differs from the baseline —
   * the same guard {@link m3uRefreshComplete} uses, so a source already
   * sitting in a stale error state cannot resolve this instantly. This is
   * safe for the error paths this harness's XMLTV-only scenario can reach
   * (see the next paragraph) — it is **not** proven safe in general; see
   * the `schedules_direct` case below.
   *
   * **Not true that every error path skips `updated_at`** — two exceptions:
   * `parse_programs_for_source`'s outer `except Exception` (`:2402`)
   * catches anything raised *after* its own `:2377-2378` write (e.g. inside
   * `log_system_event` or `_dispatch_late_mapped_epg_parses`) and returns
   * `False` with `status: 'error'`; `updated_at` is left at the value that
   * success write set, and `_refresh_epg_data_impl` never reaches its own
   * `:523` write for this call (it returns as soon as
   * `parse_programs_for_source` comes back falsy) — so no double-write and
   * no settling hazard there either. The second exception is narrower than
   * it first looks: a `schedules_direct` source reaches the unconditional
   * `:523` write regardless of `fetch_schedules_direct`'s outcome, since
   * that return value is ignored (`:521`) — so a `schedules_direct` refresh
   * that fails internally still gets `updated_at` bumped once, *after* its
   * own error write. That means the immediate-error resolve above **can**
   * return a row for a `schedules_direct` source whose `updated_at` has not
   * yet been bumped by that pending `:523` write — an unsettled row, by the
   * same mechanism the settling wait exists to prevent, just reached
   * through the error branch instead of the success one. This harness is
   * XMLTV-only and never exercises `schedules_direct`, so it is not pinned
   * here; a future `schedules_direct` caller should not assume an
   * error-resolved row from this method is settled.
   *
   * **The hazard this cannot see:** an *inactive* source. `_refresh_epg_data_impl`
   * returns on `if not source.is_active` before any status write, and
   * `_ensure_epg_refresh_terminal_status` only forces `error` from
   * `fetching`/`parsing`. So an inactive source's refresh changes nothing at
   * all and this times out saying so. `seed.epgSource()` defaults to
   * `is_active: false` — pass `{ is_active: true }` for a source you intend to
   * refresh.
   *
   * **What this does NOT wait for:** programmes. `parse_programs_for_source`
   * only parses `<programme>` elements whose channel is already mapped to a
   * `Channel` (`epg_ids_mapped_to_channels`), so a freshly refreshed source
   * with no associations has zero `ProgramData` and says so in `last_message`.
   * Programmes arrive after `set-epg`; poll
   * `/api/epg/programs/search/?channel_id=` for those.
   */
  async epgRefreshComplete(
    sourceId: number,
    { baseline, trigger, ...options }: EpgRefreshWaitOptions = {}
  ): Promise<EpgSource> {
    const url = `/api/epg/sources/${sourceId}/`;

    const before =
      baseline ??
      (await this.api.json<EpgSource>(
        await this.api.get(url),
        `epgRefreshComplete baseline read for source ${sourceId}`
      ));

    if (trigger) {
      await trigger();
    } else {
      const triggered = await this.api.post('/api/epg/import/', { id: sourceId });
      if (!triggered.ok()) {
        throw new Error(
          `triggering the refresh of EPG source ${sourceId} failed: ` +
            `${triggered.status()} ${await triggered.text()}. No refresh was ` +
            'queued, so there was nothing to wait for.'
        );
      }
    }

    // See "Not a guarantee" in the doc comment above: `updated_at` can
    // advance twice on the mapped-channel path, separated by an unbounded
    // gap (it contains a synchronous, user-extensible webhook dispatch), so
    // a single observed change is not enough to know it has settled.
    // `settling` remembers the value first seen changed and *when* — the
    // predicate only resolves once that same value has held continuously
    // for `EPG_UPDATED_AT_SETTLE_MS`, checked by wall-clock time rather
    // than poll count so the window means the same thing regardless of
    // `intervalMs`.
    let settling: { value: string | null; since: number } | undefined;

    return this.resource<EpgSource>(
      url,
      (body) => {
        if (
          body.status === 'error' &&
          (body.status !== before.status || body.last_message !== before.last_message)
        ) {
          return true;
        }
        if (body.updated_at === before.updated_at) {
          settling = undefined;
          return false;
        }
        if (settling?.value !== body.updated_at) {
          settling = { value: body.updated_at, since: Date.now() };
          return false;
        }
        return Date.now() - settling.since >= EPG_UPDATED_AT_SETTLE_MS;
      },
      {
        description:
          `EPG source ${sourceId} refresh to finish ` +
          `(updated_at to advance from '${before.updated_at}' and hold for ` +
          `${EPG_UPDATED_AT_SETTLE_MS}ms, or a changed error state)`,
        timeoutMs: 180_000,
        intervalMs: 250,
        ...options,
      }
    );
  }
}
