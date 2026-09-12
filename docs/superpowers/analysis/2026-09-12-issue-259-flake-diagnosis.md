# Issue #259 — diagnosis of the `FfmpegStderrFailoverTests` flakes

Written 2026-09-12 against `analysis/issue-259-flake` at `93900a6f` (main's tip,
`contract(phase2): 2b-1 … (#256)`). Measurement only: **no production or test code was
changed**, in this worktree or anywhere else. Every rate below comes from runs listed in
§ 1 with the command quoted; every failure message is copied from a log, none predicted.

## Summary

Three findings, in descending order of how much they should change what anyone does:

1. **The issue names the wrong test as the file's flake risk.** In 72 local executions of
   the whole `FfmpegStderrFailoverTests` class, the test named in #259 —
   `test_the_captured_cumulative_lead_must_burn_off_before_the_detector_arms` (parity row
   4) — failed **zero** times, across 116 executions in total. Its sibling
   `test_a_buffering_threshold_change_does_not_reach_a_running_channel` (parity row 5)
   failed **34 of 96**, a 35% rate, in both the coverage and the plain arm. Row 5 has
   never been seen to fail in CI; row 4 has been seen once. They fail at *opposite ends*
   of the machine-speed axis, which is why each is invisible where the other bites.
2. **The mechanism for row 4 is measured and quantified, and it is not what the issue
   says.** The observable window is ~290 ms wide, and its lower edge is set by a
   hard-coded `threading.Timer(0.5, …)` in production code
   (`apps/proxy/live_proxy/input/manager.py:1953`), not by the tracer. Coverage
   instrumentation does **not** shrink it: measured median 312 ms with coverage vs 287 ms
   without, 52 runs, ranges fully overlapping. The window is quantised in 500 ms steps,
   and the step below the one every observed run lands on is a *negative* window — i.e.
   the failure is a discrete rung, not a tolerance that can be widened into safety.
3. **Both tests should pin an edge, not a sample.** For row 4 the edge already exists and
   is already written to the database: the single `channel_buffering` `SystemEvent`
   carries the `speed` that armed the detector. Asserting on it makes the test
   deterministic and kills the race outright, rather than trading it for a wider margin.

The in-flight PR is exposed: the coverage matrix is **not** path-gated, so
`Coverage apps.proxy.live_proxy.tests` runs on every non-docs push to any branch (§ 5).

Added after three further observers reported row 5 (§ 3a, § 4a, § 7): the two tests
**do not share a mechanism**, they share a design flaw and fail in opposite directions
with machine speed; contention makes row 5 *more* reliable, not less, measured across
three load levels; and `scripts/coverage_live_path_isolated.sh` loses a whole coverage
round to this failure rather than one label.

## 1. Reproduction, with rates

All local runs are in a container created solely for this work
(`dispatcharr-flake259`, its own `dispatcharr-flake259-db` volume), bind-mounted at this
worktree. The shared `dispatcharr-testrunner` was not touched.

Base command (the `cov` arm adds `COVERAGE_CORE=sysmon` and
`-m coverage run --rcfile=scripts/coverage_live_path.coveragerc`, which is what
`scripts/coverage_live_path.sh --label` runs):

```bash
docker exec dispatcharr-flake259 redis-cli flushall
docker exec \
  -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  [-e COVERAGE_CORE=sysmon] \
  dispatcharr-flake259 /dispatcharrpy/bin/python \
  [-m coverage run --rcfile=scripts/coverage_live_path.coveragerc] \
  manage.py test --keepdb -v1 <target>
```

