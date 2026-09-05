#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

# Function to echo with timestamp
echo_with_timestamp() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Set PostgreSQL environment variables
export POSTGRES_DB=${POSTGRES_DB:-dispatcharr}
export POSTGRES_USER=${POSTGRES_USER:-dispatch}
# AIO mode: default to 'secret' for internal DB.
# Modular mode + TLS: no default — cert-only auth (mTLS) uses no password.
# Modular mode + no TLS: preserve 'secret' default for backward compatibility.
if [[ "${DISPATCHARR_ENV:-}" == "modular" && "${POSTGRES_SSL:-}" == "true" ]]; then
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
else
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-secret}"
fi
export DISPATCHARR_ENV=${DISPATCHARR_ENV:-aio}

# DISPATCHARR_ROLE selects which supervisord programs this container runs.
# It is orthogonal to DISPATCHARR_ENV, which answers where Postgres and
# Redis run — but the impossible pairings are rejected rather than left to
# fail later as a FATAL program or a five-minute wait loop:
#   * role all runs its own Postgres and Redis, so it cannot be modular;
#   * roles api, relay and worker have neither, so they cannot be anything
#     else. A non-modular worker would sit in the migrate --check loop
#     below until MIG_TIMEOUT against a database nothing was going to
#     start.
# Every deployment that predates this variable sets only DISPATCHARR_ENV,
# so the default is derived from it: modular means api, anything else means
# all. Without that derivation an existing modular web container would load
# all.conf and its [program:postgres] would fail against an uninitialised
# /data/db forever.
if [ -z "${DISPATCHARR_ROLE:-}" ]; then
    if [ "$DISPATCHARR_ENV" = "modular" ]; then
        DISPATCHARR_ROLE=api
    else
        DISPATCHARR_ROLE=all
    fi
fi
export DISPATCHARR_ROLE
case "$DISPATCHARR_ROLE" in
    all|api|relay|worker) ;;
    *)
        echo ""
        echo "================================================================"
        echo "ERROR: DISPATCHARR_ROLE must be one of: all, api, relay, worker."
        echo "  DISPATCHARR_ROLE=$DISPATCHARR_ROLE"
        echo "================================================================"
        echo ""
        exit 1
        ;;
esac
if [ "$DISPATCHARR_ROLE" = "all" ] && [ "$DISPATCHARR_ENV" = "modular" ]; then
    echo ""
    echo "================================================================"
    echo "ERROR: DISPATCHARR_ROLE=all runs its own PostgreSQL and Redis and"
    echo "  cannot be combined with DISPATCHARR_ENV=modular."
    echo "  Use DISPATCHARR_ROLE=api (the default in modular mode)."
    echo "================================================================"
    echo ""
    exit 1
fi
case "$DISPATCHARR_ROLE" in
    api|relay|worker)
        if [ "$DISPATCHARR_ENV" != "modular" ]; then
            echo ""
            echo "================================================================"
            echo "ERROR: DISPATCHARR_ROLE=$DISPATCHARR_ROLE expects external"
            echo "  PostgreSQL and Redis, and therefore DISPATCHARR_ENV=modular."
            echo "  DISPATCHARR_ENV=$DISPATCHARR_ENV"
            echo "  Use DISPATCHARR_ROLE=all for a self-contained container."
            echo "================================================================"
            echo ""
            exit 1
        fi
        ;;
esac
echo "🎛️  DISPATCHARR_ROLE=$DISPATCHARR_ROLE (DISPATCHARR_ENV=$DISPATCHARR_ENV)"

if [[ "$DISPATCHARR_ENV" == "aio" ]]; then
    # Use Unix socket for loopback values (unset, localhost, 127.0.0.1)
    if [[ -z "$POSTGRES_HOST" || "$POSTGRES_HOST" == "localhost" || "$POSTGRES_HOST" == "127.0.0.1" ]]; then
        export POSTGRES_HOST=/var/run/postgresql
    fi
