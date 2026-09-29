# Phase 4 — Apple-Native Live Playback

**Date:** 2026-09-27
**Status:** Draft
**Parent:** [ADR 0008](../../adr/0008-phase-4-reopens-the-programme-for-apple-native-live-playback.md)
(Phase 4 reopens the programme; its three deliverables and scope limits) and
[ADR 0009](../../adr/0009-the-hls-output-re-encodes-by-default.md) (the HLS output re-encodes by
default). Both are accepted and land in this spec's own branch. The owner's rulings of 2026-09-26/27
override any default here; they are restated in Appendix A, so this document can be read without the
conversation that produced them.
**Predecessors:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (the Go relay: its
decisions D1-D7, Amendments A1-A16, stdlib-only, in-memory state, D6's drain) and
`docs/adr/0006-the-go-relay-keeps-its-state-in-memory-and-the-cutover-is-hard.md`. Phase 4a is new
work on the Go relay and binds to both.
**Verified at:** code anchors at `main` `560c6d58`; this branch's tip adds only documentation
(`87b1434b` carries the two ADRs and the `CONTEXT.md` entries). Line numbers drift; route shapes,
header names, setting keys and symbol names are the durable half of every citation.

## Goal

Watch live TV on iPhone, iPad and Apple TV through AVPlayer, from this server, on the household LAN.
The server half is **4a**, and it is what this spec designs in full. It has three deliverables, in
the owner's order (ruling R1):

1. **4a-1, live-edge HLS.** The Go relay serves any live channel as HLS: a multivariant playlist,
   media playlists, fMP4/CMAF init and media segments, made by one shared re-encode per channel on
   Quick Sync (ADR 0009). An Xtream client that asks for `.m3u8` gets a real playlist (R9).
2. **4a-2, the browser player on HLS.** `FloatingVideo.jsx` plays live **channels** over HLS
   through hls.js, instead of MPEG-TS through mpegts.js (R17). Stream previews stay on TS (R18).
3. **4a-3, the live rewind window.** The last hour of a channel watched over HLS is kept on disk
   from its first HLS viewer (R19). It is shared per channel, lingers after its last viewer, gives
   its provider slot up to a new tune that needs it, and is lost when the relay restarts (R10).

**4b**, the Apple app, lives in its own repository. This spec defines only the server contract it
builds against (§ 4b). **4c**, paired-device auth, is an investigation brief (§ 4c), to be taken up
after 4b's first playable build.

Every stage below is a legitimate stopping point. After 4a-1 the household can already watch live
TV in AVPlayer, through any Xtream app or the first app build. `CLAUDE.md`'s warning applies
unchanged: widening scope is the main way this fails.

## What was measured before this spec was written

These are observations, not reasoning. The prototypes ran in the orchestrator's scratchpad and never
entered the repository. They were a Python stand-in for the relay's segmenter, `libx264` as a
stand-in for Quick Sync, and a Swift AVPlayer probe run on macOS 27 and, via
`xcrun simctl spawn`, on the iOS 27 Simulator (iPhone 18 Pro). No tvOS runtime and no Intel GPU was
available. Appendix B has the commands.

| # | What | Result |
|---|---|---|
| M1 | Does the production ffmpeg support Quick Sync? `docker/DispatcharrBase:7` and `:115` pin `lscr.io/linuxserver/ffmpeg:version-9.0-cli@sha256:47fbdc93…`, an index. Its **amd64** manifest (`sha256:1a264852…`) was pulled and inspected. | **Yes, on amd64.** The encoders include `h264_qsv`, `hevc_qsv`, `mpeg2_qsv`, `h264_vaapi` and `hevc_vaapi`, and the filters include `vpp_qsv`, `deinterlace_qsv`, `bwdif` and `yadif`. `-hwaccels` lists `qsv` and `vaapi`. The configure line includes `--enable-libvpl`, `--enable-vaapi`, `--enable-libx264`, `--enable-libx265` and `--enable-libfdk_aac`, and the encoders include `libx265`. The image ships `iHD_drv_video.so`, `libmfx-gen.so.1.2.17` (the oneVPL runtime 12th-generation parts use) and `libmfxhw64.so`, and sets `LIBVA_DRIVERS_PATH=/usr/local/lib/x86_64-linux-gnu/dri`. The **arm64** manifest has no QSV or VAAPI encoder at all. **No base-image change is needed.** |
| M2 | What does a QSV device initialisation do with no `/dev/dri`? The amd64 image was run under emulation. | It fails **during global option parsing**, before any input is opened: `Device creation failed … Error parsing global options`, with a non-zero exit, in well under a second. In the same image, the same command with `libx264` succeeds. |
| M3 | Does **one** encoder, fed on stdin, survive a failover source switch? A 1080i H.264 + MP2 + AC-3 source (PIDs from 0x100) was fed, followed by a 720p MPEG-2 + MP2 source (PIDs from 0x200, a timestamp jump of 5000 s). | **No.** It exits 0, but the output is 20.04 s (1000 frames) of the 40 s fed. Source B is **silently dropped**, and the only trace is a `New audio stream with index 4` warning. With the **same** PIDs and a resolution change, output continues for 39.98 s (1996 frames) with non-monotonic-DTS warnings. With the same PIDs and the same parameters (a plain timestamp jump) it continues for 40.02 s. |
| M4 | Can one encoder write fMP4 renditions on separate pipes, with the relay's own segmenter owning the playlists? The prototype wrote video on fd 1, stereo AAC on fd 3 and AC-3 passthrough on fd 4, all `-movflags frag_keyframe+delay_moov+default_base_moof`, with a 2 s forced IDR interval. It served one `EXT-X-STREAM-INF` per audio group. | **Yes.** Every segment was exactly 2.000 s. `empty_moov` refuses AC-3 passthrough (`Cannot write moov atom before AC3 packets`), so `delay_moov` is needed, as the existing remux already uses (`relay/output/fmp4.go:80`). **macOS 27:** ready 0.37 s, first frame 0.32 s, 981 frames in ~19.6 s, **7.26 s behind the segments' `EXT-X-PROGRAM-DATE-TIME`**. **iOS 27 Simulator, warm:** ready 0.21-0.32 s, 983-986 frames, **7.22-7.40 s behind PDT**. The first cold spawn after boot took 13.56 s, which is simulator start-up, and is discounted. Both platforms chose the AAC group. macOS fetched the AC-3 media playlist once and iOS never did. |
| M5 | Does the demuxed AC-3 fMP4 rendition decode? A multivariant offering only the AC-3 group was used. | **Yes** on macOS and on the iOS Simulator. The audio track's format was `ac-3`. |
| M6 | Discontinuity. The encoder was restarted at a source boundary (stdin closed, a new process started on source B), and the next segment was marked `EXT-X-DISCONTINUITY` with a new `EXT-X-MAP`. | AVPlayer on macOS **played across it without error**: 1742 frames in the 40 s probe, where a steady ~49 fps gives ~1960. The old generation's flushed tail became two final segments. The new generation's first segment appeared **8.9 s after the boundary** on the prototype host. That host is a laptop running `libx264` 1080p50 plus the feeders and the player, and it then ran slower than real time (a segment every 2.2-2.9 s). The gap on real hardware is open question Q6. |
| M7 | Does a **paused** AVPlayer keep requesting? It played 12 s, paused 60 s and resumed 10 s, against a 90-segment live playlist. | On macOS **and** iOS: during the pause AVPlayer reloaded the media playlist **every 2.0 s** (30 reloads in 60 s), fetched 46 segments ahead, and resumed **58.2-58.3 s behind the live end**. Pausing live HLS is timeshift, from the player's own buffer and the playlist. |
| M8 | How does a generation with **no qualifying audio** get its AAC rendition, while still exiting promptly on stdin EOF with video flowing (round 3, finding 1)? | **An ffmpeg `anullsrc` second input fails; relay-synthesised silence works.** <br>- **Production image** (amd64 manifest `1a264852`, under emulation), fed a 6 s 320×240 H.264 no-audio TS on stdin. The video-only generation exits 0 on stdin EOF, with all 150 frames in its fMP4 output, in 0.97 s wall-clock including `docker run`. The same argv with `-f lavfi -i anullsrc=r=48000:cl=stereo` as a second input feeding an AAC output **never exits**: `timeout 20` killed it, exit 124. In those 20 s the AAC output reached 262 KB, which is unpaced silence. Round 3's reviewer, on local ffmpeg 9.0.1, saw the same no-exit, and also a starved video output.<br>- **Chosen mechanism, prototyped locally** (ffmpeg 9.0.1, the M4 harness, a live 1080i50 no-audio source). The generation writes video only. The relay synthesises every declared audio rendition from a canned silent frame:<br>&nbsp;&nbsp;- AAC-LC stereo 48 kHz: a 6-byte frame of 1024 samples;<br>&nbsp;&nbsp;- AC-3 5.1 640 kb/s: a 2560-byte frame of 1536 samples.<br>&nbsp;&nbsp;Each frame, and its init segment (728 and 725 bytes), was taken from a one-off `anullsrc` encode. In both, every steady-state frame is byte-identical. Frames are counted against each video segment's time span: frames whose start is before the segment's end, which is exact by construction. The results:<br>&nbsp;&nbsp;- **Exit on EOF:** the generation exited 0.065 s after stdin closed, rc 0.<br>&nbsp;&nbsp;- **Segments:** every segment was 2.000 s, with 666-672 bytes of AAC and 158-161 KB of AC-3 silence.<br>&nbsp;&nbsp;- **macOS 27:** ready 0.21 s, 738 frames in 15 s, 6.30 s behind PDT.<br>&nbsp;&nbsp;- **iOS 27 Simulator:** ready 0.20-0.80 s, 708-738 frames in 15 s, 6.07-6.62 s behind PDT.<br>&nbsp;&nbsp;- **Audio track selected:** `aac ` from the full multivariant, and `ac-3` from an AC-3-only one, on both platforms.<br>&nbsp;&nbsp;- **Across a restart:** after an encoder restart at a source boundary, AVPlayer on macOS played 1052 frames in 22 s across `EXT-X-DISCONTINUITY`. The silent renditions carried their own discontinuity and `EXT-X-MAP`. |

**What was not measured**, and where each item lands: Quick Sync encoding itself (no Intel GPU was
available; Q1), tvOS (Q2-Q4), Atmos (Q3), a 60-minute playlist on Apple TV (Q4), zap time on the
household host (Q5), the failover gap on real hardware (Q6), and E-AC-3 silence (M8 prototyped only
AAC and AC-3; 4a-1a's test covers it). M8 was added in round 3, to settle the no-audio mechanism. § Open questions says, for each,
who takes the measurement and what it decides.

## Verified facts this design rests on

Each fact was read at `560c6d58`.

**The relay today.**

- Output formats. `OutputFormatMPEGTS` is at `relay/httpapi/stream.go:171` and `output.FormatFMP4`
  at `relay/output/fmp4.go:47`. `identify()` (`relay/httpapi/stream.go:348-438`) refuses anything
  else with `ErrUnsupportedOutput` (`:397-403`), which is answered 501 "this output is not served
  yet" in `writeTuneFailure`.
- The format arrives on `X-Relay-Output-Format` from the authorize hop. It is read only when
  `X-Dispatcharr-Authorized` verifies (`identify`, `:349-365`). `XCHandler`
  (`relay/httpapi/xc.go:39-59`) rewrites it from the path's extension, `.mp4` and `.ts` only
  (`xcForcedFormat`, `:64-72`). A `.m3u8` therefore streams raw TS today.
- Routes, behind the dev-routes gate: `GET /proxy/ts/stream/{channelID}` and both XC live roots
  (`relay/httpapi/server.go:64`, `:70-71`), plus the five `/proxy/relay/…` control routes
  (`:84-88`). `docker/supervisord.d/relay-go.conf` sets `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"`.
- One `channel.Manager` owns every channel (`relay/channel/manager.go:47-60`). `Attach`
  (`:131-181`) registers a client and starts the channel once. The returned release func drops the
  client, and the last drop stops the channel after `channel_shutdown_delay` (`release`,
  `:393-404`; `stopIfStillIdle`, `:437-454`). `channel_shutdown_delay` defaults to **0**
  (`core/models.py:726`).
- Output pipelines. `Channel.AttachOutput` (`relay/channel/output.go:126-185`) refcounts one
  `output.Pipeline` per format key, and the last release stops it (`:192-207`). A pipeline's
  writer feeds the channel's ring to the child's stdin, starting `JoinBehind` behind live
  (`relay/output/fmp4.go:724-760`). The fMP4 remux's argv is `relay/output/fmp4.go:69-83`.
- A failover switch goes through `Channel.applySwitch` (`relay/channel/failover.go:257-281`). It
  resets the ring's packetiser (`:259`) but **not** its index, and it raises `stream_switch`. The
  ring's chunks carry their arrival time (`relay/buffer/ring.go:44-56`, `Chunk.At`).
- The provider slot is released once per channel. `run()`'s **first** deferred call is
  `releaseSlot` (`relay/channel/channel.go:445`, `:697-702`), so it runs **after**
  `close(c.done)`: `stop()` (`:748-755`) returns before the release POST has completed.
- Redirect. A Redirect-profile tune is answered 302/301 with no channel published, unless the
  principal is internal, in which case it is served as Proxy (`startTune`,
  `relay/httpapi/stream.go:655-737`, the Redirect arm at `:701-713`).
- Spawning. `ffmpeg.Start`/`StartPiped` (`relay/ffmpeg/spawn.go:94-113`) set `Setpgid` and, on
  Linux, `Pdeathsig SIGKILL` (`relay/ffmpeg/spawn_linux.go:19-20`). No spawn helper passes a file
  descriptor beyond 0-2 today.
- Internal HMAC tokens. They are built by `relay/control/token.go` from `SECRET_KEY` and three
  context strings (`relay-trust`, `internal-principal`, `internal-request`). `SECRET_KEY` arrives
  as `DJANGO_SECRET_KEY` (`relay/config/config.go`'s `loadSecret`).
- Memory. The channel ring is 300 chunks, 76,760,400 B, 60 s (`relay/buffer/buffer.go:58-78`). An
  fMP4 channel holds a second buffer (`buffer.Fragments`).

**The control plane.**

- `authorize_stream` (`apps/proxy/authorize.py:464-526`) resolves the format through
  `resolve_output_format` (`:259-282`), using the alias table `_FORMAT_ALIASES` (`:251-257`:
  `mpegts`, `ts`, `fmp4`, `mp4`). An unknown value such as `hls` is ignored, and resolution falls
  through to the user's `custom_properties.output_format`, then `CoreSettings`'
  `default_output_format` (`core/models.py:438`, `:574`). The stream limit is checked at `:500`.
  The Output Profile comes from `?output_profile=` or the user's `custom_properties`
  (`resolve_output_profile`, `:226-244`).
- The per-user stream limit counts **live** connections from the relay's own client list
  (`apps/proxy/utils.py:256-345`, `get_user_active_connections`, which calls
  `relay_client.live_connections`). When the limit is exceeded and
  `terminate_on_limit_exceeded` is set (the default), `attempt_stream_termination` (`:143-254`)
  stops the chosen client through `relay_client.stop_client`, which is
  `DELETE /proxy/relay/channels/<id>/clients/<client>`.
- Provider slots are reserved by `Channel.get_stream()` (`apps/channels/models.py:527-662`). It
  answers `"All active M3U profiles have reached maximum connection limits"` (`:656`) when every
  profile is full. `reserve_profile_slot` fails with `profile_full` or `credential_full`
  (`apps/m3u/connection_pool.py:20`, `:264`, `:270`). `resolve_initial_source`
  (`apps/proxy/next_source.py:598-749`) turns that failure into `{"source": None, "error": …}`
  (`:691-692`). The #513 reconciler (`apps/proxy/slot_reconciler.py`) counts every channel the
  relay lists as a holder of its `m3u_profile_id` unless its `state` is `stopped` or `error`
  (`_live_holders`, `:260-267`; `_ENDED_RELAY_STATES`, `:111`).
- `NextSourceResponseSerializer` (`apps/proxy/serializers.py:247-259`) carries `source`,
  `alternates`, `error`, `proxy_settings` and `output_profiles`. The relay requires every
  `proxy_settings` key and fails the tune on an absent one (`relay/httpapi/stream.go:87-163`,
  Amendment A1.4). `get_proxy_settings` back-fills defaults for keys a stored row lacks
  (`core/models.py:707-731`).
- `OutputProfile` (`core/models.py:169-203`) is `name`, `command`, `parameters`, `locked` and
  `is_active`. It is selected per **client**, never per channel. Two locked rows are seeded by
  `core/migrations/0024_outputprofile.py`.

**Client surfaces.** `get.php` builds `{base}/live/{u}/{p}/{channel.id}` with no extension, and
copies `?output=` into `?output_format=` (`apps/output/views.py:227-232`, `:318`). `player_api.php`
advertises `allowed_output_formats` as `['ts', 'mp4']` (`:416-418`, `:469`). Its `get_short_epg`
and `get_simple_data_table` actions are at `:519-522`.

**nginx.** Three Go-bound byte locations run the hop and set `proxy_buffering off`:
`^~ /proxy/ts/stream/` (`docker/nginx.conf:304-365`), `^~ /live/` (`:461-522`) and the XC
three-segment regex (`:620-681`). `^~ /proxy/relay/` (`:449-460`) is Go-bound, runs no hop, and
includes `dispatcharr_api_params_proxy.conf`, which blanks `X-Dispatcharr-Authorized` and the six
`X-Relay-*` headers. `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` pins the exact
target sets: `UWSGI_BOUND_TARGETS` (`:139-146`), `PROXY_BOUND_TARGETS` (`:155-159`), their union
for the hop assertion (`:183`), and `^~ /proxy/relay/`'s own properties (fourth test, `:511-576`).

**The browser player.** `FloatingVideo.jsx` imports both `mpegts.js` and `hls.js`
(`frontend/src/components/FloatingVideo.jsx:6-7`). Live plays through mpegts.js
(`initializeLivePlayer`, `:444-555`), sending the JWT as a `Bearer` header. hls.js is used only for
recordings (`:333-420`). `buildLiveStreamUrl` forces `output_format=mpegts` and appends the
browser-local web-player Output Profile preference (`frontend/src/utils/components/FloatingVideoUtils.js:8-14`),
which is set in `UiSettingsForm.jsx:29` and `:103`.

**The GPU in the container.** `docker/init/01-user-setup.sh:69-110` adds the service user to the
group owning `/dev/dri/renderD128`. `relay-go.conf` drops privilege with
`setpriv … --init-groups`, which keeps that supplementary group. `docker/entrypoint.sh:101`
exports `LIBVA_DRIVERS_PATH`. The compose files carry `/dev/dri` only as a commented example
(`docker/docker-compose.yml:124-130`).


**Facts the round-1 review surfaced, verified at `560c6d58`.**

- **The client registry.** ADR 0006 (`docs/adr/0006-…:76-78`) and CLAUDE.md § State both say the
  registry has "no TTL, no heartbeat and no ghost sweep, because with one process a client entry
  cannot outlive the goroutine that made it". `relay/channel/channel.go:709-711` states "a channel
  in this manager never exists without at least one attached client". An HLS session (D5) and a
  lingering window (D15) each change one of these, so § The ADR 0006 amendment records it.
- **Zero-client consumers.** `_stop_dvr_clients` (`apps/channels/api_views.py:3831-3841`) stops a
  channel whose relay `client_count` is 0 after it has stopped the DVR's own clients.
- **A channel UUID is the anonymous live capability.** `_PRINCIPAL_REQUIRED` excludes
  `SURFACE_LIVE` (`apps/proxy/authorize.py:77-84`), and the stream limit is checked only when there
  is a user (`:498-500`). Xtream surfaces never hand a UUID out: `get.php` uses `channel.id`
  (`apps/output/views.py:318`), and only the non-XC M3U branch emits UUIDs (`:335-338`).
- **An anonymous client's user id is the string `"0"`**, not an empty string
  (`relay/httpapi/stream.go:423-427`).
- **The stream limit on zap.** When a user is at their limit, `check_user_stream_limits` refuses
  outright if `terminate_on_limit_exceeded` is off (`apps/proxy/utils.py:400-402`). Otherwise
  (the default) it stops the chosen older connection and admits the new one.
- **Every OutputProfile consumer:**
  - `resolve_output_profile` (`apps/proxy/authorize.py:226-244`);
  - `_resolve_hdhr_output_profile_id` (`apps/hdhr/api_views.py:104-118`);
  - the `output_profiles` map built for next-source (`apps/proxy/next_source.py:892`);
  - `OutputProfileViewSet` (`core/api_views.py:82`);
  - the frontend selects in `User.jsx:352`, `StreamSettingsForm.jsx:208` (HDHR),
    `UiSettingsForm.jsx:183` (web player) and `ChannelsTable.jsx:1288` and `:1421` (the M3U-link
    builder);
  - the display lookup in `StreamConnectionCard.jsx:419`.
- **Browser play sites.** Channel playback (by channel UUID) builds its URL in:
  - `ChannelsTable.jsx:665-666`;
  - `StreamConnectionCard.jsx:516`;
  - `RecordingCardUtils.js:62-68` (`getShowVideoUrl`, used by `Guide.jsx:778`, `DVR.jsx:213`,
    `RecordingCard.jsx:124`, `RecordingDetailsModal.jsx:287` and `ProgramDetailModal.jsx:109`).

  Stream previews (by stream hash) build it in `StreamsTable.jsx:954` and
  `ChannelTableStreams.jsx:404`. All of them go through `buildLiveStreamUrl`.

## Decisions

| # | Decision | Why |
|---|---|---|
| **D1** | **Seven PRs.** 4a-0 (e2e-upstream fixtures). 4a-1a (the packager, inert). 4a-1b (sessions, routes, surfaces: live HLS works end to end, with an explicit session leave). 4a-1c (slot reclaim: a blocked tune takes back a channel nobody is watching). 4a-1d (the *automatic* HLS profile). 4a-2 (browser player). 4a-3 (the rewind window, linger, and lingering windows in the reclaim set). Branches are `migration/phase4-*`, so the full E2E and lifecycle matrix runs on every one (CLAUDE.md § Full E2E runs). The stopping points are after 4a-1c, 4a-1d, 4a-2 and 4a-3. | 4a-0 has its own package, version and guard, and every later PR's E2E depends on it (finding 18). The packager can land inert and be reviewed on its own evidence. 4a-1c follows 4a-1b directly, because an HLS session that nobody ends explicitly would otherwise hold a provider slot for its idle timeout, which is a zap regression against TS (§ Presence). 4a-1d is separable because the default (transcode) needs no schema. The window's slot yield uses 4a-1c's mechanism, so it needs no PR of its own. |
| **D2** | **HLS is an output format, not a new authorised route.** `hls` joins the resolved formats. `_FORMAT_ALIASES` gains `"hls": "hls"` and `"m3u8": "hls"`. `xcForcedFormat` maps `.m3u8` to `hls`. Any live tune URL whose resolved format is `hls` (`/proxy/ts/stream/<id>?output_format=hls`, `/live/<u>/<p>/<id>.m3u8`, `/<u>/<p>/<id>.m3u8`) is answered **200 with the multivariant playlist**. `hls` is **not** offered as `default_output_format` or as a user's `output_format` (accepted, R23). | The authorize hop, its nginx locations, the XC credential check, the stream limit and every channel check apply unchanged, with no new Django urlconf entry for `_surface_for` to learn. A deployment-wide default of `hls` would turn every byte-stream URL (HDHomeRun, Plex, TS apps) into a playlist. |
| **D3** | **Everything after the entry lives under a token-authorised root, `/hls/`, and runs no authorize hop.** URL layout: `/hls/<token>/<rendition>.m3u8` (media playlist), `/hls/<token>/<rendition>/init-<gen>.mp4`, `/hls/<token>/<rendition>/<seq>.m4s`, and `DELETE /hls/<token>` (leave, D5). nginx gets `location ^~ /hls/` with `include dispatcharr_api_params_proxy.conf`, `proxy_buffering off`, `proxy_http_version 1.1`, `proxy_connect_timeout 60s` and `proxy_pass http://relay_go`. There is no `auth_request` and no `internal;`. The multivariant references media playlists by **absolute path**, and media playlists reference init and media segments **relatively**. | R13: Django is not asked per segment. Absolute-path URIs need no `Host` or scheme reconstruction, so the six server-level `proxy_set_header` lines need not be re-declared, for the same reason `^~ /proxy/relay/` omits them. Buffering is off because a segment runs to megabytes and buffering it would spool to disk. One cost, recorded: a bare three-segment XC request from a user literally named `hls` now reaches this location. That is the same class of collision the `live`, `movie`, `series` and `timeshift` prefixes already impose, and the `/live/…` form still works for that user. |
| **D4** | **An opaque media-session token** (§ The media-session token; R22): `v1.<session id>.<MAC>`, where the session id is 128 random bits. The relay mints and verifies it. The channel, client id, user and HLS profile live in the relay's **session table**, never in the token. It is valid exactly while its session is: MAC verifies, **and** the session id is in the table, **and** the session has not ended. A session ends on an explicit leave, on an admin stop or stream-limit termination, on idle departure plus the resume window, or on relay restart. There is **no absolute expiry**, so a continuously watched session is never cut off. It is not bound to an IP address. | A channel UUID in the token would hand every Xtream user the anonymous live capability (finding 2; `authorize.py:77-84`), which Xtream surfaces never expose today. The relay needs the session table anyway, for presence (D5), so holding the claims there costs nothing, and every revocation is simply a table delete: no revoked set. The session id is distinct from the client id, because the client id appears in stats and events, and the token must not. The MAC rejects a forged id before any table lookup and keeps the check constant-time. There is no IP binding because AirPlay hands a URL to an Apple TV that fetches from a different address, and phones roam between access points. |
| **D5** | **An HLS viewer is a client in the channel's registry for exactly as long as its session is live.** It **arrives** when the multivariant is served (the `Attach` call, a `client_connect` event). It is **active** on every request carrying its token. It **leaves** when it calls `DELETE /hls/<token>` (the Mino app on zap and after the R11 countdown; the browser player on close or switch), or after the **idle timeout**, `max(12 s, 6 × TARGETDURATION)`, with no request in flight (§ Presence thresholds). Leaving emits `client_disconnect` with `duration` and `bytes_sent` and calls the release func. A departed (not left) session may **resume** within 300 s **if its channel is still running** (another viewer, or 4a-3's linger), with a new `client_connect`. When its channel stops, a session becomes **STOPPED**: its next request gets 410 and it is then removed (§ Presence). `output_format` is `hls`, so `/proxy/relay/channels`, `/proxy/ts/status/` and the stats page show it without change. Admin stop, and stream-limit termination, end the session. | M7 measured AVPlayer reloading every target duration (2 s) even while paused, so an idle timeout of six target durations (at least 12 s) cannot mistake a paused viewer for a departed one. The explicit leave is what makes a zap as fast as TS's connection close (finding 1). The idle timeout covers only clients that never call it: third-party apps, a killed app, a closed tab. The per-user stream limit needs no change, because it counts the relay's client list, which now includes HLS sessions (§ Presence says what a limit-1 user gets on zap). |
| **D6** | **The relay owns packaging.** One ffmpeg per (channel, HLS profile) reads the channel's ring on stdin. It writes **one fragmented-MP4 stream per rendition on its own file descriptor**: video on fd 1, stereo AAC on fd 3, AC-3 on fd 4, E-AC-3 on fd 5, each `-movflags frag_keyframe+delay_moov+default_base_moof`. A new package, `relay/hls`, parses the boxes (stdlib `encoding/binary`), cuts segments, stores them, and renders every playlist. The segmenter accumulates video fragments until the 2 s grid is reached, and checks that each segment's first sample is a sync sample; it does not cut at every fragment. **Rejected:** ffmpeg's own `-f hls` muxer, and one muxed audio-plus-video stream. | M4 shows the shape works, with 2.000 s segments on every rendition. `-f hls` writes files the relay would have to watch (no inotify in the stdlib) and playlists it would have to rewrite: for tokens, for D10's discontinuities across processes, and for 4a-3's on-disk window. A muxed stream cannot carry two alternative audio codecs as HLS renditions. `buffer.Fragments` is not reused, because it is a cursor stream for one long response, and HLS needs random access by media sequence across aligned renditions (`hls.Store`). The spawn helper gains `ExtraFiles` (stdlib `os/exec`); `start()` (`relay/ffmpeg/spawn.go:113-197`) keeps `Setpgid` and `Pdeathsig`. Accumulating to the grid guards against stray non-IDR keyframes the encoder may emit (Q1). |
| **D7** | **Playlists** (§ Playlists, exact tags). There is one video rendition and one audio group per audio codec: `aac` always; `ac3` when the source carries AC-3 or E-AC-3; `eac3` when it carries E-AC-3. Each group gets its own `EXT-X-STREAM-INF` on the same video playlist. `CODECS` is read from each rendition's **init segment** (`avcC`, `hvcC`, `esds`, `dac3` and `dec3` boxes). `EXT-X-PROGRAM-DATE-TIME` is written on **every** segment, derived from the ring's **arrival time** of the generation's first chunk plus media time (the known drift is § Risks). `TARGETDURATION` is 2 (transcode), with `INDEPENDENT-SEGMENTS`, `VERSION:7`, a media sequence that continues across generations, and `DISCONTINUITY-SEQUENCE`. The live-edge playlist lists 10 segments. A media playlist request **waits** for its rendition's first segment, bounded by 20 s, then answers 503 with `Retry-After: 1`. The multivariant waits for every first-generation init segment, bounded the same way. | Apple rules 2.3, 2.5-2.6, 7.4, 8.4, 8.11 and 9.11-9.12 (Appendix A). The 2 s target departs **deliberately** from Apple 7.5/7.6's 6 s target (a SHOULD): R8 prefers lower latency, and M4 measured about 7.3 s behind PDT at 2 s against about 24.5 s at 6 s. Codec strings read from init segments stay true in every mode, copy included. Arrival time rather than publish time keeps PDT honest while the encoder catches up the first generation's `JoinBehind` backlog. Holding a request until content exists is simpler for every player than an empty live playlist. |
| **D8** | **The default re-encode** (§ Encoder argv). The source is decoded in software, and deinterlaced with `bwdif=mode=send_field:deint=interlaced` when the probe says it is interlaced (50i → 50p, Apple 1.14-1.15). **Output geometry and frame rate are fixed for the channel's run** at the first generation's probe: at most 1920×1080, never upscaled at the first generation, and `scale`/`pad`/`fps` enforce them on every later generation. Video is H.264 High@L4.2 at constant frame rate, with a forced IDR every 2.000 s and a bitrate from a table by output height. It is encoded with `h264_qsv` behind `hwupload`, or with `libx264 -preset veryfast -tune zerolatency` (D11). **Audio**, per R20 and Apple 2.3/2.6: stereo AAC 160 kb/s always. An AC-3 source track is copied. An E-AC-3 source track is copied **and** an AC-3 rendition is encoded from it at the source's layout (640 kb/s at 5.1, 192 kb/s at 2.0; § Encoder argv › Channel layouts), giving three audio renditions. Only **qualifying** audio streams are mapped (§ Encoder argv). **The rendition set is fixed at generation 0**, as geometry is, and every later generation fills every declared rendition (§ Encoder argv, rendition filling). A rendition with no source is filled with **relay-synthesised silence** (M8): canned silent frames, counted against the video segments' time spans, with no audio output in the ffmpeg argv at all. | ADR 0009 makes codec, field order and keyframe spacing Mino's decisions. Software decode plus `bwdif`'s `deint=interlaced` handles mixed progressive and interlaced content without a hardware filter chain whose behaviour on progressive frames is unknown (Q1). Encoding is the expensive half, and it is the half that goes to Quick Sync. Fixed output parameters are what ADR 0009 promised across a switch, and what keeps the multivariant true after one. A PMT-declared audio track with no packets would otherwise make ffmpeg fail every rendition (finding 7). Silence satisfies Apple 2.3 on a video-only source. It is synthesised by the relay because an ffmpeg `anullsrc` input never lets the generation exit on stdin EOF, and it is unpaced (M8). |
| **D9** | **A probe precedes every generation, and reads from where that generation will start** (D10): the first generation from `JoinBehind` behind live, every later one from its boundary index. The probe is `ffprobe -show_streams -of json`, decoded with stdlib `encoding/json`, bounded to **3 s or 3,000,000 bytes** (`-analyzeduration 3000000 -probesize 3000000`; 3 MB is 3 s of an 8 Mb/s source, and a faster one ends on bytes first), with **one re-probe at 8 s or 5 MB only when the video has no width, height or `field_order`** (or, in *automatic* mode only, the 3 s window held fewer than 2 keyframes, R37) and the first probe's feed stopped for a reason more bytes would change (not at a boundary or the ring's close). The encoder analyses its own `pipe:0` input at the bound its generation's probe succeeded with (amended by R30). It decides interlacing (`field_order`), frame rate, geometry and the qualifying audio streams, and, in *automatic* mode, the copy decisions (D12). A probe that finds no video stream fails the HLS attach with 502, and the channel's TS clients are unaffected. `Channel.AttachOutput` holds `outMu` across a pipeline's start (`relay/channel/output.go:126-185`). The HLS attach therefore only registers its pipeline under `outMu`, and runs the probe (3 s, or 11 s with its re-probe) and the init wait (up to 20 s) **outside** it, so an fMP4 or Output Profile attach on the same channel never waits behind them. | Every later choice depends on these facts, and the relay is the only process that can see the bytes. Probing across a boundary would describe the old source's streams, and M3 shows how silently a stream mismatch fails (finding 6). The 3 s bound (R30): on an MPEG-TS pipe ffprobe reads to its `-analyzeduration` whatever it has found (mpegts is a no-header format), so the bound **is** the probe's share of the zap time and the failover gap. The 4a-1a plan review measured every decision on the 4a-0 fixtures identical to a full probe at 2.5-3 s and geometry lost at 1 s; the bound must exceed the GOP, which the re-probe covers when it does not. |
| **D10** | **The encoder restarts at every source boundary. It does not survive a switch.** A boundary is every new upstream connection: an `applySwitch`, or a reconnect of the same URL. The channel records the ring index of the boundary's first chunk. The running generation's writer stops **at** that index and closes stdin. The generation then exits on its own (M8: 0.065 s), and its flushed tail becomes the generation's last, possibly short, segments. The argv never carries an input that could keep it alive: no lavfi source. A generation still running 5 s after stdin closed is killed. The grace is its own constant,
`hls.GenerationExitGrace` = 5 s, and `ffmpeg.KillWait` (500 ms, `relay/ffmpeg/spawn.go:60-62`)
stays the reap budget after the kill. If the channel has an HLS pipeline, a new generation is probed and started at the boundary. A channel with none starts nothing there (R19; § Encoder argv › Failure). Its first segment is marked `EXT-X-DISCONTINUITY` with a new `EXT-X-MAP` (`init-<gen>.mp4`), and the media sequence continues. | M3: a surviving encoder silently drops a source with different PIDs, so every failover to another provider would be a picture that stops with no error anywhere. M6: AVPlayer plays across a discontinuity. Restarting also makes a change of codec, resolution or audio layout between providers safe, and the fixed output parameters (D8) keep the declared variant true. The cost is the gap measured in M6 (Q6). |
| **D11** | **With no usable Quick Sync, the relay encodes in software and says so. It never refuses** (accepted, R23). At the first HLS attach in the process, the relay runs a one-frame QSV test encode (§ Encoder argv, detection) and caches the answer. **A generation that exits before its first segment** is retried once with the same engine. If the retry also fails on QSV, the same input is retried in software. **QSV is marked unusable for the process only when that software retry succeeds and the detection encode, re-run, now fails**: both are needed to show the failure was the device's. Any other early failure fails that channel's HLS output alone: a mark on the channel, cleared at its next source boundary, with the pipeline torn down (§ Encoder argv, failure). The channel payload carries `hls_encoder` (`"qsv"` or `"software"`), and the fallback is logged once at WARNING. | Refusing would reproduce the failure ADR 0009 exists to prevent: an Apple TV showing nothing, because `/dev/dri` was left out of a compose file. Fallback also makes the path testable on CI and developer Macs. Distinguishing a device failure from a source failure (finding 5) stops one bad channel from pushing every channel in the process onto the CPU. |
| **D12** | ***Automatic* is an Output Profile mode, selected per channel.** `OutputProfile` gains `hls_mode` (blank; `transcode`; `automatic`). Two **locked** rows are seeded, "HLS (Re-encode)" and "HLS (Automatic)", with `command="ffmpeg"` and `parameters="(built by the relay)"`. They are never executed, because every consumer that builds or offers an argv excludes them. Rows with a non-blank `hls_mode` cannot be created or edited through the API. `Channel` gains `hls_output_profile`, a nullable FK with `on_delete=SET_NULL` (null means the built-in transcode). Next-source carries the channel's choice as `hls_profile: {id, mode} \| null`. **Every OutputProfile consumer excludes `hls_mode != ''`:** `resolve_output_profile`, `_resolve_hdhr_output_profile_id`, the next-source `output_profiles` map, the viewset's writes, and the frontend selects (User, HDHR, web player, the M3U-link builder). The only select that offers them is the new channel-form "HLS output" select. On an `hls` tune, `X-Relay-Output` is ignored. | ADR 0009: "reuses the existing Output Profile mechanism… and adds no new one". The per-channel FK is new because R7 says "opt-in per channel", and Output Profiles are selected per client today. A per-client HLS profile would break "one shared encode per channel". The policy is product-owned (an argv the relay builds from a probe), which is why the rows are locked. Without the exclusions, an admin could pick "HLS (Automatic)" as the HDHR profile and get a silent no-op (finding 11). |
| **D13** | **A Redirect-profile channel is served over HLS through the relay, as Proxy** (accepted, R23). It reserves and holds a provider slot like any Proxy tune. TS clients on the same channel keep their 302 unless the channel is already running, in which case they attach to it, as any client does. | HLS is made by the relay from bytes it holds. A 302 to the provider's endless TS is exactly what AVPlayer cannot play (ADR 0008). `startTune` already takes this path for an internal principal (`relay/httpapi/stream.go:701-713`). |
| **D14** | **The rewind window is the HLS output's own segments, kept on disk** (4a-3, § The live rewind window). It **starts at the channel's first HLS viewer** (R19). A TS-only channel (DVR, TS apps) keeps no window and triggers no encode. The layout is `/data/cache/rewind/<boot-id>/<channel>/<gen>/<rendition>/<seq>.m4s`, and `docker/init/03-init-dispatcharr.sh` creates the root. The depth is a setting, with a global byte cap. The last `StoreSegments` (21) segments per rendition stay in memory (amended by the 4a-1b plan, R44). A disk error degrades the window and never the live output. The window is deleted on drain, and every boot directory is deleted at start-up. Playlists become a **sliding window with no `EXT-X-PLAYLIST-TYPE`**, listing every segment in the window. | ADR 0008: about 3.6 GB per channel-hour is too big for memory, and a restart discards it rather than recovering it. `EVENT` forbids removing segments from the head, so it cannot express a full window. 60 min (the default) is well past Apple's 15-minute SHOULD (8.11). |
| **D15** | **The window lingers, and a lingering window holds its channel open** (4a-3). When the channel's last HLS session leaves (by a leave or an idle departure, not by going STOPPED), its HLS pipeline keeps running for `rewind_linger_seconds`, growing the window and holding the channel, its upstream and its provider slot. Lingering is not a client and appears in no client list or stream-limit count. A lingering channel is **reclaimable** (D16) when it has zero clients of any format and its grace has passed. The grace is `rewind_behind_live_grace_seconds` only when the last session **departed without an explicit leave** (idle departure) while **behind live**, meaning its last segment request was more than 5 × TARGETDURATION older than the newest segment (§ Presence thresholds). The grace is 0 in every other case, including **any explicit leave** (R25). For the Mino app's own zap, R11's countdown already was the grace. | R10: zapping back keeps the rewind, and the window stays continuous to live, so the encoder must keep running. A channel with a TS viewer still attached is watched, and is never reclaimed. R25: a grace after the countdown would add 10 s of "no source available" to a behind-live zap on a constrained provider. |
| **D16** | **A blocked tune reclaims a channel nobody is watching** (4a-1c; 4a-3 adds lingering windows). When `get_stream()` finds every profile full, next-source answers `capacity: {blocked: true, profile_ids: […]}`: each `profile_full` profile, and each profile sharing a `credential_full` profile's credential counter. The relay reclaims one **reclaimable** channel whose current `m3u_profile_id` is in that list. A channel is reclaimable when it has **no TS or fMP4 client**, and **either** every HLS session on it is **silent**: no request in flight, and more than **2 × TARGETDURATION** since its last request **ended** (§ Presence thresholds), **or** it is a lingering window past its grace (4a-3). Holding the Manager mutex, the relay either picks a channel on those profiles that is already releasing and waits for it, or picks, re-checks under the session-table lock, and removes a reclaimable one, or finds neither (§ Slot reclaim). In **every** case it then retries next-source **once**. At most one reclaim per tune. A zero-client channel held only by a non-zero `channel_shutdown_delay` countdown is reclaimable too, deliberately: under slot pressure that setting keeps a channel warm only until a tune needs its slot. | ADR 0005: slots stay in Django, and the relay does not decide them. Django knows why a tune is blocked; the relay knows which channels are idle. Answering with the blocking profiles keeps both facts where they are, with no Django-to-relay call inside next-source. The silence rule (4 s at the transcode target of 2 s) reclaims a session its client abandoned without a leave, long before the idle timeout. A paused AVPlayer (reloading every 2 s, M7) is never caught, and neither is a viewer whose entry request or first media-playlist long-poll is still in flight. Waiting for in-flight releases covers a leave that has stopped channel A before its release POST lands. Retrying in every case covers a release that completes before B looks at all. The #513 reconciler needs no change: a reclaimable channel is listed with its own `state` and counted as the holder it is, and a reclaim's release is an ordinary release that bumps the version. |
| **D17** | **Four settings, in the `proxy_settings` group** (4a-3):<br>- `rewind_window_minutes`: default 60; 0 disables the window; at most 120.<br>- `rewind_linger_seconds`: default 300; 0 means drop at once.<br>- `rewind_behind_live_grace_seconds`: default 10.<br>- `rewind_disk_cap_gb`: default 16.<br>They are back-filled by `get_proxy_settings`' defaults, sent on every next-source answer (A1.4), and required by the relay. | `proxy_settings` is the group the relay already receives. The names are neutral (R15). A channel snapshots them at start. The disk cap is process-wide and takes the most recent answer's value. The 120-minute ceiling is Apple's tvOS scrub-back figure. |
| **D18** | **The browser player plays live *channels* over hls.js, and keeps stream previews on mpegts.js over TS** (4a-2; R18). Playback of a channel, by UUID, from the channels table, the guide, the DVR page and the recording cards and modals, requests `output_format=hls`. It plays through hls.js where MSE or ManagedMediaSource exists (`xhrSetup` sends the `Bearer` JWT), and natively with `?token=` otherwise. When the player closes or switches, it calls the leave route (D5). Stream previews by stream hash, and the stats card's play button (`StreamConnectionCard.jsx:516`, preview-style per R26), keep `output_format=mpegts`, mpegts.js and the web-player Output Profile preference. | R17 for channels, and R18 for previews: an admin previewing a stream wants the stream as it is, with no encode and no slot held after close. R26: the stats card watches a running channel that may have only TS clients, and an HLS play there would start an encode that R19 forbids for a TS-only channel. mpegts.js and the preference therefore stay (the preference applies to the TS previews). |
| **D19** | **A Mino capability document:** `GET /api/mino/capabilities/` (4a-1b), `AllowAny`, gated by the `XC_API` network ACL (§ 4b). It reports `server_version` **deliberately**: the app shows it, and on a LAN-only server (R3) it discloses nothing the web UI's login page does not. | R16: the app refuses a server without 4a, and must be able to ask before sign-in. The route is Mino-named (R15). |
| **D20** | **Gates** (§ Testing and gates):<br>- **The Go ratchet, amended by R21.** A Go PR **may** raise `scripts/coverage_relay_go.floor`'s `missing`, but only by the uncovered statements of its own new or changed code. They are listed per file in the PR body, with **≥ 85%** statement coverage on the PR's additions, measured by the ≥12-round CI census. The reviewer checks the listing. A noise draw above the floor still gets a re-measurement PR of its own, never a bump.<br>- **A package that is not yet linked (R27).** In 4a-1a, `relay/hls` is unlinked, so it is outside the gate's denominator. 4a-1a's PR therefore shows `relay/hls`'s own per-package coverage: ≥ 85%, CI-measured with the same `-count=1 -race -covermode=atomic` flags, with a per-file uncovered listing. 4a-1b links it. It re-baselines `packages=` and `package_count` and may raise `missing` by exactly two amounts, each listed per file: `relay/hls`'s uncovered statements as 4a-1a listed them, re-measured as the maximum over 4a-1b's own 12-round CI census (R34); plus 4a-1b's own new or changed uncovered statements, with ≥ 85% on 4a-1b's own additions and a 12-round CI census. Anything else above the floor is a finding, not a bump. The same rule applies to any later PR that first links a package.<br>- **Python Gate 2 is unchanged:** new lines in its nine modules are covered, and `missing` stays 33.<br>- **Parity rows** land pinned in the PR that makes the behaviour.<br>- **E2E** runs the software encoder on CI.<br>- **AVPlayer** is a manual gate recorded in the PR body. | R21 (owner), R27 (orchestrator). Since 2c-9 no Go PR has moved `missing` (`git log -- scripts/coverage_relay_go.floor` shows one commit), so this is a change of policy, and it is recorded as one: in CLAUDE.md, and in 4a-1a's edit to the floor file's "HOW TO MOVE" header. There is no macOS or iOS 27 runner in this repository's CI, and automated AVPlayer checks belong in the app repository (Q8). |

## The ADR 0006 amendment

ADR 0006 and CLAUDE.md § State say the Go relay's client registry has no TTL, no heartbeat and no
ghost sweep. They say this because a client entry cannot outlive the goroutine that made it.
`relay/channel/channel.go:709-711` says a channel never exists without an attached client. Phase 4a
changes both, and ADR 0008's Consequences now record it:

- **An HLS session is a registry entry with no goroutine of its own** (D5). It ends by an explicit
  leave, by an admin stop, by stream-limit termination, or by the idle sweep (§ Presence thresholds). The sweep is a TTL
  in all but name, and it is the one place in the relay where presence is inferred rather than
  observed.
- **A lingering window keeps a channel running with zero clients** (D15, 4a-3).

Every consumer that acts on a channel's client count, and what each does to a lingering channel:

| Consumer | Effect on a lingering channel (0 clients) | Decision |
|---|---|---|
| `_stop_dvr_clients` (`apps/channels/api_views.py:3831-3841`), on a recording's cancellation | stops it when `client_count == 0` | Accepted: stopping a channel whose only client was a cancelled recording is the intent. The window is lost, as on any stop. |
| `Manager.release` / `stopIfStillIdle` (`relay/channel/manager.go:393-454`) | would stop it on the last client's release | Changed in 4a-3: the countdown starts only when the client count **and** the linger hold are both zero. |
| `promoteOnFirstChunk`'s invariant (`relay/channel/channel.go:709-711`) | the comment's premise ("never exists without … a client") no longer holds | Changed in 4a-3: the comment is corrected, and promotion is unaffected, because a lingering channel is already `active`. |
| The drain's client grace (`relay/drain/drain.go`) | serves no client, then stops it with every other channel | No change. The window is lost on drain (R10). |
| `/readyz`'s client count; `/proxy/ts/status/` and the stats page | show a channel with 0 clients | The payload carries `lingering_since`, so the UI can say why. Rendering it is a 4a-3 frontend line, not a new page. |
| `check_user_stream_limits`, `xc_get_info`'s `active_cons` | count no connection for it | Correct: nobody is watching. |
| `apps/proxy/slot_reconciler.py`'s `_live_holders` | counts it as holding its profile's slot | Correct: it holds a provider connection. No other zero-client channel stays active. A channel whose HLS output failed with no other client is stopped by `Manager.StopIfIdle` (§ Presence › Who ends sessions). So the only zero-client active channels the reconciler sees are lingering windows and channels in a `channel_shutdown_delay` countdown, both of which really hold their slot. |

4a-1b updates the CLAUDE.md § State sentence; 4a-3 updates it again for linger.

## Architecture

### Request flow, 4a-1

```
 Apple device / Xtream app / browser                                          relay-go (5658)
 ───────────────────────────────────                                          ───────────────
 GET /live/<u>/<p>/<id>.m3u8 ───► nginx ^~ /live/ ──auth_request──► Django authorize_stream()
                                     │  (hop: ACL, principal, channel checks, stream limit,
                                     │   X-Relay-Output-Format, client id minted)
                                     └─proxy_pass──► XCHandler: .m3u8 ⇒ format hls
                                                       │ Manager.Attach(channel, client)
                                                       │   (first client ⇒ next-source, slot, ring)
                                                       │ Channel.AttachOutput("hls[:p<id>]")
                                                       │   ⇒ probe ⇒ ffmpeg gen 0 ⇒ relay/hls segmenter
                                                       │ session table: sid → {channel, client, user,
                                                       │   profile}; wait for first-gen init segments
                                                       ◄─ 200 multivariant, URIs /hls/<v1.sid.mac>/…
 GET /hls/<token>/video.m3u8 ───► nginx ^~ /hls/ (no hop) ─► MAC ⇒ session lookup ⇒ touch
 GET /hls/<token>/video/<n>.m4s                               ⇒ serve from hls.Store
 DELETE /hls/<token>          ─────────────────────────────► leave: client_disconnect, release()
                                     idle timeout ⇒ the same leave, by the sweep
```

### State the relay adds, all in process memory

- **`hls.Pipeline`**: one per (channel, HLS profile), refcounted by sessions through
  `AttachOutput`. It owns the current generation (an ffmpeg child, its probe, its fixed output
  parameters) and the `hls.Store`.
- **`hls.Store`**: segments per rendition, keyed by media sequence, with each generation's init
  segments and discontinuity markers. It is bounded by count and bytes: from 4a-1b it keeps 21 per
  rendition (`StoreSegments`; 4a-1a's inert store kept 12), so a segment that leaves the 10-segment
  live-edge playlist stays fetchable for its own duration plus the playlist's, 2 s + 20 s, as RFC 8216
  § 6.2.2 requires of a server that removes a segment URI (R44, amended by the 4a-1b plan). That is
  about 46 MB per HLS channel at D8's top rate with AAC and AC-3 (21 × 2 s × 8.8 Mb/s), and about
  50 MB with an E-AC-3 rendition too, under the store's 64 MiB byte ceiling (computed, not measured).
- **The session table**: `session id → {channel, client id, user id, HLS profile, state, last
  activity, departed-at, bytes}`. It is lost on restart, and with it every token (D4). Players
  re-authorise, which is also what the lost window (4a-3) requires.
- **4a-3** adds the on-disk window and per-channel linger state.

Nothing is added to Redis or Postgres by the relay. `scripts/check_go_stdlib_only.sh` holds, because
every mechanism above is `os/exec`, `os`, `crypto/rand`, `encoding/binary`, `encoding/json`,
`encoding/base64`, `crypto/hmac` or `crypto/sha256`.

## The contract

### Entry (4a-1b)

| Request | Resolved by | Answer |
|---|---|---|
| `GET /proxy/ts/stream/<id>?output_format=hls` (or `?output=hls`, `m3u8`) | the hop's `resolve_output_format` with the new aliases | 200 `application/vnd.apple.mpegurl`, the multivariant |
| `GET /live/<u>/<p>/<id>.m3u8`, `GET /<u>/<p>/<id>.m3u8` | `xcForcedFormat` (`.m3u8` ⇒ `hls`) | same |
| any of the above on a channel whose probe finds no video | relay | 502 `{"error": "no video stream in the source"}`. TS clients are unaffected. |
| any of the above when the channel's HLS output has failed (§ Encoder argv, failure) | relay | 502 `{"error": "HLS output failed"}` |
| first-generation init segments not ready within 20 s (the first generation that writes a complete set, R41) | relay | 503, `Retry-After: 1`. The session is dropped. |
| draining relay | relay (`Lifecycle`) | 503, as for every tune |
| every hop denial (401, 403, 404, 429) | unchanged | unchanged |

The multivariant is sent with `Cache-Control: no-store`, because it carries a fresh token every
time.

### Session resources (4a-1b)

| Request | Answer |
|---|---|
| `GET /hls/<token>/<rendition>.m3u8` | 200 media playlist, `Cache-Control: no-cache`, and `Last-Modified` = the newest segment's publish time (Apple 8.24). It waits for the first segment, up to 20 s, then answers 503 + `Retry-After: 1`. |
| `GET /hls/<token>/<rendition>/init-<gen>.mp4` | 200 `video/mp4` or `audio/mp4`, `Cache-Control: private, max-age=86400` |
| `GET /hls/<token>/<rendition>/<seq>.m4s` | 200 with the same types and caching. **404** if the sequence is outside the store (or, in 4a-3, the window). |
| `DELETE /hls/<token>` | **204**. The session ends at once: `client_disconnect`, release, and 4a-3's linger (with grace 0, R25). **Idempotent**: a valid MAC with an unknown or already-ended sid (after a relay restart, or once forgotten) also gets **204**. Only a MAC or format failure gets 403. |
| a **GET** with a token whose MAC or format is wrong, or whose sid is unknown (removed: after a leave, a client stop, the resume window, a STOPPED session's one 410, or a relay restart) | **403** `{"error": "invalid or expired media session"}`, with no detail on which condition failed |
| a **GET** on a **STOPPED** session: its channel stopped (§ Presence › Session states) | **410** `{"error": "channel stopped"}` **once**; the entry is then removed, so a further GET is 403 |
| unknown rendition name | 404 |

Rendition names are `video`, `aac`, `ac3` and `eac3`. The relay ignores every `X-Relay-*` and
`X-Dispatcharr-Authorized` header on `/hls/`: authorisation there is the token and nothing else,
so how the playlist was authorised cannot matter (R13). The leave route is the only non-`GET`
route, and nginx needs no change for it.

### The media-session token (4a-1b)

```
sid   = base64url_nopad(16 bytes from crypto/rand)                         (22 characters)
mac   = HMAC-SHA256(key = SECRET_KEY, msg = "media-session" LF "v1" LF sid)
token = "v1" "." sid "." base64url_nopad(mac)                               (path-safe, 69 characters)
```

- The token carries **no claim**. The session table maps `sid` to the session: the channel (the
  `X-Relay-Channel` value), the client id (`X-Relay-Client`), the user id (`X-Relay-User`, or the
  string `"0"` for anonymous, as `identify()` records it, `relay/httpapi/stream.go:423-427`), and
  the HLS profile id (empty for the built-in transcode).
- **Verification:** split on `.`; check that the version is `v1`; ASCII-check; compare the MAC
  with `hmac.Equal` (mirroring `relay/control/token.go`'s `matches`); look up `sid`; check that the
  session is active or resumable. Every failure is the same 403.
- **Lifetime** is the session's (D4). There is no expiry field to renew, and nothing interrupts a
  continuously watched session.
- **Never logged.** It is a bearer credential. The `/hls/` handlers log the client id, and a unit
  test asserts that a rejected token's text does not appear in the log. `credlint` cannot see a
  string, so the test holds the rule. nginx's default access log records request paths, and so the
  token, as it already records XC credentials. That is recorded under § Risks. The token names no
  channel.

### Playlists (4a-1a renders, 4a-1b serves)

Multivariant, for a source with AC-3 (sample; the values are illustrative):

```
#EXTM3U
#EXT-X-VERSION:7
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="Stereo",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="2",URI="/hls/<token>/aac.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="ac3",NAME="Surround",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="6",URI="/hls/<token>/ac3.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=8200000,AVERAGE-BANDWIDTH=6200000,CODECS="avc1.64002a,mp4a.40.2",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="aac"
/hls/<token>/video.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=8700000,AVERAGE-BANDWIDTH=6700000,CODECS="avc1.64002a,ac-3",RESOLUTION=1920x1080,FRAME-RATE=50.000,AUDIO="ac3"
/hls/<token>/video.m3u8
```

- An E-AC-3 source adds an `eac3` group (`CODECS` `ec-3`; Q3) and a third `EXT-X-STREAM-INF`.
- `LANGUAGE` is emitted only when the probe reports a language tag.
- `BANDWIDTH` is the video `maxrate` plus the audio bitrate in transcode mode. In a copied
  rendition it is 1.25× the ring's measured rate over the probe window (the full 8 s window whenever automatic mode re-probed, R37).
- The AAC group is listed first. Which group a given device picks is Q2 (M4: macOS and iOS chose
  AAC).

Media playlist (live edge; 4a-3 extends the list to the window):

```
#EXTM3U
#EXT-X-VERSION:7
#EXT-X-TARGETDURATION:2
#EXT-X-MEDIA-SEQUENCE:<first seq listed>
#EXT-X-DISCONTINUITY-SEQUENCE:<discontinuities that have left the list>
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MAP:URI="video/init-<gen>.mp4"
#EXT-X-PROGRAM-DATE-TIME:<ring arrival of gen start + media offset, UTC, ms>
#EXTINF:2.000,
video/<seq>.m4s
…
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="video/init-<gen+1>.mp4"
#EXT-X-PROGRAM-DATE-TIME:…
#EXTINF:2.000,
video/<seq>.m4s
```

- `EXT-X-PROGRAM-DATE-TIME` is written on every segment, at about 45 bytes each.
- Audio playlists list the same sequence numbers with their own `EXTINF`. An audio segment holds
  the audio fragments whose start time falls within its video segment's span. With audio
  fragments of at least 200 ms (`-frag_duration 200000`, rounded up to whole frames: 213 ms of AAC,
  224 ms of AC-3), an audio segment is within one audio fragment, 0.225 s, of its video segment,
  which is inside Apple 7.7's +0.5 s (erratum, 4a-1a plan review; the text said 0.2 s).
- `EXT-X-ENDLIST` is never written.

### Next-source additions

- **4a-1c** adds `capacity: {blocked: bool, profile_ids: [int]} | null`. It is non-null only when
  `source` is null *because* every profile was full.
- **4a-1d** adds `hls_profile: {id: int, mode: "transcode"|"automatic"} | null`.
- **4a-3** adds the four `rewind_*` keys to `proxy_settings`.

Each addition is a serializer field in `apps/proxy/serializers.py`, and so appears in the
drf-spectacular schema. Each has a Go decoder in `relay/control/nextsource.go`. The relay requires
`hls_profile` and the `rewind_*` keys (A1.4). It treats an absent `capacity` as "not blocked",
because that field describes a failure rather than a setting.

### Relay channel payload additions

All are optional fields, preserved by `apps/proxy/relay_serializers.py`:

- `hls_encoder` (4a-1b): `"qsv"` or `"software"`, present while an HLS pipeline runs; `"copy"`
  while the current generation copies its video (4a-1d).
- `hls_generation` (4a-1b): an int.
- `lingering_since` (4a-3): a float Unix time, present while lingering.
- `rewind_window_seconds` (4a-3): a float.
- `rewind_degraded` (4a-3): a bool, present when true.

`state` gains **no** new value, so the reconciler (`_ENDED_RELAY_STATES`) and the frontend's
state handling are untouched.

## Encoder argv

`relay/hls` builds the argv in Go, from the probe and the mode. Django does not send it, because it
depends on facts only the relay can observe. This is a deliberate exception to Amendment A4.1's "Django builds the argv"
(Phase 2 spec, 2c-4; 2c-7 extended it to Output Profiles). That rule exists because an operator-authored parameter string must go through
`shlex` in one place, and this argv has no operator input (D12).

**Qualifying audio streams** (D8). A probed stream qualifies when it has a known `codec_name`,
`channels > 0` and `sample_rate > 0`. When the probe finds more than one qualifying stream, the
choice is logged. Language-based selection is a non-goal.

**The rendition set** (D8, finding 5) is decided by **generation 0's** probe and fixed for the
channel's run, as geometry is. `aac` is always declared. `ac3` is declared when generation 0's
source has AC-3 or E-AC-3, and `eac3` when it has E-AC-3. Undeclared source tracks in later
generations are ignored.

**Rendition filling.** Every generation, the first included, fills **every** declared rendition:

| Rendition | Filled from (first that applies) |
|---|---|
| `aac` | the first qualifying stream, encoded (or copied if AAC, in *automatic*); otherwise **silence** |
| `ac3` | a qualifying AC-3 stream, copied; else a qualifying E-AC-3 stream, encoded AC-3; else the first qualifying stream, encoded AC-3. Either encode is at the declared layout: 640 kb/s at 5.1, 192 kb/s at 2.0. Otherwise **silence**. |
| `eac3` | a qualifying E-AC-3 stream, copied; else the first qualifying stream, encoded with ffmpeg's `eac3` encoder at 640 kb/s for 5.1 (256 kb/s for 2.0); otherwise **silence** |

**Channel layouts** (nit 5). Generation 0 fixes each rendition's declared channel count, which is
the `CHANNELS` attribute. `aac` is always 2. `ac3` and `eac3` take generation 0's source layout,
**clamped to 2.0 or 5.1** (round 6):

- mono or 2.0 → 2.0;
- any layout with more than 2 channels → 5.1. That includes 5.0, 6.1 and 7.1: AC-3 cannot carry
  7.1, and the bitrate table has only these two.

`CHANNELS` is set to "2" or "6" to match. A generation-0 source whose layout is not exactly the
clamped one is **encoded**, not copied.
Every later generation fills a rendition **at its declared layout**:

- **Copy** only when the source's channel count matches the declared one.
- **Otherwise encode**, with `-ac` set to the declared count, up- or down-mixing: AC-3 at
  640 kb/s for 5.1 and 192 kb/s for 2.0; E-AC-3 as in the table above.
- **Canned silence** is encoded once per (codec, declared layout).

So `CHANNELS` stays true across every discontinuity.

**Silence is synthesised by the relay, never by ffmpeg** (M8). An ffmpeg `anullsrc` input keeps
the generation alive after stdin EOF, which breaks D10, and it floods unpaced audio. So a rendition
filled with silence has **no** output in the argv. Instead the segmenter writes its segments
itself:

- **The canned frame.** At the first need in the process, the relay runs one bounded ffmpeg encode
  of `anullsrc` (1 s, 10 s timeout) per (codec, declared layout): AAC-LC stereo 48 kHz 160k; AC-3
  at 640k (5.1) or 192k (2.0); E-AC-3 at 640k (5.1) or 256k (2.0). It keeps that encode's init segment and one steady-state frame (M8: every steady-state frame
  is byte-identical), and caches them for the life of the process.
- **Each segment.** For each video segment `[start, end)`, the rendition's segment holds every
  frame whose start falls before `end`, continuing from the previous segment's last frame, with
  `tfdt` at the first frame's start **on the video's timeline**: frame 0 presents with the
  generation's first video frame, so its `tfdt` is that frame's `tfdt` converted to `Ta`
  (erratum, 4a-1a plan review). It is one `moof` (with `tfhd` default duration and size,
  `tfdt` v1, and `trun` with a data offset) plus an `mdat` of the repeated frame.
- **The arithmetic is integer, and absolute per generation.** A segment's `end`, in ticks of the
  video timescale `Tv`, is converted to a frame index at the audio timescale `Ta` (48000) with a
  single ceiling, in 64-bit integers, with `spf` samples per frame (1024 AAC, 1536
  AC-3/E-AC-3). The segment ends at frame index
  `ceil(end_ticks × Ta / (Tv × spf))`, computed as `(end_ticks × Ta + Tv × spf − 1) / (Tv × spf)`.
  `end_ticks` is measured from the **generation's first video `tfdt`**, so a generation's frame
  index starts at 0. There is no intermediate floor, so the count is exact. The next segment starts where this one ended. Because every segment is
  computed from the generation's absolute sample index rather than from a running sum, the error
  never accumulates: each segment's end is within one frame of its video segment's end.
- **The generation's last segment** is the flushed tail after stdin EOF, and may be short. Its
  `end` is its video `tfdt` plus the **sum of its video sample durations** from the `trun`, never
  an assumed 2 s. (M8's Python prototype used floats and `start + 2.0` for the tail. A Go port
  must not copy either.)
- **Edit lists.** A canned init segment may carry an `edts`/`elst`. M8's AC-3 init has
  `media_time` 256, which is 5.3 ms; its AAC init has none. The relay **strips `edts`** from every
  canned init, so every silent rendition presents from 0 in its own timeline, aligned with the
  video. This is a decision, not an accident of the encode.
- **Edit lists on the encoder's own outputs** (erratum, 4a-1a plan review). Each fragmented-MP4
  output starts its `tfdt` at 0 and records where its track really starts, relative to the output's
  zero, as an **empty edit** (measured on ffmpeg 9.0.1 after a mid-GOP join: video 0.86 s, the
  copied AC-3 none). Aligned by `tfdt` alone the renditions would be 0.86 s apart, and hls.js
  ignores edit lists. So the relay moves every fragment's `tfdt` by its track's offset (the empty
  edit converted from the movie to the media timescale, less any `media_time`, never negative) and
  strips `edts` from **every** init it serves, the encoder's included; every rendition of a
  generation is then aligned by `tfdt` alone. A `media_time` longer than the empty edit cannot be
  represented that way, which is why the video output carries `+negative_cts_offsets` (R31).
- **Generations.** The init segment serves every generation's `EXT-X-MAP` for that rendition, and a
  generation boundary starts the frame count again at the new generation's first video `tfdt`.
- **What was measured.** M8 prototyped AAC and AC-3. E-AC-3's canned frame uses the same mechanism,
  is unprototyped, and is covered by 4a-1a's test.

**Transcode generation, QSV.** The software variant replaces the QSV-specific parts, as noted
inline:

```
ffmpeg -hide_banner -loglevel warning -nostats
  -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw          # software: omitted
  -fflags +genpts+discardcorrupt
  -probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0          # the probe's bound (R30);
                                                                           # 5000000 / 8000000 after a re-probe
  -map 0:v:0
  -vf "[bwdif=mode=send_field:deint=interlaced,]scale=W:H:force_original_aspect_ratio=decrease,
       pad=W:H:(ow-iw)/2:(oh-ih)/2,fps=R,format=nv12,hwupload=extra_hw_frames=64"
                                                   # software: format=yuv420p, no hwupload
  -c:v h264_qsv -preset veryfast -profile:v high -level 42                 # software: libx264
       -b:v B -maxrate M -bufsize M -g G -idr_interval 0 -forced_idr 1     #   -preset veryfast -tune zerolatency
       -force_key_frames "expr:gte(t,n_forced*2)"                          #   -profile:v high -level:v 4.2
                                                                           #   -g G -keyint_min G -sc_threshold 0
  -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof+negative_cts_offsets pipe:1
  [-map <aac source> -c:a aac -ac 2 -b:a 160k
   -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:3]
  [-map <ac3 source> -c:a copy | -c:a ac3 -ac <declared> -b:a <640k|192k> … -frag_duration 200000 pipe:4]
  [-map <eac3 source> -c:a copy | -c:a eac3 -ac <declared> -b:a <640k|256k> … -frag_duration 200000 pipe:5]
                                 # copy only when the source's channel count equals the declared one
                                 # each audio output present only when its rendition has a source
                                 # this generation; otherwise the relay synthesises its silence
```

- `W`, `H` and `R` are fixed at the first generation. `R` is the field rate for an interlaced
  source (1080i at 25 frames or 50 fields per second becomes 50p), or the frame rate for a
  progressive one, capped at 60. `G` = round(2 × R). For fractional rates (29.97, 59.94) a segment
  is then 60 or 120 frames, and `EXTINF` is 2.002 s rather than 2.000 s. That is within
  4a-1a's "2.000 s ± one frame" and within Apple 7.7.
- Bitrate `B` / `M`: height ≥ 1080 is 6 / 8 Mb/s; ≥ 720 is 4 / 5 Mb/s; otherwise 2.5 / 3 Mb/s.
- The software variant is the shape M4 ran (Appendix B), with `-nostats` added and the audio maps
  generalised.
- **The video output carries `+negative_cts_offsets`** (amended by R31). With B-frames (h264_qsv's
  default, and any copied source's) ffmpeg's mp4 muxer otherwise shifts the track by its reorder
  delay and records the shift as the edit list's `media_time` (measured, libx264 `-bf 2` from a
  keyframe-aligned start: 80 ms). The relay strips every init's edit list (§ Edit lists above), so
  the video would present that much late for the whole generation. With negative composition
  offsets (`trun` version 1) no `media_time` is needed. The 4a-1a plan measured a B-frame encode
  playing on AVPlayer, macOS 27 and the iOS 27 Simulator, across a boundary.
- **The QSV argv has not been run on Quick Sync.** No hardware was available. M2 shows only that
  the device option fails cleanly without a device. Its first run on the household host is Q1, and
  4a-1a's PR body records it.

**Detection (D11).** The test encode, with a 10 s timeout:

```
ffmpeg -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -f lavfi \
  -i color=c=black:s=256x144:r=25 -frames:v 1 -vf format=nv12,hwupload -c:v <h264_qsv|hevc_qsv> -f null -
```

Exit 0 means the encoder is usable. A missing `/dev/dri/renderD128`, any non-zero exit or the
timeout means software. `hevc_qsv` is detected separately, the first time an HEVC encode is needed
(4a-1d).

**Failure (D11, finding 7).** A generation that exits before its first segment is retried once with
the same engine. If that is QSV and it fails again, the same input is tried in software. QSV is
marked unusable for the process only if that software attempt succeeds **and** a re-run of the
detection encode fails. A transiently bad source that happens to recover on the third attempt
therefore does not write QSV off.

When every attempt fails, the relay sets a mark **on the channel**, `hlsFailedUntilBoundary`,
never on a pipeline. It logs the failure at ERROR with the last stderr lines through `redact.Line`.
No new event type is added, because the Connect vocabulary is a fixed dict. **A probe that finds
no video (`hls.ErrNoVideo`) sets the same mark** (ruling R50), and the mark records its reason, so
the 502 body says which (`no video stream in the source` or `HLS output failed`) and an audio-only
channel is not re-probed for every entry; the next source boundary clears it either way. Then:

- **Existing sessions become STOPPED:** one 410 on their next request, then removal (§ Presence).
  The self-stop goroutine drops them (§ Presence › Who ends sessions).
- **The pipeline is torn down at once.** With every session STOPPED its refcount is 0, so it stops
  exactly as at any last departure. In 4a-3 it does **not** linger, and its window is discarded.
- **New HLS entries answer 502** while the mark is set. The check is in `StreamHandler`'s HLS
  entry path, after `Attach` and before `AttachOutput`. An entry that finds the mark set has
  already registered a client (and, as the first client, may have started the channel). So it
  **calls its Attach release func before answering 502**, as any failed HLS attach does. That
  release runs the ordinary `Manager.release` → `stopIfStillIdle`, so a channel that the refused
  entry alone started is stopped by the normal idle rule, `ShutdownDelay` included.
- **The channel and its TS clients are unaffected.**

**The next real source boundary (D10) only clears the mark.** It starts nothing: there is no
pipeline and no session at that point, and a TS-only channel must trigger no encode (R19). After
the boundary, a new HLS entry is accepted again. It gets 200 and starts a **fresh pipeline** at
generation 0, with its own probe, rendition set and multivariant. So a failover to a good source
makes HLS available again, but no encode runs until someone asks for one.

A generation that dies **after** its first segment is treated as a source boundary (D10) at the
ring's current head, while its sessions keep their pipeline. That restart is bounded: a third such
death within 60 s counts as total failure, exactly as above: the mark is set, the sessions are
STOPPED, and the pipeline is torn down.

**A stalled encoder is a death** (amended by R33). A generation that writes no new video fragment
for `max(10 s, 5 × TARGETDURATION)` while the channel's ring keeps advancing is killed, and counts
as a death after its first segment (or an early exit before it) under the rules above. An encoder
that neither exits nor reads its input, a wedged device driver say, otherwise holds the pipeline
until a stop. The ring is the measure of "input advancing", not the bytes fed to the encoder,
because an encoder that stops reading its stdin stops the feed too; the clock starts at the first
ring advance after the latest fragment and stops whenever the ring has not moved for half the
timeout, so an upstream in dead air never reads as a stalled encoder. 4a-1a implements it.

**A connection that ends before it can be probed is skipped** (4a-1a plan review, finding 3; R39
for generation 0). When a generation's probe feed stopped at the next boundary and the probe found no
complete video (or failed), there is nothing of that connection to encode: the pipeline moves on to
the next boundary, as at any boundary. Generation 0 does the same and keeps its number: it starts
`JoinBehind` behind live, so a failover in the last few seconds can put a boundary inside its probe
window. Only a probe that read its whole bound and still failed ends the output. A probe whose
feed ended because the channel's ring closed is a stop, at every generation (R40): the channel is
ending.

**Automatic generation (4a-1d).** The rules are applied per rendition, from the probe. Amended by the
4a-1d plan: the copy conditions below are the whole rule; the rows the plan added are marked.

| Source | Automatic does |
|---|---|
| video H.264 (profile Constrained Baseline, Baseline, Main or High; 8-bit `yuv420p`/`yuvj420p`, 4a-1d plan), or HEVC **Main profile, 8-bit** (`yuv420p`), progressive (a `field_order` of `unknown` is progressive, R28, issue #525), with ≥ 2 keyframes in the probe window and a maximum keyframe interval K ≤ 6 s (automatic mode re-probes at the full 8 s / 5 MB bound whenever the 3 s probe saw fewer than 2 keyframes, R37), no larger than 1920×1080 and no faster than 60 frames a second (4a-1d plan: the output's geometry and rate are the source's, never scaled) | copies it (`-c:v copy`, with HEVC tagged `hvc1`). `TARGETDURATION` = max(2, ⌈K − 0.1 s⌉) (4a-1d plan: RFC 8216 § 4.3.3.1 rounds `EXTINF`, so a 2.002 s GOP keeps a target of 2 and every K keeps at least 0.4 s below `TARGETDURATION` + 0.5 s). The segmenter closes a segment before a keyframe fragment once the 2 s grid is reached, **or** when that fragment would take the segment to `TARGETDURATION` + 0.5 s or beyond (4a-1d plan: "the first keyframe at or after 2 s" alone lets a segment reach 2 s + K). |
| any other video: interlaced, MPEG-2, HEVC Main10 or any other profile or bit depth, H.264 High 10 or 4:2:2, K > 6 s, fewer than 2 keyframes seen, or larger than 1920×1080 or faster than 60 frames a second | runs the transcode chain above (H.264) |
| audio AAC-LC, stereo (4a-1d plan: the `aac` rendition declares `CHANNELS="2"` and `mp4a.40.2`) | copies it into the `aac` rendition, with `-bsf:a aac_adtstoasc` (measured, ffmpeg 9.0.1: an ADTS stream copied into MP4 otherwise fails with "Malformed AAC bitstream") |
| audio AAC of any other profile or layout, MP2, MP3 or anything else qualifying | encodes AAC 160 kb/s stereo |
| audio AC-3 / E-AC-3 | handles it as in transcode |

**A later generation copies** only when the rule above holds for its own probe **and** its video is
the declared family, its width, height and frame rate equal the run's fixed output, its K is no
longer than the run's `TARGETDURATION` allows, and its level is no higher than the declared one
(4a-1d plan). Otherwise it is encoded into the declared family. A run whose first generation was
encoded may copy later, on the same conditions.

**The probe in automatic mode** adds `-show_entries packet=stream_index,pts_time,flags,size` to
`-show_streams` (4a-1d plan; one ffprobe, measured to keep every stream field): the keyframe count
and K come from the first video stream's key packets, and the probe window's rate from the packet
sizes. Transcode mode's probe argv is unchanged. The full bound is 5 MB **or** 8 s, so above
about 5 Mb/s the window is shorter than 8 s and a K near 6 s can go unseen; that source is encoded,
which is correct and only costs the copy (§ Risks).

**The multivariant in automatic mode** (4a-1d plan, answering § 4a-1d's `CODECS` question).
- The video `CODECS` is the declared family's **ceiling**. It is read from the first complete
  generation's init, as in transcode (R41). Its level is then raised to the higher of that level and
  the family's encode level: 4.2 for H.264 (`-level 42`), 4.1 for HEVC (`-level 41` on `hevc_qsv`,
  `level-idc=4.1` on `libx265`). An H.264 profile is raised to High (`avc1.64…`).
- So a copied Main@3.0 generation is declared `avc1.64002a`, and a copied HEVC Main@3.1
  generation is declared `hvc1.1.6.L123.…`. Every generation of the run, copied or encoded, is then
  decodable at the declared profile and level.
- A later generation above the declared level is encoded, never copied (above). The init segments
  still carry each generation's own string.
- `BANDWIDTH` is the higher of transcode's figure and 1.25 × the probe window's measured rate plus the
  group's audio rate; `AVERAGE-BANDWIDTH` is the higher of transcode's and the measured rate plus it.
- The channel payload's `hls_encoder` is `"copy"` while the current generation copies its video.

**Two run-level rules for automatic** (finding 8). Both are reasoning, not measured behaviour;
4a-1d pins them with fixtures.

- **The first generation fixes the multivariant's video `CODECS` family.** A later generation (after
  a source boundary) that cannot copy is encoded **into the declared family**:
  - an H.264-declared run uses the transcode chain above;
  - an HEVC-declared run (only ever Main, 8-bit, by the copy rule above, so the declared `CODECS`
    profile and bit depth stay true) uses `hevc_qsv -profile:v main -level 41` (8-bit `nv12`) with the same `-g`, `-idr_interval 0`,
    `-forced_idr 1`, `force_key_frames` and bitrate table, tagged `hvc1`; `hevc_qsv` is detected by its own one-frame encode, the first time it is needed, and written off on its own evidence (D11);
  - without QSV, it uses `libx265 -preset ultrafast -x265-params keyint=G:min-keyint=G:scenecut=0:level-idc=4.1`
    with the same bitrate table and `force_key_frames`, tagged `hvc1`. M1 shows `hevc_qsv` and `libx265` in the production image; the 4a-1d plan ran the `libx265` argv on ffmpeg 9.0.1 (Main, level 123, a keyframe every 2 s from an MPEG-2 576i source).
- **The segmenter enforces the target duration.** A copied segment of `TARGETDURATION` +
  0.5 s or longer (it would round above the target, RFC 8216 § 4.3.3.1) ends the generation **at once**, as a synthetic source boundary at the ring's head (as a
  death after the first segment is treated), is never published, and every later generation of the run is encoded
  into the declared family. It counts toward the 3-in-60 s restart bound.
- **Every threshold measured in target durations is the pipeline's own** (R42, 4a-1d plan). The
  stall timeout is `max(10 s, 5 × TARGETDURATION)`, 30 s at 6. Its startup allowance before a
  generation's first video fragment is `max(30 s, the stall timeout)`, not three times it: before the
  first fragment the wait is an encoder's cold start, whose GOP is 2 s in every mode, or a copy's
  first closed GOP, which is at most 2 × K = 12 s of media, and three times 30 s would push the
  entry's wait (43 s) past nginx's 60 s `proxy_read_timeout` on `/hls/`. So the waits stay 43 s at
  every target. The presence thresholds (§ Presence thresholds) take the session's pipeline's
  target, set once the first generation's inits exist. The store's byte ceiling scales with the
  target (64 MiB at 2, 192 MiB at 6), which keeps RFC 8216 § 6.2.2's 21 segments of a copied
  source up to about 12 Mb/s at a target of 6, and the ten listed ones up to about 26 Mb/s; above
  that it is the runaway guard it already is (computed, not measured).

## Presence and lifecycle (4a-1b, extended by 4a-3)

### Presence thresholds

Every presence threshold is per channel, in units of the channel's `TARGETDURATION` (TD).
Transcode mode always has TD = 2. *Automatic* mode may declare up to 6 (4a-1d). The spec's
"4 s", "12 s" and "10 s" are the TD = 2 values.

| Threshold | Rule | TD = 2 | TD = 6 |
|---|---|---|---|
| silent (D16 reclaim) | no request in flight **and** more than 2 × TD since the last request ended | 4 s | 12 s |
| idle departure (D5) | no request in flight **and** at least `max(12 s, 6 × TD)` since the last request ended | 12 s | 36 s |
| behind live (D15 grace) | the session's last segment request more than 5 × TD older than the newest segment | 10 s | 30 s |
| resume window | a DEPARTED session may re-attach within 300 s, while its channel runs | 300 s | 300 s |

### Session states

```
 entry request arrives ──► ARRIVED (client registered via Attach; client_connect as its multivariant is written)
      │  the entry request stays in flight until the multivariant is written
      ▼
   ACTIVE ── DELETE /hls/<token> ──────────────► removed (client_disconnect; release())
      │ ── admin client stop / limit termination ► removed (client_disconnect; release())
      │ ── idle departure ──► DEPARTED (client_disconnect; release(); departed_at)
      │                        │ valid request within 300 s AND channel still running
      │                        │   ⇒ re-attach via AttachExisting (client_connect) ⇒ ACTIVE
      │                        └ 300 s elapse ⇒ removed
      └ ACTIVE or DEPARTED, and its channel stops (admin channel stop, reclaim, drain, the
        channel's run ending) or its HLS output fails ──► STOPPED (client_disconnect if
        still a client; client entry dropped)
                                        │ next GET ⇒ 410, then removed
                                        │ DELETE ⇒ 204, removed
                                        └ 300 s with no request ⇒ removed
```

- **Status codes.** A GET on a STOPPED session answers **410** once, and the entry is then
  removed. Any request on a removed (unknown) sid is a GET 403 or a DELETE 204. That is the
  whole mapping (§ Session resources): 410 means "re-tune", and 403 means "re-request the entry
  once".
- **Activity** is any request carrying the session's token, **and** the entry request that created
  the session. A request counts from its arrival until its response is complete. So an entry
  waiting up to 20 s for the first init segments, or a media-playlist request long-polling for the
  first segment, is activity for its whole duration. Silence and idle departure are measured from
  the **end** of the last request, and only while none is in flight.

### Locks

- **The session table is guarded by one process-wide mutex, `st.mu`.** Every session's state,
  in-flight count, last-activity time and bytes live under it. A request takes `st.mu` to look its
  session up and increment its in-flight count, and again at completion to decrement it and stamp
  the end time. The response is written with no lock held.
- **The lock order is `m.mu` → `c.mu` → `st.mu`.** Code holding `st.mu` never takes `c.mu` or
  `m.mu`, and code holding `c.mu` never takes `m.mu`. A resuming request looks its session up
  under `st.mu`, releases it, and only then attaches (see "Resume never starts a channel" below). `claim()` already takes `c.mu` (`addClient`) under `m.mu` (`manager.go:196-234`).
  ReclaimFor (§ Slot reclaim) takes `st.mu` under `m.mu`.

### Resume never starts a channel

`Manager.Attach` starts a channel when it is absent from the map (`claim` hands the caller a
gate, and `start()` runs next-source; `relay/channel/manager.go:131-181`). A resume must never
do that: a `/hls/` GET has run no authorize hop and no stream-limit check. So resume uses a new
**non-starting** attach, `Manager.AttachExisting(c, client)`, which takes the session's own
`*Channel` rather than its id (erratum, 4a-1b plan):

- It takes `m.mu` and looks the channel up.
- It registers the client only when that very channel is the map's entry for its id and its ring is
  open. A channel restarted under the same id by a later tune is a different channel, and a resume
  never joins it.
- Otherwise, including while a start is in progress, it returns `ErrChannelAbsent`, and never a
  gate.
- It has no start function.

The resume sequence:

1. Under `st.mu`, find the session DEPARTED and within 300 s. Release `st.mu`.
2. Call `AttachExisting`. On `ErrChannelAbsent`, mark the session STOPPED if it is still
   DEPARTED, and answer **410**. The entry is then removed.
3. On success, re-take `st.mu` and confirm the session is **still DEPARTED**. If it became STOPPED
   or was removed in the meantime (its channel stopped between step 1 and step 2), release `st.mu`,
   call the new attachment's release func at once, and answer **410**. Otherwise move it to ACTIVE,
   store the new release func, and serve the request.

A resume can therefore never reserve a provider slot or start an upstream, and a session the
table says is STOPPED never holds a client entry.

### Who ends sessions, and from which goroutine

- **A stopped channel's sessions are moved to STOPPED by the goroutine that decided the stop,
  before that goroutine calls `c.stop`.**
  - Admin stop and the drain end them in `Manager.Stop`/`StopAll` after `take`.
  - The last client's departure ends them in `stopIfStillIdle`, on the goroutine that released that
    client: a leave's request goroutine, the sweeper, or a TS handler. At that point only DEPARTED
    sessions remain.
  - A reclaim ends them in `ReclaimFor`, inside its critical section (§ Slot reclaim).
  - Their client entries are dropped by a new `Channel.dropHLSClients`, which emits
    `client_disconnect` and does **not** call `Manager.release`. So no `stopIfStillIdle` → `c.stop`
    runs on a channel whose `done` the caller is itself about to wait on.
- **They are never ended synchronously from inside the channel's own goroutines.** The HLS
  pipeline's failure path, and a channel whose `run()` ends by itself (sources exhausted), hand the
  job to a **new goroutine**. That goroutine does three things:
  - it marks the sessions STOPPED;
  - it drops their entries with `dropHLSClients`;
  - it calls **`Manager.StopIfIdle(c)`**, a new exported wrapper around `stopIfStillIdle`.

  `StopIfIdle` makes the manager's ordinary idle decision, off the channel's goroutine. When
  `Clients()` is 0, it removes the channel from the map, inserts it into the releasing set if its
  `released` is still open (§ Slot reclaim), and stops it, honouring `ShutdownDelay` exactly as `release` does. When a TS or fMP4 client remains,
  it does nothing, and the channel keeps running for that client.
  - **Run ended:** the channel is removed. Its slot was already released by `releaseSlot`, and
    `c.stop` returns at once because `done` has closed.
  - **HLS output failed with no other client:** the channel is stopped and removed, and
    `releaseSlot` gives its slot back.
  - **HLS output failed with a TS client:** the channel keeps running.

  Doing any of this from `run()`'s defer chain (`channel.go:444-457`) would make a `c.stop` there
  wait out `StopWait` on its own `done` (`channel.go:748-755`, 5 s by `manager.go:67-69`).
- **The HLS pipeline's `Stop` does not wait for the failure goroutine.** That goroutine is
  detached, and holds no pipeline lock. Its `StopIfIdle` → `c.stop` → `run()`'s `stopOutputs` →
  pipeline `Stop` chain waits only for the pipeline's own generation goroutines, which have
  already exited on the failure path. Nothing waits on the failure goroutine, so the chain cannot
  deadlock. The HLS-failure path's behaviour is therefore defined, but its wrong edit (a
  synchronous `Manager.release` on the pipeline's goroutine) need not self-wait. That is why the
  break-check's oracle is the run-ended case (§ 4a-1b).
- **Explicit leaves and idle departures call the session's Attach release func**, exactly as a TS
  client's handler does. It runs on the request goroutine (for a leave) or, for an idle departure,
  on a goroutine of its own that the sweeper starts (ruling R51), never on the channel's: a lone
  viewer's release can stop its channel and wait out `StopWait`, and on the sweeper's own
  goroutine that would delay every other departure behind it.

### The sweeper

- **One process-wide sweeper goroutine**, started in `main.go` with the session table, ticks every
  1 s. It:
  - departs ACTIVE sessions that have gone idle, running each departure's event and releases on a
    goroutine of its own (R51);
  - removes DEPARTED sessions past 300 s;
  - removes STOPPED sessions left unrequested for 300 s.
- Lookups apply the same expiry lazily, so a request never sees a state the sweeper has not yet
  caught up with.
- The sweeper outlives every pipeline and channel. The table is therefore bounded by the sessions
  of the last 300 s.

### The rest

- **Resume** applies only while the channel is still running: another viewer is attached, or 4a-3's
  linger holds it. In 4a-1, a lone viewer's departure stops the pipeline, and with
  `channel_shutdown_delay` at its default of 0 (`core/models.py:726`) it stops the channel too. The
  session then becomes STOPPED, a resume gets 410, and the app re-tunes. **A resume also needs its
  session's own HLS pipeline to be registered and running** (ruling R49): when the lone HLS viewer
  departs, its pipeline stops at once, and a TS client can keep the channel running without it. A
  resume then answers 410 rather than re-attaching a fresh pipeline, whose media sequence would
  restart at 0 under the same playlist URL.
- **A resumed session is not re-checked against the stream limit.** That is bounded by the 300 s
  window, and recorded rather than engineered away.
- **What a limit-1 user gets on zap:**
  - **The Mino app and the browser player** call leave before tuning the next channel. A's session
    is removed, so B's hop counts zero connections: no 429 and no wait.
  - **A third-party app that never calls leave:** with `terminate_on_limit_exceeded` on (the
    default), the hop stops A's session and admits B (`attempt_stream_termination`,
    `apps/proxy/utils.py:143-254`, which removes it through `DELETE …/clients/<id>`). With it off
    (`apps/proxy/utils.py:400-402`), B gets 429 until A's session departs: at most one idle
    timeout (12 s at TD = 2) plus one 1 s sweep tick.
- **The HLS pipeline's refcount** is the number of ARRIVED and ACTIVE sessions. When it reaches 0,
  whether by the last departure, the last leave, or the last session going STOPPED, the pipeline
  stops at once in 4a-1. In 4a-3 it starts the linger (D15), except when the sessions went STOPPED
  because the HLS output failed or the channel stopped: then it is torn down with no linger. **A
  pipeline never exists with a refcount of 0 outside a linger**, so no encode runs without a
  viewer or a window to feed (R19).

## The live rewind window (4a-3)

### Storage and bounds

- **Layout.** `/data/cache/rewind/<boot-id>/<channel>/<gen>/<rendition>/<seq>.m4s`, plus
  `init.mp4` per `<gen>/<rendition>`. `<boot-id>` is 16 random hex characters per relay start.
  - At start-up, the relay removes every directory under `/data/cache/rewind/`.
  - On drain, it removes its own boot directory after `StopAll`, best effort.
  - Both are deliberate: the window is lost on restart and on drain (R10), and there is one relay
    per deployment (ADR 0006; Phase 2 D2).
- **Writes.** Each segment is written once when it is published: to a temporary name, then
  renamed. The newest 21 per rendition (`StoreSegments`, R44) are also kept in memory, and live-edge reads never touch the
  disk.
- **Depth.** A channel's window keeps the segments whose PDT is within `rewind_window_minutes` of
  the newest. The pipeline's own sweep unlinks older ones. The window starts at the channel's first
  HLS viewer (R19). The stored segments are what a future TS reader (`?behind=`, R10) would remux
  from.
- **Cap.** After each write, the process-wide total is checked against `rewind_disk_cap_gb`. While
  it is over, the oldest segment overall is unlinked, with lingering windows' segments taken first.
  The 21 in-memory live-edge segments of any window are never unlinked.
- **Disk errors.** On `ENOSPC` or any write error, the window stops persisting for the rest of the
  channel's run. It keeps serving what it has, plus the live edge from memory, sets
  `rewind_degraded`, and logs once at WARNING. The live output never fails because of the disk.
  Tests inject the writer.
- **Arithmetic** (computed, not measured).
  - At D8's top rate with AAC and one AC-3 rendition, a channel-hour is about 3.1-3.4 GB, so the
    16 GB default holds about 4.7 channel-hours.
  - A 60-minute media playlist has 1,800 entries of about 70 bytes each, with PDT on every segment:
    about 126 KB per playlist.
  - Reloading video and one audio playlist every 2 s is about 126 KB/s per viewer, about 1 Mb/s.
  - That is small beside the 6-8 Mb/s video on a LAN. Compression is a follow-up if Q4 shows
    reload time matters.

### Playlists and seeking

- Media playlists list every segment in the window, with no `EXT-X-PLAYLIST-TYPE`, so a joining
  client sees the whole shared window. The multivariant is unchanged.
- AVPlayer's `seekableTimeRanges` then spans the window. The app seeks by date
  (`AVPlayerItem.seek(to: Date)`) using PDT.
- Programme markers and "restart programme" are EPG start times mapped to dates, available when
  the start is inside the window.
- Whether a 1,800-entry live playlist behaves well on Apple TV is Q4.

### Linger, reclaimability and the grace

- **Linger.** At the pipeline's last session end, if `rewind_linger_seconds` > 0 and the window is
  enabled, the pipeline enters LINGERING. It keeps a hold on the channel: a Manager-internal count
  that `Clients()` and every client list exclude. It stops, releasing the hold, when the linger
  elapses, when the channel is reclaimed (D16), or when a new session arrives, which cancels the
  linger and makes the pipeline ACTIVE again.
  A pipeline whose sessions all went STOPPED, because its HLS output failed or its channel
  stopped, never lingers (§ Encoder argv › Failure).
- **Channel shutdown.** `Manager.release`'s shutdown-delay countdown starts only when both the
  client count and the linger hold are zero (§ The ADR 0006 amendment).
- **Reclaimable** means: LINGERING, zero clients of every format, and now ≥ lingering-start +
  grace.
  - The grace is `rewind_behind_live_grace_seconds` only when the last session departed by the
    **idle timeout** (no explicit leave) and its last segment request was more than 5 × TD
    older than the newest segment. It is 0 otherwise.
  - An **explicit leave sets the grace to 0** (R25). For the Mino app's own zap, R11's countdown
    already was the grace, and the app calls leave when the countdown completes. The 10 s server
    grace protects only viewers that depart without a leave, such as third-party apps or a
    backgrounded app.

### Slot yield

4a-3 adds "a lingering window past its grace" to D16's reclaimable set. 4a-1c's mechanism is
otherwise unchanged.

## Slot reclaim (4a-1c)

1. **Django.** `resolve_initial_source`'s maxed-out branch computes `profile_ids`. For each of the
   channel's (or stream's) active profiles:
   - when `profile_has_capacity_for_selection` is false, it takes that profile;
   - when `pool_has_capacity_for_profile` is false, it adds every active profile sharing that
     profile's credential counter (`_credential_counter_key`, `apps/m3u/connection_pool.py:138`).

   It returns `capacity: {blocked: true, profile_ids}`. This is **advisory and read-only**: the
   reservation itself is still the slot script's atomic step on the retry.
