#!/usr/bin/env bash
# Generate the finite VOD asset. Build-time only, alongside make-asset.sh, in
# the Docker builder stage — the runtime image carries the assets, not ffmpeg.
#
# Deliberately short and deliberately *finite*: the whole point of this asset
# is that it has an end, a Content-Length and a byte offset you can seek to.
# The TS loop next to it has none of those and never will.
set -euo pipefail

OUT="${1:?usage: make-vod-asset.sh <output.mp4>}"
DURATION="${VOD_ASSET_DURATION_SECONDS:-5}"
FPS="${VOD_ASSET_FPS:-25}"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc=size=320x180:rate=${FPS}:duration=${DURATION}" \
  -f lavfi -i "sine=frequency=440:duration=${DURATION}" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -c:a aac -b:a 64k \
  -movflags +faststart \
  -f mp4 "${OUT}"

# ffmpeg's version is unpinned (see make-asset.sh), so assert the output
# rather than a byte-exact artifact. Nothing downstream may hardcode this
# size: the server reads it from the file at load time.
SIZE="$(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}")"
if [ "${SIZE}" -lt 1024 ]; then
  echo "make-vod-asset.sh: ${OUT} is only ${SIZE} bytes — ffmpeg produced nothing usable" >&2
  exit 1
fi

# `ftyp` is the first box of every MP4. A file that does not start with one is
# not an MP4, whatever the extension says — and Dispatcharr infers its
# client-facing Content-Type from that extension.
if [ "$(dd if="${OUT}" bs=1 skip=4 count=4 2>/dev/null)" != "ftyp" ]; then
  echo "make-vod-asset.sh: ${OUT} does not begin with an ftyp box — this is not an MP4" >&2
  exit 1
fi

echo "Wrote ${OUT} (${SIZE} bytes)"
