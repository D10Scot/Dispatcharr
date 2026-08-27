#!/usr/bin/env bash
# Generate the looping MPEG-TS asset. Build-time only: ffmpeg is confined to
# the Docker builder stage so the runtime image, and this repo, carry neither
# ffmpeg nor a version of it that could drift from CI's.
set -euo pipefail

OUT="${1:?usage: make-asset.sh <output.ts>}"
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

# ffmpeg's apt version is deliberately unpinned above — Debian point releases
# vanish from the archive, and pinning one would break this build for a
# byte-exact reproducibility guarantee we don't need. What we do need is that
# a drifted ffmpeg can't ship a broken asset silently, hence the checks below.
# Nothing downstream may hardcode the packet count or duration this produces:
# a version drift is expected to change them, and they are measured from the
# asset at startup (see Task 5's measureLoop()), not baked in as constants.
SIZE="$(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}")"
PACKET_SIZE=188

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
echo "Wrote ${OUT} (${SIZE} bytes, ${PACKETS} packets, ${ACTUAL_DURATION}s)"
