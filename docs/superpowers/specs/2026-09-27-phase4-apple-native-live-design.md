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
2. **4a-2, the browser player on HLS.** `FloatingVideo.jsx` plays live channels over HLS through
   hls.js, instead of MPEG-TS through mpegts.js (R17).
3. **4a-3, the live rewind window.** The last hour of a watched channel is kept on disk, shared per
   channel, lingers after its last viewer, gives its provider slot up to a new tune that needs it,
   and is lost when the relay restarts (R10).

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
| M1 | Does the production ffmpeg support Quick Sync? `docker/DispatcharrBase:7` and `:115` pin `lscr.io/linuxserver/ffmpeg:version-9.0-cli@sha256:47fbdc93…`, an index. Its **amd64** manifest (`sha256:1a264852…`) was pulled and inspected. | **Yes, on amd64.** The encoders include `h264_qsv`, `hevc_qsv`, `mpeg2_qsv`, `h264_vaapi` and `hevc_vaapi`, and the filters include `vpp_qsv`, `deinterlace_qsv`, `bwdif` and `yadif`. `-hwaccels` lists `qsv` and `vaapi`. The configure line includes `--enable-libvpl`, `--enable-vaapi`, `--enable-libx264` and `--enable-libfdk_aac`. The image ships `iHD_drv_video.so`, `libmfx-gen.so.1.2.17` (the oneVPL runtime 12th-generation parts use) and `libmfxhw64.so`, and sets `LIBVA_DRIVERS_PATH=/usr/local/lib/x86_64-linux-gnu/dri`. The **arm64** manifest has no QSV or VAAPI encoder at all. **No base-image change is needed.** |
| M2 | What does a QSV device initialisation do with no `/dev/dri`? The amd64 image was run under emulation. | It fails **during global option parsing**, before any input is opened: `Device creation failed … Error parsing global options`, with a non-zero exit, in well under a second. In the same image, the same command with `libx264` succeeds. |
| M3 | Does **one** encoder, fed on stdin, survive a failover source switch? A 1080i H.264 + MP2 + AC-3 source (PIDs from 0x100) was fed, followed by a 720p MPEG-2 + MP2 source (PIDs from 0x200, a timestamp jump of 5000 s). | **No.** It exits 0, but the output is 20.04 s (1000 frames) of the 40 s fed. Source B is **silently dropped**, and the only trace is a `New audio stream with index 4` warning. With the **same** PIDs and a resolution change, output continues for 39.98 s (1996 frames) with non-monotonic-DTS warnings. With the same PIDs and the same parameters (a plain timestamp jump) it continues for 40.02 s. |
| M4 | Can one encoder write fMP4 renditions on separate pipes, with the relay's own segmenter owning the playlists? The prototype wrote video on fd 1, stereo AAC on fd 3 and AC-3 passthrough on fd 4, all `-movflags frag_keyframe+delay_moov+default_base_moof`, with a 2 s forced IDR interval. It served one `EXT-X-STREAM-INF` per audio group. | **Yes.** Every segment was exactly 2.000 s. `empty_moov` refuses AC-3 passthrough (`Cannot write moov atom before AC3 packets`), so `delay_moov` is needed, as the existing remux already uses (`relay/output/fmp4.go:80`). **macOS 27:** ready 0.37 s, first frame 0.32 s, 981 frames in ~19.6 s, **7.26 s behind the segments' `EXT-X-PROGRAM-DATE-TIME`**. **iOS 27 Simulator, warm:** ready 0.21-0.32 s, 983-986 frames, **7.22-7.40 s behind PDT**. The first cold spawn after boot took 13.56 s, which is simulator start-up, and is discounted. Both platforms chose the AAC group. macOS fetched the AC-3 media playlist once and iOS never did. |
| M5 | Does the demuxed AC-3 fMP4 rendition decode? A multivariant offering only the AC-3 group was used. | **Yes** on macOS and on the iOS Simulator. The audio track's format was `ac-3`. |
| M6 | Discontinuity. The encoder was restarted at a source boundary (stdin closed, a new process started on source B), and the next segment was marked `EXT-X-DISCONTINUITY` with a new `EXT-X-MAP`. | AVPlayer on macOS **played across it without error**: 1742 frames in the 40 s probe, where a steady ~49 fps gives ~1960. The old generation's flushed tail became two final segments. The new generation's first segment appeared **8.9 s after the boundary** on the prototype host. That host is a laptop running `libx264` 1080p50 plus the feeders and the player, and it then ran slower than real time (a segment every 2.2-2.9 s). The gap on real hardware is open question Q6. |
| M7 | Does a **paused** AVPlayer keep requesting? It played 12 s, paused 60 s and resumed 10 s, against a 90-segment live playlist. | On macOS **and** iOS: during the pause AVPlayer reloaded the media playlist **every 2.0 s** (30 reloads in 60 s), fetched 46 segments ahead, and resumed **58.2-58.3 s behind the live end**. Pausing live HLS is timeshift, from the player's own buffer and the playlist. |

**What was not measured**, and where each item lands: Quick Sync encoding itself (no Intel GPU was
available; Q1), tvOS (Q2-Q4), Atmos (Q3), a 60-minute playlist on Apple TV (Q4), zap time on the
household host (Q5) and the failover gap on real hardware (Q6). § Open questions says, for each,
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

## Decisions