| # | arm | CPU quota | target | runs | row 4 fails | row 5 fails |
|---|-----|-----------|--------|------|-------------|-------------|
| A | coverage | 14 | row 4 alone | 12 | 0 | n/a |
| B | coverage | 14 | full label (249 tests) | 10 | 0 | 5 |
| C | plain | 14 | full label (249 tests) | 10 | 0 | 3 |
| D | coverage | 4 | the class (5 tests) | 20 | 0 | 6 |
| E | coverage | 2 | the class (5 tests) | 20 | 0 | 7 |
| F | coverage | 2 | full label (249 tests) | 12 | 0 | 7 |
| G | coverage | 2 | row 4 alone | 20 | 0 | n/a |
| H | plain | 2 | row 4 alone | 20 | 0 | n/a |
| I | coverage | 0.5 | row 4 alone | 12 | 0 | n/a |
| J | coverage, DEBUG | 14 | the class (5 tests) | 8 | 0 | 3 |
| K | coverage, DEBUG | 14, 4 busy loops | the class (5 tests) | 8 | 0 | 3 |
| L | coverage, DEBUG | 14, 24 busy loops | the class (5 tests) | 8 | 0 | **0** |

Row 4 ran in every one of those runs (it sorts last in the class, and a row-5 failure does
not stop it): **140 executions, 0 failures.** Row 5 ran in arms B–F and J–L: **96
executions, 34 failures = 35%** — 31/86 (36%) under coverage, 3/10 under plain. Arms J–L
are the DEBUG-level captures § 2 measures the window from; they carry the same rate as the
quiet arms, so the logging did not manufacture the effect it was used to observe.

Row 5's failure text, copied verbatim from
`scratchpad/covlabel/run-2.log` (arm B) — four distinct variants were seen, differing only
in which three speeds were caught:

```
FAIL: test_a_buffering_threshold_change_does_not_reach_a_running_channel
      (apps.proxy.live_proxy.tests.test_manager_stderr_failover.FfmpegStderrFailoverTests.
       test_a_buffering_threshold_change_does_not_reach_a_running_channel)
AssertionError: 3 not greater than or equal to 4 : too few distinct speeds after the
change to prove records were still being parsed: [2.87, 6.8, 11.5]
```

Other observed sets: `[5.27, 6.8, 11.5]`, `[2.87, 2.95, 11.5]`, `[3.25, 3.42, 3.66]`.

### CI side

Every attempt of every `backend-tests.yml` run since `test_manager_stderr_failover.py`
landed (`cfccf00d`, 2026-09-10 22:57), enumerated through
`repos/D10Scot/Dispatcharr/actions/runs/<id>/attempts/<n>/jobs`:

