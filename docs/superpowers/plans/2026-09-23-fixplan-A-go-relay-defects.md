# Fix plan, category A — Go relay defects carried from the Python relay

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementers are `sonnet`; reviewers are `fable` (or `opus`). This plan implements nothing itself.

**Goal.** Fix the eleven defects the Go relay carried verbatim from the deleted Python relay under spec D5's reproduce-do-not-fix rule. Since stage 2d-4 there is no second implementation to agree with, so each is an ordinary Go defect (spec Amendment A16.12 item 4): a fix changes the Go code, the test that pinned the defect, and — where one exists — the parity-matrix row.

**Architecture.** Stdlib-only Go relay (`relay/`), one process, in-memory channel registry. Six of the seven PRs touch only `relay/`; one (A-5) is mostly `core/relay_events.py`; one (A-7) touches `relay/httpapi/` and one Django serializer. No PR changes a wire contract the relay and Django both depend on, except A-7, which adds one field Django already declares.

**Tech stack.** Go (stdlib only), Python 3 / Django 6 / DRF for A-5 and A-7.

**Spec.** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` § D5 and Amendment **A16.12 item 4** ("#222, #296, #299, #302 and #314: ordinary Go defects now, fixable without a parity obligation"). The other six issues (#24, #119, #221, #227, #233, #306) are the same class and are covered by the same reasoning. `docs/relay-parity-matrix.md` is the regression catalogue each PR reads against.

**Revision 2 (fix round 1).** Revised after the fable review of `0e21dd9d` (`review-A-r1.md`: 2 blocking, 7 should-fix, 4 nits) and after reading the competing plan on PR #350 (`docs/fixplan-A` at `587a0582`). Where #350's design is better it is adopted here **with attribution in the text**, marked "(from #350)":

- #221 now refuses a buffering switch once the budget is spent and keeps the channel playing (#350 R1). It no longer ends the channel, and that retires review finding 8.
- #299 gets #350's narrower gate: a `size=`/`Lsize=`-led record carrying `speed=` (#350 R8). It also gets #350's real ffmpeg 6.1.1 capture step.
- #296 gets #350's second arm: a dropped flag takes its value (#350 R9).
- #302's flipped test uses a steady-buffering corpus (#350's A-2 note).
- #222's healthy-channel test starves the fMP4 client from its first second, and its unhealthy test reads its clock before the last healthy sighting (#350's A-5 notes).
- #306's resync candidate has an upper length bound as well as a lower one (#350 R6).

The per-finding dispositions are at the end, under "Review round 1 dispositions".

---

## Header

| field | value |
|---|---|
| Category | A — Go relay defects carried from the Python relay |
| Measurement seed | **`a54b09a9`** (`main`, 2026-09-23, #342). Every `file:line` below was opened there. |
| Ordering | Second of ten: B, **A**, J, C, D, E, G, H, I, F. The lead re-seeds after B merges. B's plan (`origin/docs/fixplan-B`) touches no file this plan touches. |
| PRs, in implementation order | A-1 `fix/A-1-ffmpeg-stderr-parsing` (#24, #227, #299) · A-2 `fix/A-2-buffering-failover-bounds` (#302, #221) · A-3 `fix/A-3-udp-user-agent-flags` (#296) · A-4 `fix/A-4-fmp4-scanner-resync` (#306, #119) · A-5 `fix/A-5-hash-tune-events` (#233) · A-6 `migration/A-6-fmp4-client-timeout` (#222) · A-7 `migration/A-7-detail-ffmpeg-bitrate` (#314) |
| Dependencies | A-1, A-2 and A-3 must land in that order. They edit adjacent Known-defects bullets in `CLAUDE.md`, A-2 and A-3 both edit `relay/channel/source_transcode_test.go`, and A-2's steady-buffering corpus reads the `CorpusSpeeds` helper that A-1 widens. A-4 and A-5 are independent and may land any time. A-6 and A-7 each edit one `CLAUDE.md` bullet and land after A-3. |
| Decision memos | None. No rule-4 policy item is in category A. |
| upstreamable | **no** for all seven. `relay/` does not exist upstream; A-5's `core/relay_events.py` is fork-only (Phase 1 PR 6). |

### Files this plan touches

| file | PR | change |
|---|---|---|
| `relay/ffmpeg/spawn.go:226-275` | A-1 | hard ceiling on an unterminated stderr buffer (#24) |
| `relay/ffmpeg/progress.go:25-40` | A-1 | `speedRe` reads the exponent (#227); `IsProgressLine` accepts a `size=`/`Lsize=`-led record carrying `speed=` (#299) |
| `relay/ffmpeg/progress_test.go`, `relay/ffmpeg/spawn_test.go`, `relay/channel/source_transcode_test.go` | A-1 | one test flipped, four new |
| `relay/internal/relaytest/corpus.go:29-30`, `:104-126` | A-1 | two capture names added; the copied speed regex widened and its comment corrected |
| `relay/internal/relaytest/testdata/ffmpeg_stderr/{ffmpeg6-normal,ffmpeg6-slow-trickle}.stderr` (new), `CAPTURE.md` | A-1 | real ffmpeg 6.1.1 captures with provenance; the #227 bullet says fixed |
| `.github/workflows/go-tests.yml:147-156` | A-1 | comment only (the "#299 owns that" sentence) |
| `relay/ffmpeg/detector.go` | A-2 | a `clock()` helper, a `retryFrom` field and `Rearm()` (#302) |
| `relay/channel/source_transcode.go:326-344` | A-2 | the failed-or-refused branch calls `Rearm()` (#302) |
| `relay/channel/channel.go:162` (struct), `:435-558` (run loop) | A-2 | the switch counter becomes a `Channel` field shared by both paths (#221) |
| `relay/channel/failover.go:283-318` | A-2 | `failoverFromBuffering` refuses when the budget is spent, and counts a switch it makes (#221) |
| `relay/channel/tuning.go:77-80` | A-2 | the `MaxStreamSwitches` comment |
| `relay/channel/failover_test.go:40-70` | A-2 | `fakeResolver` gains a `callTimes()` accessor (test support only) |
| `relay/channel/source_transcode_test.go`, `relay/ffmpeg/detector_test.go` | A-2, A-3 | A-2 flips two tests and adds two; A-3 flips one and adds one |
| `relay/channel/source_transcode.go:97-119` | A-3 | a dropped value takes its flag and a dropped flag takes its value (#296) |
| `relay/output/fmp4.go:133-245` | A-4 | resynchronise by literal `moof` search with a length window; keep a 7-byte tail; cap an unbounded fragment (#306, #119) |
| `relay/output/scanner_test.go` | A-4 | one test flipped, six new |
| `core/relay_events.py:46-56`, `:183-216` | A-5 | a non-UUID identifier moves to `details["stream_hash"]` (#233) |
| `core/tests/test_relay_events.py` | A-5 | two new tests |
| `relay/channel/events.go:7-11` | A-5 | doc comment stating the contract |
| `relay/channel/manager_test.go` | A-5 | one new contract test |
| `relay/httpapi/fmp4.go:112-241` | A-6 | the TS loop's health gate and keepalive-cap exit, with no bytes written (#222) |
| `relay/httpapi/fmp4_test.go:356-470` | A-6 | one test flipped, one new |
| `relay/httpapi/detail.go:115-175`, `:340-357` | A-7 | emit `ffmpeg_bitrate` from the output bitrate the relay already computes (#314) |
| `relay/httpapi/detail_golden_test.go`, `relay/httpapi/testdata/channel_detail.json` | A-7 | one test flipped, one new, golden regenerated |
| `apps/proxy/relay_serializers.py:133` | A-7 | `source_bitrate` deleted |
| `apps/proxy/tests/test_relay_detail_payload_golden.py:43-62` | A-7 | `NEVER_WRITTEN` emptied, fixture gains `ffmpeg_bitrate` |
| `docs/relay-parity-matrix.md` rows 6, 12, 28 (and the citations of rows 1, 3, 4, 5 if lines move) | A-1, A-2, A-3, A-6 | row rewritten to the fixed behaviour; pin renamed; shifted ranges re-anchored |
| `metrics/curated/defects.yml` | A-1, A-2, A-3, A-6, A-7 | three entries → `fixed`; four new entries at `fixed` |
| `CLAUDE.md` Known defects (`:128`, `:129`, `:130`, `:134`, `:135`, `:136`), plus `:63` (A-1) and `:82` (A-2) | A-1, A-2, A-3, A-6, A-7 | each bullet a PR closes is **rewritten to one sentence** saying how it closed and naming the PR, following the section's precedent for #295, #190 and the lease; the two other sentences each PR makes false are rewritten |

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

**The Go coverage ratchet has no headroom.** `scripts/coverage_relay_go.floor` sets `missing=589`, the worst of 12 CI rounds whose range was 588–589. Two measurements of the seed (`scripts/coverage_relay_go.sh --measure` then `--report`) disagree by one block:

- **This planner, 2026-09-23:** `statements=3710 missing=587`.
- **The round-1 reviewer:** `missing=588`.

The one-block difference is the floor header's documented flapper, `relay/buffer/ring.go:262.3`. Either way, a PR that adds **one** uncovered statement can draw 590 in CI and fail. The rule for every PR below: **every new statement is executed by that PR's own new tests in its own package** (per-package measurement; a neighbour's test does not count, and a test in `relay/channel` does not cover a statement in `relay/ffmpeg`). Each PR's task list carries the check:

```bash
# the PR's base, measured from a clean detached worktree (never from the PR tree with stashed edits)
git -C /Users/dion/git/Dispatcharr worktree add --detach /tmp/cov-base-wt <base-sha>
(cd /tmp/cov-base-wt && scripts/coverage_relay_go.sh --measure /tmp/cov-seed)
# the PR itself
(cd <worktree> && scripts/coverage_relay_go.sh --measure /tmp/cov-pr && scripts/coverage_relay_go.sh --gate /tmp/cov-pr)
diff <(awk 'NR>1 && $3==0 {print $1}' /tmp/cov-seed/relay.coverprofile | LC_ALL=C sort) \
     <(awk 'NR>1 && $3==0 {print $1}' /tmp/cov-pr/relay.coverprofile   | LC_ALL=C sort)
