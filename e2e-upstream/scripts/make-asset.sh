#!/usr/bin/env bash
# Generate a looping MPEG-TS asset. Build-time only: ffmpeg is confined to
# the Docker builder stage so the runtime image, and this repo, carry neither
# ffmpeg nor a version of it that could drift from CI's.
#
#   make-asset.sh <output.ts>              the default loop (`loop`)
#   make-asset.sh <output.ts> <variant>    one of the Phase 4a codec fixtures
#
# The variants are the six codec fixtures of the Phase 4 spec's § Testing
# (docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md, 4a-0);
# src/asset.ts's ASSET_NAMES lists the same seven names, and
# test/asset-names.test.ts holds this file, that list and the Dockerfile to
# one set. Each variant is 20 s at 25 frames per second with PIDs of its own,
# and is checked after it is written: `check_shape` compares every stream
# ffprobe reports against the variant's expected shape, and `check_gop` the
# video's keyframe spacing. A variant whose shape drifts fails the image
# build, naming the stream, instead of shipping a fixture that silently tests
# something else. The expected shapes are what CONTRACT.md guarantees.
#
# The variants use no drawtext, so they build with any ffmpeg that has
# libx264 and libx265 (Homebrew's included); `loop` still needs drawtext.
set -euo pipefail

OUT="${1:?usage: make-asset.sh <output.ts> [variant]}"
VARIANT="${2:-loop}"

PACKET_SIZE=188
# Every variant: 20 s at 25 frames per second (500 frames), one loop.
VARIANT_SECONDS=20
VARIANT_FPS=25
VARIANT_FRAMES=$((VARIANT_SECONDS * VARIANT_FPS))

# A fixture that fails its check is deleted, so a caller that ignores the
# exit status is left with no file rather than a wrong one.
fail() {
  echo "make-asset.sh: ${VARIANT}: $*" >&2
  rm -f -- "${OUT}"
  exit 1
}

# One ffprobe line per stream, in stream order: `index=N|key=value|...`.
# ffprobe lists every stream twice for a TS, once inside its program and once
# at top level, as `program|stream|index=...`, `stream|index=...` or a bare
# continuation line; the section prefixes are stripped and the duplicates
# dropped, which leaves one line per stream in index order.
probe_streams() {
  ffprobe -v error \
    -show_entries stream=index,id,codec_type,codec_name,profile,pix_fmt,field_order,width,height,r_frame_rate,sample_rate,channels,channel_layout \
    -of compact "${OUT}" \
    | sed -E 's/^(program[|])?(stream[|])?//' \
    | grep '^index=' \
    | awk '!seen[$0]++'
}

# Compares the probed streams against the expected lines given as arguments,
# one per stream in order, each a `|`-joined list of `key=value` pairs that
# must all appear in that stream's probe line. Names the missing, wrong or
# unexpected stream.
check_shape() {
  local actual line
  local -a lines=()
  actual="$(probe_streams)" || fail "ffprobe could not list the streams of ${OUT}"
  while IFS= read -r line; do
    [ -n "${line}" ] && lines+=("${line}")
  done <<< "${actual}"

  local index=0 expected pair
  for expected in "$@"; do
    if [ "${index}" -ge "${#lines[@]}" ]; then
      fail "missing stream ${index}: expected ${expected}, but the asset has only ${#lines[@]} stream(s)"
    fi
    for pair in $(printf '%s' "${expected}" | tr '|' ' '); do
      case "|${lines[${index}]}|" in
        *"|${pair}|"*) ;;
        *) fail "stream ${index}: expected ${pair}, found ${lines[${index}]}" ;;
      esac
    done
    index=$((index + 1))
  done

  if [ "${#lines[@]}" -gt "${index}" ]; then
    fail "unexpected stream ${index}: ${lines[${index}]} (expected exactly ${index} stream(s))"
  fi
}

# Asserts the first video stream has exactly VARIANT_FRAMES frames, starts on
# a keyframe, and has a keyframe exactly every <gop-seconds>, and no other.
check_gop() {
  local gop_seconds="$1"
  local gop_frames=$((gop_seconds * VARIANT_FPS))
  local expected_keyframes=$((VARIANT_FRAMES / gop_frames))
  # Packets in decode order, `<pts>,<flags>`; frame indices in display order
  # come from sorting by pts. ffprobe 5.1 (Debian bookworm, the image build)
  # prints a blank line after every packet and ffprobe 9 does not, so blank
  # lines are dropped before anything is counted.
  local verdict
  verdict="$(
    ffprobe -v error -select_streams v:0 -show_entries packet=pts,flags -of csv=p=0 "${OUT}" \
      | grep -v '^[[:space:]]*$' \
      | sort -t, -k1,1n \
      | awk -F, -v frames="${VARIANT_FRAMES}" -v gop="${gop_frames}" -v want="${expected_keyframes}" '
          { if (index($2, "K") > 0) { keys[k++] = NR - 1 } }
          END {
            if (NR != frames) { printf "has %d video frames, expected %d", NR, frames; exit 1 }
            if (k != want) { printf "has %d keyframes, expected %d (one every %d frames)", k, want, gop; exit 1 }
            for (i = 0; i < k; i++) {
              if (keys[i] != i * gop) { printf "keyframe %d is at frame %d, expected frame %d", i, keys[i], i * gop; exit 1 }
            }
          }'
  )" || fail "video stream 0 ${verdict}; expected one keyframe every ${gop_seconds} s"
}

