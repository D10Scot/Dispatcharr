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

# Add timestamp argument
ARG TIMESTAMP

# Update version.py with build timestamp if provided
RUN if [ -n "$TIMESTAMP" ]; then \
    echo "Updating timestamp to ${TIMESTAMP} in version.py" && \
    sed -i "s|__timestamp__ = None.*|__timestamp__ = '${TIMESTAMP}'    # Set during CI/CD build process|" /app/version.py && \
    cat /app/version.py; \
    fi

# No static `USER` here: the container starts as root by design so
# entrypoint.sh can create a user at the PUID/PGID the operator supplies (NAS
# self-hosting convention, same as linuxserver.io images) and chown bind
# mounts before dropping to it — Django/Celery/nginx/etc. all end up running
# as that non-root user. A static USER would break PUID/PGID entirely.
# Covered by docker/tests/test-puid-pgid.sh.
ENTRYPOINT ["/app/docker/entrypoint.sh"]