2. **Relay** (`startTune`, initial tunes only; failover never reclaims). On `source: null` with
   `capacity.blocked`, it calls `Manager.ReclaimFor(profileIDs)`. That function holds `m.mu`, the
   mutex `claim()` holds, for one decision:
   - **(a) Wait.** If a **releasing** channel's profile is in `profileIDs`, it picks that channel.
     Releasing means removed from the map, or run ended (ring closed), with `released` not yet
     closed. Entries that have been releasing for longer than `StopWait` + `tuneBudget` are
     ignored: their stop timed out and they may never release (nit 15). It then drops `m.mu` and
     waits on `released`, bounded by `tuneBudget`. Whether the wait ends or times out, it goes to
     step 3.
   - **(b) Reclaim.** Otherwise it looks at each map channel on those profiles:
     1. **Pick.** It counts the TS and fMP4 clients under `c.mu`, and evaluates the channel's HLS
        sessions under `st.mu`, releasing each lock after reading. It picks the channel that has
        been reclaimable (D16) longest.
     2. **Test hook.** It calls the optional hook, with `m.mu` held and `st.mu` not held.
     3. **Re-check and mark.** It takes `c.mu` and then `st.mu` (the lock order in § Presence
        › Locks), re-evaluates the channel, and, if it is still reclaimable, marks every one of its
        sessions STOPPED **before releasing `st.mu`**. A request that arrives later therefore gets
        410, and one that arrived earlier has already made the channel non-reclaimable.
     4. **Remove.** Still holding `m.mu`, it deletes the channel from the map and inserts it into
        the releasing set.
     5. **Stop.** It drops `m.mu`, drops the channel's HLS client entries
        (`Channel.dropHLSClients`, § Presence), stops the channel, and waits on `released`
        (bounded by `tuneBudget`).
   - **(c) Nothing.** Otherwise there is nothing to wait on or reclaim. Step 3 still runs, because a
     release may have completed between Django's blocked answer and this call (finding 3).

   `released` is a new signal, closed after `releaseSlot` returns (`relay/channel/channel.go:445`,
   `:697-702`). The channel leaves the releasing set when `released` closes, under `m.mu`.
   **Insertion is conditional.** Each stop path inserts the channel only if `released` is still
   open, checked under `m.mu` in the same critical section as the map delete (a `select` on
   `released` with a `default`). The close handler removes the entry under `m.mu` too. So an
   insertion and a removal are ordered by the lock, and a channel whose `releaseSlot` has already
   run is never inserted. This matters for self-stop case (i), where `run()` has already ended, and
   for a last client leaving after run end. Neither leaks an entry.

   **Every path that removes a channel from the map inserts it into the releasing set in the same
   `m.mu` critical section as the delete.** There are four, and `manager.go` has exactly three
   `delete(m.channels, …)` sites plus the new one:
   - `stopIfStillIdle` (`relay/channel/manager.go:437-454`): the last client's release. An explicit
     leave, an idle departure and a TS disconnect all arrive this way.
   - `take`, via `Manager.Stop` and `StopAll` (`:327-383`): admin stop, `_stop_dvr_clients`, and the
     drain.
   - `claim()`'s delete of a channel whose ring has closed (`:220-226`).
   - `ReclaimFor` itself.

   A channel whose run ends on its own is removed by `stopIfStillIdle`, reached through the
   self-stop goroutine's `Manager.StopIfIdle` (§ Presence › Who ends sessions). Until that runs,
   case (a) treats its closed ring as releasing.

   This design does not claim every interleaving is caught by (a) or (b). A release that finishes
   before `ReclaimFor` runs leaves nothing to find, and step 3's retry is what makes that case
   succeed.