| job | runs | failures |
|-----|------|----------|
| `Coverage apps.proxy.live_proxy.tests` | 32 | **1** (the #259 occurrence) |
| `apps.proxy.live_proxy.tests` (plain) | 32 | 0 |

So the CI rate for row 4 is **1/32 ≈ 3%** per coverage-label job. 1-of-32 against 0-of-32
is not evidence that instrumentation is the discriminating variable (Fisher exact p = 1.0);
§ 3 measures that question directly instead, and answers it no. No CI failure of row 5 has
been observed.

**I did not reproduce the failure #259 names.** That is a finding, not a gap in effort:
140 local executions across eight environments, spanning a 28x CPU-quota range and three
host-load levels, produced none.
§ 2 explains why — the failure needs a discrete event that my environment never produced,
and it says which one.

## 2. The mechanism

### What the test is sampling

`slow-trickle.stderr` holds 76 progress records. Speeds open at 10.8× and decay
monotonically; the first record below the default `buffering_speed` of 1.0 is **index 35**
(value 0.993). The 35 records before it are the "lead". The stand-in replays them one per
`stderr_interval`, which this test sets to **0.02 s**, so the lead is **0.70 s of wall
clock** starting when the stand-in process boots.

`input/manager.py:1166` takes the sub-threshold branch on the *first* record below the
threshold and `:1234` writes `state = buffering` to Redis, so the window in which a status snapshot can show `ffmpeg_speed >= 1.0` closes
0.72 s after the stand-in starts. The test's poll loop, `sample_while(…, drain=stream)`,
cannot begin until `tuned()` returns, and `tuned()` returns when the first body byte
reaches the client — wsgiref flushes headers on the first yielded chunk, and that chunk
comes from the generator's main loop, after `_wait_for_initialization()` releases.

**The margin is therefore `0.72 s − (time from spawn to the client's first byte)`, and
nothing in the test controls the subtrahend.**

### What sets the subtrahend: a 500 ms production timer

From a single DEBUG-level run (`scratchpad/debug1.log`, coverage arm, 2 CPU), with the
stand-in's pid 72995 spawned at `13.076`:

```
13.076  posix_spawn completed in 0.001s pid=72995
13.076  Stream generator started, channel_ready=False
13.077  Channel … connected but waiting for buffer to fill: 0/4 chunks
13.109  Added 4 chunks (1880 bytes each) to Redis … at index 4      <- threshold met, 33 ms in
13.118  FFmpeg stats … Speed: 10.8x                                  <- corpus record 0
…
13.586  Buffer threshold reached for channel …: 61/4 chunks          <- 510 ms in
13.588  Channel … state transition: connecting -> active
13.620  Channel … ready, starting normal streaming                   <- client served
13.630  FFmpeg stats … Speed: 1.16x
…                                                                    <- 13 records >= 1.0
13.894  FFmpeg stats … Speed: 0.993x
13.894  Buffering started for channel … - speed: 0.993x              <- window closes
```

The buffer reached its 4-chunk threshold at **33 ms**. The channel was promoted at
**510 ms**. The 477 ms in between is not work — it is
`apps/proxy/live_proxy/input/manager.py:1953`:

```python
# Schedule a retry to check buffer status again
timer = threading.Timer(0.5, self._check_buffer_and_set_state)
```

`_set_waiting_for_clients()` runs immediately after the spawn, when the Redis buffer index
is still 0, so it always takes that branch and always schedules one 500 ms retry
(`:2003` schedules further ones). The generator then picks the new state up on its own
`gevent.sleep(0.1)` poll (`output/ts/generator.py:238`) — and because both clocks start at
the same instant, 500 ms is exactly five poll periods, so the pickup is systematically
tight rather than uniformly distributed over 100 ms.

### The margin is quantised, not continuous

Client-served time can only take these values, and the margin follows:

| rung | condition | client served at | margin |
|------|-----------|------------------|--------|
| 0 | buffer already ≥ 4 chunks at the first check | ~spawn + 30 ms | **~+790 ms** |
| 1 | one 500 ms timer round | spawn + ~510–530 ms | **~+290 ms** |
| 2 | two 500 ms timer rounds | spawn + ~1010–1030 ms | **≈ −190 ms** |

**Every one of the 52 margin measurements I took landed on rung 1** (§ 3). Rung 2 produces
exactly the reported failure: zero snapshots with `ffmpeg_speed >= 1.0`, hence
`self.assertTrue(leading, "never observed the lead at all; …")`. Rung 2 is reached when the
Redis buffer index is still below 4 when the first timer fires 500 ms after the spawn —
i.e. when fewer than ~7.5 KB have travelled `FakeUpstream` → stand-in → relay → Redis in
half a second. `FakeUpstream` is a `ThreadingHTTPServer` **inside the test process**, so a
process whose GIL is saturated (249 tests' worth of relay daemon threads on a shared
4-vCPU runner) can starve the byte path while the stand-in's stderr pump, a separate
process paced by `time.sleep`, keeps its own clock. That is the shape of thing that puts
the run on rung 2.

**Verdict on the mechanism: the margin arithmetic and the rung structure are measured and
certain (high confidence). Which specific stall put the CI run on rung 2 is not
determined (low confidence, stated as a hypothesis above).** The experiment that settles
it: capture `DISPATCHARR_LOG_LEVEL=INFO` output from the coverage-label job and read
`Buffer threshold reached` against `posix_spawn completed` on a failing run — or, cheaper
and permanently useful, make the assertion message carry the snapshot count, the first
snapshot's `(ffmpeg_speed, state)` pair, and the time from `tuned()` to the first sample,
so the next occurrence distinguishes the rungs by itself. The current message cannot:
"never observed the lead at all; poll faster or pace the corpus slower" reads as a
sampling-density problem, and the density is not the problem.

### Why the margin is small, not the ordering wrong

This is a **tuning** problem, not a logic one. The invariant the test asserts —
speed ≥ threshold ⇒ state ≠ buffering — held in all 116 executions; no run showed the
detector arming during the lead. The production ordering is correct. What is wrong is that
the test's observation window is the *difference of two constants it does not own* (a
0.70 s corpus replay and a 0.5 s production timer), and that difference is ~290 ms.

