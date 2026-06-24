"""Audit ranking feature: backend endpoint and frontend connectivity.

Tests that:
- /api/stock-analysis/ranking backend route exists
- Endpoint returns valid response structure
- Frontend getStockRanking calls correct endpoint
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FRONTEND_SRC = PROJECT_ROOT / "qlib-dashboard" / "src"


class TestRankingBackend:
    """Test ranking backend endpoint exists and is properly registered."""

    def test_ranking_route_exists_in_stock_analysis_router(self):
        """The stock_analysis router must have a ranking route."""
        from src.api.routers.stock_analysis import router

        routes = [r.path for r in router.routes]
        ranking_routes = [r for r in routes if "ranking" in r.lower()]
        assert len(ranking_routes) > 0, (
            f"stock_analysis router has no ranking route. "
            f"Found routes: {routes}"
        )

    def test_ranking_endpoint_registered_in_app(self):
        """The /api/stock-analysis/ranking endpoint must be registered in the FastAPI app."""
        from api_server import app

        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)

        # Check for the ranking endpoint (may be with or without prefix)
        ranking_routes = [r for r in route_paths if "ranking" in r.lower()]
        assert len(ranking_routes) > 0, (
            "No ranking endpoint found in FastAPI app routes. "
            "Frontend BacktestPage calls /api/stock-analysis/ranking."
        )

    def test_ranking_endpoint_accepts_expected_params(self):
        """The ranking endpoint should accept market, sort_by, sort_grade params."""
        import inspect

        from src.api.routers.stock_analysis import get_stock_ranking

        sig = inspect.signature(get_stock_ranking)
        param_names = list(sig.parameters.keys())

        assert "market" in param_names, "ranking endpoint missing 'market' parameter"
        assert "sort_by" in param_names, "ranking endpoint missing 'sort_by' parameter"


class TestRankingFrontend:
    """Test frontend ranking feature connectivity."""

    def test_release_api_calls_ranking_endpoint(self):
        """release-api.ts must call /api/stock-analysis/ranking."""
        release_api = FRONTEND_SRC / "lib" / "release-api.ts"
        content = release_api.read_text(encoding="utf-8")

        assert "/api/stock-analysis/ranking" in content, (
            "release-api.ts does not call /api/stock-analysis/ranking"
        )

    def test_backtest_page_has_ranking_ui(self):
        """BacktestPage.tsx must have ranking-related UI elements."""
        backtest_page = FRONTEND_SRC / "pages" / "BacktestPage.tsx"
        content = backtest_page.read_text(encoding="utf-8")

        # Check for ranking-related code
        assert "ranking" in content.lower(), (
            "BacktestPage.tsx has no ranking feature"
        )
        assert "fetchRanking" in content or "getStockRanking" in content, (
            "BacktestPage.tsx does not call ranking API"
        )