3. **Relay** retries next-source **once**, whichever of (a), (b) or (c) happened. A second blocked
   answer is 503 "no source available", as today. There is at most one wait or reclaim per tune.

**Budgets** (nit 11). `startTune` today runs one context of `tuneBudget` (14.1 s:
`relay/httpapi/stream.go:180`, from `control`'s 2 s connect and 5 s read timeouts, two attempts
and a 100 ms delay). A blocked tune now has three bounded steps, each with its own fresh budget:
the first next-source, the wait, and the retried next-source. So the worst case is about 42 s. In
the E2E and on a LAN the wait is milliseconds.

**The deterministic seam** (finding 17, round 3's finding 2). The hook runs between the pick and
the re-check, with `m.mu` held. It must not take `m.mu`, so it cannot call `Attach`. In the race
test, "a viewer arrives" means the hook **starts a request on an existing session** of the picked
channel: it takes `st.mu` and increments that session's in-flight count, and completes the request
only after `ReclaimFor` returns. With the re-check, the channel is not reclaimed, every time.
Without it, the pick's stale verdict reclaims a channel with a request in flight, every time. The
break-check therefore reddens deterministically, not one run in several thousand (compare
`manager.go:405-425`'s note on its sibling race).

## Browser player (4a-2; R18)

- **Two URL builders.**
  - `buildLiveStreamUrl` keeps its current behaviour (`output_format=mpegts`, plus the web-player
    Output Profile preference) for **stream previews** by stream hash (`StreamsTable.jsx:954`,
    `ChannelTableStreams.jsx:404`).
  - A new `buildChannelHlsUrl` returns `<path>?output_format=hls`, with no `output_profile`, for
    **channel** playback by UUID: `ChannelsTable.jsx:665-666` and `RecordingCardUtils.js`'s
    `getShowVideoUrl` (every caller listed in § Verified facts).
  - **The stats card's play button stays on TS** (`StreamConnectionCard.jsx:516`, R26). It is
    preview-style: it watches a running channel that may have only TS clients, and an HLS play
    would start an encode R19 forbids for such a channel. It keeps `buildLiveStreamUrl`.
- **The player** chooses by URL. It uses hls.js when `output_format=hls`, and mpegts.js otherwise,
  which is today's live path, unchanged.
- **hls.js is configured with:**
  - `xhrSetup` adding `Authorization: Bearer <fresh JWT>`, read at request time as the recordings
    path does; on `/hls/` requests it is harmless;
  - `liveSyncDurationCount: 3`;
  - `backBufferLength: 120`, so a 60-minute window is not held in browser memory;
  - recovery on `NETWORK_ERROR` and `MEDIA_ERROR`, as the recordings path already does.

  On a 403 from `/hls/`, the player re-requests the entry URL once.
- **Native fallback.** Otherwise, if `canPlayType('application/vnd.apple.mpegurl')`, `video.src` is
  the entry URL with the JWT as `?token=` (`QueryParamJWTAuthentication`,
  `apps/proxy/authorize.py:93-97`).
- **Leave.** When the player closes, or switches to another URL, it calls `DELETE /hls/<token>`
  through a new `api.js` function (components do not call fetch). The token comes from the media
  playlist URL that hls.js loaded. On `pagehide` the same call is made with `keepalive: true`. On
  the native path the token is not observable, and the idle timeout (and D16's silence rule) covers it.
- **Kept:** mpegts.js, its dependency and the web-player Output Profile preference (R18).
- **Error text** for HLS channels no longer says "try Chrome or Edge", because Firefox plays through
  hls.js.
- **The vitest files that change**, each assertion listed before and after in the PR:
  - `FloatingVideoUtils.test.js` (the new builder);
  - `RecordingCardUtils.test.js:150-167` (`getShowVideoUrl` now expects `?output_format=hls`, and
    the `output_profile=5` case moves to a `buildLiveStreamUrl` test);
  - `ChannelsTable.test.jsx`;
  - `Guide.test.jsx`, `DVR.test.jsx`, `RecordingCard.test.jsx`, `RecordingDetailsModal.test.jsx`
    and `ProgramDetailModal.test.jsx` wherever they assert the URL;
  - the `FloatingVideo` tests.

  - `StreamConnectionCard.test.jsx:800-804` is **tightened** to pin R26. Its expected URL
    changes from `expect.stringContaining('/proxy/ts/stream/ch-uuid-1')` to
    `expect.stringMatching(/\/proxy\/ts\/stream\/ch-uuid-1\?output_format=mpegts/)`. Without
    that, `buildChannelHlsUrl`'s URL would also satisfy the test, and the R26 break-check would stay
    green.

  `StreamsTable.test.jsx` and `ChannelTableStreams.test.jsx` do not change: both keep
  `buildLiveStreamUrl` (R18).

## 4b — the server contract (only)

The Apple app is built in its own repository (R4). What it may rely on, from a server that answers
the capability document below:

| Need | Server surface |
|---|---|
| Is this a Mino server with 4a? (R16, on "add server") | `GET /api/mino/capabilities/` → 200 JSON. It is AllowAny, gated by the `XC_API` network ACL (403 otherwise), and served by Django under `^~ /api/`. The body is `{"product": "mino", "api_version": 1, "server_version": "<version.py>", "live_hls": {"available": true, "segment_seconds": 2, "session_leave": true, "rewind_window": {"available": <bool>, "depth_seconds": <int>}}}`. `rewind_window.available` is false until 4a-3 lands, and after it whenever `rewind_window_minutes` is 0. The app refuses a server that 404s this or reports `api_version` < 1. |
| Sign in (R13) | `player_api.php?username=&password=` (no action), answering `user_info` and `server_info`. `user_info.allowed_output_formats` includes `"m3u8"` from 4a-1b. |
| Channel list | `player_api.php?action=get_live_categories`, and `…&action=get_live_streams[&category_id=]` (unchanged). |
| Playback | `http://<host>:<port>/live/<username>/<password>/<stream_id>.m3u8` → the multivariant (D2). The app never builds `/hls/` URLs itself: they come only from playlists. |
| **Leaving a channel** | `DELETE` on the token path of any media playlist URL, `/hls/<token>`. The app calls it on zap, after R11's 10 s countdown ends, when playback is dismissed, and when the app is backgrounded without Picture in Picture. It answers 204 (§ Session resources). |
| Now/next | `player_api.php?action=get_short_epg&stream_id=<id>[&limit=]` (unchanged). |
| Programme markers inside the window | `player_api.php?action=get_simple_data_table&stream_id=<id>` (unchanged). Times follow `server_info` (`apps/output/views.py`'s `_build_xc_server_info`). |
| Rewind | Seek within the playlist's range. The depth is the capability document's `depth_seconds`. |
| Errors | 401/403 from the entry means credentials or ACL. 429 means the stream limit. 403 from `/hls/`: re-request the entry URL once, then show an error. After a channel stops, an app fetching video and audio playlists in parallel may see one 410 and then 403s ("410 once", § Presence): treat both the same, by re-requesting the entry, and do not treat that 403 as a failure. 410: the channel stopped, so re-tune. 503 with `Retry-After`: retry. |

**App-side, recorded here and owned by the app repository:**

- **Demo mode.** App Review cannot reach a LAN server (R4). The app needs self-contained content it
  has the right to ship; that is the app repository's decision and needs nothing from this server.
- **App Transport Security.** Plain HTTP to a LAN host needs an ATS exception
  (`NSAllowsLocalNetworking`, and possibly `NSAllowsArbitraryLoadsForMedia` for AVFoundation). The
  app repository verifies which one covers IP-literal hosts on iOS/tvOS 27; this spec does not
  claim it.
- **Local Network permission.** `NSLocalNetworkUsageDescription`, for the first LAN connection.
- **The R11 countdown.** The app's 10 s "leaving rewind" countdown **is** the grace for its own
  zaps. The leave call is made when the countdown completes, not when it starts, and an explicit
  leave makes the window reclaimable at once (grace 0, R25). The server's 10 s behind-live grace
  applies only when a session departs without a leave. A cancelled countdown sends nothing.
- **Out of scope here:** the app's design, player UI, Top Shelf, channel up/down, the guide grid,
  and Bonjour discovery (R6: later).

## 4c — investigation brief (only)

Taken up after 4b's first playable build (R1, R14). Questions to answer before any design:

1. **Pairing flow.** A code on the Apple TV, approved by an admin in the web UI, which issues a
   per-device, revocable credential. Where is it stored (a new model), and what does an admin see
   and revoke?
2. **What the credential authorises.** Does it replace Xtream credentials entirely for the Mino app
   (R14: "drops cross-IPTV-app support")? Which endpoints are Mino-only (`/api/mino/…`)?
3. **Playlist authorisation.** The new credential must reach `authorize_stream` as a principal. Is
   that a new authenticator class in `_AUTHENTICATOR_CLASSES`, or a new surface?
4. **LAN TLS.** Is it worth it (certificate distribution to Apple devices, ATS)? Does it change the
   plain-HTTP decision in R6?
5. **Channel list and EPG.** Over Mino-only endpoints, or through `player_api.php` actions with the
   new principal?

**What 4a must keep agnostic, and does:**

- Segment authorisation depends only on the opaque media-session token (D4), never on how the
  playlist request was authorised. A 4c principal that passes `authorize_stream` gets the same
  kind of session.
- The session table holds a user id string and a client id, not an Xtream username.
- The capability document versions itself (`api_version`), so 4c can add `"pairing": {…}` without
  breaking a 4b build.

## Testing and gates

**Go (every 4a PR that touches `relay/`).**

- `go build`, `go vet` and `golangci-lint`, natively and under `GOOS=linux` and `darwin`, plus
  `go test -race`, `scripts/check_go_stdlib_only.sh relay` and the credlint ratchet.
- Unit tests use the `relaytest` stand-in for process shape: pipes, exits, EOF mid-fragment, and a
  generation that dies before its first segment.
- Real-ffmpeg tests for the packager are gated as parity row 4's pin is. They run in
  `go-tests.yml`'s `build` job against the base image's ffmpeg 9.0 (software encoder), and skip
  locally where ffmpeg is absent unless `CI` is set.
- The box reader gets fuzz tests (`testing.F`, stdlib).
- **Coverage (D20, R21).**
  - The PR runs the floor file's ≥12-round CI census.
  - Its body lists, per file, the uncovered statements of its own new or changed code, and states
    the PR's coverage on its additions (≥ 85%).
  - `missing` rises by exactly that listed count.
  - 4a-1a, the first PR to use the rule, also edits `scripts/coverage_relay_go.floor`'s "HOW TO
    MOVE" header to state it.

**Python.**

- New serializer fields, aliases and the capability view get tests in `apps.proxy.tests` and
  `apps.output.tests`.
- `authorize.py`, `next_source.py` and `relay_serializers.py` are Gate 2 modules
  (`scripts/coverage_live_path.coveragerc`). **4a-1b, 4a-1c and 4a-1d** each run
  `scripts/coverage_live_path_isolated.sh` before push and cover every new line, so the Python
  floor (`missing=33`) does not move.
- Migrations ship with reverses, and a test runs each one forward and back.

**Parity matrix.**

- New rows land **pinned** in the PR that implements the behaviour.
- `HIGHEST_ROW_ID` in `e2e/tests/guards/parity-matrix.ts` is raised in the same diff.
- Rows are appended to a new `<!-- block: phase 4 -->`. The guard already accepts it:
  `classifyTableLine` skips any one-line `<!-- … -->` (`e2e/tests/guards/parity-matrix.ts:135-141`).
  The first PR to add a row also extends the matrix's "Blocks, in file order" sentence
  (`docs/relay-parity-matrix.md:155-156`) to name the new block.
- 4a-1a, which adds the first HLS rows, widens the preamble's scope sentence ("the live TS/fMP4
  path") to include HLS (housekeeping, 4a-1a plan review).
- Ids are assigned at merge time, as the next free id.

The behaviours, by owning PR:

- **4a-1a:**
  - a generation's segments are 2.000 s ± one frame, each starting with a sync sample;
  - a source boundary ends the generation, and the next segment carries `EXT-X-DISCONTINUITY` and
    a new `EXT-X-MAP`;
  - the second generation is probed at the boundary;
  - the software fallback is selected when QSV detection fails;
  - a non-qualifying audio stream is not mapped.
- **4a-1b:**
  - an `hls` tune answers a multivariant rather than bytes;
  - `.m3u8` forces `hls`;
  - a token is refused when forged, when its MAC is tampered, or after leave or revocation;
  - an HLS session registers, and leaves on `DELETE` and after its idle timeout, with
    `client_disconnect`;
  - an admin stop ends an HLS session;
  - a Redirect channel is served over HLS as Proxy;
  - media playlists conform: ≥ 6 segments, PDT, `INDEPENDENT-SEGMENTS`, and a continuous media
    sequence.
- **4a-1c:**
  - a blocked tune reclaims a channel whose HLS sessions have left or been silent (more than 2 × TD);
  - a watched channel (a TS client, or an HLS session reloading) is never reclaimed.
- **4a-1d:** the automatic per-rendition decisions, and the declared-family rule.
- **4a-3:**
  - linger holds the channel;
  - the behind-live grace delays reclaim;
  - the playlist spans the window depth;
  - a disk error degrades the window and not the output.

**E2E.**

- **4a-0** adds six `e2e-upstream` loop assets, built at image build time by `make-asset.sh`
  variants and kept small (≤ 20 s, SD) so software encoding keeps real time on CI:
  - MPEG-2 576i + MP2;
  - H.264 1080i + AAC + AC-3 5.1;
  - HEVC progressive + AAC;
  - H.264 with a 10 s GOP;
  - H.264 + E-AC-3 only;
  - H.264 with **no audio at all**, which drives the silent-AAC path.

  A scenario channel can name its asset. `e2e-upstream/package.json`'s version is bumped with
  `CONTRACT.md`, as `e2e/tests/guards/upstream-contract.spec.ts` requires, and `e2e-upstream/test/`
  covers the field.
- **Specs in the `streaming` project** (no new project or workflow matrix change):
  - parse the multivariant and media playlists, and assert the tags and `CODECS` per asset,
    including three audio groups on the E-AC-3 asset, and one `aac` group on the no-audio asset;
  - fetch an init segment and two media segments, and assert their box structure and durations in
    TypeScript;
  - tokens: tampered MAC, and use after `DELETE /hls/<token>` and after
    `DELETE /proxy/relay/…/clients/<id>`;
  - presence: `/proxy/ts/status/<uuid>` shows an `hls` client that disappears at once after
    `DELETE /hls/<token>`;
  - failover: an upstream fault switches to an alternate with a **different** asset, and the next
    media playlist carries `EXT-X-DISCONTINUITY`;
  - **4a-1c: no waiting out the idle timeout.** The scenario creates the M3U account with
    `max_streams: 1`. `apps/m3u/models.py:386-396` syncs that value to the account's default
    profile, and the profile's `max_streams` is what the slot script counts
    (`apps/m3u/connection_pool.py:159-178`, and `reserve` at `:260-270`). So `capacity.blocked`
    genuinely comes from Django. The e2e-upstream scenario also sets `maxConnections: 1`, as a
    provider-side confirmation that A's upstream connection really closed. The "B gets 503"
    assertion measures Django's slot refusal: the E2E checks that the 503 body is "no source
    available", not an upstream refusal.
    - Tune A over HLS, `DELETE` its session, and **immediately** tune B: B plays.
    - Tune A, stop requesting for 5 s (2 × TD + 1 s at TD = 2, below the 12 s idle timeout),
      tune B: B plays.
    - Tune A with a session that keeps reloading: B gets 503.
    - A limit-1 user tunes A, calls leave, tunes B: no 429.
  - **4a-2's** hls.js playback runs in the `frontend` project (Chromium): `currentTime` advances
    on a live channel, a `DELETE /hls/…` is observed when the player closes, and the playlist
    reload cadence while paused is recorded (Q9).
- **Timeouts** in these specs are generous and are not gates. CLAUDE.md's measure-where-enforced
  rule forbids setting a latency or zap threshold from a local run, and none is set in 4a.
- **The nginx greybox spec** gains `TOKEN_BOUND_TARGETS = ['/hls/']` and a fifth test:
  `proxy_pass http://relay_go`, `proxy_buffering off`, the blanking include, and **no**
  `auth_request` and no `internal;`.
  - `/hls/` joins neither `PROXY_BOUND_TARGETS` nor `RELAY_BOUND_TARGETS`. The first test filters
    by its own list, and the second requires the hop on every member, so both stay exact.
  - The file's header comment and CLAUDE.md's nginx buffering paragraph are updated in the same PR.

**AVPlayer (manual gate, 4a-1b and 4a-3).** The owner runs the M4/M7 probe shape against the
branch's image on the household host, on macOS, the iOS 27 Simulator and the Apple TV. The PR body
records the probe output: ready time, frames, behind-PDT, the selected audio format, pause
behaviour, and (4a-3) a seek into the window. **Ruling R45** (amended by the 4a-1b plan): the
owner's hardware runs (the Apple TV, Quick Sync, Q1-Q5 and Q7) do not gate a 4a merge and stay owed
as follow-ups. What gates 4a-1b is CI plus software-encoder evidence, and the implementer's own
AVPlayer run on macOS 27 and the iOS 27 Simulator against the branch's relay, whose output the PR
body carries (the 4a-1b plan § AVPlayer).

## The PRs

Each PR:

- is branch `migration/phase4-<id>-<slug>`, opened as a draft;
- is planned and implemented through `plan-review-fix`, `implement-review-escalate` and
  `pr-merge-gate`;
- carries break-checks: a named wrong edit, the test that reddens with a message naming the
  mechanism, then the revert.

4a-1b and 4a-1c are security-adjacent (a bearer token; slot accounting). The owner's ruling of
2026-09-27 puts every review on `opus` while it stands.

### 4a-0 — e2e-upstream fixtures

- **Scope.** The six assets and the scenario `asset` field (§ E2E), the `CONTRACT.md` and version
  bump, and `e2e-upstream/test/`. No server change.
- **Break-check.** Build an asset without its AC-3 track: the upstream's asset-shape test reddens,
  naming the missing stream.
- **Stopping point.** Inert for viewers.

PR description draft:

> **Phase 4a-0: e2e-upstream gains the codec fixtures Phase 4a's HLS tests need.** Six short loop
> assets (MPEG-2 576i + MP2; H.264 1080i + AAC + AC-3; HEVC + AAC; H.264 with a 10 s GOP; H.264 +
> E-AC-3; H.264 with no audio) and a scenario field choosing a channel's asset. `CONTRACT.md` and the package version
> move together. Spec: `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`
> § Testing.

### 4a-1a — the HLS packager (inert)

- **Scope.**
  - The new `relay/hls` package: the probe (D9), the argv builder with the qualifying-audio rules
    and the failure policy (D8, D11), the pipeline and its generations (D10), the box reader and
    segmenter (D6), `hls.Store`, and playlist rendering (D7).
  - `relay/ffmpeg` gains an extra-output-pipes spawn.
  - The channel records the ring index of each source boundary.
  - The floor file's R21 header edit.
  - Amended by the 4a-1a plan review: the probe's 3 s bound and re-probe (R30), with automatic
    mode's keyframe re-probe decided here for 4a-1d (R37); the video output's
    `+negative_cts_offsets` (R31); the stall watchdog (R33); skipping a connection too short to
    probe, at generation 0 too (finding 3, R39); a ring closing under a probe as a stop (R40); and
    `Ready` on the first generation with every init (R41).
  - No route and no Django change: nothing reaches the package.
- **Tests.**
  - Unit tests and fuzzing for the box reader, plus a stand-in for pipe shapes and early exits.
  - Real ffmpeg, software:
    - 12 s of the 1080i fixture gives aligned 2 s segments on three renditions, with correct
      `CODECS`;
    - the E-AC-3 fixture gives three audio renditions;
    - a declared-but-empty audio PID is not mapped;
    - the no-audio fixture gets a relay-synthesised silent AAC rendition (M8). Its argv has no
      audio output, the generation exits within 1 s of stdin EOF, and each silent segment's
      duration equals its video segment's to within one audio frame;
    - E-AC-3 silence: the same mechanism with the E-AC-3 canned frame, which M8 did not
      prototype.
  - Real ffmpeg, a boundary test: two fixtures with different PIDs give two generations and a
    discontinuity, and the second generation's probe reports the second source.
  - Rendition filling (finding 5). Generation 0 runs on the 1080i AAC + AC-3 fixture, and
    generation 1 on the MPEG-2 + MP2 fixture. The `ac3` rendition keeps growing across the
    boundary (encoded from MP2), and the rendition set is unchanged. The reverse direction (a
    later source adding E-AC-3) declares no new rendition.
  - Detection with QSV unavailable gives software. A source-caused early failure does **not**
    mark QSV unusable.
- **Break-checks.**
  - Remove the restart at a boundary. The boundary test reddens: "generation 1 produced no segments
    after the boundary".
  - Probe generation 1 from `JoinBehind`. The second-probe assertion reddens, naming the old
    source's codec.
  - Replace `delay_moov` with `empty_moov`. The AC-3 test reddens, naming the moov error. (Erratum,
    4a-1a plan review: dropping `delay_moov` alone stays green on ffmpeg 9.0.1.)
  - Mark QSV unusable on any early failure. The source-failure test reddens.
  - Add an `anullsrc` input to the no-audio argv. The exit-on-EOF assertion reddens, timing out.
  - Rebuild the rendition set from generation 1's probe. The rendition-filling test reddens: `ac3`
    stops growing.
- **Gates.**
  - `relay/hls` is unlinked, so it is outside the Go gate (R27). The PR body shows `relay/hls`'s
    own per-package coverage, ≥ 85%, CI-measured with `-count=1 -race -covermode=atomic`, plus a
    per-file uncovered listing. Changes to already-linked packages (`relay/ffmpeg`,
    `relay/channel`) follow R21 with the census.
  - The PR body records Q1's first QSV run on the household host if it is available. Otherwise
    that becomes the first item of 4a-1b's body.
- **Stopping point.** Inert.

PR description draft:

> **Phase 4a-1a: the HLS packager (inert).** Adds `relay/hls`, which turns a channel's ring into
> fMP4/CMAF HLS renditions. A probe (at each generation's own start) decides deinterlacing,
> geometry and which audio streams qualify. One ffmpeg per generation writes video, stereo AAC and
> AC-3/E-AC-3 on separate pipes, and a segmenter cuts 2-second segments and renders playlists. The
> encoder restarts at every source boundary, because a surviving encoder silently drops a source
> with different PIDs (spec M3). Quick Sync when the one-frame detection succeeds, libx264
> otherwise, and QSV is only written off for the process when the failure is shown to be the
> device's. No route reaches it yet. Spec D6-D11; ADR 0009. Coverage: census <rounds>; uncovered
> statements of this PR, per file: <list>; coverage on additions <n>% (R21). Break-checks: <four,
> with red output>. QSV on the household host: <result, or "first item of 4a-1b">.

### 4a-1b — live HLS end to end

- **Scope, relay.**
  - `identify()` accepts `hls`, and `xcForcedFormat` maps `.m3u8`.
  - The HLS entry path in `StreamHandler`.
  - The opaque token and session table (D4).
  - The `/hls/` routes, including `DELETE /hls/<token>`.
  - Presence (D5, § Presence): the session states (STOPPED included), `st.mu` and its lock order,
    the process-wide sweeper started in `main.go`, `Channel.dropHLSClients`, events, resume, and
    ending the session through `DELETE …/clients/<id>`.
  - Redirect as Proxy (D13).
  - `hls_encoder` and `hls_generation` in the channel payload.
- **Scope, Django.**
  - `_FORMAT_ALIASES`.
  - `_xc_allowed_output_formats` gains `m3u8`.
  - `get.php` with `output=m3u8|hls` emits `/live/u/p/<id>.m3u8` with no `output_format` query
    (R9).
  - The capability view, its serializer and its URL.
  - `relay_serializers.py` fields.
- **Scope, nginx and Docker.** `location ^~ /hls/`, and a commented `/dev/dri` note on the
  compose files' relay-bearing services naming Quick Sync for HLS.
- **Scope, docs.**
  - CLAUDE.md: the nginx paragraph; the § State registry sentence (the ADR 0006 amendment); "no
    HLS output" becomes history.
  - `README.md:153`, reworded to "live only" (F1).
  - The parity matrix preamble and rows.
  - `e2e/COVERAGE.md`.
- **Tests.** As § Testing lists for 4a-1b, plus these Go tests:
  - STOPPED: after an admin channel stop, a GET gets 410 once, and 403 after that. A DELETE gets
    204.
  - Self-stop without self-wait (round-4 finding 2, round-5 finding 1). Three cases, each with two
    HLS sessions attached:
    - **(i) Run ended** (the stand-in source exhausts every candidate). The sessions become STOPPED
      and the channel is removed from the map within 1 s, with no "source goroutine did not return
      in time" warning (`channel.go:748-755`). **This case is the break-check's oracle.**
    - **(ii) HLS output fails, no TS client.** The sessions become STOPPED, and the channel is
      stopped and removed within 1 s. The control-plane stub records its release (the slot comes
      back).
    - **(iii) HLS output fails, one TS client attached.** The sessions become STOPPED. The channel
      stays in the map, running, and the TS client keeps receiving bytes.

    The admin-stop path is kept as a coverage row: a GET gets 410 within 1 s of `Manager.Stop`
    returning.
  - HLS failure and recovery (round-6 finding 1). A channel with a TS client and an HLS session.
    The stand-in fails every generation attempt on the first source, and succeeds after the source
    switch.
    - The session gets 410 once, the pipeline is torn down, and a new entry answers 502.
    - While the mark is set, no ffmpeg HLS generation is running: the stand-in records zero
      spawns.
    - A source switch clears the mark. The stand-in still records **no** spawn until the next
      entry. That entry answers 200 and starts generation 0 of a fresh pipeline.
  - Resume never starts a channel (finding 1). A test hook between the resume's lookup (step 1)
    and `AttachExisting` (step 2) stops the channel. The GET answers 410. The control-plane stub
    sees **no second next-source call**, and the session table ends with no entry for that sid. A
    second case uses the same hook to stop the channel between step 2 and step 3: the fresh
    attachment's release func is called, and the answer is 410.
  - The sweeper: after a lone viewer departs and the pipeline and channel stop, the session table
    is empty within 300 s + one tick.
- **Break-checks.**
  - Look up the session without verifying the MAC. The tampered-MAC spec reddens: 200 where 403
    is expected.
  - Make `DELETE /hls/<token>` return 204 without ending the session. The post-leave spec reddens.
  - Put `auth_request` on `^~ /hls/`. The greybox fifth test reddens.
  - Remove the session end from the client stop. The revoke spec reddens.
  - On the self-stop paths, mark and drop the sessions **synchronously from `run()`'s defer
    chain** through `Manager.release`, instead of on a new goroutine. Self-stop case (i)
    reddens.
    `Manager.release` → `stopIfStillIdle` → `c.stop` then runs on the channel's own goroutine,
    before `close(c.done)` (the defers at `channel.go:444-457` run `stopOutputs` first and
    `close(done)` later). So `stop` waits its full `StopWait` (5 s) and logs "source goroutine did
    not return in time", which names the mechanism. Cases (ii) and (iii) are coverage only: on the
    HLS-failure path the wrong edit runs on the pipeline's goroutine, which need not self-wait.
  - Start a new generation at the boundary instead of only clearing the mark. The recovery test
    reddens: the stand-in records a spawn with no session attached.
  - Drop the sessions without calling `Manager.StopIfIdle`. Self-stop cases (i) and (ii) redden:
    the channel stays in the map, and in (ii) it keeps its slot with zero clients.
  - Resume through the ordinary starting `Attach` instead of `AttachExisting`. The resume test
    reddens: the stub records a second next-source call. (Under R49 the GET itself still ends
    410, at the re-attach to its own pipeline, so the second call is the oracle.)
  - Run the idle sweep per pipeline. The sweeper test reddens: the departed entry is never
    removed.
- **Gates.** The Python Gate 2 isolated run (`authorize.py`, `relay_serializers.py`). The Go gate
  under R27: 4a-1b first links `relay/hls`, so it re-baselines `packages=` and `package_count`, and
  raises `missing` by exactly two amounts, each listed per file: `relay/hls`'s uncovered
  statements as 4a-1a listed them (re-measured as the census maximum, R34), plus 4a-1b's own. It needs ≥ 85% on its own
  additions and a 12-round CI census.
- **Also carried by 4a-1b** (amended by the 4a-1b plan): `hls.StoreSegments` rises from 12 to 21,
  so a segment removed from the live-edge playlist stays available for its duration plus the
  playlist's (RFC 8216 § 6.2.2; R44; § State); the E2E records the failover gap in software on CI
  (Q6) and whether CI's software transcode of the 1080i fixture keeps real time (R29), each a
  measurement and neither a gate; `README.md`'s HLS line is corrected (F1).
- **Manual gate.** The AVPlayer run: macOS and the iOS 27 Simulator by the implementer, against the
  branch's relay; the Apple TV by the owner, owed and not gating (R45).
- **Stopping point.** Not on its own. On a slot-constrained provider a third-party app that never
  calls leave holds its slot for the idle timeout, so 4a-1c follows directly.

PR description draft:

> **Phase 4a-1b: live HLS end to end.** A live tune whose format resolves to `hls`
> (`?output_format=hls`, or an Xtream `.m3u8` URL) now answers a multivariant playlist instead of
> bytes. Segments and media playlists live under `/hls/<token>/…`, where the token is an opaque,
> relay-minted session id with an HMAC of `SECRET_KEY` (context `media-session`). It names no
> channel and lives exactly as long as its session: an explicit `DELETE /hls/<token>`, an idle
> timeout, an admin stop or a relay restart ends it. An HLS viewer is a client in the relay's
> registry, so stream limits, admin stop and stats need no special case. `player_api` advertises
> `m3u8`, `get.php?output=m3u8` emits `.m3u8` URLs, and `/api/mino/capabilities/` tells the Apple
> app this server has 4a. Spec D2-D5, D13, D19. This amends ADR 0006's registry sentence (spec
> § The ADR 0006 amendment). AVPlayer manual gate: <probe output>. Refs: ADR 0008, ADR 0009.

### 4a-1c — slot reclaim

- **Scope.**
  - Django: `capacity` on next-source (the serializer, and the computation in
    `resolve_initial_source`).
  - Relay: the releasing set, the `released` signal, `Manager.ReclaimFor` with its test hook, and
    the single retry in `startTune`.
  - The D16 reclaimable predicate for HLS-silent channels.
  - Parity rows.
- **Tests.**
  - Django: `profile_ids` with `profile_full` and `credential_full` siblings.
  - Go: the predicate table (a TS client; a reloading session; sessions silent for 2 × TD + 1 s).
  - Go: the hook-driven race. The hook starts a request on an existing session of the picked
    channel (§ Slot reclaim, the deterministic seam), and the channel must not be reclaimed.
  - Go, **(c)**: a release that completes before `ReclaimFor` runs. The stub answers the first
    next-source "blocked" and the retry "source". With no releasing and no reclaimable channel,
    B's tune still succeeds through step 3's retry.
  - Go: a releasing entry older than `StopWait` + `tuneBudget` is ignored, and case (b) proceeds.
  - Go, **(a)**: the releasing wait. A control-plane stub holds channel A's release POST open.
    The test calls leave on A, then `ReclaimFor` for B's profiles. It asserts B waits on A's
    `released` and its retry succeeds once the stub releases. It also asserts, under a test hook
    placed between A's map delete and the end of that critical section, that A is always found
    in the map, in the releasing set, or with `released` already closed, on each of the four stop
    paths. It asserts too that an entry never outlives its `released` (the round-6 conditional
    insertion).
  - Go, **(b)**: in-flight activity. An entry request is held in its init wait, and a
    media-playlist request in its long-poll, for longer than 2 × TD. `ReclaimFor` must not pick
    the channel. Once each request completes and more than 2 × TD passes, it must.
  - E2E: the four no-wait scenarios (§ E2E).
- **Break-checks.**
  - Reclaim on the pick's verdict, without the re-check under `st.mu`. The hook-driven race test
    reddens on every run: the channel is reclaimed with a request in flight.
  - Retry next-source only after (a) or (b). Test (c) reddens with a 503.
  - Omit the credential siblings. The Django test reddens.
  - Skip the releasing wait (case (a)). The Go releasing-wait test reddens deterministically,
    because B's retry answers 503 while the stub holds A's release. The immediate-zap E2E stays as
    behaviour coverage only: on the E2E container the release lands in milliseconds, so it is not
    this break-check's oracle.
  - Insert into the releasing set after leaving the lock on one stop path. The Go hook assertion
    reddens, naming that path.
  - Measure silence from request arrival. Test (b) reddens.
  - Count a reloading session as silent. The "B gets 503" scenario reddens with a 200.
- **Gates.** The Python Gate 2 isolated run (`next_source.py`), and the Go census with its R21
  listing.
- **Stopping point.** Yes. This closes 4a-1: live HLS on Apple devices, with zaps as fast as TS.

PR description draft:

> **Phase 4a-1c: a blocked tune reclaims a channel nobody is watching.** When every provider
> profile is full, next-source now says which profiles blocked the tune. The relay waits for any
> release already in flight on them, otherwise stops one channel on those profiles that has no
> TS client and whose HLS sessions have all left or gone silent for more than two target
> durations, and retries once. Slots stay Django's decision (ADR 0005): Django names the blocking
> profiles, and the relay only chooses among channels it knows are unwatched. A paused AVPlayer
> keeps reloading every 2 s and is never reclaimed. The #513 reconciler needs no change. Spec D16.

### 4a-1d — the automatic HLS profile

- **Scope.**
  - A `core` migration: `OutputProfile.hls_mode`, and the two locked rows (`command="ffmpeg"`,
    `parameters="(built by the relay)"`), with a reverse.
  - A `channels` migration: `Channel.hls_output_profile`, `SET_NULL`, with a reverse.
  - Serializers and viewset: `hls_mode` is read-only, and HLS rows cannot be created or edited.
  - Every exclusion D12 lists, backend and frontend.
  - Next-source `hls_profile`.
  - The channel form's "HLS output" select. Bulk edit is not in scope.
  - The relay's automatic rules, including the declared-family rule with `hevc_qsv` and `libx265`.
  - Counting keyframes in the probe window (`Probe.Keyframes`), which 4a-1a's re-probe decision
    already reads in automatic mode (R37).
  - The stall watchdog's timeout becomes per-pipeline, `max(10 s, 5 × TARGETDURATION)` at the
    pipeline's own TARGETDURATION (R42): 4a-1a's is a constant for transcode's TD = 2, 10 s.
  - Which video `CODECS` string the multivariant advertises when a copied and an encoded HEVC
    generation differ in level (for example `hvc1…L120` against `L123`). Since R41 the string is
    read from the first generation that writes a complete set of inits, not from generation 0's
    probe; in transcode every generation's string is the same (4a-1a plan review, round 4).
    **Answered by the 4a-1d plan:** the family's ceiling (§ Automatic generation › The multivariant
    in automatic mode), and each attempt of a generation starts with no codec recorded by an
    earlier attempt, so a failed Quick Sync attempt's string never mixes with its retry's.
  - The startup allowance and the entry's waits at a target of 6 (R42, R55, R57): the allowance is
    `max(30 s, the stall timeout)`, and the waits stay 43 s (§ Automatic generation).
  - The `hls_profile` key is required on every next-source answer, as `output_profiles` is: an
    answer without it is a contract mismatch that answers an HLS entry 502, and a TS tune is not
    affected (4a-1d plan). A non-degraded failover answer refreshes the channel's choice, as it
    refreshes `output_profiles`; entries after it use the new profile.
  - Issue #525 (R28) is closed by 4a-1d's implementation PR, which lands the copy rule's
    `unknown`-is-progressive row.
- **Tests.**
  - Migrations forward and back.
  - A per-rendition decision table against the 4a-0 assets.
  - Declared-family: a copied-HEVC run whose next source is MPEG-2 is encoded as HEVC, not H.264.
  - Over-long segment (finding 10): a copied segment exceeding the target + 0.5 s ends the
    generation at once, and the next generation is encoded.
  - Presence at TD = 6 (finding 6): a reclaim-predicate row with sessions reloading every 6 s is
    not silent. The idle sweep does not depart it within 36 s.
  - Each exclusion: the HDHR resolver ignores an HLS row, and the HDHR select omits it.
  - E2E: an automatic channel on the H.264 asset serves copied video: `hls_encoder` is `"copy"`,
    and its init segment carries the source's own `avc1` string, while the multivariant declares
    the family ceiling `avc1.64002a` (4a-1d plan; the spec's "with the source's `CODECS`" predates
    the ceiling). The HEVC asset is declared `hvc1`, and the 10 s-GOP asset is encoded.
- **Break-checks.**
  - Copy interlaced video. The decision test reddens, naming `field_order`.
  - Encode the HEVC run's second generation as H.264. The declared-family test reddens.
  - Let a copied segment exceed target + 0.5 s. The segmenter test reddens.
  - Hard-code the silence threshold at 4 s. The TD = 6 predicate row reddens.
  - Treat `field_order=unknown` as interlaced. The HEVC decision row and the real HEVC copy test
    redden (R28, #525).
- **Gates.** The Python Gate 2 isolated run (`next_source.py`, `authorize.py`), and the Go census
  with its R21 listing.
- **Stopping point.** Yes.

PR description draft:

> **Phase 4a-1d: the *automatic* HLS profile.** ADR 0009's opt-in: a channel can be set to an HLS
> Output Profile in *automatic* mode, which copies what AVPlayer accepts and transcodes only what
> it does not (MP2 → AAC; interlaced, MPEG-2 or long-GOP video → the run's declared codec). Two
> locked profiles are seeded; the choice is per channel (`Channel.hls_output_profile`) and reaches
> the relay as `hls_profile`. HLS profiles are excluded from every other Output Profile consumer,
> so they cannot be picked for HDHR, users or the web player. Spec D12. Migrations have reverses
> and a round-trip test.

### 4a-2 — the browser player plays channels over HLS

- **Scope.** § Browser player: `FloatingVideo.jsx`, `FloatingVideoUtils.js`, `RecordingCardUtils.js`,
  the channel call sites, `api.js` (the leave call), and the vitest files listed there. There is no
  server change, and mpegts.js stays.
- **Tests.** Vitest for both builders and the player's choice, and the E2E `frontend` spec.
- **Break-checks.**
  - Point `getShowVideoUrl` at `buildLiveStreamUrl`. The `RecordingCardUtils` test and the E2E
    playback spec redden.
  - Skip the leave call on close. The E2E's `DELETE` observation reddens.
  - Point stream previews at HLS. The `StreamsTable` test reddens.
  - Point the stats card at `buildChannelHlsUrl`. The tightened `StreamConnectionCard` test reddens
    (R26).
- **Stopping point.** Yes.

PR description draft:

> **Phase 4a-2: the browser player plays live channels over HLS.** Channel playback (channels
> table, guide, DVR, recordings) now requests `output_format=hls` and plays through
> hls.js (native HLS where only that exists), so Firefox plays live channels too; closing or
> switching the player ends the HLS session at once. Stream previews by stream hash, and the stats
> card's play button, stay on mpegts.js over TS with the web-player Output Profile preference, unchanged (owner rulings R18, R26).
> Spec D18. Changed tests, before → after: <list>.

### 4a-3 — the live rewind window, linger and lingering reclaim

- **Scope.**
  - The disk store, sweep, cap and degradation (D14).
  - Window playlists.
  - Linger, the grace, and lingering reclaim (D15, D16).
  - `Manager`'s linger hold, and the `channel.go:709-711` comment correction.
  - The four settings end to end (D17): `get_proxy_settings` defaults, the relay settings
    serializer, the Go `tuningFrom` keys, and the proxy-settings form fields.
  - `03-init-dispatcharr.sh` creates `/data/cache/rewind`.
  - The capability document reports the window.
  - The payload fields, and the stats UI showing `lingering_since`.
  - The CLAUDE.md § State update.
- **Tests.**
  - Unit: depth trim, cap eviction order, `ENOSPC` degradation (an injectable writer), start-up
    cleanup.
  - Unit: the reclaimable predicate with linger (a TS client attached means not reclaimable; the
    grace delays it).
  - E2E: a playlist spanning more than the 10 live-edge segments under a short configured depth.
  - E2E: a channel still running during linger with zero clients, and stopped after it.
  - E2E: a lingering window reclaimed by a blocked tune without waiting out the linger.
  - E2E (R25): a behind-live viewer that calls leave is reclaimable at once. A behind-live
    viewer that goes silent without a leave is not reclaimable during the grace, and B gets 503
    until the grace ends.
- **Break-checks.**
  - Let a channel with a TS client be reclaimable. The predicate test reddens.
  - Stop the encoder at the last session. The linger spec reddens on a stopped channel.
  - Ignore the grace. The behind-live idle-departure test reddens.
  - Apply the grace to an explicit leave. The R25 leave test reddens with a 503.
- **Manual gate.** AVPlayer seek into the window on Apple TV. Q4 is measured here.
- **Stopping point.** This completes 4a.

PR description draft:

> **Phase 4a-3: the live rewind window.** Each HLS channel now keeps its last
> `rewind_window_minutes` (60) on disk under `/data/cache/rewind`, from its first HLS viewer,
> shared by every viewer and served as a sliding HLS window so AVPlayer can pause, rewind and scrub
> back to live. After the last viewer leaves, the channel lingers for `rewind_linger_seconds` (300)
> so zapping back keeps the rewind; a lingering window gives its provider slot to a blocked tune
> (after a 10 s grace if its viewer was behind live). The window is lost on restart and drain,
> capped by `rewind_disk_cap_gb`, and a disk error degrades the window, never the live output.
> Spec D14-D17. AVPlayer seek gate: <output>.

## Open questions that need a measurement

| # | Question | Who, where | What decides |
|---|---|---|---|
| Q1 | Does D8's QSV argv run on the household host (12th-gen, UHD 770)? That covers device init, `hwupload` + `h264_qsv`, `forced_idr` with `force_key_frames` giving IDRs every 2 s, and `-level 42`. What CPU and GPU do two concurrent 1080i50 channels cost? | Owner, on the host, with the 4a-1a image: `ffmpeg` on a captured provider TS, then two live channels via the relay. | A refused option is corrected in 4a-1a, with no design change. If two channels exceed 60% of total CPU with software deinterlacing, D8's deinterlace moves to `vpp_qsv=deinterlace=2` behind a probe-driven switch. |
| Q2 | Which audio group does an Apple TV 4K pick, through a TV only and through a surround receiver? | Owner, Apple TV, the 4a-1b build. | If tvOS picks AAC with a receiver attached, the AC-3 variant is listed first (a one-line change). |
| Q3 | E-AC-3 JOC (Atmos) passthrough: does ffmpeg's `dec3` carry the JOC signalling, and does `CODECS="ec-3"` or `"ec+3"` make an Apple TV output Atmos? | Owner, with an Atmos channel if the provider has one, an Apple TV and an Atmos receiver. | Declare `ec+3` when JOC is present. Until this is measured, 4a ships `ec-3` with no Atmos claim. |
| Q4 | How does a 1,800-entry sliding live playlist behave on Apple TV: memory, CPU, reload time, seek responsiveness? | Owner, Apple TV, 4a-3, a channel watched for 60 min. | If it misbehaves, the default depth drops, and a follow-up considers compression or a shorter listed window. |
| Q5 | Zap time on the host with QSV: channel tap to first frame, cold tune. It is informational. | Owner or the app. | Whether generation 0 starts at the ring's head rather than `JoinBehind` (one constant). |
| Q6 | What is the failover gap on real hardware, from boundary to the new generation's first segment? | E2E records it (software, CI); the owner measures QSV. | Above 10 s, a follow-up considers pre-spawning the next generation. |
| Q7 | Is ffprobe's `field_order` reliable on the household's real channels (H.264 PAFF/MBAFF, MPEG-2)? | Owner: capture three channels' ring bytes and run D9's probe. | If it is unreliable, `bwdif=deint=interlaced` is applied to every source, and `R` is taken from the field rate. |
| Q8 | Are GitHub macOS runners available with an iOS/tvOS 27 runtime? | The app repository, when its CI is set up. | Whether the manual AVPlayer gate moves into the app repository's CI. |
| Q9 | Does hls.js keep reloading a live playlist while paused, as AVPlayer does (M7)? | 4a-2's E2E records the cadence. | If it stops, the browser player calls leave on pause and re-tunes on play. |

## Rejected alternatives

- **Remux by default.** ADR 0009.
- **ffmpeg's `-f hls` muxer.** D6.
- **One encoder surviving failover.** D10, M3.
- **Refusing HLS without Quick Sync.** D11.
- **Marking QSV unusable on any early generation failure.** D11: that confuses a source failure
  with a device failure.
- **A per-client HLS profile.** D12.
- **A token that carries its claims (channel, user, expiry).** It exposes the channel UUID (D4,
  finding 2).
- **A fixed absolute expiry.** It cuts off a continuously watched session (R22).
- **Binding the token to the client IP.** It breaks AirPlay and roaming.
- **Relying on the idle timeout alone to end sessions.** It holds a slot for the idle timeout (12 s at TD = 2) after every zap
  (finding 1). D5 adds the leave call, and D16 reclaims silent sessions.
- **`EXT-X-PLAYLIST-TYPE:EVENT` for the window.** D14.
- **Keeping the window in memory.** ADR 0008.
- **Starting the window at the channel's first tune of any format.** A TS-only channel would need
  an encode that nothing reads (R19).
- **Moving stream previews to HLS.** R18.
- **The relay choosing which slot to take without Django naming the blocking profiles.** ADR 0005.
- **Django calling the relay to reclaim, inside next-source.** It nests a cross-process call in a
  request the relay is itself waiting on.
- **A macOS CI job running AVPlayer in 4a.** Q8.

## Risks

- **The QSV argv is unexercised.** Q1 is its first run. Fallback degrades a wrong argv to CPU
  encoding, not to no picture, but a household host at 100% CPU is its own failure. 4a-1a must not
  merge claiming QSV works without Q1's output.
- **Lingering holds scarce provider slots.** Each zap-away holds a slot for up to 5 minutes, unless
  a blocked tune reclaims it (D16). On a two-connection provider that is correct, but it means the
  household's third channel always evicts a window.
- **A third-party client that never calls leave** holds its slot for up to 2 × TD against a
  blocked tune (D16), and its stream-limit count for up to the idle timeout plus one sweep tick. At
  TD = 2 that is 4 s and 13 s (§ Presence thresholds).
- **Advertising `m3u8`.** `allowed_output_formats` gaining `m3u8` may move third-party Xtream apps,
  Android ones included, onto HLS, and so onto one encode per watched channel. That app behaviour
  is unverified.
- **A token in the URL path is logged by nginx's default access log.** It names no channel, and
  dies with its session. The same log already holds XC credentials. A remote-access future would
  revisit both together (ADR 0008).
- **PDT drift.** Within a generation, PDT is the generation's arrival anchor plus media time. An
  upstream stall without a reconnect advances the wall clock but not media time, so PDT drifts
  behind real time by the stall's length until the next generation. That moves programme markers
  (4a-3) by the same amount. A reconnect starts a new generation and re-anchors. Measuring the
  drift on real channels is a 4a-3 E2E observation, not a gate.
- **Disk.** 3.1-3.4 GB per channel-hour of writes on whatever backs `/data`. On an SD card or a slow
  NAS that is wear and latency. The cap bounds space, not wear.
- **The failover gap** (M6: 8.9 s on the prototype host) is longer than a TS client sees today.
- **Parity-matrix growth.** Rows must land pinned. An `owed:` row would need a `PRS` vocabulary
  change, which this spec does not plan.
- **Resume bypasses the stream limit** for at most 300 s (§ Presence).

## Non-goals — deliberately out of scope

- **VOD, catch-up (timeshift) and recordings** over HLS or in the app (R2). The DVR's own HLS
  (`apps/channels/tasks.py`, `/api/channels/recordings/<pk>/hls/…`) is untouched.
- **Remote access** built into the app, and the remote-access hardening it would require (R3,
  ADR 0008).
- **Low-Latency HLS** (R8). The fixed 2 s GOP keeps it reachable later.
- **A TS reader for the rewind window** (`?behind=`, R10): a known extension. A window for
  TS-only channels, likewise (R19).
- **Stream previews over HLS** (R18).
- **Plex design weight, and deleting the HDHomeRun, M3U or XMLTV outputs** (R12).
- **Renaming** Dispatcharr to Mino, or renaming any existing identifier, route or header (R15). The
  existing `X-Dispatcharr-*` headers and `DISPATCHARR_*` variables are kept, and nothing new is
  named for Dispatcharr.
- **Android** (ADR 0008).
- **Adaptive bitrate ladders.** One video rendition per channel.
- **Audio language selection, subtitles and closed captions.**
- **Bonjour discovery** (R6: later) and **multi-profile** households (R5).
- **HLS as a deployment or user default** (D2, R23).
- **Bulk-editing the HLS profile** across channels.
- **Metrics endpoints** (Phase 2 D6's reasoning stands).

## Follow-ups noticed while writing this spec (not folded in)

- **F1.** `README.md:153` advertises "📡 **HLS Output** — Serve streams as HLS alongside existing
  container formats". That is false today. 4a-1b makes it true for **live** only, and rewrites it
  to say so.
- **F2.** `resolve_output_format` returns a user's `custom_properties.output_format` **unvalidated**
  (`apps/proxy/authorize.py:277-281`). Any string stored there reaches the relay and is refused
  with 501. This is pre-existing and recorded, not fixed.

## Done log

Filled in as PRs merge.

| Item | PR | Merged |
|---|---|---|
| Spec, ADR 0008, ADR 0009, glossary | #523 | 2026-09-27 (`6c985473`) |
| 4a-0 e2e-upstream fixtures | #526 | 2026-09-27 (`97675e88`) |
| 4a-1a packager | #529 | 2026-09-28 (`fabc663a`) |
| 4a-1b live HLS end to end | | |
| 4a-1c slot reclaim | | |
| 4a-1d automatic profile | | |
| 4a-2 browser player | | |
| 4a-3 rewind window | | |

## Changelog

- **2026-09-27, v1.** First draft, written against `560c6d58` with the prototypes M1-M7.
- **2026-09-27, round 1, reviewed at `8bec4ca9`** (one blocking finding, eleven should-fix, eleven
  nits; owner and orchestrator rulings R18-R24).
  - **Leave call.** An explicit `DELETE /hls/<token>`, and D16 reclaims channels whose HLS
    sessions are silent for more than 2 × target duration. Reclaim moves into 4a-1 as the new
    4a-1c, and the E2E no longer waits out the idle timeout (finding 1, R24).
  - **Token.** It is now opaque, holds no claims, has no absolute expiry, and an anonymous user is
    `"0"` (finding 2, R22).
  - **ADR 0006 amendment.** Recorded, with every zero-client consumer listed (finding 3).
  - **Go ratchet.** Amended per R21 (finding 4).
  - **D11.** QSV is marked unusable only on device evidence (finding 5).
  - **Probe.** It starts at the generation's own start (finding 6).
  - **Audio and failure.** The qualifying-audio rules, the silent AAC track, and the HLS output
    failure policy (finding 7).
  - **Automatic mode.** The declared-family rule now specifies HEVC (finding 8).
  - **Break-checks.** Those that could not fail are replaced (findings 9, 10 and 17).
  - **D12.** It lists every Output Profile consumer, the seeded rows' fields and `on_delete`
    (finding 11).
  - **D18.** Rewritten per R18: channels go over HLS, previews stay on TS, mpegts.js stays
    (finding 12).
  - **The window** starts at the first HLS viewer (R19).
  - **E-AC-3** sources get three audio renditions (R20).
  - **PR layout.** 4a-0 is split out (finding 18), and 4a-3a and 4a-3b are merged into 4a-3.
  - **Nits 13-16 and 19-23** are applied.
- **2026-09-27, round 2, reviewed at `fdcf23d2`** (three should-fix, eight nits; rulings R25, R26).
  - **Reclaim is race-free** (finding 1). The wait-or-reclaim pick is one `m.mu` critical section.
    Every stop path inserts into the releasing set atomically with its map delete (the four are
    named). In-flight requests count as activity. There are Go tests (a) and (b).
  - **The releasing-wait break-check's oracle** is the Go stub test, not the E2E (finding 2).
  - **An explicit leave sets the behind-live grace to 0** (finding 3, R25).
  - **The stats card's play button stays on TS** (R26).
  - **Nits.**
    - 4: D11 needs the software success **and** a failed detection re-run.
    - 5: M1 lists `libx265`.
    - 6: a failed HLS output recovers at the next source boundary, and restarts are bounded to 3 in
      60 s.
    - 7: DELETE with a valid MAC and an unknown sid answers 204, and the 403 row covers only GETs.
    - 8: automatic copies only HEVC Main 8-bit, so a later HEVC encode matches the declared
      profile and bit depth.
    - 9: a no-audio fixture and a silent-AAC test.
    - 10: D16 covers zero-client channels held by `channel_shutdown_delay`.
    - 11: the PR body now describes seven PRs.
- **2026-09-27, round 3, reviewed at `61fedfbf`** (one blocking, nine should-fix, eight nits; ruling
  R27; a fresh cold reviewer).
  - **No-audio mechanism (finding 1).** The `anullsrc` input is replaced by relay-synthesised
    silence, measured as M8: the generation exits in 0.065 s on EOF, and AVPlayer plays AAC and
    AC-3 silence. The `anullsrc` failure was confirmed on the production image.
  - **Reclaim concurrency, re-derived (findings 2, 3).**
    - `st.mu` guards session activity, with the lock order `m.mu` → `c.mu` → `st.mu`.
    - The hook starts a request on an existing session, and never calls `Attach`.
    - The re-check and the STOPPED marking are atomic under `st.mu`.
    - Case (c) retries too, and the "always seen" claim is dropped.
    - Stuck releasing entries are skipped, and each step has its own budget (nits 11, 15).
  - **Session lifecycle (finding 4).** A STOPPED state (one 410, then removal), sessions ended by
    the stopping goroutine and never inside `run()`, and a process-wide sweeper.
  - **Rendition set (finding 5).** Fixed at generation 0, and every later generation fills every
    declared rendition, by copy, encode or silence.
  - **Presence thresholds (finding 6).** They scale with TD: silence 2 × TD, idle
    `max(12 s, 6 × TD)`, behind-live 5 × TD.
  - **E2E (finding 7).** 4a-1c's E2E seeds `max_streams: 1` on the M3U account.
  - **Go gate for an unlinked package (finding 8, R27).**
  - **Hollow break-check (finding 9).** The `StreamConnectionCard` test is tightened.
  - **Over-long copied segment (finding 10).** It ends the generation at once.
  - **Nits.**
    - 12: the guard already accepts the block marker.
    - 13: the PR body is updated.
    - 14: the citation is A4.1.
    - 16: `G = round(2 × R)`, and EXTINF can be 2.002.
    - 17: the probe runs outside `outMu`.
    - 18: the deliberate 2 s target is recorded.
- **2026-09-27, round 4, reviewed at `4456392f`** (two should-fix, six nits).
  - **Resume never starts a channel (finding 1).** It goes through a non-starting
    `AttachExisting`, which answers 410 when the channel is absent, and re-checks the session
    under `st.mu` after attaching. There is a hook-driven Go test and a break-check (the stub sees
    a second next-source call).
  - **The self-stop test and its wrong edit target the real self-wait (finding 2):** `run()`
    ending on its own, and HLS-output failure, rather than admin stop.
  - **Nits.**
    - 3: canned inits have `edts` stripped.
    - 4: integer absolute-index arithmetic, and the tail's `end` from sample durations.
    - 5: declared channel layouts are kept across generations, and E-AC-3 has a bitrate.
    - 6: CLAUDE.md's R27 clause is completed.
    - 7: `hls.GenerationExitGrace` is named separately from `ffmpeg.KillWait`.
    - 8: the 4b Errors row covers a 410 followed by 403s.
- **2026-09-27, round 5, reviewed at `de6dfb9c`** (one should-fix, two nits).
  - **Self-stop paths now reach the manager's idle decision (finding 1).** After dropping the
    sessions, the self-stop goroutine calls a new `Manager.StopIfIdle(c)` (wrapping
    `stopIfStillIdle`, off the channel's goroutine).
    - The test is split into three cases: run ended; HLS failure with no TS client; HLS failure
      with a TS client. The run-ended case is the break-check's oracle.
    - It is stated that the HLS pipeline's `Stop` does not wait for the detached failure goroutine.
    - The :844 claim and the reconciler row are made consistent.
  - **Nits.**
    - 2: every audio encode and canned frame follows the declared layout, including D8, the `ac3`
      row and the argv's `-ac`.
    - 3: the silence frame index is a single integer ceiling, measured from the generation's first
      video `tfdt`.
- **2026-09-27, round 6, reviewed at `a116d934`** (one should-fix, two nits).
  - **The failed mark lives on the channel (finding 1),** as `hlsFailedUntilBoundary`.
    - STOPPED tears the pipeline down at refcount 0, with no linger.
    - The next source boundary only clears the mark, and the next entry starts a fresh pipeline
      (200). A pipeline never exists at refcount 0 outside a linger (R19).
    - The recovery test and break-check are added, and the refcount wording is reconciled.
  - **Nits.**
    - 2: a stop path inserts into the releasing set only while `released` is still open, checked
      under `m.mu`.
    - 3: declared `ac3`/`eac3` layouts are clamped to 2.0 or 5.1.
- **2026-09-27, round 7 PASS at `e1dcfa5c`; nits applied** (the recovery test's stand-in
  succeeds after the switch; a 502-refused entry calls its release func first).
- **2026-09-27, amended by the 4a-1a plan review** (PR #528, round 1 reviewed at `ae8dde9f`;
  rulings R30-R36).
  - **R30.** The probe is bounded to 3 s / 3,000,000 bytes, with one re-probe at 8 s / 5 MB when the
    video lacks width, height or `field_order`; the encoder's input analysis follows the bound its
    probe needed (D9, § Encoder argv). Measured: at 8 s the probe alone took 7.7-9.5 s of wall time
    on a paced feed.
  - **R31.** The video output carries `+negative_cts_offsets`, so a B-frame encode keeps its sync
    once the relay strips edit lists (§ Encoder argv).
  - **R33.** A stalled encoder is a death (§ Encoder argv, failure).
  - **Errata** (R32): § Playlists' "within 0.2 s" is "within one audio fragment, 0.225 s"; the
    silent `tfdt` is on the video's timeline; every init's edit list is stripped and every
    fragment's `tfdt` moved, not only the canned inits'; the `delay_moov` break-check swaps it for
    `empty_moov`; a later generation whose connection ends before it can be probed is skipped.
  - **Housekeeping** (R32): the parity preamble's scope sentence moves to 4a-1a; the Done log
    records #523 and #526.
- **2026-09-27, amended by the 4a-1a plan review, round 2** (reviewed at `178b92b8`; rulings
  R37-R39).
  - **R37.** Automatic mode re-probes at the full bound when the 3 s probe saw fewer than 2
    keyframes, so the copy rule's K ≤ 6 s and the copied rendition's bitrate over the probe window
    stay observable (D9, § Automatic generation, § Playlists). The default re-encode keeps 3 s.
  - **R38.** The stall watchdog is a parity row.
  - **R39.** Generation 0 skips a connection too short to probe, as later generations do.
  - **Errata:** the edit-list cross-reference points above; D20 and § Testing state R34's census
    maximum for the re-measured `relay/hls` amount.
- **2026-09-27, amended by the 4a-1a plan review, round 3** (reviewed at `dea8332a`; rulings
  R40-R42).
  - **R40.** A ring that closes during a probe is a stop, at every generation (§ Encoder argv,
    failure).
  - **R41.** `Ready`, and the multivariant's init wait, are answered by the first generation that
    writes a complete set of init segments (§ Entry).
  - **R42.** 4a-1d makes the stall watchdog's timeout per-pipeline (§ 4a-1d).
  - **Errata:** § 4a-1a's scope note names R37, R39, R40 and R41.
- **2026-09-27, amended by the 4a-1a plan review, round 4** (reviewed at `255bd7c7`).
  - **4a-1d:** decides which video `CODECS` string the multivariant uses when copied and encoded
    HEVC generations differ in level (§ 4a-1d).
- **2026-09-28, amended by the 4a-1b plan** (`docs/superpowers/plans/2026-09-28-phase4-4a1b-live-hls.md`;
  rulings R44 and R45).
  - **R44.** `hls.StoreSegments` is 21 from 4a-1b, so a segment that leaves the live-edge playlist
    stays available for its duration plus the playlist's (RFC 8216 § 6.2.2): § State, D14 and
    § Storage and bounds, which said 12. About 46 MB per HLS channel at the top rate.
  - **R45.** The owner's hardware measurements do not gate a 4a merge; § Testing and gates' AVPlayer
    paragraph and § 4a-1b's manual gate say so, and name the implementer's own macOS and iOS
    Simulator run as the AVPlayer evidence 4a-1b's merge rests on.
  - **Erratum:** `Manager.AttachExisting` takes the session's `*Channel`, not its id, and joins
    only that very channel (§ Resume never starts a channel).
  - **Housekeeping:** § 4a-1b names what it also carries (R44, Q6, R29, F1); the Done log records
    #529.
- **2026-09-28, amended by the 4a-1b plan review, round 1** (reviewed at `22de7696`; rulings
  R49-R53).
  - **R49.** A resume needs its session's own HLS pipeline registered and running, else 410
    (§ The rest).
  - **R50.** `hls.ErrNoVideo` sets the channel's mark too, and the mark records its reason
    (§ Encoder argv › Failure).
  - **R51.** Each idle departure runs on a goroutine of its own that the sweeper starts
    (§ Who ends sessions; § The sweeper).
  - **Round 3 of the 4a-1b plan review** (reviewed at `84dc45d6`): § Session states' diagram
    says `client_connect` is emitted as the multivariant is written, not at `Attach`; § 4a-1b's
    `AttachExisting` break-check names the second next-source call as its oracle, the GET
    ending 410 under R49.
  - **D2, enforced (the 4a-1b plan's Decision 18).** `hls` resolves only from the request
    (`?output_format=`/`?output=` or the Xtream `.m3u8` override). A user's stored
    `custom_properties.output_format` of `hls` or `m3u8` is skipped, and a stored
    `default_output_format` of either reads as `mpegts`, so no byte-stream URL becomes a playlist
    by a default (`resolve_output_format`; nothing validates either value at `fabc663a`).
  - **R52 and R53** bind the 4a-1b implementation, not this text: the Go floor becomes
    `589 + H + O`, every census round at or under it, and the floor header's R21 sentence reads
    "does not exceed"; the orchestrator files the issue if R29's measurement is below real time.

- **2026-09-29, amended by the 4a-1d plan** (`docs/superpowers/plans/2026-09-29-phase4-4a1d-automatic-profile.md`;
  seed `4ed75d96`, #538's reviewed head). § Automatic generation and § 4a-1d only, plus one payload line.
  - **The copy rule** names what it had left implicit: H.264's profiles and 8-bit 4:2:0, the
    1920×1080 and 60 fps ceilings (a copy is never scaled), AAC copied only as LC stereo with
    `aac_adtstoasc`, and when a later generation may copy.
  - **`TARGETDURATION` = max(2, ⌈K − 0.1 s⌉)**, and the copy segmenter also closes before a keyframe
    that would take a segment to the target + 0.5 s; a segment reaching that ends the generation
    (RFC 8216 § 4.3.3.1's rounding, where "longer than the target + 0.5 s" let a 2.5 s segment
    stand under a target of 2).
  - **The automatic probe** lists the video packets for the keyframe count, K and the window's rate.
  - **`CODECS`** (§ 4a-1d's open item): the family ceiling, and a per-attempt codec reset.
  - **R42**: every target-duration threshold is the pipeline's; the startup allowance is
    `max(30 s, the stall timeout)`, so the entry's 43 s waits (R57) hold at a target of 6 and stay
    under nginx's 60 s.
  - **The HEVC encode** pins level 4.1, takes the bitrate table, and has its own Quick Sync detection.
  - **`hls_profile`** is required as `output_profiles` is, and refreshed by a non-degraded failover.
  - **`hls_encoder`** gains `"copy"`.
  - **The store's byte ceiling** scales with the target.

## Appendix A — the owner's rulings (2026-09-26/27), restated

These override any default in this spec.

- **R1.** Phase 4 is Apple-native live playback. 4a is the server (HLS, the live rewind window, the
  browser player on HLS). 4b is the first-party Apple app. 4c is paired-device auth, investigated
  after 4b's first playable build. Order: 4a-1 live-edge HLS → 4a-2 browser player HLS for live →
  4a-3 live rewind window → 4b → 4c.
- **R2.** Live TV only. VOD, catch-up and recordings are out of every 4x deliverable.
- **R3.** LAN only. No remote access is built into the app. Away from home means the user's own
  VPN, outside the app. Remote-access hardening is not a prerequisite.
- **R4.** The app is for household use but has a **public** App Store listing, under an individual
  developer account, with a demo mode for App Review. It targets iOS and tvOS, minimum 27, with
  macOS only via "Designed for iPad". It is SwiftUI, in a separate repository. This repository's
  spec is the server contract.
- **R5.** App scope v1: channel list, playback, live rewind, EPG now/next, and programme markers on
  the scrub bar, plus restart-programme when inside the window. The full guide grid comes later.
  Favourites and groups are fine. No multi-profile.
- **R6.** The app discovers the server by a typed URL in v1 (Bonjour later). Plain HTTP on the LAN
  (an ATS local-networking exception, the Local Network permission).
- **R7.** The HLS output re-encodes **by default** on Intel Quick Sync (the host is 12th-gen with
  UHD Graphics 770 and `/dev/dri`): H.264, deinterlaced at full frame rate, a fixed short keyframe
  interval, fMP4/CMAF segments. Audio is stereo AAC, plus source AC-3/E-AC-3 (JOC/Atmos included)
  passed through as a second rendition. Remux is opt-in per channel, through an Output Profile in
  *automatic* mode. The re-encode feeds HLS only, and TS clients are unchanged. One shared encode
  per channel (per profile). The spec decides the no-QSV host behaviour, and whether the encoder
  survives a failover source switch.
- **R8.** Plain HLS first, with ~2 s segments. LL-HLS later, not in 4a. Lower latency is preferred.
- **R9.** For Xtream clients, `/live/u/p/<id>.m3u8` (and `get.php` `output=m3u8`/`hls`) returns a
  real HLS playlist.
- **R10.** The live rewind window:
  - It starts at tune, never before.
  - There is one per channel, shared by all clients.
  - Its default depth is 60 min (a setting).
  - It is stored on disk under `/data`, with a configurable cap.
  - It lingers ~5 min after the last client leaves (a setting; 0 drops it at once).
  - A lingering window yields its provider slot to a new tune that needs it. Only lingering
    windows are evictable, never watched ones.
  - A window that was being watched behind live gets a 10 s grace (a setting) before it becomes
    evictable.
  - It is lost on relay restart, with no recovery.
  - It is format-agnostic in definition, but 4a ships only the HLS reader. The TS reader
    (`?behind=`) is a known extension, not built.
- **R11.** App-side: when behind live and the user changes channel, a 10 s "leaving rewind"
  countdown with cancel.
- **R12.** Plex carries no design weight. HDHR, M3U and XMLTV stay in the code, and deleting them is
  a separate post-4b question.
- **R13.** App sign-in uses Xtream credentials first. The playlist request is authorised by the
  existing authorize hop. Segments carry a short-lived HMAC token so Django is not asked per
  segment. Segment auth must not care how the playlist was authorised.
- **R14.** 4c: device pairing (a code on the Apple TV, approval in the web UI, a per-device
  revocable token, possibly LAN TLS, Mino-only endpoints, dropping cross-IPTV-app support). An
  investigation brief only in this spec.
- **R15.** The product's working name is "Mino". No renaming now. Every **new** externally visible
  identifier (route, header, Bonjour type, bundle id, setting key) is named for Mino or neutrally,
  never for Dispatcharr.
- **R16.** The app refuses a server lacking 4a (a capability check on server add).
- **R17.** The browser player switches to HLS for live (hls.js is already bundled; Chrome and Edge
  142+ have native HLS).
- **R18** (owner, round 1). In the browser, live **channels** play over HLS. Admin **stream
  previews** (by stream hash), and any preview-style playback, stay on mpegts.js over TS. mpegts.js
  and the web-player Output Profile preference are kept.
- **R19** (owner, round 1). The rewind window starts at the channel's **first HLS viewer**. A
  TS-only channel keeps no window and triggers no encode.
- **R20** (owner, round 1). E-AC-3-only sources get three audio renditions, per Apple rule 2.6:
  AAC, encoded AC-3, and E-AC-3 passthrough.
- **R21** (owner, round 1). A Go PR may raise the coverage floor's `missing`, but only by the
  uncovered statements of its own new or changed code:
  - they are listed per file in the PR;
  - the PR has ≥ 85% coverage on its additions, measured by the 12-round CI census;
  - the reviewer checks the listing.

  Noise draws above the floor still get a re-measurement PR of their own. The Python Gate 2 floor
  is unchanged.
- **R22** (orchestrator, round 1). "Short-lived" (R13) is satisfied by an **opaque** session token
  whose validity ends when its session ends: explicit leave, idle departure plus the resume window,
  admin stop, or relay restart. There is no fixed wall that cuts off a continuously watched
  session.
- **R23** (orchestrator, round 1). D13 (Redirect as Proxy over HLS), D2 (`hls` never a default)
  and D11 (software fallback, never refuse) are accepted as decided, with D11 subject to finding 5.
- **R24** (orchestrator, round 1). An explicit session leave, from the app (on zap, and after the
  R11 countdown) and from the browser player (on close or switch). D16 treats an HLS session silent
  for more than 2 × target duration as departed for slot reclaim. The E2E must not wait out the
  idle timeout.
- **R25** (orchestrator, round 2). An explicit leave (`DELETE /hls/<token>`) sets the behind-live
  grace to 0: for the app's own zap, R11's countdown is the grace. The 10 s server grace applies
  only to a behind-live session that departs without an explicit leave.
- **R26** (orchestrator, round 2). The stats card's play button (`StreamConnectionCard.jsx:516`) is
  preview-style. It stays on TS and mpegts.js (R18), and never starts an encode for a TS-only
  channel (R19).
- **R27** (orchestrator, round 3), on how R21 applies to an unlinked package. In 4a-1a, `relay/hls`
  is unlinked and outside the Go gate. 4a-1a's PR shows `relay/hls`'s own per-package coverage:
  ≥ 85%, CI-measured with `-count=1 -race -covermode=atomic`, with a per-file uncovered listing.
  4a-1b links it. It re-baselines `packages=`, and may raise `missing` by exactly `relay/hls`'s
  listed uncovered statements (re-measured as the census maximum, R34) plus 4a-1b's own new or changed uncovered statements.
  Each is listed per file, with ≥ 85% on 4a-1b's own additions and a 12-round CI census. Anything
  else above the floor is a finding. The same rule applies to any later PR that first links a
  package.

Apple rules cited above are from Apple's *HLS Authoring Specification for Apple Devices* (revised
2025-04-30), as summarised in the research that preceded this spec:

- 1.2: H.264 in TS or fMP4. 1.5: HEVC must be fMP4.
- 1.13: an IDR every 2 s should be used. 1.14-1.15: interlaced content must be deinterlaced, and
  30i becomes 60p.
- 2.3: stereo AAC must be provided. 2.5: AC-3, E-AC-3 and E-AC-3 JOC are supported. 2.6: if
  E-AC-3 is provided, AC-3 must be provided too.
- 7.4: every segment must start with an IDR. 7.7: a segment must be ≤ target + 0.5 s.
- 8.4: `EXT-X-PROGRAM-DATE-TIME` must be used in live playlists. 8.11: at least 6 segments; a
  15-minute window should be offered (tvOS: 120). 8.24: a playlist is stale if `Last-Modified`
  lags `Date` by more than 3 target durations.
- 9.11-9.12: `EXT-X-INDEPENDENT-SEGMENTS`.
- RFC 8216 § 6.3.3: a player starts at least 3 target durations from the end.

## Appendix B — how the prototypes were run

The prototypes were built in the orchestrator's scratchpad (`p4proto/`), never in the repository.

- **M1.** `docker buildx imagetools inspect` on the pinned index. Then `docker pull --platform
  linux/amd64 …@sha256:1a2648529e85…` and
  `docker run --platform linux/amd64 --entrypoint ffmpeg … -encoders | -hwaccels | -filters | -version`.
  Then `ls /usr/local/lib/x86_64-linux-gnu/dri` and `env` in the same image.
- **M2.** The QSV argv of § Encoder argv, run against a 3 MB TS file in that image under
  emulation, with no `/dev/dri`.
- **M3.** Three 20 s sources made with local ffmpeg 9.0.1: A (1080i H.264 + MP2 + AC-3, PIDs from
  0x100), A2 (A with `-output_ts_offset 3000`, the same PIDs) and B (720p25 MPEG-2 + MP2, PIDs from
  0x200, `-output_ts_offset 5000`). Each pair was piped with `cat` into one
  `ffmpeg -f mpegts -i pipe:0 … -c:v libx264 … -c:a aac`, and the output counted with
  `ffprobe -count_frames`.
- **M4-M7.** A Python harness. A feeder ffmpeg `-re` generated a live 1080i source as TS on stdout.
  The harness copied it to the encoder's stdin, with the encoder argv as in § Encoder argv
  (software), fds 3 and 4 wired through `sh -c 'exec "$@" 3>&N 4>&M'`. It parsed `moof`/`tfdt`
  per pipe, cut segments at video fragment boundaries, and grouped audio fragments by start time.
  It served the § Playlists shapes over `http.server`, with a 10-segment live window (90 for M7).
  - The Swift probes used `AVPlayer` with `AVPlayerItemVideoOutput` frame counting,
    `seekableTimeRanges` and `currentDate()`. M7's probe paused with `player.pause()`, and M5's
    read the audio track's `CMFormatDescription` media subtype.
  - They ran on macOS 27 directly and on the iOS 27 Simulator (iPhone 18 Pro) via
    `xcrun simctl spawn`, built with
    `xcrun -sdk iphonesimulator swiftc -target arm64-apple-ios27.0-simulator`.
  - Request timelines were read from the harness's per-request log.

- **M8** (round 3). The `anullsrc` failure was reproduced on the production image, amd64 manifest
  `1a264852` under `docker run --platform linux/amd64`, with round 3's 6 s 320×240 H.264 no-audio
  TS on stdin. Two runs were compared: `-map 0:v` to one fMP4 on stdout; and the same with
  `-f lavfi -i anullsrc=r=48000:cl=stereo` mapped to a second fMP4, under `timeout 20`.
  - **The silence mechanism** is a variant of the M4 harness (`pkg_silent.py`, `silentlib.py` in the
    scratchpad) on local ffmpeg 9.0.1. A live 1080i50 H.264 source with no audio was fed through a
    video-only generation. Canned frames came from a 3 s `anullsrc` encode per codec (AAC stereo
    160k; AC-3 5.1 640k; `delay_moov` for AC-3), parsed with the same box reader. Silent fragments
    were written per video segment: one `moof` (`tfhd` default duration and size, `tfdt` v1,
    `trun` with a data offset) plus an `mdat`.
  - **Playback** was probed on macOS 27 and the iOS 27 Simulator with the M4 probes, including the
    audio-format probe of M5.
  - **Exit on EOF** was timed at a source boundary, by closing stdin and waiting on the process.
