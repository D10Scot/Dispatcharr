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

echo "Wrote ${OUT} ($(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}") bytes)"