| # | Decision | Why |
|---|---|---|
| **D1** | **Six PRs in three stages, each stage a stopping point.** 4a-1a (the packager, inert), 4a-1b (sessions, routes, surfaces: live HLS works end to end), 4a-1c (the *automatic* HLS profile), 4a-2 (browser player), 4a-3a (the rewind window and linger), 4a-3b (a lingering window yields its slot). Branches are `migration/phase4-*`, so the full E2E and lifecycle matrix runs on every one (CLAUDE.md § Full E2E runs). | 4a-1 as one PR would be several thousand lines of Go across two concerns. The packager can land inert and be reviewed on its own evidence, as 2c-6's fMP4 remux was. 4a-1c is separable because the default (transcode) needs no schema. 4a-3b is separable because it is the only part of the window that touches Django's slot model. |
| **D2** | **HLS is an output format, not a new authorised route.** `hls` joins the resolved formats. `_FORMAT_ALIASES` gains `"hls": "hls"` and `"m3u8": "hls"`. `xcForcedFormat` maps `.m3u8` to `hls`. Any live tune URL whose resolved format is `hls` (`/proxy/ts/stream/<id>?output_format=hls`, `/live/<u>/<p>/<id>.m3u8`, `/<u>/<p>/<id>.m3u8`) is answered **200 with the multivariant playlist**. `hls` is **not** offered as `default_output_format` or as a user's `output_format` in 4a. | The authorize hop, its nginx locations, the XC credential check, the stream limit and every channel check apply unchanged, with no new Django urlconf entry for `_surface_for` to learn. A deployment-wide default of `hls` would turn every byte-stream URL (HDHomeRun, Plex, TS apps) into a playlist, so the value is only ever asked for explicitly. |
| **D3** | **Everything after the entry lives under a token-authorised root, `/hls/`, and runs no authorize hop.** URL layout: `/hls/<token>/<rendition>.m3u8` (media playlist), `/hls/<token>/<rendition>/init-<gen>.mp4`, and `/hls/<token>/<rendition>/<seq>.m4s`. nginx gets `location ^~ /hls/` with `include dispatcharr_api_params_proxy.conf`, `proxy_buffering off`, `proxy_http_version 1.1`, `proxy_connect_timeout 60s` and `proxy_pass http://relay_go`. There is no `auth_request` and no `internal;`. The multivariant references media playlists by **absolute path**, and media playlists reference init and media segments **relatively**. | R13: Django is not asked per segment. Absolute-path URIs need no `Host` or scheme reconstruction, so the six server-level `proxy_set_header` lines need not be re-declared, for the same reason `^~ /proxy/relay/` omits them. Buffering is off because a segment runs to megabytes, and buffering it would spool to disk, which is CLAUDE.md's incident in a new place. One cost, recorded: a bare three-segment XC request from a user literally named `hls` now reaches this location. That is the same class of collision the `live`, `movie`, `series` and `timeshift` prefixes already impose, and the `/live/…` form still works for that user. |
| **D4** | **A media-session token, minted and verified only by the relay** (§ The media-session token). It is bound to the channel, the client id the hop minted (the session id), the user, the HLS profile and an absolute expiry of 24 h. The key is the deployment's `SECRET_KEY` under a new HMAC context, `media-session`. A token is honoured while its MAC and expiry verify, it is not revoked, and its session is live or departed less than **300 s** ago. It is **not** bound to an IP address. Rotating `SECRET_KEY` invalidates every session. | This is stateless where it can be: MAC and expiry. It is stateful only where state already exists: the presence registry. A second key would be a second secret to provision and leak. The relay already holds `SECRET_KEY` for three contexts, and Django shares it, so a future Django-minted session (4c) can issue the same token. No IP binding, because AirPlay hands a URL to an Apple TV that fetches from a different address, and phones roam between access points. The 300 s resume grace lets a briefly backgrounded app carry on without re-authorising. The 24 h cap bounds a URL copied out of a log. |
| **D5** | **An HLS viewer is a client in the channel's registry for exactly as long as its session is live.** It **arrives** when the multivariant is served (the `Attach` call, a `client_connect` event). It is **active** on every request carrying its token. It **leaves** after **12 s** with no request, which emits `client_disconnect` with `duration` and `bytes_sent` and calls the release func. A later request inside the resume grace **re-attaches** it, with a new `client_connect`. `output_format` is `hls`, so `/proxy/relay/channels`, `/proxy/ts/status/` and the stats page show it without change. Admin stop, and stream-limit termination, remove the session **and revoke its token**. | M7 measured AVPlayer reloading every target duration (2 s) even while paused, so 12 s (six reloads) cannot mistake a paused viewer for a departed one. RFC 8216 § 6.3.4 requires every client to reload at about the target duration. The per-user stream limit needs no change, because it counts the relay's client list, which now includes HLS sessions. A channel with only HLS viewers stays up, because its clients are registered sessions and not connections. |
| **D6** | **The relay owns packaging.** One ffmpeg per (channel, HLS profile) reads the channel's ring on stdin, joining `JoinBehind` behind live as every output does. It writes **one fragmented-MP4 stream per rendition on its own file descriptor**: video on fd 1, stereo AAC on fd 3, AC-3 on fd 4, E-AC-3 on fd 5, each `-movflags frag_keyframe+delay_moov+default_base_moof`. A new package, `relay/hls`, parses the boxes (stdlib `encoding/binary`), cuts segments on video fragment boundaries, stores them, and renders every playlist. **Rejected:** ffmpeg's own `-f hls` muxer, and one muxed audio-plus-video stream. | M4 shows the shape works, with 2.000 s segments on every rendition. `-f hls` writes files the relay would have to watch (no inotify in the stdlib) and playlists it would have to rewrite: for tokens, for the discontinuity rule D10 needs across processes, and for the window 4a-3 keeps on disk. A muxed stream cannot carry two alternative audio codecs as HLS renditions. `buffer.Fragments` is not reused. It is a cursor stream for one long response, and HLS needs random access by media sequence number across aligned renditions, which is a different type (`hls.Store`). The spawn helper gains `ExtraFiles` (stdlib `os/exec`), keeping `Setpgid` and `Pdeathsig`. |
| **D7** | **Playlists** (§ Playlists, exact tags). There is one video rendition and one audio group per audio codec: `aac` always, `ac3` when the source carries AC-3 or E-AC-3, `eac3` when it carries E-AC-3. Each group gets its own `EXT-X-STREAM-INF` on the same video playlist. `CODECS` is read from each rendition's **init segment** (`avcC`, `hvcC`, `esds`, `dac3` and `dec3` boxes). `EXT-X-PROGRAM-DATE-TIME` is derived from the ring's **arrival time** of the generation's first chunk, plus media time. `TARGETDURATION` is 2 (transcode), with `INDEPENDENT-SEGMENTS`, `VERSION:7`, a media sequence that continues across generations, and `DISCONTINUITY-SEQUENCE`. The live-edge playlist lists 10 segments. A media playlist request **waits** for its rendition's first segment, bounded by 20 s, then answers 503 with `Retry-After: 1`. The multivariant waits for every first-generation init segment, bounded the same way. | Apple rules 2.3, 2.5-2.6, 7.4, 8.4, 8.11 and 9.11-9.12 (research list, Appendix A). Reading codec strings from the init segments keeps them true in every mode, copy included, without guessing from ffprobe's profile names. Arrival time rather than publish time keeps PDT honest while the encoder catches up the `JoinBehind` backlog at start. Holding a request until content exists is simpler for every player than an empty live playlist. |
| **D8** | **The default re-encode** (§ Encoder argv). The source is decoded in software. It is deinterlaced with `bwdif=mode=send_field:deint=interlaced` when the probe says the source is interlaced, so 50i becomes 50p (Apple 1.14-1.15). The **output geometry and frame rate are fixed for the channel's run** at the first generation's probe: at most 1920×1080, never upscaled at the first generation, with `scale`/`pad`/`fps` enforcing them on every later generation. The video is H.264 High@L4.2 at constant frame rate, with a forced IDR every 2.000 s and a bitrate from a table by output height. It is encoded with `h264_qsv` behind `hwupload`, or with `libx264 -preset veryfast -tune zerolatency` (D11). Audio: stereo AAC 160 kb/s always. AC-3 is copied, or encoded at 640 kb/s 5.1 when the source has only E-AC-3. E-AC-3 is copied. | ADR 0009 fixes codec, field order and keyframe spacing as Mino's decisions. Software decode plus `bwdif`'s `deint=interlaced` handles mixed progressive and interlaced content without a hardware filter chain whose behaviour on progressive frames is unknown (Q1). Encoding is the expensive half, and it is the half that goes to Quick Sync. Fixed output parameters are what ADR 0009 promised across a switch, and what keeps the multivariant's `CODECS`, `RESOLUTION` and `FRAME-RATE` true after one. |
| **D9** | **A probe precedes every generation.** `ffprobe -show_streams -of json` reads the ring from `JoinBehind` behind live, bounded to 5 MB or 8 s, and is decoded with stdlib `encoding/json`. It decides interlacing (`field_order`), frame rate, geometry and the audio layout, and, in *automatic* mode, the copy decisions (D12). A probe that finds no video stream fails the HLS attach with 502, while the channel's TS clients are unaffected. | Every later choice depends on these facts, and the relay is the only process that can see the bytes. |
| **D10** | **The encoder restarts at every source boundary. It does not survive a switch.** A boundary is every new upstream connection: an `applySwitch`, or a reconnect of the same URL. The channel records the ring index of the boundary's first chunk. The running generation's writer stops **at** that index and closes stdin. Its flushed tail becomes the generation's last (possibly short) segments. A new generation is probed and started at the boundary. Its first segment is marked `EXT-X-DISCONTINUITY` with a new `EXT-X-MAP` (`init-<gen>.mp4`). The media sequence continues. | M3: a surviving encoder silently drops a source with different PIDs, so every failover to another provider would be a picture that stops with no error anywhere. M6: AVPlayer plays across a discontinuity. Restarting also makes a change of codec, resolution or audio layout between providers safe, and the fixed output parameters (D8) keep the declared variant true. The cost is the gap measured in M6, which is open question Q6 on real hardware. |
| **D11** | **With no usable Quick Sync, the relay encodes in software and says so. It does not refuse.** At the first HLS attach in the process, the relay runs a one-frame QSV test encode (§ Encoder argv, detection) and caches the answer for the life of the process. If a QSV generation exits within its first 10 s having produced no segment, it is retried once in software, and the process marks QSV unusable. The channel payload gains `hls_encoder` (`"qsv"` or `"software"`), and the fallback is logged once at WARNING. | Refusing would reproduce the exact failure ADR 0009 exists to prevent: an Apple TV showing nothing, with no explanation, because `/dev/dri` was left out of a compose file. Fallback also makes the whole path testable in CI and on developer Macs, neither of which has an Intel GPU (M1: the arm64 image has no QSV at all). M2 shows detection is cheap and unambiguous. |
| **D12** | ***Automatic* is an Output Profile mode, selected per channel.** `OutputProfile` gains `hls_mode` (blank; `transcode`; `automatic`). Two **locked** rows are seeded, "HLS (Re-encode)" and "HLS (Automatic)", and rows with a non-blank `hls_mode` are neither user-creatable nor editable. `Channel` gains `hls_output_profile`, a nullable FK (null means the built-in transcode). Next-source carries the channel's choice as `hls_profile: {id, mode} \| null`. HLS-mode rows are excluded from `output_profiles` and ignored by `resolve_output_profile`. On an `hls` tune, `X-Relay-Output` is ignored. | ADR 0009 says "reuses the existing Output Profile mechanism… and adds no new one". The per-channel FK is new because R7 says "opt-in per channel", and Output Profiles are selected per client today. A per-client HLS profile would break "one shared encode per channel". The policy is product-owned (ffmpeg argv the relay builds from a probe) rather than an operator-typed command line, which is why those rows are locked. |
| **D13** | **A Redirect-profile channel is served over HLS through the relay, as Proxy.** It reserves and holds a provider slot like any Proxy tune. TS clients on the same channel keep their 302 unless the channel is already running, in which case they attach to it, as any client does. | HLS is by definition made by the relay from bytes it holds. A 302 to the provider's endless TS is exactly what AVPlayer cannot play (ADR 0008). `startTune` already takes this path for an internal principal (`relay/httpapi/stream.go:701-713`). |
| **D14** | **The rewind window is the HLS output's own segments, kept on disk** (4a-3a, § The live rewind window). The path is `/data/cache/rewind/<boot-id>/<channel>/<gen>/<rendition>/<seq>.m4s`, created by `docker/init/03-init-dispatcharr.sh`. The depth defaults to 60 min. There is a global byte cap. The last 12 segments stay in memory. A disk error degrades the window and never the live output. The window is deleted on drain, and every boot directory is deleted at start-up. Playlists become a **sliding window with no `EXT-X-PLAYLIST-TYPE`**, listing every segment in the window. | ADR 0008: about 3.6 GB per channel-hour is too big for memory, and a restart discards it rather than recovering it. `EVENT` forbids removing segments from the head, so it cannot express a 60-minute window once the window is full. 60 min is well past Apple's 15-minute SHOULD (research, rule 8.11). |
| **D15** | **The window lingers, and a lingering window holds its channel open** (4a-3a). When a channel's last HLS session leaves, its HLS pipeline keeps running for `rewind_linger_seconds` (default 300; 0 means stop at once). It keeps growing the window, and holds the channel, its upstream and its provider slot. Lingering is not a client and appears in no client list or stream-limit count. A lingering channel is **evictable** when it has zero clients of any format and its grace has passed. The grace is 0 if the last viewer left at live, and `rewind_behind_live_grace_seconds` (default 10) if it left **behind live**, meaning its last segment request was more than 5 target durations older than the newest segment. | R10 verbatim: zapping back keeps the rewind, and the window stays continuous to live, so the encoder must keep running. A channel with a TS viewer still attached is watched, and is never evicted. |
| **D16** | **A lingering window yields its slot only when Django says a tune is blocked** (4a-3b, § Slot yield). When `get_stream()` finds every profile full, next-source answers `capacity: {blocked: true, profile_ids: […]}`. The ids are every M3U profile whose release would let this tune reserve: each `profile_full` profile, and each profile sharing a `credential_full` profile's credential counter. The relay picks, among its **evictable** channels whose current `m3u_profile_id` is in that list, the one that became evictable first. It evicts it atomically under the Manager lock, waits for its release POST, and retries next-source **once**. | ADR 0005: slots stay in Django, and the relay does not decide them. Django knows why a tune is blocked, and the relay knows which of its channels are idle. Answering with the blocking profiles keeps both facts where they are, and it needs no Django-to-relay call inside a next-source request. The #513 reconciler needs no change: a lingering channel is listed with its own `state` (never a new value), so it is counted as the holder it is, and an eviction's release is an ordinary release that bumps the version. |
| **D17** | **Four settings, in the `proxy_settings` group** (4a-3a): `rewind_window_minutes` (60; 0 disables the window; at most 120), `rewind_linger_seconds` (300), `rewind_behind_live_grace_seconds` (10), `rewind_disk_cap_gb` (16). They are back-filled by `get_proxy_settings`' defaults, sent on every next-source answer (A1.4), and required by the relay. | `proxy_settings` is the group the relay already receives, so no new wire field is needed. The names are neutral (R15). A channel snapshots them at start, as it does every other threshold. The disk cap is process-wide and takes the value from the most recent answer. The 120-minute ceiling is Apple's tvOS scrub-back figure (research). |
| **D18** | **The browser player plays live over hls.js** (4a-2). It uses hls.js wherever MSE or ManagedMediaSource exists, with `xhrSetup` sending the `Bearer` JWT, and falls back to native HLS with the JWT as `?token=` where only native exists. The mpegts.js live path, its dependency and the web-player Output Profile preference are removed. | R17. hls.js is already bundled and plays fMP4 with alternative audio groups. Relying on Chrome's native HLS would add one more player to reason about for no gain. The preference only ever applied to the live mpegts URL. The AAC rendition is always present, so it has no function under HLS. |
| **D19** | **A Mino capability document:** `GET /api/mino/capabilities/` (4a-1b), `AllowAny`, gated by the `XC_API` network ACL (§ 4b). | R16: the app refuses a server without 4a, and it must be able to ask before sign-in. The route is Mino-named (R15). |
| **D20** | **Gates** (§ Testing and gates). Every 4a PR that adds Go statements carries its own ≥12-round CI coverage census, and moves `scripts/coverage_relay_go.floor`'s `missing` with the census recorded. Its marginal coverage is ≥ 80%. New lines in Gate 2's nine Python modules are covered, so that floor's `missing` does not move. New parity-matrix rows land **pinned** in the PR that makes the behaviour. E2E runs the software encoder on CI. The AVPlayer check is a manual gate recorded in the PR body. | The Go floor file's own "HOW TO MOVE" section prescribes a census for a `missing` move. New code with any uncovered statement moves `missing`, so the census is the cost of each PR, stated up front rather than discovered in CI. There is no macOS or iOS 27 runner in this repository's CI (no workflow uses one), and the app repository is where an automated AVPlayer suite belongs. |