else
    export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
fi
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export PG_VERSION=$(ls /usr/lib/postgresql/ | sort -V | tail -n 1)
export PG_BINDIR="/usr/lib/postgresql/${PG_VERSION}/bin"
export REDIS_HOST=${REDIS_HOST:-localhost}
export REDIS_PORT=${REDIS_PORT:-6379}
export REDIS_DB=${REDIS_DB:-0}
export REDIS_PASSWORD=${REDIS_PASSWORD:-}
export REDIS_USER=${REDIS_USER:-}
export DISPATCHARR_PORT=${DISPATCHARR_PORT:-9191}
export LIBVA_DRIVERS_PATH='/usr/local/lib/x86_64-linux-gnu/dri'
export LD_LIBRARY_PATH='/usr/local/lib'
export SECRET_FILE="/data/jwt"

if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
    # Ensure Django secret key exists or generate a new one
    if [ ! -f "$SECRET_FILE" ]; then
      echo "Generating new Django secret key..."
      old_umask=$(umask)
      umask 077
      tmpfile="$(mktemp "${SECRET_FILE}.XXXXXX")" || { echo "mktemp failed"; exit 1; }
      python3 - <<'PY' >"$tmpfile" || { echo "secret generation failed"; rm -f "$tmpfile"; exit 1; }
import secrets
print(secrets.token_urlsafe(64))
PY
      mv -f "$tmpfile" "$SECRET_FILE" || { echo "move failed"; rm -f "$tmpfile"; exit 1; }
      umask $old_umask
    fi
else
    # relay and worker never generate the key: they mount the same /data
    # volume as the all/api container, and two roles racing to create
    # /data/jwt on first boot would leave one writer's key overwritten and
    # every internal HMAC comparison 403ing. Lifted from the deleted
    # docker/entrypoint.celery.sh:12-24.
    echo 'Waiting for Django secret key...'
    JWT_TIMEOUT=120
    JWT_WAITED=0
    while [ ! -f "$SECRET_FILE" ]; do
        if [ "$JWT_WAITED" -ge "$JWT_TIMEOUT" ]; then
            echo "❌ ERROR: Timed out waiting for ${SECRET_FILE} after ${JWT_TIMEOUT}s."
            echo "   Is the api/all container running? Does it have the /data volume mounted?"
            exit 1
        fi
        sleep 1
        JWT_WAITED=$((JWT_WAITED + 1))
    done
fi
export DJANGO_SECRET_KEY="$(tr -d '\r\n' < "$SECRET_FILE")"

# Process priority configuration
# UWSGI_NICE_LEVEL: Absolute nice value for uWSGI/streaming (default: 0 = normal priority)
# CELERY_NICE_LEVEL: Absolute nice value for Celery/background tasks (default: 5 = low priority)
# Both are absolute now. Before supervisord, Celery was an attach-daemon of
# an already-niced uWSGI, so the entrypoint subtracted UWSGI_NICE_LEVEL to
# reach the intended absolute value. Under supervisord every program is a
# direct child of supervisord at nice 0, so the subtraction would land
# Celery at the wrong priority at any non-zero UWSGI_NICE_LEVEL.
# Negative values still need cap_add: SYS_NICE, which is why the programs
# run `nice` as root and drop privileges afterwards with setpriv rather
# than using supervisord's own user=.
export UWSGI_NICE_LEVEL=${UWSGI_NICE_LEVEL:-0}
export CELERY_NICE_LEVEL=${CELERY_NICE_LEVEL:-5}

