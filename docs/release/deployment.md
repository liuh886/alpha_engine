# Container Deployment

This deployment path packages the authenticated FastAPI API and the React UI in
one image. The frontend is rebuilt from `qlib-dashboard/package-lock.json` in a
Node 20 stage; local `dist`, data, reports, MLflow state, caches, and secrets are
excluded from the build context. The runtime uses the Python 3.10 line used by
CI and installs production dependencies from `uv.lock`.

## Required Configuration

Set these values in the invoking shell or an external secret manager before
running Compose. Do not bake them into the image or commit them to the repo.

```text
TRADING_UI_USER
TRADING_UI_PASSWORD
ALPHA_DEVELOPER_TOKEN
```

Compose rejects missing values during interpolation. The container entrypoint
also rejects missing or placeholder values, a non-production environment, a
missing UI build, or unwritable persistent paths. `.env` may be used locally by
Compose for interpolation, but `.dockerignore` prevents it entering the image.

## Build And Start

```powershell
$env:TRADING_UI_USER = "operator"
$env:TRADING_UI_PASSWORD = Read-Host "Dashboard password"
$env:ALPHA_DEVELOPER_TOKEN = Read-Host "MCP token"

docker compose build --pull api
docker compose up -d --no-build api
docker compose ps
```

The default host binding is `127.0.0.1:8000`. The process listens on
`0.0.0.0:8000` only inside the container so Docker port forwarding works.

For a trusted LAN, explicitly set `ALPHA_ENGINE_BIND_ADDRESS=0.0.0.0`, restrict
the host firewall to the intended subnet, and use a TLS reverse proxy. Do not
publish this single-user Basic Auth service directly to the public internet.
Set `CORS_ORIGINS` to the exact externally visible origins when using a proxy.

## Health And Smoke Checks

The image health check verifies both `/api/public/health` and the built UI at
`/`. Compose reports the service healthy only after both respond successfully.

```powershell
curl.exe --fail http://127.0.0.1:8000/api/public/health
curl.exe --fail http://127.0.0.1:8000/
curl.exe --fail --user "$env:TRADING_UI_USER`:$env:TRADING_UI_PASSWORD" `
  http://127.0.0.1:8000/api/system/me
docker inspect --format "{{.State.Health.Status}}" (docker compose ps -q api)
```

To prove startup fails closed, run the image without credentials. It must exit
with code 64 and name the first missing variable:

```powershell
docker run --rm alpha-engine:local
```

## Persistent State

Compose uses named volumes instead of host repository bind mounts:

| Volume | Container path | Purpose |
|---|---|---|
| `alpha-engine-data` | `/app/data` | Qlib and source market data |
| `alpha-engine-artifacts` | `/app/artifacts` | metadata, models, runs, evidence |
| `alpha-engine-mlruns` | `/app/mlruns` | legacy/root MLflow state |
| `alpha-engine-reports` | `/app/reports` | generated reports |
| `alpha-engine-configs` | `/app/configs` | mutable runtime configuration |

Set `ALPHA_ENGINE_VOLUME_PREFIX` before first startup to use a different volume
set. The root filesystem is read-only; `/tmp` is a bounded tmpfs; Linux
capabilities are dropped and the process runs as uid/gid `10001`.

Persistence smoke test:

```powershell
docker compose exec api sh -c 'date -u > /app/artifacts/.persistence-smoke'
docker compose restart api
docker compose exec api test -s /app/artifacts/.persistence-smoke
docker compose exec api rm /app/artifacts/.persistence-smoke
```

## Backup And Restore

Stop writes before taking a consistent backup. Store the archive outside the
repository and protect it as sensitive research data.

```powershell
docker compose stop api
New-Item -ItemType Directory -Force backups | Out-Null
$backup = (Resolve-Path backups).Path

foreach ($name in @("data", "artifacts", "mlruns", "reports", "configs")) {
  docker run --rm `
    --mount "type=volume,src=alpha-engine-$name,dst=/source,readonly" `
    --mount "type=bind,src=$backup,dst=/backup" `
    alpine:3.22 tar -C /source -czf "/backup/$name.tgz" .
}
docker compose start api
```

Restore only while the service is stopped. The command below replaces a volume,
so verify the backup path and volume name first.

```powershell
docker compose stop api
$backup = (Resolve-Path backups).Path

foreach ($name in @("data", "artifacts", "mlruns", "reports", "configs")) {
  docker run --rm `
    --mount "type=volume,src=alpha-engine-$name,dst=/target" `
    --mount "type=bind,src=$backup,dst=/backup,readonly" `
    alpine:3.22 sh -c "find /target -mindepth 1 -delete; tar -C /target -xzf /backup/$name.tgz"
}
docker compose start api
```

Repeat the health, authenticated API, and persistence checks after restore.

## Upgrade, Migration, And Rollback

Tag every verified image immutably, back up all volumes, then start the new
image without rebuilding it:

```powershell
docker tag alpha-engine:local alpha-engine:2.5.0-<git-sha>
$env:ALPHA_ENGINE_IMAGE = "alpha-engine:2.5.0-<git-sha>"
docker compose up -d --no-build api
```

Alpha Engine currently has no standalone database migration command. Runtime
SQLite stores are initialized by the application, so the volume backup is the
migration boundary. For a release that changes a persisted schema, document and
run its release-specific migration after backup and before admitting traffic.

Rollback uses the previous verified image and, if the schema changed, the
matching pre-upgrade volume backup:

```powershell
docker compose stop api
$env:ALPHA_ENGINE_IMAGE = "alpha-engine:<previous-git-sha>"
# Restore the matching backup here when the persisted schema changed.
docker compose up -d --no-build api
```

## Artifact Inspection

Before release, inspect image history and ensure the runtime has no ignored
inputs or build-only dependency trees:

```powershell
docker history --no-trunc alpha-engine:local
docker run --rm --entrypoint sh alpha-engine:local -c `
  'find /app -name .env -o -name node_modules -o -name __pycache__ -o -name "*.pem" -o -name "*.key"'
```

The `find` command must produce no output. The empty persistent mount points are
expected; source data and generated state must not be present in image layers.