# Shared by every variant. `-t` cuts every stream at 20 s. `-muxdelay 0
# -muxpreload 0` start the PCR at the first DTS instead of 0.7 s ahead of it:
# src/asset.ts's measureLoop() spans every PCR, PTS and DTS it sees, so the
# default lead would add ~0.7 s of dead time at every loop seam, and a 20 s
# loop would jump its timestamps forward 0.7 s three times a minute.
TIMING=(-t "${VARIANT_SECONDS}" -muxdelay 0 -muxpreload 0)
X264_GOP_2S=(-g 50 -keyint_min 50 -sc_threshold 0)
STEREO_SINE=(-f lavfi -i "sine=frequency=440:sample_rate=48000:duration=${VARIANT_SECONDS}")
# Six channels, each its own tone, so a downmix is audible as a downmix.
SURROUND_51=(-f lavfi -i "aevalsrc=exprs=sin(440*2*PI*t)|sin(550*2*PI*t)|sin(660*2*PI*t)|sin(110*2*PI*t)|sin(770*2*PI*t)|sin(880*2*PI*t):channel_layout=5.1(side):sample_rate=48000:duration=${VARIANT_SECONDS}")

case "${VARIANT}" in
  loop)
    DURATION="${ASSET_DURATION_SECONDS:-60}"
    FPS="${ASSET_FPS:-25}"
    BITRATE="${ASSET_BITRATE:-2000k}"
    # The burned-in frame counter is a human debugging aid only — for eyeballing a
    # captured TS in VLC after a failure. Nothing in the test runner decodes video,
    # so no test asserts on it.
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc=size=640x360:rate=${FPS}:duration=${DURATION}" \
      -f lavfi -i "sine=frequency=440:duration=${DURATION}" \
      -vf "drawtext=text='%{frame_num}':x=10:y=10:fontsize=48:fontcolor=white:box=1:boxcolor=black" \
      -c:v libx264 -preset ultrafast -b:v "${BITRATE}" -pix_fmt yuv420p \
      -c:a aac -b:a 128k \
      -mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257 \
      -f mpegts "${OUT}"
    ;;

  mpeg2-576i-mp2)
    # 576i25: a 50 fps progressive source woven into top-field-first frames,
    # so the two fields of a frame really are 20 ms apart.
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc2=size=720x576:rate=50:duration=${VARIANT_SECONDS}" \
      "${STEREO_SINE[@]}" \
      -map 0:v -map 1:a -vf "interlace=scan=tff" \
      -c:v mpeg2video -flags +ildct+ilme -b:v 4000k -g 50 -bf 0 \
      -c:a mp2 -b:a 192k -ac 2 \
      "${TIMING[@]}" \
      -mpegts_start_pid 0x200 -streamid 0:512 -streamid 1:513 \
      -f mpegts "${OUT}"
    check_shape \
      "index=0|id=0x200|codec_type=video|codec_name=mpeg2video|profile=Main|pix_fmt=yuv420p|field_order=tt|width=720|height=576|r_frame_rate=25/1" \
      "index=1|id=0x201|codec_type=audio|codec_name=mp2|sample_rate=48000|channels=2|channel_layout=stereo"
    check_gop 2
    ;;

  h264-1080i-aac-ac3)
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc2=size=1920x1080:rate=50:duration=${VARIANT_SECONDS}" \
      "${STEREO_SINE[@]}" \
      "${SURROUND_51[@]}" \
      -map 0:v -map 1:a -map 2:a -vf "interlace=scan=tff" \
      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -flags +ildct+ilme -x264-params tff=1 \
      -b:v 6000k "${X264_GOP_2S[@]}" \
      -c:a:0 aac -b:a:0 128k -ac:a:0 2 \
      -c:a:1 ac3 -b:a:1 448k \
      "${TIMING[@]}" \
      -mpegts_start_pid 0x300 -streamid 0:768 -streamid 1:769 -streamid 2:770 \
      -f mpegts "${OUT}"
    check_shape \
      "index=0|id=0x300|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=tt|width=1920|height=1080|r_frame_rate=25/1" \
      "index=1|id=0x301|codec_type=audio|codec_name=aac|profile=LC|sample_rate=48000|channels=2|channel_layout=stereo" \
      "index=2|id=0x302|codec_type=audio|codec_name=ac3|sample_rate=48000|channels=6|channel_layout=5.1(side)"
    check_gop 2
    ;;

  hevc-aac)
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
      "${STEREO_SINE[@]}" \
      -map 0:v -map 1:a \
      -c:v libx265 -preset ultrafast -pix_fmt yuv420p -b:v 1000k \
      -x265-params "log-level=error:keyint=50:min-keyint=50:scenecut=0" \
      -c:a aac -b:a 128k -ac 2 \
      "${TIMING[@]}" \
      -mpegts_start_pid 0x400 -streamid 0:1024 -streamid 1:1025 \
      -f mpegts "${OUT}"
    # No field_order pair: ffprobe reports `unknown` for this progressive
    # HEVC stream (measured on ffmpeg 5.1.9, 8.1.2 and 9.0.1), not
    # `progressive`, so asserting either would pin an ffprobe quirk.
    check_shape \
      "index=0|id=0x400|codec_type=video|codec_name=hevc|profile=Main|pix_fmt=yuv420p|width=640|height=360|r_frame_rate=25/1" \
      "index=1|id=0x401|codec_type=audio|codec_name=aac|profile=LC|sample_rate=48000|channels=2|channel_layout=stereo"
    check_gop 2
    ;;

  h264-gop10-aac)
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
      "${STEREO_SINE[@]}" \
      -map 0:v -map 1:a \
      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -b:v 1500k \
      -g 250 -keyint_min 250 -sc_threshold 0 \
      -c:a aac -b:a 128k -ac 2 \
      "${TIMING[@]}" \
      -mpegts_start_pid 0x500 -streamid 0:1280 -streamid 1:1281 \
      -f mpegts "${OUT}"
    check_shape \
      "index=0|id=0x500|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=progressive|width=640|height=360|r_frame_rate=25/1" \
      "index=1|id=0x501|codec_type=audio|codec_name=aac|profile=LC|sample_rate=48000|channels=2|channel_layout=stereo"
    check_gop 10
    ;;

  h264-eac3)
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
      "${SURROUND_51[@]}" \
      -map 0:v -map 1:a \
      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -b:v 1500k "${X264_GOP_2S[@]}" \
      -c:a eac3 -b:a 384k \
      "${TIMING[@]}" \
      -mpegts_start_pid 0x600 -streamid 0:1536 -streamid 1:1537 \
      -f mpegts "${OUT}"
    check_shape \
      "index=0|id=0x600|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=progressive|width=640|height=360|r_frame_rate=25/1" \
      "index=1|id=0x601|codec_type=audio|codec_name=eac3|sample_rate=48000|channels=6|channel_layout=5.1(side)"
    check_gop 2
    ;;

  h264-noaudio)
    ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i "testsrc2=size=640x360:rate=25:duration=${VARIANT_SECONDS}" \
      -map 0:v \
      -c:v libx264 -preset veryfast -profile:v high -pix_fmt yuv420p -b:v 1500k "${X264_GOP_2S[@]}" \
      "${TIMING[@]}" \
      -mpegts_start_pid 0x700 -streamid 0:1792 \
      -f mpegts "${OUT}"
    check_shape \
      "index=0|id=0x700|codec_type=video|codec_name=h264|profile=High|pix_fmt=yuv420p|field_order=progressive|width=640|height=360|r_frame_rate=25/1"
    check_gop 2
    ;;

  *)
    echo "make-asset.sh: unknown variant '${VARIANT}'" >&2
    exit 2
    ;;