# Who Celery runs as, and how loudly — both per role, both preserving what
# the deployment did before supervisord.
#   * AIO's Celery was an attach-daemon of a uWSGI started under `su -`,
#     so it ran as $POSTGRES_USER, and it carried no -l, so celery's own
#     default of WARNING applied.
#   * entrypoint.celery.sh never used `su -`, so modular Celery ran as
#     root, and it passed -l info on all three commands.
# Dropping the worker to $POSTGRES_USER needs a one-time recursive chown of
# /data/recordings, /data/m3us, /data/epgs, /data/uploads and /data/plugins
# — 03-init-dispatcharr.sh's chown is non-recursive — so it is a follow-up,
# not this PR.
if [ "$DISPATCHARR_ROLE" = "worker" ]; then
    export DISPATCHARR_CELERY_USER="${DISPATCHARR_CELERY_USER:-root}"
    export CELERY_LOG_LEVEL="${CELERY_LOG_LEVEL:-info}"
else
    export DISPATCHARR_CELERY_USER="${DISPATCHARR_CELERY_USER:-$POSTGRES_USER}"
    export CELERY_LOG_LEVEL="${CELERY_LOG_LEVEL:-warning}"
fi

# Set LIBVA_DRIVER_NAME if user has specified it
if [ -v LIBVA_DRIVER_NAME ]; then
    export LIBVA_DRIVER_NAME
fi
# Extract version information from version.py
export DISPATCHARR_VERSION=$(python -c "import sys; sys.path.append('/app'); import version; print(version.__version__)")
export DISPATCHARR_TIMESTAMP=$(python -c "import sys; sys.path.append('/app'); import version; print(version.__timestamp__ or '')")

# Display version information with timestamp if available
if [ -n "$DISPATCHARR_TIMESTAMP" ]; then
    echo "📦 Dispatcharr version: ${DISPATCHARR_VERSION} (build: ${DISPATCHARR_TIMESTAMP})"
else
    echo "📦 Dispatcharr version: ${DISPATCHARR_VERSION}"
fi
export DISPATCHARR_LOG_LEVEL
# Set log level with default if not provided
DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL:-INFO}
# Convert to uppercase
DISPATCHARR_LOG_LEVEL=${DISPATCHARR_LOG_LEVEL^^}


echo "Environment DISPATCHARR_LOG_LEVEL set to: '${DISPATCHARR_LOG_LEVEL}'"

# Select the uwsgi ini that [program:api-uwsgi] will load, and the extra
# args that go with it. Unconditional, in every role: an unset %(ENV_x)s is
# a hard supervisord config error, not an empty expansion, and it is
# cheaper to always export these two than to reason about which rungs
# include api-uwsgi. Same ladder, same order, as the pre-supervisord
# entrypoint used at :332-353.
if [ "$DISPATCHARR_ENV" = "dev" ] && [ "$DISPATCHARR_DEBUG" != "true" ]; then
    export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.dev.ini"
elif [ "$DISPATCHARR_DEBUG" = "true" ]; then
    export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.debug.ini"
elif [ "$DISPATCHARR_ENV" = "modular" ]; then
    export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.modular.ini"
else
    export DISPATCHARR_UWSGI_INI="/app/docker/uwsgi.ini"
fi
# uWSGI's own per-request access log, independent of Django's logging.
# Suppressed outside debug mode; debug.ini needs it to see request timing
# while attached. api-uwsgi.conf is one file shared by every rung that runs
# it, so the flag travels as an env var rather than being baked in.
if [ "$DISPATCHARR_DEBUG" != "true" ]; then
    export DISPATCHARR_UWSGI_EXTRA_ARGS="--disable-logging"
else
    export DISPATCHARR_UWSGI_EXTRA_ARGS=""
fi