### Row 5, which is the one that actually fails here

Same class of defect, opposite polarity. `test_a_buffering_threshold_change_does_not_reach_a_running_channel`
uses `sample_while(self, running, chunks=24, drain=stream)` as a pacing device — 24
ring-buffer reads, meant to span enough wall clock for four distinct progress records
(`normal.stderr` loops 11 records at 0.02 s = 220 ms per lap).

It does not span that, because the client is not reading live. `new_client_behind_seconds`
defaults to 5, the buffer holds far less than 5 s, so `_setup_streaming()` falls back to
the oldest available chunk — index 0 — while the head is 61–69 chunks ahead. Every failing
run logged it:

```
Time-based positioning: 5s behind -> index 0 (buffer head at 69)
```

24 reads of 1880 bytes come straight out of that backlog at HTTP-round-trip speed, so the
loop finishes fast and spans too few records. A *slower* machine spans more and passes,
which is exactly why this one is at 39% locally and unobserved in CI, and why row 4 is the
reverse.

### Row 5, measured directly

Each status poll is an HTTP request and is logged by `urllib3` at DEBUG, so the whole loop
is visible on the same clock as the stderr records it is sampling. Over 24 DEBUG-level
runs (`manage.py test -v2` on the class, under coverage, at three host-load levels):

| host load | 24-poll window | per poll | records in window | reader gap (median) | row 5 |
|-----------|----------------|----------|-------------------|---------------------|-------|
| idle | 51–57 ms | 2.2–2.5 ms | 2–3 | 21–22 ms | **3/8 fail** |
| 4 busy loops (29% of 14 cores) | 53–57 ms | 2.3–2.5 ms | 2–3 | 21–23 ms | **3/8 fail** |
| 24 busy loops (171% of cores) | 165–427 ms | 7.2–18.6 ms | 8–19 | 19–20 ms | **0/8 fail** |

The arithmetic is exact, and the logs confirm it run by run:

**`len(seen) == records_in_window + 1`** — the `+1` is the value already standing in Redis
when the first of the 24 polls ran. Verified against every failure:

| run | records parsed inside the window | asserted `seen` | standing value |
|-----|----------------------------------|-----------------|----------------|
| 2 | `6.8`, `5.27` | `[5.27, 6.8, 11.5]` | `11.5` |
| 4 | `3.66`, `3.42` | `[3.42, 3.66, 3.98]` | `3.98` |
| 6 | `6.8`, `5.27` | `[5.27, 6.8, 11.5]` | `11.5` |

So `len(seen) >= 4` requires the window to contain **three** record boundaries. The window
is ~52 ms and the record period is ~21 ms: **2.5 periods.** It therefore crosses three
boundaries or two depending on where it happens to start inside a 21 ms period — an
unbiased coin flip on sub-period phase, which is precisely the ~40–50% rate every observer
has reported. The margin is **one record period, ~21 ms**, and it is phase, not noise.

That also settles the mechanism question directly: **the stderr reader is not starved.**
Its median inter-record gap is 19–23 ms in every condition including host saturation —
flat, and equal to the corpus's own 0.02 s pacing. Records are not being dropped, batched
or delayed; the *observer* is simply too fast. The hypothesis that contention starves the
reader greenlet so fewer records are parsed is refuted by these 24 runs: under the load
that would cause it, the reader's cadence is unchanged (19–20 ms) and the test passes
8/8 because the window grew 3–8×.

