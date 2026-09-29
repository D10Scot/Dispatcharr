# Plan: Phase 4a-1c, slot reclaim

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The Go and Python code is specified by its contracts below (types, signatures, lock order, flows, test names and their oracles), not by a diff: the implementer writes it. Every documentation edit is Appendix A, a byte-exact `git diff` against the seed that the implementer applies and does not rewrite; its only non-literal parts are the `⟨…⟩` source slots in parity rows 45 and 46, each of which names exactly the declarations that fill it.

**Goal.** A tune that Django refuses because every provider profile is full takes back one channel nobody is watching and asks once more, so a zap on a slot-constrained provider is as fast over HLS as over TS. That means: next-source's all-profiles-full refusal carries `capacity: {blocked: true, profile_ids}`, naming each profile full on its own counter and every profile sharing a credential counter that is full; the relay, on that answer at an initial tune, waits for a channel on those profiles that is already releasing its slot, or else stops the one on them that has been reclaimable longest (no client but silent HLS sessions, or no client at all), or finds neither, and in every case retries next-source exactly once. An HLS session is silent when nothing of its is in flight and more than 2 × TARGETDURATION has passed since its last request ended, so a paused AVPlayer (reloading every 2 s, M7) is never caught. Spec D16; § Slot reclaim; § 4a-1c; ruling R24's second half.

**Seed.** `4ed75d963dee2b43246fd2ef5ab43ab471f58812` (`4ed75d96`): the head of PR #538 (`migration/phase4-4a1b-live-hls`, 4a-1b), reviewed PASS there. **#538 is not merged when this plan is written.** Every `file:line` below is at `4ed75d96` unless it says otherwise, read with `git show "4ed75d96:<path>"`. Only #538's coverage-floor numbers were still due to move before its merge. **The implementer re-greps every anchor at #538's merge commit on main** (Task 1) and stops if anything the plan names has moved in shape rather than line.

**Branch.** `migration/phase4-4a1c-slot-reclaim` (spec D1), off `origin/main` once #538 has merged, so the full E2E and lifecycle matrix runs on it.

**Authority.** In order of precedence:

1. The owner's and orchestrator's rulings R1-R72 (the orchestrator's `rulings.md`). The ones this PR carries: R64-R67 and R72 (this plan's own questions, § Rulings on the plan's open questions), R24 (the reclaim half: a session silent for more than 2 × TD is departed for slot yield; the E2E never waits out the idle timeout), R21 and R52 (the Go floor: raised only by this PR's own listed uncovered statements, and every census round at or under the new floor), R15 (no new externally visible identifier is Dispatcharr-named: the one new wire key is `capacity`), R45 (no hardware gate), R47 (implementations land serially), R48 (the seam, if a split is needed). R25 is 4a-3's (§ R24 and R25 below).
2. The Phase 4 spec, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` at `4ed75d96`, as amended by this plan's own PR (§ Spec amendments in this PR): D16 (`:227`), § Presence thresholds (`:673-684`), § Locks (`:716-725`), § Who ends sessions (`:756-798`), § Slot reclaim (`:909-987`), § Testing and gates (`:1097-1225`), § 4a-1c (`:1433-1488`).
3. The 4a-1b plan (`docs/superpowers/plans/2026-09-28-phase4-4a1b-live-hls.md` on main) for the session table's shape and its hand-offs to this PR (§ Overlap, its 4a-1c row), and **the code as committed at `4ed75d96`**, tests included. This plan links against `relay/session`, `relay/channel` and `relay/httpapi` as committed, never against that plan's prose.
4. CLAUDE.md (the Go hooks, stdlib-only, credlint, the Go ratchet as amended by R21/R27, the #513 slot-script rule, the Gate 2 isolated run, the commit gate), ADR 0005 (slots stay in Django), ADR 0006 (the relay's state is in memory and it opens no Redis connection), ADR 0008, `CONTEXT.md`, and `docs/relay-parity-matrix.md` (every new live-path behaviour lands as a pinned row).

**Issues.** This PR closes no issue. Nothing it carries is tracked by an open issue, so neither its commits nor its description carry a closing keyword or a `Refs`.

## Global constraints

1. **Standard library only**, and no Redis or Postgres by any route (ADR 0006; `scripts/check_go_stdlib_only.sh relay`). The releasing set, `released` and the silence judge are `sync`, `time` and `sort`.
2. **Slots stay Django's decision (ADR 0005).** The relay never counts, reserves or releases a slot other than by its existing one release POST per channel (`relay/channel/channel.go:723-728`); it never reads `max_streams`; `capacity` is advisory. **Every provider-slot counter write stays inside the #513 slot script** (`apps/m3u/connection_pool.py`'s `_SLOT_SCRIPT` through `reserve_profile_slot`/`release_profile_slot`/`switch_profile_slot`): this PR's Django code only **reads** counters, through the existing non-mutating helpers `profile_has_capacity_for_selection` and `group_has_capacity_for_profile` (`apps/m3u/connection_pool.py:159-175`), and writes none. The #513 reconciler (`apps/proxy/slot_reconciler.py`) is untouched: a reclaimed channel's release is an ordinary release that bumps the counter's version.
3. **Every error a log or format call carries goes through `redact.Error`**, or carries a written `credential-logging: ok - <reason>` (`scripts/check_go_credential_logging.sh relay`). No new log line names a URL; the reclaim's log lines name channel ids and profile ids only. `scripts/check_credential_logging.py` holds for the Python.
4. **Zero lint findings under three GOOS** (`golangci-lint run ./...` natively, `GOOS=linux`, `GOOS=darwin`, v2.13.2), `go vet` and `go test -race ./...` green.
5. **Lock order `m.mu` → `c.mu` → `st.mu`** (spec § Locks). `ReclaimFor` holds `m.mu` across its pick, its hook and its re-check; it takes `c.mu` (read) under `m.mu`, and `st.mu` under `c.mu` only for the re-check. Code holding `st.mu` never takes `c.mu` or `m.mu` (unchanged from 4a-1b). No lock is held while waiting on `released`, while stopping a channel, or while calling the control plane.
6. **The test-modification rule.** An existing test changes only where the behaviour it pins is the thing this PR changes, and every such change, and every test-support edit that changes no assertion, is listed in § Tests changed with its before and after.
7. **Parity rows 45 and 46 land pinned** in the `phase 4` block, and `HIGHEST_ROW_ID` goes 44 → 46 in the same diff. Ids are the next free ones after #538's 37-44; if a sibling PR takes 45 or 46 first, renumber at merge (spec: "Ids are assigned at merge time").
8. **The spec amendments ride in this plan PR**, not the implementation PR (§ Spec amendments in this PR). The implementation PR edits no spec text.
9. **Python Gate 2 does not move.** `apps/proxy/next_source.py` is one of its nine modules (`scripts/coverage_live_path.coveragerc`); every new line there is covered, and `scripts/coverage_live_path_isolated.sh` shows `missing` 33 before push.
10. **No new E2E project and no workflow change.** Three specs join the `streaming` project; one test joins `streaming-failover`'s `stream-limit-429.spec.ts`, which is already on the global-settings allowlist (R67).
11. **No hardware gate** (R45), and no AVPlayer gate: 4a-1c changes nothing a player sees on a successful tune.

## Overlap with sibling plans

| Plan | Its files | Boundary with 4a-1c |
|---|---|---|
| **4a-1b** live HLS (#538, merged before this starts) | `relay/session`, `relay/channel/{sessions,hlsoutput,clientevents}.go`, `relay/channel/manager.go` (`Stop`/`endSessions`/`StopIfIdle`/`EndHLSSessions`/`runEnded`/`AttachExisting`), `relay/httpapi/hls.go` | Read and extended, never reshaped. 4a-1c adds `relay/session/silence.go` and one function in `relay/session/thresholds.go`, splits the lock out of `Table.stop` (`relay/session/table.go:337-354`) into `stopLocked` with no behaviour change, and adds one test accessor (`Table.InFlight`). In `manager.go` it routes the three existing map deletes through one helper (`removeLocked`) and adds the fourth, `ReclaimFor`'s; 4a-1b's session-ending order around them is unchanged. 4a-1b's per-session `inFlight` and `lastEnd` (`relay/session/table.go:62-63`) are exactly what the silence predicate reads, as the 4a-1b plan's overlap row promised. |
| **4a-1d** automatic profile | `apps/proxy/serializers.py` (`hls_profile`), `relay/control/nextsource.go` (its decoder), `relay/httpapi/stream.go` (`startTune` reading it, and the session's `TD` from the pipeline), the migrations, `relay/hls`'s automatic rules | Both add one field to `NextSourceResponseSerializer` (`apps/proxy/serializers.py:247-259`) and one to `control.NextSourceAnswer` (`relay/control/nextsource.go:193-217`), and both edit `startTune` (`relay/httpapi/stream.go:695-783`): textually adjacent, semantically independent, and R47 lands them serially, so the second rebases. 4a-1c's silence threshold reads each session's own `TD` (`SilentAfter(s.TD)`), so when 4a-1d sources `TD` from the pipeline (up to 6 s in automatic mode) the reclaim scales with it and needs no change: `TestSilence`'s TD-6 row holds that now. `capacity` is not required by the relay (an absent key is "not blocked"); `hls_profile` is (A1.4). |
| **4a-2** browser player | `frontend/…` only | No shared file. 4a-2's player calls `DELETE /hls/<token>` on close and switch (D18); that leave is what makes 4a-1c's case (a) the common one for the browser's own zaps. |
| **4a-3** rewind window, linger, lingering reclaim | `relay/channel/manager.go` (the linger hold), `relay/session` (behind-live tracking, the grace), `relay/hls` (the disk store), the four `rewind_*` settings | 4a-3 comes after this PR and builds on `ReclaimFor`. It plugs in at exactly two functions and adds no third: `Manager.reclaimable` (the pick's verdict and its "since") and `Manager.reclaimLocked` (the re-check and mark), both in `relay/channel/reclaim.go` (§ How 4a-3 plugs in). The releasing set, `released`, the retry, `capacity` and the silence judge are unchanged by 4a-3. The four `rewind_*` settings, their proxy-settings form fields and the stats UI's `lingering_since` are 4a-3's alone: 4a-1c adds no setting and no frontend file. |

## R24 and R25: what 4a-1b already carries, and what is left

Checked against the code at `4ed75d96`:

- **R24, first half (the explicit leave).** Carried by 4a-1b: `DELETE /hls/<token>` (`relay/httpapi/hls.go`, `HLSLeaveHandler`) removes the session at once through `Table.Leave` (`relay/session/table.go:287-296`) and answers 204 only after its `client_disconnect`, its pipeline release and its client release have run (`Departure.Run`, `relay/session/departure.go:29-46`), pinned by `TestALeaveEndsTheSessionAtOnceAndIsIdempotent` and by `e2e/tests/streaming/hls-sessions.spec.ts`'s "leaves at once on DELETE" (parity row 39). When that release was the channel's last client, `stopIfStillIdle` stops the channel (`relay/channel/manager.go:523-541`) — but its provider slot comes back only when `releaseSlot`'s POST lands, **after** `close(c.done)` (`relay/channel/channel.go:460-461`). That gap is what 4a-1c's case (a) closes.
- **R24, second half (a session silent for more than 2 × TD is departed for slot yield).** Not carried by 4a-1b, by design (the 4a-1b plan's overlap row: "exposes no silence predicate and no reclaim"). 4a-1b records the two facts it needs, `Session.inFlight` and `Session.lastEnd`, under `st.mu`, with `lastEnd` stamped at a request's **end** (`Table.End`, `relay/session/table.go:244-255`; `Activate`, `:124-136`). This PR adds the predicate and the reclaim.
- **R24's E2E rule** ("must not wait out the idle timeout"). 4a-1b's E2E already never waits it out (`hls-sessions.spec.ts`'s header). This PR's three `streaming` scenarios wait at most 5 s (2 × TD + 1 s), never 12 s.
- **R25 (an explicit leave sets the behind-live grace to 0).** Nothing to carry in 4a-1c: there is no grace until 4a-3, so every leave is "grace 0" by construction here. What 4a-1b does carry is the distinction 4a-3 will need: a leave and an idle departure are separate code paths (`Table.Leave` versus `Table.Sweep`/`Begin`'s lazy expiry, whose `Departure.idle` is true, `relay/session/departure.go:15-18`). 4a-3 records which one ended a pipeline's last session and applies the grace only to the idle one.

## ADR 0005: slots stay Django's decision

ADR 0005 (`docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md:117-122`): "`Channel.get_stream()` — selection and reservation together — keeps its current shape and callers … The relay never enforces `max_streams`; it asks." This design keeps every half of that:

- **Django still decides whether a tune gets a slot, and which.** `get_stream()` is unchanged in shape and in its callers; the reservation on the retry is the same slot-script step as every tune's (Global constraint 2). `capacity` is computed **after** the refusal, read-only, and describes it; it grants nothing.
- **Django still decides which profiles are blocking.** The relay never infers a profile's fullness; it reads `profile_ids` and filters its own channels by their `m3u_profile_id` (`SourceInfo.M3UProfileID`, which Django itself sent on each channel's next-source answer).
- **The relay decides only what Django cannot know**: which of its channels is unwatched. Its one action is to stop such a channel, whose release is the ordinary release POST every stop makes. Whether that frees the slot, and who gets it, is Django's answer to the retry; a racing tune can take it first and the retried tune then gets 503, as any tune does on a full provider.
- **No new cross-process call, in either direction.** Next-source gains a field; the relay makes no call to Django that it did not already make (the retry is a second next-source), and Django makes no call to the relay inside next-source (the spec's rejected alternative).

## Decisions the spec leaves open

Each is this plan's ruling, open to challenge. Those that changed spec text were put to the orchestrator and are now rulings R64-R67 and R72 (§ Rulings on the plan's open questions).

1. **The capacity walk lives beside `get_stream()`, not in `next_source.py`.** `Channel.blocking_profile_ids()` and `Stream.blocking_profile_ids()` (`apps/channels/models.py`) walk the profiles `get_stream()` tries (`:527-662` and `:218-256`), in the same order and with the same skips, and hand them to `apps.m3u.connection_pool.blocking_profile_ids(profiles, redis_client)`. `next_source.py` calls the method from its two refusal sites through one new helper, `_refusal(obj, error_reason)`. Why not in `next_source.py`: the knowledge of which profiles `get_stream()` tries lives in `apps/channels/models.py`, and a second copy in another app is the drift this repository's "one mechanism" rule forbids; `test_blocking_profiles_walk_the_profiles_get_stream_tries` pins the two walks together. The consequence for the tune-path ORM ratchet is stated, not hidden: `apps/proxy/tests/test_tune_path_query_ledger.py`'s static `BOUNDARY_MODULES` pin (`:244-287`) does not move, because the new reads are in `apps/channels/models.py` and `apps/m3u/connection_pool.py`, which are not boundary modules; and the reads are pinned instead by a **new ledger drive**, `next_source_blocked`, which records the exact query multiset of a blocked next-source from a cold cache (§ Tests added). A read added to the blocked path later fails that drive.
2. **`capacity` is added only to the all-profiles-full refusal**, identified by the reason string both `get_stream()`s return (`apps/channels/models.py:256`, `:656`), which becomes one constant, `ALL_PROFILES_FULL`, in `apps/m3u/connection_pool.py` (not in a `.models` module, so `next_source.py`'s model-import pin does not move). Every other refusal ("No streams assigned to channel", "Stream has no M3U account", an exception's text) keeps its dict unchanged, so `apps/proxy/tests/test_next_source_edges.py:342`'s exact-dict assertion (a refusal that does pass through `_refusal`, at `next_source.py:635`) stays green, and the serializer renders `capacity` as `null` for them; `:327`'s refusal is returned at `next_source.py:630`, before `get_stream()`, and never reaches `_refusal`. **`profile_ids` can be empty** and the answer still says `blocked: true`: `Stream.get_stream()` returns the all-full reason even when every profile was skipped as inactive (its loop ends at `apps/channels/models.py:256` with no reservation attempted), and on the Channel path a release can land between the refused reserve and the read-only capacity walk. The relay then finds nothing (`ReclaimNothing`) and makes its one retry, which in the race case succeeds; that retry is why the empty list is kept rather than dropped.
3. **The serializer renders an absent `capacity` as `null`.** `capacity = NextSourceCapacitySerializer(allow_null=True)` on `NextSourceResponseSerializer`: DRF's `Field.get_attribute` returns `None` for a missing key when `allow_null` is set (verified in the test container's DRF, `rest_framework/fields.py:450-454`), so every answer, the 404 body at `apps/proxy/api_views.py:69-78` included, carries the key. That matches the spec's `capacity: {…} | null`.
4. **The reclaimable predicate is stated over the channel's registry** (R66). A channel is reclaimable when **every registered client** is the client of one of its HLS sessions that is silent: ACTIVE with nothing in flight and more than `SilentAfter(TD)` = 2 × TD since its last request ended, or DEPARTED and still settling (its idle departure is in the middle of dropping it). A registered client with no session (a TS or fMP4 client, an HLS entry between `Attach` and `Table.Add`, a leave or admin stop between `Table.Leave`/`EndClient` and its client release), or whose session is ARRIVED, or DEPARTED and **not** settling (a resume between its `AttachExisting` and its `ResumeCommit`: 4a-1b's `fresh` client is a copy of the session's client, same id, `relay/httpapi/hls.go:463-464`), or STOPPED, makes the channel **not** reclaimable. A channel with no client is reclaimable (D16's `channel_shutdown_delay` case). This is D16's "no TS or fMP4 client, and every HLS session silent" made exact, and it closes a gap the spec's wording left: a resume's GET is a request in flight, but `Begin` does not count a `Resume` outcome in `inFlight` (`relay/session/table.go:223-231`), so a predicate over the table alone would call that session silent.
5. **"Reclaimable longest"** orders by `since`: for a channel with clients, the latest `lastEnd + SilentAfter(TD)` among its matched sessions (when the last of them became silent); for a channel with none, `Channel.idleSince`, the channel clock's time its registry last emptied. Ties break by channel id. The two clocks are the same `time.Now` in production (`main.go` passes neither `session.Config.Now` nor `ManagerConfig.Now`); tests that rank channels do so within one kind.
6. **One `released` per channel, closed by the manager together with the releasing-set delete.** `run`'s first deferred call becomes `finishRelease` (`releaseSlot`, then the manager's `released` hook, which takes `m.mu`, closes `c.released` and deletes `m.releasing[c]` in one critical section). `publish` always sets both `released` and `onReleased`, and `run` is started only by `publish`, so `finishRelease` has no other branch (round 1, finding 3: a nil-`onReleased` fallback would be dead code). A channel literal built by an in-package test without `publish` has a nil `released`, which every reader treats as never released (a `select` on a nil channel takes its `default`).
7. **Every map removal goes through one helper**, `Manager.removeLocked(c, site)`, which deletes, inserts into the releasing set only if `released` is still open (`select` with `default`, under `m.mu`), and runs the in-package test hook `afterRemove(c, site)` before returning. The four sites are `take` (`manager.go:367-376`), `stopIfStillIdle` (`:530-532`, only when the entry is `c`), `claim`'s closed-ring delete (`:231`) and `ReclaimFor`. One helper is what makes "insert in the same critical section as the delete" a property of the code rather than of four call sites.
8. **`ReclaimFor` is bounded by its `wait` from its own start**, in **real time**: one `time.Timer` (or `time.Now()` deadline) taken on entry bounds every wait, never `m.now`, which is `ManagerConfig.Now`, the injectable test clock (a stopped fake clock would make a deadline computed on it zero or unbounded). `m.now` is used only to timestamp and prune releasing entries. Not per step: (a) waits on `released` until `start + wait`; (b) stops the channel (bounded by `StopWait`) and then waits on `released` until `start + wait`. So a blocked tune costs at most three `tuneBudget`s (the first next-source, the reclaim, the retry): about 42 s worst case, the spec's figure, and milliseconds on a LAN.
9. **A declined re-check is its own outcome**, `ReclaimDeclined`, distinct from `ReclaimNothing`: the pick found a reclaimable channel and the re-check under `st.mu` refused it. The retry still runs (spec: "in every case"). The distinction exists for the log line and for the hook-driven race test's assertion.
10. **The test seams.** `ManagerConfig.ReclaimPicked func(*Channel)` is the spec's hook (exported because the race test lives in `httpapi`, where the rig has a real session table; nil in production, as `session.Releases.BeforeClient` is). `Manager.afterRemove func(*Channel, string)` is unexported and in-package only. `Table.InFlight(sid) int` is a test accessor beside `Table.Len` (`relay/session/table.go:434-439`).
11. **The fake control plane gains a slot model** (`relay/internal/relaytest/controlplane.go`): per-profile capacity, per-channel profile, blocked answers carrying `capacity`, a gate that holds release POSTs, and `BlockFirst`. `relaytest` is outside the Go gate's denominator (CLAUDE.md § Testing), so none of it counts toward R21's listing. Its zero value keeps every existing test's behaviour (unlimited, every channel on profile 1).
12. **The E2E's limit-1 scenario lives in `streaming-failover`** (R67).

## Rulings on the plan's open questions (round 1: R64-R67, R72)

The round-0 draft asked three questions; the orchestrator ruled each as recommended (R64-R67, 2026-09-29), and round 1's finding 6 tightened the first (R72). The text below is the question as asked, with its ruling.

1. **Which credential failure adds siblings.** The spec (§ Slot reclaim, step 1) says "when `pool_has_capacity_for_profile` is false, it adds every active profile sharing that profile's credential counter". `pool_has_capacity_for_profile` is `profile_has_capacity_for_selection and group_has_capacity_for_profile` (`apps/m3u/connection_pool.py:178-182`), so it is also false for a profile full only on its **own** counter while its login has room. Adding siblings then would let the relay stop an unwatched channel on a sibling profile whose release frees a credential slot that was not blocking, so the retry is still refused and a channel was stopped for nothing. **Ruled R64, tightened by R72:** a profile contributes its credential siblings only when its **own** counter has room and its credential counter is full (`profile_has_capacity_for_selection and not group_has_capacity_for_profile`), which is exactly the slot script's `credential_full` refusal (it checks the profile cap first, `apps/m3u/connection_pool.py:264`, and answers `credential_full` only past it, `:270`; D16: "each profile sharing a `credential_full` profile's credential counter"). A profile full on its own counter contributes only itself, whatever its credential counter says: stopping a sibling's channel cannot unblock it. Pinned by `test_a_full_profile_whose_login_has_room_names_no_sibling` and `test_a_profile_full_on_both_counters_names_no_sibling`.
2. **Which profiles are siblings, and the registry-level predicate.** (a) The spec says "every **active** profile sharing that profile's credential counter". A profile deactivated while a channel plays on it still holds its credential slot (deactivation releases nothing). **Recommendation:** every profile whose reserve counts against that counter (`credential_reservation(p)[0]` equal, `apps/m3u/connection_pool.py:359-371`), active or not; the relay stops only channels actually playing on a listed profile, so the wider list costs nothing and misses nothing. **Ruled R65.** (b) Decision 4's registry-level statement of the predicate, which also covers a resume between its attach and its commit. **Recommendation:** accept. A resume whose `Begin` preceded the pick but whose `AttachExisting` follows the reclaim gets 410 and re-tunes; that viewer had been idle for at least the idle timeout (12 s at TD 2), so this is the same outcome as any request on a stopped channel. **Ruled R66.**
3. **Where the limit-1 zap E2E runs.** The spec lists "A limit-1 user tunes A, calls leave, tunes B: no 429" among the `streaming` scenarios. With `terminate_on_limit_exceeded` at its default (on), the hop stops A's session and admits B whether or not A left (spec § The rest), so the scenario cannot fail and pins nothing. Turning it off is an instance-wide `CoreSettings` write, allowed only in serialised projects (`e2e/tests/guards/allowlist.ts`, the global-settings list). **Recommendation:** add the test to `e2e/tests/streaming-failover/stream-limit-429.spec.ts`, which is already allowlisted for exactly that write, already restores it in an unconditional `afterEach`, and runs in the `workers: 1` `streaming-failover` project. It also runs on a `max_streams: 1` account, so B's tune is admitted by the hop **and** served by a slot A's leave gave back. **Ruled R67**; the spec's E2E list is amended to match (§ Spec amendments in this PR).

## The design

### Django

**`apps/m3u/connection_pool.py`**, three additions (and nothing else in the module changes):

```python
# The reason both get_stream()s give when every profile they tried was full
# (apps/channels/models.py). next-source adds `capacity` to exactly this refusal.
ALL_PROFILES_FULL = "All active M3U profiles have reached maximum connection limits"