# uWSGI's own $(VAR) expansion reads these from its process environment
# (not %(ENV_x)s — that is supervisord's own syntax, irrelevant to what
# the uwsgi binary itself expands). Exported unconditionally, in every
# role, for the same reason DISPATCHARR_UWSGI_INI is: an unset $(VAR) in
# an ini uWSGI does not even load is harmless, but a role that does load
# it (relay-uwsgi reads DISPATCHARR_RELAY_GEVENT; api-uwsgi reads the
# other two) must never see an empty expansion.
export DISPATCHARR_API_HARAKIRI=${DISPATCHARR_API_HARAKIRI:-120}
export DISPATCHARR_API_MAX_REQUESTS=${DISPATCHARR_API_MAX_REQUESTS:-5000}
export DISPATCHARR_RELAY_GEVENT=${DISPATCHARR_RELAY_GEVENT:-1600}

# Translate Dispatcharr POSTGRES_SSL_* env vars into libpq-recognized PGSSL*
# env vars. Called once before any external PostgreSQL connection; all child
# processes (psql, pg_dump, pg_isready, createdb, dropdb) inherit these
# automatically. No-op when POSTGRES_SSL is not "true".
setup_pg_ssl_env() {
    if [ "${POSTGRES_SSL:-false}" != "true" ]; then
        return 0
    fi
    export PGSSLMODE="${POSTGRES_SSL_MODE:-verify-full}"
    if [ -n "${POSTGRES_SSL_CA_CERT:-}" ]; then export PGSSLROOTCERT="$POSTGRES_SSL_CA_CERT"; fi
    if [ -n "${POSTGRES_SSL_CERT:-}" ];    then export PGSSLCERT="$POSTGRES_SSL_CERT"; fi
    if [ -n "${POSTGRES_SSL_KEY:-}" ];     then export PGSSLKEY="$POSTGRES_SSL_KEY"; fi
}

# READ-ONLY - don't let users change these
export POSTGRES_DIR=/data/db

# Run init scripts. User setup runs before the environment files are
# written, so DISPATCHARR_HOME can be read back from the passwd database
# this script has just reconciled with PUID/PGID.
echo "Starting user setup..."
. /app/docker/init/01-user-setup.sh

# supervisord gives a child no login shell, so nothing sets HOME and USER
# the way `su -` did: without these, every non-root program would inherit
# HOME=/root and fail or litter (npm's cache, Celery's, psql's history).
# Read from getent rather than assumed, because 01-user-setup.sh may have
# renamed a pre-existing account at this PUID rather than creating one.
_dispatcharr_home=$(getent passwd "$POSTGRES_USER" | cut -d: -f6)
export DISPATCHARR_HOME="${_dispatcharr_home:-/home/$POSTGRES_USER}"
_dispatcharr_celery_home=$(getent passwd "$DISPATCHARR_CELERY_USER" | cut -d: -f6)
export DISPATCHARR_CELERY_HOME="${_dispatcharr_celery_home:-$DISPATCHARR_HOME}"
unset _dispatcharr_home _dispatcharr_celery_home

# Global variables, stored so other users inherit them.
# Rewritten every startup so that container restarts with changed env vars
# pick up the new values (not stale ones from a previous run).
# Define all variables to process
variables=(
    PATH VIRTUAL_ENV DJANGO_SETTINGS_MODULE PYTHONUNBUFFERED PYTHONDONTWRITEBYTECODE
    POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT
    DISPATCHARR_ENV DISPATCHARR_ROLE DISPATCHARR_DEBUG DISPATCHARR_LOG_LEVEL DISPATCHARR_ENABLE_IP_LOOKUP
    REDIS_HOST REDIS_PORT REDIS_DB REDIS_PASSWORD REDIS_USER POSTGRES_DIR DISPATCHARR_PORT
    DISPATCHARR_VERSION DISPATCHARR_TIMESTAMP LIBVA_DRIVERS_PATH LIBVA_DRIVER_NAME LD_LIBRARY_PATH
    CELERY_NICE_LEVEL UWSGI_NICE_LEVEL DJANGO_SECRET_KEY
    PG_BINDIR DISPATCHARR_HOME DISPATCHARR_CELERY_USER DISPATCHARR_CELERY_HOME CELERY_LOG_LEVEL
    DISPATCHARR_UWSGI_INI DISPATCHARR_UWSGI_EXTRA_ARGS
    DISPATCHARR_API_HARAKIRI DISPATCHARR_API_MAX_REQUESTS DISPATCHARR_RELAY_GEVENT
)