## Architecture

### Request flow, 4a-1

```
 Apple device / Xtream app / browser                                          relay-go (5658)
 ───────────────────────────────────                                          ───────────────
 GET /live/<u>/<p>/<id>.m3u8 ───► nginx ^~ /live/ ──auth_request──► Django authorize_stream()
                                     │  (hop: ACL, principal, channel checks, stream limit,
                                     │   X-Relay-Output-Format=mpegts|…, client id minted)
                                     └─proxy_pass──► XCHandler: .m3u8 ⇒ format hls
                                                       │ Manager.Attach(channel, client=session)
                                                       │   (first client ⇒ next-source, slot, ring)
                                                       │ Channel.AttachOutput("hls[:p<id>]")
                                                       │   ⇒ probe ⇒ ffmpeg gen 0 ⇒ relay/hls segmenter
                                                       │ wait for first-gen init segments
                                                       ◄─ 200 multivariant, URIs /hls/<token>/…
 GET /hls/<token>/video.m3u8 ───► nginx ^~ /hls/ (no hop) ─► token verify (MAC, exp, revoked,
 GET /hls/<token>/video/<n>.m4s                               live-or-resumable) ⇒ touch session
 GET /hls/<token>/aac.m3u8 …                                  ⇒ serve from hls.Store
                                     session idle 12 s ⇒ leave: client_disconnect, release()
```

### State the relay adds, all in process memory (ADR 0006 unchanged)

- **`hls.Pipeline`**: one per (channel, HLS profile), refcounted by sessions through
  `AttachOutput`. It owns the current generation (an ffmpeg child, its probe, its fixed output
  parameters) and the `hls.Store`.
