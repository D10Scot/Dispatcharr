FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS asset
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY scripts/make-asset.sh scripts/make-vod-asset.sh ./
# One TS asset per name in src/asset.ts's ASSET_NAMES: `loop`, the default,
# and Phase 4a's six codec fixtures, each shape-checked by make-asset.sh
# itself. test/asset-names.test.ts holds this list to ASSET_NAMES. `|| exit 1`
# because `sh -c` has no `-e`, and a loop's status is only its last command's.
RUN chmod +x make-asset.sh make-vod-asset.sh \
 && mkdir /build/assets \
 && for name in loop mpeg2-576i-mp2 h264-1080i-aac-ac3 hevc-aac h264-gop10-aac h264-eac3 h264-noaudio; do \
      ./make-asset.sh "/build/assets/${name}.ts" "${name}" || exit 1; \
    done \
 && ./make-vod-asset.sh /build/assets/vod.mp4

FROM node:24-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc

# package.json declares no runtime dependencies — only the compiler and test
# tooling used above — so the runtime stage needs nothing from node_modules,
# not even a pruned copy of it.
FROM node:24-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS runtime
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=asset /build/assets/ /app/assets/
ENV UPSTREAM_ASSET=/app/assets/loop.ts
ENV UPSTREAM_ASSET_DIR=/app/assets
ENV UPSTREAM_VOD_ASSET=/app/assets/vod.mp4
EXPOSE 8080
CMD ["node", "dist/index.js"]