# Optional variables, only propagate when set to avoid noisy warnings
for _opt_var in POSTGRES_SSL POSTGRES_SSL_MODE POSTGRES_SSL_CA_CERT POSTGRES_SSL_CERT POSTGRES_SSL_KEY \
                REDIS_SSL REDIS_SSL_VERIFY REDIS_SSL_CA_CERT REDIS_SSL_CERT REDIS_SSL_KEY \
                DISPATCHARR_SETUP_ALLOWED_IP DISPATCHARR_TRUSTED_PROXIES; do
    if [ -n "${!_opt_var+x}" ]; then
        variables+=("$_opt_var")
    fi
done

# Truncate files before rewriting
> /etc/profile.d/dispatcharr.sh

# Process each variable for both profile.d and environment
for var in "${variables[@]}"; do
    # Check if the variable is set in the environment
    if [ -n "${!var+x}" ]; then
        # Add to profile.d (quoted to handle special characters in values)
        echo "export ${var}='${!var}'" >> /etc/profile.d/dispatcharr.sh
        # Add/update in /etc/environment
        sed -i "/^${var}=/d" /etc/environment
        echo "${var}='${!var}'" >> /etc/environment
    else
        echo "Warning: Environment variable $var is not set"
    fi
done

chmod +x /etc/profile.d/dispatcharr.sh

# Ensure root's .bashrc sources the profile.d scripts for interactive non-login shells
if ! grep -q "profile.d/dispatcharr.sh" /root/.bashrc 2>/dev/null; then
    cat >> /root/.bashrc << 'EOF'

# Source Dispatcharr environment variables
if [ -f /etc/profile.d/dispatcharr.sh ]; then
    . /etc/profile.d/dispatcharr.sh
fi
EOF
fi

# Fix TLS client key permissions/ownership BEFORE any external PG connections.
# Must run after 01-user-setup.sh (user exists for chown) and before
# 02-postgres.sh / pg_isready (which make the first external PG connections).
# The destination is per-role because api, relay and worker containers share
# one /data volume from PR 4 on, and a single fixed path would have three
# writers racing on it. The file is a per-boot scratch copy, never read
# across boots, so renaming it costs nothing.
FIXED_KEY_PATH="/data/.pg-client-${DISPATCHARR_ROLE}.key"
. /app/docker/init/00-fix-pg-ssl-key.sh
# Propagate the fixed path to login shells (su - strips env vars)
if [ "${POSTGRES_SSL_KEY:-}" = "$FIXED_KEY_PATH" ]; then
    sed -i "/^POSTGRES_SSL_KEY=/d" /etc/environment
    echo "POSTGRES_SSL_KEY='$FIXED_KEY_PATH'" >> /etc/environment
    sed -i "s|export POSTGRES_SSL_KEY=.*|export POSTGRES_SSL_KEY='$FIXED_KEY_PATH'|" /etc/profile.d/dispatcharr.sh
fi

# Export libpq TLS env vars so all subsequent psql/pg_dump/pg_isready calls
# (in 02-postgres.sh, modular-mode checks, etc.) use TLS automatically.
setup_pg_ssl_env

if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
    # Initialize PostgreSQL (script handles modular vs internal mode
    # internally, and defines promote_app_role, ensure_app_database,
    # ensure_utf8_encoding, check_external_postgres_version and
    # prepare_pg_socket_dir, all used below).
    echo "Setting up PostgreSQL..."
    . /app/docker/init/02-postgres.sh
fi

echo "Starting init process..."
. /app/docker/init/03-init-dispatcharr.sh