```

The diff may show uncovered blocks **disappearing**. A-2 covers `relay/ffmpeg/detector.go:75.3` and `:105-114`; A-4 covers `relay/output/fmp4.go:226.4` and `:231.4`. It may show the documented flappers `relay/buffer/ring.go:262.3` and `relay/httpapi/fmp4.go:188.4`. It must show **no new uncovered block in a file the PR edited**.

None of these PRs changes the linked package set or `relay/go.mod`, so `shape`, `packages` and `gomod` stay equal and no `--write-floor` is ever run. **Never lower the floor or raise `missing` in these PRs**; the floor's own header forbids a bump on the PR that drew it.

**The parity-matrix guard.** `e2e/tests/guards/parity-matrix.spec.ts` checks two things:

- every Source citation resolves to a line inside its file;
- every Pin names a real test symbol.

A PR that renames a pinning test must rename it in the row in the same commit, or the guard fails. On a PR, `e2e-tests.yml`'s `changes` job (`:108-133`) sets `guards=true` only when the diff matches its path pattern (`:110`) or touches `docs/relay-parity-matrix.md`. The pattern has no `relay/` prefix, but it does carry `apps/` and `core/`. So the guard runs in CI as follows:

| PR | guard runs in CI? | why |
|---|---|---|
| A-1, A-2, A-3, A-6 | yes | each edits the matrix |
| A-5 | yes | edits `core/` |
| A-7 | yes | edits `apps/` |
| A-4 | **no** | touches only `relay/output/` |

A-4 cites no row, but every PR still runs the guard locally, because row citations point into files these PRs shift:

```bash
cd e2e && npx playwright test --project=guards parity-matrix
```

The guard needs no container. The missing `relay/` prefix is a real gap: a relay-only PR that shifts a cited line past a file's end passes PR CI and fails on `main`. It is **not** fixed here; see Open questions.

---

## Per-issue analysis

Every citation was opened at `a54b09a9`.

### #24 — the stderr reader grows without bound on unterminated `frame=` output

- **Root cause.** `relay/ffmpeg/spawn.go:253-257`: when the buffer holds no CR or LF, it is flushed only if `len(buf) > 1024 && !bytes.Contains(buf, []byte("frame="))`. A delimiter-free stream containing `frame=` never matches, so `buf` grows until EOF (`:274`'s trailing `emit`). This reader runs in the one `relay-go` process that carries every live viewer.
- **Fix.** Add a hard ceiling, `maxStderrLine = 64 << 10`. A buffer past it is flushed as one line whatever it contains. It flushes; it never truncates or drops, so no stderr byte is lost. The 1 KiB `frame=` exemption stays for its original purpose, which is not splitting a real progress record of about 100 bytes. Memory per reader is bounded at the ceiling plus one 4 KiB read. #350 R7 reaches the same design independently.
- **Tests.** New `TestAnUnterminatedFrameRecordCannotGrowTheReaderWithoutBound` (spawn_test.go), driven like the existing `TestALongUnterminatedLineIsFlushedWhileTheChildStillRuns` (`spawn_test.go:125`). The corpus is about 2 MiB of `frame=1 ` with no terminator. Because it carries no `speed=`, `SplitCorpus` treats it all as preamble (`relaytest/corpus.go:97-98`) and the stand-in writes it at once (`relaytest/standin.go:386-387`). So the corpus rule is not in play, and the reader drains the pipe as it goes. The stand-in is kept alive by `--dead-air-after-bytes`. The assertion is that no line longer than `maxStderrLine + 4096` reaches the callback, and that at least one line arrives while the child lives. No existing test changes.
- **Size** S. **upstreamable** no. **Duplicates** none.

### #227 — `speed=` in scientific notation is read as its mantissa

- **Root cause.** `relay/ffmpeg/progress.go:33`: `speedRe = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)` stops at the `e`. The comment at `:25-31` names row 28 and #227.
- **Fix.** `speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?`, the expression `progress_test.go:13`'s `fullSpeedRe` already uses. `strconv.ParseFloat` reads the exponent. The mirror case `speed=9.5e-05x` now reads as `0.000095` and correctly counts as below `buffering_speed`. `fpsRe` keeps its narrow class, because ffmpeg is not observed to print a frame rate in scientific notation (#350 R10).
- **The copy in `relaytest/corpus.go:104-110`.** It is documented as "the PRODUCTION speed regex, copied deliberately", and `CorpusSpeeds` derives nine tests' expectations from it. After this fix that comment is false. **Widen the copy in the same PR and rewrite its comment.** The comment's `apps/proxy/live_proxy/tests/manager_support.py:24` reference names a file deleted at 2d-4; drop it.
  - #350 R10 leaves the copy alone on the ground that no caller reads the `truncation` corpus through it. That is true today, and the review measured it: `normal` and `slow-trickle` carry no scientific-notation speed.
  - A helper whose stated contract is "what the shipped parser sees" diverging from the shipped parser is a latent trap. This plan follows the review.
- **Tests.** Flip `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` (`progress_test.go:23`) to `TestAScientificNotationSpeedIsReadWithItsExponent` (listed under A-1). **Its corpus-shape precondition reads the mantissa through a test-local `mantissaSpeedRe`**, the seed literal kept in the test as the record of what the parser used to read, not through `speedRe`. After the fix `speedRe` reads the whole value, the ratio would be 1, and the "re-derive" guard would fire for a reason that is not the mechanism (review finding 1; #350's A-1 test table makes the same move). Add two regression rows to `TestParseProgressReadsTheRealRecordShapes`' table (`:52-63`) from the issue body: `speed=1.82e+03x` → 1820 and `speed=9.5e-05x` → 0.000095.
- **Size** S. **upstreamable** no. **Duplicates** none. Ledger entry `ffmpeg-speed-scientific-notation` (`defects.yml:32`).

### #299 — the progress gate is blind on ffmpeg 6.x stream-copy lines

- **Root cause.** `relay/ffmpeg/progress.go:40`: `IsProgressLine` is `strings.Contains(line, "frame=")`. On ffmpeg 6.x a `-c copy` progress record begins `size=` and has no `frame=` (issue body, measured on 6.1.1). So `source_transcode.go:234` never calls `progress()`, `ffmpeg_speed` is never recorded, and the buffering detector never arms. The shipped ffmpeg 8.1.2 is unaffected.
- **Fix (from #350 R8).** `IsProgressLine` keeps `frame=` as its first clause and adds the 6.x shape: a line that begins `size=` or `Lsize=` and carries `speed=`. `emit` has already trimmed the line (`spawn.go:280`), so a prefix test is exact.
  - This is narrower than revision 1's "any line containing `speed=`". The existing assertion that `fps=25 speed=1.0x` is not a progress line (`progress_test.go:103-107`) stays unchanged and true, so rule 5 has nothing to list there.
  - The `frame=` exemption in the stderr flush guard (#24) is not widened, because a 6.x record is about 80 bytes and never reaches 1 KiB.
- **Real captures (from #350's A-1 Step 1).** Capture ffmpeg 6.1.1's stderr with the repository's own `scripts/capture_ffmpeg_stderr.py`, unmodified, in `ubuntu:24.04` pinned by digest (resolve it with `docker buildx imagetools inspect ubuntu:24.04`). Commit `normal` and `slow-trickle` as `relay/internal/relaytest/testdata/ffmpeg_stderr/ffmpeg6-normal.stderr` and `ffmpeg6-slow-trickle.stderr`, and add both names to `CorpusNames` (`corpus.go:30`). `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord` (`spawn_test.go:74`) then runs on them unchanged.
  - **Shape to confirm, a STOP if it does not hold:** `grep -c 'frame=' <file>` is 0 for both; every record begins `size=`; slow-trickle's speeds start above 1.0 and end below it.
  - #350 measured 12 and 64 records, each opening with `speed=N/A`. So **`CorpusSpeeds` must not be called on them**: it panics on a non-numeric speed, correctly for the 8.1.2 corpus.
  - Record the image digest and the `ffmpeg -version` line in `CAPTURE.md`. Do not commit that run's `truncation`, and never hand-edit a capture.
- **Tests.**
  - New `TestAnFFmpeg6StreamCopyRecordIsAProgressRecord`: a record read from `ffmpeg6-normal` is gated in and parses to a speed and a bitrate. It also asserts that `fps=25 speed=1.0x`, with no `size=` prefix, is still not a progress line.
  - New `TestAnFFmpeg6StreamCopyArmsTheBufferingDetector` (source_transcode_test.go, from #350): replaying `ffmpeg6-slow-trickle`, a speed is reported to the channel.
  - The two `CorpusNames` subtests of `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord`.
  - All red at the seed.
- **Size** S. **upstreamable** no. **Duplicates** none. Not in the ledger; CLAUDE.md lists it (`:135`), so A-1 adds a ledger entry at `fixed`.

### #302 — a failed buffering switch asks next-source on every progress record

- **Root cause.** `relay/channel/source_transcode.go:326-344`: on `ffmpeg.TimedOut` the reader calls `failoverFromBuffering`. On failure (`:342-343`) it only logs. `relay/ffmpeg/detector.go:86-88` returns `TimedOut` again on the next sub-threshold sample, because `since` is unchanged, so every record (about every 0.5 s in production) makes another control-plane call. `failover.go:298-300` returns false without touching the detector.
- **Fix.** `Detector.Rearm()`: the channel stays buffering and the next `TimedOut` comes a full `Timeout` from now, so a channel with no alternate asks once per `buffering_timeout` window. `BufferingFor()` keeps measuring from the first sub-threshold sample, so a later successful switch's `channel_failover.duration` stays truthful. That needs a second field (`retryFrom`), not a reset of `since`. (#350's `Defer()` is the same mechanism under another name.)
  - The failed-switch branch calls `Rearm()`, and so does #221's refusal, which returns through the same `false`. A spent budget is therefore re-checked once per window, locally, with no network call.
  - **A detector nobody re-arms still repeats `TimedOut` on every sample**, so `TestTheDetectorFollowsPythonsTransitions`' "a further sample after an unhandled timeout times out again" stays true and unchanged.
  - The comment on the `TimedOut` verdict (`detector.go:46-50`) is rewritten to say "until something resets or re-arms it".
- **Coverage detail (review finding 4).** Hoist the nil-clock fallback into `func (d *Detector) clock() func() time.Time`. `Observe`, `BufferingFor` and `Rearm` all use it, so `Rearm` adds no nil-clock branch of its own. The seed's two copies of the branch (`detector.go:73-76`, `:109-112`) collapse into one. The detector test drives it once with `Now: nil`, so the helper is covered in `relay/ffmpeg`'s own profile. Appendix A has the hunk.
- **Tests.**
  - Flip `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` (`source_transcode_test.go:442`) to `TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord` (listed under A-2).
  - New `TestRearmHoldsTheNextTimeoutBackAndKeepsTheBufferingDuration` in `detector_test.go`, which also covers `BufferingFor` (`detector.go:105-114`, uncovered at the seed).
- **Size** S. **upstreamable** no. **Duplicates** none. CLAUDE.md `:129`; A-2 adds a ledger entry at `fixed`.

### #221 — MAX_STREAM_SWITCHES does not bound buffering-triggered switches

- **Root cause.** `relay/channel/channel.go:455-457`: `switches` is a local of `run`. Only the health-monitor branch (`:539-541`) and the exhausted-URL branch (`:550-552`) increment it. `failoverFromBuffering` (`failover.go:293-318`) never reads it, and the run loop adopts the buffering switch at `:476-482` without counting it (the comment at `:479` says "row 6").
- **Fix (from #350 R1; revision 1 ended the channel instead).**
  - **One counter for both paths.** The counter becomes a `Channel` field under `c.mu`, with three accessors (`switchCount`, `countSwitch`, `resetSwitches`), replacing the run loop's local. The run loop's five uses move to the accessors.
  - **The buffering path consults it.** `failoverFromBuffering` checks it **before** asking the resolver. When `switchCount() >= MaxStreamSwitches` it logs once per refusal, returns `false`, and never calls the resolver. On a successful switch it counts.
  - **The channel keeps playing on the slow source.** The main loop's own behaviour at its bound is unchanged: it ends the channel, because it reaches the bound with no working source (`failover_test.go:604-624` stays the pin). The buffering path reaches the bound with a source that is still delivering, only slowly, so ending the tune there would turn a degraded stream into a dead one.
  - **Retires review finding 8.** Revision 1's end-the-channel form exited the run loop with `last == nil`, an `ErrSourcesExhausted` with no cause. Refusal never exits the loop, so that path no longer exists.
  - **The off-by-one between the two paths is inherent, and it is stated.** The main loop's condition is `switchCount() <= Max` evaluated *after* a switch: with `Max = 0` it makes one switch and then ends. The buffering path's is `switchCount() >= Max` evaluated *before*: with `Max = 0` it makes none, and with `Max = 1` it makes one.
  - **No race between check and count.** The run loop calls `failover` only after `runAttempt` returns, and `TranscodeSource.Run` waits for its stderr reader first (`source_transcode.go:187-189`). So the stderr reader's check-then-count never interleaves with a main-loop switch on the same channel.
  - **The stable-run reset (`:488-493`) is unchanged.** It fires only where the main loop sees an attempt end.
  - **An operator's `Advance` is not counted**, because it is not automatic.
- **Tests (listed under A-2).**
  - Flip `TestABufferingFailoverIgnoresMaxStreamSwitches` (`source_transcode_test.go:396`) to `TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent`.
  - New `TestABufferingFailoverCountsAgainstMaxStreamSwitches`.
  - The sibling `TestMaxStreamSwitchesBoundsAMainLoopSwitch` (`failover_test.go:604`) is unchanged and stays in row 6's Pin cell.
- **Size** M. **upstreamable** no. **Duplicates** none. Ledger `max-stream-switches-unbounded` (`defects.yml:21`).

### #296 — the UDP user-agent filter leaves dangling flags

- **Root cause.** `relay/channel/source_transcode.go:105-119`: on a `udp://` URL every argument containing the user agent, `user-agent` or `user_agent` is dropped, but the argument's partner is kept.
  - `-headers 'User-Agent: X'` spawns as a bare `-headers` whose value becomes `-i`. `source_transcode_test.go:569-585`'s `want` keeps the bare `-headers` on purpose.
  - The shipped Streamlink profile, `{streamUrl} --http-header User-Agent={userAgent} best --stdout` (`core/migrations/0011_fix_stream_profiles_and_user_agents.py:10`), spawns on UDP as `--http-header best --stdout`, handing the quality selector to the header. This is from #350 R9; verify the migration line when implementing.