Note what the load curve is and is not sensitive to. Four busy loops on a 14-core host
changed nothing measurable — the container was never starved. Only host *oversubscription*
moved the window. A container sitting at ~20% of one core is roughly 1.4% of this machine,
a third of the 4-hog condition that moved nothing, so a correlation between that and a
failure run is not supported by this data; four consecutive failures is an ordinary draw
from a ~40% coin (p ≈ 2.6%) over a session of many attempts.

**The corollary is uncomfortable and worth stating: this test gets *more* reliable the
worse the machine is.** It passes in CI because CI is slow.

## 3. Coverage instrumentation is not the variable

The issue's central hypothesis is that `COVERAGE_CORE=sysmon` shrinks the margin. Measured
directly, same container, same 2-CPU quota, row 4 run alone, margin =
`t("ready, starting normal streaming") − t("Buffering started for channel")` read off
INFO-level logs:

| arm | runs | min | median | max |
|-----|------|-----|--------|-----|
| coverage (arm G) | 20 | 262 ms | **312 ms** | 353 ms |
| plain (arm H) | 20 | 254 ms | **287 ms** | 353 ms |
| coverage, full label (arm F) | 12 | 261 ms | 289 ms | 341 ms |

The distributions overlap completely, and the coverage median is 25 ms *higher*, not
lower. Instrumentation slows the relay's Python, but the thing that dominates the
subtrahend is a wall-clock `threading.Timer(0.5, …)` that no tracer can slow, and the
corpus replay it is measured against runs in a separate, uninstrumented process. Measured
`init` (spawn → client served) across arms F/G/H: **507–532 ms in every single run**, the
500 ms constant plus jitter.

A second hypothesis, that CPU starvation shrinks the margin, is also **false**, and cleanly
so: at a 0.5-CPU quota (arm I) the margins were 245–447 ms, i.e. *wider* on average, because
starvation stretches the stand-in's `time.sleep(0.02)` pacing while leaving the relay's
0.5 s wall-clock timer alone.

The repo precedent quoted in the issue — 2a-3's parity row 8 widening a tolerance for
instrumentation slowdown — does not transfer here. That was a byte-count margin against
work the tracer genuinely slows. This is a wall-clock margin against a constant it does
not.

## 3a. Do rows 4 and 5 share a mechanism?

Three possibilities were put to me: two independent flakes, a mis-named issue, or one
cause with scheduling deciding which test loses. **None of the three is right, and the
most attractive one — a single shared cause — is the one the evidence rules out.**

They share a **design flaw**, not a mechanism:

> both observe a producer running on a corpus-fixed clock (the stderr reader writing
> `ffmpeg_speed` and `state` into one Redis hash) through an observer whose cadence is set
> by machine speed, and both report "the mechanism is absent" when what happened is "I did
> not sample at the right moment".

Below that, everything differs, including the sign:

| | row 4 (burn-off) | row 5 (threshold snapshot) |
|---|---|---|
| what bounds the window | a **production constant** — `threading.Timer(0.5, …)` deciding when the client is served — against the corpus's 0.70 s lead | the **observer's own speed** — 24 HTTP round trips draining ring-buffer backlog |
| window | ~290 ms | ~52 ms |
| fails when the observer is | **too late** | **too fast** |
| a slower machine | makes it **worse** | makes it **better** |
| where it is seen | CI (1/32); never locally in 116 runs | locally (28/72); never in CI in 32 runs |
| what the fix must do | stop depending on when the client was served | stop depending on how fast the client reads |

"Which test loses is a matter of scheduling" would be true if they shared a cause. They do
not: which one loses is decided by **the machine**, not by scheduling within a run, and it
is decided in opposite directions. That is why the two have never been seen to fail in the
same environment, and why #259 recording only one of them is not a mis-naming — the issue
was filed from a CI log, and row 4 is the one that fails in CI.

