# Define base image build arguments (must be before any FROM)
ARG REPO_OWNER=dispatcharr
ARG REPO_NAME=dispatcharr
ARG BASE_TAG=base
# CI resolves the tag above to a digest before build (see docker-build.yml /
# release.yml) and overrides this with e.g. ghcr.io/<owner>/<repo>@sha256:...,
# so every arch in a multi-arch build and every re-run of the same commit
# compiles against the exact same base layer, not whatever ":base" happens to
# point to at pull time. The tag-based default below is a floating reference,
# kept only so a manual `docker build` without CI's resolve step still works.
ARG BASE_IMAGE=ghcr.io/${REPO_OWNER}/${REPO_NAME}:${BASE_TAG}

# --- Build frontend ---

FROM node:24@sha256:934240a162082fd8b8a2f90cd5114446443f1eba1c5378f6687167ca405e6584 AS frontend-builder

WORKDIR /app/frontend
COPY ./frontend /app/frontend
# npm ci installs exactly the committed lockfile and removes any node_modules
# itself, so the image is built from the dependency set CI tested.
RUN npm ci --no-audit --progress=false
RUN    npm run build && \
    rm -rf node_modules .cache

# --- Build the Go relay ---

# --platform=$BUILDPLATFORM with an explicit GOARCH, not a plain FROM.
# docker-build.yml builds linux/amd64 and linux/arm64 in one buildx
# invocation; a plain FROM would run the arm64 leg's compilation under QEMU
# emulation, minutes per build, for a binary Go cross-compiles natively in
# about a second.
FROM --platform=$BUILDPLATFORM golang:1.27.1-trixie@sha256:9baa6b4187bbb98d240372a8a235ac0bb6b5ddd52bba1431dc2f7c0705862728 AS relay-builder

ARG TARGETOS
ARG TARGETARCH

WORKDIR /src
# One COPY, deliberately. The usual "copy go.mod first, download, then copy
# the source" split exists to cache `go mod download` across source changes;
# a stdlib-only module downloads nothing, so the split would add a layer
# that caches an empty step and a comment claiming a benefit it does not
# deliver. Reinstate it in the same commit as the first dependency, if there
# ever is one.
COPY ./relay ./

# CGO_ENABLED=0 makes the binary static, so it runs on the final image
# whatever its libc. -trimpath keeps build paths out of the binary;
# -s -w drop the symbol and DWARF tables.
RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags="-s -w" -o /out/relay-go .

# --- Redeclare build arguments for the next stage ---
ARG BASE_IMAGE

# --- Final image based on the dynamic (CI-pinned) base ---
FROM ${BASE_IMAGE} AS final
ENV VIRTUAL_ENV=/dispatcharrpy
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

# Copy application code
COPY . /app
# Copy nginx configuration
COPY ./docker/nginx.conf /etc/nginx/sites-enabled/default
COPY ./docker/dispatcharr_api_params.conf /etc/nginx/dispatcharr_api_params.conf
COPY ./docker/dispatcharr_api_params_proxy.conf /etc/nginx/dispatcharr_api_params_proxy.conf
# Fix line endings and make entrypoint scripts executable
RUN for f in /app/docker/entrypoint*.sh; do \
    if [ -f "$f" ]; then \
    sed -i 's/\r$//' "$f" && chmod +x "$f"; \
    fi; \
    done
# Clean out existing frontend folder
RUN rm -rf /app/frontend
# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# The Go relay binary. /usr/local/bin so docker/supervisord.d/relay-go.conf
# can name it without a path prefix.
COPY --from=relay-builder /out/relay-go /usr/local/bin/relay-go

# Add timestamp argument
ARG TIMESTAMP

# Update version.py with build timestamp if provided
RUN if [ -n "$TIMESTAMP" ]; then \
    echo "Updating timestamp to ${TIMESTAMP} in version.py" && \
    sed -i "s|__timestamp__ = None.*|__timestamp__ = '${TIMESTAMP}'    # Set during CI/CD build process|" /app/version.py && \
    cat /app/version.py; \
    fi

# The container health probe (spec D6). Role-aware, because this image runs
# four different program sets and only three of the rungs start relay-go;
# docker/healthcheck.sh exits 0 for the roles that do not have one.
#
# interval/timeout/retries are sized against relay-go's own supervisord
# settings: startsecs=5 and startretries=20, so start-period=30s covers a
# cold start plus a couple of restarts, and 3 retries at 15s means a genuinely
# dead relay is reported unhealthy inside a minute.
# Exec form, not shell form: hadolint's DL3025 warns on the latter, and the
# repo's Dockerfiles are at zero hadolint findings.
#
# AND IT NAMES THE INTERPRETER RATHER THAN RELYING ON THE SCRIPT'S MODE BIT.
# Exec form does not go through a shell, so `CMD ["/app/docker/healthcheck.sh"]`
# needs the file to be executable: at 0644 every probe fails with
# `permission denied` and the container reports `unhealthy` for ever, with
# nothing in the build or the test suite saying so -- hadolint is clean either
# way and no Go or Python test reads this file. The script IS committed 0755
# (`git ls-files -s docker/healthcheck.sh`), and this form means a mode bit
# lost to a patch that does not carry modes, an editor, or a file written by
# hand cannot silently disable the probe. Belt and braces, deliberately: the
# mode is the intent and the interpreter is the guarantee.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["/bin/sh", "/app/docker/healthcheck.sh"]

# No static `USER` here: the container starts as root by design so
# entrypoint.sh can create a user at the PUID/PGID the operator supplies (NAS
# self-hosting convention, same as linuxserver.io images) and chown bind
# mounts before dropping to it — Django/Celery/nginx/etc. all end up running
# as that non-root user. A static USER would break PUID/PGID entirely.
# Covered by docker/tests/test-puid-pgid.sh.
ENTRYPOINT ["/app/docker/entrypoint.sh"]