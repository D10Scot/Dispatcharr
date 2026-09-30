# Plan: fix #553, an interlaced source's HLS output rate comes from its `avg_frame_rate`

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The whole change is byte-exact: Appendix A is the Go code and its test, Appendix B the spec amendment, Appendix C the defect-ledger entry, each a `git diff` against the seed. The implementer applies them, does not rewrite them, and fills only the `⟨…⟩` slots, each of which names what fills it.

**Goal.** For an interlaced source, the HLS re-encode derives the output rate `R` from the probe's `avg_frame_rate` × 2, capped at 60, and falls back to `r_frame_rate` only when `avg_frame_rate` is missing or `0/0`. Progressive sources, and sources whose field order is unknown (R28), are unchanged. A 1080i25 PAFF source that ffprobe reports as `r_frame_rate` 50/1 and `avg_frame_rate` 25/1 then comes out at 50p with G = 100, as D8 says, instead of 60p with G = 120. Owner ruling R94; issue #553.

**Seed.** `a1e9da65` (`a1e9da653ed3f036ca7aa5d0033518d5fca22a48`, `main`, "docs(phase4): close out 4a"). Every `file:line` below was re-grepped at the seed with `git show "a1e9da65:<path>"`. **The implementer re-greps them at the PR's base** (Task 1) and stops if anything named here has changed shape rather than just moved lines.

**Branch.** `fix/553-interlaced-output-rate`, off `origin/main` at the seed. Under ruling R94 **this plan is the branch's first commit and ships in the fix PR itself.** There is no separate plan PR: the implementation commits go on top of this one, on the same branch.

**Authority**, in order of precedence:

1. **Owner ruling R94** (binding). For an interlaced source the output rate derives from `avg_frame_rate` × 2 (cap 60), falling back to `r_frame_rate` only when `avg_frame_rate` is missing or `0/0`. Progressive sources are unchanged. The fix is pinned with a new probe fixture (`r_frame_rate` 50/1, `avg_frame_rate` 25/1 → output 50/1, with the GOP to match), and a 29.97i source (30000/1001) must still give 60000/1001. The plan ships as the first commit of the fix PR. Also R21, R27, R52, R80 and R93 (the Go ratchet: a raise needs a per-file listing, and O is counted by the block start-line rule over every census round) and R28 (unknown field order is progressive).
2. **The Phase 4 spec**, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` at the seed:
   - D8 (`:217`): the source is deinterlaced "50i → 50p", and the output's frame rate is fixed at the first generation.
   - § Encoder argv's `R` bullet (`:556-558`): "`R` is the field rate for an interlaced source (1080i at 25 frames or 50 fields per second becomes 50p), or the frame rate for a progressive one, capped at 60. `G` = round(2 × R)".
   - § Open questions Q7 (`:1868`): whether ffprobe's `field_order` is reliable on the household's channels, and, if it is not, `bwdif` on every source with "`R` … taken from the field rate".
   - Apple 1.14-1.15 (Appendix A of the spec): 30i becomes 60p.
3. CLAUDE.md: the Go hooks, stdlib-only, credlint, zero lint findings under three GOOS, `go test -race`, and the Go coverage ratchet as amended by R21/R27 (§ Testing). Also AGENTS.md's test rules (break-checks, and a test changes only when the behaviour it pins changes) and `docs/agents/metrics.md` (the ledger contract).

**Issues.** The fix PR closes #553 and carries `Closes #553.` in its description (§ PR description draft). **Only there:** this plan's own commit message, and every commit message on the branch, says `Refs #553` and never a closing keyword. GitHub reads commit messages too, and a plan commit that carried the keyword would close the issue on merge whatever else landed.

## Global constraints

1. **Standard library only** (`scripts/check_go_stdlib_only.sh relay`). The fix adds no import to production code; the test adds `fmt`, which is stdlib.
2. **Zero lint findings under three GOOS** (`golangci-lint run ./...` natively, with `GOOS=linux` and with `GOOS=darwin`), `go vet ./...` and `go test -race ./...` green, and credlint clean (`go run ./internal/credlint ./...`). The fix adds no log or format call.
3. **The test-modification rule.** No existing test changes. The existing tests that construct a `Video` literal with `FrameRate` set (`relay/hls/argv_test.go:10-12`, `automatic_test.go`, `automatic_pipeline_test.go:476`) bypass `ParseProbe`, so their oracles do not move. The existing tests that go through `ParseProbe`, listed below, keep their oracles and are verified unchanged by Task 4:
   - `TestParseProbeReadsTheStreams`: interlaced, 25/1 and 25/1, so both orders read 25/1.
   - `TestParseRational`'s fallback case: no `field_order` (unknown), `r_frame_rate` 0/0 and `avg_frame_rate` 50/1, which still reads 50/1.
   - The progressive and HEVC probe fixtures.
4. **Go unit tests pin the fix; no E2E and no fixture change** (§ The design, Why no E2E).
5. **No floor raise.** `scripts/coverage_relay_go.floor` is not edited (§ Coverage).
6. **Deterministic tests.** The new test is table-driven over literal ffprobe JSON. It spawns nothing and does not wait.

## Overlap with sibling work

