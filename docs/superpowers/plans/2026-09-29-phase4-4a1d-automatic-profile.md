# Plan: Phase 4a-1d, the automatic HLS profile

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The Go, Python and JavaScript code is specified by its contracts below: types, signatures, lock order, flows, and test names with their oracles. It is not given as a diff; the implementer writes it. Every documentation edit in the implementation PR is in Appendix A: a byte-exact `git diff` against the seed that the implementer applies and does not rewrite. Its only non-literal parts are the `⟨…⟩` slots, and each one names exactly what fills it.

**Goal.** An admin can set a channel to an HLS Output Profile in *automatic* mode. For that channel, the relay's HLS output **copies what AVPlayer accepts** and encodes only what it does not (ADR 0009's opt-in). The pieces are:

- **Data model.** `OutputProfile` gains `hls_mode`. Two locked rows are seeded, "HLS (Re-encode)" and "HLS (Automatic)". `Channel` gains `hls_output_profile`, which uses `SET_NULL`. Both migrations have reverses and a round-trip test.
- **Exclusion.** Every other Output Profile consumer excludes the HLS rows, on the backend and in the frontend.
- **Next-source.** It carries `hls_profile`.
- **Channel form.** It gains an "HLS output" select.
- **Relay.** It applies the automatic rules per rendition:
  - the copy rule, with K ≤ 6 s;
  - the declared-family rule, with `hevc_qsv` and `libx265`;
  - the over-long-segment rule.

  Each HLS pipeline carries its own target duration. That target scales the stall watchdog (R42), the store and every presence threshold.

Spec D12, § Automatic generation, § 4a-1d.

**Seed.** `4ed75d963dee2b43246fd2ef5ab43ab471f58812` (`4ed75d96`). This is #538's head (branch `migration/phase4-4a1b-live-hls`, 4a-1b), reviewed PASS; #538 was not yet merged when this plan was written. Every `file:line` below is at the seed unless it says otherwise. **The implementer re-greps every anchor once #538 has merged, and again once 4a-1c has merged (4a-1c lands first, § Overlap), and branches from `main` at that point.** Only #538's coverage-floor numbers are expected to move before it merges. So `M₀`, the floor's `missing` that this plan raises, is read from `main` when the branch is cut, and is never the seed's `589`.

**Branch.** `migration/phase4-4a1d-automatic-profile` (spec D1), so the full E2E and lifecycle matrix runs on it.

**Authority.** In order of precedence:

1. **The rulings** (the orchestrator's `rulings.md`), R1-R77. The ones this PR carries:
   - R7: remux is opt-in per channel through an Output Profile in "automatic" mode.
   - R15: every new identifier is neutral. That covers `hls_mode`, `hls_output_profile`, `hls_profile` and `"copy"`.
   - R21 and R34: the Go floor.
   - R28: `field_order=unknown` is progressive for copy eligibility (issue #525).
   - R37: automatic mode's keyframe re-probe, which 4a-1a decided and this PR wires.
   - R41: `CODECS` comes from the first complete generation.
   - R42: the per-pipeline stall timeout.
   - R45: hardware measurements do not gate.
   - R48: the seam, if a split is needed.
   - R55 and R57: the startup allowance and the entry's waits, which this PR keeps consistent at a target of 6.
   - The 4a-1a r5 hand-off: reset per-attempt codecs.
   - R58-R63: this plan's own six round-0 questions, each ruled as recommended (§ Rulings on this plan's questions).
   - R74-R77: the round-1 review's findings 8-11, ruled by the orchestrator (§ Rulings on this plan's questions).
2. **The Phase 4 spec**, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`, as amended by this plan's own PR (§ Spec amendments in this PR). The relevant parts are D8-D12, § Next-source additions, § Relay channel payload additions, § Encoder argv (with § Automatic generation, as amended here), § Presence thresholds, § Testing and gates, § 4a-1d, and Q1.
3. **The 4a-1b plan** (`docs/superpowers/plans/2026-09-28-phase4-4a1b-live-hls.md`, on `main`). Its § Overlap row for 4a-1d says: "4a-1b stores each session's target duration from `hls.TargetDuration` (always 2); 4a-1d sources it from the pipeline (R42's per-pipeline `StallTimeout` is 4a-1d's too)". Also **`relay/hls`, `relay/session` and `relay/httpapi` as committed at the seed**, tests included. This plan links against the code as committed, never against a plan appendix.
4. **The standing references.** CLAUDE.md covers the Go hooks, stdlib-only, credlint, the Go ratchet as amended by R21/R27, the Python Gate 2, the migration check, the frontend conventions and the commit gate. Also ADR 0005, ADR 0006 (with ADR 0008's record of its amendment), ADR 0008, ADR 0009, `CONTEXT.md`, and `docs/relay-parity-matrix.md` at the seed (rows 31-44).

**Issues.** The implementation PR **closes #525** (R28: `field_order=unknown` is treated as progressive for copy eligibility). The implementer adds the line `Closes #525.` to the implementation PR's own body and its squash body, where the § PR description draft shows a slot. The draft in this plan carries no closing keyword. This plan PR closes nothing. Its body names the issue as "#525 (closed by the 4a-1d implementation PR)", with no keyword.

## Global constraints