# --- NumPy version switching for legacy hardware ---
# Outside the role gate: docker-compose.yml documents USE_LEGACY_NUMPY on
# the celery service as well as the web one, and entrypoint.celery.sh ran
# this same block. A worker on a pre-2009 CPU needs the swap as much as the
# API does.
if [ "$USE_LEGACY_NUMPY" = "true" ]; then
    # Check if NumPy was compiled with baseline support
    if "$VIRTUAL_ENV/bin/python" -c "import numpy; numpy.show_config()" 2>&1 | grep -qi "baseline" || [ $? -ne 0 ]; then
        echo_with_timestamp "🔧 Switching to legacy NumPy (no CPU baseline)..."
        uv pip install --python "$VIRTUAL_ENV/bin/python" --no-cache --force-reinstall --no-deps /opt/numpy-*.whl
        echo_with_timestamp "✅ Legacy NumPy installed"
    else
        echo_with_timestamp "✅ Legacy NumPy (no baseline) already installed, skipping reinstallation"
    fi
fi

if [[ "$DISPATCHARR_ROLE" == "all" ]]; then
    # Start PostgreSQL exactly as before. supervisord's [program:postgres]
    # takes it over after the one-shot work; see the fast stop below.
    echo "Starting Postgres..."
    prepare_pg_socket_dir
    su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
    # Wait for PostgreSQL to be ready
    until su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
        echo_with_timestamp "Waiting for PostgreSQL to be ready..."
        sleep 1
    done
    echo "✅ Postgres is ready"

    # Unconditional startup guarantees — run on every AIO startup.
    # Each is idempotent and handles all scenarios (fresh, upgrade, restart).
    promote_app_role
    ensure_app_database
elif [[ "$DISPATCHARR_ROLE" == "api" ]]; then
    echo "🔗 Modular mode: Using external PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}"
    # Wait for external PostgreSQL to be ready using pg_isready (checks actual protocol readiness)
    echo_with_timestamp "Waiting for external PostgreSQL to be ready..."
    until $PG_BINDIR/pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -q >/dev/null 2>&1; do
        echo_with_timestamp "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
        sleep 1
    done
    echo "✅ External PostgreSQL is ready"

    # Check PostgreSQL version compatibility
    check_external_postgres_version || exit 1

    # Wait for external Redis so a misconfigured host fails here with a
    # clear message rather than inside a supervisord program's retry loop.
    # wait_for_redis.py is wait-only after D15 — it must not, and does not,
    # flush: a modular web restart cannot be allowed to wipe a running
    # relay's keys. [program:api-uwsgi] waits again through
    # wait-for-stores.sh, which is what actually gates the process.
    echo "🔗 Modular mode: Using external Redis at ${REDIS_HOST}:${REDIS_PORT}"
    echo_with_timestamp "Waiting for Redis to be ready..."
    python3 /app/scripts/wait_for_redis.py
    echo "✅ Redis is ready"
fi

if [[ "$DISPATCHARR_ROLE" == "all" || "$DISPATCHARR_ROLE" == "api" ]]; then
    # Ensure database encoding is UTF8 (handles both internal and external databases)
    ensure_utf8_encoding

    # Development container setup: node, npm install, uv sync, and debugpy
    # when DISPATCHARR_DEBUG=true. Runs as root, before migrate, because
    # `uv sync` inside it can change the venv the migration then runs from,
    # and because [program:vite] starts as soon as supervisord does — a
    # container without node would crash-loop it.
    if [[ "$DISPATCHARR_ENV" == "dev" ]]; then
        . /app/docker/init/99-init-dev.sh
    fi

    # Run Django commands as non-root user to prevent permission issues
    su - "$POSTGRES_USER" -c "cd /app && python manage.py migrate --noinput"
    su - "$POSTGRES_USER" -c "cd /app && python manage.py collectstatic --noinput"