def credential_sibling_profile_ids(profile) -> list[int]:
    """Every profile whose reserve counts against `profile`'s credential counter,
    `profile` included and active or not; [] when it has none (no ServerGroup,
    max_streams 0, or no fingerprint: credential_reservation's (None, 0))."""

def blocking_profile_ids(profiles, redis_client) -> list[int]:
    """Read-only: of `profiles`, each one full on its own counter
    (not profile_has_capacity_for_selection) names itself alone; each one
    whose own counter has room but whose credential counter is full
    (not group_has_capacity_for_profile: the credential_full refusal, R72)
    names every credential sibling, itself included. Sorted ascending, no
    duplicates. Writes nothing."""
```

`credential_sibling_profile_ids` computes `key, _ = credential_reservation(profile)`; `None` answers `[]`; otherwise it reads `M3UAccountProfile.objects.filter(m3u_account__server_group=group).select_related("m3u_account")` (a function-local import of `apps.m3u.models`, the module's own idiom for the mesh, `:71`, `:109`) and keeps each profile whose `credential_reservation(p)[0] == key`. `profile_has_capacity_for_selection` is true for `max_streams == 0` (`:159-163`) and `group_has_capacity_for_profile` likewise (`:166-175`), so an unlimited profile is never named. The two checks are taken in the slot script's own order (own counter first, `:264`, then the credential counter, `:270`), so a profile full on both counters is named alone (R72). **Accepted cost, not pinned by the ledger (round 1, nit 14):** the sibling walk reads one row per profile in the group plus a fingerprint per profile, and a non-XC profile's fingerprint is a `Stream` query (`:67-77`); `next_source_blocked`'s fixture account has no `ServerGroup` (`apps/proxy/tests/test_next_source_api.py:126-132`), so that walk is outside the drive. It runs only on a blocked tune, and scales with the group's size.

**`apps/channels/models.py`**:

- Both `get_stream()`s return `ALL_PROFILES_FULL` (imported from `apps.m3u.connection_pool` beside `reserve_profile_slot`, `:19`) in place of the literal at `:256` and `:656`. Same string, one definition.
- `Stream.blocking_profile_ids(self) -> list[int]`: the profiles `Stream.get_stream()` tries (`:233-252`: `self.m3u_account.profiles.all()`, default first, skipping inactive ones and a missing default), through `blocking_profile_ids(profiles, RedisClient.get_client())`.
- `Channel.blocking_profile_ids(self) -> list[int]`: the profiles `Channel.get_stream()` tries (`:587-611`: `self.streams.all().order_by("channelstream__order")`, skipping a stream with no account or an inactive account, and an account with no active default profile; that account's active profiles, default first), deduplicated in walk order, through the same helper.

Each docstring says it mirrors `get_stream()`'s walk and names the test that holds them together.

**`apps/proxy/next_source.py`**:

```python
def _refusal(obj, error_reason):
    """get_stream()'s refusal as a next-source answer. When every profile was
    full it carries `capacity` (Phase 4 spec § Slot reclaim): the profiles that
    blocked the tune, so the relay can take back a channel nobody is watching on
    one of them and ask once more. Advisory and read-only: the reservation is
    still the slot script's, on that retry."""
    answer = {"source": None, "error": error_reason}
    if error_reason == ALL_PROFILES_FULL:
        answer["capacity"] = {"blocked": True, "profile_ids": obj.blocking_profile_ids()}
    return answer
```

It replaces the two `get_stream()` refusal returns in `resolve_initial_source`: the Stream branch (`:633-635`, `return _refusal(stream, error_reason)`) and the Channel branch (`:690-692`, `return _refusal(channel, error_reason)`), each keeping its `logger.error` line. `ALL_PROFILES_FULL` joins the existing `from apps.m3u.connection_pool import (…)` (`:26-29`). `resolve_source` needs no change: its initial branch returns `resolve_initial_source`'s dict through `_with_output_profiles(_with_proxy_settings(…))` (`:1006-1024`), and the failover and target branches never set the key. An exception inside `blocking_profile_ids` reaches `resolve_initial_source`'s outer `except Exception` (`:745-747`) and answers `{"source": None, "error": <text>}` with no `capacity`: the relay then answers 503 at once, which is today's behaviour and fails closed.

**`apps/proxy/serializers.py`**, above `NextSourceResponseSerializer` (`:247`):

```python
class NextSourceCapacitySerializer(serializers.Serializer):
    # Phase 4a-1c. Present (non-null) only on the all-profiles-full refusal.
    blocked = serializers.BooleanField()
    profile_ids = serializers.ListField(child=serializers.IntegerField())
