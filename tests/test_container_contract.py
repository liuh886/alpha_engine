from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _significant_lines(relative_path: str) -> set[str]:
    return {
        line.strip()
        for line in _read(relative_path).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_dockerignore_excludes_secrets_state_outputs_and_local_builds() -> None:
    lines = _significant_lines(".dockerignore")
    required_patterns = {
        ".env",
        ".env.*",
        "**/secrets/**",
        "**/*.key",
        "**/*.pem",
        "data/**",
        "artifacts/**",
        "mlruns/**",
        "reports/**",
        "site/**",
        "qlib-dashboard/dist/**",
        "**/node_modules/**",
        ".venv/**",
        "**/__pycache__/**",
        ".pytest_cache/**",
        ".ruff_cache/**",
        ".mypy_cache/**",
        ".git/**",
        ".worktrees/**",
    }

    assert required_patterns <= lines


def test_dockerfile_builds_frontend_and_locked_python_runtime() -> None:
    dockerfile = _read("Dockerfile")
    lower = dockerfile.lower()

    assert re.search(r"^from node:20[^\n]* as frontend-build$", lower, re.MULTILINE)
    assert "copy qlib-dashboard/package.json qlib-dashboard/package-lock.json ./" in lower
    assert "npm ci" in lower
    assert "npm run lint" in lower
    assert "tsc --noemit" in lower
    assert "npm test" in lower
    assert "npm run build" in lower

    assert re.search(r"^from python:3\.10[^\n]* as python-deps$", lower, re.MULTILINE)
    assert re.search(r"^from python:3\.10[^\n]* as runtime$", lower, re.MULTILINE)
    assert "copy pyproject.toml uv.lock ./" in lower
    assert "uv sync --frozen --no-dev --no-install-project" in lower
    assert re.search(
        r"copy\s+--from=frontend-build[^\n]*/frontend/dist\s+\./qlib-dashboard/dist/",
        lower,
    )


def test_runtime_image_uses_explicit_safe_copy_inputs() -> None:
    dockerfile = _read("Dockerfile")
    copy_lines = [
        line.strip().lower()
        for line in dockerfile.splitlines()
        if line.strip().lower().startswith(("copy ", "add "))
    ]

    forbidden_broad_copies = {"copy . .", "copy . /app", "add . .", "add . /app"}
    assert forbidden_broad_copies.isdisjoint(copy_lines)

    forbidden_sources = re.compile(
        r"(?:^|\s)(?:\.env(?:\s|$)|secrets?/|data/|artifacts/|mlruns/|reports/|"
        r"site/|qlib-dashboard/dist/|node_modules/|\.venv/|\.git/)"
    )
    unsafe = [
        line for line in copy_lines if "--from=" not in line and forbidden_sources.search(line)
    ]
    assert unsafe == []


def test_runtime_is_non_root_and_has_startup_and_readiness_contracts() -> None:
    dockerfile = _read("Dockerfile").lower()
    entrypoint = _read("scripts/container-entrypoint.sh")
    healthcheck = _read("scripts/container-healthcheck.py")

    assert re.search(r"^user (?:10001:10001|alpha)$", dockerfile, re.MULTILINE)
    assert "entrypoint" in dockerfile and "container-entrypoint.sh" in dockerfile
    assert "healthcheck" in dockerfile and "container-healthcheck.py" in dockerfile

    assert "ALPHA_ENGINE_ENV:-" in entrypoint
    assert "TRADING_UI_USER" in entrypoint
    assert "TRADING_UI_PASSWORD" in entrypoint
    assert "ALPHA_DEVELOPER_TOKEN" in entrypoint
    assert "qlib-dashboard/dist/index.html" in entrypoint
    assert 'exec "$@"' in entrypoint

    assert "/api/public/health" in healthcheck
    assert 'f"{base_url}/"' in healthcheck


def test_compose_requires_auth_persists_state_and_defaults_to_localhost() -> None:
    compose = _read("docker-compose.yml")

    assert "${ALPHA_ENGINE_BIND_ADDRESS:-127.0.0.1}:${ALPHA_ENGINE_PORT:-8000}:8000" in compose
    assert "TRADING_UI_USER: ${TRADING_UI_USER:?" in compose
    assert "TRADING_UI_PASSWORD: ${TRADING_UI_PASSWORD:?" in compose
    assert "ALPHA_DEVELOPER_TOKEN: ${ALPHA_DEVELOPER_TOKEN:?" in compose
    assert "ALPHA_ENGINE_ENV: production" in compose
    assert "API_HOST: 0.0.0.0" in compose

    for mount in (
        "alpha-engine-data:/app/data",
        "alpha-engine-artifacts:/app/artifacts",
        "alpha-engine-mlruns:/app/mlruns",
        "alpha-engine-reports:/app/reports",
        "alpha-engine-configs:/app/configs",
    ):
        assert mount in compose

    assert not re.search(r"-\s+\./(?:data|artifacts|mlruns|reports|configs):", compose)
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "condition: service_healthy" not in compose
