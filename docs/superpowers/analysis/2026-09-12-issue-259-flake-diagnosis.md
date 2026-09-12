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
   failed **28 of 72**, a 39% rate, in both the coverage and the plain arm. Row 5 has
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

Row 4 ran in every one of those runs (it sorts last in the class, and a row-5 failure does
not stop it): **116 executions, 0 failures.** Row 5 ran in arms B–F: **72 executions, 28
failures = 39%**, 25/62 (40%) under coverage and 3/10 under plain.

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
116 local executions across five environments, including a 28× CPU spread, produced none.
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
loop finishes in roughly 40–60 ms and spans **3** records where the assertion needs 4. It
misses by about one record — ~20 ms. A *slower* machine spans more records and passes,
which is exactly why this one is at 39% locally and unobserved in CI, and why row 4 is the
reverse.

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

### Row 5 — replace the broken pacing device

`chunks=24` was chosen as a proxy for elapsed time and is not one, because the client
starts 61–69 chunks behind live. Options, best first:

1. **Make the stopping condition the observation**: extend `sample_while` with an `until=`
   predicate over accumulated snapshots (e.g. "4 distinct `ffmpeg_speed` values seen since
   the change"), bounded by the existing timeout. The test then cannot fail for having
   looked too fast; it fails only if records genuinely stopped being parsed, which is what
   it is there to prove. This is the row-5 analogue of the row-4 recommendation: assert
   the thing, do not sample for it.
2. **`set_proxy_settings(self, new_client_behind_seconds=0)`** so the client reads at live
   and the drain is genuinely paced by the upstream. Better than today (24 chunks × 1880 B
   at 250 KB/s ≈ 180 ms ≈ 9 records) but still a machine-speed-dependent margin, which is
   the shape of bug being fixed.
3. Raise `chunks` — same objection as widening row 4's tolerance, and it scales with the
   backlog rather than with time.

### Both — make the failure legible

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

## 6. What I did not establish

- **Which stall put the CI run on rung 2.** Named as a hypothesis in § 2 (GIL saturation
  starving the in-process `FakeUpstream` while the stand-in's stderr clock runs free), not
  demonstrated. The experiment that settles it is in § 2.
- **Whether row 4 can fail without instrumentation.** 0/32 in CI's plain arm and 0/30 in
  local plain executions is consistent with both "coverage matters a little" and "the rung
  is rare and the arms are identical". § 3 argues from the margin measurement that the arms
  are identical; the event counts alone cannot separate them.
- **Row 5's CI rate.** Zero observed in 64 CI label jobs, 39% locally. I have an
  explanation for the gap (§ 2) but no CI-side measurement of it.
- **The other three tests in the class.** `test_a_scientific_notation_speed_is_under_reported_as_its_mantissa`
  and `test_a_sustained_speed_below_the_threshold_fails_the_channel_over` also drive
  `sample_while`, and `test_a_buffering_failover_ignores_max_stream_switches` was not
  examined at all. None failed in 72 class executions; that is weak evidence of safety, not
  an audit.