```

and on `NextSourceResponseSerializer`: `capacity = NextSourceCapacitySerializer(allow_null=True)` (Decision 3). It is therefore in the drf-spectacular schema as a component, `NextSourceCapacity`.

### `relay/control/nextsource.go`

```go
// Capacity is next-source's capacity object (Phase 4a-1c): non-nil only when
// source is null because every profile was full. An absent key and a null one
// both decode to nil, "not blocked" -- the field describes a failure, not a
// setting, so unlike proxy_settings and hls_profile it is not required (spec
// § Next-source additions).
type Capacity struct {
	Blocked    bool  `json:"blocked"`
	ProfileIDs []int `json:"profile_ids"`
}
```

`NextSourceAnswer` gains `Capacity *Capacity \`json:"capacity"\`` (the existing `UnmarshalJSON`'s `plain` alias decodes it with no change, `:223-245`) and one method:

```go
// Blocked reports the profiles that blocked a tune, when the answer says one was.
func (a *NextSourceAnswer) Blocked() ([]int, bool)
```

which answers `nil, false` unless `Capacity != nil && Capacity.Blocked`.

### `relay/session`

`thresholds.go` gains:

```go
// SilentAfter is how long an ACTIVE session may go with nothing in flight
// before a blocked tune may take its channel back: 2 x TARGETDURATION (spec
// § Presence thresholds, D16). Silent is STRICTLY MORE than this, measured from
// the end of the session's last request: 4 s at TD 2, well inside M7's 2 s
// reload cadence for a paused AVPlayer, and 12 s at TD 6.
func SilentAfter(td time.Duration) time.Duration { return 2 * td }
```

`table.go`: `stop(match)` (`:337-354`) becomes `t.mu.Lock(); defer t.mu.Unlock(); return t.stopLocked(match, t.now())`, with the body moved unchanged into `stopLocked`. `func (t *Table) InFlight(sid string) int` (tests; 0 for an unknown sid) joins `Len`.

`silence.go` (new):

```go
// Silent implements channel.SilenceJudge: whether every client in clientIDs
// is the client of a silent session of c, and since when the last of them
// has been silent. An empty clientIDs is silent, with a zero since.
func (t *Table) Silent(c *channel.Channel, clientIDs []string) (since time.Time, ok bool)

// StopIfSilent implements channel.SilenceJudge: Silent's verdict, re-taken,
// and StopChannel's mark, in ONE critical section of t.mu. If the verdict
// holds, every ARRIVED, ACTIVE or DEPARTED session of c is marked STOPPED
// (their releases discarded, as StopChannel does) and the client entries they
// held come back with ok true. Otherwise nothing changes and ok is false.
func (t *Table) StopIfSilent(c *channel.Channel, clientIDs []string) ([]channel.StoppedClient, bool)

// silentLocked is the predicate, over an Owner so the package's own tests
// drive it with a fake owner (the stopOwner idiom, table.go:324-326).
func (t *Table) silentLocked(o Owner, clientIDs []string, now time.Time) (time.Time, bool)
```

`silentLocked`, in order: empty `clientIDs` → `(zero, true)`. Otherwise, for every session `s` with `s.Owner == o`, `s.client != nil` and `s.client.ID` in `clientIDs`: ACTIVE with `inFlight == 0` and `now.Sub(s.lastEnd) > SilentAfter(s.TD)` is silent; DEPARTED with `settling` is silent; every other case (ACTIVE in flight or heard from within `SilentAfter`, ARRIVED, DEPARTED not settling, STOPPED) answers `(zero, false)` at once. A silent session contributes `s.lastEnd.Add(SilentAfter(s.TD))` to `since` (the latest wins) and marks its client id matched. Finally, any id in `clientIDs` that no session matched answers `(zero, false)`: it is a client with no session. `StopIfSilent` takes `t.mu`, runs `silentLocked` at `t.now()`, and on `ok` returns `t.stopLocked(func(s) bool { return s.Owner == Owner(c) }, now), true` before unlocking.

### `relay/channel`

`reclaim.go` (new):

```go
// SilenceJudge is the HLS session table as ReclaimFor sees it (Phase 4a-1c).
// Both methods take only the table's own mutex, and are called with m.mu held
// (and, for StopIfSilent, c.mu read-held): the lock order m.mu -> c.mu -> st.mu.
type SilenceJudge interface {
	Silent(c *Channel, clientIDs []string) (since time.Time, ok bool)
	StopIfSilent(c *Channel, clientIDs []string) ([]StoppedClient, bool)
}

type ReclaimCase int

const (
	ReclaimNothing  ReclaimCase = iota // (c): nothing releasing, nothing reclaimable
	ReclaimWaited                      // (a): waited on a channel already releasing
	ReclaimStopped                     // (b): stopped a reclaimable channel, then waited
	ReclaimDeclined                    // (b): the pick's channel failed the re-check
)

func (r ReclaimCase) String() string // "nothing", "waited", "stopped", "declined"

// Reclaim is what ReclaimFor did, for the tune's log line and for tests.
type Reclaim struct {
	Case     ReclaimCase
	Channel  string // the channel waited on, stopped or declined; "" for nothing
	Released bool   // its released closed before the wait ended
}

// ReclaimFor is a blocked tune's one reclaim (spec § Slot reclaim, step 2).
// profileIDs are next-source's capacity.profile_ids. It returns within wait of
// its call (Decision 8). The caller retries next-source once whatever it
// returns.
func (m *Manager) ReclaimFor(profileIDs []int, wait time.Duration) Reclaim
```

`ManagerConfig` gains `Silence SilenceJudge` (nil: only a channel with no client is reclaimable) and `ReclaimPicked func(picked *Channel)` (a test seam only: run with `m.mu` held and `st.mu` not held, between the pick and the re-check; nil in production). `Manager` gains `releasing map[*Channel]time.Time` (made in `NewManager`), `now func() time.Time` (`cfg.Now` or `time.Now`), and the in-package seam `afterRemove func(c *Channel, site string)`.

`Channel` gains three fields, set in `publish`: `released chan struct{}` (made there), `onReleased func(*Channel)` (`m.released`), and `idleSince time.Time` under `c.mu`, written by `addClient` (zeroed), `dropClient` and `dropHLSClients` (set to `c.now()` when the registry becomes empty). Two unexported readers: `clientIDsLocked() []string` (caller holds `c.mu`) and `clientState() ([]string, time.Time)` (takes `c.mu` read).

`run` (`relay/channel/channel.go:459-460`): `defer c.releaseSlot()` becomes `defer c.finishRelease()`, still the first deferred call so it still runs last, after `close(c.done)`:

```go
// finishRelease is releaseSlot, then the signal ReclaimFor waits on. The
// manager closes released and forgets the releasing entry in one m.mu
// critical section (Decision 6).
func (c *Channel) finishRelease() {
	c.releaseSlot()
	c.onReleased(c) // set by publish, which is the only caller of run
}

// Released is closed once the channel's provider slot has been given back.
func (c *Channel) Released() <-chan struct{} { return c.released }
```

`manager.go`:

```go
// removeLocked deletes c from the map (the caller holds m.mu and has checked
// c is the entry) and, IN THE SAME CRITICAL SECTION, puts it into the
// releasing set unless its release has already landed. Every map removal goes
// through here: take, stopIfStillIdle, claim's closed-ring delete, ReclaimFor.
func (m *Manager) removeLocked(c *Channel, site string) {
	delete(m.channels, c.id)
	select {
	case <-c.released:
	default:
		m.releasing[c] = m.now()
	}
	if m.afterRemove != nil {
		m.afterRemove(c, site)
	}
}

// released is the channel's onReleased: close released and forget the
// releasing entry under one lock, so insertion and removal are ordered.
func (m *Manager) released(c *Channel) {
	m.mu.Lock()
	defer m.mu.Unlock()
	close(c.released)
	delete(m.releasing, c)
}
```

`take` calls `m.removeLocked(c, "take")` in place of its `delete` (`:374`); `stopIfStillIdle`'s `delete` (`:531`) becomes `m.removeLocked(c, "stopIfStillIdle")`, still only when `existing == c`; `claim`'s closed-ring `delete` (`:231`) becomes `m.removeLocked(c, "claim")`. A reclaimed channel whose `ShutdownDelay` countdown later fires reaches `stopIfStillIdle` with a map entry that is not `c` (or none), so it neither deletes nor inserts, and its `c.stop` returns at once on a closed `done` (the idempotence the method's comment already states, `:513-522`).

`ReclaimFor`, in order (all of steps 1-4 under one hold of `m.mu`):

1. `start := m.now()`; `want` is `profileIDs` as a set.
2. **(a) Wait.** Candidates, oldest first: each `m.releasing` entry inserted within `m.cfg.StopWait + wait` of `start` (an older one is deleted from the set: its stop timed out and it may never release, nit 15), whose `released` is still open and whose `c.Source().M3UProfileID` is in `want`; then each map channel, by id, whose ring has closed, whose `released` is open and whose profile is in `want` (a run that ended by itself, not yet removed). The first candidate is waited on: drop `m.mu`, wait on its `released` until `start + wait`, return `{ReclaimWaited, id, released-closed}`.
3. **(b) Pick.** For each map channel, by id, whose ring is open and whose profile is in `want`: `since, ok := m.reclaimable(c)`; keep the one with the earliest `since` (ties: lower id). None: drop `m.mu`, return `{ReclaimNothing}`.
4. **Hook, re-check, remove.** `m.cfg.ReclaimPicked(picked)` when set. `stopped, ok := m.reclaimLocked(picked)`. Not `ok`: drop `m.mu`, return `{ReclaimDeclined, id, false}`. Otherwise `m.removeLocked(picked, "reclaim")` and drop `m.mu`.
5. **Stop.** `picked.dropHLSClients(stopped)`; `picked.setState(StateStopping, nil)`; `picked.stop(m.cfg.StopWait)`; wait on `released` until `start + wait`; log at INFO `"reclaimed an unwatched channel for a blocked tune"` with the channel and its profile; return `{ReclaimStopped, id, released-closed}`.

```go
// reclaimable is the pick's verdict (spec D16), called with m.mu held. It
// takes c.mu and then the judge's lock one after the other, never nested.
// 4a-3 adds its lingering clause HERE.
func (m *Manager) reclaimable(c *Channel) (since time.Time, ok bool) {
	ids, idleSince := c.clientState()
	if len(ids) == 0 {
		return idleSince, true
	}
	if m.cfg.Silence == nil {
		return time.Time{}, false
	}
	return m.cfg.Silence.Silent(c, ids)
}

// reclaimLocked is the re-check and the mark (spec § Slot reclaim, (b) 3),
// called with m.mu held: c.mu read-held across the judge's own lock, so no
// client can join (addClient needs c.mu) and no request can begin (Begin
// needs st.mu) between the verdict and the STOPPED mark. 4a-3 adds its
// lingering clause HERE, in step with reclaimable.
func (m *Manager) reclaimLocked(c *Channel) ([]StoppedClient, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	ids := c.clientIDsLocked()
	if m.cfg.Silence == nil {
		return nil, len(ids) == 0
	}
	return m.cfg.Silence.StopIfSilent(c, ids)
}
```

Why no new client can join a picked channel at all while `m.mu` is held: `addClient` is called only from `claim` and `AttachExisting` (both under `m.mu`) and from `publish` (on a channel not yet in the map). `c.mu` held across the judge is what makes the client-id list and the session verdict one snapshot.

### How 4a-3 plugs in

4a-3 changes exactly `Manager.reclaimable` and `Manager.reclaimLocked`, and adds nothing beside them:

- A lingering channel has no client and a linger hold (a Manager-internal count, spec § Linger). In `reclaimable`, the `len(ids) == 0` branch becomes: with a linger hold, `(lingerStart + grace, now ≥ lingerStart + grace)`; without one, `(idleSince, true)` as now. In `reclaimLocked`, the same clause, read under the same `c.mu`.
- The grace is computed from what 4a-3 records in `relay/session` (whether the last session left by `Leave` or by an idle departure, and whether it was behind live); `StopIfSilent` is unchanged, because a lingering channel has no live session to judge.
- Stopping a lingering channel is `ReclaimFor`'s ordinary step 5: `c.stop` runs `stopOutputs`, which tears the pipeline, and with it the linger, down. The releasing set, `released`, the retry and `capacity` are untouched.

### `relay/httpapi`

`tuneDeps` (`relay/httpapi/stream.go:681-689`) gains `reclaim func(profileIDs []int) channel.Reclaim` (nil: no reclaim, the retry still runs). `StreamHandler` passes `reclaim: func(ids []int) channel.Reclaim { return deps.Channels.ReclaimFor(ids, tuneBudget) }` at `:254`.

`startTune` (`:695-783`), from its first next-source call: when `answer.Source == nil`, `ids, blocked := answer.Blocked()`; not blocked is `ErrNoSource` as today. Blocked: `r := deps.reclaim(ids)` when set; log at INFO `"a blocked tune asked once more"` with the channel, the profile ids, `r.Case`, `r.Channel` and `r.Released`; then **one** more `NextSource` call with the same request under a **fresh** `context.WithTimeout(context.WithoutCancel(parent), tuneBudget)`, which also becomes the context for the rest of `startTune` (the Redirect probe); an error from it is returned as the first call's would be; a null source again is `ErrNoSource` (503 "no source available", `:910-912`). The failover path never reaches this: it resolves through `resolver`, which holds no `reclaim` (spec: "failover never reclaims").

### `relay/main.go`

`channel.NewManager(channel.ManagerConfig{…, Sessions: sessions, Silence: sessions})` (`:66-70`). Nothing else.

### `relay/internal/relaytest/controlplane.go` (test support)

`ControlPlaneConfig` gains:

- `Slots map[int]int`: capacity per m3u profile id. Nil is unlimited, today's behaviour.
- `ProfileOf map[string]int`: a channel id's m3u profile. Absent is 1, today's `"m3u_profile_id": 1` (`:529`), which `render` now takes from here.
- `BlockFirst int`: the first n next-source calls answer blocked with `capacity.profile_ids` `[ProfileOf(channel)]`, whatever the model says.

The model, keyed by the channel id in the path (`/api/relay/channels/<id>/next-source`, `…/release`): an initial call (reason `initial`, no excludes, no current URL) from a channel that holds no slot reserves one on its profile when `len(holders[p]) < Slots[p]`, else answers `{"source": null, "alternates": [], "error": "All active M3U profiles have reached maximum connection limits", "capacity": {"blocked": true, "profile_ids": [p]}, "proxy_settings": …, "output_profiles": …}`; a holder's own initial call reuses its slot; failover calls leave the holders alone. A release POST frees the channel's slot. `func (c *ControlPlane) HoldReleases() (open func())` makes every later release POST, after it is recorded and before it frees anything or answers, wait until `open` is called (`open` is idempotent; the test registers `t.Cleanup(open)` **after** building its rig, so it runs first and `httptest.Server.Close` never waits on a held POST). `func (c *ControlPlane) Holders(profile int) []string` reads the model.

## PR 4a-1c: slot reclaim

**Files.**

- New: `relay/channel/reclaim.go`, `relay/channel/reclaim_test.go`; `relay/session/silence.go`, `relay/session/silence_test.go`; `relay/httpapi/reclaim_test.go`; `relay/internal/relaytest/controlplane_test.go`; `apps/proxy/tests/test_next_source_capacity.py`; `apps/m3u/tests/test_credential_siblings.py`; `e2e/tests/streaming/hls-slot-reclaim.spec.ts`.
- Changed, relay: `relay/main.go`; `relay/channel/{manager,channel,sessions}.go` (`sessions.go`: `dropHLSClients` stamps `idleSince`); `relay/session/{table,thresholds}.go`; `relay/control/nextsource.go`, `relay/control/nextsource_test.go`; `relay/httpapi/stream.go`; test support in `relay/httpapi/{stream_test,hls_test}.go` and `relay/internal/relaytest/controlplane.go` (§ Tests changed).
- Changed, Django: `apps/m3u/connection_pool.py`, `apps/channels/models.py`, `apps/proxy/next_source.py`, `apps/proxy/serializers.py`; `apps/proxy/tests/test_tune_path_query_ledger.py` (one ledger entry and one test added, § Tests added).
- Changed, E2E: `e2e/tests/streaming/helpers.ts` (one helper), `e2e/tests/streaming-failover/stream-limit-429.spec.ts` (one test added).
- Changed by Appendix A (apply it; do not rewrite it): `CLAUDE.md`, `docs/relay-parity-matrix.md` (fill the `⟨…⟩` slots), `e2e/COVERAGE.md`, `e2e/tests/guards/parity-matrix.ts`.
- Changed by the census (§ Coverage): `scripts/coverage_relay_go.floor`'s fields.

**Tasks.** Run every command from the implementation worktree (`worktree-per-change`), anchored with an absolute path or a leading `cd`. `SEED=4ed75d963dee2b43246fd2ef5ab43ab471f58812`; `BASE` is #538's merge commit on main.

1. **Pre-flight.** #538 is merged (`gh pr view 538 --repo D10Scot/Dispatcharr --json state,mergeCommit`). `set -o pipefail; git diff --stat "${SEED}" "${BASE}" -- relay apps/proxy/next_source.py apps/proxy/serializers.py apps/proxy/api_views.py apps/channels/models.py apps/m3u/connection_pool.py apps/proxy/tests/test_tune_path_query_ledger.py e2e/tests/streaming e2e/tests/streaming-failover e2e/fixtures e2e/tests/guards CLAUDE.md docs/relay-parity-matrix.md e2e/COVERAGE.md` (stderr kept; a non-zero exit is a stop). It is expected to show `scripts/coverage_relay_go.floor`-adjacent churn only if #538's merge moved relay code after `4ed75d96`; for every file it lists, re-grep each anchor this plan names in that file and record the moved line numbers in the PR body. A **shape** change (a renamed function, a changed signature, a moved map delete) is a stop: report it to the orchestrator. Then branch `migration/phase4-4a1c-slot-reclaim` off `origin/main` in its own worktree.
2. **Apply Appendix A.** `awk '/^<!-- appendix-A-begin -->$/{f=1; next} /^<!-- appendix-A-end -->$/{f=0} f' docs/superpowers/plans/2026-09-29-phase4-4a1c-slot-reclaim.md | sed '1d;$d' > "$SCRATCH/4a1c-docs.diff" && git apply --whitespace=error "$SCRATCH/4a1c-docs.diff"` (from the plan at its merged SHA; `$SCRATCH` is your session scratchpad). `git diff --stat` shows the four files of § Files' Appendix-A bullet. The parity rows' `⟨…⟩` slots are filled in Task 10.
3. **Django** (connection pool, models, next_source, serializer) with its tests (§ Tests added, Python). Re-point the test container first (`cd <worktree> && .claude/hooks/start-test-container.sh`; check it is not occupied by another agent's run, CLAUDE.md § Isolation). Run `apps.proxy.tests`, `apps.m3u.tests` and `apps.channels.tests` once fresh without `--keepdb`. Measure the new ledger drive cold (its test prints `observed:` on the first red run), type the entry by hand, and **name in the entry's comment which call makes each line** (the ledger's own rule, `test_tune_path_query_ledger.py:24-28`). Then **the Python Gate 2 isolated run**, `scripts/coverage_live_path_isolated.sh`: `missing` 33, because `next_source.py` is a Gate 2 module (a green label does not imply a green gate). `BOUNDARY_MODULES`' static test stays green unmodified; if it reddens, stop: a read reached a boundary module and Decision 1 has been broken.
4. **`relay/control`**: the `Capacity` decoder and `Blocked`; `go test -race ./control`.
5. **`relay/session`**: `SilentAfter`, `stopLocked`, `InFlight`, `silence.go`, with their tests; `go test -race ./session`.
6. **`relay/channel`**: `released`, `finishRelease`, `idleSince`, `removeLocked` at the three existing sites, `reclaim.go`, with their tests; `go test -race ./channel` (and the whole module: `channel` is imported everywhere).
7. **`relay/httpapi`** and `relaytest`: `startTune`'s retry, the rig and fixture support edits, the slot model, `reclaim_test.go`; `go test -race ./httpapi ./internal/relaytest`.
8. **`main.go`** wiring, then **the whole relay gate**: `cd relay && go build ./... && go vet ./...`; `golangci-lint run ./...`, `GOOS=linux golangci-lint run ./...`, `GOOS=darwin golangci-lint run ./...` (`0 issues.` each); from the repo root `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh relay` (the package count unchanged from #538's merge: no new package); `cd relay && go test -count=1 -race ./...`. The `relay/hls` real tests skip locally without ffmpeg and fail under `CI` without it; say which happened.
9. **E2E, static.** `cd e2e && npm ci && npx tsc --noEmit -p . && npx playwright test --project=guards`. The parity guard passes only after Task 10. **Do not start a local stack or the shared provider**: the `streaming` and `streaming-failover` projects run on the PR's CI (the `migration/` branch runs every project).
10. **Fill the slots.** Each parity row's `⟨file: symbols⟩` becomes one `file:start-end` per named declaration, as `grep -n` prints it at the implementation's final head (the guard checks each resolves). Re-run the guards.
11. **Break-checks** (§ Break-checks): each applied alone, run, the red line compared with the one described and recorded verbatim for the PR body, reverted; `git diff --stat` afterwards unchanged. BC7's E2E half runs on CI only, from a throwaway commit on a scratch branch `migration/phase4-4a1c-bc` pushed, observed red and deleted (never on the PR branch).
12. **Push and open the PR as a draft** (`implement-review-escalate`), branch `migration/phase4-4a1c-slot-reclaim`, with the description below. No closing keyword and no `Refs` anywhere.
13. **The census and the floor** (§ Coverage). Detach the census loop and watch its stopfile (a long CI loop stalls an attached subagent).

### Tests added

"Rig" tests use `relay/httpapi`'s rig (`newRigWithClient`, `relay/httpapi/stream_test.go:150-230`) with the slot model and 4a-1b's HLS stand-ins (`hlsFixture`, `relay/httpapi/hls_test.go:57-145`); "driven clock" means `rig.SessionClock.Advance`, which ages sessions and nothing else. `reclaimRig(t, f, cp, overrides)` in `reclaim_test.go` is `fanRigWith(t, cp, relaytest.Config{Rate: 4}, overrides, f.option())`, `hlsRig`'s shape with a control-plane config of the test's own (`relay/httpapi/hls_test.go:148-151`). Channel-package tests use a fake `SilenceJudge` and the package's own helpers (`attachBlocking`, `testTuning`, `testClient`, `relay/channel/sessions_test.go:16`, `manager_test.go:22-60`), with `Started.Info.M3UProfileID` set per channel.

| File | Test | Pins |
|---|---|---|
| `relay/control/nextsource_test.go` | `TestTheCapacityFieldDecodes` | an answer with no `capacity` key and one with `null` both give `Capacity == nil` and `Blocked()` `nil, false`; `{"blocked": true, "profile_ids": [3, 5]}` gives `[3 5], true`; `{"blocked": false, "profile_ids": [3]}` gives `nil, false` |
| `relay/session/silence_test.go` | `TestSilentAfterIsTwoTargetDurations` | `SilentAfter(2 s)` 4 s, `SilentAfter(6 s)` 12 s |
| | `TestSilentAndInFlightThroughTheTablesOwnMethods` | round 1, finding 3(a)(b), so `relay/session`'s own tests reach the exported wrappers (the gate measures per package): the test drives `Table.Silent` with a `*channel.Channel` value used only as an identity (`&channel.Channel{}`, the idiom 4a-1b's table tests use for `*hls.Pipeline`), its session added through `Add` and activated: silent after 5 s of clock, not at 3 s; and `InFlight(sid)` reads 1 during a `Begin`, 0 after `End`, and 0 for an unknown sid |
| | `TestSilence` | row 46, the spec's predicate table, driven through `silentLocked` with a fake owner and an injected clock, one row per case: (1) no client ids → silent, zero since; (2) an id with no session (a TS client) → not; (3) ACTIVE, nothing in flight, last request ended exactly 4 s ago → **not** (more than 2 × TD); (4) the same at 5 s (2 × TD + 1 s) → silent, `since` = `lastEnd + 4 s`; (5) a reloading session, `Begin`/`End` every 1 s of clock for 10 s → not; (6) a request begun 60 s ago and still in flight → not; (7) ARRIVED at 60 s → not; (8) DEPARTED and settling with its client id listed → silent; (9) DEPARTED, not settling, with its client id listed (a resume between attach and commit) → not; (10) two sessions, one silent and one reloading → not; (11) TD 6 s, silent for 11 s → not, for 13 s → silent; (12) a session of another owner carrying a listed client id → not matched, so not; (13) two silent sessions → `since` is the later one's |
| | `TestStopIfSilentMarksOnlyWhenStillSilent` | a silent owner's ACTIVE and DEPARTED sessions become STOPPED and the ACTIVE one's client comes back with its `Connected`; another owner's session is untouched; a non-silent owner's sessions keep their state and no `stoppedAt` is written |
| `relay/channel/reclaim_test.go` | `TestReclaimForTakesTheLongestReclaimableChannelOnABlockingProfile` | row 45: X (profile 1, silent since t−10 s), Y (profile 1, since t−5 s), Z (profile 2, since t−20 s); `ReclaimFor([]int{1}, 2*time.Second)` is `{ReclaimStopped, "X", true}`; X's `Done()` and `Released()` closed; Y and Z still in the map with their rings open; the fake judge's `StopIfSilent` was called for X only |
| | `TestAChannelTheJudgeRefusesIsNeverReclaimed` | the judge's `Silent` answers false: `{ReclaimNothing}`; the channel is in the map, running, and its release func was never called |
| | `TestADeclinedReCheckLeavesTheChannelRunning` | `Silent` true, `StopIfSilent` false: `{ReclaimDeclined, id, false}`; the channel is in the map and running |
| | `TestAZeroClientChannelInItsShutdownDelayIsReclaimable` | D16's last sentence: `ShutdownDelay` 1 s in the test's own `Tuning`, the last client released, the channel still in the map; `ReclaimFor` at once is `ReclaimStopped`; the fake judge's `Silent` was **not** called (the pick's verdict for a channel with no client is `reclaimable`'s own) and its `StopIfSilent` was called exactly once, with an empty client-id list (the re-check still runs, so any resumable DEPARTED session is marked STOPPED under `st.mu`, `reclaimLocked`); the release func ran exactly once; once `Released()` is closed the releasing set is empty; 1.5 s later the countdown's own `stopIfStillIdle` has run and `afterRemove` fired exactly once in the whole test, with site `reclaim` (the late countdown deletes and inserts nothing) |
| | `TestReclaimForWithNoJudgeTakesOnlyAChannelWithNoClient` | `Silence` nil: a channel with one client is `ReclaimNothing`; one with none is `ReclaimStopped` |
| | `TestReclaimForWaitsOnAReleasingChannel` | row 45, case (a) in the manager: a channel whose release func blocks on a gate is stopped with `Manager.Stop` (so it is in the releasing set); `ReclaimFor([]int{1}, 2*time.Second)` on another goroutine has not returned 100 ms after the call; the test opens the gate; it returns `{ReclaimWaited, id, true}`. A second case never opens the gate within `wait` 200 ms: `{ReclaimWaited, id, false}` within 200 ms plus 100 ms slack (`t.Cleanup` opens the gate) |
| | `TestAStaleReleasingEntryIsIgnored` | `ManagerConfig.Now` is a fake clock: a releasing entry (a channel whose release never lands) inserted, then the clock advanced past `StopWait + wait`; a silent channel on the same profile is `ReclaimStopped`, not `ReclaimWaited`; the stale entry is gone from the set |
| | `TestEveryMapRemovalInsertsIntoTheReleasingSet` | row 45, the spec's four-path assertion, deterministically: `afterRemove` runs inside each removal's `m.mu` critical section and asserts, reading the maps directly (same goroutine, lock held), that the channel is no longer the map's entry and is either in `m.releasing` or has a closed `released`, failing with the site's name. Four subtests drive `take` (`Manager.Stop`), `stopIfStillIdle` (the last client's release), `claim` (a channel whose run ended, then a new `Attach` of its id) and `ReclaimFor`; each asserts `afterRemove` fired exactly once with that site. A fifth subtest drives `claim`'s delete of a channel whose release has **already** landed: `afterRemove` fires, the channel is not in `m.releasing` (conditional insertion) |
| | `TestAReleasingEntryNeverOutlivesItsRelease` | for each of the four sites: after `<-c.Released()`, the test takes `m.mu` and finds no `m.releasing[c]` (the close and the delete share one critical section, so this read is deterministic, not a poll). The `claim` subtest waits `<-c.Released()` **before** the new `Attach` that triggers `claim`'s delete, so the delete meets an already-closed `released` (a claim that precedes the release is inserted and then correctly removed by `m.released`, which no wrong insertion could redden) |
| | `TestReclaimForWaitsOnARunThatEndedByItself` | round 1, finding 3(c), the spec's "or run ended (ring closed)" releasing class: a channel whose source returns on its own (every attempt ends, `MaxRetries` 1, no resolver), its release func blocked on a gate, one client still attached so it stays in the map with its ring closed; `ReclaimFor([]int{1}, 2*time.Second)` on a goroutine has not returned 100 ms later; the gate opens; it returns `{ReclaimWaited, id, true}`. `ReclaimCase.String()` is asserted here for all four values (round 1, nit 15) |
| `relay/httpapi/reclaim_test.go` | `TestABlockedTuneReclaimsASilentHLSChannel` | row 45, case (b) end to end: `Slots{1: 2}`; sessions on channels A1 and then, 3 s of driven clock later, A2; 5 s more (A1 silent 8 s, A2 5 s); a TS tune of B answers 200 with bytes; A1's next GET is 410 `{"error": "channel stopped"}` and A2's is 200; the control plane records one release, A1's, before B's second next-source call, and exactly two next-source calls for B; A1's session emitted one `client_disconnect` |
| | `TestABlockedTuneNeverReclaimsAWatchedChannel` | row 46, `Slots{1: 1}`. Subtest `ts-client`: A held by a TS client (`tuneAs`); B's TS tune is 503 `no source available`; A's client still receives bytes; B made exactly two next-source calls (one retry, never a second). Subtest `reloading`: A's session makes a playlist GET after every 1 s of driven clock, six times (6 s of clock, never more than 1 s silent); B is 503; A is in the map and its next GET 200 |
| | `TestTheReclaimReCheckSeesARequestThatArrivedAfterThePick` | row 46, the spec's deterministic seam: `Slots{1: 1}`; A's session silent for 5 s of driven clock; `rig.onReclaimPick` installs a hook that, for A, calls `rig.Sessions.Begin(sidA)` (asserting `Serve`) and records that it ran; B's TS tune is 503; the hook ran exactly once; A is in the map; `rig.Sessions.End(sidA)` then A's next GET is 200, not 410; the control plane records no release for A. Every run: nothing in it is timing |
| | `TestABlockedTuneRetriesOnceWhenNothingIsReleasingOrReclaimable` | the spec's case (c): `BlockFirst: 1` and no other channel; B's TS tune is 200; exactly two next-source calls |
| | `TestABlockedTuneWaitsForAReleaseInFlight` | row 45, the spec's case (a): `Slots{1: 1}`; `open := rig.Control.HoldReleases()`, `t.Cleanup(open)`; A's session; `DELETE /hls/<A>` answers 204 (A's channel stopped; its release POST is recorded and held); B's HLS entry on a goroutine has not answered 300 ms later; `open()`; B answers 200; its answer arrived after `open` returned; B made exactly two next-source calls, the first recorded before A's release completed |
| | `TestAnInFlightRequestHoldsAChannelAgainstReclaim` | row 46, the spec's in-flight test, two subtests with the new gated fixture modes (§ Tests changed). `entry`: A's entry on a goroutine, held in its init wait (`modeGatedInit`), the table holding one ARRIVED session; 5 s of driven clock; `rig.Manager.ReclaimFor([]int{1}, time.Second)` is `ReclaimNothing`; the gate file is touched; the entry answers 200; 5 s more; `ReclaimFor` is `ReclaimStopped` for A. `long-poll`: A's entry answers 200 (`modeGatedSegments`: inits only until the gate); a video-playlist GET on a goroutine until `rig.Sessions.InFlight(sidA) == 1`; 5 s of clock; `ReclaimFor` is `ReclaimNothing`; the gate is touched and the GET answers 200; 5 s more; `ReclaimFor` is `ReclaimStopped` |
| `relay/internal/relaytest/controlplane_test.go` | `TestTheSlotModelBlocksReleasesAndHolds` | the fake's own contract: a second channel on a full profile is answered with `capacity` and a null source; the holder's own repeat call reuses; a release frees; `HoldReleases` holds a release until `open`; `BlockFirst` answers blocked once; the zero config is unlimited on profile 1 |
| `apps/m3u/tests/test_credential_siblings.py` | `CredentialSiblingTests` (`test_siblings_share_the_credential_counter_across_accounts`, `test_a_different_login_in_the_same_group_is_not_a_sibling`, `test_an_unlimited_profile_has_no_siblings`, `test_an_inactive_profile_sharing_the_counter_is_a_sibling`, `test_a_profile_outside_any_server_group_has_no_siblings`) | `credential_sibling_profile_ids`, on `PoolEnforcementTests`' XC fixture shape (`apps/m3u/tests/test_connection_pool.py:172-189`) |
| `apps/proxy/tests/test_next_source_capacity.py` | `NextSourceCapacityTests(RelayApiTestCase)`: `test_a_blocked_channel_names_its_full_profile` | row 45: the channel's profile at `max_streams` 1 with its counter at 1 in the fake Redis; `POST …/next-source` is 200 with `source` null, `error` `ALL_PROFILES_FULL` and `capacity` `{"blocked": true, "profile_ids": [<profile>]}`. Nothing was written (round 1, nit 13): the fake Redis's whole keyspace (`slot_version:*` included) is snapshotted after `get_stream()`'s refusal (`blocking_profile_ids` patched to record its call and delegate) and compared with the keyspace after `_refusal` returns; the blocking walk added no key and changed no value |
| | `test_credential_siblings_are_named` | row 45: two XC accounts sharing one login in one `ServerGroup`, the channel's streams on account 1, account 2's profile holding the credential counter's one slot: `profile_ids` is both profiles, sorted |
| | `test_a_full_profile_whose_login_has_room_names_no_sibling` | R64: account 1's profile full on its own counter, the shared credential counter below its cap: `profile_ids` is account 1's profile alone |
| | `test_a_profile_full_on_both_counters_names_no_sibling` | R72: account 1's profile full on its own counter **and** the shared credential counter at its cap: `profile_ids` is account 1's profile alone, never account 2's |
| | `test_a_blocked_stream_preview_names_its_full_profile` | the Stream branch, by `stream_hash` |
| | `test_an_answered_tune_carries_null_capacity` | a tune with room: `capacity` is `null` and the key is present |
| | `test_a_refusal_that_is_not_maxed_out_carries_null_capacity` | a channel with no streams ("No streams assigned to channel"): `capacity` `null` |
| | `test_the_capacity_field_is_in_the_schema` | drf-spectacular's schema has a `NextSourceCapacity` component with `blocked` and `profile_ids`, and `NextSourceResponse` lists `capacity` |
| | `test_blocking_profiles_walk_the_profiles_get_stream_tries` | Decision 1's drift guard: a channel with five streams, one per skip `get_stream()` makes (on an active account with two active profiles and one **inactive non-default** profile, the `filter(is_active=True)` skip at `apps/channels/models.py:598`; on an inactive account; on an account whose default profile is inactive; and a stream with no account); `apps.channels.models.reserve_profile_slot` patched to record each profile it is asked for and refuse with `profile_full`; with **every profile in the fixture**, the skipped ones included, set at its cap in the fake Redis (so a walk that failed to skip would name an extra profile), `sorted(set(recorded))` equals `blocking_profile_ids()` (every profile the walk examines is full, so each is named; one the walk skipped would be missing, one it added would be extra) |
| `apps/proxy/tests/test_tune_path_query_ledger.py` | `test_a_blocked_next_source_runs_no_query_outside_its_ledger` | a new drive, `LEDGER["next_source_blocked"]`: the fixture channel's profile full, next-source from a cold cache; the exact query multiset, measured and typed by hand (Task 3), each line's comment naming the call that makes it |

**E2E** (e2e-upstream's assets, `rate: 1`, the locked Proxy profile, every test ends by `DELETE`ing the sessions it opened; timeouts generous and never gates). A new helper in `e2e/tests/streaming/helpers.ts`:

```ts
/**
 * Two channels on ONE M3U account whose default profile allows one stream
 * (`max_streams: 1`, synced to the default profile, apps/m3u/models.py:388-424)
 * and whose provider allows one connection (`maxConnections: 1`): Django's
 * slot refusal, not the provider's, is what blocks the second tune, and the
 * provider's cap confirms the first connection really closed.
 */
export async function slotCappedChannels(upstream, seed, api, prefix: string): Promise<{ a: Channel; b: Channel; scenario: UpstreamScenario }>
```

It creates the scenario (two channels, `asset: 'mpeg2-576i-mp2'`, `rate: 1`, `maxConnections: 1`), `seed.upstreamM3UAccount(scenario, { max_streams: 1 })`, reads the account's two ingested streams (`/api/channels/streams/?m3u_account=<id>`, `channel-from-stream.spec.ts:23-27`'s shape) and makes one channel per stream with `seed.channel({ streams: [id], stream_profile_id: proxy.id })`. **Never the custom account**: `seed.upstreamChannel`'s streams live on the instance-wide custom M3U account, whose `max_streams` no test may change.

| Spec | Test (tag) | Asserts |
|---|---|---|
| `tests/streaming/hls-slot-reclaim.spec.ts` | `a zap that leaves its session plays the next channel at once` (`@contract`) | row 45: `enterHls` A (`/proxy/ts/stream/<a>?output_format=hls`), then `leaveHls` (204), then **immediately** `enterHls` B: 200, and `waitForSegments` lists at least one segment within 60 s; `expect.poll` on the provider's `connections(scenario)` reaches `channels` equal to B's upstream channel alone within 10 s |
| | `a session silent for more than two target durations yields its slot` (`@contract`) | row 45: `enterHls` A, then no request for 5 s (2 × TD + 1 s, below the 12 s idle timeout), then `enterHls` B: 200 with segments; A's next `video.m3u8` GET is 410 `{"error": "channel stopped"}` |
| | `a session that keeps reloading holds its slot` (`@contract`) | row 46: `enterHls` A; A's `video.m3u8` is fetched every 1 s from then until the end of the test; after 5 s, B's entry is 503 and its body contains `no source available` (Django's refusal, relayed: not an upstream failure); A's reload keeps answering 200 |
| `tests/streaming-failover/stream-limit-429.spec.ts` | `an HLS viewer at stream_limit 1 who leaves zaps with no 429` (`@contract`) | R67: the file's own settings capture and `afterEach` restore (`terminate_on_limit_exceeded` off, `:66-94`); `slotCappedChannels`; a `seed.xcUser({ user_level: 1, stream_limit: 1 })`; `enterHls` A at `/live/<u>/<p>/<a.id>.m3u8`; `leaveHls`; `request.get` of B's `.m3u8` form is 200 (not 429, not 503), and its multivariant parses |

### Tests changed

Each is a change to a test whose pinned behaviour this PR changes, or a support edit that changes no assertion.

| Test | Before | After | Why |
|---|---|---|---|
| `relay/internal/relaytest/controlplane.go` (support) | every answer carries `m3u_profile_id` 1; no slot model | `ControlPlaneConfig.Slots`, `ProfileOf`, `BlockFirst`; `HoldReleases`, `Holders`; `m3u_profile_id` from `ProfileOf` (default 1) | the reclaim tests need Django's refusal and a held release; the zero value is today's fake exactly, so no existing test's inputs change |
| `relay/httpapi/stream_test.go` `newRigWithClient` (support) | `ManagerConfig{…, Sessions: sessions}` | adds `Silence: sessions` and `ReclaimPicked: func(c *channel.Channel) { if f := rig.reclaimPick.Load(); f != nil { (*f)(c) } }`; `rig` gains `reclaimPick atomic.Pointer[func(*channel.Channel)]` and `onReclaimPick(f)` | the rig builds the manager before a test can reach it, so the hook is late-bound; nil in every existing test, which therefore runs with reclaim live and no hook |
| `relay/httpapi/hls_test.go` `hlsFixture` (support) | modes `modeGood`, `modeInitOnly`, `modeNoInit`, `modeStubborn`, `modeFlaky` (`:50-56`) | two more, `modeGatedInit` (writes nothing until a gate file exists, then healthy output) and `modeGatedSegments` (writes the inits, then the rest of `vfull.mp4`/`afull.mp4` once the gate exists); the fixture writes `vrest.mp4`/`arest.mp4` as `vfull`/`afull` minus the `vinit`/`ainit` prefix, and `t.Fatal`s naming the file if the init is not a byte prefix of the full stream (it is, at the seed: `bytes.HasPrefix(HLSVideoStream(20, 50), HLSVideoStream(0, 50))` and the AAC twin both hold, checked in a scratch export) | the in-flight test needs an entry and a long-poll held open for as long as the test chooses; both are shell scripts in `modeFlaky`'s idiom (`:117-138`), and no existing mode changes |
| `apps/channels/models.py:256`, `:656` (not a test) | the literal reason string | `ALL_PROFILES_FULL` | one definition for the string next-source matches on; the value is byte-identical, so no test reading it moves |

No existing assertion changes. `apps/proxy/tests/test_next_source_edges.py:327`, `:342` stay green because only the all-profiles-full refusal gains `capacity` (Decision 2); `apps/proxy/tests/test_tune_path_query_ledger.py`'s existing four drives and `BOUNDARY_MODULES` stay green unmodified (Decision 1; Task 3 stops if not); `relay/channel/sessions_test.go`'s `recordingEnder` is untouched, because `SilenceJudge` is its own interface and `ManagerConfig.Silence` its own field.

### Break-checks

Each wrong edit is applied alone, the named test run (`cd relay && go test -count=1 -race -run '<test>' ./<pkg>`, or the named Django test, or CI for the E2E), the red line compared with the one described (the implementer records the literal line in the PR body), and the edit reverted. BC1-BC7 are the spec's (§ 4a-1c); BC8-BC15 are this plan's.

- **BC1 — reclaim on the pick's verdict, without the re-check** (spec). `reclaimLocked`: `return m.cfg.Sessions.StopChannel(c), true` in place of the judge's `StopIfSilent`. `TestTheReclaimReCheckSeesARequestThatArrivedAfterThePick` reddens on every run: B answers 200 where 503 is expected, and A's next GET is 410 — the channel was reclaimed with a request in flight.
- **BC2 — retry only after (a) or (b)** (spec). `startTune`: skip the retry when `r.Case == channel.ReclaimNothing`. `TestABlockedTuneRetriesOnceWhenNothingIsReleasingOrReclaimable` reddens: 503 where 200 is expected, one next-source call where two are.
- **BC3 — omit the credential siblings** (spec). `blocking_profile_ids`: drop the sibling branch. `test_credential_siblings_are_named` reddens: `profile_ids` lacks account 2's profile.
- **BC4 — skip the releasing wait** (spec). `ReclaimFor`: delete step 2 (a). `TestABlockedTuneWaitsForAReleaseInFlight` reddens deterministically: B answers 503 while the stub still holds A's release, before `open`. The immediate-zap E2E stays behaviour coverage only: on the E2E container the release lands in milliseconds, so it is not this break-check's oracle (spec).
- **BC5 — insert after leaving the lock on one path** (spec). `stopIfStillIdle`: in place of `m.removeLocked(c, …)`, keep the delete **and the hook** under `m.mu` — `delete(m.channels, c.id); if m.afterRemove != nil { m.afterRemove(c, "stopIfStillIdle") }` — and move only the insertion out: after `m.mu.Unlock()`, re-take the lock and insert into `m.releasing`. `TestEveryMapRemovalInsertsIntoTheReleasingSet/stopIfStillIdle` reddens with `afterRemove`'s own message naming the site and the mechanism: removed from the map with neither a releasing entry nor a closed `released`. (A wrong edit that bypassed the hook as well would redden only the subtest's once-per-site count, which names no mechanism; round 1, finding 1.)
- **BC6 — measure silence from request arrival** (spec). `silentLocked`: test `now.Sub(s.lastEnd)` only, ignoring `inFlight`, and make `Table.Begin` stamp `lastEnd = now` for a served request. `TestAnInFlightRequestHoldsAChannelAgainstReclaim/long-poll` reddens (`ReclaimFor` answers `ReclaimStopped` while the playlist request is in flight), and `TestSilence` row 6 (an ACTIVE session whose request began 60 s ago with no `End`). The `entry` subtest and row 7 stay green, because the predicate refuses an ARRIVED session by its state, whatever `inFlight` says (round 1, finding 2).
- **BC7 — count a reloading session as silent** (spec). `silentLocked`: an ACTIVE session with `inFlight == 0` is silent whatever its `lastEnd`. `TestABlockedTuneNeverReclaimsAWatchedChannel/reloading` reddens (B 200 where 503 is expected) and `TestSilence` row 5; on CI the E2E `a session that keeps reloading holds its slot` reddens with a 200.
- **BC8 — a client with no session counts as silent.** `silentLocked`: drop the unmatched-id check. `TestABlockedTuneNeverReclaimsAWatchedChannel/ts-client` reddens (B 200, and the TS client's stream ends) and `TestSilence` row 2.
- **BC9 — unconditional insertion.** `removeLocked`: insert without the `select` on `released`. `TestEveryMapRemovalInsertsIntoTheReleasingSet`'s fifth subtest reddens (an entry for a channel whose release had already landed), and `TestAReleasingEntryNeverOutlivesItsRelease/claim`, whose claim runs after the release by construction.
- **BC10 — no stale cutoff.** `ReclaimFor`: consider every releasing entry. `TestAStaleReleasingEntryIsIgnored` reddens: `ReclaimWaited` where `ReclaimStopped` is expected.
- **BC11 — `capacity` on every refusal.** `_refusal`: drop the `ALL_PROFILES_FULL` test. `test_a_refusal_that_is_not_maxed_out_carries_null_capacity` reddens with a `capacity` object; so does `test_next_source_edges.py:342` (its refusal passes through `_refusal`); `:327`'s does not (Decision 2).
- **BC12 — reclaim across profiles.** `ReclaimFor` step 3: ignore `want`. `TestReclaimForTakesTheLongestReclaimableChannelOnABlockingProfile` reddens: Z (profile 2) stopped.
- **BC13 — the newest, not the longest.** Step 3: keep the latest `since`. The same test reddens: Y stopped where X is expected.
- **BC14 — siblings on any pool failure.** `blocking_profile_ids`: add siblings when `pool_has_capacity_for_profile` is false. `test_a_full_profile_whose_login_has_room_names_no_sibling` reddens with a sibling listed.
- **BC15 — siblings for a profile full on both counters** (R72). `blocking_profile_ids`: add siblings whenever `group_has_capacity_for_profile` is false, without the own-room condition. `test_a_profile_full_on_both_counters_names_no_sibling` reddens with account 2's profile listed.

### Coverage (R21, R52)

No package is newly linked (`relay/session` and `relay/hls` were linked by #538), so the floor file's shape fields do not move and the gate prints `this run missing=` on the first push.

1. **The census.** Dispatch `go-tests.yml` on the branch one run at a time, at least twelve times, until the maximum has held for six consecutive rounds, recording every round's `this run missing=` in order. A round counts when its `build` job succeeded, whatever `Coverage gate` said. From each round's `relay-go-coverage` artifact, compute (b) the uncovered **statements** (Σ `numStmt` of each uncovered block in the coverprofile, the unit the floor's `missing` counts) in this PR's own new or changed code, a block counting when its start line falls in an added range of `git diff -U0 "${BASE}" -- relay ':!*_test.go' ':!relay/internal'`; and (c) any other uncovered block absent from #538's census artifacts: a pre-existing flap, recorded, never counted. **A round whose `this run missing=` exceeds `F + O` by more than O explains stops the census**: report it to the orchestrator with the block diff; it is never absorbed into `O`, and its fix is a re-measurement PR of its own (R52; CLAUDE.md § Testing).
2. **O and the additions figure.** `O` = the sum over this PR's files of each file's maximum of (b). Coverage on additions = 1 − (maximum uncovered statements in (b)) / (added statements, by (b)'s start-line rule), and must be **≥ 85%**; below it, add tests, never lower the bar.
3. **The floor, by hand** (a plain `--write-floor` refuses a rising `missing`, `scripts/coverage_relay_go.sh:349-356`): `missing = F + O`, where `F` is `missing` in `scripts/coverage_relay_go.floor` at `BASE` (#538's merged floor); `percent` from this census's `statements`; `measured` today; `runs` the round count. **Every** census round's `this run missing=` is at or under the new `missing` (R52: "does not exceed"). Commit, and confirm one more CI run's gate is green.
4. **The listing, in the PR body** (the reviewer checks it against the artifacts):

```
Coverage (R21, R52). Census: <N> rounds (runs <ids>), `this run missing=` in order: <m1, …, mN>; max <M>.
Floor: missing <F> -> <F> + O = <new>; statements <S>; percent <P>; packages unchanged (12).
O, 4a-1c's own new or changed statements, uncovered (per-file max over the rounds):
  relay/channel/reclaim.go: <n> (blocks <start-end>, …)
  relay/channel/manager.go: <n> …   relay/channel/channel.go: <n> …   relay/session/silence.go: <n> …
  relay/session/table.go: <n> …     relay/control/nextsource.go: <n> …  relay/httpapi/stream.go: <n> …  = <O>
Additions: <A> statements, at most <U> uncovered in any round -> <pct>% (>= 85%).
Pre-existing flaps outside O: <none | file:block, rounds>.
```

**Python Gate 2**: Task 3's isolated run; `missing` stays 33 and is quoted in the PR body.

### Gates

- Go: Task 8, and the Go gate under § Coverage.
- Python: `apps.proxy.tests`, `apps.m3u.tests`, `apps.channels.tests` green, once fresh; Gate 2 isolated `missing` 33.
- E2E: every `E2E`, `Lifecycle`, `Go`, `Backend` and `Frontend` result green on the PR (the `migration/` branch runs the full matrix).
- **Stopping point.** Yes. This closes 4a-1: live HLS on Apple devices, with zaps as fast as TS on a slot-constrained provider.

### PR description draft

Fill the `<…>` slots from Tasks 1, 11 and 13; no closing keyword and no `Refs` anywhere.

> **Phase 4a-1c: a blocked tune takes back a channel nobody is watching.** When every provider profile is full, next-source's refusal now carries `capacity: {blocked: true, profile_ids}`: each profile full on its own counter and every profile sharing a full credential counter, computed read-only after `get_stream()`'s refusal. The relay then waits for a channel on those profiles that is already releasing its slot (a leave that stopped it before its release POST landed), or else stops the one on them that has been unwatched longest — no TS or fMP4 client, and every HLS session silent for more than two target durations (4 s) with nothing in flight — and asks next-source exactly once more; a second refusal is 503 as before. A paused AVPlayer reloads every 2 s and is never taken. The verdict is re-checked, and the channel's sessions marked STOPPED, in one critical section of the session table, so a request that arrives after the pick is either seen or answered 410. Slots stay Django's decision (ADR 0005): Django names the blocking profiles and the slot script makes the reservation on the retry; the relay only chooses among channels it knows are unwatched, and makes no new call to Django. The #513 reconciler needs no change. Spec D16, § Slot reclaim; parity rows 45-46. Plan: `docs/superpowers/plans/2026-09-29-phase4-4a1c-slot-reclaim.md` at `<plan PASS SHA>`. Anchors re-grepped at #538's merge `<BASE>`: <moved lines, or "none moved">.
>
> **Coverage.** <§ Coverage listing, verbatim>. Python Gate 2: `missing` 33, unchanged.
>
> **Tests changed** (before → after): <§ Tests changed, one line each>.
>
> **Break-checks:** <BC1-BC15, one line each: the wrong edit, the test, the red line>.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## The seam, if this PR must split (R48)

One PR is the default. If fix rounds grow it past review, the seam is the wire:

- **4a-1c-1**: the Django half (`ALL_PROFILES_FULL`, `blocking_profile_ids`, the two model methods, `_refusal`, the serializer field), its Python tests and the ledger drive. Inert on its own: the relay at `BASE` ignores an unknown `capacity` key (`encoding/json` drops it), so a blocked tune still answers 503.
- **4a-1c-2**: everything else — the decoder, the session judge, the releasing set, `ReclaimFor`, the retry, the E2E, the parity rows and CLAUDE.md.

## Residual risks and follow-ups

- **A reclaim can lose its slot to a racing tune.** Between the reclaimed channel's release and the retry, another tune may reserve the freed slot; the retried tune then gets 503, as any tune does on a full provider. Slots are Django's (ADR 0005); nothing here queues.
- **A third-party app that never calls leave** holds its slot against a blocked tune for 2 × TD after its last request (4 s at TD 2; spec § Risks), and its stream-limit count for the idle timeout plus one sweep tick.
- **A resume racing a reclaim gets 410** (R66): the viewer re-tunes. Bounded to viewers already idle for at least the idle timeout.
- **"Failover never reclaims" is structural, not pinned by a test.** The failover path resolves through `resolver`, which holds no reclaim function; a test would need the fake control plane to answer a failover call blocked, which nothing in the product does differently today. Recorded, not engineered.
- **Worst-case blocked tune** is about three `tuneBudget`s (42 s) against a hung control plane, the spec's figure; on a LAN it is milliseconds.
- **A channel whose stop times out and never releases** stays in the releasing set until a later `ReclaimFor` prunes it after `StopWait + wait`; it is ignored from then on, and its source goroutine is the leak to look at, not the entry.

## Spec amendments in this PR

Edits to `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` in this plan PR, confined to § Slot reclaim and one changelog entry ("2026-09-29, amended by the 4a-1c plan", at the end of the Changelog). The branch's base is main (`d51d3195`), whose spec lacks #538's R55-R57 amendments; these hunks touch none of their lines.

- **§ Slot reclaim, step 1**: an italic paragraph after "It returns `capacity: …`" recording R64 as tightened by R72, R65, the model methods beside `get_stream()`, and `ALL_PROFILES_FULL`.
- **§ Slot reclaim, step 2 (b) › Pick**: an italic paragraph stating the predicate over the registry (Decision 4) and defining "longest" (Decision 5).
- **§ Slot reclaim, `released`**: one parenthetical sentence (Decision 6).
- **§ Testing and gates › E2E, the 4a-1c no-wait bullets**: one italic sentence saying the limit-1 scenario runs in `streaming-failover/stream-limit-429.spec.ts` with `terminate_on_limit_exceeded` off, and why (R67).
- **Changelog**: the entry, citing R64-R67 and R72 as ruled (2026-09-29).

## Appendix A — documentation

Byte-exact against `4ed75d96`, verified with `git apply --check --whitespace=error` on a `git archive 4ed75d96` export, except the `⟨…⟩` slots in `docs/relay-parity-matrix.md`'s rows 45 and 46 (Task 10). Apply with Task 2's command. `e2e/COVERAGE.md`'s new row sits after #538's "Gap, pinned in Go only" row; `CLAUDE.md`'s hunk corrects the preemption bullet, which would otherwise read as though a blocked tune could evict nothing.

<!-- appendix-A-begin -->
```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 8d1cce1..a980503 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -122,7 +122,7 @@ Security — treat the first as an incident:
 Correctness:
 
 - **The ownership lease was time-bounded, not fenced.** `StreamBuffer.add_chunk()` wrote with no ownership check or fencing token — two owners interleaved chunks at alternating monotonic indices and readers decoded a spliced stream with every check passing. The lease **failed open** three ways (`live_proxy/server.py` and `_execute_redis_command` swallowing exceptions to `None`); `release_ownership` was GET→compare→DELETE, `extend_ownership` GET→EXPIRE, both non-atomic. **Phase 2 stage 2d-4 deleted all of it with the package** — the defect is retired by elimination, not fixed, and **no parity-matrix row covers it**: row 27 is the `_execute_redis_command` swallow named above and carries a `retired:` sentinel of its own, while the lease itself never earned a row because nothing outside the container could provoke it (`e2e/COVERAGE.md`'s G4 flagship says why). **If you carry this design forward anywhere: lease token in the write path via Lua, never fail open.**
-- Channel preemption is **gone, and was never alive**: `_pick_channel_to_preempt()` was deleted in Phase 1 PR 7 along with the commented-out `return` beside its call site. It could never have returned a channel — `apps/channels/models.py` imports no `time`, so its cooldown check raised `NameError`; the profile index key it prefers is written nowhere in the tree; and its scan fallback `int()`s a segment of `live:channel:{uuid}:metadata`, which is a UUID. The feature gap is unchanged: channel preemption stays unimplemented.
+- Channel preemption is **gone, and was never alive**: `_pick_channel_to_preempt()` was deleted in Phase 1 PR 7 along with the commented-out `return` beside its call site. It could never have returned a channel — `apps/channels/models.py` imports no `time`, so its cooldown check raised `NameError`; the profile index key it prefers is written nowhere in the tree; and its scan fallback `int()`s a segment of `live:channel:{uuid}:metadata`, which is a UUID. The feature gap is unchanged: channel preemption stays unimplemented. Phase 4a-1c's slot reclaim is not preemption: a tune whose next-source answer is `capacity.blocked` takes back only a channel nobody is watching (no TS or fMP4 client, every HLS session silent for more than 2 × TARGETDURATION, or no client at all), never a watched one (Phase 4 spec D16, § Slot reclaim).
 - **Both scheduler migration reverses are broken**: `epg/migrations/0007` deletes *every* `IntervalSchedule`/`PeriodicTask`; `m3u/migrations/0006` filters on a field `IntervalSchedule` never had (`FieldError`). 16 migrations have no reverse; nothing in CI exercises reverse migrations, and `makemigrations --check` runs only as `core/tests/test_no_pending_migrations.py`, which is to say only when the `core.tests` label runs (#177).
 - Channel-authorization filter copy-pasted across **eight functions** (**ten pasted blocks**: `generate_m3u` and `epg_generator` each carry the profile and no-profile copies). `hide_adult_content` applied in listing paths but, since Phase 1 PR 5, no longer absent from the relay-served surfaces — `authorize_stream` applies it there, closing "unlistable yet streamable" on the live tune path (now `apps/proxy/stream_routes.py`, authorized before the Go relay ever sees the connection) and on `timeshift`'s streaming views, without touching the filter's other copies. **`hdhr/api_views.py` is a separate defect, not an instance of that one**: all four endpoint views (`DiscoverAPIView`, `LineupAPIView`, `LineupStatusAPIView`, `HDHRDeviceXMLAPIView`) are `AllowAny` and never resolve a user, gated only by `network_access_allowed(request, "M3U_EPG")` — so a per-*user* preference like `hide_adult_content` is inapplicable there rather than forgotten, and the real gap is that the HDHomeRun surface performs no authorization of any kind. The two need different fixes and neither closes the other. The one extracted helper, `_user_can_access_channel`, moved in Phase 1 PR 5 to `apps/proxy/authorize.py` as `user_can_access_channel`, the membership check `authorize_stream` applies.
 - **`MAX_STREAM_SWITCHES` now bounds buffering-triggered switches** ([#221](https://github.com/D10Scot/Dispatcharr/issues/221), fixed in #394, row 6): once the budget is spent the buffering path refuses the switch and keeps the slow source, where the main loop still ends the channel at its bound.
diff --git a/docs/relay-parity-matrix.md b/docs/relay-parity-matrix.md
index 1dc8f83..9ab0e26 100644
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -216,4 +216,6 @@ PR's first, which is the distance git needs to merge them cleanly.
 | 42 | A Redirect-profile channel is served over HLS through the relay, as Proxy: an `hls` tune reserves and holds the provider slot and reads the provider itself, where a TS tune on the same channel, while it is not running, still gets its 302 | `relay/httpapi/stream.go:741-758` | `relay/httpapi/hls_test.go::TestARedirectChannelIsServedOverHLSAsProxy`, `e2e/tests/streaming/hls-entry.spec.ts::a Redirect-profile channel is served over HLS through the relay` | Phase 4a-1b (spec D13, R23). HLS is made from bytes the relay holds; a 302 to an endless provider TS is what AVPlayer cannot play (ADR 0008). |
 | 43 | Live HLS media playlists conform and their segments stay fetchable: `VERSION:7`, `TARGETDURATION:2`, `INDEPENDENT-SEGMENTS`, `EXT-X-PROGRAM-DATE-TIME` on every segment, at most 10 listed and at least 6 once the channel has run 12 s, a media sequence that only advances; `Cache-Control: no-cache` and a `Last-Modified` from the newest segment; and a segment that leaves the list stays in the store for its duration plus the playlist's | `relay/hls/store.go:22-246`, `relay/httpapi/hls.go:521-548` | `relay/hls/store_test.go::TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists`, `relay/hls/store_test.go::TestTheMediaPlaylist`, `relay/httpapi/hls_test.go::TestAMediaPlaylistWaitsForItsFirstSegmentAndCarriesItsHeaders`, `e2e/tests/streaming/hls-playlists.spec.ts::a media playlist conforms and its init and segments parse` | Phase 4a-1b (spec D7, § Session resources; ruling R44 for the store's 21, RFC 8216 § 6.2.2). Apple 8.4, 8.11 (the 6-segment minimum), 8.24, 9.11-9.12. |
 | 44 | A failed HLS output marks the channel, not a pipeline: its sessions become STOPPED, its pipeline is torn down, and new HLS entries answer 502 until the channel's next source boundary, which only clears the mark and starts nothing; the channel and its TS clients are unaffected | `relay/channel/hlsoutput.go:67-167`, `relay/channel/boundary.go:38-47`, `relay/httpapi/hls.go:370-385` | `relay/httpapi/hls_test.go::TestAFailedHLSOutputRefusesEntriesUntilTheNextBoundaryAndStartsNothingThere` | Phase 4a-1b (spec § Encoder argv, failure; R19: a TS-only channel starts no encode, so the boundary only clears). The 502's body names the reason: `no video stream in the source` for `hls.ErrNoVideo`, `HLS output failed` otherwise. |
+| 45 | A blocked tune takes back one channel nobody is watching and asks next-source once more: when every profile is full, next-source answers `capacity: {blocked: true, profile_ids}` (each profile full on its own counter, and every profile sharing a credential counter that is full), and the relay waits for a channel on those profiles that is already releasing its slot, or else stops the one on them that has been reclaimable longest, or finds neither; in every case it retries next-source exactly once, and a second blocked answer is 503 `no source available` | `⟨apps/proxy/next_source.py: _refusal⟩`, `⟨apps/m3u/connection_pool.py: blocking_profile_ids, credential_sibling_profile_ids⟩`, `⟨relay/channel/reclaim.go: ReclaimFor⟩`, `⟨relay/httpapi/stream.go: startTune⟩` | `relay/httpapi/reclaim_test.go::TestABlockedTuneReclaimsASilentHLSChannel`, `relay/httpapi/reclaim_test.go::TestABlockedTuneWaitsForAReleaseInFlight`, `relay/httpapi/reclaim_test.go::TestABlockedTuneRetriesOnceWhenNothingIsReleasingOrReclaimable`, `relay/channel/reclaim_test.go::TestEveryMapRemovalInsertsIntoTheReleasingSet`, `relay/channel/reclaim_test.go::TestReclaimForTakesTheLongestReclaimableChannelOnABlockingProfile`, `apps/proxy/tests/test_next_source_capacity.py::test_credential_siblings_are_named`, `e2e/tests/streaming/hls-slot-reclaim.spec.ts::a zap that leaves its session plays the next channel at once`, `e2e/tests/streaming/hls-slot-reclaim.spec.ts::a session silent for more than two target durations yields its slot` | Phase 4a-1c (spec D16, § Slot reclaim; R24). Slots stay Django's decision (ADR 0005): Django names the blocking profiles and the slot script still makes the reservation on the retry; the relay only chooses among channels it knows are unwatched, and never calls Django inside next-source. Initial tunes only: a failover never reclaims. Every removal from the manager's map (`take`, `stopIfStillIdle`, `claim`'s closed-ring delete, the reclaim) puts the channel into the releasing set in the same critical section unless its release has already landed, so a leave that stopped a channel before its release POST completes is waited for rather than missed. |
+| 46 | A watched channel is never reclaimed: a channel with a TS or fMP4 client, an HLS session with a request in flight (an entry waiting for its init segments, a media playlist long-polling for its first segment, a resume between its attach and its commit), or an HLS session whose last request ended 2 × TARGETDURATION ago or less, is not reclaimable; the verdict is re-checked, and the channel's sessions marked STOPPED, in one critical section of the session table's lock, so a request that arrives after the pick is either seen or answered 410 | `⟨relay/session/silence.go: silentLocked, StopIfSilent⟩`, `⟨relay/channel/reclaim.go: reclaimable, reclaimLocked⟩` | `relay/session/silence_test.go::TestSilence`, `relay/httpapi/reclaim_test.go::TestABlockedTuneNeverReclaimsAWatchedChannel`, `relay/httpapi/reclaim_test.go::TestTheReclaimReCheckSeesARequestThatArrivedAfterThePick`, `relay/httpapi/reclaim_test.go::TestAnInFlightRequestHoldsAChannelAgainstReclaim`, `e2e/tests/streaming/hls-slot-reclaim.spec.ts::a session that keeps reloading holds its slot` | Phase 4a-1c (spec D16, § Presence thresholds). Silence is measured from the END of a session's last request and only while none is in flight, so a paused AVPlayer (reloading every 2 s, M7) is never caught, at 4 s for TARGETDURATION 2. The re-check's deterministic seam is `ManagerConfig.ReclaimPicked`, run between the pick and the re-check; without the re-check the pick's stale verdict reclaims a channel with a request in flight on every run. 4a-3 adds a lingering window past its grace to the reclaimable set. |
 <!-- end of matrix -->
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index 64b646e..6b37fc1 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -213,6 +213,7 @@ resolve (see the G8/G10 Gap rows).
 | Streaming | Live HLS failover: an upstream fault on `h264-1080i-aac-ac3` switches the channel to an alternate carrying `mpeg2-576i-mp2`, and the next media playlist carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` with the media sequence continuing and the multivariant's `CODECS` unchanged. `tests/streaming/hls-failover.spec.ts` | 4a-1b | done |
 | Streaming | **Observation (spec Q6, ruling R29), measured on CI's software encoder, not a gate:** the failover gap from the switch (the first status poll naming the alternate) to the new generation's first segment was 8.68 s (CI run 36495275297, one run, at 250 ms poll resolution; the fault-to-flip time was 0.80 s); the software transcode of `h264-1080i-aac-ac3` (1080i → 1080p50, libx264) published 1.044 of real time (42.0 s of segments over the 40 s window, run 36495275297) over a 40 s window under the `streaming` project's two workers. At or above real time, so no finding. `tests/streaming/hls-failover.spec.ts`, `tests/streaming/hls-realtime.spec.ts` | 4a-1b | done |
 | Streaming | **Gap, pinned in Go only:** idle departure (`max(12 s, 6 × TARGETDURATION)`), the resume within 300 s, the sweeper's removals and the self-stop paths are pinned by `relay/session` and `relay/httpapi` tests with an injected clock and a stand-in encoder, never by an E2E that waits out a timeout (ruling R24). No E2E plays HLS in a browser or in AVPlayer: hls.js is 4a-2's `frontend` project, and AVPlayer is the manual gate recorded in the 4a-1b PR body (spec § Testing and gates). | 4a-1b | done |
+| Streaming | Slot reclaim with no wait for the idle timeout (Phase 4a-1c, spec D16, ruling R24), on an M3U account with `max_streams: 1` whose provider also caps connections at 1, so `capacity.blocked` genuinely comes from Django: a zap that `DELETE`s its session plays the next channel at once; a session silent for 5 s (2 × TARGETDURATION + 1 s, below the 12 s idle timeout) yields its slot, and its next request is 410; a session that keeps reloading holds its slot, and the second channel gets 503 `no source available`. `tests/streaming/hls-slot-reclaim.spec.ts`. A `stream_limit: 1` user with `terminate_on_limit_exceeded` off who leaves channel A before tuning B gets B, not 429. `tests/streaming-failover/stream-limit-429.spec.ts` | 4a-1c | done |
 
 The ten G1 rows above are covered by these specs (the two seeding rows
 share one file, as do the two principal rows):
diff --git a/e2e/tests/guards/parity-matrix.ts b/e2e/tests/guards/parity-matrix.ts
index d0298a8..e67db1a 100644
--- a/e2e/tests/guards/parity-matrix.ts
+++ b/e2e/tests/guards/parity-matrix.ts
@@ -592,7 +592,7 @@ export const WHITE_BOX_ONLY: readonly WhiteBoxRow[] = [
  * close a row** — rows are added only by a deliberate extension of the matrix,
  * which is exactly the edit that should take two places and a stated reason.
  */
-export const HIGHEST_ROW_ID = 44;
+export const HIGHEST_ROW_ID = 46;
 
 /**
  * Gate 1's own switch. Flipped to `true` by the PR that closes the last owed
```
<!-- appendix-A-end -->