Consequences for the fix: **there is no single constant to change.** There is a single
*principle* that repairs both — assert the transition, do not sample for it — and it lands
as two unrelated edits (§ 4, § 4a).

### Is there a third exposed test in this file? No — and here is the criterion

The distinguishing property is whether the awaited condition **latches**:

| test | condition | latches? | exposed |
|------|-----------|----------|---------|
| row 28 (scientific notation) | `ffmpeg_speed is not None`, with `stderr_interval=0.0` | yes — whole corpus written at spawn | no |
| row 1 (sustained low speed) | `state == BUFFERING`, then `stream_id == alternate.id`, then `wait_until` on the event | yes — both persist once true | no |
| **row 4** | `state == BUFFERING`, but asserts over snapshots taken **before** it | **no** — the lead is transient | **yes** |
| **row 5** | none — a fixed count of reads, asserting over the snapshots | **no** — a fixed-width sample | **yes** |
| row 6 (max switches) | `stream_id == alternate.id`, then `wait_until` on the event | yes — persists once switched | no |

For a latching condition a missed sample costs one more loop iteration and nothing else.
Rows 4 and 5 are the only two that assert over *transient* content, and they are exactly
the two that flake. Anyone fixing these should apply the latching test to new ones rather
than re-deriving this.

## 4. Options for a fix

### Row 4 — recommended: pin the edge that is already recorded

`input/manager.py:1219-1226` emits `channel_buffering` exactly once, at the False→True
transition, carrying `speed=ffmpeg_speed`; `core/utils.py:872-896` stores `**details`
verbatim as JSON on the `SystemEvent` row. With `buffering_timeout` left at its default 15
and the corpus monotone below 1.0 after the crossing, exactly one such row exists per run,
and its `speed` **must** be `values[crossing]` (0.993) — if the detector had armed during
the lead it would be a lead value ≥ 1.0. That assertion is edge-triggered by construction:
it cannot be missed by a poll, it does not depend on when the client was served, and it
pins row 4's actual claim ("the lead must burn off before the detector arms") more
directly than the sampled invariant does. Row 1 already uses the same
`wait_until(... event exists ...)` shape for `channel_failover`, for the same ordering
reason, so this is the file's existing idiom and not a new mechanism.

Cost: it drops one thing the sampled version also proved — that the *status surface* never
showed a high speed paired with `state=buffering`. Keep the sampled loop and its
`for info in leading: assertNotEqual(...)` invariant; what should go is
`assertTrue(leading, …)`, the vacuity guard, because the event assertion supersedes it and
is the only part that was ever racy.

### Row 4 — alternative: pace the corpus slower

`stderr_interval=0.05` makes the lead 1.75 s and the margin ~1.2 s, clearing rung 2
(−190 ms → +310 ms) with room. Costs about 1 s of test time. This is the cheap fix, and I
am recommending against it *alone*: it buys a bigger number against the same unowned
constant, and the next person to change `initial_behind_chunks`, the 0.5 s timer or the
corpus silently re-opens the race. Combined with the event assertion it is cheap insurance
and I would take both — but the event assertion is what makes the test correct.

What should **not** be done: widening the `leading` tolerance, or deleting the
`assertTrue(leading, …)` guard without replacing what it protects. The guard exists because
without it the loop below is vacuous, and a vacuously-passing row 4 is worse than a flaky
one.

If the margin arithmetic is to be relied on at all, the test should also *state* it — the
docstring is thorough about the corpus and silent about the 500 ms timer that halves its
window.

## 4a. Row 5 — and whether the `4` is load-bearing

### What the guard proves at each value

This was asked specifically, and the exact relation from § 2 answers it without guesswork.
`len(seen) = records_in_window + 1`, where the `+1` is the value standing in Redis before
the loop began. The guard's job is to prove records were **still being parsed after the
settings change**, so that "the state never became BUFFERING" is not vacuously true
because parsing had stopped:

| threshold | records it proves were parsed after the loop started | verdict |
|-----------|------------------------------------------------------|---------|
| `>= 1` | **zero** — the one value may be the pre-existing standing value | **vacuous**; proves nothing at all |
| `>= 2` | one | **the genuine floor** — the minimum that proves progress |
| `>= 3` | two | margin |
| `>= 4` (today) | three | margin |

So the honest answer is narrower than "4 is load-bearing" and narrower than "lower it to
3": **the guard stops proving anything at 1, and everything from 2 up is the same kind of
proof with more margin.** Lowering 4 to 3 would not make the test vacuous — that is the one
correction I would make to the framing I was given — and it would roughly halve the
failure rate. But it does not *fix* anything: the window holds 2.5 record periods, the
outcome is decided by sub-period phase, and the margin after the change is still one
record period. On a machine 40% faster, `>= 3` fails exactly as `>= 4` does now. **Changing
the constant moves the coin, it does not put it away.**

There is a second reason not to treat this as a constant-tuning problem, and it is the more
important one. The *property* the test exists to assert —
`for info in after: assertNotEqual(info.get("state"), BUFFERING)` — is checked over the
**same 24 snapshots**, i.e. a ~52 ms window spanning 2.5 corpus records. The guard firing
is the visible symptom; the quiet problem is that on a *passing* run this test verifies its
subject over about three progress records. **Widening the window fixes the guard and the
property together; lowering the constant fixes neither and hides both.**

### Replace the broken pacing device

`chunks=24` was chosen as a proxy for elapsed time and is not one, because the client
starts 61-69 chunks behind live (§ 2). Options, best first:

1. **Make the stopping condition the observation.** Extend `sample_while` with an `until=`
   predicate over accumulated snapshots — "N distinct `ffmpeg_speed` values seen since the
   change" — bounded by the existing timeout. The test then cannot fail for having looked
   too fast; it fails only if records genuinely stopped being parsed, which is exactly what
   the guard is for, and the timeout keeps a real stall failing. This is row 5's analogue
   of row 4's recommendation: assert the thing, do not sample for it. It also widens the
   window for the property, because the loop now runs until the producer has demonstrably
   advanced.
2. **`set_proxy_settings(self, new_client_behind_seconds=0)`** so the client reads at live
   and the drain is genuinely paced by the upstream (24 chunks x 1880 B at 250 KB/s
   ~ 180 ms ~ 9 records). Better than today, and it removes the backlog coupling — but it
   is still a machine-speed-dependent margin, which is the shape of bug being fixed. Good
   as a companion to 1, not a substitute for it.
3. Raise `chunks`, or lower the `4`. Both move the coin. See above.

## 4b. Both — make the failure legible

