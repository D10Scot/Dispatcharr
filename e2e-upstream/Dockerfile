FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS asset
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY scripts/make-asset.sh ./
RUN chmod +x make-asset.sh && ./make-asset.sh /build/loop.ts

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
COPY --from=asset /build/loop.ts /app/assets/loop.ts
ENV UPSTREAM_ASSET=/app/assets/loop.ts
EXPOSE 8080
CMD ["node", "dist/index.js"]
