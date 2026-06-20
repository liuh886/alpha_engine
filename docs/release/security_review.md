# Security & Local Deployment Review

**Date:** 2026-06-19
**Scope:** Alpha Engine local-only deployment (single-user, localhost-bound)
**Reviewer:** Automated audit

---

## 1. API Authentication (HTTP Basic Auth)

**Verdict: PASS**

All API routers are protected by `get_current_user` dependency which enforces HTTP Basic Auth.

- Credentials sourced from environment variables `TRADING_UI_USER` and `TRADING_UI_PASSWORD`.
- Password comparison uses `secrets.compare_digest` (constant-time, resistant to timing attacks).
- **Fail-closed**: if credentials are not configured, the server returns HTTP 500 rather than allowing unauthenticated access.
- Every router declaration in `api_server.py` includes `dependencies=[Depends(get_current_user)]`.
- Public endpoints are limited to `/health`, `/api/public/health`, and `/api/public/version` (read-only, no data exposure).

**Source:** `api_server.py` lines 63-86

---

## 2. MCP Token Authentication

**Verdict: PASS-WITH-NOTE**

MCP tools use a shared token (`ALPHA_DEVELOPER_TOKEN` env var) passed as a `token` parameter on every tool call.

- Every MCP tool calls `_verify_token(token)` before executing.
- Comparison uses direct `==` (not `secrets.compare_digest`), which is a minor timing side-channel. Acceptable for local-only use.
- **Note:** When `ALPHA_DEVELOPER_TOKEN` is unset, all tokens are accepted (development mode). A warning is logged. For production/deployment, this token MUST be set.

**Source:** `src/api/mcp_server.py` lines 31-47

---

## 3. Command Execution Allowlists

**Verdict: PASS**

The `/api/system/exec` endpoint uses a strict allowlist pattern.

- `_EXPLICIT_SAFE_COMMANDS`: Only two hardcoded commands: `data_update` and `arena_settle`, each mapped to a fixed argv prefix.
- `_WORKFLOW_ACTIONS`: Only `train` and `backtest`, which are constructed via `WorkflowCommandEnvelope` (not user-supplied strings).
- Unknown task keys are rejected with HTTP 400.
- Args are sanitized: any arg containing `;` or `&` is dropped.
- Commands are executed via `subprocess.Popen(list)` (no `shell=True`), preventing shell metacharacter injection.
- The `shell=True` usage found in `scripts/run_agents_pipeline.py` is a standalone script, not API-exposed.

**Source:** `src/api/routers/system.py` lines 147-221

---

## 4. CORS Configuration

**Verdict: PASS**

CORS origins are allowlisted, not wildcarded.

- Default origins: `localhost:5173`, `127.0.0.1:5173`, `localhost:8000`, `127.0.0.1:8000`.
- Configurable via `CORS_ORIGINS` or `ALLOWED_ORIGINS` env var (comma-separated).
- `allow_credentials=True` is set, which is correct for Basic Auth with cookies.
- `allow_headers=["*"]` is acceptable for local development; restrict if exposing publicly.

**Source:** `src/common/runtime_settings.py` lines 16-21, `api_server.py` lines 55-61

---

## 5. Static File Serving Security

**Verdict: PASS**

- Static files are served from `qlib-dashboard/dist` via FastAPI's built-in `StaticFiles`, which handles path traversal internally.
- API routers are mounted **before** the static mount, so API routes take precedence.
- The root `index.html` is served with `Cache-Control: no-cache, no-store, must-revalidate` and an ETag.
- No directory listing is exposed.

**Source:** `api_server.py` lines 211-229

---

## 6. Secret Handling

**Verdict: PASS**

- `.env` is listed in `.gitignore` (line 57) and will not be committed.
- `data/`, `artifacts/`, `mlruns/`, `*.log` are all gitignored, preventing accidental leakage of model artifacts or data files.
- Credentials are loaded from environment variables, not hardcoded.
- No API keys, passwords, or tokens appear in the source code.

**Source:** `.gitignore`

---

## 7. File Access Boundaries

**Verdict: PASS**

- `ArtifactGateway` uses a strict allowlist of known artifact keys (`dashboard-db`, `thought-stream`, `arenas`, etc.). Unknown keys raise `ValueError`.
- `get_arena_leaderboard` rejects arena IDs containing `/` or `\`.
- Report archive (`src/reporting/report_archive.py`) uses `Path.is_relative_to()` to prevent path traversal on output paths.
- Dashboard DB deletion (`src/dashboard/run_deletion.py`) also uses `is_relative_to()` validation.
- The `/api/system/paths` endpoint exposes filesystem paths (project root, data dir, etc.) but is behind auth.

**Source:** `src/assistant/services/artifact_gateway.py`, `src/reporting/report_archive.py` lines 21-26

---

## 8. Network Binding

**Verdict: PASS-WITH-NOTE**

- Default bind is `0.0.0.0:8000` (all interfaces). This is standard for Docker/container deployments.
- For strictly local use, set `API_HOST=127.0.0.1` to prevent external access.
- The `ecosystem.config.js` PM2 config should be reviewed to confirm host binding in production.

**Source:** `src/common/runtime_settings.py` line 14

---

## Known Limitations and Mitigations

| # | Issue | Severity | Mitigation |
|---|-------|----------|------------|
| 1 | MCP dev mode accepts any token when `ALPHA_DEVELOPER_TOKEN` is unset | Medium | Always set this env var in deployment. Warning is logged on startup. |
| 2 | MCP token comparison uses `==` instead of `secrets.compare_digest` | Low | Timing attack requires local network access. Acceptable for localhost-only. |
| 3 | `allow_headers=["*"]` in CORS | Low | Restrict to specific headers if exposing beyond localhost. |
| 4 | `0.0.0.0` default bind | Low | Set `API_HOST=127.0.0.1` for local-only use. |
| 5 | `/api/system/paths` exposes internal directory structure | Low | Behind auth. Consider removing or redacting if not needed by dashboard. |
| 6 | Command arg sanitization only filters `;` and `&` | Low | Mitigated by `Popen(list)` (no shell). Additional metacharacters are inert without shell interpretation. |

---

## Summary

Alpha Engine's security posture is appropriate for its intended deployment model (local single-user or small team behind a LAN). Authentication is enforced on all data-modifying endpoints, command execution is allowlisted with no shell injection surface, secrets are excluded from version control, and file access is bounded by allowlists and path validation. The two actionable items for hardening before any internet-exposed deployment are:

1. Set `ALPHA_DEVELOPER_TOKEN` to disable MCP dev mode.
2. Bind to `127.0.0.1` instead of `0.0.0.0`.
