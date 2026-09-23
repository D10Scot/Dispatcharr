# Fix plan, category A — Go relay defects carried from the Python relay

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementers are `sonnet`; reviewers are `fable` (or `opus`). This plan implements nothing itself.

**Goal.** Fix the eleven defects the Go relay carried verbatim from the deleted Python relay under spec D5's reproduce-do-not-fix rule. Since stage 2d-4 there is no second implementation to agree with, so each is an ordinary Go defect (spec Amendment A16.12 item 4): a fix changes the Go code, the test that pinned the defect, and — where one exists — the parity-matrix row.

**Architecture.** Stdlib-only Go relay (`relay/`), one process, in-memory channel registry. Six of the seven PRs touch only `relay/`; one (A-5) is mostly `core/relay_events.py`; one (A-7) touches `relay/httpapi/` and one Django serializer. No PR changes a wire contract the relay and Django both depend on, except A-7, which adds one field Django already declares.

**Tech stack.** Go 1.x (stdlib only), Python 3 / Django 6 / DRF for A-5 and A-7.

**Spec.** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § D5 and Amendment **A16.12 item 4** ("#222, #296, #299, #302 and #314: ordinary Go defects now, fixable without a parity obligation"). The other six issues (#24, #119, #221, #227, #233, #306) are the same class and are covered by the same reasoning. `docs/relay-parity-matrix.md` is the regression catalogue each PR reads against.

---

## Header

| field | value |
|---|---|
| Category | A — Go relay defects carried from the Python relay |
| Measurement seed | **`a54b09a9`** (`main`, 2026-09-23, #342). Every `file:line` below was opened there. |
| Ordering | Second of ten: B, **A**, J, C, D, E, G, H, I, F. The lead re-seeds after B merges. B's plan (`origin/docs/fixplan-B`) touches no file this plan touches. |
| PRs, in implementation order | A-1 `fix/A-1-ffmpeg-stderr-parsing` (#24, #227, #299) · A-2 `fix/A-2-buffering-failover-bounds` (#302, #221) · A-3 `fix/A-3-udp-user-agent-flags` (#296) · A-4 `fix/A-4-fmp4-scanner-resync` (#306, #119) · A-5 `fix/A-5-hash-tune-events` (#233) · A-6 `migration/A-6-fmp4-client-timeout` (#222) · A-7 `migration/A-7-detail-ffmpeg-bitrate` (#314) |
| Dependencies | A-1 → A-2 → A-3 share `CLAUDE.md`'s Known-defects list (adjacent bullets) and A-2/A-3 share `relay/channel/source_transcode_test.go`; land them in that order. A-4 and A-5 are independent of everything and may land any time. A-6 and A-7 each edit one `CLAUDE.md` bullet and land after A-3. |
| Decision memos | None. No rule-4 policy item is in category A. |
| upstreamable | **no** for all seven. `relay/` does not exist upstream; A-5's `core/relay_events.py` is fork-only (Phase 1 PR 6). |

### Files this plan touches

| file | PR | change |
|---|---|---|
| `relay/ffmpeg/spawn.go:233-275` | A-1 | hard cap on an unterminated stderr buffer (#24) |
| `relay/ffmpeg/progress.go:25-40` | A-1 | `speedRe` reads the exponent (#227); `IsProgressLine` also accepts `speed=` (#299) |
| `relay/ffmpeg/progress_test.go`, `relay/ffmpeg/spawn_test.go` | A-1 | one test flipped, three new |
| `relay/internal/relaytest/testdata/ffmpeg_stderr/CAPTURE.md:88-98` | A-1 | the #227 bullet says fixed |
| `.github/workflows/go-tests.yml:147-156` | A-1 | comment only (the "#299 owns that" sentence) |
| `relay/ffmpeg/detector.go` | A-2 | `Rearm()` plus a `retryFrom` field (#302) |
| `relay/channel/source_transcode.go:326-344` | A-2 | failed-switch branch calls `Rearm()` (#302) |
| `relay/channel/channel.go:476-482` | A-2 | a buffering switch counts toward `switches` (#221) |
| `relay/channel/failover.go:283-292` | A-2 | doc comment only |
| `relay/channel/source_transcode_test.go`, `relay/ffmpeg/detector_test.go` | A-2, A-3 | two tests flipped (A-2), one flipped (A-3), two new |
| `relay/channel/source_transcode.go:97-119` | A-3 | the flag goes with its dropped value (#296) |
| `relay/output/fmp4.go:133-245` | A-4 | resynchronise by literal `moof` search; keep a 7-byte tail; cap an unbounded fragment (#306, #119) |
| `relay/output/scanner_test.go` | A-4 | one test flipped, four new |
| `core/relay_events.py:46-56`, `:183-216` | A-5 | a non-UUID identifier moves to `details["stream_hash"]` (#233) |
| `core/tests/test_relay_events.py` | A-5 | two new tests |
| `relay/channel/events.go:33-49` | A-5 | doc comment stating the contract |
| `relay/channel/manager_test.go` | A-5 | one new contract test |
| `relay/httpapi/fmp4.go:112-241` | A-6 | the TS loop's health gate and keepalive cap (#222) |
| `relay/httpapi/fmp4_test.go:356-470` | A-6 | one test flipped, one new |
| `relay/httpapi/detail.go:115-133`, `:340-357` | A-7 | emit `ffmpeg_bitrate` from the output bitrate the relay already computes (#314) |
| `relay/httpapi/detail_golden_test.go:24-120`, `:216-244`, `relay/httpapi/testdata/channel_detail.json` | A-7 | one test flipped, golden regenerated |
| `apps/proxy/relay_serializers.py:133` | A-7 | `source_bitrate` deleted |
| `apps/proxy/tests/test_relay_detail_payload_golden.py:43-62` | A-7 | `NEVER_WRITTEN` emptied, fixture gains `ffmpeg_bitrate` |
| `docs/relay-parity-matrix.md` rows 6, 12, 28 (and row 1's, row 4's citations if lines move) | A-1, A-2, A-6 | row rewritten to the fixed behaviour; pin renamed |
| `metrics/curated/defects.yml` | A-1, A-2, A-3, A-6, A-7 | three entries → `fixed`; four new entries at `fixed` |
| `CLAUDE.md` Known defects (`:128`, `:129`, `:130`, `:134`, `:135`, `:136`), plus `:63` (A-1) and `:82` (A-2) | A-1, A-2, A-3, A-6, A-7 | the bullet each PR makes false is deleted; the two other sentences it makes false are rewritten |

### Overlap with other categories

Checked against `sweep-report.md`, every `issues-*.md`, and the B and J plans on origin. No other category's evidence cites a file under `relay/ffmpeg/`, `relay/channel/`, `relay/output/`, `core/relay_events.py` or `apps/proxy/relay_serializers.py`.

| file | other category | assumption | order |
|---|---|---|---|
| `CLAUDE.md` | B, J, and later C–I | J-1/J-2/J-3 edit `CLAUDE.md:77`, `:84`, `:138`, `:154` (J plan, J-1 Step list) — none of them the Known-defects bullets A deletes (`:128-136`) or the two sentences A rewrites (`:63`, `:82`). A edits **only** the bullets listed per PR. Anchor every edit on the bullet's quoted opening text, never on a line number. | A first; J re-anchors |
| `relay/httpapi/*` | J-1 | J-1 edits two comments, `relay/httpapi/stream.go:392-395` and `relay/httpapi/fanout_test.go:443-449`. A edits `fmp4.go`, `fmp4_test.go`, `detail.go`, `detail_golden_test.go` and `testdata/channel_detail.json` — no file in common. | A first (J says so) |
| `apps/proxy/next_source.py` | J-3 (measures it), C (#171) | J's overlap table says "A (#314 serializer fields)" edits it. **It does not**: A-7 edits `apps/proxy/relay_serializers.py`, and A-5 edits `core/relay_events.py`. Neither changes a query next-source runs, so J-3's ledger is unaffected. | no interaction |
| `metrics/curated/defects.yml` | J-1 (`:25`, `hls-proxy-dead`), others later | A edits rows `:21`, `:22`, `:32` and appends four entries. Appending is a merge hazard only against another append; each PR appends at the end in its own commit. | A first |
| `docs/relay-parity-matrix.md` | none | No other category edits the matrix. | — |
| `.github/workflows/go-tests.yml` | G (#16 Node 24 actions) | G bumps `uses:` pins; A-1 edits one comment paragraph at `:147-156` inside the `build` job. Different lines. | A first |

### The two CI gates every Go PR must keep green

**The Go coverage ratchet has no headroom.** `scripts/coverage_relay_go.floor` sets `missing=589`, the worst of 12 CI rounds whose range was 588–589. Measured locally at the seed on 2026-09-23 (this planner, `scripts/coverage_relay_go.sh --measure` then `--report`):

```
shape=go-race-per-package/v1  packages=10  statements=3710  missing=587  coverage=84.18%
```

So a PR that adds **one** uncovered statement can draw 590 in CI and fail. The rule for every PR below: **every new statement is executed by that PR's own new test in its own package** (per-package measurement; a neighbour's test does not count). Each PR's task list carries the check:

```bash
# the PR's base, measured from a clean detached worktree (never from the PR tree with stashed edits)
git -C /Users/dion/git/Dispatcharr worktree add --detach /tmp/cov-base-wt <base-sha>
(cd /tmp/cov-base-wt && scripts/coverage_relay_go.sh --measure /tmp/cov-seed)
# the PR itself
(cd <worktree> && scripts/coverage_relay_go.sh --measure /tmp/cov-pr && scripts/coverage_relay_go.sh --gate /tmp/cov-pr)
diff <(awk 'NR>1 && $3==0 {print $1}' /tmp/cov-seed/relay.coverprofile | LC_ALL=C sort) \
     <(awk 'NR>1 && $3==0 {print $1}' /tmp/cov-pr/relay.coverprofile   | LC_ALL=C sort)
```

The diff may show uncovered blocks **disappearing** (A-4 covers two blocks the seed leaves uncovered at `relay/output/fmp4.go:226.4` and `:231.4`) and may show the documented flapper `relay/buffer/ring.go:262.3`; it must show **no new uncovered block in a file the PR edited**. None of these PRs changes the linked package set or `relay/go.mod`, so `shape`/`packages`/`gomod` stay equal and no `--write-floor` is ever run. **Never lower the floor or raise `missing` in these PRs**; the floor's own header forbids a bump on the PR that drew it.

**The parity-matrix guard.** `e2e/tests/guards/parity-matrix.spec.ts` checks that every Source citation resolves to a line inside its file and every Pin names a real test symbol. A PR that renames a pinning test must rename it in the row in the same commit, or the guard fails. Two facts about when it runs:

- `e2e-tests.yml`'s `changes` job (`:108-133`) sets `guards=true` on a PR only when the diff matches its path pattern **or touches `docs/relay-parity-matrix.md`**. The pattern has no `relay/` prefix. A-1, A-2 and A-6 edit the matrix, so the guard runs on them. A-3, A-4, A-5 and A-7 do not edit it; each must still be checked locally, because A-2's and A-6's row citations point into files those PRs shift.
- Run it locally, no container needed: `cd e2e && npx playwright test --project=guards parity-matrix`.

The missing `relay/` prefix in that pattern is a real gap (a relay-only PR that shifts a cited line past a file's end would pass PR CI and fail on `main`). It is **not** fixed here; it is recorded under Open questions for the lead to route.

---

## Per-issue analysis

Every citation was opened at `a54b09a9`.

### #24 — the stderr reader grows without bound on unterminated `frame=` output

- **Root cause.** `relay/ffmpeg/spawn.go:253-257`: when the buffer holds no CR or LF, it is flushed only if `len(buf) > 1024 && !bytes.Contains(buf, []byte("frame="))`. A delimiter-free stream containing `frame=` never matches, so `buf` grows until EOF (`:274`'s trailing `emit`). This reader runs in the one `relay-go` process that carries every live viewer.
- **Fix.** Add a hard ceiling, `maxPendingStderr = 64 * 1024`. A buffer past it is flushed as one line whatever it contains. The 1 KiB `frame=` exemption stays for its original purpose (not splitting a real progress record, which is about 100 bytes), so memory per reader is bounded at the ceiling plus one 4 KiB read.
- **Tests.** New `TestAnUnterminatedFrameRecordIsFlushedAtTheCeilingNotHeldToEOF` (spawn_test.go), driven like the existing `TestALongUnterminatedLineIsFlushedWhileTheChildStillRuns` (`spawn_test.go:125`): a corpus of about 160 KiB of `frame=1 ` with no terminator, the stand-in kept alive by `--dead-air-after-bytes`, and the assertion that a line arrives while the child lives and is no longer than `maxPendingStderr + 4096`. No existing test changes.
- **Size** S. **upstreamable** no. **Duplicates** none.

### #227 — `speed=` in scientific notation is read as its mantissa

- **Root cause.** `relay/ffmpeg/progress.go:33`: `speedRe = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)` stops at the `e`. The comment at `:25-31` names row 28 and #227.
- **Fix.** `speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?`, the expression `progress_test.go:13`'s `fullSpeedRe` already uses. `strconv.ParseFloat` reads the exponent. The mirror case `speed=9.5e-05x` now reads as `0.000095` and correctly counts as below `buffering_speed`.
- **Tests.** Flip `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` (`progress_test.go:23`) to `TestAScientificNotationSpeedIsReadWithItsExponent` (listed under A-1). Add two regression rows to `TestParseProgressReadsTheRealRecordShapes`' table (`:52-63`) from the issue body: `speed=1.82e+03x` → 1820 and `speed=9.5e-05x` → 0.000095.
- **Size** S. **upstreamable** no. **Duplicates** none. Ledger entry `ffmpeg-speed-scientific-notation` (`defects.yml:32`).

### #299 — the progress gate is blind on ffmpeg 6.x stream-copy lines

- **Root cause.** `relay/ffmpeg/progress.go:40`: `IsProgressLine` is `strings.Contains(line, "frame=")`. On ffmpeg 6.x a `-c copy` progress line begins `size=` and has no `frame=` (issue body, measured on 6.1.1), so `source_transcode.go:234` never calls `progress()`, `ffmpeg_speed` is never recorded and the buffering detector never arms. The shipped ffmpeg 8.1.2 is unaffected.
- **Fix.** `IsProgressLine` returns true for `frame=` **or** `speed=`. Every progress record of every major carries `speed=`; `ParseProgress` already refuses a line that yields none of its three fields. The `frame=` exemption in the stderr flush guard (#24) is not widened, because a 6.x record is about 80 bytes and never reaches 1 KiB.
- **Tests.** Change the second assertion of `TestAnUnparseableNumberDropsTheWholeRecord` (`progress_test.go:103-107`) — listed under A-1. New `TestAnFFmpeg6StreamCopyRecordIsAProgressLine` using the issue's literal line `size=     464kB time=00:00:07.74 bitrate= 490.4kbits/s speed=1.08x`: gated in, parsed to speed 1.08 and bitrate 490.4. A real 6.x corpus capture is **not** required. The line is quoted from the issue's measurement, and `CAPTURE.md`'s corpus rule governs replayed files, not inline literals.
- **Size** S. **upstreamable** no. **Duplicates** none. Not in the ledger; CLAUDE.md lists it (`:135`), so A-1 adds a ledger entry at `fixed`.

### #302 — a failed buffering switch asks next-source on every progress record

- **Root cause.** `relay/channel/source_transcode.go:326-344`: on `ffmpeg.TimedOut` the reader calls `failoverFromBuffering`. On failure (`:342-343`) it only logs. `relay/ffmpeg/detector.go:86-88` returns `TimedOut` again on the next sub-threshold sample, because `since` is unchanged, so every record (about every 0.5 s in production) makes another control-plane call. `failover.go:298-300` returns false without touching the detector.
- **Fix.** Add `Detector.Rearm()`: the channel stays buffering and the next timeout is measured from now. The failed-switch branch calls it, so a channel with no alternate asks once per `buffering_timeout` window, not once per record. `BufferingFor()` keeps measuring from the first sub-threshold sample, so a later successful switch's `channel_failover.duration` stays truthful. That needs a second field (`retryFrom`), not a reset of `since`. Appendix A has the hunk.
- **Tests.** Flip `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` (`source_transcode_test.go:442`) to `TestAFailedBufferingSwitchAsksOncePerTimeoutWindowNotOnEveryRecord` (listed under A-2). New `TestRearmStartsAFreshTimeoutWindowButKeepsTheBufferingDuration` in `detector_test.go`. It also covers `BufferingFor` (`detector.go:105-114`), which the seed profile shows uncovered, and gains the ratchet some headroom.
- **Size** S. **upstreamable** no. **Duplicates** none. CLAUDE.md `:129`; A-2 adds a ledger entry at `fixed`.

### #221 — MAX_STREAM_SWITCHES does not bound buffering-triggered switches

- **Root cause.** `relay/channel/channel.go:455-457`: `switches` is a local of `run`, and only the health-monitor branch (`:539-541`) and the exhausted-URL branch (`:550-552`) increment it. The buffering switch is adopted at `:476-482` (`takePending`) and deliberately does not count (the comment at `:479` says "row 6").
- **Fix.** Increment `switches` in the `takePending` branch. The outer condition at `:457` then ends the loop exactly as it does after a main-loop switch. The rule is one counter for every automatic switch, with no new state, lock or field. The stable-run reset at `:488-493` applies unchanged. Alternative considered: refuse the switch and keep playing the slow stream. It is under Open questions, because it changes what a user sees, and the recommended form is the one that matches the main loop's existing, pinned semantics (`failover_test.go:604`).
- **Tests.** Flip `TestABufferingFailoverIgnoresMaxStreamSwitches` (`source_transcode_test.go:396`) to `TestABufferingFailoverCountsTowardMaxStreamSwitches` (listed under A-2). Its sibling `TestMaxStreamSwitchesBoundsAMainLoopSwitch` (`failover_test.go:604`) is unchanged and stays in row 6's Pin cell.
- **Size** S. **upstreamable** no. **Duplicates** none. Ledger `max-stream-switches-unbounded` (`defects.yml:21`).

### #296 — the UDP user-agent filter leaves dangling flags

- **Root cause.** `relay/channel/source_transcode.go:105-119`: on a `udp://` URL every argument containing the user agent, `user-agent` or `user_agent` is dropped, but the flag that introduced a dropped *value* is kept. `-headers 'User-Agent: X'` spawns as a bare `-headers` whose value becomes `-i`. `source_transcode_test.go:569-585`'s `want` keeps the bare `-headers` on purpose.
- **Fix.** When a dropped argument is a value (it does not begin with `-`) and the argument kept just before it is a flag (begins with `-`), drop that flag too. A dropped argument that is itself a flag (`-user_agent`) removes nothing before it; its own value is then dropped by the same user-agent match. Removing only the `User-Agent:` line from a multi-header `-headers` value is **out of scope**: this fix loses the other headers on a UDP upstream, where HTTP headers are meaningless anyway.
- **Tests.** Change `TestTheUDPFilterDropsUserAgentArguments`' `want` (listed under A-3). New `TestAValuelessFlagBeforeADroppedFlagIsKept`, which pins the boundary: `-re -user_agent X -i udp://…` keeps `-re`.
- **Size** S. **upstreamable** no. **Duplicates** none. CLAUDE.md `:134`; A-3 adds a ledger entry at `fixed`.

### #306 and #119 — the fMP4 scanner's resynchronisation discards instead of resynchronising

The two issues share one root cause and one PR closes both. **Not tracker duplicates:** #119 also asks for the stride to be bounded (its "cap the stride" suggestion), which A-4 does as the unbounded-fragment cap. Both numbers stay open until A-4 merges and both close with it.

- **Root cause.** `relay/output/fmp4.go:216-227`: when the working buffer does not start at a `moof`, `flush` calls `findMoofOffset(s.frag, 1)`. `findMoofOffset` (`:145-165`) walks by box length. From offset 1 it re-reads a length at a one-byte shift, and any value of 8 or more is a stride (`:156-162`). A garbage byte `0x01` reads as 16 MiB, jumps past the real `moof` and returns -1. `:222-224` then clears the whole buffer, losing the fragments behind the misalignment. The doc comment at `:136-140` claims recovery "at the next real box header either way", which is false. Two adjacent faults surface on the same path:
  - A `moof` whose own length is below 8 makes `:229-231` return without consuming anything. The buffer never advances and grows with every write.
  - A corrupt length on the box after a valid `moof` makes `:238-240` return -1 ("not complete yet") indefinitely. `s.frag` grows toward that length, up to 4 GiB.
- **Fix.** Replace the resync call with a literal search for the four bytes `moof` at a type position of 5 or more, which puts the box start at 1 or more. Accept a candidate only when its length is at least 16, the minimum `moof` holding an `mfhd`. When nothing is found, keep the last 7 bytes instead of clearing the buffer, so a header split across two reads survives. Treat an aligned `moof` with length below 16 as misaligned. Cap `s.frag` at `MaxFragmentBytes`: past it, with no fragment bound found, resynchronise from offset 1. The cap is 64 MiB, which is 50 Mbit/s times a 10-second keyframe interval with margin; see Open questions. `findMoofOffset` itself is unchanged for the init-segment path, which already has its 10 MB abort (`:188-189`), and its doc comment is corrected. Appendix B has the hunk.
- **Tests.** Flip `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` (`scanner_test.go:181`) to `TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof` (listed under A-4). New tests:
  - `TestAGarbageByteThatReadsAsAHugeLengthDoesNotHideTheNextMoof`, #119's shrunk counterexample `\x01` + fragment.
  - `TestAMoofHeaderSplitAcrossReadsAfterGarbageIsStillFound`.
  - `TestAMoofShorterThanItsOwnHeaderIsSkippedNotStuckOn`.
  - `TestAFragmentPastTheCeilingIsAbandonedNotBufferedForever`.
  - The existing `TestABoxLengthBelowEightAdvancesOneByteRatherThanGivingUp` (`:220`) tests `findMoofOffset` directly and is unchanged.
- **Size** M. **upstreamable** no.

### #233 — a stream-by-hash tune raises no persisted channel_start or channel_stop

- **Root cause.** The relay puts the tune identifier in `channel_id` whatever it is: `relay/channel/events.go:38` (`ChannelID: c.id`), raised at `manager.go:310` (`channel_start`) and `channel.go:442` (the deferred `emitStop`). For the admin single-stream preview the identifier is a 64-hex `stream_hash` (`apps/proxy/next_source.py:247-257`'s fallback). `apps/proxy/relay_serializers.py`'s event serializer accepts any string (`channel_id = CharField(required=False)`). `core/relay_events.py:46-56`'s `_clean` maps only `""` to None. `log_system_event` (`core/utils.py:890-924`) then hits `SystemEvent.channel_id`, a `UUIDField` (`core/models.py:817`), and its bare `except Exception` (`:922-924`) swallows the `ValidationError`. No row is written, no Connect fan-out runs, and one ERROR log line is written per event. The issue body blames "the event serializer"; the mechanism is the model field, but the outcome is the same.
- **Fix, Django side (the fix).** A `_split_identifier` helper in `core/relay_events.py`. A value that parses as a UUID stays `channel_id`. Anything else becomes `channel_id=None` plus `details["stream_hash"]`, unless `details` already carries one. It applies to every event type, so `client_connect`, `stream_switch` and the rest of a hash tune are written too. `channel_name` already carries the stream's name for a hash tune (`next_source.py:663`). The WebSocket push (`_push`) is unchanged and still carries the raw identifier.
- **Relay side (a contract, not a change).** The relay keeps posting the identifier verbatim. Classifying it in Go would need a second copy of the UUID rule and change the wire for no gain, because Django owns the `UUIDField` and must defend it against any poster anyway. A-5 adds a doc paragraph to `relay/channel/events.go` stating the contract, and a Go test pinning it: a channel claimed under a non-UUID identifier emits `channel_start` and `channel_stop` with that identifier in `ChannelID`. A later Go change that dropped or rewrote it would break Django's classification silently. The test makes that change visible.
- **Tests.** New in `core/tests/test_relay_events.py`:
  - `test_a_stream_hash_identifier_writes_a_row_with_the_hash_in_details`, which is red at the seed: zero rows, one ERROR log.
  - `test_an_explicit_stream_hash_in_details_is_not_overwritten`.
  - The existing `test_each_event_becomes_a_system_event_row` and `test_an_event_without_a_channel_id_still_writes_a_row` are unchanged and guard the UUID and empty paths.
  - New Go test `TestAHashIdentifiedChannelReportsItsIdentifierAsTheChannelID` in `relay/channel/manager_test.go`.
- **Size** S. **upstreamable** no. **Duplicates** none.

### #222 — an fMP4 viewer is dropped on elapsed time alone

- **Root cause.** `relay/httpapi/fmp4.go:229-236`: once `ClientTimeout` (`STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD`, 40 s by default) passes with no fragment, the client is dropped. There is no health gate and no keepalive cap. The TS loop drops only an unhealthy channel's client (`relay/httpapi/stream.go:1023`), and before that holds it on keepalives for up to `MaxKeepalive` (`:1005-1022`). So a failover slower than 40 s drops fMP4 viewers and keeps TS ones. The doc comment at `fmp4.go:112-158` is the row in prose.
- **Fix.** Give the fMP4 loop the TS loop's exits, less the one fMP4 cannot perform:
  - **Healthy channel:** no silence drop, as on TS.
  - **Unhealthy channel:** a wall-clock cap of `MaxKeepalive` from the moment the stall is first seen unhealthy, which is TS's reachable exit (`stream.go:1009-1013`).
  - **No bytes are sent.** fMP4 has no null-packet equivalent, and a partial box would corrupt the player's parse.
  - The `url_switching` exemption stays unported on both loops. The reason the doc comment gives at `:134-144` still holds.
  - **Residual, stated rather than hidden.** A remux wedged alive on a healthy channel now holds its fMP4 clients until they hang up. That is no worse than today: dropping them never cured the wedge, because a reconnecting client rejoins the same shared remux (`relay/output`, one per channel). A remux-liveness watchdog is new work; see Open questions.
  - Appendix C has the hunk.
- **Tests.** Flip `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` (`fmp4_test.go:384`) to `TestAStalledFMP4ClientStaysConnectedLikeATSClientWhileTheChannelIsHealthy` (listed under A-6). New `TestAnFMP4ClientOnAnUnhealthyChannelIsDroppedAfterMaxKeepalive`, modelled on `keepalive_test.go:109`'s compressed `MAX_KEEPALIVE_DURATION` and `failover_test.go:59`'s compressed `CONNECTION_TIMEOUT`/`HEALTH_CHECK_INTERVAL`.
- **Size** M. **upstreamable** no. **Duplicates** none. Ledger `fmp4-timeout-no-switch-exemption` (`defects.yml:22`).

### #314 — `source_bitrate` and `ffmpeg_bitrate` are declared and emitted by nothing

- **Root cause.** `apps/proxy/relay_serializers.py:133` (`source_bitrate`) and `:141` (`ffmpeg_bitrate`) are declared on `RelayChannelDetailSerializer`. `relay/httpapi/detail.go`'s `detailPayload` (`:134-175`) carries neither, by design (comment `:118-133`), although the relay computes the output bitrate on every progress record (`relay/channel/stats.go:39`, `:105-107`, `FFmpegOutputBitrate`) and drops it. The Python name mismatch the issue describes went with `live_proxy/`; only the Go absence and the Django declaration remain.
- **Fix.**
  - **`ffmpeg_bitrate`:** add `FFmpegBitrate string `json:"ffmpeg_bitrate,omitempty"`` to `detailPayload` in serializer declaration order, between `ActualFPS` and `StreamType`. `describeChannelDetail` renders it as `pythonFloat(*stats.FFmpegOutputBitrate)`, the same string form as its neighbours `ffmpeg_fps` and `actual_fps` (`detail.go:345-350`); the serializer field is a `CharField`.
  - **`source_bitrate`:** delete it from the serializer. No writer exists and no frontend code reads it (`grep -rn source_bitrate frontend/src` is empty at the seed). A real source bitrate needs an input-side measurement nobody has specified, which is feature work, not a fix. Open questions has the alternative.
- **Tests.** Flip `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` (`detail_golden_test.go:222`) to `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate` (listed under A-7). Empty `NEVER_WRITTEN` in `apps/proxy/tests/test_relay_detail_payload_golden.py:49-62`, which leaves the completeness test (`test_the_fixture_covers_every_serializer_field`) pinning every remaining field, and give `fixture()` an `ffmpeg_bitrate`. Regenerate `relay/httpapi/testdata/channel_detail.json` with `DISPATCHARR_WRITE_GOLDEN=1`. Add a render test (`TestDescribeChannelDetailRendersTheOutputBitrateAsAPythonFloatString`) in the httpapi package that drives `describeChannelDetail` over a channel whose stats carry an output bitrate, so the new statements are covered by their own package.
- **Size** S. **upstreamable** no. **Duplicates** none. CLAUDE.md `:136`; A-7 adds a ledger entry at `fixed`.

---

## PR sections

Every PR follows the commit discipline of `CLAUDE.md`:

- Stage and commit in separate Bash calls.
- Write the message with the Write tool and commit with `-F`.
- Anchor every command on the PR's own worktree, `cd /Users/dion/git/Dispatcharr/.worktrees/<branch-leaf> && …`.
- The Go PostToolUse hook runs build, vet, lint and `-race` on the edited package for every `.go` edit. **Keep prototypes out of commits.** A break-check is an edit you revert before staging, never one you commit.

Every break-check below is run the same way: make the named wrong edit, run the named test, and confirm it fails **with a message naming the mechanism** (a red for a side reason is not a pass). Then revert and confirm green.

### A-1 — `fix/A-1-ffmpeg-stderr-parsing` (#24, #227, #299)

- **Files.** `relay/ffmpeg/spawn.go`, `relay/ffmpeg/progress.go`, `relay/ffmpeg/progress_test.go`, `relay/ffmpeg/spawn_test.go`, `relay/internal/relaytest/testdata/ffmpeg_stderr/CAPTURE.md`, `.github/workflows/go-tests.yml` (comment), `docs/relay-parity-matrix.md` (row 28; row 4's citation only if lines move), `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** `python scripts/ci_backend_test_labels.py relay/ffmpeg/progress.go` prints `[]`, so no backend label runs. Go: `go-tests.yml` (build, vet, `-race`, lint under three GOOS, credlint, coverage gate). The guards project runs because the matrix is in the diff. The workflow edit triggers the zizmor hook, and the file must stay at zero findings.

Tasks:

- [ ] **1. Seed coverage.** Measure the seed profile per "The two CI gates" above and keep it.
- [ ] **2. #227 red first.** Flip the pin. `progress_test.go:15-46` becomes `TestAScientificNotationSpeedIsReadWithItsExponent`.
  - Before: `if *p.Speed != mantissa` fails; `if *p.Speed >= actual/100` fails with "#227 appears to have been fixed".
  - After: `if *p.Speed != actual { t.Fatalf("Speed = %v, want the full value %v read with its exponent", *p.Speed, actual) }`. The corpus-shape guard (`actual/mantissa < 100` → re-derive) is kept verbatim. Delete the "PINS A DEFECT … Do not fix this" header and replace it with one naming #227 as fixed.
  - Run `cd relay && go test -run TestAScientificNotationSpeedIsReadWithItsExponent ./ffmpeg/`. It must be **red** at the seed regex, reporting `Speed = 1.41, want … 1410`.
- [ ] **3. #227 fix.** Replace `speedRe` (`progress.go:33`) and rewrite the comment at `:25-31` to state that the exponent is read and why (the truncation capture). Add the two table rows to `TestParseProgressReadsTheRealRecordShapes`. Green.
  - **Break-check 3a:** revert the regex, and the flipped test goes red naming the mantissa.
- [ ] **4. #299 red first.** In `TestAnUnparseableNumberDropsTheWholeRecord` (`:103-107`):
  - Before: `if IsProgressLine("fps=25 speed=1.0x") { t.Fatal("a line without frame= is not a progress record …") }`.
  - After: `if IsProgressLine("fps=25 q=-1.0") { t.Fatal("a line with neither frame= nor speed= is not a progress record") }`. The meaning moves from "frame= only" to "frame= or speed=", and that behaviour is what this PR changes.
  - Add `TestAnFFmpeg6StreamCopyRecordIsAProgressLine`: the issue's line is gated in, `ParseProgress` gives speed 1.08 and bitrate 490.4, and `TestAnUnparseableNumberDropsTheWholeRecord`'s `frame=` positive case still holds. Red at the seed.
- [ ] **5. #299 fix.** `func IsProgressLine(line string) bool { return strings.Contains(line, "frame=") || strings.Contains(line, "speed=") }`. Rewrite the comment at `:38-39` to name both majors. Green.
  - **Break-check 5a:** drop the `speed=` clause, and the new test goes red.
- [ ] **6. #24 red first.** Add `TestAnUnterminatedFrameRecordIsFlushedAtTheCeilingNotHeldToEOF` to `spawn_test.go`, beside `:125`: corpus `strings.Repeat("frame=1 ", 20_000)`, child kept alive, 5 s deadline. Red at the seed: nothing arrives while the child lives.
- [ ] **7. #24 fix.** In `ReadStderr` (`spawn.go:253-257`) the no-terminator branch becomes `if len(buf) > maxPendingStderr || (len(buf) > 1024 && !bytes.Contains(buf, frameMarker))`, with `const maxPendingStderr = 64 * 1024` documented beside the 1 KiB rule in the doc comment at `:226-238`. Green.
  - **Break-check 7a:** set the ceiling to `1 << 30`, and the test goes red.
  - **Break-check 7b:** delete the ceiling clause, and the test goes red.
- [ ] **8. Matrix row 28.** Rewrite the Behaviour cell to the fixed behaviour: "`ffmpeg_speed` is parsed with its exponent: `speed=1.41e+03x` reports 1410". Keep the Source citations and re-anchor their line ranges if `progress.go` moved. The Pin becomes `relay/ffmpeg/progress_test.go::TestAScientificNotationSpeedIsReadWithItsExponent`. The Notes open with "Fixed by #<A-1 PR> (issue #227); reproduced per D5 until stage 2d-4 retired the obligation." One line, no padding. Check row 4's `relay/ffmpeg/progress.go:20-40` citation still lands inside the file (it will). Run the guard.
- [ ] **9. Prose.**
  - `CAPTURE.md:88-98`'s #227 bullet: "Reproduced here, not fixed" becomes "Fixed by #<PR>: the parser now reads the exponent; the capture remains the regression input."
  - `go-tests.yml:147-156`: replace "so ffmpeg 6.x is blind to every progress line … Do not widen the parser or this test to accommodate 6.x -- #299 owns that." with a sentence saying the gate accepts `speed=` since #<PR>, and that row 4's real-ffmpeg pin still runs against the production 8.1.2 because its measured shape (the burn-off) is that version's.
  - `CLAUDE.md`: delete the bullet beginning "**The buffering-progress gate is structurally blind on ffmpeg 6.x" (`:135`). Also rewrite the end of the Test-hooks bullet on `scripts/check_go_credential_logging.sh` (`:63`). Its clause "ffmpeg 6.1.1 (ubuntu-latest's own apt) omits `frame=` from stream-copy progress lines, so the verbatim-ported `IsProgressLine` gate never passes and the pin fails rather than skips when `CI` is set" becomes a statement that the gate accepts `speed=` since #<PR>, and that the job keeps the production ffmpeg because row 4's measured burn-off shape is that version's. Anchor on the quoted text.
- [ ] **10. Ledger.**
  - `ffmpeg-speed-scientific-notation` (`defects.yml:32`): `status: fixed`, `fixed_in: <PR>`, `status_changed: <merge date>`.
  - Append `{id: ffmpeg6-progress-gate-blind, title: "The progress gate keyed on frame=, which ffmpeg 6.x stream-copy records do not carry", area: correctness, severity: low, status: fixed, source: null, issue: 299, test: relay/ffmpeg/progress_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-14, status_changed: <date>}`.
  - #24 has no ledger entry and no CLAUDE.md bullet; add none.
  - Run `python -m metrics.build --validate-only --curated metrics/curated`.
- [ ] **11. Gates.** Coverage diff per the header (expected: three to five new statements, all executed by tasks 2–7's tests; no new uncovered block in `relay/ffmpeg/`). `cd e2e && npx playwright test --project=guards parity-matrix`. `cd relay && go test -race ./ffmpeg/ ./channel/`; the channel package consumes `IsProgressLine`, so its buffering tests are the integration check.

PR description draft:

> **fix(relay): the ffmpeg stderr reader and progress parser — #24, #227, #299**
>
> Three defects the Go relay carried verbatim from the Python relay under spec D5. Since stage 2d-4 they are ordinary Go defects (A16.12 item 4).
>
> - **#24.** The stderr reader never flushed an unterminated buffer containing `frame=`, so it grew until EOF inside the process that carries every live viewer. It now has a 64 KiB ceiling.
> - **#227.** `speed=1.41e+03x` was read as 1.41. The regex now reads the exponent. Parity-matrix row 28 is rewritten and its pin flipped.
> - **#299.** On ffmpeg 6.x a stream-copy progress line carries no `frame=`, so the buffering detector could never arm. The gate now also accepts `speed=`.
>
> Tests changed under the fix plan's rule 5: `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` becomes `…IsReadWithItsExponent`, shown red before the fix. One assertion in `TestAnUnparseableNumberDropsTheWholeRecord` changes from "no `frame=` means no record" to "neither `frame=` nor `speed=` means no record". Both before and after assertions are in the plan.
>
> Go coverage ratchet: no new uncovered block (diff attached); floor untouched. Ledger: `ffmpeg-speed-scientific-notation` is set to fixed, and a new entry for #299 is added at fixed.
>
> Closes #24, #227, #299.

### A-2 — `fix/A-2-buffering-failover-bounds` (#302, #221)

- **Files.** `relay/ffmpeg/detector.go`, `relay/ffmpeg/detector_test.go`, `relay/channel/source_transcode.go`, `relay/channel/channel.go`, `relay/channel/failover.go` (comment), `relay/channel/source_transcode_test.go`, `docs/relay-parity-matrix.md` (row 6; row 1's citation line range), `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** Backend `[]`. Go as A-1. Guards run because the matrix is edited.

Tasks:

- [ ] **1. Seed coverage** (the tree after A-1 merged).
- [ ] **2. #302 red first.** Flip `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` (`source_transcode_test.go:436-470`) to `TestAFailedBufferingSwitchAsksOncePerTimeoutWindowNotOnEveryRecord`. Same rig: slow-trickle corpus at 0.02 s, API-maximum threshold, 1 s timeout, `fakeResolver{}` always answering `ErrNoAlternate`.
  - **Before:** `waitFor(… ">= 1")` then `waitFor(… "a third failed switch, one per record" … >= 3)` within 10 s. It passes in about 60 ms at the seed. Then state is buffering and the channel is not done.
  - **After:**
    1. `waitFor(… first request …)`.
    2. Record `t0`. Then `time.Sleep(700 * time.Millisecond)` and assert `len(resolver.requests()) == 1`. At one record per 20 ms, the seed makes about 35 calls here, so this is the red.
    3. `waitFor(t, "the second window's single request", 5*time.Second, func() bool { return len(resolver.requests()) >= 2 })` and assert the gap between the two requests is at least `900ms`. That is a lower bound only, 0.1 s under the 1 s timeout, the same allowance `failover_test.go:369-392` makes for #309.
    4. Keep the state-is-buffering and not-done assertions verbatim.
  - The 700 ms window is 0.7 of the timeout. Per the "latching conditions" rule, widen that window if it flakes; never raise the asserted count.
  - Red at the seed with "resolver asked N times inside one window, want 1".
- [ ] **3. #302 fix.** Appendix A's hunk: `detector.go` gains `retryFrom time.Time`. `Observe`'s timeout test uses the later of `since` and `retryFrom`. `Rearm()` sets `retryFrom = now()`. `Reset()` and the `Ended` edge clear it. `source_transcode.go:342-343`'s failure branch calls `r.detector.Rearm()` after its log line. Rewrite the `:327-332` comment ("one control-plane call per progress record … reproduced and filed") to describe the new behaviour. Add `TestRearmStartsAFreshTimeoutWindowButKeepsTheBufferingDuration` to `detector_test.go`, with an injected clock:
  - Started at t=0; TimedOut at t=1.1 s; `Rearm()`.
  - At t=1.5 s, Continuing.
  - At t=2.2 s, TimedOut; `BufferingFor()` is 2.2 s, not 1.1 s.
  - Green.
  - **Break-check 3a:** remove the `Rearm()` call, and the flipped channel test goes red.
  - **Break-check 3b:** make `Rearm()` also reset `since`, and the detector test's `BufferingFor` assertion goes red.
- [ ] **4. #221 red first.** Flip `TestABufferingFailoverIgnoresMaxStreamSwitches` (`:387-434`) to `TestABufferingFailoverCountsTowardMaxStreamSwitches`. Same rig, `MaxStreamSwitches = 0`.
  - **Before:**
    1. `waitFor(… ch.Source().StreamID == 2)`.
    2. `waitFor(… ran.get() == 1)`, meaning the alternate's child ran.
    3. After 300 ms, `state == StateActive`.
    4. Exactly one `channel_failover`.
  - **After:** mirror the sibling `TestMaxStreamSwitchesBoundsAMainLoopSwitch` (`failover_test.go:604-624`):
    1. `select { case <-ch.Done(): case <-time.After(15 * time.Second): t.Fatal(…) }`.
    2. `ch.State() == StateError`.
    3. `len(resolver.requests()) == 1` (the switch itself happened).
    4. `ran.get() == 0` (the alternate never ran).
    5. Exactly one `channel_failover` with `reason: buffering_timeout`.
  - Rewrite the header comment: row 6 is now "both paths share one bound".
  - Red at the seed. The channel stays active and the alternate runs.
- [ ] **5. #221 fix.** `channel.go:476-482`: inside `if resolved := c.takePending(); resolved != nil {` add `switches++` before `source = resolved.Source`. Rewrite the comment at `:477-479` ("It never touched `switches`: row 6") and the `run` doc comment's matching sentence (`:428-429`). Update `failover.go:283-292`'s "It never touches the main loop's switch counter, which is row 6" to say the run loop counts the adopted switch. Green.
  - **Break-check 5a:** delete `switches++`, and the flipped test goes red on `ran.get() == 1`.
  - **Also run** `TestASustainedSubThresholdSpeedFailsTheChannelOver`, row 1's pin. It must stay green unedited: `transcodeTuning` (`source_transcode_test.go:43`) starts from `testTuning()`, whose `MaxStreamSwitches` is 10 (`manager_test.go:32`), so one buffering switch is within budget.
- [ ] **6. Matrix.**
  - **Row 6.** Behaviour: "`MAX_STREAM_SWITCHES` bounds every automatic switch, the buffering-triggered one included: the run loop counts a switch the stderr reader parked". Source: `relay/channel/channel.go:<new range>`, `relay/channel/failover.go:<new range>`. Pin: `relay/channel/source_transcode_test.go::TestABufferingFailoverCountsTowardMaxStreamSwitches`, `relay/channel/failover_test.go::TestMaxStreamSwitchesBoundsAMainLoopSwitch`. Notes open with "Fixed by #<PR> (issue #221); reproduced per D5 until stage 2d-4."
  - **Row 1.** Re-anchor `relay/channel/source_transcode.go:320-341` on the moved lines.
  - Run the guard.
- [ ] **7. Prose and ledger.**
  - `CLAUDE.md`: delete the bullets beginning "`MAX_STREAM_SWITCHES` doesn't bound buffering-triggered switches" (`:128`) and "**A buffering timeout with no alternate asks `next-source` on every progress record**" (`:129`). Also rewrite the State paragraph's clause "the buffering-triggered switch bypasses `MAX_STREAM_SWITCHES` as in Python (row 6)" (`:82`) to "every automatic switch, the buffering-triggered one included, counts toward `MAX_STREAM_SWITCHES` (row 6, since #<PR>)". Anchor on the quoted text.
  - Ledger `max-stream-switches-unbounded` (`:21`): set to `fixed`.
  - Append `{id: buffering-timeout-asks-every-record, title: "A buffering timeout with no alternate asked next-source on every progress record", area: correctness, severity: low, status: fixed, source: null, issue: 302, test: relay/channel/source_transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-15, status_changed: <date>}`.
  - Validate.
- [ ] **8. Gates.** Coverage diff: `Rearm` and `retryFrom` add about four statements, covered by task 3's detector test; `switches++` is one statement, covered by task 4. The detector test also covers `BufferingFor` (`detector.go:105-114`), which the seed shows uncovered, so `missing` should fall. Run `go test -race -count=3 -run 'Buffering|MaxStreamSwitches' ./channel/`, three runs because these are timing tests. Run the guard.

PR description draft:

> **fix(relay): buffering failover — one ask per timeout window (#302), and MAX_STREAM_SWITCHES counts it (#221)**
>
> - **#302.** After a buffering switch found no alternate, the stderr reader asked next-source again on every progress record, about twice a second. `Detector.Rearm()` restarts the timeout window while keeping the channel buffering, so the control plane is asked once per `buffering_timeout`. `channel_failover.duration` still measures from the first slow sample.
> - **#221.** A switch parked by the stderr reader now increments the run loop's `switches`. `MAX_STREAM_SWITCHES` bounds it exactly as it bounds a health or connect-failure switch, matching the sibling pin `TestMaxStreamSwitchesBoundsAMainLoopSwitch`.
>
> Both flipped tests are shown red at the seed and green after; before/after assertions are in the plan. Row 6 is rewritten. Ledger: #221's entry is set to fixed, and a new entry for #302 is added at fixed. Go ratchet: `missing` falls.
>
> Closes #221, #302.

### A-3 — `fix/A-3-udp-user-agent-flags` (#296)

- **Files.** `relay/channel/source_transcode.go:97-119`, `relay/channel/source_transcode_test.go:566-585`, `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** Backend `[]`. Go. No matrix row, so run the guard locally, because A-2's row citations point into `source_transcode.go`.

Tasks:

- [ ] **1. Red first.** `TestTheUDPFilterDropsUserAgentArguments` (`:569`):
  - **Before:** `want := []string{"-headers", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}`, with the comment calling the kept `-headers` a reproduced defect.
  - **After:** `want := []string{"-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}`, with the comment rewritten to name #296 as fixed. The HTTP half is unchanged.
  - Add `TestAValuelessFlagBeforeADroppedFlagIsKept`: argv `-re -user_agent VLC/3 -i udp://…` on UDP gives `-re -i udp://…`.
  - The first test is red at the seed. The second is green at the seed and pins the boundary the fix must not cross.
- [ ] **2. Fix.** In `argv()`, when an argument is dropped and it does not begin with `-`, pop the last kept element if it begins with `-` **and** it was the immediately preceding argument. Track the previous index; do not pop a flag separated by a kept value. Rewrite the doc comment `:97-104`. Green.
  - **Break-check 2a:** pop the preceding flag unconditionally, and the second test goes red on `-re`.
  - **Break-check 2b:** remove the pop, and the first test goes red.
- [ ] **3. Prose and ledger.**
  - `CLAUDE.md`: delete the bullet beginning "**The UDP user-agent filter leaves dangling flags**" (`:134`).
  - Append `{id: udp-user-agent-dangling-flag, title: "The UDP user-agent filter dropped a flag's value and kept the flag", area: correctness, severity: low, status: fixed, source: null, issue: 296, test: relay/channel/source_transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-14, status_changed: <date>}`.
  - Validate.
- [ ] **4. Gates.** Coverage diff: about two statements, both covered by task 1's tests. Guard run locally.

PR description draft:

> **fix(relay): the UDP user-agent filter drops the flag with its value (#296)**
>
> On a `udp://` upstream the filter dropped `'User-Agent: X'` and kept `-headers`, so ffmpeg read `-i` as the header value. A dropped value now takes the flag immediately before it; a dropped flag takes nothing before it. `TestTheUDPFilterDropsUserAgentArguments`' expected argv changes (before/after in the plan), and a new boundary test pins that a valueless flag before a dropped flag survives. Ledger: new entry for #296 at fixed.
>
> Closes #296.

### A-4 — `fix/A-4-fmp4-scanner-resync` (#306, #119)

- **Files.** `relay/output/fmp4.go:130-245`, `relay/output/scanner_test.go`.
- **Test labels.** Backend `[]`. Go. No matrix row and no ledger entry. Run the guard locally anyway, because `relay/output/fmp4.go` is not cited by any row at the seed (verify with `grep -n 'relay/output/fmp4.go' docs/relay-parity-matrix.md`).

Tasks:

- [ ] **1. Red first.** Flip `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` (`:181-218`) to `TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof`. Same input: a 72-byte `junk` box, then fragments 5 and 6.
  - **Before:** `len(collect(f)) == 0` and `f.Head() == 0`, per the lines after `:215`; read them in full before editing.
  - **After:** exactly one fragment is published, with `relaytest.FMP4FragmentIndex(got[0]) == 5`, and fragment 6 is held back. Rewrite the comment block `:182-203` to state the fix and keep the Python-verification paragraph as history.
  - Add the four new tests named in the per-issue section. #119's regression example is `[]byte{0x01}` followed by `relaytest.SyntheticFMP4Fragment(0)` and `SyntheticFMP4Fragment(1)`, which publishes fragment 0. The split-read test feeds garbage plus the first 6 bytes of a `moof` header in one write and the rest in the next. The ceiling test lowers the cap through an unexported package variable the test sets, rather than feeding 64 MiB, and asserts the scanner drops to the next literal `moof`.
  - All red at the seed except the new "moof shorter than its header" test, which at the seed **hangs the buffer**: assert `len(s.frag)` stays bounded after three further writes.
- [ ] **2. Fix.** Appendix B. Correct `findMoofOffset`'s doc comment (`:136-140`); its code is unchanged. Add `resyncMoof(data []byte) int` (literal search, length ≥ 16 check), `const minMoofBox = 16`, `MaxFragmentBytes` as a package `var` (so the test can lower it, documented as such), and the tail-retention and ceiling branches in `flush`. Green.
  - **Break-check 2a:** keep a 0-byte tail instead of 7, and the split-read test goes red.
  - **Break-check 2b:** go back to `findMoofOffset(s.frag, 1)`, and the flipped test and #119's example go red.
  - **Break-check 2c:** remove the ceiling branch, and the ceiling test goes red.
- [ ] **3. Gates.** Coverage diff: the seed's uncovered `relay/output/fmp4.go:226.4` (successful resync) and `:231.4` (moof length below 8) blocks must now be covered. New statements (about 12) are covered by task 1's tests, so `missing` should fall. Run `go test -race ./output/` and `go test -race -run FMP4 ./httpapi/`, the fMP4 end-to-end rigs that drive this scanner.

PR description draft:

> **fix(relay): the fMP4 scanner resynchronises instead of discarding (#306, #119)**
>
> When the working buffer did not begin at a `moof`, the scanner searched by box length from offset 1. That re-read a length at a one-byte shift, jumped past every real box, returned -1 and cleared the whole buffer. It now searches for the literal type bytes and validates the candidate's length. It keeps a 7-byte tail so a header split across reads survives, and it abandons a fragment that grows past `MaxFragmentBytes` (64 MiB) instead of buffering toward a corrupt 4 GiB length. A `moof` shorter than its own header no longer stalls the buffer. `findMoofOffset`'s doc comment, which claimed recovery "either way", is corrected.
>
> `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` is flipped (before/after in the plan). Four new tests carry #119's shrunk counterexample and the three adjacent faults. Go ratchet: two previously uncovered blocks are now covered.
>
> Closes #306, #119.

### A-5 — `fix/A-5-hash-tune-events` (#233)

- **Files.** `core/relay_events.py`, `core/tests/test_relay_events.py`, `relay/channel/events.go` (comment), `relay/channel/manager_test.go`.
- **Test labels.** `python scripts/ci_backend_test_labels.py core/relay_events.py core/tests/test_relay_events.py` prints `["core.tests"]`. The Go files add no label. `core/relay_events.py` is **not** a Gate 2 module (the nine are listed in `scripts/coverage_live_path.coveragerc`), so no isolated coverage run is owed.
- **Backend runs.** Use your own container, never the shared `dispatcharr-testrunner`: `DISPATCHARR_TEST_CONTAINER=fixA5 DISPATCHARR_TEST_DB_VOLUME=fixA5-db CLAUDE_HOOK_REPO_ROOT=<worktree> .claude/hooks/start-test-container.sh`. Check the variable names with `grep -n DISPATCHARR_ .claude/hooks/start-test-container.sh` first. Remember the PostToolUse hook runs `core.tests` against whichever tree the **shared** container holds. Re-point it at this worktree, or treat the hook's result as not covering this PR.

Tasks:

- [ ] **1. Red first.** Add to `EventBatchWritesSystemEventRowsTests` (`core/tests/test_relay_events.py:18`):
  - `test_a_stream_hash_identifier_writes_a_row_with_the_hash_in_details`. It posts `{"type": "channel_start", "channel_id": "a"*64, "channel_name": "Preview", "details": {"stream_name": "S"}}` and asserts `accepted == 1`, one `SystemEvent` with `channel_id is None`, `channel_name == "Preview"`, `details["stream_hash"] == "a"*64` and `details["stream_name"] == "S"`. At the seed it is red: zero rows. Capture `assertLogs("core.utils", "ERROR")` in the seed run to show the swallowed `ValidationError`, and do **not** keep that assertion after the fix.
  - `test_an_explicit_stream_hash_in_details_is_not_overwritten`.
- [ ] **2. Fix.** Appendix D: `_split_identifier(value) -> (uuid_str | None, stream_hash | None)` using `uuid.UUID(str(value))` inside `try/except (ValueError, TypeError, AttributeError)`, with `""`/None mapping to `(None, None)` so `_clean`'s existing contract holds. In `apply_event_batch` (`:183`), `channel_id, stream_hash = _split_identifier(event.get("channel_id"))`; after the `details.pop` lines, `if stream_hash is not None: details.setdefault("stream_hash", stream_hash)`. Update `_clean`'s docstring (`:47-55`) to point at the helper. Green.
  - **Break-check 2a:** return `(value, None)` for every non-empty value, and the new test goes red with zero rows.
  - **Break-check 2b:** use `details["stream_hash"] = …` instead of `setdefault`, and the second test goes red.
- [ ] **3. Relay contract.** Add a paragraph to `relay/channel/events.go:7-11`'s doc comment: `ChannelID` is the tune identifier verbatim, a channel UUID or a stream hash for the admin preview, and `core/relay_events.py` classifies it. Add `TestAHashIdentifiedChannelReportsItsIdentifierAsTheChannelID` to `relay/channel/manager_test.go`. Claim a channel under `strings.Repeat("a", 64)` with the package's existing event-log fake (`eventLog`, used at `source_transcode_test.go:398`), stop it, and assert both `channel_start` and `channel_stop` carry `ChannelID == strings.Repeat("a", 64)`. It is green at the seed; it is a contract pin, not a red. Its break-check is **break-check 3a:** make `emit` set `ChannelID: ""`, and it goes red. No new Go statements, so the coverage ratchet is unaffected; confirm with the diff.
- [ ] **4. Gates.** Run `core.tests` in your own container once **without** `--keepdb` (the seeded-row drift rule). Run `go test -race ./channel/`, and the guard locally.

PR description draft:

> **fix(events): a stream-by-hash tune writes its lifecycle events (#233)**
>
> The admin single-stream preview tunes by a 64-hex stream hash, and the relay posts that identifier as `channel_id`. `SystemEvent.channel_id` is a `UUIDField`, and `log_system_event`'s bare `except` swallowed the `ValidationError`, so the preview wrote no `channel_start`, `channel_stop` or any other row, and Connect saw nothing. `core/relay_events.py` now keeps a UUID as `channel_id` and moves anything else into `details["stream_hash"]`. The relay's wire is unchanged; a Go test now pins the contract Django relies on.
>
> New tests only; no existing assertion changes.
>
> Closes #233.

### A-6 — `migration/A-6-fmp4-client-timeout` (#222)

- **Why `migration/`.** Rule 3: it edits `relay/httpapi/`. The full E2E matrix runs, including `streaming-greybox`'s fMP4 specs.
- **Files.** `relay/httpapi/fmp4.go`, `relay/httpapi/fmp4_test.go`, `docs/relay-parity-matrix.md` (row 12), `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** Backend `[]`. Go. Guards. Full E2E.

Tasks:

- [ ] **1. Red first.** Flip `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` (`:356-470`) to `TestAStalledFMP4ClientStaysConnectedLikeATSClientWhileTheChannelIsHealthy`. Same rig and compression: `STREAM_TIMEOUT`=1, `FAILOVER_GRACE_PERIOD`=1, `CONNECTION_TIMEOUT` left at its default, upstream stall after 200,000 bytes.
  - **Before:**
    1. The fMP4 body reaches EOF within 30 s.
    2. `sent > 0`.
    3. `took >= 2s`.
    4. The channel is still healthy.
    5. `ch.Clients() == 1`.
  - **After:**
    1. Read the fMP4 body in a goroutine.
    2. Wait `3 * (streamTimeout + failoverGrace)` = 6 s, still inside the healthy window: `CONNECTION_TIMEOUT` defaults to 10 s in the rig's control plane (`relay/internal/relaytest/controlplane.go:44`).
    3. Assert the body has **not** ended.
    4. Assert `ch.Healthy()`.
    5. Assert `ch.Clients() == 2`, both clients still connected.
  - Rewrite the header comment; the TS-contrast paragraph becomes "the two loops agree".
  - Red at the seed: the fMP4 body ends at about 2 s.
- [ ] **2. New test.** `TestAnFMP4ClientOnAnUnhealthyChannelIsDroppedAfterMaxKeepalive`. Overrides: `CONNECTION_TIMEOUT`=0.3, `HEALTH_CHECK_INTERVAL`=0.05 (`failover_test.go:59`'s values), `MAX_KEEPALIVE_DURATION`=0.5, `STREAM_TIMEOUT`=1, `FAILOVER_GRACE_PERIOD`=1. Give the resolver no alternate, so the channel stays unhealthy rather than failing over; check how `fanRig`'s control plane answers a second next-source and pin it to "no alternate". Assert:
  - the fMP4 body ends;
  - `took >= 0.5s`, a lower bound only;
  - no bytes arrive after the stall began, because fMP4 sends no keepalive.
  - At the seed this ends at `ClientTimeout` (2 s), which also satisfies `>= 0.5s`, so this test alone is **not** red at the seed. It pins the new cap. The red for the fix is task 1. It is kept because without it the fix could drop the timeout entirely and pass task 1.
- [ ] **3. Fix.** Appendix C. `serveFMP4Client` gains `stallStart time.Time`. On a wait timeout, if `ch.Healthy()`, reset `stallStart` and continue. Otherwise set `stallStart` on first sight and return once `time.Since(stallStart) > tuning.MaxKeepalive`, logging "fMP4 stall outlasted the keepalive duration on an unhealthy channel, disconnecting". A fragment write resets `stallStart`. Rewrite the doc comment `:112-158` to describe the new contract and the residual (a wedged remux on a healthy channel). Green.
  - **Break-check 3a:** drop the health check (the seed shape), and task 1's test goes red.
  - **Break-check 3b:** never drop, and task 2's test goes red (times out).
- [ ] **4. Matrix row 12.** Behaviour: "An fMP4 client, like a TS client, is not dropped for silence while the channel is healthy; on an unhealthy channel it is dropped after `MAX_KEEPALIVE_DURATION`, with no keepalive bytes (fMP4 has none)". Source: `relay/httpapi/fmp4.go:<new ranges>`, plus `relay/httpapi/stream.go:1005-1030` for the TS side, re-anchored after J-1 if it has landed. Pin: both new test symbols. Notes: "Fixed by #<PR> (issue #222); reproduced per D5 until stage 2d-4. The url_switching exemption remains unported on both loops; see fmp4.go's doc comment." Run the guard.
- [ ] **5. Prose and ledger.** `CLAUDE.md`: delete the bullet beginning "The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption" (`:130`). Ledger `fmp4-timeout-no-switch-exemption` (`:22`): set to `fixed`. Validate.
- [ ] **6. Gates.** Coverage diff: about six statements, covered by tasks 1–2. The floor's own header names `relay/httpapi/fmp4.go:188.4,189.1` as a local flapper; if it appears in the diff, it is that block and not this PR's doing. Say so in the PR if it does. `go test -race -count=3 -run 'FMP4|Keepalive' ./httpapi/`. Guard. Full E2E through `migration/**`.

PR description draft:

> **fix(relay): an fMP4 viewer survives a failover the way a TS viewer does (#222)**
>
> The fMP4 loop dropped a client `stream_timeout + failover_grace_period` (40 s) after its last fragment, whatever the channel's health, while the TS loop on the same channel holds its client for up to `MAX_KEEPALIVE_DURATION`. The fMP4 loop now has the TS loop's exits: no silence drop on a healthy channel, and a `MAX_KEEPALIVE_DURATION` cap on an unhealthy one. It sends no keepalive bytes, because fMP4 has no null packet.
>
> Residual, stated: a remux wedged alive on a healthy channel now holds its clients until they hang up. Dropping them never helped, because a reconnect joins the same shared remux.
>
> Row 12 is rewritten. `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` is flipped (before/after in the plan) and a keepalive-cap test is added. Ledger `fmp4-timeout-no-switch-exemption` is set to fixed. `migration/` branch because the PR edits `relay/httpapi/`.
>
> Closes #222.

### A-7 — `migration/A-7-detail-ffmpeg-bitrate` (#314)

- **Why `migration/`.** It edits `relay/httpapi/`.
- **Files.** `relay/httpapi/detail.go`, `relay/httpapi/detail_golden_test.go`, `relay/httpapi/testdata/channel_detail.json`, one new render test (in `relay/httpapi/detail_golden_test.go` or beside it), `apps/proxy/relay_serializers.py`, `apps/proxy/tests/test_relay_detail_payload_golden.py`, `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** `python scripts/ci_backend_test_labels.py apps/proxy/relay_serializers.py` prints `["apps.proxy.tests"]`. Go. Full E2E.
- **Gate 2 applies.** `apps/proxy/relay_serializers.py` is one of the nine Gate 2 modules, so run `scripts/coverage_live_path_isolated.sh` before push, and read `--gate` against `scripts/coverage_live_path.floor`. Deleting one field declaration removes one covered statement; `missing` must not move. **Run it after J-4 has landed if J-4 is merged by then**: J-4 fixes that driver's dropped arguments. Otherwise pass `--gate` exactly as J-4's plan describes.

Tasks:

- [ ] **1. Red first, Go.** Flip `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` (`detail_golden_test.go:216-244`) to `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate`.
  - **Before:** for each of `source_bitrate` and `ffmpeg_bitrate`, `if _, present := payload[key]; present { t.Errorf(…) }`, plus the three neighbours present.
  - **After:** `ffmpeg_bitrate` is present and equal to the golden struct's value (`"3500.0"`, added to `detailGoldenPayload` at the `FFmpegFPS` line `:94`); `source_bitrate` is still absent, now because the serializer no longer declares it (comment says so); the three neighbours are still present.
  - Add the render test: drive `describeChannelDetail` over a channel whose stats carry `FFmpegOutputBitrate = 3500.0`, and assert `out.FFmpegBitrate == "3500.0"`. Find the existing seam that builds a `*channel.Channel` with stats for detail tests (`grep -n describeChannelDetail relay/httpapi/*_test.go`); if none exists, drive it through the rig's `GET /proxy/relay/channels/<id>` with the slow-trickle corpus instead.
  - Red at the seed: the field does not exist.
- [ ] **2. Fix, Go.** Add `FFmpegBitrate string `json:"ffmpeg_bitrate,omitempty"`` to `detailPayload` between `ActualFPS` and `StreamType`, which is the serializer's declaration order (`relay_serializers.py:138-142`). In `describeChannelDetail` (`detail.go:~350`), `if stats.FFmpegOutputBitrate != nil { out.FFmpegBitrate = pythonFloat(*stats.FFmpegOutputBitrate) }`. Rewrite the comment at `:118-133` to say `ffmpeg_bitrate` is emitted since #<PR> and `source_bitrate` was removed from the serializer. Green.
  - **Break-check 2a:** remove the assignment, and the render test goes red.
- [ ] **3. Django.** Delete `source_bitrate = serializers.CharField(required=False)` (`relay_serializers.py:133`). In `test_relay_detail_payload_golden.py`, empty `NEVER_WRITTEN` (keep the name and a comment saying why it is empty, so a future absence has a home) and add `"ffmpeg_bitrate": "3500.0"` to `fixture()`. Regenerate the golden: `DISPATCHARR_WRITE_GOLDEN=1 python manage.py test apps.proxy.tests.test_relay_detail_payload_golden` in your own container, and commit the regenerated `relay/httpapi/testdata/channel_detail.json`. Re-run without the variable, then `cd relay && go test ./httpapi/ -run Golden`. Both are green, so the two implementations read one golden.
  - **Break-check 3a:** put `source_bitrate` back in the serializer without a fixture value, and `test_the_fixture_covers_every_serializer_field` goes red. That proves the completeness test still bites with `NEVER_WRITTEN` empty.
- [ ] **4. Schema.** Confirm drf-spectacular's schema still generates: `python manage.py spectacular --validate --file /dev/null` in the container. `source_bitrate` leaves `GET /proxy/ts/status/<uuid>`'s documented shape, and no frontend code reads it (seed grep empty).
- [ ] **5. Prose and ledger.** `CLAUDE.md`: delete the bullet beginning "**Two fields on `GET /proxy/ts/status/<uuid>` are documented and emitted by nothing**" (`:136`). Also edit the Architecture section's "Observing a channel" paragraph if it names either field; grep `CLAUDE.md` for `source_bitrate` and `ffmpeg_bitrate`, and at the seed only `:136` does. Append `{id: detail-bitrate-fields-unwritten, title: "source_bitrate and ffmpeg_bitrate were declared on the channel detail payload and emitted by nothing", area: correctness, severity: low, status: fixed, source: null, issue: 314, test: relay/httpapi/detail_golden_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-15, status_changed: <date>}`. Validate.
- [ ] **6. Gates.** Go coverage diff: about two statements, covered by task 1's render test. Gate 2 isolated run: `missing` unchanged. `apps.proxy.tests` once without `--keepdb`. Guard locally. Full E2E.

PR description draft:

> **fix(relay): the channel detail carries ffmpeg_bitrate; source_bitrate is removed (#314)**
>
> The relay computed ffmpeg's output bitrate on every progress record and dropped it. `GET /proxy/ts/status/<uuid>` now carries it as `ffmpeg_bitrate`, a string like its `ffmpeg_fps` neighbour. `source_bitrate` had no writer in either relay and no reader in the frontend, so it is deleted from `RelayChannelDetailSerializer` rather than left documented and empty.
>
> The golden is regenerated from Django's serializer and read back by Go. `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` is flipped (before/after in the plan). Gate 2's isolated run shows `missing` unchanged. `migration/` branch because the PR edits `relay/httpapi/`.
>
> Closes #314.

---

## Appendix A — #302, `relay/ffmpeg/detector.go` (A-2 task 3)

```diff
@@ type Detector struct {
 	buffering bool
 	since     time.Time
+	// retryFrom is when the current timeout window began, if a failed switch
+	// re-armed it (Rearm). Zero means the window began at since. Kept apart
+	// from since so BufferingFor, and the channel_failover duration built on
+	// it, still measures from the first slow sample (#302).
+	retryFrom time.Time
 }
@@ func (d *Detector) Observe(speed float64) Verdict {
-		if now().Sub(d.since) > d.Timeout {
+		from := d.since
+		if d.retryFrom.After(from) {
+			from = d.retryFrom
+		}
+		if now().Sub(from) > d.Timeout {
 			return TimedOut
 		}
 		return Continuing
 	}
 	if d.buffering {
 		d.buffering = false
 		d.since = time.Time{}
+		d.retryFrom = time.Time{}
 		return Ended
 	}
@@
+// Rearm is the failed-switch branch (#302): the channel stays buffering and
+// the next TimedOut comes a full Timeout from now, so a channel with no
+// alternate asks the control plane once per window rather than once per
+// progress record. BufferingFor is unaffected.
+func (d *Detector) Rearm() {
+	now := d.Now
+	if now == nil {
+		now = time.Now
+	}
+	d.retryFrom = now()
+}
@@ func (d *Detector) Reset() {
 	d.buffering = false
 	d.since = time.Time{}
+	d.retryFrom = time.Time{}
 }
```

And in `relay/channel/source_transcode.go`, in the `TimedOut` case's failure branch:

```diff
 		} else {
 			s.log().Error("failed to switch to the next stream after a buffering timeout", "channel", s.channelID())
+			r.detector.Rearm()
 		}
```

## Appendix B — #306/#119, `relay/output/fmp4.go` (A-4 task 2)

```diff
+// minMoofBox is the smallest real moof: its own 8-byte header plus an mfhd
+// (16 bytes). A candidate shorter than this is garbage that happens to
+// spell "moof".
+const minMoofBox = 16
+
+// MaxFragmentBytes bounds the working buffer while a fragment has no end in
+// sight. A var, not a const, only so scanner_test.go can lower it.
+var MaxFragmentBytes = 64 * 1024 * 1024
+
+// resyncMoof is the start of the first plausible moof at or after offset 1:
+// the literal type bytes, found by search rather than by walking box lengths,
+// because the lengths are exactly what cannot be trusted once the stream is
+// misaligned (#306, #119). -1 when none is in data yet.
+func resyncMoof(data []byte) int {
+	for from := 5; from+4 <= len(data); {
+		i := bytes.Index(data[from:], moofBox)
+		if i < 0 {
+			return -1
+		}
+		start := from + i - 4
+		if binary.BigEndian.Uint32(data[start:start+4]) >= minMoofBox {
+			return start
+		}
+		from += i + 1
+	}
+	return -1
+}
@@ func (s *scanner) flush() {
 	for len(s.frag) >= 8 {
-		if !bytes.Equal(s.frag[4:8], moofBox) {
-			next := findMoofOffset(s.frag, 1)
-			if next < 0 {
-				s.frag = s.frag[:0]
-				return
-			}
+		size := int64(binary.BigEndian.Uint32(s.frag[0:4]))
+		if !bytes.Equal(s.frag[4:8], moofBox) || size < minMoofBox {
+			next := resyncMoof(s.frag)
+			if next < 0 {
+				// Keep what could be the first 7 bytes of a header split
+				// across reads; drop the rest.
+				keep := min(len(s.frag), 7)
+				s.frag = append(s.frag[:0], s.frag[len(s.frag)-keep:]...)
+				return
+			}
 			s.frag = s.frag[next:]
 			continue
 		}
-		size := int64(binary.BigEndian.Uint32(s.frag[0:4]))
-		if size < 8 {
-			return
-		}
 		if size > int64(len(s.frag)) {
+			if len(s.frag) > MaxFragmentBytes {
+				s.frag = s.frag[1:] // misaligned now; the next pass resyncs
+				continue
+			}
 			return
 		}
 		next := findMoofOffset(s.frag, int(size))
 		if next < 0 {
+			if len(s.frag) > MaxFragmentBytes {
+				s.frag = s.frag[1:]
+				continue
+			}
 			return
 		}
```

The `s.frag[1:]` step deliberately misaligns the buffer by one byte so the next pass takes the resync arm. The implementer may instead call `resyncMoof` directly; either is acceptable if break-check 2c reddens.

## Appendix C — #222, `relay/httpapi/fmp4.go` (A-6 task 3)

```diff
 	lastYield := time.Now()
+	// stallStart is when this client's current stall was first seen on an
+	// UNHEALTHY channel; zero while the channel is healthy or data flows.
+	var stallStart time.Time
 	for {
@@
 		if len(frags) > 0 {
 			cursor = next
 			if !writeChunks(w, rc, frags) {
 				return
 			}
 			lastYield = time.Now()
+			stallStart = time.Time{}
 			client.Touch(lastYield)
 			continue
 		}
@@
 		case errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
-			// ROW 12. No health check, no switching exemption, no keepalive:
-			// elapsed time since the last fragment, and nothing else.
-			if time.Since(lastYield) > tuning.ClientTimeout {
-				log.Warn("fMP4 no data for the client timeout, disconnecting",
-					"channel", ch.ID(), "client", client.ID, "timeout", tuning.ClientTimeout)
-				return
-			}
+			// ROW 12, fixed (#222): the TS loop's exits. Healthy: wait, as
+			// serveClient does. Unhealthy: at most MaxKeepalive, serveClient's
+			// reachable exit -- without the null packets, which fMP4 has no
+			// equivalent of.
+			if ch.Healthy() {
+				stallStart = time.Time{}
+				continue
+			}
+			if stallStart.IsZero() {
+				stallStart = time.Now()
+			}
+			if time.Since(stallStart) > tuning.MaxKeepalive {
+				log.Warn("fMP4 stall outlasted the keepalive duration on an unhealthy channel, disconnecting",
+					"channel", ch.ID(), "client", client.ID, "max", tuning.MaxKeepalive)
+				return
+			}
 			continue
```

`lastYield` may become unused apart from `client.Touch`; if lint flags it, fold it into `client.Touch(time.Now())`.

## Appendix D — #233, `core/relay_events.py` (A-5 task 2)

```diff
 import logging
 import time
+import uuid
@@
+def _split_identifier(value):
+    """(channel_uuid, stream_hash) for a relay-posted identifier.
+
+    The relay posts the tune identifier verbatim: a channel UUID, or the
+    64-hex stream_hash of the admin single-stream preview
+    (apps/proxy/next_source.py's get_stream_object fallback). Only the first
+    fits SystemEvent.channel_id, a UUIDField; the second used to raise inside
+    log_system_event and be swallowed there -- no row, no Connect fan-out
+    (#233). "" and None are "no identifier", as _clean has always said.
+    """
+    value = _clean(value)
+    if value is None:
+        return None, None
+    try:
+        return str(uuid.UUID(str(value))), None
+    except (ValueError, TypeError, AttributeError):
+        return None, str(value)
@@ def apply_event_batch(events):
-        channel_id = _clean(event.get("channel_id"))
+        channel_id, stream_hash = _split_identifier(event.get("channel_id"))
         channel_name = _clean(event.get("channel_name"))
@@
         details.pop("event_type", None)
+        if stream_hash is not None:
+            details.setdefault("stream_hash", stream_hash)
```

---

## Open questions

Each has a default this plan already adopts. The user rules only if they want the other reading.

1. **#221: end the channel, or refuse the switch?** The plan counts a buffering switch toward `MAX_STREAM_SWITCHES`, so exceeding the bound ends the channel in error, exactly as a main-loop switch does (`failover_test.go:604`). The alternative is to consult the counter *before* asking and, when spent, keep playing the slow stream. That keeps a degraded picture on screen instead of an error, but gives the one bound two meanings. **Default: end the channel, for one semantics.**
2. **#314: delete `source_bitrate`, or implement it?** Deleting removes a documented field that never had a value. Implementing it means parsing the input's bitrate from ffmpeg's preamble (`Duration: …, bitrate: N kb/s`, usually `N/A` on a live input) or probing it, which is feature work with an unclear value. **Default: delete.**
3. **#306/#119: the 64 MiB fragment ceiling.** It is a derived threshold (50 Mbit/s × 10 s GOP, with margin), not a measurement. A-4 carries the formula in the constant's comment. If the user knows of higher-bitrate sources, raise it; the tests lower it and do not depend on its value.
4. **#222: a remux-liveness watchdog.** A-6 removes the only thing that ended a client of a remux wedged alive on a healthy channel. That never cured the wedge, but a watchdog that restarts a remux whose input advances while its output does not would be the real fix. It is new work, not a defect fix. **Default: file it as a new issue after A-6 merges; not planned here.**
5. **`e2e-tests.yml`'s guards trigger has no `relay/` prefix** (`:110`, `:127-133`). A relay-only PR that moves a cited line past its file's end passes PR CI and fails the guard on `main`. It is a one-line workflow edit, but it is outside category A's issues. **Default: the lead routes it (category G owns workflows); every A PR runs the guard locally meanwhile.**

---

## Coverage table

| issue | disposition | PR |
|---|---|---|
| #24 | fix | A-1 |
| #119 | fix (shares root cause with #306; both close) | A-4 |
| #221 | fix | A-2 |
| #222 | fix | A-6 |
| #227 | fix | A-1 |
| #233 | fix (Django side) + contract pin (relay side) | A-5 |
| #296 | fix | A-3 |
| #299 | fix | A-1 |
| #302 | fix | A-2 |
| #306 | fix | A-4 |
| #314 | fix (`ffmpeg_bitrate` emitted, `source_bitrate` deleted) | A-7 |

Eleven issues, seven PRs, no memos, no duplicates to close.
