"""Audit that every frontend API call has a matching backend route.

This test parses the frontend TypeScript source files for API endpoint strings
and compares them with the FastAPI registered routes. It catches mismatches
like /api/stock-analysis/ranking if no backend route exists.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = PROJECT_ROOT / "qlib-dashboard" / "src"


def _extract_frontend_endpoints() -> set[str]:
    """Extract all API endpoint strings from frontend source files."""
    endpoints: set[str] = set()
    # Match patterns like: apiClient.get("/api/...") or apiClient.post("/api/...")
    pattern = re.compile(r'''(?:apiClient|apiFetch)\.(?:get|post|put|delete)\s*(?:<[^>]*>)?\s*\(\s*["'](/api/[^"']+)["']''')

    for ts_file in FRONTEND_SRC.rglob("*.ts"):
        if "node_modules" in str(ts_file):
            continue
        # Skip test files
        if ".test." in ts_file.name or ".spec." in ts_file.name:
            continue
        content = ts_file.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(content):
            endpoint = match.group(1)
            # Strip query parameters
            endpoint = endpoint.split("?")[0]
            # Normalize path parameters: ${id} -> {id}
            endpoint = re.sub(r'\$\{[^}]+\}', '{id}', endpoint)
            endpoints.add(endpoint)

    return endpoints


def _extract_backend_routes() -> set[str]:
    """Extract all registered route paths from FastAPI app."""
    # Import the FastAPI app
    import sys
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from api_server import app

    routes: set[str] = set()
    for route in app.routes:
        if hasattr(route, "path"):
            path = route.path
            # Normalize FastAPI path params: {param} -> {id}
            path = re.sub(r'\{[^}]+\}', '{id}', path)
            routes.add(path)
    return routes


def _get_frontend_source_files() -> dict[str, str]:
    """Read frontend API source files for endpoint extraction."""
    files = {}
    api_files = [
        "lib/release-api.ts",
        "api/dataApi.ts",
        "api/modelsApi.ts",
        "api/backtestApi.ts",
        "api/jobsApi.ts",
        "hooks/useAppBootstrap.ts",
        "hooks/useSystemHealth.ts",
    ]
    for rel_path in api_files:
        path = FRONTEND_SRC / rel_path
        if path.exists():
            files[rel_path] = path.read_text(encoding="utf-8", errors="ignore")
    return files


def _extract_endpoints_from_content(content: str) -> set[str]:
    """Extract API endpoints from a single file's content."""
    endpoints: set[str] = set()
    # Match apiClient.get/post patterns
    pattern = re.compile(r'''(?:apiClient|apiFetch)\.(?:get|post|put|delete)\s*(?:<[^>]*>)?\s*\(\s*["'](/api/[^"']+)["']''')
    for match in pattern.finditer(content):
        endpoint = match.group(1)
        endpoint = re.sub(r'\$\{[^}]+\}', '{id}', endpoint)
        endpoints.add(endpoint)
    return endpoints


class TestFrontendApiAudit:
    """Audit frontend API calls against backend routes."""

    def test_all_frontend_endpoints_have_backend_routes(self):
        """Every endpoint called by the frontend must have a registered backend route."""
        frontend_endpoints = _extract_frontend_endpoints()
        backend_routes = _extract_backend_routes()

        # Normalize: strip trailing slashes
        frontend_endpoints = {e.rstrip("/") for e in frontend_endpoints}
        backend_routes = {r.rstrip("/") for r in backend_routes}

        missing = frontend_endpoints - backend_routes
        # Filter out known dynamic paths that are covered by parameterized routes
        missing_filtered = set()
        for ep in missing:
            # Check if it's covered by a parameterized route
            covered = False
            for route in backend_routes:
                if "{" in route:
                    # Convert route pattern to regex
                    pattern = re.sub(r'\{[^}]+\}', '[^/]+', route)
                    if re.fullmatch(pattern, ep):
                        covered = True
                        break
            if not covered:
                missing_filtered.add(ep)

        assert not missing_filtered, (
            "Frontend calls endpoints that have no backend route:\n"
            + "\n".join(f"  - {ep}" for ep in sorted(missing_filtered))
        )

    def test_release_api_endpoints_covered(self):
        """All release-api.ts endpoints must be covered by backend routes."""
        content = (FRONTEND_SRC / "lib" / "release-api.ts").read_text(encoding="utf-8")
        endpoints = _extract_endpoints_from_content(content)
        backend_routes = _extract_backend_routes()
        backend_routes = {r.rstrip("/") for r in backend_routes}

        for ep in endpoints:
            ep = ep.rstrip("/")
            # Check direct match or parameterized match
            found = ep in backend_routes
            if not found:
                for route in backend_routes:
                    if "{" in route:
                        pattern = re.sub(r'\{[^}]+\}', '[^/]+', route)
                        if re.fullmatch(pattern, ep):
                            found = True
                            break
            assert found, f"release-api.ts calls {ep!r} but no backend route exists"

    def test_stock_analysis_ranking_endpoint_exists(self):
        """The /api/stock-analysis/ranking endpoint must exist."""
        backend_routes = _extract_backend_routes()
        # Check for the ranking endpoint (may be parameterized)
        ranking_routes = [r for r in backend_routes if "ranking" in r.lower()]
        assert len(ranking_routes) > 0, (
            "No /api/stock-analysis/ranking route found. "
            "Frontend BacktestPage calls this endpoint for stock ranking."
        )