- **`hls.Store`**: segments per rendition, keyed by media sequence, with each generation's init
  segments and discontinuity markers. It is bounded by count (4a-1: 12 per rendition, about 26 MB
  per HLS channel at the D8 table's top rate, computed rather than measured) and by bytes.
- **The session table**: `client id → {channel, token claims, last activity, departed-at, bytes}`,
  plus a revoked set whose entries expire with their token's `exp`. It is lost on restart, and so
  every outstanding token becomes invalid (D4): players re-authorise, which is also what the lost
  window (4a-3) requires.
- **4a-3a** adds the on-disk window beside the store, and per-channel linger state.

Nothing is added to Redis or Postgres by the relay. `scripts/check_go_stdlib_only.sh` holds: every
mechanism above is `os/exec`, `os`, `encoding/binary`, `encoding/json`, `encoding/base64`,
`crypto/hmac` or `crypto/sha256`.

## The contract

### Entry (4a-1b)

| Request | Resolved by | Answer |
|---|---|---|
| `GET /proxy/ts/stream/<id>?output_format=hls` (or `?output=hls`, `m3u8`) | the hop's `resolve_output_format` with the new aliases | 200 `application/vnd.apple.mpegurl`, the multivariant |
| `GET /live/<u>/<p>/<id>.m3u8`, `GET /<u>/<p>/<id>.m3u8` | `xcForcedFormat` (`.m3u8` ⇒ `hls`) | same |
| any of the above on a channel whose probe finds no video | relay | 502 `{"error": "no video stream in the source"}`; TS clients unaffected |
| first-generation init segments not ready within 20 s | relay | 503, `Retry-After: 1`; the session is dropped |
| draining relay | relay (`Lifecycle`) | 503, as for every tune |
| every hop denial (401, 403, 404, 429) | unchanged | unchanged |

`Cache-Control: no-store` on the multivariant, because it carries a fresh token every time.

### Session resources (4a-1b)

| Request | Answer |
|---|---|
| `GET /hls/<token>/<rendition>.m3u8` | 200 media playlist, `Cache-Control: no-cache`, `Last-Modified` = the newest segment's publish time (Apple 8.24). Waits for the first segment (≤ 20 s, then 503 + `Retry-After: 1`). |
| `GET /hls/<token>/<rendition>/init-<gen>.mp4` | 200 `video/mp4` or `audio/mp4`, `Cache-Control: private, max-age=86400` |
| `GET /hls/<token>/<rendition>/<seq>.m4s` | 200 the same types, `Cache-Control: private, max-age=86400`; **404** if the sequence is outside the store (or the window, 4a-3) |
| a token whose MAC, version or format is wrong, or whose `exp` has passed, or that is revoked, or whose session departed more than 300 s ago | **403** `{"error": "invalid or expired media session"}`, with no detail on which condition failed |
| a valid token whose channel is no longer running | **410** `{"error": "channel stopped"}` |
| unknown rendition name | 404 |

Rendition names are `video`, `aac`, `ac3` and `eac3`. The relay ignores every `X-Relay-*` and
`X-Dispatcharr-Authorized` header on `/hls/`: authorisation there is the token and nothing else,
so how the playlist was authorised cannot matter (R13).

### The media-session token (4a-1b)

```
payload = "v1" LF channel LF client_id LF user_id LF hls_profile_id LF iat LF exp      (ASCII)
mac     = HMAC-SHA256(key = SECRET_KEY, msg = "media-session" LF payload)
token   = base64url_nopad(payload) "." base64url_nopad(mac)                          (path-safe)
```

- `channel` is the `X-Relay-Channel` value (a channel UUID, or a stream hash for a stream preview).
  `client_id` is `X-Relay-Client`, the hop's `mint_client_id()` (`apps/proxy/authorize.py:145`).
  `user_id` is `X-Relay-User` (empty when anonymous). `hls_profile_id` is empty for the built-in
  transcode. `iat` and `exp` are Unix seconds, with `exp = iat + 86400`.
- Verified with `hmac.Equal` after an ASCII check, mirroring `relay/control/token.go`'s `matches`.
  The path's rendition must be one the channel's pipeline has. The token's `channel` is the only
  channel it can read.
- **Never logged.** It is a bearer credential. The `/hls/` handlers log the client id instead, and
  a unit test asserts a rejected token's text does not appear in the log. `credlint` cannot see a
  string, so this is held by the test. nginx's access log records request paths, and therefore the
  token, as it already records XC credentials. That is recorded under § Risks.

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

- `LANGUAGE` is emitted only when the probe reports a language tag.
- `BANDWIDTH` is the video `maxrate` plus the audio bitrate in transcode mode. In a copied
  rendition it is 1.25× the ring's measured rate over the probe window.
- The AAC group is listed first. Which group a given device picks is open question Q2 (M4: macOS
  and iOS chose AAC).

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

- `EXT-X-PROGRAM-DATE-TIME` is written on the first listed segment, after every discontinuity, and
  every 30th segment.
- Audio playlists list the same sequence numbers with their own `EXTINF`. An audio segment holds
  the audio fragments whose start time falls within its video segment's span. With 200 ms audio
  fragments (`-frag_duration 200000`) an audio segment is within 0.2 s of its video segment, which
  is inside Apple 7.7's +0.5 s.
- `EXT-X-ENDLIST` is never written.

### Next-source additions

- **4a-1c** adds `hls_profile: {id: int, mode: "transcode"|"automatic"} | null`.
- **4a-3a** adds the four `rewind_*` keys to `proxy_settings`.
- **4a-3b** adds `capacity: {blocked: bool, profile_ids: [int]} | null`. It is non-null only when
  `source` is null *because* every profile was full.

Each is a serializer field in `apps/proxy/serializers.py`, and is therefore in the drf-spectacular
schema, and each has a Go decoder in `relay/control/nextsource.go`. The relay requires `hls_profile`
and the `rewind_*` keys, which is A1.4's rule. It treats an absent `capacity` as "not blocked",
because that field describes a failure rather than a setting.

### Relay channel payload additions

These are all optional fields, preserved by `apps/proxy/relay_serializers.py`:

- `hls_encoder` (`"qsv"`/`"software"`, present while an HLS pipeline runs; 4a-1a/b).
- `hls_generation` (int; 4a-1b).
- `lingering_since` (float Unix time, present while lingering; 4a-3a).
- `rewind_window_seconds` (float; 4a-3a).
- `rewind_degraded` (bool, present when true; 4a-3a).

`state` gains **no** new value. The reconciler (`_ENDED_RELAY_STATES`) and the frontend's state
handling are therefore untouched.

## Encoder argv

Built in Go by `relay/hls` from the probe and the mode. It is not sent by Django, because it depends
on facts only the relay can observe: the source's codecs, field order and geometry. This is a
deliberate exception to 2c-7's "Django builds the argv". That rule exists because an
operator-authored parameter string must go through `shlex` in one place. This argv has no operator
input, since `hls_mode` rows are locked (D12).

**Transcode generation, QSV** (the software variant replaces the three QSV-specific parts, noted
inline):

```
ffmpeg -hide_banner -loglevel warning -nostats
  -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw          # software: omitted
  -fflags +genpts+discardcorrupt -f mpegts -i pipe:0
  -map 0:v:0
  -vf "[bwdif=mode=send_field:deint=interlaced,]scale=W:H:force_original_aspect_ratio=decrease,
       pad=W:H:(ow-iw)/2:(oh-ih)/2,fps=R,format=nv12,hwupload=extra_hw_frames=64"
                                                   # software: format=yuv420p, no hwupload
  -c:v h264_qsv -preset veryfast -profile:v high -level 42                 # software: libx264
       -b:v B -maxrate M -bufsize M -g G -idr_interval 0 -forced_idr 1     #   -preset veryfast -tune zerolatency
       -force_key_frames "expr:gte(t,n_forced*2)"                          #   -profile:v high -level:v 4.2
                                                                           #   -g G -keyint_min G -sc_threshold 0
  -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof pipe:1
  -map 0:a:<first> -c:a aac -ac 2 -b:a 160k
  -f mp4 -movflags frag_keyframe+delay_moov+default_base_moof -frag_duration 200000 pipe:3
  [-map 0:a:<ac3 or eac3> -c:a copy | -c:a ac3 -b:a 640k   … -frag_duration 200000 pipe:4]
  [-map 0:a:<eac3> -c:a copy                                … -frag_duration 200000 pipe:5]
```

- `W`, `H` and `R` are fixed at the first generation. `R` is the field rate for an interlaced
  source (1080i at 25 frames, 50 fields per second, becomes 50p) or the frame rate for a progressive one, capped at 60. `G` = 2 × R.
- Bitrate `B`/`M`: height ≥ 1080 → 6 / 8 Mb/s; ≥ 720 → 4 / 5 Mb/s; otherwise 2.5 / 3 Mb/s.
- The software variant is the shape M4 ran (Appendix B), with `-nostats` added and the audio maps
  generalised.
- **The QSV argv has not been run on Quick Sync** (no hardware was available). M2 shows only that
  the device option parses and fails cleanly without a device. Its first execution on the
  household host is Q1, and 4a-1a's PR body records it.
- The audio map chooses the first audio stream for AAC. Whenever the probe finds more than one
  audio stream it logs the choice; language-based selection is a non-goal of 4a.

**Detection (D11).** The test encode is:

```
ffmpeg -init_hw_device qsv=hw:/dev/dri/renderD128 -filter_hw_device hw -f lavfi \
  -i color=c=black:s=256x144:r=25 -frames:v 1 -vf format=nv12,hwupload -c:v h264_qsv -f null -
```

It has a 10 s timeout. Exit 0 means QSV. A missing `/dev/dri/renderD128`, any non-zero exit or the
timeout means software.

**Automatic generation (4a-1c).** The rules are applied per rendition from the probe:

| Source | Automatic does |
|---|---|
| video H.264 or HEVC, progressive, with ≥ 2 keyframes in the probe window, max keyframe interval K ≤ 6 s | copy (`-c:v copy`; HEVC tagged `hvc1`). `TARGETDURATION` = max(2, ⌈K⌉). Segments are cut at the first keyframe at or after 2 s. |
| video interlaced, MPEG-2, anything else, or K > 6 s, or < 2 keyframes seen | the transcode chain above |
| audio AAC | copy into the `aac` rendition |
| audio MP2, MP3 or anything else | AAC 160 kb/s stereo |
| audio AC-3 / E-AC-3 | as in transcode (copy) |

**Two run-level rules for automatic.**

- The multivariant's `CODECS` family is fixed by the first generation. A later generation (after a
  source boundary) whose copy decision would change that family, or whose keyframe interval exceeds
  the declared `TARGETDURATION` + 0.5 s, is transcoded into the declared family for the rest of the
  channel's run.
- The segmenter enforces the `TARGETDURATION` rule. When a copied segment exceeds
  `TARGETDURATION` + 0.5 s, the generation is ended at the next boundary and the run switches to
  transcode.

Both rules are reasoning, not measured behaviour. 4a-1c's tests pin them with fixtures (§ Testing).

## Presence and lifecycle (4a-1b, extended by 4a-3a)

```
 multivariant served ──► ARRIVED (client registered; client_connect)
      │  any valid token request: touch(last_activity)
      ▼
   ACTIVE ──idle ≥ 12 s──► DEPARTED (client_disconnect; release(); departed_at)
      ▲                        │ valid request within 300 s ⇒ re-attach (client_connect)
      └────────────────────────┘ 300 s elapse ⇒ FORGOTTEN (token now 403)
 admin stop / limit termination ⇒ REVOKED (release(); client_disconnect; token 403 until exp)
```

- The idle sweep runs every 2 s per HLS pipeline.
- `bytes_sent` sums every body byte served to the session.
- A session re-attaching after departure is **not** re-checked against the stream limit. That is
  bounded by the 300 s grace, and it is recorded rather than engineered away. The app always
  re-tunes through a fresh multivariant when the user changes channel.