Whatever is chosen, the two assertion messages should name what was actually observed
(snapshot count, elapsed wall clock of the sampling loop, the first and last
`(speed, state)` pair). Both messages today describe a *remedy* ("poll faster or pace the
corpus slower", "too few distinct speeds") rather than the evidence, and in row 4's case
the remedy it suggests is the wrong lever.

## 5. Exposure of `migration/phase2b-output-profile-and-user`

**Exposed, on every push.** `backend-tests.yml:171-180` fixes the `coverage-label` matrix
at the three Gate-2 labels — `apps.proxy.tests`, `apps.proxy.live_proxy.tests`,
`apps.channels.tests` — and gates the job only on `needs.plan.outputs.has_tests == 'true'`.
There is no path filter on the coverage matrix: any non-docs diff runs all three labels.
That PR touches `apps/proxy/live_proxy/views.py`, `authorize_views.py`, `internal_auth.py`
and `client_manager.py`, so it additionally selects `apps.proxy.live_proxy.tests` for the
plain `test` matrix through `_PATH_ALIASES`. `coverage-label` feeds `coverage-gate`, which
feeds `Backend result`, which the Main ruleset requires.

Likelihood per push: **~3%**, the CI-observed rate (1 failure in 32 coverage-label jobs
since the file landed). That is a wide interval on one event — a 95% binomial interval runs
roughly 0.1%–16% — so treat 3% as an order of magnitude, not a figure. The plain label job
adds no observed risk (0/32). Row 5 has never been observed to fail in CI and, on the
evidence in § 2, is a fast-machine failure that CI's slower runners suppress; it is a
local-run and commit-hook hazard, not a CI one.

Practical read for the PR in flight: one failure in thirty-odd pushes, recoverable by
re-running the job (the #259 occurrence passed on re-run of the identical SHA), and
presenting as a *coverage* failure, which is the part that costs a cycle. The mitigation
with the best ratio right now is not a code change at all: when
`Coverage apps.proxy.live_proxy.tests` fails, grep the log for
`never observed the lead at all` or `too few distinct speeds` before investigating
coverage.

## 5a. A flaky test currently destroys a whole coverage round

Reported by a third observer and confirmed from source, independent of the flake itself.

`scripts/coverage_live_path_isolated.sh` opens with `set -euo pipefail` (line 12) and then
drives the three labels in a bare loop:

```bash
declare -a PAIRS=(
  "proxy:apps.proxy.tests"
  "liveproxy:apps.proxy.live_proxy.tests"
  "channels:apps.channels.tests"
)
for pair in "${PAIRS[@]}"; do
  ...
  docker exec "$c" bash -lc "... bash scripts/coverage_live_path.sh --label ${label}"
  docker cp "${c}:/tmp/rd" "${OUT}/${suffix}"
done
```

`--label` ends `run_label "$2"; exit $?` (`coverage_live_path.sh:552`), so it exits with the
Django runner's status. Under `set -e` that aborts the loop. `liveproxy` is the **second**
of three, so a row-5 failure means `channels` never runs, the `docker cp` never happens, and
the combine/report/gate at the bottom is never reached — **the round produces no
measurement at all** rather than a partial one or a named failure.

Note the contrast with the in-container script, which handles this properly: its no-argument
path collects failures into a `failed=()` array, runs every label anyway, and then prints
"THE FIGURES BELOW ARE INVALID" before the numbers. The isolated wrapper has none of that
and inherits `set -e` instead. The fix is the same shape — collect the failing labels, run
the rest, report which died, exit non-zero — and it is worth doing regardless of what
happens to these two tests, because the wrapper's current behaviour turns any future
one-label failure into a silently lost round.

Measured coverage impact of the row-5 failure *itself*, once the round completes: **none**.
The four clean rounds' figures sit inside the spread of the failing rounds — consistent with
the test aborting after the channel is already tuned and its lines already executed.

## 6. What I did not establish

- **Which stall put the CI run on rung 2** (row 4). Named as a hypothesis in § 2 (GIL
  saturation starving the in-process `FakeUpstream` while the stand-in's stderr clock runs
  free), not demonstrated. The experiment that settles it is in § 2. Note the host-load
  measurements in § 2 do *not* test it: they starve the whole machine uniformly, whereas
  this hypothesis needs the test process's GIL saturated while the stand-in, a separate
  process, keeps its clock.
- **Whether row 4 can fail without instrumentation.** 0/32 in CI's plain arm and 0/30 in
  local plain executions is consistent with both "coverage matters a little" and "the rung
  is rare and the arms are identical". § 3 argues from the margin measurement that the arms
  are identical; the event counts alone cannot separate them.
- **Row 5's CI rate.** Zero observed in 64 CI label jobs against 28/72 locally. § 2 now
  gives a measured explanation for the gap (CI's slower round trips widen the window), but
  I have taken no CI-side measurement of the window itself to confirm it there.
- **Row 5's rate as a function of round-trip latency.** I have three load points and they
  are consistent, but the transition between "fails half the time" and "never fails" was not
  bracketed: nothing was measured between a 57 ms window and a 165 ms one. The prediction is
  that the rate falls to zero once the window reliably exceeds ~63 ms (three record
  periods); that is untested.