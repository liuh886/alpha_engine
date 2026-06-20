#!/bin/sh
set -eu

fail() {
    printf 'alpha-engine startup error: %s\n' "$1" >&2
    exit 64
}

[ "${ALPHA_ENGINE_ENV:-}" = "production" ] || \
    fail "ALPHA_ENGINE_ENV must be production in the release container"

# ---- Credential validation ----
for name in TRADING_UI_USER TRADING_UI_PASSWORD ALPHA_DEVELOPER_TOKEN; do
    value="$(printenv "$name" 2>/dev/null || true)"
    [ -n "$value" ] || fail "$name is required"

    case "$value" in
        your-password-here|your-developer-token-here|change-me|changeme)
            fail "$name still contains a placeholder value"
            ;;
    esac
done

# ---- Static asset validation ----
[ -s /app/qlib-dashboard/dist/index.html ] || \
    fail "built dashboard is missing at qlib-dashboard/dist/index.html"

# ---- Directory validation ----
for directory in /app/data /app/artifacts /app/mlruns /app/reports /app/configs; do
    [ -d "$directory" ] || fail "required runtime directory is missing: $directory"
    [ -w "$directory" ] || fail "runtime directory is not writable by uid $(id -u): $directory"
done

# ---- Configs volume initialisation ----
# When the configs volume is first mounted it will be empty.  Copy the
# baked-in defaults so the application has something to work with.
config_marker="/app/configs/.volume_initialised"
if [ ! -f "$config_marker" ]; then
    # /app/configs.bak holds the files COPYed during the Docker build.
    if [ -d /app/configs.bak ] && [ "$(ls -A /app/configs.bak 2>/dev/null)" ]; then
        printf 'Initialising configs volume from baked-in defaults ...\n'
        cp -a /app/configs.bak/. /app/configs/
        touch "$config_marker"
        printf 'Configs volume initialised.\n'
    fi
fi

# ---- Snapshot integrity (non-blocking warning) ----
# If a metadata DB exists, verify it is a valid SQLite file.  A corrupt DB
# should not block startup -- the readiness probe will catch it -- but we
# warn early so operators see it in container logs.
metadata_db="/app/artifacts/metadata/metadata.db"
if [ -f "$metadata_db" ]; then
    if ! python -c "import sqlite3; sqlite3.connect('$metadata_db').execute('SELECT 1')" 2>/dev/null; then
        printf 'WARNING: metadata DB at %s may be corrupt -- readiness probe will fail.\n' "$metadata_db" >&2
    fi
fi

exec "$@"