- The HLS pipeline's refcount is the number of ARRIVED/ACTIVE sessions. In 4a-1 the last
  departure stops the pipeline at once. In 4a-3a it starts the linger (D15).

## The live rewind window (4a-3)

### Storage and bounds (4a-3a)

- **Layout.** `/data/cache/rewind/<boot-id>/<channel>/<gen>/<rendition>/<seq>.m4s`, plus
  `init.mp4` per `<gen>/<rendition>`. `<boot-id>` is 16 random hex characters per relay start.
  At start-up the relay removes every directory under `/data/cache/rewind/`. On drain it removes
  its own boot directory after `StopAll`, best effort. Both are deliberate: the window is lost on
  restart and on drain (R10), and there is one relay per deployment (ADR 0006, D2 of Phase 2).
- **Writes.** Each segment is written once when it is published, to a temporary name, then
  renamed. The newest 12 per rendition are also kept in memory, and live-edge reads never touch
  the disk.
- **Depth.** A channel's window keeps segments whose PDT is within `rewind_window_minutes` of the
  newest. Older segments are unlinked by the pipeline's own sweep. The window starts when the
  channel's HLS output starts. It never starts before a tune, and in 4a a channel watched only over
  TS keeps no window. That is how R10's "starts at tune" and the glossary's format-agnostic
  definition meet: the stored segments are what a future TS reader (`?behind=`, R10) would remux
  from.
- **Cap.** After each write, the process-wide total is checked against `rewind_disk_cap_gb`. While
  it is over, the oldest segment overall is unlinked, taking lingering windows' segments first. The
  12 in-memory live-edge segments of any window are never unlinked.
- **Disk errors.** On `ENOSPC` or any write error, the window stops persisting for the rest of the
  channel's run. It keeps serving what it has plus the live edge from memory, sets
  `rewind_degraded`, and logs once at WARNING. The live output never fails because of the disk.
- **Arithmetic** (computed, not measured). At the D8 table's top rate with AAC and one AC-3
  rendition, a channel-hour is about 3.1-3.4 GB, so the 16 GB default holds about 4.7
  channel-hours. A 60-minute media playlist is 1,800 entries of about 25 bytes, 45 KB per
  playlist. That is about 45 KB/s per viewer across video and one audio playlist, reloading every
  2 s. It is negligible on a LAN, so no compression is added.

### Playlists and seeking

- Media playlists list every segment in the window, with no `EXT-X-PLAYLIST-TYPE`, so a joining
  client sees the whole shared window.
- The multivariant is unchanged.
- AVPlayer's `seekableTimeRanges` then spans the window. The app seeks by date
  (`AVPlayerItem.seek(to: Date)`) using PDT. Programme markers and "restart programme" are EPG
  start times mapped to dates, available when the start is inside the window.
- Whether a 1,800-entry live playlist behaves well on Apple TV is Q4.

### Linger, evictability and the grace (4a-3a)

- **Linger.** At the pipeline's last session departure, if `rewind_linger_seconds` > 0 and the
  window is enabled, the pipeline enters LINGERING. It keeps a hold on the channel, a
  Manager-internal count that `Clients()` and every client list exclude. It stops, and releases
  the channel, when the linger elapses, when it is evicted, or when a new session arrives (the
  linger is cancelled and the pipeline is ACTIVE again).
- **Channel shutdown.** `Manager.release`'s shutdown-delay countdown starts only when both the
  client count and the linger hold are zero.
- **Evictable** = LINGERING, the channel's clients of every format = 0, and now ≥
  lingering-start + grace. The grace is `rewind_behind_live_grace_seconds` when the departing
  session's last segment request was more than 5 target durations older than the newest segment,
  and 0 otherwise.

### Slot yield (4a-3b)

1. **Django.** `resolve_initial_source`'s maxed-out branch computes `profile_ids`. For each of the
   channel's (or stream's) active profiles, it takes the profile when
   `profile_has_capacity_for_selection` is false, and when `pool_has_capacity_for_profile` is
   false it adds every active profile sharing that profile's credential counter
   (`_credential_counter_key`, `apps/m3u/connection_pool.py:138`). It returns
   `capacity: {blocked: true, profile_ids}`. This is **advisory and read-only**. The reservation
   itself is still the slot script's atomic step on the retry.
2. **Relay** (`startTune`, initial tunes only; failover never evicts). On `source: null` with
   `capacity.blocked`, it calls `Manager.EvictFor(profileIDs)`. Under the Manager mutex, that
   picks the evictable channel with the earliest evictable-at whose `SourceInfo.M3UProfileID` is
   in the set, re-checks it is still evictable, and removes it from the map. The mutex is also
   what `claim()` holds, so a viewer racing to re-attach either wins before the check or starts a
   fresh channel after it. It then stops the channel and waits for a new `released` signal, closed
   after `releaseSlot` returns, bounded by `tuneBudget`. It emits `channel_stop` as every stop
   does.
3. **Relay** retries next-source once with the same request. A second blocked answer is 503
   "no source available", as today.

At most one eviction per tune.

**Interplay with the reconciler.** A lingering channel is listed by `/proxy/relay/channels` with
its real `state` and `m3u_profile_id`, so `_live_holders` counts it. That is correct, because it
holds a provider connection. An eviction ends in `release_source()`, which bumps the counter's
version like every release, so the reconciler's write rule sees an ordinary holder leaving.

## Browser player (4a-2)

- **Entry URL.** `buildLiveStreamUrl` returns `<path>?output_format=hls`, with no `output_profile`.
- **hls.js.** `FloatingVideo.jsx`'s live path becomes an hls.js instance whenever
  `Hls.isSupported()`, configured with:
  - `xhrSetup` adding `Authorization: Bearer <fresh JWT>` (read at request time, as the recordings
    path does). It is sent to `/hls/` too, where it is harmless.
  - `liveSyncDurationCount: 3`.
  - `backBufferLength: 120`, so a 60-minute window is not held in browser memory.
  - Recovery on `NETWORK_ERROR` and `MEDIA_ERROR` as the recordings path already does. On a 403
    from `/hls/`, the player re-requests the entry URL once.
- **Native fallback.** Otherwise, if `video.canPlayType('application/vnd.apple.mpegurl')`, it sets
  `video.src` to the entry URL with the JWT as `?token=` (`QueryParamJWTAuthentication`, already in
  the hop's union at `apps/proxy/authorize.py:93-97`).
- **Removed.** `initializeLivePlayer`'s mpegts.js body, the `mpegts.js` dependency (its only
  importer is `FloatingVideo.jsx`), and the web-player Output Profile preference
  (`UiSettingsForm.jsx`, `FloatingVideoUtils.js`). The removal is listed in the PR, with the
  vitest files that change and before/after for each changed assertion.
- **Error text.** It no longer says "try Chrome or Edge". Firefox plays through hls.js.

## 4b — the server contract (only)

The Apple app is built in its own repository (R4). What it may rely on from a server that answers
the capability document below:

| Need | Server surface |
|---|---|
| Is this a Mino server with 4a? (R16, on "add server") | `GET /api/mino/capabilities/` → 200 JSON `{"product": "mino", "api_version": 1, "server_version": "<version.py>", "live_hls": {"available": true, "segment_seconds": 2, "rewind_window": {"available": <bool>, "depth_seconds": <int>}}}`. `rewind_window.available` is false until 4a-3a lands, and after it, false when `rewind_window_minutes` is 0. It is AllowAny, gated by the `XC_API` network ACL (403 otherwise), and served by Django under `^~ /api/`. The app refuses a server that 404s it or reports `api_version` < 1. |
| Sign in (R13) | `player_api.php?username=&password=` (no action) → `user_info`/`server_info`. `user_info.allowed_output_formats` includes `"m3u8"` from 4a-1b. |
| Channel list | `player_api.php?action=get_live_categories`, `…&action=get_live_streams[&category_id=]` (unchanged). |
| Playback | `http://<host>:<port>/live/<username>/<password>/<stream_id>.m3u8` → multivariant (D2). The app never builds `/hls/` URLs itself: they come only from playlists. |
| Now/next | `player_api.php?action=get_short_epg&stream_id=<id>[&limit=]` (unchanged). |
| Programme markers inside the window | `player_api.php?action=get_simple_data_table&stream_id=<id>` (unchanged). Times are UTC per `server_info.timezone` (`apps/output/views.py`'s `_build_xc_server_info`). |
| Rewind | seek within the playlist's range. The depth is the capability document's `depth_seconds`. |
| Errors | 401/403 from the entry means credentials or ACL. 429 means the stream limit. 403 from `/hls/` means re-request the entry URL once, then show an error. 410 means the channel stopped: re-tune. 503 with `Retry-After` means retry. |

**App-side, recorded here and owned by the app repository:**

- **Demo mode.** App Review cannot reach a LAN server (R4), so the app needs self-contained content
  it has the right to ship. That is the app repository's decision, and it needs nothing from this
  server.
- **App Transport Security.** Plain HTTP to a LAN host needs an ATS exception
  (`NSAllowsLocalNetworking`, and possibly `NSAllowsArbitraryLoadsForMedia` for AVFoundation). The
  app repository verifies which of these covers IP-literal hosts on iOS/tvOS 27; this spec does not
  claim it.
- **Local Network permission.** `NSLocalNetworkUsageDescription`, for the first LAN connection.
- **The R11 countdown.** The 10 s "leaving rewind" countdown pairs with D15's 10 s behind-live
  grace. The app needs no server call for it.
- **Everything else.** The app's design, its player UI, Top Shelf, channel up/down, the guide grid
  and Bonjour discovery (R6: later).

## 4c — investigation brief (only)

Taken up after 4b's first playable build (R1, R14). The questions to answer before any design:

1. **Pairing flow.** A code shown on the Apple TV, approved by an admin in the web UI, which issues
   a per-device, revocable credential. Where it is stored (a new model), and what an admin sees and
   revokes.
2. **What the credential authorises.** Does it replace Xtream credentials entirely for the Mino
   app (R14: "drops cross-IPTV-app support"), and which endpoints are Mino-only (`/api/mino/…`)?
3. **Playlist authorisation.** The new credential must reach `authorize_stream` as a principal. Is
   that a new authenticator class in `_AUTHENTICATOR_CLASSES`, or a new surface?
4. **LAN TLS.** Is it worth it (certificate distribution to Apple devices, ATS), and does it change
   the plain-HTTP decision in R6?
5. **The channel list and EPG** over Mino-only endpoints, or continued use of `player_api.php`
   actions with the new principal.

**What 4a must keep agnostic, and does:**

- Segment authorisation depends only on the media-session token (D4), never on how the playlist
  request was authorised. A 4c principal that passes `authorize_stream` gets the same token.
- The token binds a `user_id` string and a client id, not an Xtream username.
- The capability document versions itself (`api_version`), so 4c can add
  `"pairing": {…}` without breaking a 4b build.

## Testing and gates

**Go (every 4a PR that touches `relay/`).**

- Standing checks: `go build`, `go vet` and `golangci-lint` (natively and under `GOOS=linux` and
  `darwin`, as the hook does), `go test -race`, `scripts/check_go_stdlib_only.sh relay` and the
  credlint ratchet.
- Unit tests with the `relaytest` stand-in for process shape: pipes, exits, EOF mid-fragment, a
  generation that dies before its first segment.
- **Real-ffmpeg tests** for the packager, gated as parity row 4's real-ffmpeg pin is. They run
  against the base image's ffmpeg 9.0 in `go-tests.yml`'s `build` job (software encoder), and skip
  locally where ffmpeg is absent unless `CI` is set.
- The box parser gets **fuzz tests** (`testing.F`, stdlib) over the moof, tfdt and init-box readers.
- **Coverage (D20).** `relay/hls` joins the linked packages, which changes `packages=`, and new
  statements change `missing`. The PR runs the floor file's five-step CI census (≥ 12 rounds, the
  stopping rule) and states the new `missing` with its sequence, and the marginal coverage of its
  own additions (≥ 80%). A draw above the new floor on a later PR is a finding, never a floor bump
  (the file's own rule).

**Python.**

- New serializer fields, aliases and the capability view get tests in `apps.proxy.tests` and
  `apps.output.tests`.
- `authorize.py` and `next_source.py` are Gate 2 modules
  (`scripts/coverage_live_path.coveragerc`). A PR editing them runs
  `scripts/coverage_live_path_isolated.sh` before push, and covers every new line, so the Python
  floor (`missing=33`) does not move.
- Migrations ship with reverses, and a test runs each migration forward and back.

**Parity matrix.** New rows land **pinned**, in the PR that implements the behaviour. The owning PR
raises `HIGHEST_ROW_ID` in `e2e/tests/guards/parity-matrix.ts` in the same diff, and appends to a
new `<!-- block: phase 4 -->`. 4a-1b also widens the preamble's scope sentence ("the live TS/fMP4
path") to include HLS. Ids are assigned at merge time as the next free id, never in this spec. The
behaviours, by owning PR:

- **4a-1a.**
  - A generation's segments are 2.000 s ± one frame, each starting with an IDR.
  - A source boundary ends the generation, and the next segment carries `EXT-X-DISCONTINUITY` and
    a new `EXT-X-MAP`.
  - The software fallback is selected when QSV detection fails.
- **4a-1b.**
  - An `hls` tune answers a multivariant rather than bytes.
  - `.m3u8` forces `hls`.
  - A token is refused when forged, expired, revoked or for another channel.
  - An HLS session registers, and leaves after its idle timeout with `client_disconnect`.
  - An admin stop revokes an HLS session.
  - A Redirect channel is served over HLS as Proxy.
  - Media playlist conformance: ≥ 6 segments, PDT, `INDEPENDENT-SEGMENTS`, and a continuous media
    sequence.
- **4a-1c.** The automatic copy and transcode decisions, per rendition.
- **4a-3a.** Linger holds the channel. The behind-live grace applies. The playlist spans the
  window depth. A disk error degrades the window and not the output.
- **4a-3b.** An evictable lingering window yields to a blocked tune, and a watched one never does.

**E2E.**

- **`e2e-upstream` (4a-1b and 4a-1c).** It gains four loop assets, built at image build time by
  `make-asset.sh` variants and kept small (≤ 20 s, SD) so software encoding keeps real time on CI:
  - MPEG-2 576i + MP2;
  - H.264 1080i + AAC + AC-3 5.1;
  - HEVC progressive + AAC;
  - H.264 with a 10 s GOP.

  A scenario channel can name its asset. That is a contract change: `e2e-upstream/package.json`'s
  version is bumped with `CONTRACT.md` (the pair `e2e/tests/guards/upstream-contract.spec.ts`
  holds in step), and `e2e-upstream/test/` covers the new field.
- **Specs, in the `streaming` project, which needs no new project or workflow matrix change:**
  - Parse the multivariant and media playlists, and assert the tags and `CODECS` against each
    asset.
  - Fetch the init segment and two media segments, and assert the box structure and the durations
    in TypeScript. Adding an ffprobe subprocess would need a guard allowlist entry.
  - Tokens: another channel, tampered, revoked after `DELETE …/clients/<id>`.
  - Presence: `/proxy/ts/status/<uuid>` shows an `hls` client, which disappears within the idle
    timeout plus the sweep.
  - Failover: an upstream fault switches to an alternate with a **different** asset, and the next
    media playlist carries `EXT-X-DISCONTINUITY`. This is the E2E form of M3/M6.
  - **4a-2's** hls.js playback runs in the `frontend` project (Chromium): the video element's
    `currentTime` advances on a live channel.
- **Timeouts** in these specs are generous and are not gates: CLAUDE.md's measure-where-enforced
  rule forbids setting a latency or zap threshold from a local run. None is set in 4a.
- **The nginx greybox spec** gains `TOKEN_BOUND_TARGETS = ['/hls/']` and a fifth test. It asserts
  `proxy_pass http://relay_go`, `proxy_buffering off`, the blanking include, and **no**
  `auth_request` and no `internal;`. `/hls/` joins neither `PROXY_BOUND_TARGETS` nor
  `RELAY_BOUND_TARGETS`: the first test filters by its own list and the second requires the hop on
  every member, so both stay exact. The file's header comment and CLAUDE.md's nginx buffering
  paragraph are updated in the same PR.

**AVPlayer (manual gate, 4a-1b and 4a-3a).** The owner runs the M4/M7 probe shape against the
branch's image on the household host, on macOS, the iOS 27 Simulator and the Apple TV. The PR body
records the probe output (ready time, frames, behind-PDT, the selected audio format, pause
behaviour, and 4a-3a's seek into the window). Automated AVPlayer conformance belongs in the app
repository's CI (§ Rejected alternatives).

## The PRs

Each PR is `migration/phase4-<id>-<slug>`, opened as a draft, planned and implemented through
`plan-review-fix`, `implement-review-escalate` and `pr-merge-gate`. 4a-1b and 4a-3b are
security-adjacent (a new bearer token; slot accounting), so the skills' cadence would put their
reviews on `fable` from round one. The owner's ruling of 2026-09-27 puts every review on `opus`
while it stands. Every PR carries break-checks: a named wrong edit, the test that reddens with a
message naming the mechanism, then the revert.

### 4a-1a — the HLS packager (inert)

- **Scope.**
  - New package `relay/hls`: the probe (D9), the argv builder (D8, D11), the pipeline and its
    generations (D10), the fMP4 box reader and segmenter (D6), `hls.Store`, and playlist rendering
    (D7).
  - `relay/ffmpeg` gains a spawn variant with extra output pipes.
  - The channel records the ring index of each source boundary. `run()` gains a `released` signal
    closed after `releaseSlot`, used by 4a-3b and harmless before it.
  - No route, no Django change: nothing reaches the package.
- **Tests.**
  - Unit tests and fuzzing for the box reader.
  - A stand-in for pipe shapes and early exits.
  - A real-ffmpeg software test: 12 s of the 1080i fixture produces aligned 2 s segments on three
    renditions, with correct `CODECS`.
  - A real-ffmpeg boundary test: two fixtures with different PIDs produce two generations and a
    discontinuity. It fails if the generation is not restarted, which is M3's silent drop.
  - Detection with QSV unavailable selects software.
- **Break-checks.**
  - Remove the restart at a boundary: the boundary test reddens with "generation 1 produced no
    segments after the boundary".
  - Drop `delay_moov`: the AC-3 test reddens naming the moov error.
  - Stamp PDT at publish time: the PDT test reddens on the `JoinBehind` backlog.
- **Gates.** Go coverage census (D20). The PR body records Q1's first QSV run on the household
  host if available. If it is not, that is the first item of 4a-1b's body.
- **Stopping point.** Inert, and harmless to stop after, but delivers nothing to a viewer.

PR description draft:

> **Phase 4a-1a: the HLS packager (inert).** Adds `relay/hls`, which turns a channel's ring into
> fMP4/CMAF HLS renditions. A probe decides deinterlacing, geometry and audio layout. One ffmpeg
> per generation writes video, stereo AAC and AC-3/E-AC-3 on separate pipes. A segmenter cuts
> 2-second segments and renders the playlists. The encoder restarts at every source boundary,
> because a surviving encoder silently drops a source with different PIDs (spec M3), and the
> playlist marks the discontinuity. It uses Quick Sync when the one-frame detection succeeds and
> libx264 otherwise. No route reaches it yet. Spec: `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`
> (D6-D11); ADR 0009. Coverage census: <rounds>. Break-checks: <three, with red output>. QSV on the
> household host: <result, or "not yet run — first item of 4a-1b">.

### 4a-1b — live HLS end to end

- **Scope, relay.**
  - `identify()` accepts `hls`, and `xcForcedFormat` maps `.m3u8`.
  - The HLS entry path in `StreamHandler`: `Attach`, then `AttachOutput`, then wait for init, then
    the multivariant with a fresh token.
  - The token (D4), in `relay/control`.
  - The `/hls/` routes and the session table with presence (D5): events, idle sweep, resume and
    revocation through `DELETE …/clients/<id>`.
  - Redirect as Proxy on `hls` (D13).
  - The payload fields `hls_encoder` and `hls_generation`.
- **Scope, Django.**
  - `_FORMAT_ALIASES` gains `hls` and `m3u8`.
  - `_xc_allowed_output_formats` adds `m3u8`.
  - `get.php` with `output=m3u8|hls` emits `/live/u/p/<id>.m3u8` with no `output_format` query (R9).
  - The capability view, its serializer and its URL.
  - `relay_serializers.py` preserves the new optional fields.
- **Scope, nginx and Docker.**
  - `location ^~ /hls/` (D3).
  - The compose files' relay-bearing services gain a commented `/dev/dri` note naming Quick Sync
    for HLS.
- **Scope, docs.**
  - CLAUDE.md: the nginx paragraph, and the "no HLS output" line becomes history.
  - `README.md:153` becomes true for live (follow-up F1 records the wording).
  - Parity matrix preamble and rows.
  - `e2e/COVERAGE.md`.
- **Tests.** As § Testing lists for 4a-1b, plus `e2e-upstream`'s assets and scenario field.
- **Break-checks.**
  - Accept a token for any channel: the cross-channel spec reddens.
  - Remove revocation from the client stop: the revoke spec reddens.
  - Put `auth_request` on `^~ /hls/`: the greybox fifth test reddens.
  - Set idle to 0: the presence spec reddens on a missing `hls` client.
- **Manual gate.** The AVPlayer run (macOS, iOS 27 Simulator, Apple TV).
- **Stopping point.** Yes: live TV plays in AVPlayer through any Xtream client.

PR description draft:

> **Phase 4a-1b: live HLS end to end.** A live tune whose format resolves to `hls` —
> `?output_format=hls`, or an Xtream `.m3u8` URL — now answers a multivariant playlist instead of
> bytes. Segments and media playlists live under `/hls/<token>/…`, authorised by a relay-minted
> media-session token (HMAC of `SECRET_KEY`, context `media-session`), so Django is asked once per
> playlist session, not per segment. An HLS viewer is a client in the relay's registry while its
> session is live: stream limits, admin stop and stats need no special case. `player_api`
> advertises `m3u8`, `get.php?output=m3u8` emits `.m3u8` URLs, and `/api/mino/capabilities/` tells
> the Apple app this server has 4a. Spec D2-D5, D13, D19. nginx: new `^~ /hls/`, no hop, buffering
> off; the greybox spec pins it. AVPlayer manual gate: <probe output>. Refs: ADR 0008, ADR 0009.

### 4a-1c — the automatic HLS profile

- **Scope.**
  - The `core` migration: `OutputProfile.hls_mode`, and the two locked rows, with a reverse.
  - The `channels` migration: `Channel.hls_output_profile`, with a reverse.
  - The serializers. `hls_mode` is read-only, and HLS rows are excluded from the `output_profiles`
    map and from `resolve_output_profile`.
  - Next-source `hls_profile`.
  - The channel form gets an "HLS output" select (bulk edit is not in scope).
  - The relay's automatic rules (§ Encoder argv) and the two run-level rules.
- **Tests.**
  - Migrations forward and back.
  - A per-rendition decision table test against the four new assets.
  - A run-level test: a copied HEVC run whose next source is MPEG-2 is transcoded into
    H.264/HEVC-declared form, as the rule says.
  - E2E: an automatic channel on the H.264 asset serves copied video, with `CODECS` from the
    source.
- **Break-checks.**
  - Copy interlaced video: the decision test reddens naming `field_order`.
  - Let a copied segment exceed target + 0.5 s: the segmenter test reddens.
- **Stopping point.** Yes.

PR description draft:

> **Phase 4a-1c: the *automatic* HLS profile.** ADR 0009's opt-in: a channel can be set to an HLS
> Output Profile in *automatic* mode, which copies what AVPlayer accepts and transcodes only what it
> does not (MP2 → AAC; interlaced, MPEG-2 or long-GOP video → H.264). Two locked profiles are
> seeded; the choice is per channel (`Channel.hls_output_profile`), sent to the relay as
> `hls_profile` on next-source. Spec D12. Migrations have reverses and a round-trip test.

### 4a-2 — the browser player on HLS

- **Scope.** § Browser player. It touches `FloatingVideo.jsx`, `FloatingVideoUtils.js`,
  `UiSettingsForm.jsx`, `package.json` and `package-lock.json` (removing mpegts.js), and the vitest
  files. It changes no server code.
- **Tests.**
  - Vitest for URL building and the player's choice between hls.js and native.
  - An E2E `frontend` spec for playback.
  - Every changed vitest assertion is listed before and after (the test-modification rule).
- **Break-checks.** Keep `output_format=mpegts` in `buildLiveStreamUrl`: the URL test and the E2E
  playback spec redden.
- **Stopping point.** Yes.

PR description draft:

> **Phase 4a-2: the browser player plays live over HLS.** Live channels in the floating player now
> play through hls.js against the HLS output (native HLS where only that exists), so Firefox plays
> live too. mpegts.js, its live code path and the web-player Output Profile preference (which only
> fed the mpegts URL) are removed. Spec D18. Changed tests, before → after: <list>.

### 4a-3a — the live rewind window and linger

- **Scope.**
  - The disk store and its sweep, cap and degradation (D14).
  - Window playlists.
  - Linger, evictability and grace (D15).
  - `Manager` holding a channel open for a linger.
  - The four settings (D17), end to end: `get_proxy_settings` defaults, the relay settings
    serializer, the Go `tuningFrom` keys, and the proxy-settings form fields.
  - `03-init-dispatcharr.sh` creates `/data/cache/rewind`.
  - The capability document reports the window.
  - Payload fields.
- **Tests.**
  - Unit tests: depth trim, cap eviction order, `ENOSPC` degradation (an injectable writer), and
    start-up cleanup.
  - E2E: a playlist spanning more than the live-edge 10 segments after a short configured depth.
  - E2E: the channel still running during linger with zero clients, and stopped after it.
  - E2E: the behind-live grace.
- **Break-checks.**
  - Let a TS viewer's channel be evictable: the watched-never-evicted test reddens.
  - Stop the encoder at the last session: the linger spec reddens on a stopped channel.
- **Manual gate.** AVPlayer seek into the window on Apple TV. Q4's measurement is run here.
- **Stopping point.** Yes. Without 4a-3b a lingering window holds its slot for the full linger,
  which R10 says it must not do when a tune needs it. Stopping here is legitimate only with
  `rewind_linger_seconds` set to 0 on a slot-constrained provider.

PR description draft:

> **Phase 4a-3a: the live rewind window.** Each HLS channel now keeps its last
> `rewind_window_minutes` (60) on disk under `/data/cache/rewind`, shared by every viewer, served as
> a sliding HLS window so AVPlayer can pause, rewind and scrub back to live. After the last viewer
> leaves, the channel lingers for `rewind_linger_seconds` (300) so zapping back keeps the rewind.
> The window is lost on restart and drain, capped by `rewind_disk_cap_gb`, and a disk error
> degrades the window, never the live output. Spec D14, D15, D17. AVPlayer seek gate: <output>.

### 4a-3b — a lingering window yields its slot

- **Scope.**
  - Django: `capacity` on next-source (the serializer, and the computation in
    `resolve_initial_source`).
  - Relay: `Manager.EvictFor`, and the one retry in `startTune`.
  - A parity row.
- **Tests.**
  - A Django unit test for `profile_ids` covering both `profile_full` and `credential_full`
    siblings.
  - A Go race test: an eviction concurrent with a re-attach, where the viewer and the eviction
    never both win.
  - E2E against an upstream with `maxConnections: 1`: tune A, leave, tune B. B plays, A's window is
    gone, and the release reached Django (the counter is back to 1).
- **Break-checks.**
  - Evict without the re-check under the lock: the race test reddens.
  - Omit credential siblings: the credential test reddens.
- **Gates.** The Python Gate 2 isolated run, because `next_source.py` is edited.
- **Stopping point.** This completes 4a.

PR description draft:

> **Phase 4a-3b: a lingering rewind window gives its provider slot to a blocked tune.** When every
> provider profile is full, next-source now says which profiles blocked the tune; the relay evicts
> one idle, lingering window on those profiles and retries once. Slots stay Django's decision (ADR
> 0005): Django names the blocking profiles, the relay only chooses among channels it knows nobody
> is watching. The #513 reconciler needs no change. Spec D16.

## Open questions that need a measurement

| # | Question | Who, where | What decides |
|---|---|---|---|
| Q1 | Does the D8 QSV argv run on the household host (12th-gen, UHD 770): device init, `hwupload` + `h264_qsv`, `forced_idr` with `force_key_frames` giving IDRs every 2 s, `-level 42`? And what CPU and GPU does it cost for two concurrent 1080i50 channels? | Owner, on the host, with the 4a-1a image: `ffmpeg` on a captured provider TS, then two live channels via the relay. | If an option is refused, 4a-1a corrects the argv (no design change). If two channels exceed 60% of total CPU with software deinterlacing, D8's deinterlace moves to `vpp_qsv=deinterlace=2` behind a probe-driven switch (a 4a-1a or 4a-1b change). |
| Q2 | Which audio group does Apple TV 4K pick, through a TV only and through a surround receiver? | Owner, Apple TV, the 4a-1b build, with the probe or the first app build. | If tvOS picks AAC with a receiver attached, the multivariant lists the AC-3 variant first (a one-line ordering change). |
| Q3 | E-AC-3 JOC (Atmos) passthrough: does ffmpeg's `dec3` carry the JOC signalling, and does `CODECS="ec-3"` or `"ec+3"` make Apple TV output Atmos? | Owner, with an Atmos-carrying channel if the provider has one, an Apple TV and an Atmos receiver. | Declare `ec+3` when JOC is present, or drop the `eac3` rendition (AC-3 only) if passthrough loses JOC. Until measured, 4a ships `ec-3` with no Atmos claim. |
| Q4 | A 1,800-entry sliding live playlist on Apple TV: memory, CPU, reload time, seek responsiveness. | Owner, Apple TV, 4a-3a, a channel watched for 60 min. | If it misbehaves, the default depth drops (setting) and a follow-up considers a smaller window in the playlist than on disk. |
| Q5 | Zap time: channel tap to first frame, cold tune, on the host with QSV. | Owner or app. It is informational, not a gate. | Whether the encoder should start at the ring's head instead of `JoinBehind` (a one-constant change), traded against the first segments' readiness. |
| Q6 | The failover gap on real hardware: from boundary to the next generation's first segment. | E2E (software, on CI) records it, and the owner (QSV). | Above 10 s, a follow-up considers pre-spawning the next generation at the boundary. |
| Q7 | Does ffprobe report `field_order` reliably on the household's real channels (H.264 PAFF/MBAFF, MPEG-2)? | Owner: capture three channels' ring bytes and run the D9 probe. | If unreliable, `bwdif=deint=interlaced` is applied to every source (safe on progressive frames, which it passes), and `R` is taken from the stream's field rate. |
| Q8 | Is an automated AVPlayer check feasible in GitHub's macOS runners, with a runtime at the iOS/tvOS 27 floor? | App repository, when its CI is set up. | Whether 4a's manual gate can be retired into the app repository's CI. |

## Rejected alternatives

- **Remux by default.** Rejected in ADR 0009.
- **ffmpeg's `-f hls` muxer.** D6.
- **One encoder surviving failover.** D10, M3.
- **Refusing HLS without Quick Sync.** D11.
- **A per-client HLS profile** (the existing `?output_profile=` for HLS). It breaks "one shared
  encode per channel" (D12).
- **A separate HMAC key file for the token.** D4.
- **Binding the token to the client IP.** It breaks AirPlay and roaming (D4).
- **`EXT-X-PLAYLIST-TYPE:EVENT` for the window.** It cannot drop old segments (D14).
- **Keeping the window in memory.** ADR 0008.
- **The relay deciding which channel's slot to take without Django naming the blocking profiles.**
  It would move slot knowledge into the relay (ADR 0005).
- **Django calling the relay to evict inside next-source.** It nests a cross-process call in a
  request the relay is itself waiting on, and needs Django to know relay-private linger state.
- **A macOS CI job running AVPlayer in 4a.** No runner image is known to carry the iOS/tvOS 27
  floor. Simulator boots are slow and flaky, and the app repository is the natural owner. It is a
  manual gate here (D20, Q8).

## Risks

- **The QSV argv is unexercised.** Q1 is the first run. The software fallback means a wrong argv
  degrades to CPU encoding rather than to no picture, but a household host at 100% CPU is its own
  failure. 4a-1a's PR must not merge claiming QSV works without Q1's output.
- **Lingering holds scarce provider slots.** Each zap-away holds a slot for 5 minutes. On a
  two-connection provider, zapping through three channels blocks the third until 4a-3b's eviction.
  4a-3a alone is a regression for slot-constrained households (§ 4a-3a's stopping point).
- **A token in the URL path is logged by nginx.** It is scoped to one channel, dies within 300 s of
  the session going idle, and is revoked by a stop. The nginx access log already records XC
  credentials in the same way. A remote-access future would revisit both together (ADR 0008 keeps
  remote access off the critical path).
- **Disk.** 3.1-3.4 GB per channel-hour of write traffic on whatever backs `/data`. On an SD card
  or a slow NAS this is wear and latency. The cap bounds space, not wear.
- **The failover gap** (M6: 8.9 s on the prototype host) is longer than a TS client sees today. The
  discontinuity is correct, but a viewer notices it.
- **Parity-matrix growth.** Rows must land pinned. A row landing `owed:` would need a `PRS`
  vocabulary change, and this spec does not plan one.

## Non-goals — deliberately out of scope

- **VOD, catch-up (timeshift) and recordings** over HLS or in the app (R2). The DVR's own HLS
  (`apps/channels/tasks.py`, `/api/channels/recordings/<pk>/hls/…`) is untouched.
- **Remote access** built into the app, and the remote-access hardening it would require (R3,
  ADR 0008).
- **Low-Latency HLS** (R8). The fixed 2 s GOP keeps it reachable later.
- **A TS reader for the rewind window** (`?behind=`, R10). It is recorded as a known extension.
- **Plex design weight, and deleting the HDHomeRun, M3U or XMLTV outputs** (R12).
- **Renaming** Dispatcharr to Mino, or renaming any existing identifier, route or header (R15). The
  existing `X-Dispatcharr-*` headers and `DISPATCHARR_*` variables are kept, and nothing new is
  named for Dispatcharr.
- **Android** (ADR 0008).
- **Adaptive bitrate ladders.** One video rendition per channel.
- **Audio language selection, subtitles and closed captions.** The first audio stream feeds AAC.
- **Bonjour discovery** (R6: later) and **multi-profile** households (R5).
- **HLS as a deployment or user default output format** (D2).
- **Metrics endpoints** (Phase 2 D6's reasoning stands).

## Follow-ups noticed while writing this spec (not folded in)

- **F1.** `README.md:153` advertises "📡 **HLS Output** — Serve streams as HLS alongside existing
  container formats". It is false today, and 4a-1b makes it true for **live** only. 4a-1b rewrites
  it to say so. Until then it stays, per the owner's instruction for this PR.
- **F2.** `apps/proxy/authorize.py`'s `resolve_output_format` returns a user's
  `custom_properties.output_format` **unvalidated** (`:277-281`): any string a user record holds
  reaches the relay and is refused 501. That is pre-existing, and harmless until a value such as
  `hls` is stored there on purpose. It is recorded rather than fixed.

## Done log

Filled in as PRs merge.

| Item | PR | Merged |
|---|---|---|
| Spec, ADR 0008, ADR 0009, glossary | this PR | |
| 4a-1a packager | | |
| 4a-1b live HLS end to end | | |
| 4a-1c automatic profile | | |
| 4a-2 browser player | | |
| 4a-3a rewind window | | |
| 4a-3b slot yield | | |

## Changelog

- **2026-09-27, v1.** First draft, written against `560c6d58` with the prototypes M1-M7.

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