elif [[ "$DISPATCHARR_ROLE" == "relay" || "$DISPATCHARR_ROLE" == "worker" ]]; then
    # Wait for migrations to complete. 'migrate --check' exits 0 only when
    # every migration is applied, and exits 1 on either an unapplied
    # migration or a connection error (safe either way). Lifted from the
    # deleted docker/entrypoint.celery.sh:43-58, including running as root
    # rather than through `su -`, so the worker role does exactly what its
    # own entrypoint did.
    MIG_TIMEOUT=300
    MIG_WAITED=0
    echo 'Waiting for migrations to complete...'
    until (cd /app && python manage.py migrate --check) >/dev/null 2>&1; do
        if [ "$MIG_WAITED" -ge "$MIG_TIMEOUT" ]; then
            echo "❌ ERROR: Timed out waiting for migrations after ${MIG_TIMEOUT}s."
            echo "   Check the api/all container logs for migration errors."
            exit 1
        fi
        echo_with_timestamp 'Migrations not ready yet, waiting...'
        sleep 2
        MIG_WAITED=$((MIG_WAITED + 2))
    done
    echo "✅ Migrations complete."
    if [ "$DISPATCHARR_ROLE" = "worker" ]; then
        # Wording preserved verbatim from entrypoint.celery.sh:61 —
        # docker/tests/test-tls-postgres.sh waits on this exact substring.
        echo 'Migrations complete, starting Celery...'
    fi
fi

# Hardware acceleration is a diagnostic (lspci, ffmpeg -hwaccels, vainfo;
# nothing exported downstream) about whether *this* process can reach a
# GPU. Before this PR that was always the all/api process; from this PR on,
# apps/proxy/live_proxy/'s ffmpeg spawning runs in the relay process's
# request path (docker/nginx.conf routes stream tunes there), so relay
# needs the same report. worker runs no ffmpeg and stays excluded.
# This reverses the note PR 3 added to the spec's PR 4 section, which
# recorded the gap as a deliberate PR 4 decision -- PR 4 decides the
# other way (spec amendment S2).
if [[ "$DISPATCHARR_ROLE" != "worker" ]]; then
    echo "🔍 Running hardware acceleration check..."
    . /app/docker/init/04-check-hwaccel.sh
fi

if [[ "$DISPATCHARR_ROLE" == "all" ]]; then
    # Hand PostgreSQL over to supervisord. Without this stop,
    # [program:postgres] starts a second postmaster against a data
    # directory whose postmaster.pid belongs to this script's instance; it
    # fails, retries and lands in FATAL, leaving the container running on
    # an orphaned, unsupervised postmaster. -w so supervisord's own start
    # cannot race the shutdown. -m fast, not -m immediate: this script is
    # no longer racing an 8-second ceiling.
    echo "Handing PostgreSQL over to supervisord (fast stop)..."
    su - "$POSTGRES_USER" -c "$PG_BINDIR/pg_ctl -D ${POSTGRES_DIR} stop -m fast -w"
    echo "✅ Postgres stopped; supervisord will start it as [program:postgres]"
fi

# Select the supervisord config. Two inputs, not three: DISPATCHARR_DEBUG
# chooses only the uwsgi ini (above), because docker-compose.debug.yml sets
# DISPATCHARR_ENV=dev as well as DISPATCHARR_DEBUG=true and the
# pre-supervisord entrypoint keyed its vite-instead-of-nginx branch on
# DISPATCHARR_ENV=dev alone. A debug rung with nginx and no vite would not
# match what debug does today.
if [ "$DISPATCHARR_ENV" = "dev" ]; then
    SUPERVISORD_CONF="/app/docker/supervisord/all-dev.conf"
else
    SUPERVISORD_CONF="/app/docker/supervisord/${DISPATCHARR_ROLE}.conf"
fi

echo "🚀 Starting supervisord ($DISPATCHARR_ROLE) with $SUPERVISORD_CONF"
exec supervisord -n -c "$SUPERVISORD_CONF"