No open plan touches `relay/hls/probe.go` or `probe_test.go` at the seed. `git log a1e9da65 -3 -- relay/hls/probe.go` ends at 4a-1d (#547). One piece of adjacent work could be affected:

- **The owner's hardware runbook for Q1/Q7** (being drafted by another agent; #553 was found while drafting it). The issue proposes a check: "if any interlaced channel logs `frame_rate=60/1`, this is live". After this fix that check can no longer fire, because the `HLS output decided` line (`relay/hls/pipeline.go:530-531`) logs `R`, and `R` is now 50/1 for a PAFF source. The runbook should instead record the probe's own `r_frame_rate` and `avg_frame_rate` per channel, as Q7 already asks. The orchestrator relays this to the runbook's author (open question 3).

## The defect, at the seed

- `relay/hls/probe.go:290-293` reads `r_frame_rate` and falls back to `avg_frame_rate` for **every** video stream. The field order is parsed after that, at `:298-300`, from the same JSON object.
- `relay/hls/argv.go:227-239` (`outputRate`) doubles `Video.FrameRate` when `Field == FieldInterlaced` and caps the result at 60. `Decide` (`:176-184`) sets `o.FrameRate = outputRate(*p.Video)` and `o.GOP = round(2R)`.
- For an H.264 PAFF source, ffprobe can report `r_frame_rate` as the **field** rate (50/1 for 1080i25; 60000/1001 for 1080i29.97). `R` then comes out 100 → capped 60/1, G = 120 for 1080i25, and 120000/1001 → capped 60/1 (not 60000/1001), G = 120 for 1080i29.97. The `fps=60/1` filter (`argv.go:504-505`) duplicates frames, and the multivariant declares `FRAME-RATE=60.000` (`playlist.go:43-45`).
- **Measured red at the seed.** The Appendix A test run against the unfixed `probe.go` fails on exactly its two PAFF rows, with every other row green:
  - `1080i25 PAFF, r_frame_rate the field rate: probed 50/1, R=60/1 G=120; want probed 25/1, R=50/1 G=100`
  - `1080i29.97 PAFF, r_frame_rate the field rate: probed 60000/1001, R=60/1 G=120; want probed 30000/1001, R=60000/1001 G=120`
- **Unmeasured:** whether ffprobe 9.0 really reports `r_frame_rate` 50/1 for a real PAFF broadcast. No PAFF sample is available, and neither libx264 nor ffmpeg's `mpeg2video` encoder writes field pictures, so none can be generated either. R94 fixes the behaviour for that case whichever way the measurement comes out; the owner's Q7 run is where it gets measured.

## The design

**The fix goes in `probe.go` only.** `ParseProbe` picks the rate with a new helper, `frameRate(r, avg string, field FieldOrder) Rational`. The helper reads `avg_frame_rate` first when the field order is interlaced, and `r_frame_rate` first otherwise, falling back to the other value when the first is missing, `0/0` or unreadable (the same `parseRational` rejection as today). `ParseProbe` calls it after the field order is parsed. `Video.FrameRate` then always counts whole frames, and `outputRate` in `argv.go` is left alone: it still doubles an interlaced frame rate into the field rate and caps at 60.

Why here and not in `argv.go`:

- **The decision needs two facts, and only `ParseProbe` holds both.** Both the field order and the two raw rates are in the same ffprobe stream object at `probe.go:284-300`. `outputRate` receives a `Video` that already carries one chosen rate. To fix it there, `Video` would need both raw rates, and all of the following would change: the struct; the 16 test lines that build a `Video` or set its `FrameRate` (`grep -rn 'Video{\|FrameRate = \|FrameRate:' relay --include='*_test.go'`); the probe log line (`pipeline.go:611`); and automatic mode's two `FrameRate` comparisons (`automatic.go:107`, `:178`).
- **It makes `Video.FrameRate` mean one thing.** At the seed it is a frame rate for most sources and a field rate for a PAFF source. After the fix it is always frames per second, which is also what `outputRate`'s comment already assumes ("1080i at 25 frames (50 fields) a second becomes 50p").
- **It does not reach automatic mode.** Automatic mode reads `Video.FrameRate` at `automatic.go:107` (copy eligibility), `:149` (a copied run's rate) and `:178` (a later copy's match). Every one of these sits after `copyEligible`'s `v.Field == FieldInterlaced` refusal at `automatic.go:85-87`, so an interlaced source's rate is never read there. A progressive or unknown-order source reads exactly what it read before.
- **One visible side effect.** The probe log line (`pipeline.go:611`, `HLS generation probed … video=…`) now prints a PAFF source's frame rate (25/1) where it used to print the field rate (50/1). That line is informational: nothing parses it, and no test asserts its `video=` field: `grep -rn "HLS generation probed" relay` finds the call at `pipeline.go:613` and two tests (`pipeline_test.go:822`, `:851`), which only wait for the line to appear.

**`argv.go` is not edited.** Its `Output.FrameRate` comment (`:111-112`, "the field rate of an interlaced source, the frame rate of a progressive one, capped at 60") and `outputRate`'s comment (`:223-226`) are both still true.

**What R94 means at the edges**, each one a row of the new test:

| Source | `field_order` | `r_frame_rate` | `avg_frame_rate` | probed rate | `R` | G |
|---|---|---|---|---|---|---|
| 1080i25 PAFF (the issue) | tt | 50/1 | 25/1 | 25/1 | 50/1 | 100 |
| 1080i29.97 PAFF | bb | 60000/1001 | 30000/1001 | 30000/1001 | 60000/1001 | 120 |
| 1080i25, as the 4a-0 fixtures probe | tt | 25/1 | 25/1 | 25/1 | 50/1 | 100 |
| 1080i29.97, `r_frame_rate` the frame rate (R94's second pin) | tt | 30000/1001 | 30000/1001 | 30000/1001 | 60000/1001 | 120 |
| interlaced, `avg_frame_rate` 0/0 | tt | 30000/1001 | 0/0 | 30000/1001 | 60000/1001 | 120 |
| interlaced, `avg_frame_rate` absent | tt | 30000/1001 | — | 30000/1001 | 60000/1001 | 120 |
| progressive, unchanged | progressive | 50/1 | 25/1 | 50/1 | 50/1 | 100 |
| unknown field order, unchanged (R28) | — | 50/1 | 25/1 | 50/1 | 50/1 | 100 |

The two fallback rows use 29.97 rather than 25, and that choice is load-bearing. `outputRate` turns a rate it cannot read into 25 (`argv.go:229-231`), so an interlaced row that fell back to 25/1 would still show `R` 50/1 with the fallback deleted: the default would supply the expected answer. Measured: under break-check BC3 a 25/1 fallback row stays green on `R`. The 29.97 rows redden on both the probed rate and `R`.

**Measured on the 4a-0 fixtures, at the seed, with ffprobe 9.0.1** (the version `docker/DispatcharrBase` ships). This check confirms that the new read order changes nothing for the fixtures. Both interlaced fixtures (`h264-1080i-aac-ac3`, `mpeg2-576i-mp2`) were built with `e2e-upstream/scripts/make-asset.sh` and probed with the relay's own argv. The probes covered both `QuickProbe` (3 MB / 3 s) and `FullProbe` (5 MB / 8 s), fed from byte offsets 0, 1 MB, 3 MB, 5 MB and 9 MB. All 20 probes reported `field_order=tt`, `r_frame_rate=25/1` and `avg_frame_rate=25/1`. So the fixtures' `R` stays 50/1. With the fix applied, `go test -race ./hls` passes on the host (`relay/hls` 123.9 s), and so do all 18 `TestReal*` tests, which run real ffprobe on those fixtures. Those tests exercise the new interlaced branch on real ffprobe output.

**Why no E2E and no fixture change.** An E2E could only show the new behaviour on a source whose `r_frame_rate` differs from its `avg_frame_rate`, which needs a PAFF stream. Neither encoder in the fixture toolchain writes field pictures (libx264 codes interlaced video as MBAFF only; `mpeg2video` writes frame pictures), so `make-asset.sh` cannot produce one. A captured broadcast would bring a copyrighted and unreviewed asset into the repo. The fixtures probe `r_frame_rate == avg_frame_rate` (measured above), so every existing HLS E2E keeps its current behaviour and needs no edit. The Go test pins the whole decision (`ParseProbe` → `Decide` → the argv's `fps=` and `-g`), from ffprobe's JSON through to the encoder's arguments. The remaining untested step is ffmpeg honouring `fps=50/1`, and parity row 31's real-ffmpeg tests already pin that for 50/1.

`make-asset.sh`'s shape check (`:48`, `:155`, `:174`) asserts `r_frame_rate` only, not `avg_frame_rate`. Adding `avg_frame_rate` to its `-show_entries` would change the expected line of every stream of every variant, audio streams included (`avg_frame_rate=0/0`), and would rebuild the e2e-upstream image. That is scope this fix does not need; open question 4 records it.

**No parity-matrix row.** No row pins D8's rate choice today (`grep -n "argv.go:2[23]\|outputRate\|Decide" docs/relay-parity-matrix.md` is empty at the seed). Adding one for a defect fix would widen scope; open question 2.

**No CLAUDE.md edit.** CLAUDE.md mentions neither `r_frame_rate` nor the output rate.

## The spec

The fix makes the code do what the spec already says: § Encoder argv's `R` bullet (`:556-558`) says `R` is "the field rate for an interlaced source". It never says how the field rate is read, and the code read it wrongly. **D8 is not amended.** Appendix B adds one clarifying passage to that bullet, citing R94 and #553, and a Changelog entry. Both ride in this PR, because the plan is part of the fix PR.

**Q7 is not decided here, and the changelog entry says so.** If Q7 finds `field_order` unreliable, its contingency ("`bwdif` … applied to every source, and `R` is taken from the field rate") would need a rule for a source whose field order cannot be trusted. Doubling `avg_frame_rate` for every source would make a 50p progressive channel 100 → 60. That rule belongs to Q7's own amendment, if it ever comes, and not to this fix.

## Tasks

**Task 1: re-anchor.**
- At the PR's base, `git show "${BASE}:relay/hls/probe.go"` must still read `rate, ok := parseRational(s.RFrameRate)` just before the `v := &Video{` literal, with the `FieldOrder` block after it. `argv.go`'s `outputRate` must be unchanged.
- `git apply --check` Appendices A, B and C against the base. If `main` has moved, re-anchor the hunks' context only, and record what moved in the PR body.
- Stop and report if the shape changed.

**Task 2: the failing test first.** Apply only Appendix A's `probe_test.go` hunks. Run:

```bash
cd relay && go test -count=1 -race -run TestAnInterlacedSourcesRateIsItsAverageFrameRate ./hls
```

It must fail on exactly the two PAFF rows, with the two lines quoted in § The defect, and on no other row. Record the output in the PR body.

**Task 3: the fix.** Apply Appendix A's `probe.go` hunks. The same command passes.

**Task 4: the gates, on the host.** From `relay/`:
- `gofmt -l .` must print nothing.
- Run `go build ./...`, `go vet ./...` and `go test -count=1 -race ./...`. The `TestReal*` tests must **run**, not skip: ffmpeg and ffprobe must be on `PATH`. A skip line (`is not on PATH; the packager's real-ffmpeg tests did NOT run`) means those tests did not run, and the report must say so.
- Run `golangci-lint run ./...` natively, with `GOOS=linux` and with `GOOS=darwin`.
- Run `go run ./internal/credlint ./...`.
- From the repo root, run `scripts/check_go_stdlib_only.sh relay`.

The `PostToolUse` Go hook runs most of these on every `*.go` edit, but a hook run is not a substitute for this list.

**Task 5: break-checks.** Run each one in § Break-checks against the fixed tree, and revert each before the next.

**Task 6: the spec and the ledger.**
- Apply Appendix B.
- Apply Appendix C once the PR number is known (Task 8 opens the PR): fill `⟨PR⟩` with that number and `⟨merge date⟩` with the day the PR is expected to merge. That day is normally the day the census completes. If the merge slips to a later day, the merge gate corrects it.
- Run `python -m metrics.build --validate-only` and confirm it prints `ok: … 47 defects`.

**Task 7: commit.** Stage and commit in separate Bash calls, with each message written to a file and committed with `-F`. Every message says `Refs #553` and never a closing keyword: no commit subject or body may contain "fix #553", "fixes #553", "closes #553" or "resolves #553" in any case or form. Only the PR body carries `Closes #553.` The commits in order: the test, the fix, the spec, the ledger. Or fewer commits, if the test and fix land together **after** Task 2's red run has been recorded.

**Task 8: the PR.** Open a draft: `gh pr create --repo D10Scot/Dispatcharr --draft --base main --head fix/553-interlaced-output-rate --title "fix(relay): an interlaced source's HLS output rate comes from its avg_frame_rate (#553)" --body-file <file>`, with the body from § PR description draft. Then run `gh pr view <n> --repo D10Scot/Dispatcharr --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'`. It must print `[553]` and nothing else.

**Task 9: the Go coverage census** (§ Coverage). Its result goes in the PR body.

## Tests added

- `relay/hls/probe_test.go::TestAnInterlacedSourcesRateIsItsAverageFrameRate`: the eight rows of § The design's table. Each row builds ffprobe JSON (`field_order` and `avg_frame_rate` omitted when the row says absent) and runs it through `ParseProbe` and `Decide`. It asserts three things: the probed `Video.FrameRate`; `Output.FrameRate` and `GOP`; and that the software argv (`PlanGeneration(…, EngineSoftware)`, `Argv(…, DefaultDevice)`) carries `fps=<R>,` and ` -g <G> `. Red at the seed on rows 1-2 only (§ The defect).

## Tests changed

None (Global constraint 3).

## Break-checks

Apply each wrong edit alone to the fixed tree (BC1-BC3 edit `relay/hls/probe.go`, BC4 edits `relay/hls/argv.go`), run `cd relay && go test -count=1 -run TestAnInterlacedSourcesRateIsItsAverageFrameRate ./hls`, compare the red lines with the ones below, record them in the PR body, and revert. All four were run on a prototype of this exact diff at the seed; the lines are quoted from those runs.

- **BC1: revert the fix** (read `r_frame_rate` first for every source, as at the seed). Rows 1-2 redden, naming the field rate as the probed rate and `R` capped at 60:
  - `1080i25 PAFF, r_frame_rate the field rate: probed 50/1, R=60/1 G=120; want probed 25/1, R=50/1 G=100`
  - `1080i29.97 PAFF, r_frame_rate the field rate: probed 60000/1001, R=60/1 G=120; want probed 30000/1001, R=60000/1001 G=120`
- **BC2: `avg_frame_rate` first for every source** (in `frameRate`, `if field == FieldInterlaced` → `if true`). The two unchanged-source rows redden, which shows that progressive and unknown field orders keep `r_frame_rate` first:
  - `progressive keeps r_frame_rate first: probed 25/1, R=25/1 G=50; want probed 50/1, R=50/1 G=100`
  - `an unknown field order keeps r_frame_rate first: probed 25/1, R=25/1 G=50; want probed 50/1, R=50/1 G=100`
- **BC3: no fallback for an interlaced source** (in `frameRate`, `if !ok {` → `if !ok && field != FieldInterlaced {`). The two fallback rows redden, and `R` shows `outputRate`'s default of 25 doubled:
  - `interlaced, avg_frame_rate 0/0: probed 0/0, R=50/1 G=100; want probed 30000/1001, R=60000/1001 G=120`
  - `interlaced, avg_frame_rate absent: probed 0/0, R=50/1 G=100; want probed 30000/1001, R=60000/1001 G=120`
- **BC4: the argv ignores `R`** (in `argv.go:504-505`, pass `Rational{60, 1}` to the `fps=%s` format in place of `o.FrameRate`). Every row whose `R` is not 60 reddens on the argv assertion, for example: `1080i25 PAFF, r_frame_rate the field rate: the argv does not carry fps=50/1 and -g 100: "…"`. This pins that the new test reaches the encoder's arguments, not just `Output`.

## Coverage (R21, R52, R80, R93)

**Expected: no raise.** The PR's own new or changed non-test statements under `relay/` are all in `relay/hls/probe.go`:
- the `v.FrameRate = frameRate(…)` assignment and the changed `Video` literal;
- `frameRate`'s body (the `first, fallback` assignment, the `if` and its swap, the `parseRational` call, the `if !ok` and its fallback, and the `return`).

The new test covers every one of them: the interlaced branch on rows 1-6, the non-interlaced branch on rows 7-8, and the fallback on rows 5-6. Existing tests also reach them (`TestParseRational`'s fallback case, and every `ParseProbe` caller). A prototype run with `-covermode=atomic` found no uncovered block starting on a changed line. So O = 0, and coverage on the additions is 100%, above the 85% bar. The floor's `missing` (705 at the seed) does not move, and `scripts/coverage_relay_go.floor` is **not edited**.

**The census is still run**, because the PR changes product Go code and R21/D20's additions measure is defined by the census. The procedure:

1. Dispatch `go-tests.yml` on the branch (`gh workflow run go-tests.yml --repo D10Scot/Dispatcharr --ref fix/553-interlaced-output-rate`). Run it at least twelve times, one run at a time (the workflow's concurrency group cancels an in-progress run on the same ref). Continue until the maximum has held for six consecutive rounds. A round counts only when its `build` job succeeded.
2. Record every round's `this run missing=` from the `Coverage gate` job's log, in order, with its run id.
3. From each round's `relay-go-coverage` artifact, list the uncovered blocks whose start line falls in an added range of `git diff -U0 "${BASE}" "${HEAD}" -- relay ':!*_test.go' ':!relay/internal'` (R93's start-line rule). The expected listing is `relay/hls/probe.go 0` in every round.
4. **Every round must be ≤ 705.** A round above 705 cannot be this PR's own code if step 3 lists nothing. In that case stop the census, attribute the difference per block against the base's census (`awk 'NR>1 && $3==0 {print $1}'` on both profiles, then diff the sets), and report it. A pre-existing flap above the floor is a re-measurement PR of its own, and **never a raise here**.
5. The census takes about twelve sequential CI runs, several hours in total. Per the programme's practice, run the loop detached, and have the orchestrator watch a stopfile rather than a subagent holding a multi-hour wait.

The floor file still carries `raise_from=691` / `raise_listed=14` from 4a-3. `scripts/check_floor_raise.sh` reads them only when `missing` rises, and then it would refuse them as stale (`raise_from` ≠ 705), so they are inert. This PR leaves them alone (open question 1).

**Python Gate 2** is untouched: no Python changes.

## Gates

- Go: Task 4, § Break-checks, § Coverage.
- Metrics: `python -m metrics.build --validate-only`.
- CI: every required check green on the PR's head, including `Go result`, `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result`, and the review bot once the PR is marked ready (`pr-merge-gate`).
- No hardware gate. The owner's Q7 run is where a real PAFF channel's `r_frame_rate`/`avg_frame_rate` gets measured; it is owed and does not gate this PR.

## PR description draft

Fill the `⟨…⟩` slots from Tasks 1, 2, 5 and 9.

> **fix(relay): an interlaced source's HLS output rate comes from its `avg_frame_rate`.** ffprobe can report an H.264 PAFF stream's `r_frame_rate` as its field rate (50/1 for 1080i25). The probe read `r_frame_rate` first for every source, and the argv then doubled it for an interlaced source and capped it at 60, so such a source came out 60p with G = 120 instead of D8's 50p. An interlaced source now reads `avg_frame_rate` first and falls back to `r_frame_rate` only when `avg_frame_rate` is missing or `0/0`. Progressive sources and an unknown field order (R28) are unchanged (owner ruling R94). A 29.97i source still gives 60000/1001. The fix is in `relay/hls/probe.go` only; `outputRate` is unchanged. Spec § Encoder argv's `R` bullet says how the field rate is read, and the Changelog records it; D8 is unchanged, and Q7 is not decided. Plan: `docs/superpowers/plans/2026-09-30-fix-553-interlaced-output-rate.md` (this PR's first commit), passed at `⟨plan PASS SHA⟩`. Anchors re-grepped at `⟨BASE⟩`: ⟨moved lines, or "none moved"⟩.
>
> **Red first:** ⟨Task 2's two failing lines⟩.
>
> **Break-checks:** ⟨BC1-BC4, one line each: the wrong edit and the red line⟩.
>
> **Tests changed:** none. **E2E:** none added. The fixtures probe `r_frame_rate` = `avg_frame_rate` = 25/1 (measured at every probe bound and offset), and no toolchain encoder writes PAFF, so a Go test is the only place this can be pinned.
>
> **Coverage (R21).** No raise. `relay/hls/probe.go` 0 uncovered of ⟨n⟩ added statements (100%); the floor is unchanged at 705. Census, ⟨N⟩ rounds, in order: ⟨`this run missing=` per round, with run ids⟩; max ⟨m⟩ ≤ 705.
>
> **Ledger:** `hls-interlaced-field-rate-doubled` → fixed.
>
> Closes #553.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## Risks

- **A non-canonical `avg_frame_rate`.** ffprobe computes `avg_frame_rate` from the frames it saw. If a real channel's 3 s probe gives an interlaced source an odd rational (say `2997/100`, or something less round), `R` and G follow it, and the multivariant's `FRAME-RATE` with them. Every interlaced fixture probe measured an exact 25/1, and R94 chose `avg_frame_rate` knowingly. The owner's Q7 run records `avg_frame_rate` per channel, which is where this would show. Snapping to a canonical rate is not in R94 and is not done here.
- **`r_frame_rate` also doubled in the fallback.** An interlaced source with no `avg_frame_rate` and a field-rate `r_frame_rate` would still come out capped at 60, as at the seed. R94 accepts this: the fallback is for a missing `avg_frame_rate` only.

## Open questions (each with the planner's recommendation)

1. **Remove the floor's inert `raise_from=691` / `raise_listed=14`?** 4a-1d removed 4a-1c's pair "as its note asked", but 4a-3's provenance asks nothing. *Recommendation: leave them.* They are inert (`check_floor_raise.sh` reads them only on a rise, and refuses them as stale), and editing the floor would put this PR under the floor's own review rules for no benefit. The next PR that raises the floor overwrites them.
2. **Add a parity-matrix row for D8's rate?** *Recommendation: no.* No row covers D8's geometry or rate today, and a new row would widen a one-function fix. If the owner wants one, it belongs with D8's other decisions in a documentation PR of its own.
3. **Tell the runbook's author** that "an interlaced channel logging `frame_rate=60/1`" stops being a signal once this merges, and that the runbook should record the probe's `r_frame_rate` and `avg_frame_rate` instead (§ Overlap). *Recommendation: the orchestrator relays it before the runbook lands.*
4. **Make `make-asset.sh` assert `avg_frame_rate`?** *Recommendation: no.* It would change every variant's expected shape line and rebuild the e2e-upstream image, while the measurement above already shows the fixtures' `avg_frame_rate` is 25/1. File it as a follow-up if the owner wants the fixtures to pin the value the relay now reads.
5. **Record the census in the floor file's provenance** (4a-1d's precedent), even though `missing` does not move? *Recommendation: no.* The PR body carries it, and 4a-1d's precedent came with a statement count that had moved materially (377 added statements), where this PR adds about eight.

## Appendix A: the code and its test

A byte-exact `git diff` against `a1e9da65`. It was produced from a detached worktree of the seed with this change applied. In that worktree, `go test -count=1 -race ./...` passed over the whole module, `golangci-lint` found 0 issues under all three GOOS, and credlint was clean.

```diff
diff --git a/relay/hls/probe.go b/relay/hls/probe.go
index 5bcdf21e..8b63ea9b 100644
--- a/relay/hls/probe.go
+++ b/relay/hls/probe.go
@@ -150,7 +150,8 @@ func (r Rational) Float() float64 {
 // String is "num/den", which ffmpeg's fps filter takes as it is.
 func (r Rational) String() string { return fmt.Sprintf("%d/%d", r.Num, r.Den) }
 
-// Video is the first video stream the probe found.
+// Video is the first video stream the probe found. Its FrameRate counts
+// whole frames, an interlaced source's too (frameRate).
 type Video struct {
 	ID string
 	// Index is ffprobe's stream index, which the packet list is keyed by.
@@ -287,17 +288,14 @@ func ParseProbe(raw []byte) (Probe, error) {
 			if p.Video != nil {
 				continue
 			}
-			rate, ok := parseRational(s.RFrameRate)
-			if !ok {
-				rate, _ = parseRational(s.AvgFrameRate)
-			}
 			v := &Video{
 				ID: s.ID, Index: s.Index, Level: max(0, s.Level), Codec: s.CodecName, Profile: s.Profile, PixFmt: s.PixFmt,
-				Width: s.Width, Height: s.Height, FrameRate: rate,
+				Width: s.Width, Height: s.Height,
 			}
 			if s.FieldOrder != nil {
 				v.Field, v.fieldReported = parseFieldOrder(*s.FieldOrder), true
 			}
+			v.FrameRate = frameRate(s.RFrameRate, s.AvgFrameRate, v.Field)
 			p.Video = v
 		case "audio":
 			rate, _ := strconv.Atoi(s.SampleRate)
@@ -313,6 +311,23 @@ func ParseProbe(raw []byte) (Probe, error) {
 	return p, nil
 }
 
+// frameRate is the video's frame rate: r_frame_rate, or avg_frame_rate when
+// r_frame_rate is missing, 0/0 or unreadable. An interlaced source reads them
+// the other way round (ruling R94, issue #553): ffprobe can report an H.264
+// PAFF stream's r_frame_rate as its field rate, 50/1 for 1080i25, which
+// outputRate would double again, while its avg_frame_rate is the frame rate.
+func frameRate(r, avg string, field FieldOrder) Rational {
+	first, fallback := r, avg
+	if field == FieldInterlaced {
+		first, fallback = avg, r
+	}
+	rate, ok := parseRational(first)
+	if !ok {
+		rate, _ = parseRational(fallback)
+	}
+	return rate
+}
+
 // countPackets fills Keyframes, KeyframeInterval and BitRate from the first
 // video stream's packets. Every time is integer microseconds, so the interval
 // of a 2.1 s GOP is exactly 2.1 s and never the float difference 2.0999...
diff --git a/relay/hls/probe_test.go b/relay/hls/probe_test.go
index f569d414..21f71dfc 100644
--- a/relay/hls/probe_test.go
+++ b/relay/hls/probe_test.go
@@ -1,6 +1,7 @@
 package hls
 
 import (
+	"fmt"
 	"strings"
 	"testing"
 	"time"
@@ -324,3 +325,53 @@ func TestAnHEVCProbeWithNoFieldOrderIsCompleteAndProgressive(t *testing.T) {
 		t.Fatal("an H.264 probe with no field_order did not ask for a re-probe")
 	}
 }
+
+// Ruling R94 (issue #553): an interlaced source's rate is its avg_frame_rate,
+// with r_frame_rate only when avg_frame_rate is missing or 0/0, because
+// ffprobe reports an H.264 PAFF stream's r_frame_rate as its FIELD rate (50/1
+// for 1080i25), which outputRate doubles again and caps at 60. A progressive
+// source, and an unknown field order (R28), keep r_frame_rate first. The
+// fallback rows use 29.97, not 25: a missing rate becomes 25 in outputRate,
+// so a 25/1 fallback row would pass with the fallback deleted.
+func TestAnInterlacedSourcesRateIsItsAverageFrameRate(t *testing.T) {
+	cases := []struct {
+		name, field, r, avg string
+		probed, rate        Rational
+		gop                 int
+	}{
+		{"1080i25 PAFF, r_frame_rate the field rate", "tt", "50/1", "25/1", Rational{25, 1}, Rational{50, 1}, 100},
+		{"1080i29.97 PAFF, r_frame_rate the field rate", "bb", "60000/1001", "30000/1001", Rational{30000, 1001}, Rational{60000, 1001}, 120},
+		{"1080i25 as the fixtures report it", "tt", "25/1", "25/1", Rational{25, 1}, Rational{50, 1}, 100},
+		{"1080i29.97, r_frame_rate the frame rate", "tt", "30000/1001", "30000/1001", Rational{30000, 1001}, Rational{60000, 1001}, 120},
+		{"interlaced, avg_frame_rate 0/0", "tt", "30000/1001", "0/0", Rational{30000, 1001}, Rational{60000, 1001}, 120},
+		{"interlaced, avg_frame_rate absent", "tt", "30000/1001", "", Rational{30000, 1001}, Rational{60000, 1001}, 120},
+		{"progressive keeps r_frame_rate first", "progressive", "50/1", "25/1", Rational{50, 1}, Rational{50, 1}, 100},
+		{"an unknown field order keeps r_frame_rate first", "", "50/1", "25/1", Rational{50, 1}, Rational{50, 1}, 100},
+	}
+	for _, c := range cases {
+		stream := `"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "id": "0x300", "r_frame_rate": "` + c.r + `"`
+		if c.avg != "" {
+			stream += `, "avg_frame_rate": "` + c.avg + `"`
+		}
+		if c.field != "" {
+			stream += `, "field_order": "` + c.field + `"`
+		}
+		p, err := ParseProbe([]byte(`{"streams": [{` + stream + `}]}`))
+		if err != nil {
+			t.Fatalf("%s: ParseProbe: %v", c.name, err)
+		}
+		out, err := Decide(p)
+		if err != nil {
+			t.Fatalf("%s: Decide: %v", c.name, err)
+		}
+		if p.Video.FrameRate != c.probed || out.FrameRate != c.rate || out.GOP != c.gop {
+			t.Errorf("%s: probed %v, R=%v G=%d; want probed %v, R=%v G=%d",
+				c.name, p.Video.FrameRate, out.FrameRate, out.GOP, c.probed, c.rate, c.gop)
+			continue
+		}
+		argv := joinArgs(out.Argv(PlanGeneration(out, p, EngineSoftware), DefaultDevice))
+		if !strings.Contains(argv, "fps="+c.rate.String()+",") || !strings.Contains(argv, fmt.Sprintf(" -g %d ", c.gop)) {
+			t.Errorf("%s: the argv does not carry fps=%v and -g %d: %q", c.name, c.rate, c.gop, argv)
+		}
+	}
+}
```

## Appendix B: the spec amendment

A byte-exact `git diff` against `a1e9da65`.

```diff
diff --git a/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md b/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md
index 79628d23..b9b7707e 100644
--- a/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md
+++ b/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md
@@ -555,7 +555,11 @@ ffmpeg -hide_banner -loglevel warning -nostats
 
 - `W`, `H` and `R` are fixed at the first generation. `R` is the field rate for an interlaced
   source (1080i at 25 frames or 50 fields per second becomes 50p), or the frame rate for a
-  progressive one, capped at 60. `G` = round(2 × R). For fractional rates (29.97, 59.94) a segment
+  progressive one, capped at 60. The field rate is twice the probe's `avg_frame_rate`, and twice
+  `r_frame_rate` only when `avg_frame_rate` is missing or `0/0` (R94, issue #553): ffprobe can
+  report an H.264 PAFF stream's `r_frame_rate` as its field rate, 50/1 for 1080i25, and doubling
+  that again would cap at 60. A progressive source's frame rate, or one whose field order is
+  unknown (R28), is its `r_frame_rate`, with `avg_frame_rate` as the fallback. `G` = round(2 × R). For fractional rates (29.97, 59.94) a segment
   is then 60 or 120 frames, and `EXTINF` is 2.002 s rather than 2.000 s. That is within
   4a-1a's "2.000 s ± one frame" and within Apple 7.7.
 - Bitrate `B` / `M`: height ≥ 1080 is 6 / 8 Mb/s; ≥ 720 is 4 / 5 Mb/s; otherwise 2.5 / 3 Mb/s.
@@ -2273,6 +2277,13 @@ Filled in as PRs merge.
   § Open questions records CI's measurements: Q9 is answered (hls.js keeps reloading while paused,
   so there is no leave on pause), and Q6's software gap is 7.91-9.97 s over six runs, under the
   10 s threshold every time but at its edge, so the owner's Quick Sync measurement decides.
+- **2026-09-30, amended by the fix for #553** (`docs/superpowers/plans/2026-09-30-fix-553-interlaced-output-rate.md`,
+  written against `a1e9da65`). § Encoder argv only: an interlaced source's `R` is twice its
+  `avg_frame_rate`, falling back to `r_frame_rate` only when `avg_frame_rate` is missing or `0/0`
+  (R94). The relay had read `r_frame_rate` first for every source, so a PAFF 1080i25 source whose
+  `r_frame_rate` is its field rate came out 60p with G = 120 where D8 says 50p. D8 is unchanged:
+  this says how "the field rate" is read. Q7's contingency ("`R` is taken from the field rate") is
+  not decided here.
 
 ## Appendix A — the owner's rulings (2026-09-26/27), restated
 
```

## Appendix C: the defect-ledger entry

A byte-exact `git diff` against `a1e9da65`, except for its two slots: `⟨PR⟩` is this PR's number, and `⟨merge date⟩` the day it is expected to merge (Task 6). The entry was validated with those slots set to `999` and `2026-09-30`: `python -m metrics.build --validate-only` printed `ok: 46 metrics, 39 milestones, 47 defects`.

```diff
diff --git a/metrics/curated/defects.yml b/metrics/curated/defects.yml
index 0d02eeeb..361696d4 100644
--- a/metrics/curated/defects.yml
+++ b/metrics/curated/defects.yml
@@ -47,3 +47,4 @@
 - {id: catchup-provider-tz-drops-seconds, title: "convert_timestamp_to_provider_tz dropped the requested seconds for a non-UTC provider timezone while the UTC branch kept them, so the precision asked for depended on the provider's declared zone", area: correctness, severity: low, status: fixed, source: null, issue: 111, test: e2e/tests/streaming/catchup-provider-timezone.spec.ts, fixed_in: 438, carried_as: null, first_seen: 2026-09-01, status_changed: 2026-09-25}
 - {id: xc-vod-info-detailed-info-gate, title: "xc_get_vod_info gated the relation's detailed_info merge on Movie.custom_properties, so a movie with none lost bitrate, video, audio and the plot override on the XC surface", area: correctness, severity: low, status: fixed, source: null, issue: 97, test: e2e/tests/seeded/xc-vod-catalogue.spec.ts, fixed_in: 453, carried_as: null, first_seen: 2026-08-31, status_changed: 2026-09-25}
 - {id: vod-category-account-filter-500, title: "VODCategoryFilter.m3u_account named m3u_account__id, a relation VODCategory does not have, so ?m3u_account= on /api/vod/categories/ was a 500", area: correctness, severity: low, status: fixed, source: null, issue: 96, test: e2e/tests/seeded/vod-ingest-fidelity.spec.ts, fixed_in: 453, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-09-25}
+- {id: hls-interlaced-field-rate-doubled, title: "The HLS re-encode read an interlaced source's r_frame_rate before its avg_frame_rate, so a PAFF 1080i25 source reporting its field rate (50/1) as r_frame_rate was doubled to 100 and capped, and came out 60p with G=120 instead of D8's 50p", area: correctness, severity: medium, status: fixed, source: null, issue: 553, test: relay/hls/probe_test.go, fixed_in: ⟨PR⟩, carried_as: null, first_seen: 2026-09-30, status_changed: ⟨merge date⟩}
```