1. **Standard library only**, and no Redis or Postgres by any route (ADR 0006; `scripts/check_go_stdlib_only.sh relay`).
2. **Error logging goes through `redact.Error`.** Every error that a log or format call carries goes through it, or carries a written `credential-logging: ok - <reason>` (`scripts/check_go_credential_logging.sh relay`). The media-session token and its sid are never logged (4a-1b's rule stands). On the Python side, no log line names a URL or a credential outside `redact_url` (`scripts/check_credential_logging.py`).
3. **Go checks are clean under three GOOS.** `golangci-lint run ./...` has zero findings natively, under `GOOS=linux` and under `GOOS=darwin`. `go vet` and `go test -race ./...` are green.
4. **Lock order is unchanged: `m.mu` → `c.mu` → `st.mu`**, with `outMu` never nested with `c.mu` or `st.mu`, and the pipeline's `p.mu` never held while any of them is taken.
   - This PR adds one new acquisition: `Table.SetTD` takes `st.mu` alone.
   - It also adds one new read: `Pipeline.TargetDuration` takes `p.mu` alone.
   - The entry calls the two in sequence, never nested.
5. **The test-modification rule.** An existing test changes only where the behaviour it pins is the thing this PR changes. Every such change is listed in § Tests changed with its before and after. Test-support edits that change no assertion are listed there too; the one example is the control-plane stub gaining `hls_profile`.
6. **Transcode mode is byte-for-byte unchanged.** A channel with no HLS profile, or with "HLS (Re-encode)", gets the same probe argv, encoder argv, segment cuts, `TARGETDURATION`, multivariant and timeouts as at the seed. Every 4a-1a and 4a-1b HLS test stays green, and none is edited except those § Tests changed lists.
7. **Parity rows land pinned** at the end of the `phase 4` block, as the next free ids at merge (after 4a-1c's). Rows 36 and 43 are amended in place. `HIGHEST_ROW_ID` rises in the same diff.
8. **The spec amendments ride in this plan PR**, not the implementation PR (§ Spec amendments in this PR). The implementation PR edits no spec text, with two exceptions: the Done log's 4a-1d row, which the merge gate fills, and R58's in-place edit of #538's R55 paragraph if this plan PR merged before #538 (§ Spec amendments in this PR).
9. **No hardware gate** (R45). Quick Sync, meaning `hevc_qsv` and its `-level 41`, is the owner's to verify, and that stays owed and non-gating (Q1).
10. **Frontend conventions.** Global state lives in the Zustand stores, HTTP goes through `api.js` only, the UI uses Mantine, and there are no new UI libraries. `npm run lint` must add no new error in a touched file.
11. **The migration check.** `makemigrations --check` stays clean (`core/tests/test_no_pending_migrations.py`). The two scheduler-migration reverse defects in CLAUDE.md (`epg/0007`, `m3u/0006`) are unrelated and **not touched**.

## Overlap with sibling plans

The order is **4a-1c, then 4a-1d, then 4a-2, then 4a-3** (R47: the implementations land serially). 4a-1c lands before this PR, so this PR rebases onto it. The rows below name the file-level boundaries.

| Plan | Shared files | Boundary |
|---|---|---|
| **4a-1c** slot reclaim (lands first) | `apps/proxy/next_source.py`, `apps/proxy/serializers.py`, `relay/control/nextsource.go`, `relay/internal/relaytest/controlplane.go`, `relay/session/*`, `docs/relay-parity-matrix.md` | **Next-source.** 4a-1c adds `capacity` to `resolve_initial_source` and to `NextSourceResponseSerializer`. 4a-1d adds `hls_profile` to `_with_output_profiles` and to the same serializer. They are different functions and adjacent serializer fields, so the rebase is textual only. The same holds for the Go decoder: 4a-1c adds `Capacity`, 4a-1d adds `HLSProfile`, and they are adjacent fields in `NextSourceAnswer`. The stub gains two independent keys. **Presence.** 4a-1c's D16 silence predicate reads the session's own `TD`, never a constant (confirmed with the 4a-1c planner, § Coordination). 4a-1d adds `Table.SetTD` and sets `TD` from the pipeline at entry. 4a-1d's TD = 6 presence test (`TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations`) drives 4a-1c's `SilentAfter(s.TD)` through the entry, and its break-check ("hard-code 4 s") is the spec's. **Parity rows:** 4a-1c's rows come first and 4a-1d's are appended after them. |
| **4a-2** browser player | `frontend/…` | 4a-2 edits `FloatingVideo.jsx`, `FloatingVideoUtils.js`, `RecordingCardUtils.js`, the channel play sites and `api.js`'s leave call. 4a-1d edits `forms/Channel.jsx`, `utils/forms/ChannelUtils.js`, `forms/User.jsx`, `forms/settings/StreamSettingsForm.jsx`, `forms/settings/UiSettingsForm.jsx` (the web-player select's data only), `tables/ChannelsTable.jsx` (the two link-builder selects only, never the play site at `:665-666`) and one new util. There is no shared file except `ChannelsTable.jsx`, where the two hunks are hundreds of lines apart. 4a-1d adds no `api.js` function, because the existing `updateChannel`/`addChannel` carry the new field. |
| **4a-3** rewind window | `relay/hls/store.go`, `relay/session/*`, `relay/channel/manager.go`, the proxy-settings form | **Store.** 4a-1d gives `hls.Store` a per-pipeline target (`SetTargetDuration`) and a target-scaled byte ceiling. 4a-3's window playlists render `#EXT-X-TARGETDURATION` from that same field. **Presence.** 4a-3's behind-live threshold (5 × TD) reads the session's `TD` as 4a-1d sets it. 4a-1d touches no manager, linger or settings code. |
| **4a-3 after 4a-1c** | — | This PR changes none of `ReclaimFor`, the lingering reclaim or the settings frontend. |
| 4a-1a / 4a-1b (merged or merging) | `relay/hls`, `relay/httpapi/hls.go`, `relay/session` | Read and extended. § Tests changed lists every edited test. |

## Coordination

- **With the 4a-1c planner, on 2026-09-29** (4a-1c's plan: PR #540 at `eb146bcf`). The silence rule is `session.SilentAfter(td time.Duration) time.Duration`, which returns `2 * td`, in `relay/session/thresholds.go`. Its one caller is `(*Table).silentLocked` in `relay/session/silence.go`, reached through `Table.Silent` and `Table.StopIfSilent` under one `st.mu`, and read by `relay/channel/reclaim.go`'s `SilenceJudge`/`reclaimable`. An ACTIVE session is silent when `inFlight == 0 && now.Sub(s.lastEnd) > SilentAfter(s.TD)`, so it reads each session's own `s.TD`.
- **The seam.** 4a-1c leaves `Table.Activate` unchanged. 4a-1d adds `Table.SetTD(sid, td)` (Decision 15), called from the entry before `Activate`, and corrects the "Immutable after Add" comment. `SetTD` writes `s.TD` under the same `st.mu` that `silentLocked` holds, so the two are race-free.
- **The tests.** 4a-1c already pins `SilentAfter(6 s) == 12 s` (`TestSilentAfterIsTwoTargetDurations`) and a TD = 6 row in `relay/session/silence_test.go::TestSilence` (row 11), with TD injected. 4a-1d's own TD = 6 test drives TD through the entry from the pipeline (`TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations`), so it proves the value arrives.
- **If 4a-1c's merged predicate differs.** If it reads anything but the session's own `TD`, this PR changes it to read `s.TD`, and § Tests changed lists any 4a-1c assertion that moves.

## Decisions the spec leaves open

Each decision below is the plan's own. Those that change spec text are amended in this PR (§ Spec amendments). The ones the orchestrator ruled on are in § Rulings on this plan's questions (R58-R63, R74-R77).

1. **`hls_mode` values.** `hls_mode` is `CharField(max_length=16, blank=True, default="", choices=[("", "Not HLS"), ("transcode", "HLS re-encode"), ("automatic", "HLS automatic")])`, with the module constants `HLS_MODE_TRANSCODE` and `HLS_MODE_AUTOMATIC` in `core/models.py`. The seeded rows are:
   - `name="HLS (Re-encode)"`, `hls_mode="transcode"`;
   - `name="HLS (Automatic)"`, `hls_mode="automatic"`.

   Both have `command="ffmpeg"`, `parameters="(built by the relay)"`, `locked=True` and `is_active=True`. **Name collision:** `name` is unique (`core/models.py:182`). A pre-existing admin row with either name is renamed first, to `"<name> (custom)"`, and then the seeded row is created. The reverse deletes only the rows whose `hls_mode` is non-blank and does not rename back. That asymmetry is recorded in the migration's docstring and pinned by the round-trip test.
2. **API refusal on HLS rows.** The `OutputProfileViewSet` refuses update, partial update and destroy on a row whose `hls_mode` is non-blank with **403** `{"detail": "HLS output profiles are built by the relay and cannot be changed."}`, from `perform_update`/`perform_destroy` raising `PermissionDenied`. `hls_mode` is `read_only` in `OutputProfileSerializer`, so a POST that sends it creates an ordinary row with `hls_mode=""`. This refusal also covers the Output Profiles table's active toggle (`OutputProfilesTable.jsx:147-153`), which is an update. The frontend needs no change for it: the toggle, the edit button and the delete button are already `disabled={row.original.locked}` (`OutputProfilesTable.jsx:32`, `:41`, `:122`), and both HLS rows are locked.
3. **`hls_profile` costs next-source no query.** `_with_output_profiles(answer, hls_output_profile_id=None)` already iterates every active `OutputProfile` (`apps/proxy/next_source.py:892`).
   - An HLS row (`hls_mode` non-blank) never enters `output_profiles`, which is D12's exclusion for that map. It becomes `answer["hls_profile"] = {"id": …, "mode": …}` when its id is the channel's `hls_output_profile_id`.
   - Every other case gives `None`: no choice, an inactive row, a stream preview, or the 404.
   - `resolve_source` passes `getattr(resolved_object, "hls_output_profile_id", None)` for a `Channel`, and `None` for a previewed `Stream`, at each of its five `_with_output_profiles` calls (`:1046`, `:1051`, `:1054`, `:1074`, `:1079`). The 404 path in `apps/proxy/api_views.py:71` passes nothing.

   - **No new model import.** `next_source.py` and `authorize.py` compare `hls_mode` by truthiness (`if profile.hls_mode:`) or by the literal `""` (`hls_mode=""`), and import nothing new from a `.models` module. `test_tune_path_query_ledger.py:299-305` records every name imported from a `.models` module, so importing `HLS_MODE_*` there would move the boundary pin.

   The FK column arrives with the channel row that `get_object_or_404(Channel, uuid=…)` already fetches (`:255`). So `test_tune_path_query_ledger.py`'s ledger and boundary-module pins do not move, and they are this decision's oracle. `apps/proxy/control_plane.py`'s 404 substitute (`:190-197`) is not touched: nothing in production reads it for `hls_profile`, and changing it would move a Gate 2 module and a pinned literal for nothing.
4. **The Go side mirrors `output_profiles`.**
   - `control.NextSourceAnswer` gains `HLSProfile *HLSProfileRef` and `HLSProfilePresent bool`, decoded in its existing `UnmarshalJSON`.
   - `channel.HLSProfile{Known bool; ID int; Mode string}` is cached on the channel from `Started` and refreshed in `applySwitch` from a non-degraded `Resolved`, exactly as `outputProfiles` is (`relay/channel/failover.go:257-272`).
   - An **absent** key is a contract mismatch. It answers an HLS entry **502** "control plane contract mismatch" after the Attach release, exactly as `attachOutputProfile` answers an absent `output_profiles` (`relay/httpapi/profile.go:66-75`). A TS or fMP4 tune is unaffected. The spec's "the relay requires `hls_profile`" is amended to say so, because failing every TS tune on a stale control plane would be a wider blast radius than the one `output_profiles` already accepted.
   - A mode other than `transcode` or `automatic` is treated the same as an absent key.
5. **Pipeline keys.** Every HLS pipeline gets its own key.
   - The built-in transcode keeps `"hls"`. A channel with a profile uses `"hls:p<id>"`, with the mode from the profile, so "HLS (Re-encode)" chosen explicitly runs transcode under `"hls:p<id>"`.
   - After a refresh has changed the profile, a new entry uses the new key while existing sessions keep their pipeline (spec: "One ffmpeg per (channel, HLS profile)").
   - `Channel.HLSStatus` reports the pipeline registered under the channel's current key, else the one with the lowest key, so that `hls_encoder` and `hls_generation` stay one value each. It reads the key through `c.HLSProfile()` (which takes and releases `c.mu`) and only then takes `outMu`; it never holds the two together (Global constraint 4).
   - The mark (`hlsFailedUntilBoundary`) stays channel-wide, as at the seed.
6. **The automatic probe** is `ProbeArgvFor(bound, ModeAutomatic)`: `ProbeArgv(bound)` with `-read_intervals %+<bound.Analyze in whole seconds>` inserted after `-i pipe:0`, and `-show_entries packet=stream_index,pts_time,flags,size` inserted before `-of json` (R77). For `QuickProbe` that is `-read_intervals %+3`, and for `FullProbe` `%+8`.
   - **One ffprobe run** lists every stream field and the packets. Measured on ffprobe 9.0.1 over a 4 s-GOP H.264 + AAC TS: `field_order`, `profile` and `level` are kept, and the key packets' `pts_time` gave intervals of 4.0 s.
   - **Why `-read_intervals`** (R77). Without it, packet listing makes ffprobe read to stdin's EOF, which the relay's feed gives only at the byte or wall bound: 6.16 s against 0.13 s for `-show_streams` alone, as the round-1 review measured. With it, ffprobe stops after that much media from the first packet. The planner measured the windows on ffprobe 9.0.1, piping the bytes in:
     - on the 4 s-GOP source, video `pts_time` 1.48 to 4.36 s at `%+3` and 1.48 to 9.44 s at `%+8`;
     - on `h264-gop10-aac` joined 3 s in, 3.24 to 6.12 s and 3.24 to 11.20 s;
     - each run took 0.03-0.05 s.

     So the window is bounded by media time, whatever backlog the ring holds.
   - **How the feed ends.** When ffprobe exits at the interval, the relay's feed gets `EPIPE` and ends `feedWriteFailed` (`relay/hls/feed.go:34-35`). `needsFullProbe` (`relay/hls/pipeline.go:510-518`) excludes only `feedBoundary` and `feedClosed`, so the re-probe still runs when its condition holds.
   - **Size.** Pretty JSON costs about 240 B a packet: 49,929 B for 207 packets in the 3 s window measured above, and 133,238 B for 573 in the 8 s one. At the full bound, a 1080p50 source with three audio tracks lists about 8 × (50 + 3 × 32) ≈ 1,170 packets, about 280 KB. That is well inside the unchanged `io.LimitReader(…, 4<<20)`, which holds about 17,000 packets.
   - **Transcode is unchanged.** `ProbeArgv(bound)` and transcode mode stay as they are (Global constraint 6).
   - **What `ParseProbe` fills when packets are present:**
     - `Probe.Keyframes`: the count of `K` packets on the first video stream's `index`.
     - `Probe.KeyframeInterval`: the largest gap between consecutive keyframes, or 0 below two. `pts_time` is parsed to integer microseconds (ffprobe prints six decimals) and the gap is computed in `time.Duration`, never from a float difference.
     - `Probe.BitRate`: eight times the sum of the **video** stream's packet `size`, divided by the video `pts_time` span, and 0 when the span is 0. It is video only, because the multivariant adds each group's audio rate itself.
     - `Video.Index` and `Video.Level`: ffprobe's `level`, for example 30, 42 or 51 for H.264 and 63, 93, 123 or 150 for HEVC. Also `Audio.Profile`.
   - **ffprobe's `K` flag is not IDR-only** (measured). An x264 `open_gop=1` source has one IDR (`nal_unit_type` 5) in 30 s and flags every 2 s I-frame (`nal_unit_type` 1) as `K`. No packet field distinguishes them, so the plan does not try to; the open-GOP outcome is ruling R76's measurement (§ Rulings).
7. **Copy decisions are one pure function.**
   - **Signatures.** Both live in a new `relay/hls/automatic.go`, next to `DecideFor` and `PlanAutomatic`:
     - `func copyEligible(p Probe) (ok bool, reason string)` is the copy rule of § Automatic generation, as amended, on one probe. `DecideFor` calls it for generation 0, before any `Output` exists.
     - `func (o Output) VideoDecision(p Probe, forceEncode bool) (copy bool, reason string)` is a later generation's decision. It answers `(false, "forced")` when `forceEncode` is set, then applies `copyEligible`, then adds the run conditions: the declared family, the fixed width, height and frame rate, the keyframe interval, the level, and the declared bandwidth (R75).
   - **An unreadable frame rate** (`0/0`) is `frame_rate`, and fewer than two keyframes is `keyframes`, at every generation.
     - The K bound, for a later generation, is written exactly as: the probe's K must satisfy `max(2, ⌈K − 0.1⌉) ≤ o.Target`.
     - The level bound is `p.Video.Level ≤ o.Level`.
     - The bandwidth bound (R75) is `1.25 × p.BitRate ≤ max(o.VideoMaxrate, o.PeakRate)` **and** `p.BitRate ≤ max(o.VideoBitrate, o.AverageRate)`, that is, within what the multivariant already declared.
   - **The reason** is one word from a fixed set:
     - `field_order`
     - `codec`
     - `profile`
     - `bit_depth`
     - `keyframes`
     - `keyframe_interval`
     - `geometry`
     - `frame_rate`
     - `family`
     - `level`
     - `bitrate` (R75)
     - `forced` (after an over-long segment)

     The generation logs that word, so each decision test names the mechanism it expects.
   - **Field order.** `FieldUnknown` counts as progressive and `FieldInterlaced` does not (R28). The log line says "unknown, treated as progressive (R28)" when that is why.
8. **The output of an automatic run** comes from `DecideFor(p, ModeAutomatic)`.
   - **Copied generation 0.** The output keeps the source's own width, height and frame rate (never `fit()` or `outputRate()` changed). `Family` is the source's, and `Target` is `max(2, ⌈K − 0.1⌉)`.
   - **Level.** `Level` is `max(p.Video.Level, familyLevel)`, where `familyLevel` is 42 for H.264 and 123 for HEVC.
   - **Rates.** `PeakRate` and `AverageRate` are `max(VideoMaxrate, 1.25 × BitRate)` and `max(VideoBitrate, BitRate)`.
   - **Otherwise** the output is exactly `Decide(p)` (transcode's), with `Family` H.264, `Target` 2 and `Level` 42.
   - **Bitrates.** `VideoBitrate`/`VideoMaxrate` stay the table's in every case. They are what an encoded generation of the run is given, whatever the source's rate.
   - **Transcode.** `DecideFor(p, ModeTranscode)` is `Decide(p)` with `Target` 2, `PeakRate = VideoMaxrate` and `AverageRate = VideoBitrate`. So `Multivariant`'s output is unchanged in transcode.
9. **Engines, and the copy's encode fallback (R74).** `Engine` gains `EngineCopy Engine = "copy"`. A generation whose video is copied does not consult the detector, and its argv has no `-init_hw_device` and no `-vf`. `hls_encoder` reports `"copy"` while a copy runs (spec amendment). A generation that encodes into the HEVC family asks `Detector.EngineFor(ctx, FamilyHEVC)`.
   - **The copy's attempts.** Attempt 1 copies. If it exits before its first segment, attempt 2 copies again.
   - **The fallback.** If attempt 2 also exits early, the generation does not fail. It re-plans the same probe with the video forced to encode (`PlanAutomatic(…, forceEncode: true)`, reason `forced`) and runs the ordinary encode policy on the same input: an attempt on `det.EngineFor(ctx, out.Family)`, its retry, and on QSV the software attempt with `RecheckFor`/`MarkUnusableFor(out.Family)`.
   - **When the output fails.** Only when that encode path ends `outcomeFailed` does the generation fail, and only then is the channel's mark set (R74).
   - **Scope of the fallback.** It is for this generation alone. The next generation, a new connection, is decided afresh by its own probe; a copy that fails there falls back again.
   - **Numbering and logging.** Attempt numbers continue (3, 4, 5), and the log line says "a copy generation exited before its first segment twice; encoding it into the declared family".
10. **The Detector gains per-family state.** `DetectArgvFor(device, encoder string)` covers `h264_qsv` and `hevc_qsv`. `EngineFor(ctx, Family)`, `RecheckFor(ctx, Family)` and `MarkUnusableFor(Family)` hold one `checked`/`usable`/`unusable`/`warned` set per family, each under the existing `run` lock and `mu`. The seed's `Engine(ctx)`, `Recheck(ctx)` and `MarkUnusable()` become wrappers for `FamilyH264`, with their behaviour and tests unchanged. Written off on its own evidence means `hevc_qsv` failing never writes off `h264_qsv`, and the other way round.
11. **The HEVC argv.** The `-vf` chain is the same as H.264's, with `nv12`/`hwupload` for QSV and `yuv420p` for software. The `-force_key_frames "expr:gte(t,n_forced*2)"` and the `videoFragFlags` output are also the same. Then:
    - **QSV:** `-c:v hevc_qsv -preset veryfast -profile:v main -level 41 -b:v B -maxrate M -bufsize M -g G -idr_interval 0 -forced_idr 1 -tag:v hvc1`.
    - **Software:** `-c:v libx265 -preset ultrafast -x265-params keyint=G:min-keyint=G:scenecut=0:level-idc=4.1:log-level=error -b:v B -maxrate M -bufsize M -tag:v hvc1`.

    The software argv was measured on ffmpeg 9.0.1 from an MPEG-2 576i source: Main, `level=123`, `hvc1`, a keyframe every 2.000 s. The QSV argv is unrun (Q1, R45).
    - **`-level 41`** is the oneVPL `MFX_LEVEL_HEVC_41` value, which ffmpeg's `qsvenc` passes through as `CodecLevel`. It plays the same role as `-level 42` for `MFX_LEVEL_AVC_42` on `h264_qsv`, which is `relay/hls/argv.go:363`.
    - **`hevc_qsv`'s `-idr_interval` semantics** are Q1's too, and the PR body says so. A copy's argv adds `-tag:v hvc1` for HEVC only. An AAC copy is `-c:a copy -bsf:a aac_adtstoasc`; this was measured on ffmpeg 9.0.1, and without the filter the output fails with "Malformed AAC bitstream detected".
12. **Segmenting a copied generation.** The segmenter gains three fields, set after `newSegmenter` and before `run`, so `newSegmenter`'s signature and its callers are unchanged:
    - `target uint64`, the run's target in seconds;
    - `copied bool`;
    - `onOverlong func()`.

    - **The copy cut.** For a copied generation, `cutLocked` also closes the pending segment before a sync fragment `f` when `f.End() − pending[0].Start ≥ (target + ½) × timescale`, computed in integer ticks as `2·(f.End()−start) ≥ (2·target+1)·Tv`. It still closes on the 2 s grid as now.
    - **The over-long check** (copied generations only). After it appends a fragment to `pending`, it checks whether `pending`'s span (`last.End() − pending[0].Start`) has reached `(target + ½) × timescale`. The first time it has, it does four things:
      1. sets `overlong` and drops `pending` alone, which holds the over-long span and is never published;
      2. sets `tailDone`, so `cutLocked` closes nothing more for the generation and later fragments are discarded;
      3. calls `onOverlong` once;
      4. leaves `ready` alone.

      Segments already cut into `ready` publish through the normal `publishLocked` path. After the kill, every audio reader's EOF satisfies `reached()` (`relay/hls/segmenter.go:279-287`), and the seed's empty-tail rule (`:362-373`) handles a segment whose audio has no part.
    - **Encoded generations.** An encoded generation (`copied` false) takes none of these branches, which is Global constraint 6.
13. **An over-long segment ends the generation at once.** The attempt's `onOverlong` kills the process (`proc.Kill()`), and the attempt then returns a new outcome, `outcomeOverlong`. It takes precedence over every other classification except a stop (`ctx.Err()`). `run()` then does three things:
    - it counts the event in `deaths`, the 3-in-60 s bound; a third within 60 s is `ErrFailed`, exactly as `outcomeDied`;
    - it sets `forceEncode = true` for the rest of the run;
    - it restarts at `ring.Head()`.

    `PlanAutomatic` passes `forceEncode` to `VideoDecision`, which then answers `(false, "forced")`. The segments already published stand. A generation's first segment can be the over-long one; `outcomeOverlong` is then still not `outcomeEarly`, so there is no same-engine retry of a copy that would fail the same way.
14. **Per-pipeline target durations** (R42; R58).
    - **Stall limits.** `func stallLimits(target int) (stall, startup time.Duration)` returns `max(10 s, 5 × target)` and `max(StartupStallFactor × StallTimeout, stall)`. The seed's `StallTimeout` constant stays: it is the value at target 2, 10 s. So the startup allowance is 30 s at every target from 2 to 6 (R58). `Pipeline.watchLimits()` resolves the two values in this order:
      1. **The stall timeout.** `cfg.StallTimeout` when it is set, else `stallLimits(out.Target).stall`.
      2. **The startup allowance.** `cfg.StartupStallTimeout` when it is set. Otherwise, when `cfg.StallTimeout` is set, `StartupStallFactor × cfg.StallTimeout`, which is the seed's rule at `relay/hls/pipeline.go:820-827`. Otherwise `stallLimits(out.Target).startup`.

      So the seed's `TestASlowFirstFragmentIsNotKilledAsAStall` and `TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` (`relay/hls/pipeline_test.go:1108-1150`), which set only `StallTimeout = 300 ms` and rely on a 900 ms startup allowance, stay green unedited. They pin rung 2 of the startup rule.
    - **Store.** `Store.SetTargetDuration(target int)` is called by `run()` once `Output` is decided and before any publish. `MediaPlaylist` writes the store's target, and the store's byte ceiling becomes `StoreBytes × target / TargetDuration` (`publish`, `relay/hls/store.go:130`, reads the store's own ceiling in place of the constant). The eviction rule itself is unchanged: the byte ceiling stays a runaway guard, and a store that never had `SetTargetDuration` called behaves exactly as at the seed (`TestTheStoreIsBoundedAndServesBySequence`'s byte-bound assertions, `relay/hls/store_test.go:146-155`, stay green unedited).
    - **Pipeline.** `Pipeline.TargetDuration() time.Duration` is the output's target, or `TargetDuration` seconds before the output is decided.
    - **Entry waits.** `defaultReadyWait` becomes `QuickProbe.Analyze + FullProbe.Analyze + startup(MaxTargetDuration) + readyWaitMargin`, with `MaxTargetDuration = 6`. That is 3 + 8 + 30 + 2 = **43 s, unchanged**, and now derived for the longest target.
    - `AudioWait` stays a constant (4 s). It bounds a dead audio output, not a segment, and the audio outputs run ahead of a copied video's 6 s segments as they do of 2 s ones.
15. **The session's target is set at activation time.** `session.Table.SetTD(sid string, td time.Duration)` sets `s.TD` under `st.mu` for an ARRIVED session, and is a no-op for anything else. `serveHLSEntry` calls `sessions.SetTD(sid, p.TargetDuration())` after `Ready` answers nil and before `Activate`. An ARRIVED session always holds its entry request in flight (`relay/session/table.go:112-122`), so no threshold reads `TD` before then. `Session.TD`'s comment changes from "Immutable after Add" to "fixed before Activate". `Add` still sets it to `hls.TargetDuration` seconds, which the entry then overrides. A resume keeps the session's `TD`.
16. **The codec reset, and the ceiling** (the 4a-1a r5 hand-off, R4-3; R59).
    - **Reset.** `attempt` begins, under `p.mu`, with `if p.codecs == nil { delete(p.initCodecs, gen) }`, so no attempt's `noteInit` can complete a set with an earlier attempt's string. A silence fill's `noteInit` runs after the reset, in the same attempt, as now.
    - **Ceiling.** When `noteInit` adopts a map in automatic mode, the video entry goes through `declaredVideoCodec(codec string, o Output) string`:
      - **`avc1.PPCCLL`** becomes `avc1.64` + `00` + `%02x` of `max(LL, o.Level)`.
      - **`hvc1.<space+profile>.<compat>.<T><level>[.<constraints>…]`** keeps every field and replaces `<level>` with `max(level, o.Level)`.
      - **Anything unparsable** is returned as-is and logged once at WARNING, with the codec string only.
    - **Transcode** never calls it.

## Rulings on this plan's questions

The orchestrator ruled the round-0 draft's six open questions as recommended (R58-R63), and four of round 1's findings (R74-R77). Each is recorded in the orchestrator's `rulings.md` and amended into the spec by this PR (§ Spec amendments).

1. **R58: the startup allowance at a target of 6** (R42 × R55 × R57). The allowance is `max(30 s, stall(TD))`, 30 s at every TD ≤ 6 (Decision 14), so R57's waits stay 43 s, under nginx's 60 s `proxy_read_timeout` on `/hls/`.
   - **Why not R55's literal "3 × max(10 s, 5 × TD)".** That is 90 s at TD 6, and it would push the derived wait to 3 + 8 + 90 + 2 = 103 s. A multivariant timing out at nginx answers 504.
   - **Why 30 s is enough.** The slow start R55 covers is an encoder's cold start (deinterlacer lookahead plus one GOP), and every encoded generation's GOP is 2 s whatever the target.
   - **A copy** writes its first fragment when its first GOP closes: at most 2 × K = 12 s of media.
   - **After the first fragment**, `stall(TD)` of 30 s at TD 6 covers a 6 s GOP five times over.
2. **R59: the video `CODECS` of an automatic run is the family ceiling** (R4-3; Decision 16).
   - **The rule.** H.264 is High at the higher of the copied level and 4.2. HEVC is the copied string with its level raised to at least 4.1, and the encoded HEVC is pinned at 4.1.
   - **Later sources.** A later source above the declared level is encoded, never copied.
   - **What the E2E asserts.** The multivariant declares the ceiling while the init segment carries the source's own string, and the E2E asserts both. The spec's E2E phrase is amended.
3. **R60: the copy rule's implicit conditions** (Decisions 7-8). Each one keeps a declared attribute (`RESOLUTION`, `FRAME-RATE`, `CHANNELS` or `CODECS`) true after a discontinuity:
   - H.264 only as Constrained Baseline, Baseline, Main or High, in 8-bit 4:2:0;
   - no larger than 1920×1080 and no faster than 60 fps, because a copy cannot be scaled;
   - AAC copied only as LC stereo;
   - later generations copy only against the run's fixed output, family, target and level.
4. **R61: target duration and the copy cut.**
   - **`TARGETDURATION` = max(2, ⌈K − 0.1 s⌉).** The spec's ⌈K⌉ gave a 2.002 s GOP a target of 3.
   - **The copy segmenter closes before a keyframe that would reach TD + 0.5 s.** "Cut at the first keyframe at or after 2 s" alone lets a 1.92 s GOP make a 3.84 s segment.
   - **The over-long threshold is ≥ TD + 0.5 s,** because RFC 8216 § 4.3.3.1 rounds 2.5 to 3.
5. **R62: the store's byte ceiling scales with TD** (192 MiB at TD 6; Decision 14).
   - **RFC 8216 § 6.2.2 retention** holds in full up to about 12.8 Mb/s at TD 6. The ten listed segments fit up to about 26.8 Mb/s.
   - **Above that**, listed segments can be evicted by the runaway guard. This is recorded as a residual risk.
6. **R63: a K the full probe cannot observe is encoded** (accepted). The bound is 5 MB or 8 s of media (§ Residual risks).
7. **R74: a copy generation whose attempts fail falls back to an encode** into the run's declared family, as Quick Sync falls back to software (Decision 9). The channel-wide mark is set only when that encode fails too. Pinned by `TestAFailedCopyFallsBackToAnEncode` and `TestAFailedCopyAndAFailedEncodeFailTheOutput`, and by break-check 16.
8. **R75: a later generation copies only if its probe window's video rate fits the bandwidth the multivariant already declared** (Decision 7's `bitrate` reason), on top of every R60 condition; otherwise it is encoded. Pinned by the `bitrate` row of `TestALaterGenerationCopiesOnlyAgainstTheFixedOutput`, and by break-check 17.
9. **R76: open-GOP sources.** AVPlayer tolerated them, so this is a residual risk and copy does not require a closed GOP. The planner measured it on 2026-09-29, on macOS 27 and the iOS 27 Simulator (iPhone 18 Pro), with the Appendix B `probe2` binaries.
   - **The source.** 30 s of x264 `-g 50 -bf 3 -x264-params open_gop=1`, 1280x720 at 25 fps, plus AAC, in MPEG-TS. It carried one IDR, and every other 2 s keyframe was a non-IDR I-frame that ffprobe flags `K`.
   - **The copy.** It was copied with this plan's video copy and AAC copy argv (`-c:v copy`, `-c:a copy -bsf:a aac_adtstoasc`) into 2 s fMP4 segments, each starting on such an I-frame.
   - **A live join onto an open-GOP segment**, which needs no ENDLIST:
     - open GOP: `status=1`, 144 frames on both macOS and iOS, no error;
     - closed-GOP control: 146 frames on both.
   - **A discontinuity from a closed-GOP generation into an open-GOP segment** (20 s):
     - open GOP: 494 frames on macOS and 492 on iOS, no error;
     - closed-GOP control: 496 and 493.
   - **What was not measured.** The count is of decoded frames, not of visual artefacts: an open-GOP segment's leading B-frames reference the previous GOP, which is absent after a join or a discontinuity. `EXT-X-INDEPENDENT-SEGMENTS` is therefore not strictly true of a copied open-GOP source. HEVC CRA open GOPs, x265's default, were not measured.
   - **Owed.** An open-GOP run is added to the owner's AVPlayer check (§ Gates).
10. **R77: automatic mode's ffprobe carries `-read_intervals %+<analyze>`,** and the size estimate is corrected (Decision 6).

## The design

### Django: the models and migrations

- **`core/models.py`** (`OutputProfile`, `:169-203`).
  - Add `hls_mode` (Decision 1) and the two constants.
  - `build_command` is unchanged. It is never called on an HLS row, because every consumer that builds an argv excludes them (the next-source map, Decision 3).
  - The docstring gains one paragraph: "A row with a non-blank `hls_mode` is an HLS profile. The relay builds its argv from a probe (spec D12), so its `command`/`parameters` are placeholders. It is chosen per channel, never per client, and excluded from every other consumer."
- **`core/migrations/0029_outputprofile_hls_mode.py`.**
  - It depends on `("core", "0028_alter_streamprofile_parameters")`.
  - Its operations are `AddField(model_name="outputprofile", name="hls_mode", …)`, then `RunPython(seed_hls_output_profiles, remove_hls_output_profiles)`.
  - `seed_…` uses `apps.get_model` and does the Decision 1 collision rename, then `create`.
  - `remove_…` deletes rows with `hls_mode__in=["transcode", "automatic"]`. A reverse migration runs `RunPython`'s reverse before `AddField`'s reverse, so the rows go before the column.
- **`apps/channels/models.py`** (`Channel`, beside `stream_profile` at `:344-350`). Add:

  ```python
  hls_output_profile = models.ForeignKey(
      "core.OutputProfile", on_delete=models.SET_NULL, null=True, blank=True,
      related_name="hls_channels",
      help_text="HLS Output Profile for this channel (null: the built-in re-encode).",
  )
  ```

  `related_name` is set so the reverse accessor never collides with a future per-client FK.
- **`apps/channels/migrations/0039_channel_hls_output_profile.py`.** It depends on `("dispatcharr_channels", "0038_add_catchup_fields")` and `("core", "0029_outputprofile_hls_mode")`, and its one operation is `AddField`. It is generated with `uv run python manage.py makemigrations dispatcharr_channels` (the label, never the directory name; CLAUDE.md § Test hooks), then renamed.

### Django: serializers, viewset and exclusions

- **`core/serializers.py:37-40`.** Add `"hls_mode"` to `fields` and set `read_only_fields = ["hls_mode"]`.
- **`core/api_views.py:77-89`** (`OutputProfileViewSet`). Add `perform_update` and `perform_destroy`, which raise `PermissionDenied(detail=…)` when `instance.hls_mode` is non-blank (Decision 2), else `super()`. The queryset is unchanged, because the list must show the HLS rows so the channel form can offer them.
- **`apps/channels/serializers.py`** (`ChannelSerializer`).
  - Add `hls_output_profile_id = serializers.PrimaryKeyRelatedField(queryset=OutputProfile.objects.exclude(hls_mode=""), source="hls_output_profile", allow_null=True, required=False)`, next to `stream_profile_id` (`:393-398`).
  - Add `"hls_output_profile_id"` to `Meta.fields` after `"stream_profile_id"` (`:450`).
  - An ordinary Output Profile's id is refused with DRF's "Invalid pk", a 400. It is not an override field: `OVERRIDABLE_FIELDS` (`apps/channels/managers.py`, mirrored at `frontend/src/utils/forms/ChannelUtils.js:5-14`) is unchanged, and auto-sync never writes it.
- **The exclusions** (D12; spec § Verified facts' consumer list):
  - `apps/proxy/authorize.py:226-244` (`resolve_output_profile`): both `OutputProfile.objects.get(…, is_active=True)` calls gain `hls_mode=""`. The `.objects` count is unchanged (the boundary pin in `test_tune_path_query_ledger.py:260-270`).
  - `apps/hdhr/api_views.py:114` (`_resolve_hdhr_output_profile_id`): `get(id=candidate, is_active=True, hls_mode="")`. An HLS id then logs the existing WARNING and serves with no profile.
  - The next-source map: Decision 3.
  - The viewset's writes: Decision 2.
  - The frontend selects: below.

### Django: next-source `hls_profile`

- **`apps/proxy/serializers.py:247-259`.**
  - Add `class HLSProfileRefSerializer(serializers.Serializer): id = IntegerField(); mode = ChoiceField(choices=["transcode", "automatic"])`.
  - `NextSourceResponseSerializer` gains `hls_profile = HLSProfileRefSerializer(allow_null=True)`, which puts it in the drf-spectacular schema.
- **`apps/proxy/next_source.py:868-926, 1046-1085`**: Decision 3. The `_with_output_profiles` docstring gains a paragraph naming D12's exclusion and why the HLS profile rides this loop, which is that it costs no query.

### Frontend

- **`frontend/src/utils/outputProfiles.js`** (new): `isHlsOutputProfile(p)`, which is `Boolean(p?.hls_mode)`; `selectableOutputProfiles(profiles)`, which filters out HLS rows; and `hlsOutputProfiles(profiles)`, which is the active HLS rows. These are pure functions. The Zustand store (`store/outputProfiles.jsx`) is unchanged: the rows carry `hls_mode` from the API.
- **The exclusions**, which compose the filter with each site's existing one:
  - `components/forms/User.jsx:352-354`;
  - `components/forms/settings/StreamSettingsForm.jsx:208-210` (HDHR);
  - `components/forms/settings/UiSettingsForm.jsx:183-186` (the web player). This site has no `is_active` filter today, and none is added.
  - `components/tables/ChannelsTable.jsx:1288-1290` (the HDHR URL builder) and `:1421-1423` (the M3U-link builder).
  - The display lookup in `StreamConnectionCard.jsx:419-421` is **not** filtered. It names whatever profile id a client carries, and an HLS client carries none (4a-1b ignores `X-Relay-Output` on an `hls` tune).
- **`components/tables/OutputProfilesTable.jsx`**: no change. Its active toggle, edit and delete are already `disabled={row.original.locked}` (`:32`, `:41`, `:122`), and both HLS rows are locked (Decision 2).
- **The channel form, `components/forms/Channel.jsx`.** An "HLS output" `Select` goes directly after the Stream Profile select (`:1211-1248`):
  - `id="hls_output_profile_id"`, `label="HLS output"`, `size="xs"`;
  - `description="Automatic copies what Apple devices accept and re-encodes the rest"`;
  - `data=[{value: '0', label: '(built-in re-encode)'}].concat(hlsOutputProfiles(outputProfiles).map(…))`, with `outputProfiles` from `useOutputProfilesStore`.

  It is a plain channel field, never an override, with no `ProviderHintRow`.
- **`utils/forms/ChannelUtils.js`.**
  - `getChannelFormDefaultValues` adds `hls_output_profile_id: channel?.hls_output_profile_id ? \`${…}\` : '0'`.
  - `getFormattedValues` maps `'0'`/empty to `null`.
  - `handleEpgUpdate`'s auto-created branch (`:229-246` in the seed's excerpt) adds `hls_output_profile_id: formattedValues.hls_output_profile_id` to the direct payload next to `hidden_from_output`, because it is a status field, not a provider value.
  - The manual branch sends it with the rest of the PATCH.
  - `normalizeFieldValue` treats `hls_output_profile_id` as `stream_profile_id` is treated, where `'0'` becomes `null`.

### `relay/control` and `relay/channel`

- **`relay/control/nextsource.go`.**
  - `type HLSProfileRef struct { ID int \`json:"id"\`; Mode string \`json:"mode"\` }`.
  - `NextSourceAnswer.HLSProfile *HLSProfileRef \`json:"-"\`` and `HLSProfilePresent bool \`json:"-"\``.
  - `UnmarshalJSON` reads `hls_profile` as a `json.RawMessage` beside `output_profiles`. Absent gives present=false. `null` gives present=true with a nil ref. An object gives present=true with the ref. A malformed object is a decode error, as a malformed `output_profiles` is.
- **`relay/channel`.** Beside `OutputProfiles` (`output.go:48-65`):
  - `type HLSProfile struct { Known bool; ID int; Mode string }`, with `func (h HLSProfile) Key() string`, which gives `"hls"` when `ID == 0` and `"hls:p<ID>"` otherwise.
  - `Started.HLSProfile` and `Resolved.HLSProfile`.
  - `Channel.hlsProfile` is set in `publish` (`manager.go:266-274`) and replaced in `applySwitch` only when `resolved.HLSProfile.Known` (`failover.go:257-272`, under the same `c.mu`).
  - `func (c *Channel) HLSProfile() HLSProfile` returns it under `c.mu`.
  - `HLSStatus` follows Decision 5.
- **`relay/httpapi`.** `hlsProfileFrom(answer) channel.HLSProfile` goes beside `outputProfilesFrom` (`profile.go:130-139`), and is used at `stream.go:773` and `failover.go:63`. The degraded path at `:72` passes a zero value, `Known` false, which keeps the channel's own.
- **`relay/internal/relaytest/controlplane.go`.**
  - `ControlPlaneConfig` gains `HLSProfile *HLSProfileConfig` (`{ID int; Mode string}`) and `HLSProfileAbsent bool`.
  - `SetHLSProfile` mirrors `SetOutputProfiles` (`:282`).
  - The answer builder emits `"hls_profile": nil` by default, the object when configured, and nothing when absent (`:552-571`).

  This is a test-support edit (§ Tests changed).

### `relay/hls`

- **`probe.go`.** Decision 6: `ProbeArgvFor`, the new `probeJSON` fields (`index`, `level`, `profile` on audio, and a `Packets []struct{StreamIndex int; PtsTime string; Flags string; Size string}`), and the new `Probe`/`Video`/`Audio` fields. `pipeline.probe` (`pipeline.go:523`) calls `ProbeArgvFor(bound, p.cfg.Mode)`. R37's `needsFullProbe` (`:510-518`) is unchanged and now reads a real count. That is the wiring R37 asked for.
- **`argv.go`.**
  - `Family` has the values `FamilyH264` (the zero value) and `FamilyHEVC`, with `String()`.
  - `Output` gains `Family`, `Target int`, `Level int`, `PeakRate`, `AverageRate`, and `Automatic bool`; the last says whether `declaredVideoCodec` applies.
  - `Plan` gains `VideoCopy bool` and `Family`.
  - `Argv`, for a video copy: no hardware device, no `-vf`, `-map 0:v:0 -c:v copy` plus `-tag:v hvc1` for HEVC, and then the existing `-f mp4 -movflags videoFragFlags pipe:1`.
  - `Argv`, for a HEVC-family encode: Decision 11.
  - `audioCodecArgs`, for an `aac` `FillCopy`: `-c:a copy -bsf:a aac_adtstoasc`. AC-3 and E-AC-3 copies are unchanged.
  - `Decide(p)` is unchanged. `DecideFor` goes in `automatic.go`.
- **`automatic.go`** (new): `DecideFor`, `copyEligible` and `VideoDecision` (Decision 7), `targetFor(k time.Duration) int`, `PlanAutomatic(o Output, p Probe, engine Engine, gen int, forceEncode bool) Plan`, and `declaredVideoCodec`.
  - For audio, `PlanAutomatic` fills the `aac` rendition by copy when the first qualifying stream is `aac`, has profile `LC` and has 2 channels. Otherwise it fills as `PlanGeneration` does.
  - For `ac3` and `eac3` it is exactly `PlanGeneration`'s rule.
  - For video, it is `VideoDecision`.
- **`detect.go`.** Decision 10.
- **`pipeline.go`.**
  - `Config.Mode` is already present, and `startPipeline` now sets it.
  - `run`: when `first`, the output is `DecideFor(probe, p.cfg.Mode)`, followed by `p.store.SetTargetDuration(out.Target)`. The loop also handles `outcomeOverlong` and `forceEncode` (Decision 13).
  - `generation`: in automatic mode it computes the plan's video decision before the engine. For a copy it runs attempts 1 and 2 on `EngineCopy` and then R74's encode fallback (Decision 9); for an encode it asks `det.EngineFor(ctx, out.Family)`, and the QSV → software → `RecheckFor`/`MarkUnusableFor(out.Family)` path is kept.
  - `attempt`: it begins with the codec reset (Decision 16), sets `p.engine = plan.Engine`, sets the segmenter's `target`/`copied`/`onOverlong` (Decision 12), and classifies `outcomeOverlong` (Decision 13). It logs the video decision and its reason once per attempt (`"HLS video"`, `fill`=`copy|encode`, `reason`).
  - `watch`: uses `watchLimits()` (Decision 14).
  - `noteInit`: applies `declaredVideoCodec` when `p.output.Automatic` (Decision 16).
  - `TargetDuration()` is new.
- **`segmenter.go`**: Decision 12. **`store.go`**: Decision 14. **`playlist.go`**: `Multivariant` uses `max(o.VideoMaxrate, o.PeakRate)` for `BANDWIDTH`'s video part and `max(o.VideoBitrate, o.AverageRate)` for `AVERAGE-BANDWIDTH`'s (Decision 8). For an output with `PeakRate`/`AverageRate` zero, including the seed's `TestTheMultivariant` literals (`relay/hls/store_test.go:183-213`), that is exactly the seed's figure, so that test stays unedited. Its doc comment's "lands with it in 4a-1d" sentence becomes the rule.

### `relay/httpapi` and `relay/session`

- **`hls.go`.**
  - `serveHLSEntry` first requires `ch.HLSProfile()` to be `Known` with a recognized mode (or `ID == 0`); otherwise it releases and answers 502 contract mismatch (Decision 4). It then computes `key := prof.Key()` and passes it to `AttachHLS`, `watchHLS`, `FailHLS` and `session.Session.Key`, replacing the constant `hlsKey`, which stays as the zero-profile key.
  - `startPipeline` passes `Mode` (`ModeAutomatic` for `"automatic"`, else `ModeTranscode`).
  - After a nil `Ready`: `sessions.SetTD(sid, p.TargetDuration())` (Decision 15).
  - `defaultReadyWait`: Decision 14.
- **`relay/session/table.go`**: `SetTD` (Decision 15).

## PR 4a-1d: the automatic HLS profile

### Tasks

Each task ends green on the hooks for the files it touched (CLAUDE.md § Test hooks). Stage and commit in separate calls, and commit with `-F`.

1. **Models and migrations.** Decision 1; § The models and migrations. Tests: § Tests added, Django group 1.
2. **Serializers, viewset and backend exclusions.** Tests: Django groups 2-3.
3. **Next-source `hls_profile`**, and the Python Gate 2 run (`scripts/coverage_live_path_isolated.sh`; `authorize.py` and `next_source.py` are coveragerc modules): every new line covered, `missing` still 33. Tests: Django group 4.
4. **Frontend.** Tests: the frontend group. `npm test` and `npm run build` must pass.
5. **The relay's `hls_profile` plumbing**: control, channel, the httpapi conversion, and the stub. Tests: the Go group "plumbing".
6. **The automatic probe** (Decision 6). Tests: Go group "probe".
7. **Decisions, argv and detector** (Decisions 7-11). Tests: Go group "decisions".
8. **Pipeline, segmenter, store and codecs** (Decisions 12-16). Tests: Go groups "pipeline" and "real".
9. **Entry and session** (Decisions 4, 5, 15). Tests: Go group "entry".
10. **E2E**: `e2e/tests/streaming/hls-automatic.spec.ts`, plus these fixture changes:
    - `e2e/fixtures/seed.ts`'s `upstreamChannel` gains `opts.hlsOutputProfileId`, sent as `hls_output_profile_id`, and `types.ts`'s `Channel`/`ChannelCreate` gain the field.
    - The seed gains `hlsOutputProfileByName(api, name)`, a `GET /api/core/outputprofiles/` filter.
    - `e2e/fixtures/hls.ts`'s `InitSummary` (`:207-243`) gains `codec: string`, read from the video sample entry's `avcC` (`avc1.` plus the profile, constraint and level bytes in hex) or `hvcC`. `initSummary` fills it, and the existing callers ignore it.
11. **Documentation.** Apply Appendix A: the parity rows, the rows 36 and 43 amendments, `e2e/COVERAGE.md`, and CLAUDE.md's Video-path sentence. Raise `HIGHEST_ROW_ID` in `e2e/tests/guards/parity-matrix.ts` to the last new id.
12. **The Go census and floor** (§ Coverage), then the PR body.

### Tests added

Every oracle is a literal, never a value the code under test computes.

**Seeded rows are never assumed** (round 1, finding 6). A `TransactionTestCase` earlier in the same process flushes every table at teardown, and under `--keepdb` that removes the migrations' seeded rows. That applies to this PR's own migration tests, and to the repository's existing ones (`apps/proxy/tests/test_next_source_api.py:572-583`).
- **Every non-migration test below** gets its HLS rows by `OutputProfile.objects.get_or_create(name=…, defaults={"hls_mode": …, "command": "ffmpeg", "parameters": "(built by the relay)", "locked": True, "is_active": True})`, then sets `hls_mode`, `locked` and `is_active` explicitly.
- **It creates its own ordinary rows** under test-unique names. "The AC3 row" and "`Web Player (AAC Audio)`" below mean such a created row.

**Django group 1: migrations** (`core/tests/test_output_profile_hls_migration.py`, `apps/channels/tests/test_hls_output_profile_migration.py`; `TransactionTestCase` with `django.db.migrations.executor.MigrationExecutor`, and `tearDown` migrating forward to the leaf). Each test first migrates **back** and then forward, and asserts only after its own forward, never on the state it found.

- `test_the_core_migration_seeds_two_locked_hls_rows_and_its_reverse_removes_them`:
  - **Back** to `core 0028`, which first takes `dispatcharr_channels` back to `0038`: no row has those names, and the `hls_mode` column is absent (`connection.introspection.get_table_description`).
  - **Forward:** exactly the two names, with `hls_mode` values `transcode` and `automatic`, `locked` True, `is_active` True, `command` `"ffmpeg"` and `parameters` `"(built by the relay)"`.
  - **Back again:** the rows and the column are gone.
  - **Forward again** (in `tearDown`, to the leaf).
- `test_a_pre_existing_row_with_a_seeded_name_is_renamed_not_overwritten`: roll back and create `OutputProfile(name="HLS (Automatic)", command="ffmpeg", parameters="-i pipe:0 pipe:1")`. After migrating forward, that row's name is `"HLS (Automatic) (custom)"`, with `hls_mode` `""` and its `parameters` unchanged.
- `test_the_channels_migration_adds_and_removes_hls_output_profile`: back at `0038` the column is absent; forward it exists; back again it is absent; forward again it exists. A channel created after the first forward, with the FK set, survives the next round trip, and its FK is null after the re-forward.

**Django group 2: serializers and viewset** (`core/tests/test_output_profile_hls_api.py`, `apps/channels/tests/test_channel_hls_output_profile.py`).

- `test_hls_mode_is_listed_and_read_only_on_create`: the GET list includes `hls_mode` on every row. A POST sending `"hls_mode": "automatic"` creates a row with `hls_mode == ""`.
- `test_an_hls_row_cannot_be_updated` (PATCH `{"is_active": false}`) and `test_an_hls_row_cannot_be_deleted` each expect 403 with the literal detail, and the row unchanged or present.
- `test_an_ordinary_row_is_still_editable_and_deletable`: 200 and 204.
- `test_a_channel_accepts_an_hls_output_profile_and_refuses_an_ordinary_one`: PATCH with the automatic row's id (`get_or_create`d) gives 200 and the response echoes it. PATCH with an ordinary row's id (created by the test) gives 400 naming `hls_output_profile_id`. PATCH with `null` gives 200 and null.
- `test_deleting_the_profile_nulls_the_channel` (ORM, which SET_NULL covers): `OutputProfile.objects.filter(hls_mode="automatic").delete()`, and the channel's FK is then null.

**Django group 3: the exclusions.**

- `apps/proxy/tests/test_authorize_output_profile.py` (new), `test_an_hls_profile_in_the_query_resolves_to_none` and `test_an_hls_profile_in_custom_properties_resolves_to_none`: `resolve_output_profile` with `?output_profile=<automatic id>`, and a user whose `custom_properties.output_profile` is that id, each returns `None`. The two controls with the AC3 row's id each return that row.
- `apps/output/tests/test_hdhr_output_profile.py`, `test_the_hdhr_resolver_ignores_an_hls_profile_from_the_url_and_the_default` (`apps/hdhr/` has no tests of its own, and `dispatcharr/test_discovery.py:52` routes it to `apps.output` and `apps.channels`): `_resolve_hdhr_output_profile_id(<automatic id>)` is `None`. With `stream_settings.hdhr_output_profile_id` set to it, `_resolve_hdhr_output_profile_id(None)` is `None`. The WARNING is logged in both cases (`assertLogs`).

**Django group 4: next-source** (`apps/proxy/tests/test_next_source_api.py`, new methods on the existing class).

- `test_hls_profile_is_null_without_a_choice`: `answer["hls_profile"] is None`.
- `test_the_channels_automatic_profile_travels_as_hls_profile`: set the channel's FK to the automatic row (`get_or_create`d, then set active, because setUp deactivates every row). The answer is `{"id": <literal id read before the call>, "mode": "automatic"}`.
- `test_an_inactive_hls_profile_travels_as_null`.
- `test_hls_rows_never_enter_output_profiles`: `get_or_create` both HLS rows active, and create one active ordinary row. `answer["output_profiles"]` has exactly the ordinary row's key.
- `test_a_stream_preview_carries_a_null_hls_profile` (identifier = a stream hash) and `test_the_404_carries_a_null_hls_profile`.
- The existing ledger tests (`test_tune_path_query_ledger.py`) are the oracle for "no new query", and are unchanged.

**Frontend** (vitest).

- `utils/__tests__/outputProfiles.test.js`: the three helpers over a literal list (ordinary active, ordinary inactive, HLS transcode, HLS automatic inactive).
- `components/forms/__tests__/User.test.jsx`, `it('offers no HLS output profile')`: the select's options exclude a store row with `hls_mode: 'automatic'`.
- `components/forms/settings/__tests__/StreamSettingsForm.test.jsx`, `it('omits HLS profiles from the HDHR output profile select')`.
- `components/forms/settings/__tests__/UiSettingsForm.test.jsx` (the existing file), a new `it('omits HLS profiles from the web player select')`.
- `components/tables/__tests__/ChannelsTable.test.jsx`, `it('omits HLS profiles from both link builders')`.
- `components/forms/__tests__/Channel.test.jsx`:
  - `it('offers only HLS profiles and the built-in re-encode in the HLS output select')`;
  - `it('submits hls_output_profile_id')` (manual channel: the PATCH payload has the literal id; `'0'` sends `null`);
  - `it('sends hls_output_profile_id beside hidden_from_output for an auto-created channel')`.
- `utils/forms/__tests__/ChannelUtils.test.js`: the default value, the formatted value and the normalize value for the field.

**Go group "plumbing".**

- `relay/control/hlsprofile_test.go`, `TestTheHLSProfileKeyDecodesInThreeStates`: this is a table test.
  - An absent key gives present=false with a nil ref.
  - `null` gives present=true with a nil ref.
  - `{"id": 7, "mode": "automatic"}` gives present=true with `{7, "automatic"}`.
  - `{"id": "x"}` gives a decode error.
- `relay/channel/hlsprofile_test.go`, `TestAFailoverAnswerRefreshesTheHLSProfile`: `applySwitch` with `Known` replaces the channel's profile, and a degraded `Resolved` (`Known` false) keeps it.
- `relay/channel/hlsprofile_test.go`, `TestTheHLSProfileKey`: `{}` gives `"hls"`, and `{ID: 7}` gives `"hls:p7"`.

**Go group "probe"** (`relay/hls/probe_test.go`).

- `TestTheAutomaticProbeArgvListsVideoPackets`: the argv is checked against literals.
  - `ProbeArgvFor(QuickProbe, ModeAutomatic)` is the literal slice `"-hide_banner", "-loglevel", "error", "-probesize", "3000000", "-analyzeduration", "3000000", "-f", "mpegts", "-i", "pipe:0", "-read_intervals", "%+3", "-show_streams", "-show_entries", "packet=stream_index,pts_time,flags,size", "-of", "json"`.
  - `ProbeArgvFor(FullProbe, ModeAutomatic)` carries `"%+8"`.
  - `ProbeArgvFor(QuickProbe, ModeTranscode)` equals the literal seed argv, with no `-read_intervals`.
- `TestParseProbeCountsKeyframesTheirLongestIntervalAndTheRate`: a literal JSON.
  - **The input.** Video `index` 0 has key packets at `1.480000`, `5.480000` and `9.480000`, and one non-key packet at `9.480000`, whose sizes sum to 1,000,000 bytes over a video span of 8.0 s. Audio key packets on `index` 1 carry 500,000 bytes, and are counted in neither total.
  - **The result.** `Keyframes == 3`, `KeyframeInterval == 4 s` and `BitRate == 1_000_000`.
  - **Integer arithmetic.** A second case with keys at `0.000000` and `2.100000` gives `KeyframeInterval == 2100 * time.Millisecond` exactly, so `targetFor` gives 2, not 3.
- `TestParseProbeReadsLevelIndexAndAudioProfile`: `Video.Level == 123`, `Video.Index == 0`, and `Audio.Profile == "LC"`.

**Go group "decisions"** (`relay/hls/automatic_test.go`).

- `TestTheAutomaticCopyDecision`: a table test on `copyEligible` (generation 0), giving the result, then the reason.

  | # | Source | Result | Reason |
  |---|---|---|---|
  | 1 | h264 High yuv420p progressive, 640x360, 25/1, K 2 s, 2 keyframes | copy | — |
  | 2 | HEVC Main yuv420p, `field_order` **unknown** (R28, #525) | copy | — |
  | 3 | HEVC Main, progressive | copy | — |
  | 4 | h264 `tt` | encode | `field_order` |
  | 5 | mpeg2video | encode | `codec` |
  | 6 | HEVC Main 10, `yuv420p10le` | encode | `bit_depth` |
  | 7 | HEVC `Rext` | encode | `profile` |
  | 8 | h264 High 10 | encode | `profile` |
  | 9 | h264 `yuv422p` | encode | `bit_depth` |
  | 10 | K 6.0 s | copy | — |
  | 11 | K 6.5 s | encode | `keyframe_interval` |
  | 12 | 1 keyframe | encode | `keyframes` |
  | 13 | 3840x2160 | encode | `geometry` |
  | 14 | 120/1 | encode | `frame_rate` |

  Every failure message names the row, the expected reason and the reason it got.
- `TestTheAutomaticTargetDuration`: `targetFor` gives:
  - 2 for 1.0 s, 2.0, 2.002, 2.09 and 2.1 (exact `time.Duration`s);
  - 3 for 2.11 and 3.0;
  - 4 for 4.0;
  - 6 for 5.95 and 6.0.
- `TestALaterGenerationCopiesOnlyAgainstTheFixedOutput`: an output from copied h264 1280x720 at 50/1, `Target` 2 and `Level` 42. The generation-1 rows are:
  - a match gives copy;
  - 1920x1080 gives `geometry`;
  - 25/1 gives `frame_rate`;
  - K 4 s gives `keyframe_interval`;
  - HEVC gives `family`;
  - level 51 gives `level`;
  - `BitRate` 10,000,000 against a declared `PeakRate` of 1.25 × 4,000,000 (a copied 4 Mb/s generation 0 at 1280x720, `VideoMaxrate` 5,000,000) gives `bitrate` (R75);
  - `forceEncode` gives `forced`.
- `TestTheAutomaticAudioFills`: AAC LC stereo gives `FillCopy`. AAC LC 6 channels, `HE-AAC` stereo and mp2 each give `FillEncode` into `aac`. The `ac3`/`eac3` fills equal `PlanGeneration`'s on the same probe.
- `TestTheCopyArgv`:
  - For an HEVC copy with a copied AAC, the argv literal has no `-init_hw_device` even with `EngineQSV` passed in, no `-vf`, `-map 0:v:0 -c:v copy -tag:v hvc1`, the `videoFragFlags` output, and `-c:a copy -bsf:a aac_adtstoasc` on `pipe:3`.
  - The H.264 copy has no `-tag:v`.
- `TestTheHEVCFamilyArgv`: the QSV and software literals of Decision 11, in full.
- `TestDecideForKeepsTranscodeUnchanged`: `DecideFor(p, ModeTranscode)` equals `Decide(p)` in every seed field, with `Target` 2 and `PeakRate`/`AverageRate` equal to the maxrate and bitrate. On a copy-eligible probe, `PlanAutomatic` is never reached in transcode (the pipeline test below).
- `TestTheDeclaredVideoCodecIsTheFamilyCeiling`: at `Level` 42/123:
  - `avc1.4d401e` becomes `avc1.64002a`;
  - `avc1.640033` stays `avc1.640033`;
  - `hvc1.1.6.L93.B0` becomes `hvc1.1.6.L123.B0`;
  - `hvc1.1.6.L150.90` stays unchanged;
  - `mp4a.40.2` (not video) is returned as-is;
  - `garbage` is returned as-is.
- `relay/hls/detect_test.go`, `TestHEVCDetectionIsItsOwnAnswer`: a stand-in `Command` records argv.
  - `EngineFor(ctx, FamilyHEVC)` runs one encode whose argv contains `hevc_qsv`.
  - `Engine(ctx)` then runs its own `h264_qsv` encode.
  - `MarkUnusableFor(FamilyHEVC)` leaves `Engine(ctx)` at `EngineQSV`.

**Go group "pipeline"** (`relay/hls/automatic_pipeline_test.go`, using the seed's stand-in harness in `helpers_test.go`).

- `TestACopiedGenerationCutsWithinTheTargetDuration`: segmenter unit, driven with synthetic fragments at timescale 90000.
  - 1.92 s GOPs at `target` 2 give every segment 1.92 s, and none is over-long.
  - 4 s GOPs at `target` 4 give 4 s segments.
  - Irregular 0.5/0.5/1.2/0.4 s GOPs at `target` 2 give segments that each close on the grid or before 2.5 s.
- `TestAnOverLongCopiedFragmentEndsTheGeneration`: segmenter unit at `target` 2, with a 2.0 s sync fragment and then a 2.5 s one, run in two variants. The one audio track (`aac`) is fed 200 ms fragments covering [0, 2.0 s), so the 2.0 s segment has audio. That segment becomes the generation's last once `tailDone` is set, and the seed's empty-tail rule (`relay/hls/segmenter.go:362-373`) would otherwise drop it.
  - **(a)** Each fragment arrives on its own wake.
  - **(b)** Both are queued before the segmenter's first wake.
  - **The oracle for each.** `onOverlong` is called once. The store holds exactly one segment, the 2.000 s one, with a non-empty `aac` part, published after its audio reader reaches EOF. No 2.5 s segment is ever published, and a third fragment fed afterwards is discarded.
- `TestAnEncodedGenerationIgnoresTheCopyCut`: the same 2.5 s fragment with `copied` false is published as the seed publishes it, as one segment, with no call. This pins Global constraint 6.
- `TestAnOverLongCopiedSegmentRestartsTheRunEncoded` (stand-in). The probe says h264 K 2 s, so generation 0 copies. The encoder stand-in writes one 3 s fragment.
  - The generation ends as over-long.
  - The next `Spawn` is generation 1, with an argv containing `libx264` and no `-c:v copy`.
  - The store never lists the 3 s segment.
  - `Engine()` is `software` after it.
- `TestOverLongRestartsCountTowardTheRestartBound`: three over-long generations within `deathWindow` give `Err() == ErrFailed`.
- `TestAFailedCopyFallsBackToAnEncode` (R74, stand-in): the probe says h264 K 2 s, so the generation copies.
  - The stand-in exits before a segment whenever its argv contains `-c:v copy`, and succeeds otherwise.
  - **The oracle.** The `Spawn`s are attempts 1 and 2, both with `-c:v copy`, then attempt 3 with `libx264`. The generation publishes segments, `Err()` stays nil, the channel is not marked, and `Engine()` is `software`.
- `TestAFailedCopyAndAFailedEncodeFailTheOutput` (R74): the same, with the stand-in failing every argv. The generation ends `outcomeFailed`, and `Err() == ErrFailed`.
- `TestTheStallLimitsFollowTheTargetDuration`: `stallLimits(2)` is `(10 s, 30 s)`, `stallLimits(4)` is `(20 s, 30 s)` and `stallLimits(6)` is `(30 s, 30 s)`. `p.watchLimits()` on pipelines with an output set checks Decision 14's order:
  - `Target` 6 with no overrides gives `(30 s, 30 s)`;
  - `Target` 6 with `StallTimeout = 300 ms` gives `(300 ms, 900 ms)`;
  - `Target` 6 with both overrides gives both overrides.
- `TestEachAttemptStartsWithNoCodecsFromTheLastOne` (the 4a-1a r5 hand-off). This runs in **transcode** mode, so no ceiling rewrites a string, on a stand-in with an `aac` rendition.
  - **Attempt 1** writes a video init whose `avcC` gives `avc1.4d401e`, then exits before any audio init and before a segment.
  - **Attempt 2** writes its `aac` init first. Its stdout, the video, is held until the test sees that audio init stored (a channel in the stand-in). Only then does it write a video init giving `avc1.64002a`, and then its segments.
  - **Without the reset**, attempt 2's audio init completes the map with attempt 1's stale video string, and `Ready` adopts `avc1.4d401e`.
  - **The oracle.** The multivariant's `CODECS` contains `avc1.64002a` and does not contain `avc1.4d401e`.
- `TestTheMultivariantBandwidthCoversACopiedRendition`: an output with `VideoMaxrate` 8,000,000, `VideoBitrate` 6,000,000, `PeakRate` 12,500,000 and `AverageRate` 10,000,000 gives `BANDWIDTH=12660000,AVERAGE-BANDWIDTH=10160000` on the `aac` line. The same output with `PeakRate` 5,000,000 and `AverageRate` 4,000,000 gives `BANDWIDTH=8160000,AVERAGE-BANDWIDTH=6160000`: the maximum, not the replacement. Both are literals.
- `relay/hls/store_test.go`:
  - `TestTheMediaPlaylistCarriesThePipelinesTargetDuration`: `SetTargetDuration(6)` gives the literal `#EXT-X-TARGETDURATION:6`, and no call gives `:2`.
  - `TestTheByteCeilingScalesWithTheTargetDuration`: at target 6, twenty-one 9 MiB segments (189 MiB) are all kept. At the default target, the same run keeps only the newest 7 (63 MiB ≤ 64 MiB).

**Go group "real"** (`relay/hls/real_test.go`, gated as the seed's real tests are by `requireRealFFmpeg`).

- `TestRealAutomaticCopiesTheHEVCFixture` (R28, #525): `hevc-aac`, 8 s, automatic.
  - Generation 0's probe has `Field == FieldUnknown`.
  - Its `Spawn` argv contains `-c:v copy` and `-tag:v hvc1`.
  - The video init's codec begins `hvc1.1.`, and the multivariant's video `CODECS` begins `hvc1.1.` and contains `.L123` or higher.
  - The `aac` rendition is copied: the argv has `-bsf:a aac_adtstoasc`, and the codec is `mp4a.40.2`.
  - Every segment is 2.000 s ± one frame and starts with a sync sample.
  - `TargetDuration()` is 2 s, and `Engine()` is `copy`.
- `TestRealAutomaticEncodesTheInterlacedFixtureAndCopiesItsAudio`: `h264-1080i-aac-ac3`, 6 s, automatic.
  - The video is encoded (`libx264` in the argv).
  - `aac` is copied (`-c:a copy -bsf:a aac_adtstoasc`), and `ac3` is copied as in transcode.
  - The log line carries the reason `field_order`.
- `TestRealAutomaticEncodesTheLongGOPFixtureJoinedMidGOP`: `h264-gop10-aac` joined 3 s in, which is the seed's own slice at `real_test.go:697-701` (`data[len*3/20:]`, 3,689,312 bytes, more than 3 MB). Measured by the planner through ffprobe 9.0.1 with this plan's argv:
  - the quick probe (`%+3`, video 3.24-6.12 s) sees no SPS (width 0), so R30's incomplete-video re-probe runs;
  - the full probe (`%+8`, 3.24-11.20 s) sees one keyframe, at 10.08 s.

  The oracle:
  - the probe command runs twice, and the second argv carries `-analyzeduration 8000000` and `-read_intervals %+8`;
  - the decision is encode with reason `keyframes`;
  - the target is 2;
  - the encoder's argv contains `libx264`.
- `TestRealAutomaticCopiesAFourSecondGOPAtTargetDurationFour` (the R37 wiring test): an in-test source, built once by ffmpeg into the test's temp directory. It is 16 s of `testsrc2` 640x360 at 25 fps, `libx264 -preset veryfast -g 100 -keyint_min 100 -sc_threshold 0 -b:v 1500k`, plus AAC stereo, as MPEG-TS. The planner's build was 3,400,544 bytes and the reviewer's 3,396,220; the size varies by x264 build, so the test asserts only that it exceeds `QuickProbe.Bytes`, and the window is media-bounded either way. Measured by the planner through ffprobe 9.0.1 with this plan's argv:
  - the quick probe (`%+3`) sees one keyframe, at 1.48 s, with the video complete, so R37's fewer-than-two-keyframes re-probe runs;
  - the full probe (`%+8`) sees 1.48 and 5.48 s: K = 4 s.

  With `-read_intervals` the window is media-bounded, so these hold even though `runReal` writes every byte into the ring before `Start`. The oracle:
  - the probe command runs twice, and the log carries R37's re-probe line;
  - the decision is copy;
  - `TargetDuration()` is 4 s, and the media playlist has `#EXT-X-TARGETDURATION:4`;
  - every segment but the generation's last (the flushed tail) is 4.000 s ± one frame.
- `TestRealAnHEVCRunEncodesItsMPEG2GenerationAsHEVC`: `hevc-aac` for 6 s, then `mpeg2-576i-mp2` for 6 s, as two generations, automatic.
  - Generation 1's `Spawn` argv contains `libx265` and `level-idc=4.1`, and no `libx264`.
  - Its video init's codec begins `hvc1.`.
  - The multivariant is unchanged, with `RESOLUTION=640x360` and `FRAME-RATE=25.000`.
  - Generation 1's segments are 2.000 s ± one frame.
- `TestRealAnH264CopyRunEncodesItsInterlacedGenerationAsH264`: `h264-eac3` for 6 s (copy), then `h264-1080i-aac-ac3` for 6 s.
  - Generation 1 is encoded with `libx264`, scaled to `640x360` (`scale=640:360` in `-vf`), at `fps=25/1`.
  - Its init's codec begins `avc1.64`.

**Go group "entry"** (`relay/httpapi/hls_automatic_test.go`, `relay/session/table_test.go`).

- `TestAnAutomaticChannelEntersUnderItsProfilesKey`: the stub's `HLSProfile` is `{7, "automatic"}`.
  - The entry answers 200.
  - `ch.HLSStatus()` reports the pipeline registered under `"hls:p7"`, with a recorded `hls.Config.Mode` of `ModeAutomatic`, through a `HLSDeps.Command` stand-in that records the `Spawn`.
  - A second entry reuses the same pipeline.
- `TestAnHLSEntryWithoutAnHLSProfileKeyIs502`: with `HLSProfileAbsent`, an `hls` tune is 502 with the literal body `control plane contract mismatch`, the channel's client count returns to 0, and a TS tune on the same stub is 200.
- `TestAnUnknownHLSProfileModeIs502`.
- `TestAnAutomaticSessionTakesItsPipelinesTargetDuration`: the stand-in probe reports K 6 s, so the target is 6. After the entry, the injected clock advances one second at a time, with a `Sweep` after each step.
  - The first departure is at +36 s.
  - A control with the built-in transcode departs at +12 s.
  - The failure message names the second of the first departure.
- `TestTheEntryWaitsCoverTheLongestTargetDuration`: `readyWait()` and `playlistWait()` are each ≥ `QuickProbe.Analyze + FullProbe.Analyze + startup(MaxTargetDuration)` and < 60 s. The literal expected value is 43 s.
- `relay/session/table_test.go`, `TestSetTDFixesTheThresholdsBeforeActivate`: `Add` with TD 2, `SetTD` to 6 s, then `Activate`. The idle departure is at 36 s. A `SetTD` after `Activate` is a no-op, and the departure is still at 36 s.
- `TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations` (the spec's TD = 6 presence row, driven end to end). It uses the same entry as the test above, with the stand-in probe reporting K 6 s and an injected clock. After the multivariant, a request on the session's token completes every 6 s, each lasting 50 ms.
  - **While reloading**, 4a-1c's `Table.Silent` (through `SilentAfter(s.TD)`) never reports the session silent, sampled every second over 60 s.
  - **Once the requests stop**, it is not silent at +11.9 s after the last request ended, and it is silent at +12.1 s.
  - **Control.** A built-in transcode session is silent at +4.1 s.

**E2E** (`e2e/tests/streaming/hls-automatic.spec.ts`, tagged `@contract`, in the `streaming` project, upstream at `rate: 1`).

- `an automatic channel copies HEVC and declares hvc1`: `hevc-aac`, and the channel's `hls_output_profile_id` is the seeded "HLS (Automatic)". Expected:
  - the multivariant's video `CODECS` begins `hvc1.`;
  - the audio is `mp4a.40.2`;
  - `RESOLUTION=640x360`;
  - `/proxy/ts/status/<uuid>` reports `hls_encoder: "copy"`;
  - the media playlist has `#EXT-X-TARGETDURATION:2`.
- `an automatic channel copies H.264 and its init carries the source's own codec`: `h264-eac3`. Expected:
  - `hls_encoder` is `"copy"`;
  - the multivariant declares `avc1.64002a` (the ceiling);
  - the video init's own codec (`initSummary(…).codec`, Task 10) begins `avc1.64` and its level byte is below `2a`;
  - three audio groups, as in transcode.
- `an automatic channel encodes a 10 s GOP`: `h264-gop10-aac`. Expected: `hls_encoder` is `"software"` (CI has no QSV), and the declared codec is `avc1.64002a`.
- Each test releases its session with `leaveHls`, as `hls-playlists.spec.ts` does.

### Tests changed

Each change pins behaviour this PR changes, or is support with no assertion change.

| Test | Before | After | Why |
|---|---|---|---|
| `relay/internal/relaytest/controlplane.go` (support) | the answer has no `hls_profile` | `"hls_profile": null` by default; `HLSProfile`/`HLSProfileAbsent`/`SetHLSProfile` added | Support only; no assertion anywhere changes. Every seed test's tune gets `Known` with no profile, which is the built-in transcode under key `"hls"`, as before. |
| `relay/hls/probe_test.go`, any test that pins `ProbeArgv`'s literal | — | unchanged | Named to say it does **not** change: `ProbeArgv` and transcode's probe are untouched (Decision 6). |
| `relay/hls/store_test.go::TestTheStoreIsBoundedAndServesBySequence`'s byte-bound assertions (`:146-155`) | — | unchanged | Named to say it does **not** change: an unset target keeps the seed's 64 MiB ceiling and eviction rule (Decision 14). |
| `relay/hls/store_test.go::TestTheMultivariant` (`:183-213`) | — | unchanged | Named to say it does **not** change: its literal `Output`s carry no `PeakRate`, and `Multivariant` takes `max(VideoMaxrate, PeakRate)`, so `BANDWIDTH=8160000` and `5160000` stand (round 1, finding 2). |
| `relay/hls/pipeline_test.go::TestASlowFirstFragmentIsNotKilledAsAStall`, `::TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` (`:1108-1150`) | — | unchanged | Named to say they do **not** change: an overridden `StallTimeout` still gets `StartupStallFactor ×` it (Decision 14's order, rung 2). |
| `docs/relay-parity-matrix.md` rows 36 and 43 | "three times that before its first fragment" and row 36's line-number Source; `TARGETDURATION:2` and "at least 6 once the channel has run 12 s" | Appendix A | The behaviour moved (Decision 14, R58), and row 36's cited lines move with this PR. |

No other seed test changes. In particular `TestTheEntryWaitsOutALegitimateColdStart` stays byte-identical and green: its `cold` is still ≤ 43 s. The new `TestTheEntryWaitsCoverTheLongestTargetDuration` holds the relation for a target of 6.

### Break-checks

Each is a named wrong edit, then the test, then the expected message naming the mechanism, then the revert. The PR body carries each one's red output verbatim.

1. **Copy interlaced video.** Drop the `FieldInterlaced` check in `copyEligible`. `TestTheAutomaticCopyDecision` reddens on row 4: "h264 tt: want encode (field_order), got copy".
2. **Unknown is interlaced (#525).** Map `FieldUnknown` to not-progressive in `copyEligible`. Row 2 reddens: "HEVC unknown: want copy, got encode (field_order)". `TestRealAutomaticCopiesTheHEVCFixture` also reddens: "argv has no -c:v copy".
3. **Encode the HEVC run's second generation as H.264.** In `PlanAutomatic`, use `FamilyH264` for every encode. `TestRealAnHEVCRunEncodesItsMPEG2GenerationAsHEVC` reddens: "generation 1 argv encodes libx264, want libx265".
4. **Let a copied segment exceed the target + 0.5 s.** Remove the over-long check in `cutLocked`. `TestAnOverLongCopiedFragmentEndsTheGeneration` reddens: "onOverlong called 0 times; the store published a 2.500 s segment under target 2".
5. **Hard-code the silence threshold at 4 s** in `session.SilentAfter` (or in `silentLocked`). `TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations` reddens: "a TD 6 session reloading every 6 s reported silent at +4 s". 4a-1c's `TestSilence` row 11 reddens too.
6. **Take the session's target from the constant.** Revert Decision 15's `SetTD` call. `TestAnAutomaticSessionTakesItsPipelinesTargetDuration` reddens: "first departure at +12 s, want +36 s".
7. **Ignore the target in the stall limits.** Make `stallLimits` return `(StallTimeout, 3×StallTimeout)`. `TestTheStallLimitsFollowTheTargetDuration` reddens on its target 6 row: "stall 10s, want 30s".
8. **Keep an earlier attempt's codecs.** Remove the reset in `attempt`. `TestEachAttemptStartsWithNoCodecsFromTheLastOne` reddens: "CODECS carries avc1.4d401e from a failed attempt".
9. **Drop the AAC bitstream filter.** `TestRealAutomaticCopiesTheHEVCFixture` reddens. Its failure names the `aac` rendition having produced no init segment, and the captured stderr carries "Malformed AAC bitstream".
10. **Let HLS rows into the map.** Remove the `hls_mode` skip in `_with_output_profiles`. `test_hls_rows_never_enter_output_profiles` reddens, with the extra keys listed.
11. **Honour an HLS profile per client.** Drop `hls_mode=""` in `resolve_output_profile`. `test_an_hls_profile_in_the_query_resolves_to_none` reddens with the row returned. The same edit on the HDHR resolver reddens the HDHR test.
12. **Edit an HLS row through the API.** Remove `perform_update`'s guard. `test_an_hls_row_cannot_be_updated` reddens: 200 where 403 was expected.
13. **A reverse that does nothing.** Make `remove_hls_output_profiles` a no-op. `test_the_core_migration_seeds…` reddens: "rows remain after migrating back to 0028".
14. **The frontend offers HLS rows to users.** Remove the filter at `User.jsx`. `it('offers no HLS output profile')` reddens, naming the option "HLS (Automatic)".
15. **Scale the startup allowance by three at every target.** Make `startup = 3 × stall`. `TestTheEntryWaitsCoverTheLongestTargetDuration` reddens: "readyWait 103s is not under nginx's 60 s".
16. **Fail a copy without its encode fallback** (R74). Make `generation` return `outcomeFailed` after the two copy attempts. `TestAFailedCopyFallsBackToAnEncode` reddens: "ErrFailed after two copy attempts; want an encode fallback (attempt 3 libx264)".
17. **Copy past the declared bandwidth** (R75). Drop the bandwidth bound in `VideoDecision`. The `bitrate` row of `TestALaterGenerationCopiesOnlyAgainstTheFixedOutput` reddens: "bitrate 10000000: want encode (bitrate), got copy".
18. **⌈K⌉ for the target** (R61). Make `targetFor` return `max(2, ⌈K⌉)`. `TestTheAutomaticTargetDuration` reddens on its 2.002 s row: "K 2.002s: target 3, want 2".
19. **Drop `ready` with an over-long fragment** (round 1, finding 7). Make the over-long branch clear `ready` too. `TestAnOverLongCopiedFragmentEndsTheGeneration` variant (b) reddens: "the store holds 0 segments, want the 2.000 s one".
20. **Take the startup allowance from the target even when `StallTimeout` is overridden** (Decision 14, rung 2). The seed's `TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` reddens: it is never killed within its bound.

### E2E and documentation

`e2e/COVERAGE.md` gains one row (Appendix A). The spec's § Testing E2E list is satisfied by § Tests added › E2E.

### Coverage (R21, R34)

The procedure is the Go floor file's own ("HOW TO MOVE"), as 4a-1b's plan ran it. It differs in two ways: there is no shape change, because this PR links no new package (`relay/hls` and `relay/session` are already linked), and the base is `M₀` from `main` at branch time.

1. **The census.** Dispatch `go-tests.yml` on the branch one run at a time, at least twelve times, until the maximum has held for six consecutive rounds. Record every round's `this run missing=`.
2. **Attribution.** From each round's `relay-go-coverage` artifact, compute two things:
   - **(b)**, the uncovered blocks in this PR's own new or changed code. These are the blocks whose start line falls in an added range of `git diff -U0 "${BASE}" -- relay ':!*_test.go' ':!relay/internal'`, with `BASE` the branch point.
   - **(c)**, any other uncovered block not in the base's own census artifacts. This is a pre-existing flap: recorded, never counted.
3. **The amount.** `O` is the sum over this PR's files of each file's maximum (b). Coverage on additions is 1 − (maximum uncovered in (b)) / (added statements), and must be **≥ 85%**. If it is below that, add tests; never lower the bar.
4. **The floor, by hand** (R52's form). `missing = M₀ + O`, and every round's `this run missing=` must be ≤ it. `percent`, `measured` and `runs` come from this census. `--write-floor` refuses a rising `missing`, and `--shape-only` never writes it. Commit, and confirm one more CI run's gate is green.
5. **The listing, in the PR body:**

```
Coverage (R21/R34). Census: <N> rounds (runs <ids>), `this run missing=` in order: <m1, …, mN>; max <M>.
Floor: missing M₀ <m0> -> M₀ + O = <new>; statements <S>; percent <P>; packages unchanged (<count>).
O, 4a-1d's own new or changed statements, uncovered (per-file max over the rounds):
  relay/hls/automatic.go <n> (blocks …), relay/hls/pipeline.go <n>, relay/hls/segmenter.go <n>,
  relay/hls/store.go <n>, relay/hls/probe.go <n>, relay/hls/argv.go <n>, relay/hls/detect.go <n>,
  relay/hls/playlist.go <n>, relay/control/nextsource.go <n>, relay/channel/<files> <n>,
  relay/httpapi/<files> <n>, relay/session/table.go <n> = <O>
Additions: <A> statements, at most <U> uncovered in any round -> <pct>% (>= 85%).
Pre-existing flaps outside O: <none | file:block, rounds>.
```

**Python Gate 2.** `scripts/coverage_live_path_isolated.sh` runs before the push. `authorize.py` and `next_source.py` are coveragerc modules (`scripts/coverage_live_path.coveragerc`). Every new line must be covered, and `missing` stays **33**. `apps/proxy/serializers.py`, `core/*` and `apps/channels/*` are outside Gate 2.

### Gates

- **Go:** Tasks 5-9, and the Go gate under § Coverage.
- **Python:** `core.tests`, `apps.channels.tests`, `apps.proxy.tests` and `apps.output.tests` green. Each runs once **without** `--keepdb` before push, because the migrations seed rows (the "keepdb hides seeded-row drift" lesson). Gate 2 `missing` stays 33, and `makemigrations --check` is clean.
- **Frontend:** `npm test`, `npm run build`, and no new lint error in a touched file.
- **E2E:** every `Playwright`, `Lifecycle`, `Go`, `Backend` and `Frontend` result green on the PR (the `migration/` branch runs the full matrix).
- **Manual:** none that gates (R45). The PR body records, as owed:
  - Q1's `hevc_qsv -level 41` and `-idr_interval` on the household host;
  - an AVPlayer run of an automatic HEVC channel, and of an open-GOP H.264 source copied (R76), watching for artefacts after a join and a discontinuity.

  The implementer may run the latter on macOS 27 with the 4a-1b harness if it is still in the scratchpad; it is informational.

### PR description draft

> **Phase 4a-1d: the *automatic* HLS profile.** This is ADR 0009's opt-in. A channel can be set to an HLS Output Profile in *automatic* mode, which copies what AVPlayer accepts and encodes only what it does not. MP2, or AAC that is not stereo LC, becomes AAC. Interlaced, MPEG-2, 10-bit or long-GOP video becomes the run's declared codec.
>
> Two locked profiles are seeded, "HLS (Re-encode)" and "HLS (Automatic)". The choice is per channel (`Channel.hls_output_profile`, the channel form's "HLS output") and reaches the relay as next-source's `hls_profile`. HLS profiles are excluded from every other Output Profile consumer (users, HDHR, the web player, the link builders), and the API refuses to edit them.
>
> A copied source's keyframe interval sets the target duration: max(2, ⌈K − 0.1 s⌉), with K ≤ 6 s. The stall watchdog, the store and every presence threshold follow it. A copied segment that would round above the target ends the generation, and the run is encoded from then on. A later source that cannot be copied, or whose rate exceeds the declared bandwidth, is encoded into the declared family, including `hevc_qsv`/`libx265` for an HEVC run; a copy that fails to start falls back to that encode. The multivariant declares the family's ceiling `CODECS`.
>
> Spec D12, § Automatic generation (amended by the 4a-1d plan). Migrations have reverses and round-trip tests.
>
> ⟨the closing line for #525, as § Issues directs⟩
>
> Coverage: <§ Coverage listing>. Python Gate 2: `missing` 33. Break-checks: <twenty, each with red output>. Tests changed: <§ Tests changed rows>. Owed, non-gating (R45): Q1's `hevc_qsv` argv on Quick Sync, and an AVPlayer run of an automatic HEVC channel and of a copied open-GOP source (R76).

## The seam, if this PR must split (R48)

**4a-1d-i** is Tasks 1-4: the Django models, the exclusions, next-source's `hls_profile` and the frontend. It is inert for the relay.
- At the seed the relay decodes the next-source answer with `encoding/json` into a struct and ignores unknown keys (`relay/control/nextsource.go:222-249`), so `hls_profile` changes nothing there.
- The channel form's choice has no effect until 4a-1d-ii. Its PR body says so, and the select's `description` says "takes effect when the relay supports automatic mode" until 4a-1d-ii replaces it.

**4a-1d-ii** is Tasks 5-12, and its PR body carries #525's closing line (§ Issues). Each half passes its own review and gates.

## Residual risks and follow-ups

- **The Quick Sync HEVC argv is unrun.** This covers `-level 41` and `hevc_qsv`'s `-idr_interval 0` semantics (Q1, R45). The software fallback, `libx265`, is measured. A wrong QSV argv degrades to software through D11's escalation, not to no picture.
- **K observability** (R63).
  - **Rate.** Above about 5 Mb/s, the 5 MB bound ends the window before 8 s of media, so a fast source with a 4-6 s GOP is encoded rather than copied.
  - **Phase.** At a boundary, an 8 s window holds two keyframes of a K-second GOP only when the first falls in the first 8 − K seconds: about 1/3 of probes at K = 6.
  - **The cost at boundaries.** A 3 s quick probe holds two keyframes of a 2 s GOP only about half the time, so automatic re-probes at about half of its boundaries, and each re-probe adds up to 8 s of media to that failover gap. With `-read_intervals` the re-probe ends as soon as the ring holds 8 s past the join, and on a live boundary with no backlog that is real time.
  - **The fallback** in each case is a correct encode.
- **The ceiling `CODECS` overstates a copied low-level source** (R59). A validator may flag the mismatch between the multivariant and the init, and no Apple player is known to refuse it. The owner's AVPlayer run on an automatic channel is owed.
- **Memory at a target of 6** is up to about 192 MiB per copied channel, and a copied source above about 26 Mb/s at TD 6 can have listed segments evicted (R62).
- **`libx265` real-time on CI.** The HEVC-family real test encodes the 720x576 MPEG-2 fixture scaled to 640x360 at `ultrafast`. That was measured at about 25× real time locally, so CI's real-time margin is not a concern for these tests. A 1080p50 HEVC encode on the household CPU is unmeasured (Q1's scope).
- **R75 can flip a same-source copy to an encode.** The rate check compares probe windows of a few seconds. A VBR source that fails over to itself, or reconnects, may measure above generation 0's declared peak and be encoded for that generation. That is R75 working as ruled: the declared `BANDWIDTH` stays true, at the cost of an encode.
- **Open-GOP copies** (R76). AVPlayer played them without error, with frame counts within 2 of a closed-GOP control, both after a live join and across a discontinuity (§ Rulings, 9). The leading B-frames of a copied open-GOP segment still reference a GOP that is absent after a join or a discontinuity. So `EXT-X-INDEPENDENT-SEGMENTS` is not strictly true for such a source, and a brief visual artefact there is possible and unmeasured. HEVC CRA open GOPs were not measured.
- **Follow-up:** bulk-editing the HLS profile across channels (spec non-goal) needs its own small PR against `ChannelBatch.jsx` and the bulk endpoint.

## Spec amendments in this PR

The edits are to `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` on this branch (based on `main` `d51d3195`, whose spec lacks #538's R55-R57 changelog entries). They are confined to this PR's sections, plus one payload line:

- **§ Automatic generation** (the table, then the new paragraphs "A later generation copies", "The probe in automatic mode" and "The multivariant in automatic mode", then the run-level rules): Decisions 6-9 and 11-14, and R58-R63 and R74-R77.
- **§ Relay channel payload additions:** `hls_encoder` gains `"copy"`.
- **§ 4a-1d:** the `CODECS` item's answer; R42/R55/R57; `hls_profile`'s contract-mismatch rule and its refresh; #525's closure; the E2E sentence; and one more break-check.
- **§ Risks:** four new bullets: K observability, open-GOP copies, the ceiling `CODECS`, and memory at a target of 6.
- **§ Changelog:** a new last entry, "2026-09-29, amended by the 4a-1d plan", with a round-1 sub-entry. It also records that when #538's R55 paragraph lands in § Encoder argv › Failure ("three times that"), R58 amends it to `max(30 s, the stall timeout)`. This branch is based on `main`, which lacks that paragraph, so the text is edited in place when #538 has merged: by this PR if it rebases after #538, or else by the 4a-1d implementation PR as the one spec edit Global constraint 8 allows.

## Appendix A: documentation in the implementation PR

These are byte-exact diffs against the seed. `git apply --check` passed on an export of `4ed75d96` (`git archive 4ed75d96 | tar -x`) for the round-1 revision below. They are to be re-applied onto the rebased base, and only the matrix hunk's context can move, by 4a-1c's appended rows.

⟨slots⟩:
- `⟨A⟩`, `⟨B⟩`, `⟨C⟩` and `⟨D⟩` are the next four free parity ids at merge, after 4a-1c's rows.
- **A `:⟨Name⟩` inside a backticked Source citation** (for example `relay/hls/automatic.go:⟨copyEligible⟩`) is the line range `start-end` of the Go function or method `Name`, from its `func` line to its closing brace, in that file at merge. The guard's `CITATION_RE` (`e2e/tests/guards/parity-matrix.ts:330`) then matches `path:start-end`, and "every row cites source that resolves" holds.
- `⟨pin-e2e⟩` is `e2e/tests/streaming/hls-automatic.spec.ts::an automatic channel copies HEVC and declares hvc1`.

**Verified.** The planner applied the diff to an export of `4ed75d96`, filled the slots with ids 45-48 and `1-5` ranges, raised `HIGHEST_ROW_ID` to 48, and stubbed every cited new file and test name. It then ran `npx playwright test --project=guards parity-matrix` in that export's `e2e/`, and all 9 tests passed ("48 rows — 46 pinned, 0 owed, 2 white-box-only"; "46 of 46 pinned rows carry a Go reference"). With the slots unfilled, "every row cites source that resolves" fails, as it must: the slots are the implementer's to fill.

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -82,7 +82,7 @@
 
 **State.** PostgreSQL holds durable rows — including settings, but **`CoreSettings` is one row per settings *group*, not per setting**: `key` unique, `value` a `JSONField`, eight groups (`core/models.py:207-214`). Every group is instance-wide, so there is no scoped settings write — treat any as blast radius (E2E allowlists them; see `docs/adr/0003`). `epg_settings` has no seeding migration, so POST it before you can PATCH it. **Redis no longer holds any live video byte.** Until stage 2d-4 it held the live ownership leases, channel metadata, client sets, switch requests and **the video bytes** in a ring buffer; all of that was `apps/proxy/live_proxy/`'s and went with it. What Redis holds now is the provider-slot counters, the VOD and catch-up halves of the per-user connection scan, Django's own `channel_stream:`/`stream_profile:` assignment keys, plus Celery broker / Channels layer / Django cache. They still share **DB 0**, so the blast radius of one of them is still all of them — but the biggest tenant, the video, is gone, and its removal was the whole of Phase 3's charter (ADR 0007). `BaseConfig.BUFFER_CHUNK_SIZE` at `apps/proxy/config.py:15` survives as `188 * 1361` = 255,868 bytes and is still the effective chunk size, so a `proxy_settings` edit still moves it — the 2c-2 sentence four below says how it reaches the relay and this one no longer repeats it (round-2 note 4). `scripts/wait_for_redis.py` is wait-only — it never flushes, in any role. AIO's Redis starts empty because supervisord runs it non-persistent (`--save "" --appendonly no`), not because anything wipes it, so a control-plane restart leaves a running relay's keys untouched. Since Phase 2 stage 2c-2, the Go relay's ring is a per-channel in-process buffer, not Redis-backed: a 300-chunk / 76,760,400-byte cap and the same 60-second retention as the Python relay, whichever binds first, sized from `BUFFER_CHUNK_SIZE` on the `next-source` answer (Amendment A1.4) rather than from a Go-side constant. Since stage 2c-3, the Go relay's client registry is likewise a map in process memory, and a TS or fMP4 client entry has no TTL, no heartbeat and no ghost sweep, because with one process it cannot outlive the goroutine that made it; `GET /proxy/relay/channels[?clients=all]` is served from it and performs no write. **An HLS session is the exception** (Phase 4a-1b; the Phase 4 spec's § The ADR 0006 amendment): it is a registry entry with no goroutine of its own, from the entry request that served its multivariant until an explicit `DELETE /hls/<token>`, an admin client stop or stream-limit termination, a stop of its channel, or the idle sweep (`relay/session`, one process-wide sweeper ticking every second) departs it after `max(12 s, 6 × TARGETDURATION)` with no request in flight — a TTL in all but name, and the one place the relay infers presence rather than observing it. Since 2c-4 the Go relay serves the FFmpeg/VLC/Streamlink architecture too: Django builds the argv (`StreamProfile.build_command`) and sends it as `stream_profile.argv` (Amendment A4.1); the relay spawns it with `Setpgid` and, on Linux, `Pdeathsig SIGKILL`, kills with SIGKILL, parses stderr with `relay/ffmpeg`'s port of `log_parsers.py`, and ends the tune with `ErrBufferingTimeout` until 2c-5 wires failover. Since 2c-5 the Go relay fails over: the three triggers drive one port of `StreamManager.run`'s loops (`relay/channel/channel.go`), a clean EOF is a retried connection failure, the buffering-triggered switch counts against `MAX_STREAM_SWITCHES` and, once it is spent, is refused rather than fatal (row 6, [#221](https://github.com/D10Scot/Dispatcharr/issues/221)), the degraded fallback reads the candidate list the initial `next-source` answer carried and never a Redis key, a Redirect channel is a 302 with no channel published, and `GET /proxy/relay/channels` carries `healthy`.
 
-**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). Since Phase 2 stage 2c-7 the Go relay serves them too, from `relay/output`: one transcode per pair, started by the first client on that profile and stopped by the last with no shutdown delay, writing a second in-process `buffer.Ring` its clients read instead of the channel's. Its argv is `output_profiles[*].argv` off the `next-source` answer, cached per channel and refreshed by every later answer a non-degraded failover receives (an edit mid-channel reaches new clients only after the next one, where Python re-reads the row per client), and an entry with a **null** argv is Django saying `shlex` refused that profile's parameters — a 500 for the client that selects it, where a profile merely absent from the map was deactivated and that client is served with no profile at all. An fMP4 client on a profile runs **two** chained processes, `mpegts:p<id>` then `fmp4:p<id>`, exactly as the deleted `live_proxy/views.py:765-792` composed them. **There was no HLS output until Phase 4a-1b** (ADRs 0008 and 0009, the Phase 4 spec): the deleted `live_proxy/server.py:1352`'s `_OUTPUT_FORMAT_MANAGERS` registered only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and `apps/proxy/hls_proxy/`, which never served one, was deleted by #405. Since 4a-1b a live tune whose format resolves to `hls` (`?output_format=hls`/`m3u8`, or an Xtream `.m3u8` URL) answers a multivariant playlist, and `relay/hls` — one re-encode per channel, restarted at every source boundary — serves its media playlists and fMP4 segments under `/hls/<token>/…`, where the token is an opaque, relay-minted media-session id with an HMAC of `SECRET_KEY` that names no channel. MPEG-TS and fMP4 clients are unchanged, and a TS-only channel starts no encode. Since Phase 2 stage 2c-6 the Go relay serves fMP4 too, from `relay/output`: one remux per channel spawned by the first fMP4 client and stopped by the last, reading the channel's shared ring on `pipe:0` and writing a second in-process buffer of whole fragments (`buffer.Fragments`, not `buffer.Ring` — the write unit is a variable-length fragment and the client-positioning rules differ), so an fMP4 channel costs roughly twice a TS-only channel's resident memory. It refuses any format but `mpegts`, `fmp4` and `hls` with 501. HLS *upstreams* are handled by forcing the ffmpeg profile.
+**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). Since Phase 2 stage 2c-7 the Go relay serves them too, from `relay/output`: one transcode per pair, started by the first client on that profile and stopped by the last with no shutdown delay, writing a second in-process `buffer.Ring` its clients read instead of the channel's. Its argv is `output_profiles[*].argv` off the `next-source` answer, cached per channel and refreshed by every later answer a non-degraded failover receives (an edit mid-channel reaches new clients only after the next one, where Python re-reads the row per client), and an entry with a **null** argv is Django saying `shlex` refused that profile's parameters — a 500 for the client that selects it, where a profile merely absent from the map was deactivated and that client is served with no profile at all. An fMP4 client on a profile runs **two** chained processes, `mpegts:p<id>` then `fmp4:p<id>`, exactly as the deleted `live_proxy/views.py:765-792` composed them. **There was no HLS output until Phase 4a-1b** (ADRs 0008 and 0009, the Phase 4 spec): the deleted `live_proxy/server.py:1352`'s `_OUTPUT_FORMAT_MANAGERS` registered only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and `apps/proxy/hls_proxy/`, which never served one, was deleted by #405. Since 4a-1b a live tune whose format resolves to `hls` (`?output_format=hls`/`m3u8`, or an Xtream `.m3u8` URL) answers a multivariant playlist, and `relay/hls` — one re-encode per channel, restarted at every source boundary — serves its media playlists and fMP4 segments under `/hls/<token>/…`, where the token is an opaque, relay-minted media-session id with an HMAC of `SECRET_KEY` that names no channel. MPEG-TS and fMP4 clients are unchanged, and a TS-only channel starts no encode. Since 4a-1d an HLS Output Profile (`OutputProfile.hls_mode` non-blank: the two locked rows "HLS (Re-encode)" and "HLS (Automatic)") is chosen per **channel** (`Channel.hls_output_profile`), never per client, reaches the relay as next-source's `hls_profile`, and is excluded from every other Output Profile consumer; *automatic* copies what AVPlayer accepts, may raise `TARGETDURATION` to 6, and every threshold measured in target durations (the stall watchdog, the store's byte ceiling, the session's presence thresholds) is then the pipeline's own. Since Phase 2 stage 2c-6 the Go relay serves fMP4 too, from `relay/output`: one remux per channel spawned by the first fMP4 client and stopped by the last, reading the channel's shared ring on `pipe:0` and writing a second in-process buffer of whole fragments (`buffer.Fragments`, not `buffer.Ring` — the write unit is a variable-length fragment and the client-positioning rules differ), so an fMP4 channel costs roughly twice a TS-only channel's resident memory. It refuses any format but `mpegts`, `fmp4` and `hls` with 501. HLS *upstreams* are handled by forcing the ffmpeg profile.
 
 **There is no owner election on the live path any more.** Until Phase 2 stage 2d-4 one uWSGI worker owned a channel's upstream, elected by `redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` in `live_proxy/server.py`; followers served their own clients from the same Redis keys and asked the owner to act over `live:events:{id}`. All of it is deleted. The Go relay is **one process with one in-memory registry** (spec D2): `relay/channel`'s `Manager` holds one `Channel` per live channel behind one mutex, so ownership is a map entry rather than a lease, a follower is a goroutine rather than a second process, and there is nothing to fence. What survives unchanged is the byte layout: `relay/buffer`'s ring realigns to 188-byte TS packets before writing chunks, and **the chunk index is monotonic for the channel's life, never reset by a stream switch** — why a switch doesn't touch clients; new clients still start ~5s behind live.
 
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -207,13 +207,17 @@
 | 33 | Each HLS generation is probed where it starts: the first from the join point behind live, every later one from its boundary index, so the second generation's probe describes the second source | `relay/hls/pipeline.go:328-444`, `relay/hls/pipeline.go:468-549` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity` | Phase 4a-1a (spec D9). The probe's feed stops at the next boundary as the generation's does. It is bounded at 3 s or 3,000,000 bytes, with one re-probe at 8 s or 5 MB when the video has no geometry or field order (ruling R30; the long-GOP case is `relay/hls/real_test.go::TestRealALongGOPIsReprobedAtTheFullBound`); on an MPEG-TS pipe ffprobe reads to its bound whatever it has found, so the bound is the probe's share of the failover gap (Q6). A connection that ends at the next boundary before it can be probed is skipped rather than failing the output, at generation 0 as at any later one (plan review, round 1 finding 3 and ruling R39); a ring that closes under a probe is a stop (R40). |
 | 34 | With no usable Quick Sync the HLS encoder runs in software and never refuses: a missing render node, a failing one-frame detection encode or its timeout selects libx264, and Quick Sync is written off for the process only when a software retry succeeds where it failed and the detection encode, re-run, fails | `relay/hls/detect.go:89-173`, `relay/hls/pipeline.go:574-606` | `relay/hls/detect_test.go::TestDetection`, `relay/hls/real_test.go::TestRealDetectionWithoutQuickSyncGivesSoftware`, `relay/hls/pipeline_test.go::TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff`, `relay/hls/pipeline_test.go::TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails`, `relay/hls/detect_test.go::TestADetectionCutShortByTheCallerIsNotCached` | Phase 4a-1a (spec D11, finding 5). A detection or re-check cut short by the caller's own context is no evidence and writes nothing off (plan review, finding 1). The QSV argv itself has not run on Quick Sync hardware (Q1); these pins hold the selection and the write-off rule, not the device. |
 | 35 | An audio stream that does not qualify (no known codec, 0 channels or a 0 sample rate, which is what a PMT-declared PID carrying no packets probes as) declares no HLS rendition and is never mapped into the encoder's argv | `relay/hls/probe.go:167-173`, `relay/hls/argv.go:124-154`, `relay/hls/argv.go:260-294` | `relay/hls/real_test.go::TestRealADeclaredButEmptyAudioPIDIsNotMapped`, `relay/hls/argv_test.go::TestANonQualifyingAudioStreamIsNotMapped` | Phase 4a-1a (spec § Encoder argv, finding 7). Mapping such a stream fails every output of the generation (ffmpeg 9.0.1: `sample rate not set`). The real pin strips the AC-3 PID's packets from the 4a-0 1080i fixture and keeps its PMT entry. |
-| 36 | A stalled HLS encoder is a death: a generation that writes no new video fragment for max(10 s, 5 x TARGETDURATION) of the channel's ring advancing is killed (three times that before its first fragment, R55) and counted against the restart bound, while an encoder starved by an idle ring is left alone | `relay/hls/pipeline.go:45`, `relay/hls/pipeline.go:746`, `relay/hls/pipeline.go:819-864` | `relay/hls/pipeline_test.go::TestAStalledEncoderIsKilledAsADeath`, `relay/hls/pipeline_test.go::TestAStarvedEncoderIsNotKilled`, `relay/hls/pipeline_test.go::TestASlowFirstFragmentIsNotKilledAsAStall`, `relay/hls/pipeline_test.go::TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` | Phase 4a-1a (ruling R33, R38). The ring, not the bytes fed, is the measure of input advancing, because a wedged encoder that stops reading its stdin stops the feed too. The clock starts at the first ring advance after the latest fragment and resets whenever the ring is idle for half the timeout, so the watchdog is inert below roughly 410 kb/s (a 255,868-byte chunk less often than every 5 s). Before a generation's first video fragment the allowance is StartupStallFactor (3) times the timeout (ruling R55, 4a-1b): a cold software encode of a 1080i source is fed at real time and was measured killed healthy at 10 s. |
+| 36 | A stalled HLS encoder is a death: a generation that writes no new video fragment for max(10 s, 5 x TARGETDURATION) of the channel's ring advancing is killed (before its first fragment, max(30 s, that): R55 as amended by R58) and counted against the restart bound, while an encoder starved by an idle ring is left alone | `relay/hls/pipeline.go:⟨stallLimits⟩`, `relay/hls/pipeline.go:⟨watch⟩` | `relay/hls/pipeline_test.go::TestAStalledEncoderIsKilledAsADeath`, `relay/hls/pipeline_test.go::TestAStarvedEncoderIsNotKilled`, `relay/hls/pipeline_test.go::TestASlowFirstFragmentIsNotKilledAsAStall`, `relay/hls/pipeline_test.go::TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` | Phase 4a-1a (ruling R33, R38). The ring, not the bytes fed, is the measure of input advancing, because a wedged encoder that stops reading its stdin stops the feed too. The clock starts at the first ring advance after the latest fragment and resets whenever the ring is idle for half the timeout, so the watchdog is inert below roughly 410 kb/s (a 255,868-byte chunk less often than every 5 s). Before a generation's first video fragment the allowance is StartupStallFactor (3) times the timeout (ruling R55, 4a-1b): a cold software encode of a 1080i source is fed at real time and was measured killed healthy at 10 s. Since 4a-1d the timeout is the pipeline's own (ruling R42: 10 s at TARGETDURATION 2, 30 s at 6) and the startup allowance is max(30 s, the timeout), 30 s at every target up to 6 (ruling R58), so the entry's 43 s waits stay under nginx's 60 s; pinned also by `relay/hls/automatic_pipeline_test.go::TestTheStallLimitsFollowTheTargetDuration` and `relay/httpapi/hls_automatic_test.go::TestTheEntryWaitsCoverTheLongestTargetDuration`. |
 | 37 | A live tune whose output format resolves to `hls` answers a multivariant playlist rather than bytes: `?output_format=hls` or `m3u8` through the hop's aliases, or an Xtream `.m3u8` URL on either XC root through the relay's extension override, gets 200 `application/vnd.apple.mpegurl` with `Cache-Control: no-store` once the first generation that writes a complete set of init segments has done so, every URI under `/hls/<token>/`; not ready within 43 s (R57) is 503 with `Retry-After: 1` and leaves no client | `apps/proxy/authorize.py:251-260`, `relay/httpapi/xc.go:65-76`, `relay/httpapi/stream.go:429-434`, `relay/httpapi/hls.go:200-354` | `relay/httpapi/hls_test.go::TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes`, `relay/httpapi/hls_test.go::TestAnXCM3U8URLForcesHLSOnBothRoots`, `relay/httpapi/hls_test.go::TestAnEntryWhoseInitsNeverArriveIs503AndLeavesNoClient`, `e2e/tests/streaming/hls-entry.spec.ts::an hls tune answers a multivariant playlist on all three entry forms` | Phase 4a-1b (spec D2, D3, § Entry). The multivariant carries a fresh token on every entry, hence `no-store`. `X-Relay-Output` is ignored on an `hls` tune (D12), so the client's `output_profile_id` is null. `hls` is never a deployment or user default (D2, R23). |
 | 38 | `/hls/` is authorized by the media-session token alone: `v1.<sid>.<mac>`, a 128-bit random sid and an HMAC-SHA256 of `SECRET_KEY` over `media-session`, `v1` and the sid, naming no channel; a GET whose token is malformed or whose MAC is wrong, or whose sid is unknown (left, ended by an admin, past its resume window, or minted before a relay restart), is 403 with one body and no detail; a GET on a session whose channel stopped is 410 once and 403 after; `X-Relay-*` and `X-Dispatcharr-Authorized` are ignored there | `relay/control/mediasession.go:50-79`, `relay/session/table.go:205-240`, `relay/httpapi/hls.go:394-437` | `relay/control/mediasession_test.go::TestAMediaSessionTokenIsRefusedWhenForgedOrTampered`, `relay/httpapi/hls_test.go::TestAStoppedSessionIs410OnceThen403AndADeleteIs204`, `relay/httpapi/hls_test.go::TestARejectedTokensTextNeverReachesTheLog`, `e2e/tests/streaming/hls-sessions.spec.ts::a tampered token, a left session and a stopped client are refused` | Phase 4a-1b (spec D4, § The media-session token; R13, R22). No expiry field: the token lives exactly as long as its session (R22). The MAC is compared with `hmac.Equal` before any table lookup. The token is never logged by the relay; nginx's access log records it as it records XC credentials (spec § Risks). |
 | 39 | An HLS viewer is a client in the channel's registry exactly while its session is live: it arrives with its multivariant (`client_connect`), is active on every request carrying its token, and leaves, with `client_disconnect` (`duration`, `bytes_sent`) and its Attach release, on `DELETE /hls/<token>` (204, idempotent), on an admin client stop or stream-limit termination, or once `max(12 s, 6 x TARGETDURATION)` has passed with no request in flight | `relay/session/table.go:287-409`, `relay/session/departure.go:29-46`, `relay/httpapi/control.go:128-170` | `relay/session/table_test.go::TestAnIdleSessionDepartsAfterTheIdleTimeoutAndNotBefore`, `relay/session/table_test.go::TestARequestInFlightHoldsASessionActive`, `relay/httpapi/hls_test.go::TestALeaveEndsTheSessionAtOnceAndIsIdempotent`, `relay/httpapi/hls_test.go::TestAnAdminClientStopEndsAnHLSSession`, `e2e/tests/streaming/hls-sessions.spec.ts::an hls client is listed while it plays and leaves at once on DELETE` | Phase 4a-1b (spec D5, § Presence). The one place the relay infers presence rather than observing it (spec § The ADR 0006 amendment). The per-user stream limit counts these clients because it counts the registry; a departed session is not a client. |
 | 40 | A stopped channel's HLS sessions become STOPPED on the goroutine that decided the stop, never synchronously on the channel's own: an admin stop and the drain in `Manager.Stop`, the last client's release in `stopIfStillIdle`, and a run that ended by itself or an HLS output that failed on a fresh goroutine, which drops their client entries (`client_disconnect`, no release) and then makes the manager's idle decision, so no stop waits on its own `done` | `relay/channel/manager.go:340-473`, `relay/channel/channel.go:184-188`, `relay/httpapi/hls.go:370-385` | `relay/httpapi/hls_test.go::TestSelfStopRunEnded`, `relay/httpapi/hls_test.go::TestSelfStopHLSFailedWithNoOtherClient`, `relay/httpapi/hls_test.go::TestSelfStopHLSFailedWithATSClient`, `relay/httpapi/hls_test.go::TestAnAdminChannelStopEndsItsHLSSessions` | Phase 4a-1b (spec § Presence, Who ends sessions). The run-ended case is the break-check's oracle: done synchronously from `run()`'s defers, the stop waits out `StopWait` on its own `done` and logs `source goroutine did not return in time`. |
 | 41 | A resume never starts a channel or reserves a slot: a request on a departed session within 300 s re-attaches through the non-starting `AttachExisting`, and only to the very channel and HLS pipeline its playlists name; a channel absent or restarted, a pipeline no longer running, or a stop between the lookup and the commit answers 410 and leaves no client and no table entry | `relay/channel/manager.go:480-490`, `relay/channel/hlsoutput.go:95-112`, `relay/httpapi/hls.go:453-503`, `relay/session/table.go:269-283` | `relay/httpapi/hls_test.go::TestAResumeNeverStartsAChannel`, `relay/httpapi/hls_test.go::TestAResumeThatLosesTheRaceToAStopReleasesItsAttachment`, `relay/httpapi/hls_test.go::TestADepartedSessionResumesOnItsRunningPipeline` | Phase 4a-1b (spec § Resume never starts a channel). A `/hls/` request ran no authorize hop and no stream-limit check, which is why it may never start anything. A resumed session is not re-checked against the stream limit, bounded by the 300 s window (spec § Risks). |
 | 42 | A Redirect-profile channel is served over HLS through the relay, as Proxy: an `hls` tune reserves and holds the provider slot and reads the provider itself, where a TS tune on the same channel, while it is not running, still gets its 302 | `relay/httpapi/stream.go:741-758` | `relay/httpapi/hls_test.go::TestARedirectChannelIsServedOverHLSAsProxy`, `e2e/tests/streaming/hls-entry.spec.ts::a Redirect-profile channel is served over HLS through the relay` | Phase 4a-1b (spec D13, R23). HLS is made from bytes the relay holds; a 302 to an endless provider TS is what AVPlayer cannot play (ADR 0008). |
-| 43 | Live HLS media playlists conform and their segments stay fetchable: `VERSION:7`, `TARGETDURATION:2`, `INDEPENDENT-SEGMENTS`, `EXT-X-PROGRAM-DATE-TIME` on every segment, at most 10 listed and at least 6 once the channel has run 12 s, a media sequence that only advances; `Cache-Control: no-cache` and a `Last-Modified` from the newest segment; and a segment that leaves the list stays in the store for its duration plus the playlist's | `relay/hls/store.go:22-246`, `relay/httpapi/hls.go:521-548` | `relay/hls/store_test.go::TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists`, `relay/hls/store_test.go::TestTheMediaPlaylist`, `relay/httpapi/hls_test.go::TestAMediaPlaylistWaitsForItsFirstSegmentAndCarriesItsHeaders`, `e2e/tests/streaming/hls-playlists.spec.ts::a media playlist conforms and its init and segments parse` | Phase 4a-1b (spec D7, § Session resources; ruling R44 for the store's 21, RFC 8216 § 6.2.2). Apple 8.4, 8.11 (the 6-segment minimum), 8.24, 9.11-9.12. |
+| 43 | Live HLS media playlists conform and their segments stay fetchable: `VERSION:7`, `TARGETDURATION` the pipeline's own (2 in transcode; up to 6 in automatic, 4a-1d), `INDEPENDENT-SEGMENTS`, `EXT-X-PROGRAM-DATE-TIME` on every segment, at most 10 listed and at least 6 once the channel has run six target durations (12 s at TARGETDURATION 2), a media sequence that only advances; `Cache-Control: no-cache` and a `Last-Modified` from the newest segment; and a segment that leaves the list stays in the store for its duration plus the playlist's | `relay/hls/store.go:22-246`, `relay/httpapi/hls.go:521-548` | `relay/hls/store_test.go::TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists`, `relay/hls/store_test.go::TestTheMediaPlaylist`, `relay/httpapi/hls_test.go::TestAMediaPlaylistWaitsForItsFirstSegmentAndCarriesItsHeaders`, `e2e/tests/streaming/hls-playlists.spec.ts::a media playlist conforms and its init and segments parse` | Phase 4a-1b (spec D7, § Session resources; ruling R44 for the store's 21, RFC 8216 § 6.2.2). Apple 8.4, 8.11 (the 6-segment minimum), 8.24, 9.11-9.12. |
 | 44 | A failed HLS output marks the channel, not a pipeline: its sessions become STOPPED, its pipeline is torn down, and new HLS entries answer 502 until the channel's next source boundary, which only clears the mark and starts nothing; the channel and its TS clients are unaffected | `relay/channel/hlsoutput.go:67-167`, `relay/channel/boundary.go:38-47`, `relay/httpapi/hls.go:370-385` | `relay/httpapi/hls_test.go::TestAFailedHLSOutputRefusesEntriesUntilTheNextBoundaryAndStartsNothingThere` | Phase 4a-1b (spec § Encoder argv, failure; R19: a TS-only channel starts no encode, so the boundary only clears). The 502's body names the reason: `no video stream in the source` for `hls.ErrNoVideo`, `HLS output failed` otherwise. |
+| ⟨A⟩ | An HLS channel set to the *automatic* Output Profile copies what AVPlayer accepts and encodes the rest, per rendition: video that is H.264 (Constrained Baseline, Baseline, Main or High, 8-bit 4:2:0) or HEVC Main 8-bit, progressive (ffprobe's `field_order=unknown` counts as progressive, R28), with at least two keyframes in the probe window and a longest keyframe interval K of at most 6 s, no larger than 1920x1080 and no faster than 60 fps, is copied, HEVC tagged `hvc1`, and the run's `TARGETDURATION` is max(2, ⌈K − 0.1 s⌉); AAC-LC stereo is copied into the `aac` rendition through `aac_adtstoasc`; everything else is encoded as in transcode; a copy generation whose attempts fail falls back to an encode into the declared family (R74); and the channel payload's `hls_encoder` is `copy` while the video is copied | `relay/hls/automatic.go:⟨copyEligible⟩`, `relay/hls/probe.go:⟨ParseProbe⟩`, `relay/hls/argv.go:⟨Argv⟩`, `relay/hls/pipeline.go:⟨generation⟩` | `relay/hls/automatic_test.go::TestTheAutomaticCopyDecision`, `relay/hls/real_test.go::TestRealAutomaticCopiesTheHEVCFixture`, `relay/hls/real_test.go::TestRealAutomaticCopiesAFourSecondGOPAtTargetDurationFour`, `relay/hls/automatic_pipeline_test.go::TestAFailedCopyFallsBackToAnEncode`, `⟨pin-e2e⟩` | Phase 4a-1d (spec D12, § Automatic generation as amended by the 4a-1d plan; rulings R28 and issue #525, R37, R60, R61, R74, R77). The automatic probe lists the packets of a media-bounded window (`-read_intervals %+<analyze>`, `-show_entries packet=…`); transcode's probe argv is unchanged. Open-GOP sources are copied: AVPlayer played copied open-GOP segments on macOS 27 and the iOS 27 Simulator (R76, measured in the 4a-1d plan), and ffprobe's `K` flag does not distinguish an IDR. |
+| ⟨B⟩ | The first generation fixes an automatic run's video family, geometry, frame rate, target, declared level and declared bandwidth: a later generation copies only against all of them and is otherwise encoded into the declared family, an HEVC run with `hevc_qsv` (level 4.1) or, without Quick Sync, `libx265` (level-idc 4.1); the multivariant declares the family's ceiling `CODECS` (H.264 High at the higher of the copied level and 4.2, HEVC at the higher of the copied level and 4.1), and each attempt of a generation starts with no codec recorded by an earlier one | `relay/hls/automatic.go:⟨VideoDecision⟩`, `relay/hls/automatic.go:⟨declaredVideoCodec⟩`, `relay/hls/detect.go:⟨EngineFor⟩`, `relay/hls/pipeline.go:⟨attempt⟩` | `relay/hls/real_test.go::TestRealAnHEVCRunEncodesItsMPEG2GenerationAsHEVC`, `relay/hls/automatic_test.go::TestALaterGenerationCopiesOnlyAgainstTheFixedOutput`, `relay/hls/automatic_test.go::TestTheDeclaredVideoCodecIsTheFamilyCeiling`, `relay/hls/automatic_pipeline_test.go::TestEachAttemptStartsWithNoCodecsFromTheLastOne` | Phase 4a-1d (spec § Automatic generation's run-level rules; rulings R59, R60, R75; the 4a-1a hand-off on per-attempt codecs). `hevc_qsv` has its own one-frame detection and is written off on its own evidence (D11). The QSV argv is unrun on hardware (Q1). |
+| ⟨C⟩ | A copied segment that would round above the target duration (target + 0.5 s or longer, RFC 8216 § 4.3.3.1) ends its generation at once and is never published, while the segments already cut before it publish normally; the event counts toward the 3-in-60 s restart bound, and every later generation of the run is encoded; the copy segmenter also closes a segment before a keyframe that would take it to that length | `relay/hls/segmenter.go:⟨cutLocked⟩`, `relay/hls/pipeline.go:⟨run⟩` | `relay/hls/automatic_pipeline_test.go::TestAnOverLongCopiedFragmentEndsTheGeneration`, `relay/hls/automatic_pipeline_test.go::TestAnOverLongCopiedSegmentRestartsTheRunEncoded`, `relay/hls/automatic_pipeline_test.go::TestACopiedGenerationCutsWithinTheTargetDuration` | Phase 4a-1d (spec finding 10; ruling R61). An encoded generation never takes these branches (`TestAnEncodedGenerationIgnoresTheCopyCut`). |
+| ⟨D⟩ | Every threshold measured in target durations is the pipeline's own: a session's `TD` is set from its pipeline once the first generation's inits exist, so an automatic channel at a target of 6 departs an idle session at 36 s and is silent for reclaim only after 12 s, and the store's byte ceiling scales with the target | `relay/session/table.go:⟨SetTD⟩`, `relay/httpapi/hls.go:⟨serveHLSEntry⟩`, `relay/hls/store.go:⟨publish⟩` | `relay/httpapi/hls_automatic_test.go::TestAnAutomaticSessionTakesItsPipelinesTargetDuration`, `relay/httpapi/hls_automatic_test.go::TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations`, `relay/hls/store_test.go::TestTheByteCeilingScalesWithTheTargetDuration` | Phase 4a-1d (spec § Presence thresholds, finding 6; rulings R42, R62). The silence rule is 4a-1c's `session.SilentAfter(s.TD)`. |
 <!-- end of matrix -->
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -212,6 +212,7 @@
 | Streaming | Live HLS sessions: a tampered token, a left session and a client stopped through `/proxy/ts/stop_client/` are refused 403; a session on a stopped channel is refused 410 once and 403 after; `/proxy/ts/status/<uuid>` lists an `hls` client that disappears at once on `DELETE /hls/<token>` beside a TS client that stays, with no wait for the idle timeout. `tests/streaming/hls-sessions.spec.ts` | 4a-1b | done |
 | Streaming | Live HLS failover: an upstream fault on `h264-1080i-aac-ac3` switches the channel to an alternate carrying `mpeg2-576i-mp2`, and the next media playlist carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` with the media sequence continuing and the multivariant's `CODECS` unchanged. `tests/streaming/hls-failover.spec.ts` | 4a-1b | done |
 | Streaming | **Observation (spec Q6, ruling R29), measured on CI's software encoder, not a gate:** the failover gap from the switch (the first status poll naming the alternate) to the new generation's first segment was 8.68 s (CI run 36495275297, one run, at 250 ms poll resolution; the fault-to-flip time was 0.80 s); the software transcode of `h264-1080i-aac-ac3` (1080i → 1080p50, libx264) published 1.044 of real time (42.0 s of segments over the 40 s window, run 36495275297) over a 40 s window under the `streaming` project's two workers. At or above real time, so no finding. `tests/streaming/hls-failover.spec.ts`, `tests/streaming/hls-realtime.spec.ts` | 4a-1b | done |
+| Streaming | Live HLS in *automatic* mode (Phase 4a-1d): a channel set to "HLS (Automatic)" copies `hevc-aac` (the multivariant declares `hvc1`, `/proxy/ts/status/<uuid>` reports `hls_encoder: "copy"`, `TARGETDURATION:2`), copies `h264-eac3` (its init carries the source's own `avc1` string while the multivariant declares the family ceiling `avc1.64002a`), and encodes `h264-gop10-aac` (a 10 s GOP; `hls_encoder: "software"` on CI). A target duration above 2, the declared-family encode and the over-long-segment rule are pinned in Go only, with in-test sources (`relay/hls/real_test.go`, `relay/hls/automatic_pipeline_test.go`). `tests/streaming/hls-automatic.spec.ts` | 4a-1d | done |
 | Streaming | **Gap, pinned in Go only:** idle departure (`max(12 s, 6 × TARGETDURATION)`), the resume within 300 s, the sweeper's removals and the self-stop paths are pinned by `relay/session` and `relay/httpapi` tests with an injected clock and a stand-in encoder, never by an E2E that waits out a timeout (ruling R24). No E2E plays HLS in a browser or in AVPlayer: hls.js is 4a-2's `frontend` project, and AVPlayer is the manual gate recorded in the 4a-1b PR body (spec § Testing and gates). | 4a-1b | done |
 
 The ten G1 rows above are covered by these specs (the two seeding rows
```