- **Fix (both arms from #350 R9).**
  - **A dropped value takes its flag.** When the dropped argument does not begin with `-`, drop the immediately preceding argument too if it begins with `-`.
  - **A dropped flag takes its value.** When the dropped argument begins with `-`, drop the immediately following argument too if it does not begin with `-`. This catches `-user_agent ""`, where the user agent is empty and so the value matches nothing.
  - **Out of scope:** removing only the `User-Agent:` line from a multi-header `-headers` value. On a UDP upstream, HTTP headers are meaningless anyway.
- **Tests.**
  - Change `TestTheUDPFilterDropsUserAgentArguments`' `want` (listed under A-3).
  - New `TestTheUDPFilterLeavesNoDanglingFlag`: the Streamlink parameters keep `best --stdout`; `-user_agent ""` loses both elements; `-re -user_agent VLC/3 -i udp://…` keeps `-re`.
- **Size** S. **upstreamable** no. **Duplicates** none. CLAUDE.md `:134`; A-3 adds a ledger entry at `fixed`.

### #306 and #119 — the fMP4 scanner's resynchronisation discards instead of resynchronising

The two issues share one root cause, and one PR closes both. **Tracker disposition:** #350 closes #119 as a duplicate of #306; this plan keeps both open until A-4 merges and closes both with it. The outcome is the same and the lead chooses. #119 additionally asks for the stride to be bounded, and A-4's fragment ceiling does that.

- **Root cause.** `relay/output/fmp4.go:216-227`: when the working buffer does not start at a `moof`, `flush` calls `findMoofOffset(s.frag, 1)`.
  - `findMoofOffset` (`:145-165`) walks by box length. **From offset 1** it re-reads a length at a one-byte shift, and any value of 8 or more is a stride (`:156-162`). For any real box that shift yields a size in the tens of thousands, which jumps past every following box and returns -1. `:222-224` then clears the whole buffer, losing the fragments behind the misalignment.
  - The #119 counterexample, one garbage byte `0x01` read as a 16 MiB length, is exact **from offset 0**, which this path never scans (review finding 3). At the scanner level:
    - a one-byte prefix is recovered at the seed, because offset 1 lands on the real header;
    - **two** garbage bytes `{0x01, 0x01}` defeat it.
    - Both the review and #350 measured this.
  - The doc comment at `:136-140` claims recovery "at the next real box header either way", which is false.
  - Two adjacent faults surface on the same path:
    - A `moof` whose own length is below 8 makes `:229-231` return without consuming anything. The buffer never advances and grows with every write.
    - A corrupt length on a valid `moof` (`:233-236`), or on the box after one (`:238-240`), is read as "not complete yet" indefinitely. `s.frag` grows toward that length, up to 4 GiB.
- **Fix.**
  - **Search, don't walk.** Replace the resync call with `resyncMoof(data)`, which searches for the four bytes `moof` at a type position of 5 or more (a box start of 1 or more). A candidate is accepted only when its length is at least `minMoofBox` (16, a `moof` holding an `mfhd`) and at most `maxMoofBox` (1 MiB). The upper bound is from #350 R6: a `moof` literal inside payload bytes, with an implausible length, is not a resync point.
  - **Keep a tail.** When nothing is found, keep the last 7 bytes instead of clearing the buffer, so a header split across two reads survives.
  - **Treat a short `moof` as misaligned.** An aligned `moof` shorter than `minMoofBox` goes to the resync arm.
  - **Cap the fragment.** `s.frag` is capped at `MaxFragmentBytes`. Past it, with no fragment bound found, the scanner resynchronises from offset 1, in both the arms named above. The cap is 64 MiB, which is 50 Mbit/s times a 10-second keyframe interval with margin; see Open questions.
  - **Leave the aligned walk alone.** `findMoofOffset` itself is unchanged for the init-segment path, which already has its 10 MB abort (`:188-189`), and for the aligned fragment walk, where striding is what stops a `moof` inside an `mdat` payload from being taken for a box. Its doc comment is corrected.
  - Appendix B has the hunk.
- **Tests.**
  - Flip `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` (`scanner_test.go:181`) to `TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof` (listed under A-4).
  - New tests: one per arm, so that no new statement goes unexecuted (review finding 5), plus #119's direct finder assertion. They are listed under A-4.
  - `TestABoxLengthBelowEightAdvancesOneByteRatherThanGivingUp` (`:220`) tests `findMoofOffset` directly and is unchanged.
- **Size** M. **upstreamable** no.

### #233 — a stream-by-hash tune raises no persisted channel_start or channel_stop

- **Root cause.** The relay puts the tune identifier in `channel_id` whatever it is: `relay/channel/events.go:38` (`ChannelID: c.id`), raised at `manager.go:310` (`channel_start`) and `channel.go:442` (the deferred `emitStop`). For the admin single-stream preview the identifier is a 64-hex `stream_hash` (`apps/proxy/next_source.py:247-257`'s fallback). `apps/proxy/relay_serializers.py`'s event serializer accepts any string (`channel_id = CharField(required=False)`). `core/relay_events.py:46-56`'s `_clean` maps only `""` to None. `log_system_event` (`core/utils.py:890-924`) then hits `SystemEvent.channel_id`, a `UUIDField` (`core/models.py:817`), and its bare `except Exception` (`:922-924`) swallows the `ValidationError`. No row is written, no Connect fan-out runs, and one ERROR log line is written per event. The issue body blames "the event serializer"; the mechanism is the model field, but the outcome is the same.
- **Fix, Django side (the fix).** A `_split_identifier` helper in `core/relay_events.py`. A value that parses as a UUID stays `channel_id`. Anything else becomes `channel_id=None` plus `details["stream_hash"]`, unless `details` already carries one. It applies to every event type, so `client_connect`, `stream_switch` and the rest of a hash tune are written too. `channel_name` already carries the stream's name for a hash tune (`next_source.py:663`). The WebSocket push (`_push`) is unchanged and still carries the raw identifier. `str(uuid.UUID(value))` **normalises** the form: braces, `urn:uuid:` and un-hyphenated 32-hex all become canonical. That is harmless for the row, and the helper's docstring says so, so nobody later asserts the raw posted string against the column (review finding 9).
- **Relay side (a contract, not a change).** The relay keeps posting the identifier verbatim. Classifying it in Go would need a second copy of the UUID rule and change the wire for no gain, because Django owns the `UUIDField` and must defend it against any poster anyway. A-5 adds a doc paragraph to `relay/channel/events.go` stating the contract, and a Go test pinning it: a channel claimed under a non-UUID identifier emits `channel_start` and `channel_stop` with that identifier in `ChannelID`. A later Go change that dropped or rewrote it would break Django's classification silently. The test makes that change visible.
- **Tests.** New in `core/tests/test_relay_events.py`:
  - `test_a_stream_hash_identifier_writes_a_row_with_the_hash_in_details`, which is red at the seed: zero rows, one ERROR log.
  - `test_an_explicit_stream_hash_in_details_is_not_overwritten`.
  - The existing `test_each_event_becomes_a_system_event_row` and `test_an_event_without_a_channel_id_still_writes_a_row` are unchanged and guard the UUID and empty paths.
  - New Go test `TestAHashIdentifiedChannelReportsItsIdentifierAsTheChannelID` in `relay/channel/manager_test.go`.
- **Size** S. **upstreamable** no. **Duplicates** none.

### #222 — an fMP4 viewer is dropped on elapsed time alone

- **Root cause.** `relay/httpapi/fmp4.go:229-236`: once `ClientTimeout` (`STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD`, 40 s by default) passes with no fragment, the client is dropped. There is no health gate and no keepalive cap. The TS loop drops only an unhealthy channel's client (`relay/httpapi/stream.go:1023`), and before that holds it on keepalives for up to `MaxKeepalive` (`:1005-1022`). So a failover slower than 40 s drops fMP4 viewers and keeps TS ones. The doc comment at `fmp4.go:112-158` is the row in prose.
- **Fix.** Give the fMP4 loop the exits the TS loop actually reaches, less the one fMP4 cannot perform. #350 R3 reaches the same design.
  - **Healthy channel:** no silence drop, as on TS.
  - **Unhealthy channel:** a wall-clock cap of `MaxKeepalive`, counted from the first empty read on an unhealthy channel and cleared by the next fragment or by a healthy sighting, as `keepaliveStart` is on TS. This is TS's reachable exit (`stream.go:1009-1013`).
  - **No bytes are sent.** An ISO-BMFF stream has no null packet a player is known to skip, and a partial box would corrupt the player's parse.
  - **Upstream timeout.** nginx's `proxy_read_timeout 300s` on the live locations is at least the default `MaxKeepalive` of 300 s (from #350 R3; verify the `docker/nginx.conf` lines when implementing), so the silent wait is not cut short upstream.
  - The `url_switching` exemption stays unported on both loops. The reason the doc comment gives at `:134-144` still holds.
  - **Residual, stated rather than hidden.** A remux wedged alive on a healthy channel now holds its fMP4 clients until they hang up. That is no worse than today: dropping them never cured the wedge, because a reconnecting client rejoins the same shared remux (`relay/output`, one per channel). A remux-liveness watchdog is new work; see Open questions.
  - Appendix C has the hunk.
- **Tests (listed under A-6).**
  - Flip `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` (`fmp4_test.go:384`) to `TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient`.
  - New `TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap`. It is built on the rig of `TestAClientIsDroppedOnceTheKeepaliveCapIsReached` (`keepalive_test.go:107-137`), which **parks the run loop inside `failover()` with `r.Control.SetDelay(6 * time.Second)`** so the channel stays unhealthy for the whole window.
  - A resolver answering "no alternate" does the opposite, which review finding 2 traced: `channel.go:536-545` clears the failures and retries the same URL, `runAttempt` sets `healthy = true` (`channel.go:590`), the stand-in serves again, and the cap's clock resets on every healthy sighting.
- **Size** M. **upstreamable** no. **Duplicates** none. Ledger `fmp4-timeout-no-switch-exemption` (`defects.yml:22`).

### #314 — `source_bitrate` and `ffmpeg_bitrate` are declared and emitted by nothing

- **Root cause.** `apps/proxy/relay_serializers.py:133` (`source_bitrate`) and `:141` (`ffmpeg_bitrate`) are declared on `RelayChannelDetailSerializer`. `relay/httpapi/detail.go`'s `detailPayload` (`:134-175`) carries neither, by design (comment `:118-133`), although the relay computes the output bitrate on every progress record (`relay/channel/stats.go:39`, `:105-107`, `FFmpegOutputBitrate`) and drops it. The Python name mismatch the issue describes went with `live_proxy/`; only the Go absence and the Django declaration remain.
- **Fix.** #350 R4 reaches the same design.
  - **`ffmpeg_bitrate`:** add `FFmpegBitrate string `json:"ffmpeg_bitrate,omitempty"`` to `detailPayload` in serializer declaration order, between `ActualFPS` and `StreamType`. `describeChannelDetail` renders it as `pythonFloat(*stats.FFmpegOutputBitrate)`, the same string form as its neighbours `ffmpeg_fps` and `actual_fps` (`detail.go:345-350`); the serializer field is a `CharField`.
  - **`source_bitrate`:** delete it from the serializer. No writer exists and no frontend code reads it (`grep -rn source_bitrate frontend/src` is empty at the seed). A live input's preamble reads `bitrate: N/A` anyway (#350 R4, from `normal.stderr`'s preamble). Removing a declared-but-never-emitted optional field changes no response any client has ever received.
- **Tests (listed under A-7).**
  - Flip `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` (`detail_golden_test.go:222`) to `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate`.
  - Empty `NEVER_WRITTEN` in `apps/proxy/tests/test_relay_detail_payload_golden.py:49-62`. That leaves the completeness test (`test_the_fixture_covers_every_serializer_field`) pinning every remaining field. Give `fixture()` an `ffmpeg_bitrate`, and regenerate `relay/httpapi/testdata/channel_detail.json` with `DISPATCHARR_WRITE_GOLDEN=1`.
  - Add `TestTheDetailEndpointCarriesTheFFmpegOutputBitrate`, which covers the new statement in the httpapi package. No test seam calls `describeChannelDetail` directly (`grep -n describeChannelDetail relay/httpapi/*_test.go` is empty at the seed; review finding 13), so it goes through the rig's `GET /proxy/relay/channels/<id>` on a transcode channel replaying the `slow-trickle` corpus. That corpus's records carry `bitrate=`, so `FFmpegOutputBitrate` is set. It asserts `ffmpeg_bitrate` is present and parses as a float.
- **Size** S. **upstreamable** no. **Duplicates** none. CLAUDE.md `:136`; A-7 adds a ledger entry at `fixed`.

---

## PR sections

Every PR follows the commit discipline of `CLAUDE.md`:

- Stage and commit in separate Bash calls.
- Write the message with the Write tool and commit with `-F`.
- Anchor every command on the PR's own worktree, `cd /Users/dion/git/Dispatcharr/.worktrees/<branch-leaf> && …`.
- The Go PostToolUse hook runs build, vet, lint and `-race` on the edited package for every `.go` edit. **Keep prototypes out of commits.** A break-check is an edit you revert before staging, never one you commit.
- A new test that refers to a symbol the fix introduces (`maxStderrLine`, `Rearm`, `resyncMoof`, `callTimes`) needs that symbol to exist for its red run. Add a stub that changes no behaviour first, as #350's plan does: a declared constant nothing reads, an empty method, or a finder returning -1. Then replace the stub in the fix task. The red must then be a **failed assertion naming the mechanism**, never a compile error or a panic.

Every break-check below is run the same way: make the named wrong edit, run the named test, and confirm it fails **with a message naming the mechanism** (a red for a side reason is not a pass). Then revert and confirm green. Record each in the PR body.

### A-1 — `fix/A-1-ffmpeg-stderr-parsing` (#24, #227, #299)

- **Files.** `relay/ffmpeg/spawn.go`, `relay/ffmpeg/progress.go`, `relay/ffmpeg/progress_test.go`, `relay/ffmpeg/spawn_test.go`, `relay/channel/source_transcode_test.go`, `relay/internal/relaytest/corpus.go`, two new captures and `CAPTURE.md` under `relay/internal/relaytest/testdata/ffmpeg_stderr/`, `.github/workflows/go-tests.yml` (comment), `docs/relay-parity-matrix.md` (row 28; row 4's citation), `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** `python scripts/ci_backend_test_labels.py relay/ffmpeg/progress.go` prints `[]`, so no backend label runs.
- **Go CI.** `go-tests.yml` runs build, vet, `-race`, lint under three GOOS, credlint and the coverage gate. `relay/internal/relaytest` is outside the coverage denominator.
- **Guards.** They run because the matrix is in the diff.
- **zizmor.** The workflow edit triggers the zizmor hook, and the file must stay at zero findings.

Tasks:

- [ ] **1. Seed coverage.** Measure the seed profile per "The two CI gates" above and keep it.
- [ ] **2. Captures.** Capture ffmpeg 6.1.1's stderr per the #299 analysis above (from #350). Use `scripts/capture_ffmpeg_stderr.py`, unmodified, in `ubuntu:24.04@sha256:<resolved digest>` with apt `ffmpeg` and `python3`, writing to a scratch directory.
  - Copy `normal.stderr` and `slow-trickle.stderr` in as `ffmpeg6-normal.stderr` and `ffmpeg6-slow-trickle.stderr`, and add both names to `CorpusNames` (`corpus.go:30`).
  - Confirm the shape: zero `frame=`, every record `size=`-led, and slow-trickle crossing 1.0 downward. **A different shape is a STOP**, reported rather than worked around.
  - If Docker cannot run the capture, say so in the PR. Fall back to one inline literal, the issue body's measured line `size=     464kB time=00:00:07.74 bitrate= 490.4kbits/s speed=1.08x`, in the progress test only. Drop the source_transcode test, and record the fallback as a gap.
- [ ] **3. #227 red first.** Flip the pin. `progress_test.go:11-47` (the `fullSpeedRe` declaration and the test) becomes a `var (...)` block with `fullSpeedRe` and a new test-local `mantissaSpeedRe = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)` (the seed's production literal, commented as "what the parser read before #227"), plus `TestAScientificNotationSpeedIsReadWithItsExponent`.
  - **Before:** `mantissa` came from the production `speedRe`; the test asserted `*p.Speed == mantissa` and `*p.Speed < actual/100` (the latter failing with "#227 appears to have been fixed").
  - **After:** `mantissa` comes from `mantissaSpeedRe`, and the corpus-shape guard `actual/mantissa < 100 → re-derive` is kept against it, so it still means "the capture still carries an exponent". The test asserts `*p.Speed == actual`, failing with `Speed = %v, want the whole value %v (the mantissa alone is %v: issue #227)`.
  - Delete the "PINS A DEFECT … Do not fix this" header and replace it with one naming #227 as fixed.
  - Run `cd relay && go test -run TestAScientificNotationSpeedIsReadWithItsExponent ./ffmpeg/`. It must be **red** at the seed regex with `Speed = 1.41, want the whole value 1410 …` (#350 measured exactly this message).
- [ ] **4. #227 fix.**
  - Replace `speedRe` (`progress.go:33`) and rewrite the comment at `:25-31` to state that the exponent is read and why (the truncation capture), and that `fpsRe` keeps its narrow class.
  - Widen `corpus.go`'s `corpusSpeedRe` to the same literal and rewrite its comment (`:104-108`): it copies the shipped regex so a test can quote what the parser sees, the copy must move when the parser does, and the deleted `manager_support.py` reference goes.
  - Add the two table rows to `TestParseProgressReadsTheRealRecordShapes`. Green.
  - **Break-check 4a:** revert `speedRe`, and the flipped test goes red with the message above, **not** with "re-derive". Confirming the message is the whole point of task 3's local regex.
- [ ] **5. #299 red first.** Add `TestAnFFmpeg6StreamCopyRecordIsAProgressRecord` (progress_test.go, before `// Every shape CAPTURE.md names`) and `TestAnFFmpeg6StreamCopyArmsTheBufferingDetector` (source_transcode_test.go, before `// Recovery: a speed back at the threshold`). With task 2's names in `CorpusNames`, `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord` gains two subtests. Expected reds at the seed, as #350 measured on its prototype:
  - `a real ffmpeg 6.1.1 progress record is not a progress line (#299): "size=… speed=N/A"`;
  - `the reader saw 0 progress lines, the corpus holds 12 records`;
  - `timed out … waiting for a speed reported off a 6.1.1 record`.
  - `TestAnUnparseableNumberDropsTheWholeRecord` is **unchanged** and stays green throughout.
- [ ] **6. #299 fix.**
  - The fix, with `strings` already imported:
    ```go
    func IsProgressLine(line string) bool {
        if strings.Contains(line, "frame=") {
            return true
        }
        return (strings.HasPrefix(line, "size=") || strings.HasPrefix(line, "Lsize=")) && strings.Contains(line, "speed=")
    }
    ```
  - Rewrite the comment at `:38-39` to name both majors, and say the line is already trimmed by `emit`. Green.
  - **Break-check 6a:** replace the second clause with `return false`, and the three tests redden with the messages above.
- [ ] **7. #24 red first.** Add `TestAnUnterminatedFrameRecordCannotGrowTheReaderWithoutBound` to `spawn_test.go`, driven per the #24 analysis: about 2 MiB of `frame=1 ` with no terminator, the child kept alive, and a 10 s deadline.
  - Assertions: no callback line exceeds `maxStderrLine + 4096`, and at least one line arrives while the child is alive.
  - For the red run, declare `const maxStderrLine = 64 << 10` alone in `spawn.go` first.
  - Red at the seed: nothing arrives while the child lives. At EOF, after `Kill`, one line of about 2 MiB arrives.
- [ ] **8. #24 fix.** In `ReadStderr` (`spawn.go:253-257`) the no-terminator branch becomes `if len(buf) > maxStderrLine || (len(buf) > 1024 && !bytes.Contains(buf, []byte("frame=")))`. Document the ceiling beside the 1 KiB rule in the doc comment at `:226-238`, including that it flushes and never drops. Green.
  - **Break-check 8a:** delete the `len(buf) > maxStderrLine ||` clause, and the test goes red naming the oversize line.
- [ ] **9. Matrix row 28.**
  - **Behaviour:** "`ffmpeg_speed` is parsed with an optional exponent: real ffmpeg 8.1.2 emits `speed=1.41e+03x` on a truncated input and both status surfaces report 1410, not its mantissa".
  - **Source:** `relay/ffmpeg/progress.go:<regex block through IsProgressLine>`, `relay/httpapi/detail.go:485-500`, `relay/httpapi/channels.go:85-95`.
  - **Pin:** `relay/ffmpeg/progress_test.go::TestAScientificNotationSpeedIsReadWithItsExponent`.
  - **Notes:** open with "Filed as [#227](…) and fixed in #<PR>; reproduced per D5 until stage 2d-4 left it an ordinary Go defect". Keep the found-by-capture and failover-unaffected sentences. Add that `fps=` keeps the narrow class.
  - One line, no padding. Re-anchor row 4's `relay/ffmpeg/progress.go:20-40` citation on the same span. Run the guard.
- [ ] **10. Prose.**
  - **`CAPTURE.md`:** "These three files" becomes "These five files". Add a provenance paragraph for the two 6.1.1 captures: the image digest, the `ffmpeg -version` line, the date, the command, and that `truncation` from that run was not kept. Add table rows stating shape only. The #227 bullet (`:88-98`) ends "Fixed in #<PR>; the parser now reads the exponent", in place of "Reproduced here, not fixed".
  - **`go-tests.yml:147-156`:** replace "so ffmpeg 6.x is blind to every progress line … Do not widen the parser or this test to accommodate 6.x -- #299 owns that." with a sentence saying the gate accepts ffmpeg 6.x's `size=`-led records since #<PR>. The job keeps the production ffmpeg because row 4's measured burn-off shape is that version's.
  - **`CLAUDE.md` `:135`:** rewrite the bullet beginning "**The buffering-progress gate is structurally blind on ffmpeg 6.x" to one sentence: "Fixed in #<PR> ([#299](…)): the progress gate also accepts ffmpeg 6.x's `size=`-led stream-copy records, which carry no `frame=`." This follows the section's precedent for closed defects (#295, #190; review finding 11).
  - **`CLAUDE.md` `:63`:** in the Test-hooks bullet on `scripts/check_go_credential_logging.sh`, replace "so the verbatim-ported `IsProgressLine` gate never passes and the pin fails rather than skips when `CI` is set" with "which the `IsProgressLine` gate did not accept until [#299](…) was fixed, so the pin failed rather than skipped when `CI` is set". This is #350's wording. The rest of that sentence stays true.
  - Anchor every `CLAUDE.md` edit on its quoted text.
- [ ] **11. Ledger.**
  - `ffmpeg-speed-scientific-notation` (`defects.yml:32`): `status: fixed`, `fixed_in: <PR>`, `status_changed: <merge date>`; keep `test`.
  - Append `{id: ffmpeg6-progress-gate-blind, title: "The progress gate required frame=, which ffmpeg 6.x stream-copy records never carry, so no speed was recorded and the buffering detector could never arm on a user-supplied ffmpeg 6", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 299, test: relay/ffmpeg/progress_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-14, status_changed: <date>}`.
  - #24 has no ledger entry and no CLAUDE.md bullet; add none.
  - Run `python -m metrics.build --validate-only --curated metrics/curated`.
- [ ] **12. Gates.**
  - Coverage diff per the header. The new statements in `relay/ffmpeg` are the gate's second clause and the ceiling's condition, all executed by the package's own tasks 3–8 tests, so there is no new uncovered block. #350 measured `relay/ffmpeg` at 34 → 31 missing with A-1 and A-2 together.
  - `cd e2e && npx playwright test --project=guards parity-matrix`.
  - `cd relay && go test -count=1 -race ./ffmpeg/ ./channel/`. The channel package consumes `IsProgressLine` and `CorpusSpeeds`, so its buffering tests are the integration check.

PR description draft:

> **fix(relay): read ffmpeg's exponent, accept ffmpeg 6 progress records, bound the stderr reader — #24, #227, #299**
>
> Three defects the Go relay carried verbatim from the Python relay under spec D5. Since stage 2d-4 they are ordinary Go defects (A16.12 item 4).
>
> - **#227.** `speed=1.41e+03x` was read as 1.41. `speedRe` now reads the exponent, and so does `relaytest`'s documented copy of it. Parity-matrix row 28 is rewritten and its pin flipped.
> - **#299.** On ffmpeg 6.x a stream-copy progress record begins `size=` and carries no `frame=`, so the buffering detector could never arm. The gate now also accepts a `size=`/`Lsize=`-led record carrying `speed=`. Two real ffmpeg 6.1.1 captures join the corpus, with provenance in `CAPTURE.md`.
> - **#24.** An unterminated stderr buffer containing `frame=` grew until EOF inside the process that carries every live viewer. It is now flushed past 64 KiB whatever it carries; nothing is dropped.
>
> Test changed under the fix plan's rule 5: `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` becomes `…IsReadWithItsExponent`, shown red before the fix and green after. Its precondition now reads the mantissa through a test-local copy of the old regex, since the production one can no longer supply it.
>
> Red at the base, green here; break-checks: <table>. Go coverage ratchet: no new uncovered block (diff attached); floor untouched. Ledger: `ffmpeg-speed-scientific-notation` is set to fixed, and a new entry for #299 is added at fixed.
>
> Closes #24, #227, #299.

### A-2 — `fix/A-2-buffering-failover-bounds` (#302, #221)

- **Files.** `relay/ffmpeg/detector.go`, `relay/ffmpeg/detector_test.go`, `relay/channel/channel.go`, `relay/channel/failover.go`, `relay/channel/source_transcode.go`, `relay/channel/tuning.go` (comment), `relay/channel/failover_test.go` (the `callTimes` accessor), `relay/channel/source_transcode_test.go`, `docs/relay-parity-matrix.md` (row 6; the citations of rows 1, 3, 4 and 5 if their ranges move), `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** Backend `[]`. Go as A-1. Guards run because the matrix is edited.

Tasks:

- [ ] **1. Seed coverage** (the tree after A-1 merged).
- [ ] **2. Test support.** Add `func (r *fakeResolver) callTimes() []time.Time` to `failover_test.go`, returning a copy of `calledAt` under `r.mu`, beside `firstCallAt()` (`:62-69`) (review finding 7). Add `bufferingOnlyCorpus(t) string` to `source_transcode_test.go`. It writes a temp corpus of the `slow-trickle` capture's own records with its sub-threshold tail repeated four times; the tail is located with `CorpusSpeeds`, as `slowTrickleTail` (`:303-318`) already checks it.
  - This is a synthetic **order**, not a synthetic line: the same exception `TestBufferingEndsWhenTheSpeedRecovers` (`:468-511`) takes, with its reason stated.
  - It is played **without** `--stderr-loop`, so the channel buffers once and stays buffering for about 6 s at 20 ms a record.
  - Why it is needed (from #350's A-2 note): the seed's looping corpus re-opens every pass with a record above the threshold, which ends buffering and restarts the clock. Under the fix, asks span seconds and cross passes, so "state is buffering" would be sampled at an arbitrary point of the loop.
- [ ] **3. #302 red first.** Flip `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` (`source_transcode_test.go:436-470`) to `TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord`. The rig is the same except for the corpus: API-maximum threshold, 1 s timeout, `fakeResolver{}` always answering `ErrNoAlternate`, and the corpus from task 2.
  - **Before:**
    1. `waitFor(… ">= 1")`.
    2. `waitFor(… "a third failed switch, one per record" … >= 3)` within 10 s. It passes in about 60 ms at the seed.
    3. State is buffering, and the channel is not done.
  - **After:**
    1. `waitFor(t, "a third ask", 20*time.Second, func() bool { return len(resolver.requests()) >= 3 })`.
    2. Then, over `resolver.callTimes()`, **every consecutive gap ≥ 900 ms**. That is a lower bound only, 0.1 s under the 1 s timeout, the same allowance `failover_test.go:369-392` makes for #309. It fails with `asks %d and %d were %s apart, under the 1s buffering_timeout: the channel is asking on every record (#302)`.
    3. State is buffering, **kept**.
    4. The channel is not done, **kept**.
  - Red at the seed: #350 measured `asks 0 and 1 were 22.007ms apart …`.
  - The asserted count is 3, as before. Per the "latching conditions" rule, widen a window if it flakes; never lower the count.
- [ ] **4. #302 fix.** Appendix A's hunk.
  - `detector.go` gains the `clock()` helper (used by `Observe`, `BufferingFor` and `Rearm`), a `retryFrom time.Time` field and `Rearm()`.
  - `Observe`'s timeout test measures from the later of `since` and `retryFrom`. `Reset()` and the `Ended` edge clear `retryFrom`. The `TimedOut` verdict's comment (`:46-50`) says "until something resets or re-arms it".
  - `source_transcode.go:342-343`'s failure branch calls `r.detector.Rearm()` after its log line. Rewrite the `:327-332` comment ("one control-plane call per progress record … reproduced and filed").
  - Add `TestRearmHoldsTheNextTimeoutBackAndKeepsTheBufferingDuration` to `detector_test.go`, with an injected clock:
    1. Started at t=0, TimedOut at t=1.1 s, `Rearm()`.
    2. Continuing at t=1.5 s.
    3. TimedOut at t=2.2 s; `BufferingFor()` is 2.2 s, not 1.1 s.
    4. An above-threshold sample returns `Ended`. A fresh sub-threshold sample then starts a new window, which proves `retryFrom` was cleared.
    5. One final case with a `Detector{Now: nil}` that calls `Rearm()` and `BufferingFor()`, so `clock()`'s nil branch is covered in this package (review finding 4).
  - Green.
  - **Break-check 4a:** remove the `Rearm()` call, and the flipped channel test goes red with the gap message.
  - **Break-check 4b:** make `Rearm()` also reset `since`, and the detector test's `BufferingFor` assertion goes red.
- [ ] **5. #221 red first.** **Replace** `TestABufferingFailoverIgnoresMaxStreamSwitches` (with its comment, `:387-434`) with the following two tests (from #350; its measured messages are quoted).
  - **`TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent`:** `MaxStreamSwitches = 0`, the same resolver answer as the seed test, the task-2 corpus. After three `buffering_timeout`s of buffering (`waitFor` on `channel_buffering`, then 3.5 s), it asserts:
    - zero resolver requests (the failure message is `the resolver was asked %d times under MAX_STREAM_SWITCHES = 0: the buffering path ignored the bound (#221)`);
    - `ch.Source().StreamID == 1`;
    - the alternate's child never ran (`ran.get() == 0`);
    - zero `channel_failover`;
    - the channel not done.
  - **`TestABufferingFailoverCountsAgainstMaxStreamSwitches`:** `MaxStreamSwitches = 1`, two answers, both sources replaying the task-2 corpus. Exactly one request in the window, and the channel on stream 2.
  - Red at the seed. #350 measured `asked 1 times under … = 0` and `asked 29 times under … = 1, want 1`. The 29 is because #302 is unfixed there too.
  - **Before (seed test):**
    1. `waitFor(… ch.Source().StreamID == 2)`.
    2. `waitFor(… ran.get() == 1)`.
    3. After 300 ms, `state == StateActive`.
    4. Exactly one `channel_failover`.
  - **After:** the refusal assertions above. The setup (corpus family, lever, resolver answer) is unchanged, so the only variable is the bound.
- [ ] **6. #221 fix.** Appendix A's second hunk.
  - **`channel.go`:** a `switches int` field beside `failures` in the `Channel` struct, under `c.mu`, and three accessors: `switchCount()`, `countSwitch()` and `resetSwitches()`. The run loop's local goes, and its five uses become the accessors:
    - the loop condition (`:457`);
    - the stable-run reset (`:492`);
    - the two `switches++` (`:540`, `:551`);
    - the log field (`:555`).
  - **The `takePending` branch (`:476-482`) does not count**, because `failoverFromBuffering` already did. Rewrite its comment, and the `run` doc comment's sentence at `:428-429`.
  - **`failover.go`'s `failoverFromBuffering`:** before `c.failover(…)`, `if c.switchCount() >= c.tuning.MaxStreamSwitches { c.log.Warn("the stream-switch budget is spent; keeping the current stream", "channel", c.id, "switches", c.switchCount()); return false }`. After a successful `failover`, `c.countSwitch()`. Rewrite the doc comment at `:283-292`.
  - **`tuning.go:77-80`:** the `MaxStreamSwitches` comment names both paths.
  - Green.
  - **Break-check 6a:** disable the budget check (`if false && …`). Both new tests redden: `asked 1 times under … = 0 …` and `asked 2 times under … = 1, want 1 …`.
  - **Break-check 6b:** remove `c.countSwitch()` from `failoverFromBuffering`. The second test reddens.
  - **Also run** `TestASustainedSubThresholdSpeedFailsTheChannelOver` (row 1's pin) and `TestMaxStreamSwitchesBoundsAMainLoopSwitch`, both unedited and green. `transcodeTuning` (`source_transcode_test.go:43`) starts from `testTuning()`, whose `MaxStreamSwitches` is 10 (`manager_test.go:32`).
- [ ] **7. Matrix.**
  - **Row 6, replaced in place:**
    - **Behaviour:** "`MAX_STREAM_SWITCHES` bounds buffering-triggered switches as well as the main loop's: a buffering timeout with the budget spent does not ask for a next source, and the channel keeps playing on the slow source rather than ending".
    - **Source:** `relay/channel/channel.go:<run loop>`, `relay/channel/failover.go:<failoverFromBuffering>`.
    - **Pin:** the two new `source_transcode_test.go` symbols plus `relay/channel/failover_test.go::TestMaxStreamSwitchesBoundsAMainLoopSwitch`.
    - **Notes:** "Filed as [#221](…) and fixed in #<PR>; reproduced per D5 until stage 2d-4. One counter serves both paths; at the bound the main loop ends the channel (no working source) and the buffering path refuses the switch (a source still delivering). The third pin is the main loop's side."
    - This is #350's row text, adapted.
  - **Rows 1, 3, 4 and 5:** re-anchor any `channel.go`, `detector.go` or `source_transcode.go` range this PR moved.
  - Run the guard.
- [ ] **8. Prose and ledger.**
  - **`CLAUDE.md` `:128`:** rewrite the bullet beginning "`MAX_STREAM_SWITCHES` doesn't bound buffering-triggered switches" to "Fixed in #<PR> ([#221](…)): a buffering-triggered switch counts against `MAX_STREAM_SWITCHES` and, once the budget is spent, is refused and the channel keeps playing."
  - **`CLAUDE.md` `:129`:** rewrite the bullet beginning "**A buffering timeout with no alternate asks `next-source` on every progress record**" to "Fixed in #<PR> ([#302](…)): a failed or refused buffering switch re-arms the detector, so the control plane is asked once per `buffering_timeout`."
  - **`CLAUDE.md` `:82`:** in the State paragraph, replace "the buffering-triggered switch bypasses `MAX_STREAM_SWITCHES` as in Python (row 6)" with "the buffering-triggered switch counts against `MAX_STREAM_SWITCHES` and, once it is spent, is refused rather than fatal (row 6, [#221](…))". This is #350's wording.
  - Anchor every edit on its quoted text.
  - **Ledger:** set `max-stream-switches-unbounded` (`:21`) to `fixed`, keeping `test`. Append `{id: buffering-timeout-asks-every-record, title: "A buffering timeout with no alternate asked next-source on every ffmpeg progress record, about twice a second, for as long as the speed stayed low", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 302, test: relay/channel/source_transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-15, status_changed: <date>}`.
  - Validate.
- [ ] **9. Gates.**
  - **Coverage diff.** In `relay/ffmpeg`, `clock()`, `Rearm` and the `retryFrom` arms are covered by task 4's detector test, and `BufferingFor` becomes covered. In `relay/channel`, the accessors run on every channel, the refusal runs in the bound-zero test, and the count in the bound-one test. There is no new uncovered block.
  - #350 measured `relay/channel` at 219 → 219 missing with the same design, and noted that this package holds 37% of the module's shortfall (the floor header's per-package table). Read its per-package figure before pushing.
  - `go test -count=3 -race -run 'Buffering|MaxStreamSwitches|Rearm' ./channel/ ./ffmpeg/`, three runs because these are timing tests.
  - Run the guard.

PR description draft:

> **fix(relay): bound buffering switches by MAX_STREAM_SWITCHES (#221), and stop asking on every record (#302)**
>
> - **#221.** A buffering-triggered switch never counted against `MAX_STREAM_SWITCHES`. One counter now serves both paths. With the budget spent, the buffering path does not ask for a next source and keeps playing the slow one. The main loop still ends the channel at its bound, as before.
> - **#302.** After a buffering switch failed or was refused, the stderr reader asked next-source again on every progress record, about twice a second. `Detector.Rearm()` holds the next timeout back by one `buffering_timeout` and keeps the buffering clock, so `channel_failover.duration` still measures from the first slow sample.
>
> Two defect pins are replaced and one added. The before/after assertions are in the plan, and each is shown red at the base and green here. Row 6 is rewritten. Ledger: #221's entry is set to fixed, and a new entry for #302 is added at fixed. Go ratchet: `relay/ffmpeg` falls; `relay/channel` adds no uncovered block.
>
> Closes #221, #302.

### A-3 — `fix/A-3-udp-user-agent-flags` (#296)

- **Files.** `relay/channel/source_transcode.go:97-119`, `relay/channel/source_transcode_test.go:566-585`, `metrics/curated/defects.yml`, `CLAUDE.md`, and `docs/relay-parity-matrix.md` (re-anchor row 1's `source_transcode.go` range only if it moves).
- **Test labels.** Backend `[]`. Go. If the matrix is edited the guard runs in CI; run it locally either way.

Tasks:

- [ ] **1. Red first.** Rename `TestTheUDPFilterDropsUserAgentArguments` (`:569`) to `TestTheUDPFilterDropsUserAgentArgumentsWithTheirFlags`.
  - **Before:** `want := []string{"-headers", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}`, with the comment calling the kept `-headers` a reproduced defect.
  - **After:** `want := []string{"-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}`, with the comment naming #296 as fixed. The HTTP half is unchanged.
  - Add `TestTheUDPFilterLeavesNoDanglingFlag`, a table of three rows:
    1. The Streamlink argv `udp://239.0.0.1:1234 --http-header User-Agent=VLC/3 best --stdout` gives `udp://239.0.0.1:1234 best --stdout`.
    2. `-user_agent "" -i udp://…`, with `UserAgent` empty, gives `-i udp://…`.
    3. `-re -user_agent VLC/3 -i udp://…` gives `-re -i udp://…`.
  - Red at the seed. #350 measured the first two messages; row 3 is the boundary and is green at the seed.
- [ ] **2. Fix.** Rewrite `argv()` as a single index loop.
  - Lift the seed's match predicate out as `carriesUserAgent(arg)`, and add `isFlag(arg) = strings.HasPrefix(arg, "-")`.
  - When `carriesUserAgent(s.Argv[i])`:
    - if it is not a flag and the last kept element is `s.Argv[i-1]` and is a flag, pop it;
    - if it is a flag and `i+1 < len` and `s.Argv[i+1]` is not a flag, skip `i+1` too.
  - Rewrite the doc comment `:97-104`. Green.
  - **Break-check 2a:** delete the value-takes-flag arm. The first test and row 1 of the second go red.
  - **Break-check 2b:** delete the flag-takes-value arm. Row 2 goes red.
  - **Break-check 2c:** pop the preceding flag unconditionally. Row 3 goes red on `-re`.
- [ ] **3. Prose and ledger.**
  - **`CLAUDE.md` `:134`:** rewrite the bullet beginning "**The UDP user-agent filter leaves dangling flags**" to "Fixed in #<PR> ([#296](…)): on a `udp://` upstream the user-agent filter now drops a flag together with its value."
  - **Ledger:** append `{id: udp-user-agent-dangling-flag, title: "The UDP user-agent filter dropped the argument carrying the user agent and kept the flag before it, so -headers 'User-Agent: X' spawned as a bare -headers", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 296, test: relay/channel/source_transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-14, status_changed: <date>}`.
  - Validate.
- [ ] **4. Gates.** Coverage diff: every new branch is executed by task 1's tests. Run the guard locally.

PR description draft:

> **fix(relay): the UDP user-agent filter drops a flag with its value (#296)**
>
> On a `udp://` upstream the filter dropped each argument carrying the user agent and kept its partner. `-headers 'User-Agent: X' -i <url>` spawned as `-headers -i <url>`, and the shipped Streamlink profile spawned as `--http-header best --stdout`. A dropped value now takes the flag before it, and a dropped flag takes the value after it. `TestTheUDPFilterDropsUserAgentArguments`' expected argv changes (before/after in the plan), and a new table test pins both arms and the boundary. Ledger: new entry for #296 at fixed.
>
> Closes #296.

### A-4 — `fix/A-4-fmp4-scanner-resync` (#306, #119)

- **Files.** `relay/output/fmp4.go:130-245`, `relay/output/scanner_test.go`.
- **Test labels.** Backend `[]`. Go.
- **Guards.** No matrix row cites `relay/output/fmp4.go` (verify with `grep -n 'relay/output/fmp4.go' docs/relay-parity-matrix.md`), and this is the one PR whose diff does not trigger the guard in CI; run it locally anyway. No ledger entry.

Tasks:

- [ ] **1. Red first.** Replace `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` (`:181-218`) with the tests below. For the red run, stub `resyncMoof` as `return -1` and declare the constants and the `MaxFragmentBytes` var.
  - **`TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof`**, the flip. Same input: a 72-byte `junk` box, then fragments 5 and 6.
    - **Before:** `len(collect(f)) == 0` and `f.Head() == 0`, per the lines after `:215`; read them in full before editing.
    - **After:** exactly one fragment published, carrying `relaytest.FMP4FragmentIndex(got[0]) == 5`, with 6 held back.
    - The comment block `:182-203` is rewritten to state the fix and keep the Python-verification paragraph as history.
  - **`TestAGarbageRunThatReadsAsALargeLengthDoesNotHideTheNextMoof`**, #119. Two assertions:
    - **Direct, the issue's own counterexample:** `resyncMoof(append([]byte{0x01}, moofBoxOf16Bytes...))` returns 1, where `findMoofOffset(same, 0)` returns -1. The second half documents the stride; it is not a change.
    - **Through the scanner:** prefix `{0x01, 0x01}` + fragments 0 and 1 publishes fragment 0. A one-byte prefix would be green at the seed (review finding 3).
  - **`TestAMoofHeaderSplitAcrossReadsSurvivesAResync`:** write garbage plus the first 6 bytes of fragment 0's header, then the rest of fragments 0 and 1 in a second write. Fragment 0 is published.
  - **`TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint`** (from #350). A junk box whose payload holds `\x00\x00\x00\x08moof` (length 8, below `minMoofBox`) and another `\xff\xff\xff\xffmoof` (above `maxMoofBox`), ahead of a real fragment. Each rejection step inside `resyncMoof` runs, and the real `moof` is chosen (review finding 5a).
  - **`TestAMoofShorterThanItsOwnHeaderIsSkippedNotStuckOn`:** an aligned `\x00\x00\x00\x08moof` followed by fragments 0 and 1. At the seed the buffer never advances, and `len(s.frag)` grows across three further writes; after the fix fragment 0 is published.
  - **`TestAFragmentPastTheCeilingIsAbandonedNotBufferedForever`:** table-driven over both corrupt-length shapes (review finding 5b), with `MaxFragmentBytes` lowered to 4096 through the package var and restored with `t.Cleanup`:
    - (a) a `moof` whose own length reads `0x7fffffff`;
    - (b) a valid `moof` followed by an `mdat` whose length reads `0x7fffffff`.
    - Each is followed by 5000 bytes of junk and fragments 7 and 8. Fragment 7 is published and `len(s.frag)` stays below `MaxFragmentBytes` plus one write.
  - All are red at the seed except the direct half of the #119 test, which needs the stub to compile and so is red by definition.
- [ ] **2. Fix.** Appendix B.
  - Correct `findMoofOffset`'s doc comment (`:136-140`); its code is unchanged.
  - Add `resyncMoof`, `minMoofBox = 16`, `maxMoofBox = 1 << 20`, `resyncTail = 7`, and `MaxFragmentBytes` as a package `var`, documented as a var only so tests can lower it.
  - Add the tail-retention and both ceiling branches in `flush`.
  - Green.
  - **Break-check 2a:** keep a 0-byte tail instead of 7. The split-read test goes red: `published 0 fragments, want fragment 0: its header straddled the read and was discarded`.
  - **Break-check 2b:** go back to `findMoofOffset(s.frag, 1)`. The flip and #119's scanner half go red.
  - **Break-check 2c:** remove the length window from `resyncMoof`. The implausible-length test goes red: `resyncMoof chose 1, want the real moof at …`.
  - **Break-check 2d:** remove either ceiling branch. The matching table row goes red.
- [ ] **3. Gates.**
  - Coverage diff: the seed's uncovered `relay/output/fmp4.go:226.4` (a successful resync) and `:231.4` (a `moof` length below 8) blocks are now covered. Every new statement is executed by task 1's tests, one test per arm. #350 measured `relay/output` 15 → 14 with a smaller design.
  - `go test -count=1 -race ./output/`, and `go test -race -run FMP4 ./httpapi/`, the fMP4 end-to-end rigs that drive this scanner.
  - Run the guard locally.

PR description draft:

> **fix(relay): the fMP4 scanner resynchronises instead of discarding (#306, #119)**
>
> When the working buffer did not begin at a `moof`, the scanner walked box lengths from offset 1. That re-read a length at a one-byte shift, jumped past every real box, returned -1 and cleared the whole buffer. It now searches for the literal type bytes and accepts a candidate only with a plausible length. It keeps a 7-byte tail so a header split across reads survives. It abandons a fragment that grows past `MaxFragmentBytes` (64 MiB) instead of buffering toward a corrupt 4 GiB length. A `moof` shorter than its own header no longer stalls the buffer. The aligned walks still stride, which is what keeps a `moof` inside an `mdat` from being taken for a box.
>
> `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` is flipped (before/after in the plan). Five new tests carry #119's shrunk counterexample and the adjacent faults, one per branch. Go ratchet: two previously uncovered blocks are now covered.
>
> Closes #306, #119.

### A-5 — `fix/A-5-hash-tune-events` (#233)

- **Files.** `core/relay_events.py`, `core/tests/test_relay_events.py`, `relay/channel/events.go` (comment), `relay/channel/manager_test.go`.
- **Test labels.** `python scripts/ci_backend_test_labels.py core/relay_events.py core/tests/test_relay_events.py` prints `["core.tests"]`. Guards run in CI because the diff touches `core/`. The Go files add no label. `core/relay_events.py` is **not** a Gate 2 module (the nine are listed in `scripts/coverage_live_path.coveragerc`), so no isolated coverage run is owed.
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

- [ ] **1. Red first, the flip.** Replace `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` (with its comment, `:356-470`, the end of the file) with `TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient`. The compression is the seed test's: `STREAM_TIMEOUT` 1 and `FAILOVER_GRACE_PERIOD` 1, `CONNECTION_TIMEOUT` left at its 10 s default (`relay/internal/relaytest/controlplane.go:44`) so the channel stays healthy, and the upstream stall after 200,000 bytes. Two changes, both from #350's A-5 notes:
  - **`MAX_KEEPALIVE_DURATION` compressed to 1.** Without it, a fix that capped on `MaxKeepalive` regardless of health would pass this test, since the default 300 s is far beyond the window.
  - **The remux stand-in changes from 200 fragments at 20 ms to 5 at once** (`withRemux(standInRemux(t, "--fmp4-fragments", "5", "--fmp4-interval", "0"))`, checking the flag spellings in `relaytest/standin.go`). The stand-in ignores its input. With 200 fragments it fed the fMP4 client for four seconds of a six-second window, and #350's prototype's first draft passed with the defect's elapsed-time drop re-inserted. Five fragments starve the client from its first second, which is the stall the test's name describes.
  - **Before:**
    1. The fMP4 body reaches EOF within 30 s.
    2. `sent > 0`.
    3. `took >= 2s`.
    4. The channel is healthy.
    5. `ch.Clients() == 1`.
  - **After:**
    1. Read the fMP4 body in a goroutine.
    2. After `3 * (STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD)` = 6 s, assert the body has **not** ended, failing with `the fMP4 client was dropped (%d bytes sent) on a HEALTHY channel inside 6s: the loop timed it out on elapsed time alone (#222)`.
    3. Assert `ch.Healthy()`, and assert `ch.Clients() == 2`.
    4. Rewrite the header comment: the TS-contrast paragraph becomes "the two loops agree".
  - Red at the seed. #350 measured `dropped (16776 bytes sent) on a HEALTHY channel inside 6s …`.
- [ ] **2. Red first, the cap.** Add `TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap` on the rig of `TestAClientIsDroppedOnceTheKeepaliveCapIsReached` (`keepalive_test.go:107-137`):
  - **Overrides:** `CONNECTION_TIMEOUT` 0.3, `HEALTH_CHECK_INTERVAL` 0.05, `STREAM_TIMEOUT` 0.25 and `FAILOVER_GRACE_PERIOD` 0.25 (so `ClientTimeout` is 0.5 s), and `MAX_KEEPALIVE_DURATION` 2.
  - **Control-plane hold:** `r.Control.SetDelay(8 * time.Second)` after the tune, which parks the run loop inside `failover()` so the channel stays unhealthy for the whole window. This replaces revision 1's "resolver with no alternate" (review finding 2).
  - **The clock.** Poll until `ch.Healthy()` first returns false. Take the clock **before** each `Healthy()` call, and keep the reading taken before the last call that returned true. The flip, and the cap's clock that cannot start before it, both come after that instant, so the measured gap is never shorter than the real one. #350's first draft read it after the poll's wait and measured 1.99 s against a 2 s cap once under `-race`.
  - **Assertions:**
    - the fMP4 body ends no sooner than 2 s after that instant (a lower bound, failing with `dropped %s after the channel went unhealthy, before the 2s keepalive cap: stream_timeout + failover_grace_period ended it (#222)`);
    - it ends within 6 s (an upper bound with room for `-race`);
    - no fMP4 bytes arrive after the channel went unhealthy, because fMP4 sends no keepalive.
  - Red at the seed: the client is dropped about 0.5 s in. #350 measured `dropped 193.067375ms after the channel went unhealthy …` with its own compression.
- [ ] **3. Fix.** Appendix C.
  - `serveFMP4Client` replaces the `lastYield` timeout with `stallStart time.Time`. On a wait timeout:
    - if `ch.Healthy()`, clear `stallStart` and continue;
    - otherwise set `stallStart` on first sight, and return once `time.Since(stallStart) > tuning.MaxKeepalive`, logging "fMP4 stall outlasted the keepalive duration on an unhealthy channel, disconnecting".
  - A fragment write clears `stallStart`.
  - Rewrite the doc comment `:112-158` to describe the new contract, the no-bytes reason and the residual (a remux wedged on a healthy channel).
  - Green.
  - **Break-check 3a:** delete the `if ch.Healthy() { … continue }` gate. Task 1's test reddens with its message; it is visible only because `MAX_KEEPALIVE_DURATION` is compressed there.
  - **Break-check 3b:** use `tuning.ClientTimeout` in place of `tuning.MaxKeepalive`. Task 2's test reddens with its lower-bound message.
  - **Break-check 3c:** never return. Task 2's test reddens on its 6 s upper bound.
- [ ] **4. Matrix row 12**, replaced in place.
  - **Behaviour:** "An fMP4 client leaves by the exit a TS client reaches: on a healthy channel a stall never times it out, and on an unhealthy one it is dropped once `MAX_KEEPALIVE_DURATION` passes with nothing to send, not `stream_timeout + failover_grace_period` into the stall".
  - **Source:** `relay/httpapi/fmp4.go:<doc comment through the loop>` and `relay/httpapi/stream.go:1005-1031`. Re-anchor the second citation after J-1 if J-1 has landed.
  - **Pin:** both new test symbols.
  - **Notes:** "Filed as [#222](…) and fixed in #<PR>; reproduced per D5 until stage 2d-4. The fMP4 loop now takes the TS loop's reachable exit, the keepalive cap, without writing keepalive bytes, since an fMP4 stream has no null packet a player is known to skip. Neither loop ports the `url_switching` exemption, which the keepalive shadows." This is adapted from #350's row.
  - Run the guard.
- [ ] **5. Prose and ledger.**
  - **`CLAUDE.md` `:130`:** rewrite the bullet beginning "The fMP4 generator's `_is_timeout()` lacks the TS generator's `url_switching` exemption" to "Fixed in #<PR> ([#222](…)): an fMP4 client is no longer dropped on elapsed time alone; like a TS client it is held on a healthy channel and dropped at `MAX_KEEPALIVE_DURATION` on an unhealthy one."
  - **Ledger:** set `fmp4-timeout-no-switch-exemption` (`:22`) to `fixed`, keeping `test`.
  - Validate.
- [ ] **6. Gates.**
  - Coverage diff: the gate, the clock and the cap are executed by tasks 1–2. The deleted `lastYield` timeout statements were covered.
  - The floor's header names `relay/httpapi/fmp4.go:188.4,189.1` as a local flapper. If it appears in the diff, it is that block and not this PR's doing; say so in the PR if it does.
  - `go test -count=3 -race -run 'FMP4|Keepalive' ./httpapi/`. Each unhealthy-rig test takes about 20–30 s, mostly teardown waiting on the control-plane hold.
  - Run the guard. The full E2E runs through `migration/**`.

PR description draft:

> **fix(relay): an fMP4 viewer survives a failover the way a TS viewer does (#222)**
>
> The fMP4 loop dropped a client `stream_timeout + failover_grace_period` (40 s) after its last fragment, whatever the channel's health, while the TS loop on the same channel holds its client for up to `MAX_KEEPALIVE_DURATION`. The fMP4 loop now has the TS loop's reachable exits: no silence drop on a healthy channel, and a `MAX_KEEPALIVE_DURATION` cap on an unhealthy one. It sends no keepalive bytes, because fMP4 has no null packet.
>
> Residual, stated: a remux wedged alive on a healthy channel now holds its clients until they hang up. Dropping them never helped, because a reconnect joins the same shared remux.
>
> Row 12 is rewritten. `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` is replaced (before/after in the plan) and a keepalive-cap test is added. Ledger `fmp4-timeout-no-switch-exemption` is set to fixed. `migration/` branch because the PR edits `relay/httpapi/`.
>
> Closes #222.

### A-7 — `migration/A-7-detail-ffmpeg-bitrate` (#314)

- **Why `migration/`.** It edits `relay/httpapi/`.
- **Files.** `relay/httpapi/detail.go`, `relay/httpapi/detail_golden_test.go`, `relay/httpapi/testdata/channel_detail.json`, one new rig test (`TestTheDetailEndpointCarriesTheFFmpegOutputBitrate`, beside the detail endpoint's existing rig tests), `apps/proxy/relay_serializers.py`, `apps/proxy/tests/test_relay_detail_payload_golden.py`, `metrics/curated/defects.yml`, `CLAUDE.md`.
- **Test labels.** `python scripts/ci_backend_test_labels.py apps/proxy/relay_serializers.py` prints `["apps.proxy.tests"]`. Go. Guards run in CI because the diff touches `apps/`. Full E2E.
- **Gate 2 applies.** `apps/proxy/relay_serializers.py` is one of the nine Gate 2 modules, so run `scripts/coverage_live_path_isolated.sh` before push, and read `--gate` against `scripts/coverage_live_path.floor`. Deleting one field declaration removes one covered statement; `missing` must not move. **Run it after J-4 has landed if J-4 is merged by then**: J-4 fixes that driver's dropped arguments. Otherwise pass `--gate` exactly as J-4's plan describes.

Tasks:

- [ ] **1. Red first, Go.** Flip `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` (`detail_golden_test.go:216-244`) to `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate`.
  - **Before:** for each of `source_bitrate` and `ffmpeg_bitrate`, `if _, present := payload[key]; present { t.Errorf(…) }`, plus the three neighbours present.
  - **After:** `ffmpeg_bitrate` is present and equal to the golden struct's value (`"3500.0"`, added to `detailGoldenPayload` at the `FFmpegFPS` line `:94`); `source_bitrate` is still absent, now because the serializer no longer declares it (comment says so); the three neighbours are still present.
  - Add `TestTheDetailEndpointCarriesTheFFmpegOutputBitrate`. No test seam calls `describeChannelDetail` (review finding 13), so it goes through the rig: tune a transcode channel replaying the `slow-trickle` corpus, whose records carry `bitrate=`, wait for a progress record to land, then `GET /proxy/relay/channels/<id>`. Assert `ffmpeg_bitrate` is present and `strconv.ParseFloat` accepts it. This is what covers `detail.go`'s new assignment in the httpapi package's own profile; the golden struct literal does not execute it.
  - Red at the seed: the field does not exist.
- [ ] **2. Fix, Go.** Add `FFmpegBitrate string `json:"ffmpeg_bitrate,omitempty"`` to `detailPayload` between `ActualFPS` and `StreamType`, which is the serializer's declaration order (`relay_serializers.py:138-142`). In `describeChannelDetail` (`detail.go:~350`), `if stats.FFmpegOutputBitrate != nil { out.FFmpegBitrate = pythonFloat(*stats.FFmpegOutputBitrate) }`. Rewrite the comment at `:118-133` to say `ffmpeg_bitrate` is emitted since #<PR> and `source_bitrate` was removed from the serializer. Green.
  - **Break-check 2a:** remove the assignment, and the rig test goes red with `ffmpeg_bitrate` absent.
- [ ] **3. Django.** Delete `source_bitrate = serializers.CharField(required=False)` (`relay_serializers.py:133`). In `test_relay_detail_payload_golden.py`, empty `NEVER_WRITTEN` (keep the name and a comment saying why it is empty, so a future absence has a home) and add `"ffmpeg_bitrate": "3500.0"` to `fixture()`. Regenerate the golden: `DISPATCHARR_WRITE_GOLDEN=1 python manage.py test apps.proxy.tests.test_relay_detail_payload_golden` in your own container, and commit the regenerated `relay/httpapi/testdata/channel_detail.json`. Re-run without the variable, then `cd relay && go test ./httpapi/ -run Golden`. Both are green, so the two implementations read one golden.
  - **Break-check 3a:** put `source_bitrate` back in the serializer without a fixture value, and `test_the_fixture_covers_every_serializer_field` goes red. That proves the completeness test still bites with `NEVER_WRITTEN` empty.
- [ ] **4. Schema.** Confirm drf-spectacular's schema still generates: `python manage.py spectacular --validate --file /dev/null` in the container. `source_bitrate` leaves `GET /proxy/ts/status/<uuid>`'s documented shape, and no frontend code reads it (seed grep empty).
- [ ] **5. Prose and ledger.** `CLAUDE.md`: rewrite the bullet beginning "**Two fields on `GET /proxy/ts/status/<uuid>` are documented and emitted by nothing**" (`:136`) to "Fixed in #<PR> ([#314](…)): the detail payload carries `ffmpeg_bitrate` from the relay's own output-bitrate reading, and `source_bitrate`, which nothing ever wrote, is gone from the serializer." Also edit the Architecture section's "Observing a channel" paragraph if it names either field; grep `CLAUDE.md` for `source_bitrate` and `ffmpeg_bitrate`, and at the seed only `:136` does. Append `{id: detail-bitrate-fields-unwritten, title: "source_bitrate and ffmpeg_bitrate were declared on the channel detail payload and emitted by nothing", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 314, test: relay/httpapi/detail_golden_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-15, status_changed: <date>}`. Validate.
- [ ] **6. Gates.** Go coverage diff: about two statements, covered by task 1's rig test. Gate 2 isolated run: `missing` unchanged. `apps.proxy.tests` once without `--keepdb`. Guard locally. Full E2E.

PR description draft:

> **fix(relay): the channel detail carries ffmpeg_bitrate; source_bitrate is removed (#314)**
>
> The relay computed ffmpeg's output bitrate on every progress record and dropped it. `GET /proxy/ts/status/<uuid>` now carries it as `ffmpeg_bitrate`, a string like its `ffmpeg_fps` neighbour. `source_bitrate` had no writer in either relay and no reader in the frontend, so it is deleted from `RelayChannelDetailSerializer` rather than left documented and empty.
>
> The golden is regenerated from Django's serializer and read back by Go. `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` is flipped (before/after in the plan). Gate 2's isolated run shows `missing` unchanged. `migration/` branch because the PR edits `relay/httpapi/`.
>
> Closes #314.

---

## Appendix A — #302 and #221 (A-2 tasks 4 and 6)

`relay/ffmpeg/detector.go`:

```diff
@@ type Detector struct {
 	buffering bool
 	since     time.Time
+	// retryFrom is when the current timeout window began, if a failed or
+	// refused switch re-armed it (Rearm). Zero means the window began at
+	// since. Kept apart from since so BufferingFor, and the channel_failover
+	// duration built on it, still measures from the first slow sample (#302).
+	retryFrom time.Time
 }
+
+// clock is Now, or time.Now when it is nil: the one copy of the fallback
+// Observe, BufferingFor and Rearm share.
+func (d *Detector) clock() func() time.Time {
+	if d.Now == nil {
+		return time.Now
+	}
+	return d.Now
+}
@@ func (d *Detector) Observe(speed float64) Verdict {
-	now := d.Now
-	if now == nil {
-		now = time.Now
-	}
+	now := d.clock()
 	if speed < d.Threshold {
@@
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
@@ func (d *Detector) BufferingFor() time.Duration {
 	if !d.buffering {
 		return 0
 	}
-	now := d.Now
-	if now == nil {
-		now = time.Now
-	}
-	return now().Sub(d.since)
+	return d.clock()().Sub(d.since)
 }
+
+// Rearm is the failed-or-refused-switch branch (#302, #221): the channel
+// stays buffering and the next TimedOut comes a full Timeout from now, so a
+// channel with no alternate, or with its switch budget spent, asks once per
+// window rather than once per progress record. BufferingFor is unaffected.
+func (d *Detector) Rearm() { d.retryFrom = d.clock()() }
@@ func (d *Detector) Reset() {
 	d.buffering = false
 	d.since = time.Time{}
+	d.retryFrom = time.Time{}
 }
```

`relay/channel/source_transcode.go`, the `TimedOut` case's failure branch:

```diff
 		} else {
 			s.log().Error("failed to switch to the next stream after a buffering timeout", "channel", s.channelID())
+			r.detector.Rearm()
 		}
```

`relay/channel/failover.go`, `failoverFromBuffering` (after #350's Appendix C, adapted):

```diff
 func (c *Channel) failoverFromBuffering(bufferingFor time.Duration) bool {
 	ctx := c.ctx
 	if ctx == nil {
 		ctx = context.Background()
 	}
+	// #221: one budget for every automatic switch. Checked BEFORE asking, so
+	// a spent budget costs no control-plane call; the caller re-arms its
+	// detector either way (#302).
+	if n := c.switchCount(); n >= c.tuning.MaxStreamSwitches {
+		c.log.Warn("the stream-switch budget is spent; keeping the current stream",
+			"channel", c.id, "switches", n, "max", c.tuning.MaxStreamSwitches)
+		return false
+	}
 	resolved, ok := c.failover(ctx, "buffering_timeout")
 	if !ok {
 		return false
 	}
+	c.countSwitch()
 	c.mu.Lock()
 	c.pending = &resolved
```

`relay/channel/channel.go`: add a `switches int` field beside `failures` (`:162`), guarded by `mu`, plus the three accessors. The run loop's `switches := 0` goes, and its uses become `c.switchCount()` (the loop condition and the log field), `c.countSwitch()` (the two main-loop failovers) and `c.resetSwitches()` (the stable-run reset).

## Appendix B — #306/#119, `relay/output/fmp4.go` (A-4 task 2)

```diff
+// The window a resync candidate's length must fall in. Below minMoofBox is
+// shorter than a moof's own header plus an mfhd; above maxMoofBox is not a
+// moof ffmpeg writes (from #350 R6). Garbage that happens to spell "moof"
+// fails one or the other.
+const (
+	minMoofBox = 16
+	maxMoofBox = 1 << 20
+	// resyncTail is what a failed search keeps: a 4-byte length plus 3 bytes
+	// of type, the most of a header that can straddle a read unseen.
+	resyncTail = 7
+)
+
+// MaxFragmentBytes bounds the working buffer while a fragment has no end in
+// sight. A var, not a const, only so scanner_test.go can lower it.
+var MaxFragmentBytes = 64 << 20
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
+		size := binary.BigEndian.Uint32(data[start : start+4])
+		if size >= minMoofBox && size <= maxMoofBox {
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
+				keep := min(len(s.frag), resyncTail)
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

Two notes on this hunk:

- **The one-byte step.** `s.frag[1:]` deliberately misaligns the buffer so the next pass takes the resync arm. An implementer may call `resyncMoof` directly instead, as long as break-check 2d still reddens.
- **The aligned branch.** An aligned `moof` with `size > maxMoofBox` is **not** sent to resync; only a short one is. A long one is either real and still arriving, or corrupt and caught by the ceiling. `TestAFragmentPastTheCeilingIsAbandonedNotBufferedForever` row (a) is that case.

## Appendix C — #222, `relay/httpapi/fmp4.go` (A-6 task 3)

```diff
-	lastYield := time.Now()
+	// stallStart is when this client's current stall was first seen on an
+	// UNHEALTHY channel; zero while the channel is healthy or data flows --
+	// serveClient's keepaliveStart, without the keepalive bytes.
+	var stallStart time.Time
 	for {
@@
 		if len(frags) > 0 {
 			cursor = next
 			if !writeChunks(w, rc, frags) {
 				return
 			}
-			lastYield = time.Now()
-			client.Touch(lastYield)
+			stallStart = time.Time{}
+			client.Touch(time.Now())
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
+			// ROW 12, fixed (#222): the TS loop's reachable exits. Healthy:
+			// wait, as serveClient does. Unhealthy: at most MaxKeepalive,
+			// serveClient's cap -- without the null packets, which fMP4 has
+			// no equivalent of.
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
+
+    A UUID comes back CANONICAL (str(uuid.UUID(...))): braces, urn:uuid:
+    and un-hyphenated forms all normalise. Compare rows against the
+    canonical form, never against the raw posted string.
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

---

## Open questions

Each has a default this plan already adopts. The user rules only if they want the other reading.

1. **#221: refuse the switch and keep playing, or end the channel?** Revision 2 adopts #350 R1: once the budget is spent, a buffering timeout does not ask and the channel keeps playing the slow source. The alternative, revision 1's, counts the buffering switch in the run loop and ends the channel exactly as a main-loop switch does. That gives the bound one meaning, but it turns a degraded picture into an error screen, and it exits the loop with no cause recorded (review finding 8). **Default: refuse and keep playing.** The round-1 reviewer preferred the other default before #350 was read, so this is a real choice for the user.
2. **#314: delete `source_bitrate`, or implement it?** Deleting removes a documented field that never had a value. Implementing it means parsing the input's bitrate from ffmpeg's preamble, which on a live input usually reads `bitrate: N/A`. **Default: delete.**
3. **#306/#119: the 64 MiB fragment ceiling.** It is a derived threshold (50 Mbit/s × 10 s GOP, with margin), not a measurement. The constant's comment carries the formula. Raise it if higher-bitrate sources are known; the tests lower it and do not depend on its value.
4. **#222: a remux-liveness watchdog.** A-6 removes the only thing that ended a client of a remux wedged alive on a healthy channel. That never cured the wedge, but a watchdog that restarts a remux whose input advances while its output does not would be the real fix. It is new work, not a defect fix. **Default: file it as a new issue after A-6 merges; not planned here.**
5. **`e2e-tests.yml`'s guards trigger has no `relay/` prefix** (`:110`, `:127-133`). A relay-only PR that moves a cited line past its file's end passes PR CI and fails the guard on `main`. In this plan only A-4 is in that position. The fix is a one-line workflow edit, outside category A's issues. **Default: the lead routes it (category G owns workflows); every A PR runs the guard locally meanwhile.**
6. **#119: close as a duplicate of #306, or close both by the PR?** #350 closes #119 as a duplicate. This plan closes both through A-4's description. The outcome is the same. **The lead's call.**

---

## Review round 1 dispositions

Against `review-A-r1.md` (fable, pinned to `0e21dd9d`).

| # | kind | disposition |
|---|---|---|
| 1 | blocking | **Accepted.** A-1 task 3: the precondition reads the mantissa through a test-local `mantissaSpeedRe`, and break-check 4a names the message it must show. #350 made the same move. |
| 2 | blocking | **Accepted.** A-6 task 2 is rebuilt on `keepalive_test.go`'s `SetDelay` rig, with #350's clock-before-healthy reading. Task 1 compresses `MAX_KEEPALIVE_DURATION` and starves the client (#350's stand-in note). |
| 3 | should-fix | **Accepted.** A two-byte `{0x01, 0x01}` prefix at scanner level, and the issue's literal against the finder directly. The per-issue prose now says the 16 MiB reading holds from offset 0 only. |
| 4 | should-fix | **Accepted.** A `clock()` helper serves `Observe`, `BufferingFor` and `Rearm`. The detector test has a nil-clock case. The `TimedOut` verdict comment is rewritten. |
| 5 | should-fix | **Accepted.** Each branch of `resyncMoof` and each ceiling arm now has its own named test; the ceiling test is a two-row table. |
| 6 | should-fix | **Accepted, against #350 R10**, which leaves the copy alone. The copy is widened, its comment rewritten, and the dead `manager_support.py` reference dropped. |
| 7 | should-fix | **Accepted.** A-2 task 2 names `fakeResolver.callTimes()`. |
| 8 | should-fix | **Mooted.** #221 now refuses rather than ends the channel (from #350 R1), so no path exits the loop with `last == nil`. The alternative is recorded under Open questions 1. |
| 9 | should-fix | **Accepted.** The #233 analysis and the helper's docstring state the normalisation. |
| 10 | nit | **Accepted.** The gates section has a per-PR table: guards run in CI on A-5 (`core/`) and A-7 (`apps/`), and not on A-4. |
| 11 | nit | **Accepted.** Every closed Known-defects bullet is rewritten to one sentence naming its PR, not deleted. |
| 12 | nit | **Accepted.** The #24 analysis explains the corpus is all preamble and written at once. |
| 13 | nit | **Accepted.** A-7's render test goes through the rig, and the #314 analysis says why (no seam; slow-trickle carries `bitrate=`). |

**What was taken from #350** (`docs/fixplan-A` at `587a0582`), each marked in the text:

- **#221:** R1's refusal, with its shared counter and accessors.
- **#299:** R8's narrower gate and the real 6.1.1 capture step.
- **#296:** R9's second arm, plus the Streamlink evidence.
- **#306:** R6's upper length bound.
- **#302:** the A-2 steady-buffering corpus.
- **#222:** the A-5 stand-in and clock notes.
- **CLAUDE.md:** the `:63` and `:82` wordings.
- **Measured break-check and red messages,** quoted where marked.

**Where this plan keeps its own:**

- **#227:** the relaytest copy of the speed regex is widened (review finding 6).
- **#306:** a fragment ceiling that #350 lacks, with the #119 cap.
- **#221:** the stated off-by-one between the two paths.
- **#222:** the wedged-remux residual.
- **#233:** the normalisation note.
- **#119:** both issues stay open until A-4 closes them.

---

## Coverage table

| issue | disposition | PR |
|---|---|---|
| #24 | fix | A-1 |
| #119 | fix (shares root cause with #306; both close) | A-4 |
| #221 | fix (refuse and keep playing) | A-2 |
| #222 | fix | A-6 |
| #227 | fix | A-1 |
| #233 | fix (Django side) + contract pin (relay side) | A-5 |
| #296 | fix | A-3 |
| #299 | fix | A-1 |
| #302 | fix | A-2 |
| #306 | fix | A-4 |
| #314 | fix (`ffmpeg_bitrate` emitted, `source_bitrate` deleted) | A-7 |

Eleven issues, seven PRs, no memos.