esac

# ffmpeg's apt version is deliberately unpinned above — Debian point releases
# vanish from the archive, and pinning one would break this build for a
# byte-exact reproducibility guarantee we don't need. What we do need is that
# a drifted ffmpeg can't ship a broken asset silently, hence the checks below.
# Nothing downstream may hardcode the packet count or duration this produces:
# a version drift is expected to change them, and they are measured from the
# asset at startup (see Task 5's measureLoop()), not baked in as constants.
SIZE="$(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}")"

if [ "$((SIZE % PACKET_SIZE))" -ne 0 ]; then
  echo "make-asset.sh: ${OUT} is ${SIZE} bytes, not a multiple of ${PACKET_SIZE} — ffmpeg did not produce a clean TS packet stream" >&2
  exit 1
fi

FIRST_BYTE="$(head -c 1 "${OUT}" | od -An -tx1 | tr -d ' ')"
if [ "${FIRST_BYTE}" != "47" ]; then
  echo "make-asset.sh: ${OUT} starts with 0x${FIRST_BYTE}, not the TS sync byte 0x47 — this is not a TS file" >&2
  exit 1
fi

PACKETS=$((SIZE / PACKET_SIZE))
ACTUAL_DURATION="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "${OUT}")"
echo "Wrote ${OUT} (${VARIANT}, ${SIZE} bytes, ${PACKETS} packets, ${ACTUAL_DURATION}s)"
