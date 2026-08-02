"""Enforce the artifact-only browser boundary.

The Research Artifact Studio is a static/local PWA. Production frontend source
must not import retired HTTP clients or contain browser API endpoint calls.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = PROJECT_ROOT / "qlib-dashboard" / "src"

RETIRED_MODULES = {
    "lib/api.ts",
    "lib/api-client.ts",
    "lib/release-api.ts",
    "lib/release-workflow.ts",
    "hooks/useJobs.ts",
    "hooks/useDataStatus.ts",
    "hooks/useSystemHealth.ts",
    "hooks/useQuery.ts",
    "hooks/useMutation.ts",
    "api/dataApi.ts",
    "api/jobsApi.ts",
    "api/backtestApi.ts",
}

IMPORT_PATTERN = re.compile(
    r"(?:from\s+|import\s*\()\s*['\"](?:@/|\.\.?/)*(?:lib/(?:api|api-client|release-api)|api/(?:dataApi|jobsApi|backtestApi)|hooks/(?:useJobs|useDataStatus|useSystemHealth|useQuery|useMutation))['\"]"
)
API_LITERAL_PATTERN = re.compile(r"['\"](/api(?:/[^'\"]*)?)['\"]")


def _production_sources() -> list[Path]:
    files: list[Path] = []
    for suffix in ("*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(suffix):
            if ".test." in path.name or ".spec." in path.name:
                continue
            files.append(path)
    return sorted(set(files))


def test_retired_http_modules_are_physically_absent() -> None:
    existing = sorted(path for path in RETIRED_MODULES if (FRONTEND_SRC / path).exists())
    assert not existing, "Retired frontend HTTP modules still exist:\n" + "\n".join(existing)


def test_production_frontend_has_no_retired_http_imports() -> None:
    violations: list[str] = []
    for path in _production_sources():
        content = path.read_text(encoding="utf-8", errors="ignore")
        if IMPORT_PATTERN.search(content):
            violations.append(str(path.relative_to(PROJECT_ROOT)))
    assert not violations, "Production frontend imports retired HTTP modules:\n" + "\n".join(violations)


def test_production_frontend_contains_no_api_endpoint_literals() -> None:
    violations: list[str] = []
    for path in _production_sources():
        content = path.read_text(encoding="utf-8", errors="ignore")
        endpoints = sorted(set(API_LITERAL_PATTERN.findall(content)))
        if endpoints:
            violations.append(f"{path.relative_to(PROJECT_ROOT)}: {', '.join(endpoints)}")
    assert not violations, "Production frontend still declares /api endpoints:\n" + "\n".join(violations)


def test_browser_runtime_is_artifact_only() -> None:
    runtime = (FRONTEND_SRC / "lib" / "runtime-capabilities.ts").read_text(encoding="utf-8")
    assert "export type RuntimeMode = 'static_artifact' | 'local_artifact';" in runtime
    assert "backendApi: false" in runtime
    assert "mutations: false" in runtime
    assert "jobs: false" in runtime
    assert "requiresAuthentication: false" in runtime

    routes = (FRONTEND_SRC / "routes.ts").read_text(encoding="utf-8")
    for retired_route in ("system", "agent", "backtest", "data-manager", "arena", "strategy"):
        assert f"path: '{retired_route}'" not in routes
