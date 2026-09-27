# Plan: Phase 4a-0, the e2e-upstream codec fixtures

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The PR's code is Appendix A, a byte-exact `git diff` verified to apply at the seed; the tasks around it are the checks that prove it landed.

**Goal.** `e2e-upstream` gains the six looping codec fixtures that Phase 4a's HLS tests name, and a scenario channel gains an optional `asset` field that chooses which one its stream serves. Every fixture is 20 s at 25 frames per second, has PIDs of its own, and is probed by `scripts/make-asset.sh` when the image is built, so an image that exists has the shapes `CONTRACT.md` promises. Viewers are unaffected: no server code changes, and a channel that names no asset streams exactly what it did.

**Seed.** `6c98547399a58acbd025c306f77c349c9dfcd308` (`6c985473`, main on 2026-09-27, the Phase 4 spec merged as #523). Every `file:line` below is at the seed unless it says otherwise. Main had not moved when this plan was written (`git rev-parse origin/main` = `6c985473`).

**Branch.** `migration/phase4-4a0-upstream-fixtures` (spec D1), so the full E2E and lifecycle matrix runs on it. That matters here: every E2E project's upstream image is rebuilt from this PR's Dockerfile.

**Authority.** In order of precedence:

1. The Phase 4 spec, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`: § 4a-0 (`:1173-1189`), § Testing's E2E list (`:1107-1117`), D1 (`:210`) and D20 (`:231`). Every later section that names a 4a-0 asset was read for what it needs (§ Consumers below).
2. The owner's rulings R1-R27 (the orchestrator's `rulings.md`). None rules on fixtures directly; R20 (E-AC-3-only sources get three audio renditions) and R7 (MP2 → AAC, interlaced/MPEG-2 → H.264) fix what two fixtures must exercise. Models: opus only.
3. CLAUDE.md, `e2e/README.md`, `e2e/COVERAGE.md`, ADRs 0001-0003, and `e2e-upstream/CONTRACT.md` (its bump policy decides the version).
4. `docs/relay-parity-matrix.md` is not affected: 4a-0 touches no relay code and no live-path behaviour.

**Issues.** None. This PR closes no issue, so its description carries no closing keyword.

## Global constraints

1. **No server change.** Nothing outside `e2e-upstream/`, `e2e/fixtures/upstream.ts` and `e2e/COVERAGE.md` is edited. No Django, Go, frontend, nginx or workflow file.
2. **`loop` is byte-for-byte what it was.** The default asset's ffmpeg command is moved into the `loop)` case unchanged, keeps `ASSET_DURATION_SECONDS`/`ASSET_FPS`/`ASSET_BITRATE`, its PIDs `0x100`/`0x101` and its 2000k bitrate (which `relay/internal/relaytest/asset_test.go:89-95` anchors on), and stays at `/app/assets/loop.ts` under `UPSTREAM_ASSET`. A scenario that names no asset streams it.
3. **The version moves with the contract.** `package.json`, both `version` fields of `package-lock.json` and `CONTRACT.md`'s `**Version:**` line all go `1.2.0` → `1.3.0` (minor: a new optional field and new assets, per `CONTRACT.md`'s bump policy). `e2e/tests/guards/upstream-contract.spec.ts` enforces the pair.
4. **Test-modification rule.** One existing assertion changes, because the behaviour it pins (the echoed channel shape) is the thing being changed. It is listed with before and after in § Tests. No other existing test is edited except one `import` line.
5. **Hooks.** `e2e/fixtures/upstream.ts` is under the blocking `tsc --noEmit` arm of `run-affected-tests.sh`; `e2e/COVERAGE.md` has no hook. The `e2e-upstream` edits trigger that package's `tsc` arm. None of these needs the shared test container.
6. **hadolint.** `lint.yml` runs hadolint on `e2e-upstream/Dockerfile` at `--failure-threshold error`. The new Dockerfile has one finding, the pre-existing DL3008 warning on line 2, and no error (measured).

## What was measured

All of it in the planner's scratchpad; nothing was written into the repository.

- **Three ffmpeg builds.** The final `make-asset.sh` built and passed its own shape checks for all six fixtures on:
  - Debian bookworm's `ffmpeg 5.1.9-0+deb12u1`, in the exact asset-stage base (`debian:bookworm-slim@sha256:88200866…`) under `--platform linux/amd64`, which is what CI's `build` job runs. `loop` built too.
  - The production relay's `lscr.io/linuxserver/ffmpeg:version-9.0-cli@sha256:47fbdc93…` (`docker/DispatcharrBase:7`), amd64, `ffmpeg version 9.0`. This is the ffmpeg 4a-1a's Go tests will run.
  - Homebrew `ffmpeg 9.0.1` on macOS, under `/bin/bash` 3.2 (the script uses no bash-4 feature). `loop` does not build there (no `drawtext`), as the README already says; the six fixtures do.
  - The local `ghcr.io/d10scot/dispatcharr:base` (stale, `ffmpeg 8.1.2`) also passed.
- **Asset-stage build time** under amd64 emulation on the planner's host: `loop` 12 s, `mpeg2-576i-mp2` 5 s, `h264-1080i-aac-ac3` 16 s, `hevc-aac` 19 s, `h264-gop10-aac` 6 s, `h264-eac3` 4 s, `h264-noaudio` 4 s. The whole `docker build` of the image took 2 min 31 s emulated. CI builds natively and will be faster; nothing gates on this.
- **Sizes.** The six fixtures total about 44.7 MB (bookworm build: 11.0, 17.2, 3.2, 4.3, 5.0 and 3.9 MB, in table order). Sizes vary with the ffmpeg version by up to 0.4 % (`hevc-aac`: 3,193,180 bytes on 5.1.9, 3,204,836 on 9.0.1), which is why no size is guaranteed.
- **The image, run.** The built image (`docker build --platform linux/amd64`) was started on a private port. `POST /scenarios` with seven channels, one per asset, echoed `asset` on every channel; `asset: "nope"` answered `400 {"error":"'channels.asset' for channel 1 is \"nope\", which is not an asset this provider has; expected one of loop, mpeg2-576i-mp2, h264-1080i-aac-ac3, hevc-aac, h264-gop10-aac, h264-eac3, h264-noaudio"}`. Each channel was read for 4 s at `rate: 20` (two to three loop wraps) and ffprobed: every served stream had its asset's streams and PIDs, and video DTS strictly increased across every wrap (the largest step 0.075-0.121 s, against 0.040 s within a loop; see § Decisions 7).
- **vitest.** 277 tests in 16 files at the seed; 294 in 17 with Appendix A (17 added). `npm run typecheck` exits 0. `e2e`'s `npx tsc --noEmit -p .` exits 0 and the `guards` project passes 49/49 with the version bump.
- **The 1080i encode cost (informative, not a gate).** D8's software transcode (bwdif, 1920×1080 50p, `libx264 -preset veryfast -tune zerolatency`, 6 Mb/s) over the 20 s `h264-1080i-aac-ac3` fixture took 3.6 s with `-threads 2` on an M4 Pro (5.5× real time). CI runners are slower; CLAUDE.md's measure-where-enforced rule means this sets nothing (§ Residual risks).

### The fixtures, measured

ffprobe on the bookworm build (the image's). The 9.0.1 build probes to the same values, and the 9.0 build passes the same checks. "Keyframes" are display-order frame indices of the first video stream; every fixture has exactly 500 video frames.

| `asset` | Stream 0 (video) | Audio streams | Keyframes | Measured loop / seam excess |
|---|---|---|---|---|
| `mpeg2-576i-mp2` | `0x200` mpeg2video Main (level 8), 720×576, yuv420p, `field_order=tt`, 25/1 | `0x201` mp2, 48000 Hz, 2 ch, stereo | 0, 50, …, 450 (10) | 20.035 s / 35 ms |
| `h264-1080i-aac-ac3` | `0x300` h264 High (level 40), 1920×1080, yuv420p, `field_order=tt`, 25/1 | `0x301` aac LC, 48000, 2 ch, stereo; `0x302` ac3, 48000, 6 ch, 5.1(side) | 0, 50, …, 450 (10) | 20.078 s / 78 ms |
| `hevc-aac` | `0x400` hevc Main (level 63), 640×360, yuv420p, **`field_order=unknown`**, 25/1 | `0x401` aac LC, 48000, 2 ch, stereo | 0, 50, …, 450 (10) | 20.081 s / 81 ms |
| `h264-gop10-aac` | `0x500` h264 High (level 30), 640×360, yuv420p, `progressive`, 25/1 | `0x501` aac LC, 48000, 2 ch, stereo | 0, 250 (2) | 20.081 s / 81 ms |
| `h264-eac3` | `0x600` h264 High (level 30), 640×360, yuv420p, `progressive`, 25/1 | `0x601` eac3, 48000, 6 ch, 5.1(side) | 0, 50, …, 450 (10) | 20.057 s / 57 ms |
| `h264-noaudio` | `0x700` h264 High (level 30), 640×360, yuv420p, `progressive`, 25/1 | none (the PMT declares one stream) | 0, 50, …, 450 (10) | 20.067 s / 67 ms |
| `loop` (unchanged) | `0x100` h264 **Constrained Baseline** (level 30), 640×360, `progressive`, 25/1 | `0x101` aac LC, mono | 0, 250, …, 1250 (6 of 1500 frames) | 60.683 s / 683 ms |

"Measured loop" is `measureLoop()`'s value (ported to Python in the scratchpad and cross-checked against the served streams); the seam excess is how far every timestamp jumps forward at each wrap beyond one frame.

### Consumers: what each later PR needs, and which fixture gives it

| Spec reference | Needs | Fixture and the property that serves it |
|---|---|---|
| 4a-1a (`:1202-1203`) "12 s of the 1080i fixture gives aligned 2 s segments on three renditions" | ≥ 12 s; AAC + AC-3 source | `h264-1080i-aac-ac3`: 20 s; AAC stereo + AC-3 5.1, so `aac` and `ac3` copy and three renditions exist |
| 4a-1a (`:1204`), 4a-1b E2E (`:1121`) "the E-AC-3 fixture gives three audio renditions / three audio groups" | E-AC-3 **only** (R20) | `h264-eac3`: one audio stream, eac3 5.1, so `aac` and `ac3` are encoded from it and `eac3` copies |
| 4a-1a (`:1206-1208`), 4a-1b E2E (`:1121`) "no-audio fixture gets a relay-synthesised silent AAC rendition" | no audio at all (M8) | `h264-noaudio`: the PMT declares no audio stream, so no qualifying audio exists |
| 4a-1a (`:1211-1212`) boundary test "two fixtures with different PIDs" | distinct PIDs between fixtures | every fixture has its own PID base (`0x200`…`0x700`, `loop` `0x100`) |
| 4a-1a (`:1213-1216`) rendition filling, gen 0 on 1080i AAC + AC-3, gen 1 on MPEG-2 + MP2 | an MP2-only source after an AC-3 one | `h264-1080i-aac-ac3` then `mpeg2-576i-mp2` |
| D8/D9 deinterlace (`:217-218`), 4a-1d "copy interlaced video" break-check (`:1432`) | interlaced sources that ffprobe reports as interlaced | `mpeg2-576i-mp2` and `h264-1080i-aac-ac3`: `field_order=tt`, and genuinely interlaced (a 50p `testsrc2` woven by `interlace=scan=tff`, so the two fields are 20 ms apart) |
| 4a-1d decision table (`:597-601`, `:1423`) | one fixture per rule, each differing from a copy-eligible source in one property | MPEG-2 → transcode; interlaced H.264 → transcode; HEVC Main 8-bit progressive, K = 2 s → copy; H.264 with a 10 s GOP → transcode; AAC → copy; MP2 → encode AAC; AC-3/E-AC-3 → as transcode. `h264-gop10-aac` differs from a copyable source **only** in its GOP, but under D9's probe bound ("5 MB or 8 s", `:218`) no probe window can hold two of its keyframes (0 s and 10 s), so it trips the rule's **"fewer than 2 keyframes seen"** branch (`:598`), not "K > 6 s". It does not pin the 6 s threshold (§ Follow-ups) |
| 4a-1d declared-family (`:1424`) "a copied-HEVC run whose next source is MPEG-2" | copyable HEVC, then MPEG-2 | `hevc-aac` then `mpeg2-576i-mp2` |
| 4a-1d E2E (`:1430`) "an automatic channel on the H.264 asset serves copied video with the source's `CODECS`" | progressive H.264 with K ≤ 6 s | `h264-noaudio` or `h264-eac3` (both High, 2 s GOP). **Not `loop`**: its GOP is 10 s, so an 8 s probe window sees one keyframe and automatic mode transcodes it |
| 4a-1b E2E (`:1128-1129`) failover "to an alternate with a **different** asset" | two channels, two assets | the per-channel `asset` field |
| 4a-1c E2E (`:1130-1143`) `maxConnections: 1` | already exists | unchanged |

## Decisions

The spec fixes the six assets' codecs and says they are short, SD and built by `make-asset.sh` variants. It is silent on everything below, so each is decided here.

1. **Names.** `mpeg2-576i-mp2`, `h264-1080i-aac-ac3`, `hevc-aac`, `h264-gop10-aac`, `h264-eac3`, `h264-noaudio`, and `loop` for the existing default. Each name says what the fixture is, so a consumer spec reads without a lookup. They are neutral identifiers (R15 concerns externally visible product identifiers; these are test-only).
2. **Per channel, not per scenario.** `channels[].asset`, as the spec's "a scenario channel can name its asset" says. The count form (`channels: 3`) gives every channel `loop`; a scenario that needs fixtures uses the array form. An omitted `asset` resolves to `loop` and the echo always carries the resolved name, because `CONTRACT.md` guarantees the echo includes "every default the parser filled in". An unknown or non-string name is a `400` naming the channel, the value and the valid names: accepted, it would `500` on the first stream request, far from its cause. A channel id the scenario does not declare (the plain `/stream/<n>.ts` route serves any id, `src/server.ts:254-258` at the seed) keeps getting `loop`.
3. **Geometry, and the spec's one contradiction.** The spec says the assets are "SD" (`:1108`) and also lists "H.264 1080i" (`:1110`). The 1080i fixture is 1920×1080: its name is the spec's, M3/M4 prototyped exactly that source, D8's "at most 1920×1080, never upscaled" and the `bwdif` 50i → 50p path are what it exists to exercise, and 4a-1a feeds it from a file, not in real time. The other five are SD: `mpeg2-576i-mp2` at 720×576, the rest at 640×360 (the existing asset's size). The real-time cost is a named risk (§ Residual risks), not a reason to rename the spec's fixture. **This is now the owner's ruling R29** (2026-09-27): the 1080i fixture stays 1920×1080 so that it exercises real 1080i, and 4a-1b measures whether CI's software transcode keeps real time and, if it does not, raises that as a finding rather than lowering an assertion.
4. **20 s, 25 fps, a 2 s GOP.** 20 s is the spec's ceiling, is the shortest length that gives the 10 s-GOP fixture two keyframes, and covers 4a-1a's 12 s. Every GOP is a whole divisor of the loop (500 frames), so a wrap never makes a short GOP. The copy-eligible fixtures use a fixed 2 s GOP (`-g 50 -keyint_min 50 -sc_threshold 0`, x265 `keyint=50:min-keyint=50:scenecut=0`) so that automatic mode's `TARGETDURATION` is 2 and its segment cut is deterministic. H.264 and HEVC keep B-frames, as broadcast does, so the copy path meets composition offsets. MPEG-2 uses `-bf 0`: with B-frames its encoder placed I-frames at 0, 51, 99, 147, … (measured), which the GOP check rejects and which no consumer needs.
5. **Distinct PIDs.** Each fixture's PIDs start at its own `0x?00` (`-mpegts_start_pid` and `-streamid`), so any two fixtures fed one after the other change PIDs as two providers' streams do. That is the case M3 showed one encoder silently drops, and 4a-1a's boundary test needs it. `loop` keeps `0x100`/`0x101`.
6. **Interlace for real.** The interlaced fixtures come from a 50 fps `testsrc2` woven into top-field-first frames by `interlace=scan=tff`, encoded field-aware (`-flags +ildct+ilme`, x264 `tff=1`). ffprobe reports `field_order=tt` on every ffmpeg measured, and the fields differ in time, so a missing deinterlace is visible.
7. **`-muxdelay 0 -muxpreload 0` on the six.** `measureLoop()` (`src/asset.ts:30-83`) spans every PCR, PTS and DTS and adds one mean step. With ffmpeg's default 0.7 s PCR lead that overshoots the media by about 0.76 s, so every wrap jumps all timestamps forward that much: measured 20.74-20.77 s for a 20 s fixture. That is harmless for TS clients but lands in 4a-1d's copy path: a copied segment spanning a wrap would be about 2.76 s, over its "target + 0.5 s" limit (`:614-615`), and would end the generation every 20 s. With zero mux delay the excess is 35-81 ms (a segment of at most 2.08 s). `measureLoop()` itself is not changed, because `loop` and every existing consumer depend on its current behaviour; its overshoot on `loop` (0.68 s) is a follow-up, written into `CONTRACT.md` as a non-guarantee.
8. **The shape check runs at image build, not in vitest.** CI's `upstream` job (`.github/workflows/e2e-tests.yml:189-216`) has Node and no ffmpeg, and the fixtures exist only inside the image. `make-asset.sh` therefore probes each fixture right after writing it: `check_shape` compares each stream's ffprobe `key=value` pairs against the expected ones and names the missing, wrong or unexpected stream; `check_gop` checks 500 frames and a keyframe at exactly every GOP boundary. A failure prints `make-asset.sh: <asset>: …`, deletes the file and exits 1, which fails `docker build` in the `build` job (and every E2E job after it). The Dockerfile's loop carries `|| exit 1`, because `sh -c` has no `-e` and a `for` loop's status is its last command's: measured, without it the build exits 0 with the failure message printed. This is the "asset-shape test" of the spec's break-check. Two ffprobe differences are handled: 5.1 prints a blank line after every `csv` packet line (dropped before counting), and `-of compact` lists each stream twice for a TS (under its program and at top level; deduplicated).
9. **What the shape check does not assert.** It omits `field_order` for `hevc-aac`, because ffprobe reports `unknown` for that progressive HEVC on every build measured (5.1.9, 8.1.2, 9.0.1; x265's `pic-struct`, `hrd` and `frame-dup` options did not change it). It omits `profile` for MP2, AC-3 and E-AC-3 (ffprobe prints `unknown`), and levels, bitrates, sizes and durations, which drift with ffmpeg. Ruling R28 treats `unknown` as progressive for copy eligibility (only an explicit `tt`/`bb`/`tb`/`bt` is interlaced); the hand-off to 4a-1a and 4a-1d is issue #525 (§ Follow-ups).
10. **One list of names, held to the build.** `src/asset.ts` exports `ASSET_NAMES`. A new vitest file, `test/asset-names.test.ts`, reads `scripts/make-asset.sh`'s `case` labels and the Dockerfile's `for name in …` list and requires both to equal `ASSET_NAMES`, so the door never accepts a name the image has no file for. `e2e/fixtures/upstream.ts` gains an `UpstreamAsset` union mirroring the list, as `FaultName` mirrors the fault catalogue; a drift there is loud either way (a compile error, or a `400` naming the name), so no guard is added for it.
11. **Paths.** A named asset is `<name>.ts` under `UPSTREAM_ASSET_DIR` (default `/app/assets`); `loop` keeps `UPSTREAM_ASSET`. The Dockerfile builds all seven plus `vod.mp4` into `/build/assets/` and copies the directory, so `/app/assets/loop.ts` and `/app/assets/vod.mp4` stay where they were. `getAsset()` caches by resolved path, as `getVodAsset()` already does, and still resolves before `tryAcquire`, so a missing file costs no slot.
12. **No `drawtext` in the fixtures.** The six build with any ffmpeg that has libx264 and libx265, so 4a-1a may build them in Go tests with the production ffmpeg (`make-asset.sh <out> <name>`) rather than depending on the upstream image. `testsrc2` and sine tones carry no marker, and nothing asserts on picture content. The 5.1 fixtures give each channel its own tone, so a downmix is audible as one.
13. **COVERAGE.md.** One row is added (Area `Upstream`, Goal `4a-0`, `done`), and the D6 per-stream-identity Gap row (`:51`) gains one sentence saying that channels on different assets now differ, so the gap is narrower but stands. Both are truth maintenance for text this PR makes stale.

## PR 4a-0: e2e-upstream gains the codec fixtures

**Files** (anchors at the seed):

- `e2e-upstream/scripts/make-asset.sh` (whole file, 50 lines). Rewritten as `make-asset.sh <out> [variant]`: the seed's command becomes the `loop)` case unchanged; six variants, `check_shape`, `check_gop` and `fail` are added; the seed's trailing packet-alignment and sync-byte checks run for every variant.
- `e2e-upstream/Dockerfile:6-9,25-28`. The build loop over seven names into `/build/assets/`; the runtime stage copies the directory and sets `UPSTREAM_ASSET_DIR`.
- `e2e-upstream/src/asset.ts:1-2,4`. `ASSET_NAMES`, `AssetName`, `DEFAULT_ASSET`, `isAssetName`, `assetPath`.
- `e2e-upstream/src/scenario.ts:2,20-21,23-33,194-196,602-604,736-741`. `ChannelSpec.asset`, `ResolvedChannelSpec.asset`, the door check and both defaults.
- `e2e-upstream/src/server.ts:9-10,39-54,381-386`. `getAsset(name)` with a path-keyed cache; `serveChannelStream` picks the channel's asset.
- `e2e-upstream/test/asset-names.test.ts`. New (3 tests).
- `e2e-upstream/test/asset.test.ts:2,52`. The import line; 4 tests appended.
- `e2e-upstream/test/scenario.test.ts:3,32,42`. One import added; one existing test's title and expectation change (§ Tests); 5 tests appended.
- `e2e-upstream/test/server.test.ts:1023`. 5 tests appended.
- `e2e-upstream/CONTRACT.md:3,24-27,31-33,68,161-167,175-179,199-218,219-252,253-272`. Version 1.3.0; the fixture guarantees and table; the D6 and size non-guarantees reworded; a seam non-guarantee; planned consumers; the 1.3.0 landing note; the third enforcement level.
- `e2e-upstream/README.md:66,379-381,386`. The `POST /scenarios` row; the `drawtext` paragraph narrowed to `loop`; a new "The codec fixtures" section before "The VOD asset" (`:387`).
- `e2e-upstream/package.json:4`, `e2e-upstream/package-lock.json:3,9`. `1.2.0` → `1.3.0`.
- `e2e/fixtures/upstream.ts:88-92,165`. `UpstreamAsset`, `UpstreamChannel.asset?`, and `UpstreamScenario.channels` typed with a non-optional `asset`, because the provider always echoes it.
- `e2e/COVERAGE.md:51,208`. The D6 row's added sentence; the new 4a-0 row after `:208`.

**Tasks.**

1. **Pre-flight.** In the implementation worktree, confirm the seed anchors: `git show "${SEED}:e2e-upstream/src/server.ts" | sed -n '48p;386p'` prints `let asset: LoadedAsset | undefined;` and `  const asset = getAsset();`, and `git show "${SEED}:e2e-upstream/package.json" | grep '"version"'` prints `1.2.0`. If main has moved any file Appendix A touches (`git diff --stat 6c985473 origin/main -- e2e-upstream e2e/fixtures/upstream.ts e2e/COVERAGE.md` prints anything), stop and report; do not re-derive.
2. **Apply Appendix A.** Extract it from this plan at the plan's merged SHA and apply it:
   `awk '/^<!-- appendix-A-begin -->$/{f=1; next} /^<!-- appendix-A-end -->$/{f=0} f' docs/superpowers/plans/2026-09-27-phase4-4a0-upstream-fixtures.md | sed '1d;$d' > /tmp/4a0.diff && git apply --whitespace=error /tmp/4a0.diff` (use your scratchpad rather than `/tmp` if you have one). `git status --short` shows 14 modified files and one new one, `e2e-upstream/test/asset-names.test.ts`.
3. **vitest and typecheck.** `cd e2e-upstream && npm ci && npm run typecheck && npm test`: typecheck exits 0; `Test Files 17 passed (17)`, `Tests 292 passed (292)` (seed: 16 and 277).
4. **The e2e package.** `cd e2e && npm ci && npx tsc --noEmit -p . && npx playwright test --project guards`: tsc exits 0; 49 passed, including `upstream-contract.spec.ts`.
5. **Build every fixture where CI builds it.** `docker build --platform linux/amd64 -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream-4a0:local e2e-upstream` (a private tag, per `worktree-per-change`'s E2E rule). It exits 0 and prints seven `Wrote /build/assets/<name>.ts (<name>, …)` lines. Then `docker run --rm --entrypoint ls dispatcharr-e2e-upstream-4a0:local /app/assets` lists the seven `.ts` files and `vod.mp4`.
6. **Probe the built fixtures.** `docker create` the image, `docker cp` `/app/assets` out, and run for each fixture: `ffprobe -v error -show_entries stream=index,id,codec_name,profile,pix_fmt,field_order,width,height,r_frame_rate,sample_rate,channels,channel_layout -of compact <file>`. The values match § The fixtures, measured (profile strings, PIDs, `field_order`, channel counts and layouts; levels may differ).
7. **Serve them.** `docker run -d --name upstream-4a0 -p 127.0.0.1:<free port>:8080 dispatcharr-e2e-upstream-4a0:local`; `POST /scenarios` with `rate: 20` and seven array-form channels, one per name (the last with no `asset`). The echo's `channels[].asset` is the seven names with `loop` last. `curl --max-time 4` each `/s/<id>/stream/<n>.ts` to a file and ffprobe it: each has its fixture's streams and PIDs, and `ffprobe -select_streams v:0 -show_entries packet=dts -of csv=p=0` (blank lines dropped) strictly increases. `POST` a channel with `"asset":"nope"`: `400` with the message quoted in § What was measured. `docker rm -f upstream-4a0` afterwards.
8. **hadolint.** `docker run --rm -i hadolint/hadolint@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d hadolint --failure-threshold error - < e2e-upstream/Dockerfile` exits 0 (only `-:2 DL3008` warning).
9. **Break-checks** (each applied alone, run, then reverted; the revert is checked with `git diff --stat` showing only Appendix A's files):
   - **BC1, the spec's.** Build `h264-1080i-aac-ac3` without its AC-3 track: in `make-asset.sh`, change `-map 0:v -map 1:a -map 2:a -vf "interlace=scan=tff"` to `-map 0:v -map 1:a -vf "interlace=scan=tff"` and delete the line `      -c:a:1 ac3 -b:a:1 448k \`. `bash e2e-upstream/scripts/make-asset.sh /tmp/x.ts h264-1080i-aac-ac3` exits 1 with `make-asset.sh: h264-1080i-aac-ac3: missing stream 2: expected index=2|id=0x302|codec_type=audio|codec_name=ac3|sample_rate=48000|channels=6|channel_layout=5.1(side), but the asset has only 2 stream(s)` and leaves no `/tmp/x.ts`. The same edit makes `docker build --target asset -f e2e-upstream/Dockerfile e2e-upstream` fail with that line and `did not complete successfully: exit code: 1` (measured natively; CI's `build` job reddens at "Build the upstream provider image").
   - **BC2, the long GOP.** In the `h264-gop10-aac)` case change `-g 250 -keyint_min 250` to `-g 50 -keyint_min 50`: exit 1, `make-asset.sh: h264-gop10-aac: video stream 0 has 10 keyframes, expected 2 (one every 250 frames); expected one keyframe every 10 s`.
   - **BC3, interlacing.** In the `mpeg2-576i-mp2)` case change `-c:v mpeg2video -flags +ildct+ilme` to `-c:v mpeg2video`: exit 1, `make-asset.sh: mpeg2-576i-mp2: stream 0: expected field_order=tt, found index=0|…|field_order=progressive|id=0x200|…`.
   - **BC4, the build loop.** Delete ` h264-noaudio` from the Dockerfile's `for name in …` list: `npx vitest run test/asset-names.test.ts` fails `the Dockerfile builds every name in ASSET_NAMES, and no other` with `AssertionError: Dockerfile's asset build loop vs src/asset.ts ASSET_NAMES: expected [ 'h264-1080i-aac-ac3', …(5) ] to deeply equal [ 'h264-1080i-aac-ac3', …(6) ]` and a diff whose one `-` line is `"h264-noaudio",`.
   - **BC5, routing.** In `src/server.ts` change `  const asset = getAsset(assetName);` to `  const asset = getAsset(DEFAULT_ASSET);`: four tests in `test/server.test.ts` fail, `AssertionError: channel 1 names h264-eac3 (PID 0x600); the channel's asset picks the file: expected 256 to be 1536`, the same for `/live/ channel 1` and for `PATH catch-up channel 1` (the catch-up test stops at its first assertion, so the QUERY layout's message does not print), and `hevc-aac.ts was never written, so its load must fail: expected 200 to be 500`.
   - **BC6, the door.** In `src/scenario.ts` change `if (asset !== undefined && !isAssetName(asset)) {` to `if (asset !== undefined && !isAssetName(asset) && false) {`: two tests in `test/scenario.test.ts` fail, `AssertionError: the door must refuse an asset name the provider has no file for: expected [Function] to throw an error` and `the door must refuse a non-string asset: expected [Function] to throw an error`.
   - **BC7, the Dockerfile's `|| exit 1`.** Delete ` || exit 1` from the Dockerfile's loop (`./make-asset.sh "/build/assets/${name}.ts" "${name}" || exit 1; \` becomes `./make-asset.sh "/build/assets/${name}.ts" "${name}"; \`): `npx vitest run test/asset-names.test.ts` fails `the Dockerfile fails the build when make-asset.sh fails for any name` with `AssertionError: the Dockerfile's asset loop must run make-asset.sh with '|| exit 1', or a failed shape check does not fail docker build: expected 'FROM debian:bookworm-slim@sha256:8820…' to match /do \\\n\s*\.\/make-a…/make-asset\.sh "\` (vitest truncates the regex). Why the guard matters, measured: with this edit **and** BC1 applied together, `docker build --target asset …` exits **0** although it prints BC1's message, because the loop's status is `h264-noaudio`'s. Revert.
   - **BC8, a silent probe.** Put a `ffprobe` that exits 1 first on `PATH` (`printf '#!/bin/sh\nexit 1\n' > <dir>/ffprobe; chmod +x <dir>/ffprobe`) and run `PATH="<dir>:$PATH" bash e2e-upstream/scripts/make-asset.sh /tmp/p.ts h264-noaudio`: exit 1, `make-asset.sh: h264-noaudio: ffprobe could not list the streams of /tmp/p.ts`, and no `/tmp/p.ts`. Without the `|| fail` on `probe_streams` the script dies with no message.
10. **Push and open the PR as a draft** (`implement-review-escalate`), with the description below. CI's `E2E result`, `Lifecycle result` and the `upstream` job must be green; the full matrix runs because the branch is `migration/…`.

**Tests added.**

| File | Test | Pins |
|---|---|---|
| `test/scenario.test.ts` | `channel asset (Phase 4a-0)`: `keeps a named asset and defaults an omitted one to loop, through the parser and the registry`; `gives count-form channels the default asset`; `accepts every name in ASSET_NAMES`; `rejects an unknown asset, naming the channel, the value and the names that exist`; `rejects a non-string asset, naming the field` (3 and `null`) | Decision 2 at the door and in `create()` |
| `test/asset.test.ts` | `asset names and paths (Phase 4a-0)`: `defaults to loop, which is one of the names`; `recognises exactly the declared names`; `keeps loop on UPSTREAM_ASSET and puts every other name under UPSTREAM_ASSET_DIR`; `falls back to the image's /app/assets for both` | Decision 11 |
| `test/asset-names.test.ts` | `make-asset.sh builds a variant for every name in ASSET_NAMES, and no other`; `the Dockerfile fails the build when make-asset.sh fails for any name`; `the Dockerfile builds every name in ASSET_NAMES, and no other` | Decisions 8 and 10 |
| `test/server.test.ts` | `per-channel assets (Phase 4a-0)`: `echoes each channel's resolved asset, defaulting an omitted one to loop`; `streams a channel's named asset, the default for the others and for an undeclared id`; `streams the named asset on the XC /live/ route too`; `streams the named asset on both catch-up layouts too`; `answers 500 naming the file when a named asset is missing, and holds no slot` | Decisions 2 and 11 over HTTP, with two synthetic assets told apart by PID |

`make-asset.sh`'s own checks are the fixtures' shape tests (Decision 8); they run in every `docker build` of the image.

**PR description draft:**

> **Phase 4a-0: e2e-upstream gains the codec fixtures Phase 4a's HLS tests need.** Six short loop assets (MPEG-2 576i + MP2; H.264 1080i + AAC + AC-3; HEVC + AAC; H.264 with a 10 s GOP; H.264 + E-AC-3; H.264 with no audio) and a scenario field choosing a channel's asset. `CONTRACT.md` and the package version move together (1.2.0 → 1.3.0). Spec: `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` § Testing and § 4a-0. Plan: `docs/superpowers/plans/2026-09-27-phase4-4a0-upstream-fixtures.md`.
>
> Each fixture is 20 s at 25 fps with PIDs of its own (`0x200` … `0x700`), a 2 s GOP except the 10 s one, and interlaced fixtures that ffprobe reports as `field_order=tt`. `scripts/make-asset.sh <out> <name>` builds one and then probes it: a stream that is missing, has the wrong codec, layout or field order, or a keyframe out of place fails the image build, naming the stream. The exact shapes are guaranteed in `CONTRACT.md`. The fixtures use no `drawtext`, so 4a-1a can build them with the production ffmpeg too (checked on ffmpeg 5.1.9, 9.0 and 9.0.1).
>
> A channel in `POST /scenarios` may carry `asset`; an omitted one is `loop`, the asset every scenario served before, and the echo carries the resolved name. An unknown name is a `400`. Existing scenarios stream exactly what they did. `test/asset-names.test.ts` holds `ASSET_NAMES`, `make-asset.sh`'s variants and the Dockerfile's build loop to one set.
>
> Tests changed: `test/scenario.test.ts`'s `accepts explicit channel specs verbatim, defaulting a missing categoryId` now also expects `asset: 'loop'` in the echoed channel, because the echo gains that key. Before and after are in the plan.
>
> Break-checks: building the 1080i fixture without its AC-3 track fails the build with `missing stream 2: expected …codec_name=ac3…`; a 2 s GOP on the long-GOP fixture, a progressive MPEG-2, a name missing from the Dockerfile, dropping the Dockerfile loop's `|| exit 1`, ignoring the channel's asset, dropping the door check and a failing ffprobe each redden the check named in the plan.
>
> Follow-ups: ffprobe reports `field_order=unknown` for the progressive `hevc-aac` fixture; ruling R28 treats that as progressive for copy eligibility, and 4a-1a's probe and 4a-1d's copy rule carry it (Refs #525). `h264-gop10-aac` exercises automatic mode's "fewer than 2 keyframes in the probe window" branch, not its 6 s threshold, which 4a-1d pins itself.
>
> Inert for viewers: no Django, relay, frontend or workflow change.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## Tests

### Existing tests changed

One, in `e2e-upstream/test/scenario.test.ts`, because the behaviour it pins (the channel shape `create()` returns) is what this PR changes: every resolved channel now carries `asset`.

- **Before** (`:32`, `:41-43`):
  ```ts
  it('accepts explicit channel specs verbatim, defaulting a missing categoryId', () => {
  ...
    expect(scenario.channels).toEqual([
      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null, categoryId: 1 },
    ]);
  ```
- **After:**
  ```ts
  it('accepts explicit channel specs verbatim, defaulting a missing categoryId and asset', () => {
  ...
    expect(scenario.channels).toEqual([
      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null, categoryId: 1, asset: 'loop' },
    ]);
  ```

The assertion stays a whole-object `toEqual`: it now also fails if `create()` stops defaulting the asset. `test/asset.test.ts:2`'s import line gains four names and asserts nothing new by itself. No other existing test is edited. The echo gains a key and no existing E2E spec deep-compares a channel (`git grep -n "\.channels)\.toEqual" e2e` exits 1), so no consumer changes.

## Overlap

No sibling Phase 4 plan exists yet. 4a-1a's plan should build the fixtures it needs with `e2e-upstream/scripts/make-asset.sh <out> <name>` under the production ffmpeg, or copy them out of the upstream image; either way it reads the shapes from `CONTRACT.md`, not from this plan.

## What this plan does not do

- It does not change `measureLoop()` or `loop`'s seam (Decision 7; § Follow-ups).
- It does not add a declared-but-empty audio PID fixture. 4a-1a's "a declared-but-empty audio PID is not mapped" test (`:1205`) is not in the spec's list of six, so 4a-1a builds that source itself.
- It does not add ffmpeg to the `upstream` CI job or probe fixtures from vitest (Decision 8).
- It adds no E2E spec. The first consumer is 4a-1b.
- It does not close the D6 per-stream identity gap (COVERAGE `:51`).

## Residual risks

- **The 1080i fixture's real-time cost on CI.** Through the relay's software transcode it is the heaviest of the six (1920×1080, 50p out). On the planner's host it ran at 5.5× real time on two threads; a CI runner is slower. No 4a-0 test encodes it, so 4a-1b measures it where it is enforced and, per R29, raises a shortfall as a finding rather than lowering an assertion or shrinking the fixture.
- **An unpinned Debian ffmpeg can drift.** That is why the shapes are asserted rather than the bytes. A drift that breaks a shape fails the image build loudly, naming the stream; it cannot ship a wrong fixture.
- **ffprobe's `hevc` `field_order=unknown`** is measured on three builds, not on every future one. The build does not assert it (Decision 9), so a future ffprobe that says `progressive` changes nothing here.

## Follow-ups

- **For 4a-1a and 4a-1d (Refs #525, ruling R28):** ffprobe reports `field_order=unknown`, not `progressive`, for a progressive HEVC stream in TS (measured on ffmpeg 5.1.9, 8.1.2 and 9.0.1, including the production 9.0 image). R28 rules that `unknown` counts as progressive for copy eligibility and that only an explicit `tt`/`bb`/`tb`/`bt` is interlaced. **4a-1a** owns the probe (D9, `:218`), so its probe type must keep `unknown` distinct (a tri-state, never folded into "interlaced") and its deinterlace decision (D8) must follow R28. **4a-1d** owns the copy rule (`:597`) and the declared-family test (`:1424`, "a copied-HEVC run"), which `hevc-aac` can start only under R28. Issue #525 is the durable hand-off; the PR that lands 4a-1d's copy rule closes it, and this PR does not.
- **For 4a-1d: the 6 s threshold is not pinned by any 4a-0 fixture.** `h264-gop10-aac` (and `loop`) have keyframes 10 s apart, so D9's 8 s probe window never holds two of them and they take the "fewer than 2 keyframes seen" branch. A break-check that moves the K threshold (6 s → 12 s, say) would not redden a test on them. Pinning the threshold needs a source whose GOP is between 6 s and the probe window (7 s, for example), which 4a-1d can build with a local `make-asset.sh`-style ffmpeg command, or a unit row over a probe result.
- **`measureLoop()` overshoots on `loop`:** each 60 s wrap jumps every timestamp forward about 0.68 s, because the span includes the PCR lead and B-frame DTS. Harmless for today's TS consumers; a 4a E2E test that runs automatic copy on `loop` would see an over-long segment at each wrap. A per-PID PTS span would fix it but changes `loop`'s served timeline, so it wants its own PR.
- **4a-1d's E2E should name `h264-noaudio` or `h264-eac3` as "the H.264 asset"**, not `loop` (10 s GOP, Constrained Baseline).

## Review changelog

### Round 1, reviewed at `5cb5c638`

FAIL: four should-fix, three nits. Rulings R28 and R29 followed. Each fix is in Appendix A (regenerated from the scratch worktree, still one byte-exact diff against `6c985473`) and re-measured.

1. **The Dockerfile's `|| exit 1` was unpinned** (should-fix). `test/asset-names.test.ts` gains `the Dockerfile fails the build when make-asset.sh fails for any name`, and BC7 is now a real break-check with its message quoted verbatim.
2. **CONTRACT.md claimed catch-up routing no test enforced** (should-fix). `test/server.test.ts` gains `streams the named asset on both catch-up layouts too` (PATH and QUERY). It passes, and BC5 now reddens four tests, the PATH catch-up one included.
3. **`h264-gop10-aac` was said to exercise "K > 6 s"** (should-fix). The Consumers rows now say it takes the "fewer than 2 keyframes in the probe window" branch under D9's 8 s bound, and § Follow-ups tells 4a-1d that the 6 s threshold needs a source of its own.
4. **The HEVC `field_order=unknown` hand-off named only 4a-1d and lived only in this plan** (should-fix). Per R28 it is addressed to 4a-1a (probe representation) and 4a-1d (copy rule), with issue #525 as the durable record ("Refs #525" here and in the PR-description draft, never a closing keyword).
5. **`probe_streams` could fail silently** (nit). `actual="$(probe_streams)" || fail "ffprobe could not list the streams of ${OUT}"`, pinned by BC8.
6. **1080i versus "SD"** (nit). Recorded as R29 in Decision 3.
7. **The echo type's `asset` was optional** (nit). `UpstreamScenario.channels` is `(UpstreamChannel & { asset: UpstreamAsset })[]`, and the e2e package's `tsc` is clean.

Re-measured: vitest 294 in 17 files (seed 277 in 16); `npm run typecheck` 0; e2e `tsc --noEmit` 0; `guards` 49/49; all six fixtures rebuilt on Homebrew ffmpeg 9.0.1, and the image's asset stage rebuilt natively on bookworm (exit 0); BC4, BC5, BC7 and BC8 re-run. `git apply --check --whitespace=error` passes at the seed.

### Round 2 PASS at `c97f790c`; nit N1 applied

N1: § Residual risks' first bullet now follows R29 (4a-1b measures the real-time cost where it is enforced and raises a shortfall as a finding), in place of "the lever is 4a-1b's timeouts". Plan text only; Appendix A is unchanged.

## Appendix A: PR 4a-0, against the seed `6c985473`

Produced by `git diff 6c985473` in a scratch worktree detached at the seed, after `git add -N e2e-upstream/test/asset-names.test.ts` (15 files, 757 insertions, 63 deletions). `git apply --check --whitespace=error` passes against a clean checkout of the seed.

<!-- appendix-A-begin -->
```diff
diff --git a/e2e-upstream/CONTRACT.md b/e2e-upstream/CONTRACT.md
index d7812bba..db785d33 100644
--- a/e2e-upstream/CONTRACT.md
+++ b/e2e-upstream/CONTRACT.md
@@ -1,6 +1,6 @@
 # `e2e-upstream` contract
 
-**Version:** 1.2.0
+**Version:** 1.3.0
 
 **An unlisted behaviour is not a guarantee.** If it isn't named below, a
 consumer test must not depend on it, however consistently it happens to
@@ -24,13 +24,16 @@ Everything under `e2e-upstream/src/` reachable over HTTP: `POST`/`GET`/
 `e2e-upstream/scripts/` (asset generation) and `e2e-upstream/test/` (the
 package's own vitest suite) are covered only insofar as their behaviour is
 observable through those routes — the build scripts' internals and the test
-suite's own assertions are not themselves part of this contract.
+suite's own assertions are not themselves part of this contract. The one
+exception is the codec fixtures' stream shapes (see "Guarantees"), which
+`scripts/make-asset.sh` asserts when the image is built.
 
 ## Guarantees
 
-Every item below is enforced today by `e2e-upstream/test/*.test.ts` (see
-"Enforcement"), and is safe for a consumer test to depend on. Each links to
-the README section that documents the mechanism.
+Every item below is enforced today by `e2e-upstream/test/*.test.ts`, except
+the codec fixtures' shapes, which `scripts/make-asset.sh` enforces when the
+image is built (see "Enforcement"), and is safe for a consumer test to
+depend on. Each links to the README section that documents the mechanism.
 
 - **Real per-scenario connection accounting.** `ConnectionRegistry.tryAcquire`
   (`src/connections.ts`) admits or rejects before any response header is
@@ -65,6 +68,34 @@ the README section that documents the mechanism.
   catch-up request carried, in both layouts. See "Catch-up" below and in the
   README — this is a narrower guarantee than it may first read as; see the
   matching non-guarantee.
+- **A scenario channel streams the asset it names** (Phase 4a-0). A channel
+  in `POST /scenarios`'s `channels` array may carry `asset`, one of the seven
+  names in `ASSET_NAMES` (`src/asset.ts`); an omitted `asset` resolves to
+  `loop`, the asset every scenario served before 1.3.0, and the echo carries
+  the resolved `asset` on every channel. An unknown name is a `400` naming the
+  channel and the valid names. The plain stream route, `/live/` and both
+  catch-up routes all serve the channel's asset; a channel id the scenario
+  does not declare (which the plain route still serves) gets `loop`. See "The
+  codec fixtures" in the README.
+- **Each codec fixture has exactly the streams below, in this order, and
+  nothing else.** Every one is 20 s at 25 frames per second (500 video
+  frames), and its first frame is a keyframe. `scripts/make-asset.sh` probes
+  each fixture with ffprobe after writing it and fails the image build,
+  naming the stream, if any listed property differs; so an image that exists
+  has these shapes, whatever its ffmpeg version.
+
+  | `asset` | Video | Audio | PIDs |
+  |---|---|---|---|
+  | `mpeg2-576i-mp2` | MPEG-2 Main, 720×576, interlaced top field first (`field_order=tt`), keyframe every 2 s | MP2, stereo, 48 kHz | `0x200`, `0x201` |
+  | `h264-1080i-aac-ac3` | H.264 High, 1920×1080, interlaced top field first, keyframe every 2 s | AAC-LC stereo 48 kHz, then AC-3 5.1(side) 48 kHz | `0x300`, `0x301`, `0x302` |
+  | `hevc-aac` | HEVC Main (8-bit, `yuv420p`), 640×360, progressive, keyframe every 2 s | AAC-LC, stereo, 48 kHz | `0x400`, `0x401` |
+  | `h264-gop10-aac` | H.264 High, 640×360, progressive, keyframe every **10 s** | AAC-LC, stereo, 48 kHz | `0x500`, `0x501` |
+  | `h264-eac3` | H.264 High, 640×360, progressive, keyframe every 2 s | E-AC-3 5.1(side) 48 kHz, and no other audio | `0x600`, `0x601` |
+  | `h264-noaudio` | H.264 High, 640×360, progressive, keyframe every 2 s | **none**: the PMT declares no audio stream | `0x700` |
+
+  "Progressive" is by construction. ffprobe reports `field_order=progressive`
+  for the three H.264 ones, but `unknown` for `hevc-aac`, so the build does
+  not check that property there.
 - **The asset's loop duration and packet count are measured, never
   hardcoded**, so a drifted build-time ffmpeg cannot silently desynchronise
   the server from the asset it serves. See "The asset" in the README. This is
@@ -159,11 +190,14 @@ test can prove Dispatcharr does *not* rely on them either.
   request, so `appliedTo: 0` is their correct, expected result — not a sign
   the fault failed to apply. See `FaultStore.apply` (`src/faults.ts`).
 - **The TS asset carries no per-stream identity (spec D6).** `getAsset()`
-  (`src/server.ts`) serves one shared file to every channel and every
-  scenario; the mux is built with fixed PIDs (`scripts/make-asset.sh`'s
-  `-mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257`, i.e. video
-  `0x100`, audio `0x101`), so no two channels' byte streams can be told
-  apart by content. The burned-in frame counter is, in `make-asset.sh`'s own
+  (`src/server.ts`) serves one shared file per asset name to every channel
+  and every scenario that names it; the default `loop` is built with fixed
+  PIDs (`scripts/make-asset.sh`'s `-mpegts_start_pid 0x100 -streamid 0:256
+  -streamid 1:257`, i.e. video `0x100`, audio `0x101`), so no two channels
+  on the same asset can be told apart by content. Channels on *different*
+  assets differ in codecs and PIDs, but that is the asset's identity, not the
+  channel's, and the locked FFmpeg profile's remux rewrites the PIDs anyway.
+  The burned-in frame counter is, in `make-asset.sh`'s own
   words, "a human debugging aid only … no test asserts on it" — no consumer
   test may start asserting on it either. Building per-stream identity is
   feasible under the Proxy stream profile (a dedicated marker PID injected in
@@ -172,14 +206,23 @@ test can prove Dispatcharr does *not* rely on them either.
   lets the mpegts muxer rewrite PAT/PMT/PIDs itself; this is a provider
   capability nobody has built (see `e2e/COVERAGE.md`'s Streaming Gap row for
   this goal), not a guarantee this document can make today.
-- **Neither generated asset's exact size, packet count or duration may be
+- **No generated asset's exact size, packet count or duration may be
   hardcoded anywhere.** `scripts/make-asset.sh` and `make-vod-asset.sh`
   deliberately run an unpinned Debian ffmpeg; both scripts assert only shape
-  (TS-packet-aligned and sync-byte-prefixed; at least 1 KB and `ftyp`-prefixed
+  (TS-packet-aligned and sync-byte-prefixed, plus each codec fixture's streams
+  and keyframe spacing above; at least 1 KB and `ftyp`-prefixed
   respectively), not a byte-reproducible artifact. `measureLoop`
   (`src/asset.ts`) measures the loop duration from the asset at server
   startup for the same reason. A version drift in ffmpeg is expected to
-  change these numbers.
+  change these numbers. A codec fixture's 500 frames are guaranteed; its
+  size and its container duration are not.
+- **The loop seam is not frame-exact.** `measureLoop` spans every PCR, PTS
+  and DTS in the file and adds one mean step, which comes out slightly longer
+  than the media, so each wrap moves every timestamp forward by that excess:
+  measured at 35–81 ms on the six codec fixtures (built with `-muxdelay 0`
+  for this reason) and about 0.68 s on `loop`. Timestamps still only ever
+  increase across the seam. A test must not assume the video's frame
+  interval is constant across a wrap.
 - **The pacing rate is only approximate above 1×.** `streamLoop` sleeps
   per-chunk against that chunk's own size, not a cumulative target — the
   README records rate `10` measuring roughly `8.1×`, not `10×`. Assert an
@@ -213,6 +256,13 @@ and the README, never from the implementation.
 it to hold an M3U refresh in flight across a `relay-uwsgi` restart instead of
 contending decoy accounts against a large catalogue (#197).
 
+The channel `asset` field and the six codec fixtures (1.3.0) have no
+consumer yet. Their planned consumers are Phase 4a's HLS work
+(`docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`
+§ Testing): 4a-1a's real-ffmpeg packager tests, which may build the fixtures
+themselves with `scripts/make-asset.sh <out> <name>`, and the `streaming` and
+`frontend` project specs of 4a-1b, 4a-1c, 4a-1d and 4a-2.
+
 `e2e-upstream`'s own `test/*.test.ts` (vitest) is not a consumer in this
 sense — it is the thing that keeps this document honest (see "Enforcement").
 
@@ -250,13 +300,20 @@ existing guarantee changes, and every existing consumer keeps working
 unmodified. `package-lock.json`'s stale `1.0.0` — pre-existing drift the
 guard below does not read — is corrected in the same PR.
 
+**This landing is 1.3.0, a minor bump from 1.2.0.** It adds the optional
+channel `asset` field and six named codec fixtures (Phase 4a-0), and makes
+the fixtures' shapes a guarantee. That is a backward-compatible addition by
+the rule above: an omitted `asset` resolves to `loop`, the file every
+scenario served before, and the echo gains a key rather than changing one.
+
 ## Enforcement
 
-Two different things are enforced, at two different levels, and neither
-substitutes for the other:
+Three different things are enforced, at three different levels, and none
+substitutes for another:
 
 - **That the guarantees and non-guarantees above are actually true of the
-  running provider** is enforced by `e2e-upstream/test/*.test.ts` (vitest) —
+  running provider**, the codec fixtures' shapes aside (see the last item),
+  is enforced by `e2e-upstream/test/*.test.ts` (vitest) —
   it is the semantic check, and it existed before this document did. This
   document is a claim about what that suite (and the consumer specs that
   build on it) already prove; it does not add new runtime assertions of its
@@ -270,3 +327,12 @@ substitutes for the other:
   this document, or a documented version that doesn't match `package.json`,
   fails it immediately. Verified by mutation; see `e2e/COVERAGE.md`'s Guards
   table for the exact mutation and its output.
+- **That each codec fixture has the shape "Guarantees" lists** is enforced
+  when the image is built, not by vitest: `scripts/make-asset.sh` probes each
+  fixture it writes and exits non-zero naming the missing, wrong or
+  unexpected stream, or the keyframe that is out of place, which fails
+  `docker build` (the `build` job of `e2e-tests.yml`). vitest has no ffmpeg
+  and cannot see the files. What it does check, in
+  `test/asset-names.test.ts`, is that `ASSET_NAMES`, `make-asset.sh`'s
+  variants and the Dockerfile's build loop name the same seven assets, so the
+  door never accepts a name the image lacks.
diff --git a/e2e-upstream/Dockerfile b/e2e-upstream/Dockerfile
index 06978384..9f4b93fb 100644
--- a/e2e-upstream/Dockerfile
+++ b/e2e-upstream/Dockerfile
@@ -4,9 +4,16 @@ RUN apt-get update \
  && rm -rf /var/lib/apt/lists/*
 WORKDIR /build
 COPY scripts/make-asset.sh scripts/make-vod-asset.sh ./
+# One TS asset per name in src/asset.ts's ASSET_NAMES: `loop`, the default,
+# and Phase 4a's six codec fixtures, each shape-checked by make-asset.sh
+# itself. test/asset-names.test.ts holds this list to ASSET_NAMES. `|| exit 1`
+# because `sh -c` has no `-e`, and a loop's status is only its last command's.
 RUN chmod +x make-asset.sh make-vod-asset.sh \
- && ./make-asset.sh /build/loop.ts \
- && ./make-vod-asset.sh /build/vod.mp4
+ && mkdir /build/assets \
+ && for name in loop mpeg2-576i-mp2 h264-1080i-aac-ac3 hevc-aac h264-gop10-aac h264-eac3 h264-noaudio; do \
+      ./make-asset.sh "/build/assets/${name}.ts" "${name}" || exit 1; \
+    done \
+ && ./make-vod-asset.sh /build/assets/vod.mp4
 
 FROM node:24-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build
 WORKDIR /app
@@ -22,9 +29,9 @@ RUN npx tsc
 FROM node:24-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS runtime
 WORKDIR /app
 COPY --from=build /app/dist ./dist
-COPY --from=asset /build/loop.ts /app/assets/loop.ts
-COPY --from=asset /build/vod.mp4 /app/assets/vod.mp4
+COPY --from=asset /build/assets/ /app/assets/
 ENV UPSTREAM_ASSET=/app/assets/loop.ts
+ENV UPSTREAM_ASSET_DIR=/app/assets
 ENV UPSTREAM_VOD_ASSET=/app/assets/vod.mp4
 EXPOSE 8080
 CMD ["node", "dist/index.js"]
diff --git a/e2e-upstream/README.md b/e2e-upstream/README.md
index 4477bda9..e917bc92 100644
--- a/e2e-upstream/README.md
+++ b/e2e-upstream/README.md
@@ -63,7 +63,7 @@ immediately, never a 300s timeout.
 
 | Method | Path | Purpose |
 |---|---|---|
-| `POST` | `/scenarios` | Create. Body declares catalogue, optional credentials, `maxConnections` (default unlimited), `rate` (default 1). Returns **201** with the whole resolved scenario, not just the four keys you sent: `{ id, internal, control, channels }` plus the **resolved catalogue** — `vod`, `series`, the category lists, and any defaults the parser filled in. That echo is what makes the count form usable: declare `series: 2` and the response carries the generated series and **episode** ids, which you need for `/series/.../<id>.<ext>` and cannot construct yourself. `UpstreamScenario` (`e2e/fixtures/upstream.ts`) types those fields, so they are reachable without opening `src/` |
+| `POST` | `/scenarios` | Create. Body declares catalogue, optional credentials, `maxConnections` (default unlimited), `rate` (default 1); a channel's optional `asset` picks what its stream serves (see "The codec fixtures"). Returns **201** with the whole resolved scenario, not just the four keys you sent: `{ id, internal, control, channels }` plus the **resolved catalogue** — `vod`, `series`, the category lists, and any defaults the parser filled in. That echo is what makes the count form usable: declare `series: 2` and the response carries the generated series and **episode** ids, which you need for `/series/.../<id>.<ext>` and cannot construct yourself. `UpstreamScenario` (`e2e/fixtures/upstream.ts`) types those fields, so they are reachable without opening `src/` |
 | `GET` | `/scenarios` | List live scenarios. Also the readiness endpoint `e2e_up.sh` waits on |
 | `DELETE` | `/scenarios/<id>` | Optional explicit close |
 | `POST` | `/s/<id>/fault` | Apply or clear a fault. Body takes an optional `channel` filter and per-fault parameters. Returns `{ fault, active, appliedTo }` |
@@ -376,14 +376,40 @@ duration and packet count are **measured from the asset at server startup**, nev
 version drift in ffmpeg is expected to change those numbers; nothing in this codebase or in a
 consuming test may assume a specific duration or packet count.
 
-`scripts/make-asset.sh` is not runnable on macOS outside the Docker build — it uses a `drawtext`
-filter that Homebrew's ffmpeg build typically lacks. It only ever runs against Debian's ffmpeg, in
-the builder stage.
+`scripts/make-asset.sh` with no variant (the `loop` asset) is not runnable on macOS outside the
+Docker build — it uses a `drawtext` filter that Homebrew's ffmpeg build typically lacks. It only
+ever runs against Debian's ffmpeg, in the builder stage. The codec fixtures below use no
+`drawtext` and build with any ffmpeg that has libx264 and libx265.
 
 A frame counter is burned into the video. It is a **human debugging aid only**, for eyeballing a
 captured TS artifact in a video player after a test failure — nothing in this suite decodes video
 or asserts on it.
 
+## The codec fixtures
+
+Phase 4a's HLS tests need sources the `loop` asset is not: interlaced, MPEG-2, HEVC, a long GOP,
+AC-3, E-AC-3, and no audio at all. Six more looping TS assets cover them, built beside `loop` by
+`scripts/make-asset.sh <out.ts> <name>` at image build time and served from `/app/assets/<name>.ts`
+(`UPSTREAM_ASSET_DIR`). A scenario channel picks one by name:
+
+```json
+{ "channels": [
+    { "id": 1, "name": "Interlaced", "tvgId": "i.e2e", "logo": null, "asset": "h264-1080i-aac-ac3" },
+    { "id": 2, "name": "Default", "tvgId": "d.e2e", "logo": null }
+] }
+```
+
+An omitted `asset` is `loop`, and the echo always carries the resolved name; an unknown one is a
+`400`. The count form (`channels: 3`) gives every channel `loop`. The names, and each fixture's
+exact streams, PIDs and keyframe spacing, are in `CONTRACT.md`'s "Guarantees": that table is the
+promise, and `make-asset.sh` fails the image build if a fixture does not match it. Each fixture is
+20 s at 25 frames per second with PIDs of its own, so two fixtures fed one after the other really
+do change PIDs, as two providers' streams would.
+
+Channels on different fixtures are distinguishable by codec and PID; channels on the same fixture
+are not (the D6 non-guarantee in `CONTRACT.md`). Nothing in this package decodes the video:
+`testsrc2` pictures and sine tones carry no frame counter or marker to assert on.
+
 ## The VOD asset
 
 `/movie/<user>/<pass>/<id>.<ext>` and `/series/<user>/<pass>/<id>.<ext>` (G8) serve a **second,
diff --git a/e2e-upstream/package-lock.json b/e2e-upstream/package-lock.json
index a2538ce2..67a6138c 100644
--- a/e2e-upstream/package-lock.json
+++ b/e2e-upstream/package-lock.json
@@ -1,12 +1,12 @@
 {
   "name": "dispatcharr-e2e-upstream",
-  "version": "1.2.0",
+  "version": "1.3.0",
   "lockfileVersion": 3,
   "requires": true,
   "packages": {
     "": {
       "name": "dispatcharr-e2e-upstream",
-      "version": "1.2.0",
+      "version": "1.3.0",
       "devDependencies": {
         "@types/node": "24.0.0",
         "typescript": "5.7.2",
diff --git a/e2e-upstream/package.json b/e2e-upstream/package.json
index 8c9c337b..41fb894f 100644
--- a/e2e-upstream/package.json
+++ b/e2e-upstream/package.json
@@ -1,7 +1,7 @@
 {
   "name": "dispatcharr-e2e-upstream",
   "private": true,
-  "version": "1.2.0",
+  "version": "1.3.0",
   "type": "module",
   "scripts": {
     "build": "tsc",
diff --git a/e2e-upstream/scripts/make-asset.sh b/e2e-upstream/scripts/make-asset.sh
index 267d12aa..f357550e 100755
--- a/e2e-upstream/scripts/make-asset.sh
+++ b/e2e-upstream/scripts/make-asset.sh
@@ -1,25 +1,253 @@
 #!/usr/bin/env bash
-# Generate the looping MPEG-TS asset. Build-time only: ffmpeg is confined to
+# Generate a looping MPEG-TS asset. Build-time only: ffmpeg is confined to
 # the Docker builder stage so the runtime image, and this repo, carry neither
 # ffmpeg nor a version of it that could drift from CI's.
+#
+#   make-asset.sh <output.ts>              the default loop (`loop`)
+#   make-asset.sh <output.ts> <variant>    one of the Phase 4a codec fixtures
+#
+# The variants are the six codec fixtures of the Phase 4 spec's § Testing
+# (docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md, 4a-0);
+# src/asset.ts's ASSET_NAMES lists the same seven names, and
+# test/asset-names.test.ts holds this file, that list and the Dockerfile to
+# one set. Each variant is 20 s at 25 frames per second with PIDs of its own,
+# and is checked after it is written: `check_shape` compares every stream
+# ffprobe reports against the variant's expected shape, and `check_gop` the
+# video's keyframe spacing. A variant whose shape drifts fails the image
+# build, naming the stream, instead of shipping a fixture that silently tests
+# something else. The expected shapes are what CONTRACT.md guarantees.
+#
+# The variants use no drawtext, so they build with any ffmpeg that has
+# libx264 and libx265 (Homebrew's included); `loop` still needs drawtext.
 set -euo pipefail
 
-OUT="${1:?usage: make-asset.sh <output.ts>}"
-DURATION="${ASSET_DURATION_SECONDS:-60}"
-FPS="${ASSET_FPS:-25}"
-BITRATE="${ASSET_BITRATE:-2000k}"
-
-# The burned-in frame counter is a human debugging aid only — for eyeballing a
-# captured TS in VLC after a failure. Nothing in the test runner decodes video,
-# so no test asserts on it.
-ffmpeg -hide_banner -loglevel error -y \
-  -f lavfi -i "testsrc=size=640x360:rate=${FPS}:duration=${DURATION}" \
-  -f lavfi -i "sine=frequency=440:duration=${DURATION}" \
-  -vf "drawtext=text='%{frame_num}':x=10:y=10:fontsize=48:fontcolor=white:box=1:boxcolor=black" \
-  -c:v libx264 -preset ultrafast -b:v "${BITRATE}" -pix_fmt yuv420p \
-  -c:a aac -b:a 128k \
-  -mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257 \
-  -f mpegts "${OUT}"
+OUT="${1:?usage: make-asset.sh <output.ts> [variant]}"
+VARIANT="${2:-loop}"
+
+PACKET_SIZE=188
+# Every variant: 20 s at 25 frames per second (500 frames), one loop.
+VARIANT_SECONDS=20
+VARIANT_FPS=25
+VARIANT_FRAMES=$((VARIANT_SECONDS * VARIANT_FPS))
+
+# A fixture that fails its check is deleted, so a caller that ignores the
+# exit status is left with no file rather than a wrong one.
+fail() {
+  echo "make-asset.sh: ${VARIANT}: $*" >&2
+  rm -f -- "${OUT}"
+  exit 1
+}
+
+# One ffprobe line per stream, in stream order: `index=N|key=value|...`.
+# ffprobe lists every stream twice for a TS, once inside its program and once
+# at top level, as `program|stream|index=...`, `stream|index=...` or a bare
+# continuation line; the section prefixes are stripped and the duplicates
+# dropped, which leaves one line per stream in index order.
+probe_streams() {
+  ffprobe -v error \
+    -show_entries stream=index,id,codec_type,codec_name,profile,pix_fmt,field_order,width,height,r_frame_rate,sample_rate,channels,channel_layout \
+    -of compact "${OUT}" \
+    | sed -E 's/^(program[|])?(stream[|])?//' \
+    | grep '^index=' \
+    | awk '!seen[$0]++'
+}
+
+# Compares the probed streams against the expected lines given as arguments,
+# one per stream in order, each a `|`-joined list of `key=value` pairs that
+# must all appear in that stream's probe line. Names the missing, wrong or
+# unexpected stream.
+check_shape() {
+  local actual line
+  local -a lines=()
+  actual="$(probe_streams)" || fail "ffprobe could not list the streams of ${OUT}"
+  while IFS= read -r line; do
+    [ -n "${line}" ] && lines+=("${line}")
+  done <<< "${actual}"
+
+  local index=0 expected pair
+  for expected in "$@"; do
+    if [ "${index}" -ge "${#lines[@]}" ]; then
+      fail "missing stream ${index}: expected ${expected}, but the asset has only ${#lines[@]} stream(s)"
+    fi
+    for pair in $(printf '%s' "${expected}" | tr '|' ' '); do
+      case "|${lines[${index}]}|" in
+        *"|${pair}|"*) ;;
+        *) fail "stream ${index}: expected ${pair}, found ${lines[${index}]}" ;;
+      esac
+    done
+    index=$((index + 1))
+  done
+
+  if [ "${#lines[@]}" -gt "${index}" ]; then
+    fail "unexpected stream ${index}: ${lines[${index}]} (expected exactly ${index} stream(s))"
+  fi
+}
+
+# Asserts the first video stream has exactly VARIANT_FRAMES frames, starts on
+# a keyframe, and has a keyframe exactly every <gop-seconds>, and no other.
+check_gop() {
+  local gop_seconds="$1"
+  local gop_frames=$((gop_seconds * VARIANT_FPS))
+  local expected_keyframes=$((VARIANT_FRAMES / gop_frames))
+  # Packets in decode order, `<pts>,<flags>`; frame indices in display order
+  # come from sorting by pts. ffprobe 5.1 (Debian bookworm, the image build)
+  # prints a blank line after every packet and ffprobe 9 does not, so blank
+  # lines are dropped before anything is counted.
+  local verdict
+  verdict="$(
+    ffprobe -v error -select_streams v:0 -show_entries packet=pts,flags -of csv=p=0 "${OUT}" \
+      | grep -v '^[[:space:]]*$' \
+      | sort -t, -k1,1n \
+      | awk -F, -v frames="${VARIANT_FRAMES}" -v gop="${gop_frames}" -v want="${expected_keyframes}" '
+          { if (index($2, "K") > 0) { keys[k++] = NR - 1 } }
+          END {
+            if (NR != frames) { printf "has %d video frames, expected %d", NR, frames; exit 1 }
+            if (k != want) { printf "has %d keyframes, expected %d (one every %d frames)", k, want, gop; exit 1 }
+            for (i = 0; i < k; i++) {
+              if (keys[i] != i * gop) { printf "keyframe %d is at frame %d, expected frame %d", i, keys[i], i * gop; exit 1 }
+            }
+          }'
+  )" || fail "video stream 0 ${verdict}; expected one keyframe every ${gop_seconds} s"
+}
+
+# Shared by every variant. `-t` cuts every stream at 20 s. `-muxdelay 0
+# -muxpreload 0` start the PCR at the first DTS instead of 0.7 s ahead of it:
+# src/asset.ts's measureLoop() spans every PCR, PTS and DTS it sees, so the
+# default lead would add ~0.7 s of dead time at every loop seam, and a 20 s
+# loop would jump its timestamps forward 0.7 s three times a minute.
+TIMING=(-t "${VARIANT_SECONDS}" -muxdelay 0 -muxpreload 0)
+X264_GOP_2S=(-g 50 -keyint_min 50 -sc_threshold 0)
+STEREO_SINE=(-f lavfi -i "sine=frequency=440:sample_rate=48000:duration=${VARIANT_SECONDS}")
+# Six channels, each its own tone, so a downmix is audible as a downmix.
+SURROUND_51=(-f lavfi -i "aevalsrc=exprs=sin(440*2*PI*t)|sin(550*2*PI*t)|sin(660*2*PI*t)|sin(110*2*PI*t)|sin(770*2*PI*t)|sin(880*2*PI*t):channel_layout=5.1(side):sample_rate=48000:duration=${VARIANT_SECONDS}")
+
+case "${VARIANT}" in
+  loop)
+    DURATION="${ASSET_DURATION_SECONDS:-60}"
+    FPS="${ASSET_FPS:-25}"
+    BITRATE="${ASSET_BITRATE:-2000k}"
+    # The burned-in frame counter is a human debugging aid only — for eyeballing a
+    # captured TS in VLC after a failure. Nothing in the test runner decodes video,
+    # so no test asserts on it.
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc=size=640x360:rate=${FPS}:duration=${DURATION}" \
+      -f lavfi -i "sine=frequency=440:duration=${DURATION}" \
+      -vf "drawtext=text='%{frame_num}':x=10:y=10:fontsize=48:fontcolor=white:box=1:boxcolor=black" \
+      -c:v libx264 -preset ultrafast -b:v "${BITRATE}" -pix_fmt yuv420p \
+      -c:a aac -b:a 128k \
+      -mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257 \
+      -f mpegts "${OUT}"
+    ;;
+
+  mpeg2-576i-mp2)
+    # 576i25: a 50 fps progressive source woven into top-field-first frames,
+    # so the two fields of a frame really are 20 ms apart.
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc2=size=720x576:rate=50:duration=${VARIANT_SECONDS}" \
+      "${STEREO_SINE[@]}" \
+      -map 0:v -map 1:a -vf "interlace=scan=tff" \
+      -c:v mpeg2video -flags +ildct+ilme -b:v 4000k -g 50 -bf 0 \
+      -c:a mp2 -b:a 192k -ac 2 \
+      "${TIMING[@]}" \
+      -mpegts_start_pid 0x200 -streamid 0:512 -streamid 1:513 \
+      -f mpegts "${OUT}"
+    check_shape \
+      "index=0|id=0x200|codec_type=video|codec_name=mpeg2video|profile=Main|pix_fmt=yuv420p|field_order=tt|width=720|height=576|r_frame_rate=25/1" \
+      "index=1|id=0x201|codec_type=audio|codec_name=mp2|sample_rate=48000|channels=2|channel_layout=stereo"
+    check_gop 2
+    ;;
+
+  h264-1080i-aac-ac3)
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc2=size=1920x1080:rate=50:duration=${VARIANT_SECONDS}" \
+      "${STEREO_SINE[@]}" \
+      "${SURROUND_51[@]}" \
+      -map 0:v -map 1:a -map 2:a -vf "interlace=scan=tff" \
+      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -flags +ildct+ilme -x264-params tff=1 \
+      -b:v 6000k "${X264_GOP_2S[@]}" \
+      -c:a:0 aac -b:a:0 128k -ac:a:0 2 \
+      -c:a:1 ac3 -b:a:1 448k \
+      "${TIMING[@]}" \
+      -mpegts_start_pid 0x300 -streamid 0:768 -streamid 1:769 -streamid 2:770 \
+      -f mpegts "${OUT}"
+    check_shape \
+      "index=0|id=0x300|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=tt|width=1920|height=1080|r_frame_rate=25/1" \
+      "index=1|id=0x301|codec_type=audio|codec_name=aac|profile=LC|sample_rate=48000|channels=2|channel_layout=stereo" \
+      "index=2|id=0x302|codec_type=audio|codec_name=ac3|sample_rate=48000|channels=6|channel_layout=5.1(side)"
+    check_gop 2
+    ;;
+
+  hevc-aac)
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
+      "${STEREO_SINE[@]}" \
+      -map 0:v -map 1:a \
+      -c:v libx265 -preset ultrafast -pix_fmt yuv420p -b:v 1000k \
+      -x265-params "log-level=error:keyint=50:min-keyint=50:scenecut=0" \
+      -c:a aac -b:a 128k -ac 2 \
+      "${TIMING[@]}" \
+      -mpegts_start_pid 0x400 -streamid 0:1024 -streamid 1:1025 \
+      -f mpegts "${OUT}"
+    # No field_order pair: ffprobe reports `unknown` for this progressive
+    # HEVC stream (measured on ffmpeg 5.1.9, 8.1.2 and 9.0.1), not
+    # `progressive`, so asserting either would pin an ffprobe quirk.
+    check_shape \
+      "index=0|id=0x400|codec_type=video|codec_name=hevc|profile=Main|pix_fmt=yuv420p|width=640|height=360|r_frame_rate=25/1" \
+      "index=1|id=0x401|codec_type=audio|codec_name=aac|profile=LC|sample_rate=48000|channels=2|channel_layout=stereo"
+    check_gop 2
+    ;;
+
+  h264-gop10-aac)
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
+      "${STEREO_SINE[@]}" \
+      -map 0:v -map 1:a \
+      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -b:v 1500k \
+      -g 250 -keyint_min 250 -sc_threshold 0 \
+      -c:a aac -b:a 128k -ac 2 \
+      "${TIMING[@]}" \
+      -mpegts_start_pid 0x500 -streamid 0:1280 -streamid 1:1281 \
+      -f mpegts "${OUT}"
+    check_shape \
+      "index=0|id=0x500|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=progressive|width=640|height=360|r_frame_rate=25/1" \
+      "index=1|id=0x501|codec_type=audio|codec_name=aac|profile=LC|sample_rate=48000|channels=2|channel_layout=stereo"
+    check_gop 10
+    ;;
+
+  h264-eac3)
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
+      "${SURROUND_51[@]}" \
+      -map 0:v -map 1:a \
+      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -b:v 1500k "${X264_GOP_2S[@]}" \
+      -c:a eac3 -b:a 384k \
+      "${TIMING[@]}" \
+      -mpegts_start_pid 0x600 -streamid 0:1536 -streamid 1:1537 \
+      -f mpegts "${OUT}"
+    check_shape \
+      "index=0|id=0x600|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=progressive|width=640|height=360|r_frame_rate=25/1" \
+      "index=1|id=0x601|codec_type=audio|codec_name=eac3|sample_rate=48000|channels=6|channel_layout=5.1(side)"
+    check_gop 2
+    ;;
+
+  h264-noaudio)
+    ffmpeg -hide_banner -loglevel error -y \
+      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
+      -map 0:v \
+      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -b:v 1500k "${X264_GOP_2S[@]}" \
+      "${TIMING[@]}" \
+      -mpegts_start_pid 0x700 -streamid 0:1792 \
+      -f mpegts "${OUT}"
+    check_shape \
+      "index=0|id=0x700|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=progressive|width=640|height=360|r_frame_rate=25/1"
+    check_gop 2
+    ;;
+
+  *)
+    echo "make-asset.sh: unknown variant '${VARIANT}'" >&2
+    exit 2
+    ;;
+esac
 
 # ffmpeg's apt version is deliberately unpinned above — Debian point releases
 # vanish from the archive, and pinning one would break this build for a
@@ -29,7 +257,6 @@ ffmpeg -hide_banner -loglevel error -y \
 # a version drift is expected to change them, and they are measured from the
 # asset at startup (see Task 5's measureLoop()), not baked in as constants.
 SIZE="$(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}")"
-PACKET_SIZE=188
 
 if [ "$((SIZE % PACKET_SIZE))" -ne 0 ]; then
   echo "make-asset.sh: ${OUT} is ${SIZE} bytes, not a multiple of ${PACKET_SIZE} — ffmpeg did not produce a clean TS packet stream" >&2
@@ -44,4 +271,4 @@ fi
 
 PACKETS=$((SIZE / PACKET_SIZE))
 ACTUAL_DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${OUT}")"
-echo "Wrote ${OUT} (${SIZE} bytes, ${PACKETS} packets, ${ACTUAL_DURATION}s)"
+echo "Wrote ${OUT} (${VARIANT}, ${SIZE} bytes, ${PACKETS} packets, ${ACTUAL_DURATION}s)"
diff --git a/e2e-upstream/src/asset.ts b/e2e-upstream/src/asset.ts
index 78971793..a22159cd 100644
--- a/e2e-upstream/src/asset.ts
+++ b/e2e-upstream/src/asset.ts
@@ -1,4 +1,5 @@
 import { readFileSync } from 'node:fs';
+import { join } from 'node:path';
 import {
   TS_PACKET_SIZE,
   hasPayload,
@@ -8,6 +9,44 @@ import {
   readTimestamp,
 } from './ts.js';
 
+/**
+ * Every looping TS asset a scenario channel may name (`ChannelSpec.asset`).
+ * `loop` is the 60 s H.264 + AAC loop every scenario served before Phase
+ * 4a-0, and stays the default. The other six are 4a-0's codec fixtures, each
+ * built and shape-checked by `scripts/make-asset.sh <out> <name>` at image
+ * build time; CONTRACT.md states each one's shape. `test/asset-names.test.ts`
+ * holds this list, make-asset.sh's variants and the Dockerfile's build loop
+ * to one set, so a name the door accepts is always a file the image has.
+ */
+export const ASSET_NAMES = [
+  'loop',
+  'mpeg2-576i-mp2',
+  'h264-1080i-aac-ac3',
+  'hevc-aac',
+  'h264-gop10-aac',
+  'h264-eac3',
+  'h264-noaudio',
+] as const;
+
+export type AssetName = (typeof ASSET_NAMES)[number];
+
+export const DEFAULT_ASSET: AssetName = 'loop';
+
+export function isAssetName(value: unknown): value is AssetName {
+  return typeof value === 'string' && (ASSET_NAMES as readonly string[]).includes(value);
+}
+
+/**
+ * Where `name` lives on disk. `loop` keeps its own variable,
+ * `UPSTREAM_ASSET`, which predates the others and which every existing test
+ * sets; the rest are `<name>.ts` under `UPSTREAM_ASSET_DIR`. Both default to
+ * the image's `/app/assets`, where the Dockerfile puts them.
+ */
+export function assetPath(name: AssetName, env: NodeJS.ProcessEnv = process.env): string {
+  if (name === DEFAULT_ASSET) return env.UPSTREAM_ASSET ?? '/app/assets/loop.ts';
+  return join(env.UPSTREAM_ASSET_DIR ?? '/app/assets', `${name}.ts`);
+}
+
 export interface LoadedAsset {
   bytes: Buffer;
   loopDuration90k: bigint;
diff --git a/e2e-upstream/src/scenario.ts b/e2e-upstream/src/scenario.ts
index 49b0a046..9bbbd959 100644
--- a/e2e-upstream/src/scenario.ts
+++ b/e2e-upstream/src/scenario.ts
@@ -1,5 +1,7 @@
 import { randomUUID } from 'node:crypto';
 import { BadRequestError } from './errors.js';
+import { ASSET_NAMES, DEFAULT_ASSET, isAssetName } from './asset.js';
+import type { AssetName } from './asset.js';
 
 export interface ChannelSpec {
   id: number;
@@ -18,10 +20,18 @@ export interface ChannelSpec {
    * `parseScenarioRequest` applies it.
    */
   categoryId?: number;
+  /**
+   * The looping TS asset this channel's stream serves (Phase 4a-0), one of
+   * `ASSET_NAMES` (`src/asset.ts`). Optional on input: `parseScenarioRequest`
+   * and `ScenarioRegistry.create` both default it to `DEFAULT_ASSET`
+   * (`'loop'`), the one asset every scenario served before 4a-0, so an
+   * existing scenario streams exactly what it did.
+   */
+  asset?: AssetName;
 }
 
 /**
- * A `ChannelSpec` after category resolution. Every consumer of
+ * A `ChannelSpec` after category and asset resolution. Every consumer of
  * `Scenario.channels` — the playlist/XMLTV renderers and the XC route
  * handlers built in later tasks — needs a concrete `categoryId`, never
  * `undefined` silently widened to the string `"undefined"` at render time.
@@ -30,7 +40,7 @@ export interface ChannelSpec {
  * normal case; both `parseScenarioRequest` and `ScenarioRegistry.create`
  * resolve it before it reaches a `Scenario`.
  */
-export type ResolvedChannelSpec = ChannelSpec & { categoryId: number };
+export type ResolvedChannelSpec = ChannelSpec & { categoryId: number; asset: AssetName };
 
 export interface CategorySpec {
   id: number;
@@ -193,6 +203,7 @@ function defaultChannels(count: number, categoryId: number): ResolvedChannelSpec
       // logo URL cannot accidentally make a real network request.
       logo: `https://example.invalid/logo-${n}.png`,
       categoryId,
+      asset: DEFAULT_ASSET,
     };
   });
 }
@@ -601,7 +612,17 @@ export function parseScenarioRequest(body: Record<string, unknown>): ScenarioReq
         // the M3U's `group-title="E2E"` stays what it always was.
         const categoryId = channel.categoryId ?? liveCategories[0].id;
         assertKnownCategory(categoryId, liveCategories, 'channels.categoryId');
-        channels.push({ ...channel, categoryId });
+        // Checked here rather than in `isChannelSpec`, so the 400 names the
+        // asset and the names that exist instead of the generic shape
+        // message. A name this provider has no file for would otherwise be
+        // accepted and then 500 on the first stream request.
+        const asset: unknown = channel.asset;
+        if (asset !== undefined && !isAssetName(asset)) {
+          throw new BadRequestError(
+            `'channels.asset' for channel ${channel.id} is ${JSON.stringify(asset)}, which is not an asset this provider has; expected one of ${ASSET_NAMES.join(', ')}`,
+          );
+        }
+        channels.push({ ...channel, categoryId, asset: asset ?? DEFAULT_ASSET });
       }
       request.channels = channels;
     } else if (isNonNegativeInteger(body.channels)) {
@@ -737,6 +758,7 @@ export class ScenarioRegistry {
       ? request.channels.map((channel) => ({
           ...channel,
           categoryId: channel.categoryId ?? liveCategories[0].id,
+          asset: channel.asset ?? DEFAULT_ASSET,
         }))
       : defaultChannels(request.channels ?? 1, liveCategories[0].id);
 
diff --git a/e2e-upstream/src/server.ts b/e2e-upstream/src/server.ts
index ba3943c0..375751fe 100644
--- a/e2e-upstream/src/server.ts
+++ b/e2e-upstream/src/server.ts
@@ -6,8 +6,8 @@ import type { Scenario } from './scenario.js';
 import { BadRequestError } from './errors.js';
 import { renderPlaylist, credentialQuery, PLAYLIST_CONTENT_TYPE } from './playlist.js';
 import { renderXmltv, XMLTV_CONTENT_TYPE } from './xmltv.js';
-import { loadAsset } from './asset.js';
-import type { LoadedAsset } from './asset.js';
+import { DEFAULT_ASSET, assetPath, loadAsset } from './asset.js';
+import type { AssetName, LoadedAsset } from './asset.js';
 import { ConnectionRegistry } from './connections.js';
 import type { LiveConnection } from './connections.js';
 import { streamLoop, STREAM_CONTENT_TYPE } from './stream.js';
@@ -37,18 +37,26 @@ export const faults = new FaultStore();
 export const scenarioLog = new ScenarioLog();
 
 /**
- * Loaded on first use, not at module scope. `readFileSync` on
- * `UPSTREAM_ASSET` (`/app/assets/loop.ts` by default) only succeeds inside
+ * Loaded on first use, not at module scope. `readFileSync` on an asset
+ * (`/app/assets/<name>.ts` by default, see `assetPath`) only succeeds inside
  * the Docker image, where `make-asset.sh` put it there at build time — it
  * does not exist in the environment this test suite runs in. Every test
  * that imports this module for the scenario/playlist/EPG routes would fail
  * at import time if this ran eagerly, long before any test ever exercises
  * the stream route itself.
+ *
+ * Cached by resolved path, for the reason `getVodAsset()` below gives: a
+ * test that points `UPSTREAM_ASSET` or `UPSTREAM_ASSET_DIR` somewhere new
+ * must get the new file, not whichever one an earlier test loaded. A failed
+ * load is not cached, so a missing file fails every request that names it.
  */
-let asset: LoadedAsset | undefined;
-function getAsset(): LoadedAsset {
+const assets = new Map<string, LoadedAsset>();
+function getAsset(name: AssetName): LoadedAsset {
+  const path = assetPath(name);
+  let asset = assets.get(path);
   if (!asset) {
-    asset = loadAsset(process.env.UPSTREAM_ASSET ?? '/app/assets/loop.ts');
+    asset = loadAsset(path);
+    assets.set(path, asset);
   }
   return asset;
 }
@@ -380,10 +388,16 @@ export async function serveChannelStream(
 
   // Resolved before tryAcquire, deliberately: admission doesn't depend on
   // the asset, and acquiring the slot first would leak it if getAsset()
-  // throws (missing or corrupt UPSTREAM_ASSET) — the slot would never be
+  // throws (a missing or corrupt asset file) — the slot would never be
   // released, and since a failed load isn't cached, every retry leaks
   // another one until maxConnections is permanently exhausted.
-  const asset = getAsset();
+  //
+  // The channel's own asset (4a-0), or the default for an id the scenario
+  // does not declare: the plain `/stream/<n>.ts` route serves any numeric
+  // id (see this function's doc comment), and that keeps working unchanged.
+  const assetName =
+    scenario.channels.find((channel) => channel.id === channelId)?.asset ?? DEFAULT_ASSET;
+  const asset = getAsset(assetName);
 
   // Admission is decided, and must be decided, before streamLoop writes
   // any header — a rejected client must never see a 200 first. The
diff --git a/e2e-upstream/test/asset-names.test.ts b/e2e-upstream/test/asset-names.test.ts
new file mode 100644
index 00000000..d9eb6b13
--- /dev/null
+++ b/e2e-upstream/test/asset-names.test.ts
@@ -0,0 +1,62 @@
+import { describe, it, expect } from 'vitest';
+import { readFileSync } from 'node:fs';
+import { fileURLToPath } from 'node:url';
+import { ASSET_NAMES } from '../src/asset.js';
+
+/**
+ * The door (`parseScenarioRequest`) accepts exactly `ASSET_NAMES`, and a
+ * stream request loads `<name>.ts` from the image. Nothing at runtime can tell
+ * whether the image actually has every one: a name missing from the
+ * Dockerfile's build loop, or a variant `make-asset.sh` does not know, would
+ * pass the door and 500 on the first stream. This reads both build files and
+ * holds them to the list, in both directions.
+ */
+const root = new URL('..', import.meta.url);
+const makeAsset = readFileSync(fileURLToPath(new URL('scripts/make-asset.sh', root)), 'utf8');
+const dockerfile = readFileSync(fileURLToPath(new URL('Dockerfile', root)), 'utf8');
+
+/** The case labels of make-asset.sh's `case "${VARIANT}" in`, `*` excluded. */
+function makeAssetVariants(script: string): string[] {
+  return [...script.matchAll(/^ {2}([a-z0-9][a-z0-9-]*)\)$/gm)].map((match) => match[1]);
+}
+
+/** The names the Dockerfile's `for name in … ; do` loop builds. */
+function dockerfileBuilds(file: string): string[] {
+  const match = /for name in ([^;]+); do/.exec(file);
+  if (!match) throw new Error("e2e-upstream/Dockerfile has no 'for name in …; do' asset build loop");
+  return match[1].trim().split(/\s+/);
+}
+
+const sorted = (names: readonly string[]) => [...names].sort();
+
+/** The loop body, `./make-asset.sh "/build/assets/${name}.ts" "${name}" || exit 1; \`, then `done`. */
+const GUARDED_LOOP_BODY =
+  /do \\\n\s*\.\/make-asset\.sh "\/build\/assets\/\$\{name\}\.ts" "\$\{name\}" \|\| exit 1; \\\n\s*done/;
+
+describe('asset names (Phase 4a-0)', () => {
+  it('make-asset.sh builds a variant for every name in ASSET_NAMES, and no other', () => {
+    expect(
+      sorted(makeAssetVariants(makeAsset)),
+      'scripts/make-asset.sh case labels vs src/asset.ts ASSET_NAMES',
+    ).toEqual(sorted(ASSET_NAMES));
+  });
+
+  it('the Dockerfile fails the build when make-asset.sh fails for any name', () => {
+    // `RUN` is `sh -c` with no `-e`, and a `for` loop's status is its last
+    // command's: without `|| exit 1` a fixture that fails its shape check
+    // prints the failure and the image builds anyway (measured), so the
+    // CONTRACT.md guarantee that an image which exists has these shapes
+    // rests on this one guard.
+    expect(
+      dockerfile,
+      "the Dockerfile's asset loop must run make-asset.sh with '|| exit 1', or a failed shape check does not fail docker build",
+    ).toMatch(GUARDED_LOOP_BODY);
+  });
+
+  it('the Dockerfile builds every name in ASSET_NAMES, and no other', () => {
+    expect(
+      sorted(dockerfileBuilds(dockerfile)),
+      "Dockerfile's asset build loop vs src/asset.ts ASSET_NAMES",
+    ).toEqual(sorted(ASSET_NAMES));
+  });
+});
diff --git a/e2e-upstream/test/asset.test.ts b/e2e-upstream/test/asset.test.ts
index 7f32182b..7d18d6d1 100644
--- a/e2e-upstream/test/asset.test.ts
+++ b/e2e-upstream/test/asset.test.ts
@@ -1,5 +1,5 @@
 import { describe, it, expect } from 'vitest';
-import { measureLoop } from '../src/asset.js';
+import { ASSET_NAMES, DEFAULT_ASSET, assetPath, isAssetName, measureLoop } from '../src/asset.js';
 import { makeSyntheticTs } from './helpers/synthetic-ts.js';
 
 const STEP = 3600n; // 40 ms at 90 kHz
@@ -50,3 +50,29 @@ describe('measureLoop', () => {
     expect(() => measureLoop(bytes)).toThrow(/no timestamps/i);
   });
 });
+
+describe('asset names and paths (Phase 4a-0)', () => {
+  it('defaults to loop, which is one of the names', () => {
+    expect(DEFAULT_ASSET).toBe('loop');
+    expect(ASSET_NAMES).toContain(DEFAULT_ASSET);
+  });
+
+  it('recognises exactly the declared names', () => {
+    for (const name of ASSET_NAMES) expect(isAssetName(name)).toBe(true);
+    expect(isAssetName('LOOP')).toBe(false);
+    expect(isAssetName('loop.ts')).toBe(false);
+    expect(isAssetName(undefined)).toBe(false);
+    expect(isAssetName(1)).toBe(false);
+  });
+
+  it('keeps loop on UPSTREAM_ASSET and puts every other name under UPSTREAM_ASSET_DIR', () => {
+    const env = { UPSTREAM_ASSET: '/x/custom-loop.ts', UPSTREAM_ASSET_DIR: '/y' };
+    expect(assetPath('loop', env)).toBe('/x/custom-loop.ts');
+    expect(assetPath('h264-eac3', env)).toBe('/y/h264-eac3.ts');
+  });
+
+  it("falls back to the image's /app/assets for both", () => {
+    expect(assetPath('loop', {})).toBe('/app/assets/loop.ts');
+    expect(assetPath('mpeg2-576i-mp2', {})).toBe('/app/assets/mpeg2-576i-mp2.ts');
+  });
+});
diff --git a/e2e-upstream/test/scenario.test.ts b/e2e-upstream/test/scenario.test.ts
index b59612f2..e8586bb7 100644
--- a/e2e-upstream/test/scenario.test.ts
+++ b/e2e-upstream/test/scenario.test.ts
@@ -1,6 +1,7 @@
 import { describe, it, expect } from 'vitest';
 import { ScenarioRegistry, parseScenarioRequest } from '../src/scenario.js';
 import { BadRequestError } from '../src/errors.js';
+import { ASSET_NAMES } from '../src/asset.js';
 
 describe('ScenarioRegistry', () => {
   it('generates the requested number of channels with distinct ids and tvg-ids', () => {
@@ -29,7 +30,7 @@ describe('ScenarioRegistry', () => {
     expect(registry.create({ maxConnections: 0 }).maxConnections).toBe(0);
   });
 
-  it('accepts explicit channel specs verbatim, defaulting a missing categoryId', () => {
+  it('accepts explicit channel specs verbatim, defaulting a missing categoryId and asset', () => {
     // create() is a bypass of parseScenarioRequest — this pins that it does
     // its own categoryId defaulting too, so Scenario.channels[].categoryId
     // is never undefined regardless of which path built the scenario.
@@ -39,7 +40,7 @@ describe('ScenarioRegistry', () => {
     });
 
     expect(scenario.channels).toEqual([
-      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null, categoryId: 1 },
+      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null, categoryId: 1, asset: 'loop' },
     ]);
   });
 
@@ -578,3 +579,58 @@ describe('XC scenario declaration', () => {
     expect(() => parseScenarioRequest({ seriesCategories: [] })).toThrow(/seriesCategories/);
   });
 });
+
+describe('channel asset (Phase 4a-0)', () => {
+  const spec = (over = {}) => ({ id: 1, name: 'A', tvgId: 'a.e2e', logo: null, ...over });
+
+  it('keeps a named asset and defaults an omitted one to loop, through the parser and the registry', () => {
+    const request = parseScenarioRequest({
+      channels: [
+        spec({ id: 1, asset: 'h264-1080i-aac-ac3' }),
+        spec({ id: 2, name: 'B', tvgId: 'b.e2e' }),
+      ],
+    });
+    expect((request.channels as { asset: string }[]).map((c) => c.asset)).toEqual([
+      'h264-1080i-aac-ac3',
+      'loop',
+    ]);
+
+    const scenario = new ScenarioRegistry().create(request);
+    expect(scenario.channels.map((c) => c.asset)).toEqual(['h264-1080i-aac-ac3', 'loop']);
+  });
+
+  it('gives count-form channels the default asset', () => {
+    const scenario = new ScenarioRegistry().create(parseScenarioRequest({ channels: 2 }));
+    expect(scenario.channels.map((c) => c.asset)).toEqual(['loop', 'loop']);
+  });
+
+  it('accepts every name in ASSET_NAMES', () => {
+    const channels = ASSET_NAMES.map((asset, index) =>
+      spec({ id: index, name: `C${index}`, tvgId: `c${index}.e2e`, asset }),
+    );
+    const request = parseScenarioRequest({ channels });
+    expect((request.channels as { asset: string }[]).map((c) => c.asset)).toEqual([...ASSET_NAMES]);
+  });
+
+  it('rejects an unknown asset, naming the channel, the value and the names that exist', () => {
+    // Accepted, it would 500 on the first stream request instead — far from
+    // the scenario that caused it.
+    expect(
+      () => parseScenarioRequest({ channels: [spec({ id: 4, asset: 'h265-1080p' })] }),
+      'the door must refuse an asset name the provider has no file for',
+    ).toThrow(
+      /'channels\.asset' for channel 4 is "h265-1080p".*expected one of loop, mpeg2-576i-mp2, h264-1080i-aac-ac3, hevc-aac, h264-gop10-aac, h264-eac3, h264-noaudio/,
+    );
+  });
+
+  it('rejects a non-string asset, naming the field', () => {
+    expect(
+      () => parseScenarioRequest({ channels: [spec({ asset: 3 })] }),
+      'the door must refuse a non-string asset',
+    ).toThrow(/'channels\.asset' for channel 1 is 3/);
+    expect(
+      () => parseScenarioRequest({ channels: [spec({ asset: null })] }),
+      'the door must refuse a null asset',
+    ).toThrow(/'channels\.asset' for channel 1 is null/);
+  });
+});
diff --git a/e2e-upstream/test/server.test.ts b/e2e-upstream/test/server.test.ts
index de5b5f57..4032e33c 100644
--- a/e2e-upstream/test/server.test.ts
+++ b/e2e-upstream/test/server.test.ts
@@ -1021,3 +1021,127 @@ describe('dead-air and slow-trickle applying to connections opened after they ar
     expect(outcome).toBe('stalled');
   });
 });
+
+describe('per-channel assets (Phase 4a-0)', () => {
+  // Two synthetic assets told apart by PID alone, which is all the route
+  // decides: which file a channel's stream reads. `loop` stays on
+  // UPSTREAM_ASSET; a named asset is `<name>.ts` under UPSTREAM_ASSET_DIR.
+  // `hevc-aac` is deliberately not written, for the missing-file test.
+  const LOOP_PID = 0x0100;
+  const EAC3_PID = 0x0600;
+
+  beforeAll(() => {
+    const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-named-assets-'));
+    writeFileSync(join(dir, 'loop.ts'), makeSyntheticTs({ packets: 40, pid: LOOP_PID, step: 3600n }));
+    writeFileSync(
+      join(dir, 'h264-eac3.ts'),
+      makeSyntheticTs({ packets: 40, pid: EAC3_PID, step: 3600n }),
+    );
+    process.env.UPSTREAM_ASSET = join(dir, 'loop.ts');
+    process.env.UPSTREAM_ASSET_DIR = dir;
+  });
+
+  const channel = (id: number, extra: Record<string, unknown> = {}) => ({
+    id,
+    name: `C${id}`,
+    tvgId: `c${id}.e2e`,
+    logo: null,
+    ...extra,
+  });
+
+  async function createScenario(body: Record<string, unknown>) {
+    const res = await fetch(`http://127.0.0.1:${server!.port}/scenarios`, {
+      method: 'POST',
+      body: JSON.stringify(body),
+    });
+    expect(res.status).toBe(201);
+    return readJson(res);
+  }
+
+  /** The PID of the first packet a stream URL sends. */
+  async function firstPid(url: string): Promise<number> {
+    const res = await fetch(url);
+    expect(res.status).toBe(200);
+    const reader = res.body!.getReader();
+    const { value } = await reader.read();
+    await reader.cancel().catch(() => {});
+    expect(value![0]).toBe(0x47);
+    return ((value![1] & 0x1f) << 8) | value![2];
+  }
+
+  it("echoes each channel's resolved asset, defaulting an omitted one to loop", async () => {
+    server = await startServer(0);
+    const scenario = await createScenario({
+      channels: [channel(1, { asset: 'h264-eac3' }), channel(2)],
+    });
+    expect(scenario.channels.map((c: { asset: string }) => c.asset)).toEqual(['h264-eac3', 'loop']);
+  });
+
+  it("streams a channel's named asset, the default for the others and for an undeclared id", async () => {
+    server = await startServer(0);
+    const scenario = await createScenario({
+      channels: [channel(1, { asset: 'h264-eac3' }), channel(2)],
+    });
+    const base = `http://127.0.0.1:${server.port}/s/${scenario.id}/stream`;
+
+    expect(
+      await firstPid(`${base}/1.ts`),
+      "channel 1 names h264-eac3 (PID 0x600); the channel's asset picks the file",
+    ).toBe(EAC3_PID);
+    expect(await firstPid(`${base}/2.ts`), 'channel 2 names no asset: loop (PID 0x100)').toBe(
+      LOOP_PID,
+    );
+    // The plain route serves any numeric id; one the scenario never declared
+    // has no asset of its own and gets the default, as before 4a-0.
+    expect(await firstPid(`${base}/9.ts`), 'undeclared channel 9: loop (PID 0x100)').toBe(
+      LOOP_PID,
+    );
+  });
+
+  it('streams the named asset on the XC /live/ route too', async () => {
+    server = await startServer(0);
+    const scenario = await createScenario({
+      xc: true,
+      username: 'user',
+      password: 'pass',
+      channels: [channel(1, { asset: 'h264-eac3' })],
+    });
+    expect(
+      await firstPid(`http://127.0.0.1:${server.port}/s/${scenario.id}/live/user/pass/1.ts`),
+      "/live/ channel 1 names h264-eac3 (PID 0x600); the channel's asset picks the file",
+    ).toBe(EAC3_PID);
+  });
+
+  it('streams the named asset on both catch-up layouts too', async () => {
+    server = await startServer(0);
+    const scenario = await createScenario({
+      xc: true,
+      username: 'user',
+      password: 'pass',
+      channels: [channel(1, { asset: 'h264-eac3' })],
+    });
+    const base = `http://127.0.0.1:${server.port}/s/${scenario.id}`;
+    const start = '2026-08-29:14-00';
+    expect(
+      await firstPid(`${base}/timeshift/user/pass/65/${start}/1.ts`),
+      "PATH catch-up channel 1 names h264-eac3 (PID 0x600); the channel's asset picks the file",
+    ).toBe(EAC3_PID);
+    const query = `username=user&password=pass&stream=1&start=${encodeURIComponent(start)}&duration=65`;
+    expect(
+      await firstPid(`${base}/streaming/timeshift.php?${query}`),
+      "QUERY catch-up channel 1 names h264-eac3 (PID 0x600); the channel's asset picks the file",
+    ).toBe(EAC3_PID);
+  });
+
+  it('answers 500 naming the file when a named asset is missing, and holds no slot', async () => {
+    server = await startServer(0);
+    const scenario = await createScenario({
+      maxConnections: 1,
+      channels: [channel(1, { asset: 'hevc-aac' })],
+    });
+    const res = await fetch(`http://127.0.0.1:${server.port}/s/${scenario.id}/stream/1.ts`);
+    expect(res.status, 'hevc-aac.ts was never written, so its load must fail').toBe(500);
+    expect((await readJson(res)).error).toMatch(/hevc-aac\.ts/);
+    expect(connections.count(scenario.id)).toBe(0);
+  });
+});
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index a26b8591..916370de 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -48,7 +48,7 @@ resolve (see the G8/G10 Gap rows).
 | Streaming | Stream Profile: FFmpeg | G4 | done |
 | Streaming | Output Profile shared per (channel, profile) | G4 | done |
 | Streaming | Ownership lease is fenced against a second concurrent owner — attempted by deleting `live:channel:{uuid}:owner` under a running Proxy-profile stream and polling for a second worker to claim it; confirmed empirically unprovable from outside the container: the same owning worker's own `ProxyServer._start_cleanup_thread` cleanup loop notices the missing key and calls `extend_ownership()`, re-`SET NX`-ing the identical worker id well under a second later every run (measured at ≤500ms), because that loop is the only code path with a local `StreamManager` for the channel; a follower worker never contends because `stream_ts` only lets a worker attempt ownership when channel metadata is absent too, which a bare owner-key delete does not cause — so no black-box HTTP/Redis manipulation can land a second `SET NX` in the sub-second gap. The untried lever was co-expiring `live:channel:{uuid}:metadata` with the owner key, which is what would have opened the metadata-gated follower path in `stream_ts`; it was a larger provocation than this row's brief allowed and it will never be tried, because **Phase 2 stage 2d-4 deleted the lease with `apps/proxy/live_proxy/`**. The Go relay is one process holding one in-memory channel registry (ADR 0006), so there is no second owner to fence against and no analogous defect to provoke. Retained as the record of a defect that closed by elimination rather than by a test, and as the trace a future reader needs before reintroducing any cross-process lease. | G4 | done |
-| Streaming | **Gap (spec D6):** the provider's TS asset carries no per-stream identity — one shared file, fixed PIDs `0x100`/`0x101` (`scripts/make-asset.sh`), so no test can tell one channel's stream bytes from another's by content; the burned-in frame counter is a human debugging aid only, and no test may assert on it. Feasible under the Proxy stream profile, via a dedicated marker PID injected in `LoopRewriter` (`e2e-upstream/src/ts-loop.ts`); infeasible under the locked FFmpeg profile, whose `-c:v copy -c:a copy` remux maps exactly one video and one audio stream and lets the mpegts muxer rewrite PAT/PMT/PIDs itself, leaving no slot for an injected marker to survive. Deliberately not built by G15 — it is a provider (`e2e-upstream/`) change, out of this goal's scope — and recorded here, in `e2e-upstream/CONTRACT.md`'s non-guarantees, so it is not re-derived by whichever goal picks it up | G15 | todo |
+| Streaming | **Gap (spec D6):** the provider's TS asset carries no per-stream identity — one shared file, fixed PIDs `0x100`/`0x101` (`scripts/make-asset.sh`), so no test can tell one channel's stream bytes from another's by content; the burned-in frame counter is a human debugging aid only, and no test may assert on it. Feasible under the Proxy stream profile, via a dedicated marker PID injected in `LoopRewriter` (`e2e-upstream/src/ts-loop.ts`); infeasible under the locked FFmpeg profile, whose `-c:v copy -c:a copy` remux maps exactly one video and one audio stream and lets the mpegts muxer rewrite PAT/PMT/PIDs itself, leaving no slot for an injected marker to survive. Deliberately not built by G15 — it is a provider (`e2e-upstream/`) change, out of this goal's scope — and recorded here, in `e2e-upstream/CONTRACT.md`'s non-guarantees, so it is not re-derived by whichever goal picks it up. Phase 4a-0 (`e2e-upstream` 1.3.0) lets a channel name one of seven assets, so channels on *different* assets now differ in codecs and PIDs; channels on the same asset still cannot be told apart, so the gap stands | G15 | todo |
 | Upstream | `e2e-upstream/CONTRACT.md` — the provider's guarantee/non-guarantee contract, version-addressed and kept in sync with `e2e-upstream/package.json` by `tests/guards/upstream-contract.spec.ts` (see the Guards table below) | G15 | done |
 | Output | /output/m3u parses, every URL is well-formed, and one is streamed end to end; also pins that a channel name containing a double quote no longer breaks the emitted `tvg-name`/`group-title` attributes (**fixed by #427**, [#80](https://github.com/D10Scot/Dispatcharr/issues/80)), in the same file | G5 | done |
 | Output | /output/m3u/&lt;profile_name&gt; scopes to Channel Profile membership, and 404s on a profile name that does not exist | G5 | done |
@@ -206,6 +206,7 @@ resolve (see the G8/G10 Gap rows).
 | Sources | **Gap:** `ServerGroup` credential pooling is unproven, naming `apps/m3u/connection_pool.py:group_has_capacity_for_profile` and the two-account, two-stream setup it needs — cut before this goal started, cross-referencing [#68](https://github.com/D10Scot/Dispatcharr/issues/68) | G14 | todo |
 | Upstream | **Gap, `e2e-upstream`'s scope:** the provider's `ScenarioLog` records `method`, `path` and `status` but no request headers (`e2e-upstream/src/server.ts:logRequest`), so nothing Dispatcharr sends upstream as a `User-Agent` — including `stream_settings.default_user_agent`, the unowned-`CoreSettings` gap above — is observable through it. Closing it is one field on the log entry | G14 | todo |
 | Sources | **Gap:** the bulk-path fuzzy "no match" characterization test (would have been test 8) was implemented, its own assertions and the file's typecheck passed, and it was cut before shipping — see `epg-matching.spec.ts`'s header. Mechanism: `_active_epg_fuzzy_queryset` admits every active source's `EPGData` with no scoping to the test's own source; two `seed.channel()`/`seed.generatedName('epg')`-shaped names (worker/run/test-id digits, stripped to nothing by `normalize_name`) share enough character-level structure to land inside the bulk path's `[50, 80)` ML band by coincidence — measured at fuzzy 56.91 against a leftover row from an unrelated `epg-ingest.spec.ts` run — triggering `get_sentence_transformer()` and a real ~88 MB model download, then matching the two unrelated generated names via the ML "desperate last resort" branch at cosine 0.91 (the aggressive-ML finding, folded in here rather than filed separately). The test's own ws-based settle signal also resolved before the ML-delayed match actually committed — a second, independent defect in the test design, not just in the pair choice. What a future owner needs: a fixture-scoped way to deactivate other sources during the test, or a dedicated single-worker project. G14's own shipped tests 6, 7, 10, 11, 12 and 13 each leave behind an active upstream EPG source with a generated-shape `EPGData` name of exactly this kind — six more candidates per run for the next test that lands in this band by coincidence, not just the one leftover row measured above | G14 | todo |
+| Upstream | Phase 4a codec fixtures: six named looping TS assets (`mpeg2-576i-mp2`, `h264-1080i-aac-ac3`, `hevc-aac`, `h264-gop10-aac`, `h264-eac3`, `h264-noaudio`) beside the default `loop`, and a scenario channel's optional `asset` field choosing one. Each fixture's streams, PIDs and keyframe spacing are a `CONTRACT.md` guarantee, checked by `scripts/make-asset.sh` at image build; the field, the routing and the name list are covered by `e2e-upstream`'s vitest suite. No E2E spec consumes them yet: 4a-1b onwards does | 4a-0 | done |
 
 The ten G1 rows above are covered by these specs (the two seeding rows
 share one file, as do the two principal rows):
diff --git a/e2e/fixtures/upstream.ts b/e2e/fixtures/upstream.ts
index bf30f80f..d34273b5 100644
--- a/e2e/fixtures/upstream.ts
+++ b/e2e/fixtures/upstream.ts
@@ -85,11 +85,34 @@ export interface FaultResult {
   appliedTo: number;
 }
 
+/**
+ * The looping TS assets a scenario channel may name (Phase 4a-0), mirroring
+ * the provider's `ASSET_NAMES` (`e2e-upstream/src/asset.ts`). `loop` is the
+ * default every scenario served before; the other six are the codec fixtures
+ * whose exact streams `e2e-upstream/CONTRACT.md` guarantees. A name missing
+ * here is a compile error at the call site; one the provider lacks is a 400
+ * naming it.
+ */
+export type UpstreamAsset =
+  | 'loop'
+  | 'mpeg2-576i-mp2'
+  | 'h264-1080i-aac-ac3'
+  | 'hevc-aac'
+  | 'h264-gop10-aac'
+  | 'h264-eac3'
+  | 'h264-noaudio';
+
 export interface UpstreamChannel {
   id: number;
   name: string;
   tvgId: string;
   logo: string | null;
+  /**
+   * Optional — the asset this channel's stream serves. The provider defaults
+   * it to `loop` and echoes the resolved name on every channel of the created
+   * `UpstreamScenario`.
+   */
+  asset?: UpstreamAsset;
   /**
    * Optional — mirrors the provider's `ChannelSpec.categoryId` (G8 task 1).
    * When omitted, the provider defaults it to the scenario's first declared
@@ -162,7 +185,8 @@ export interface UpstreamScenario {
   /** Origin Playwright resolves. Hand these to fetch/streamClient. */
   control: string;
   credentialQuery: string;
-  channels: UpstreamChannel[];
+  /** The provider always echoes each channel's resolved `asset` (4a-0). */
+  channels: (UpstreamChannel & { asset: UpstreamAsset })[];
   /**
    * Echoed by the provider and typed here because an XC account needs the two
    * values *separately*: `credentialQuery` is the pre-formatted query string,
```
<!-- appendix-A-end -->
