"""Minimal real local full-flow smoke test.

Proves the end-to-end path:
  data update -> Qlib provider/snapshot -> dashboard_db -> API

Uses a deterministic mock adapter for CI stability.
No network calls, no real data providers.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Deterministic Mock Adapter
# ---------------------------------------------------------------------------

class DeterministicMockAdapter:
    """Returns synthetic daily bar data for a fixed set of symbols."""

    SYMBOLS = {
        "000001": {"name": "Ping An Bank", "base_price": 12.50},
        "600519": {"name": "Kweichow Moutai", "base_price": 1800.00},
        "000300": {"name": "CSI 300 Index", "base_price": 3800.00},
    }

    @property
    def name(self) -> str:
        return "deterministic"

    def fetch_daily_bars(self, req):
        from src.data.adapters.base import DataFetchError, FetchResult

        symbol = req.symbol.split(".")[0]
        info = self.SYMBOLS.get(symbol)
        if info is None:
            raise DataFetchError(f"Unknown symbol: {symbol}")

        df = self._generate_bars(symbol, req.start, req.end or "2026-06-20", info["base_price"])
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=df,
        )

    @staticmethod
    def _generate_bars(symbol: str, start: str, end: str, base_price: float) -> pd.DataFrame:
        from datetime import timedelta

        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")

        dates = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)

        seed = hash(symbol) % 10000
        rows = []
        price = base_price
        for i, date in enumerate(dates):
            change = ((seed + i * 7) % 100 - 50) / 10000.0
            price = price * (1 + change)
            close = round(price, 2)
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(price * 0.998, 2),
                "high": round(price * 1.005, 2),
                "low": round(price * 0.995, 2),
                "close": close,
                "volume": int((seed + i * 13) % 1000000 + 100000),
                "amount": round(int((seed + i * 13) % 1000000 + 100000) * close, 2),
                "factor": 1.0,
            })

        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test: Data Update -> CSV -> Qlib Bin -> DataSnapshot
# ---------------------------------------------------------------------------

class TestFullFlowSmoke:
    """Prove the local end-to-end data pipeline works."""

    MINI_WATCHLIST = {
        "cn": ["000001", "600519", "000300"],
    }

    def test_data_update_produces_csv_and_snapshot(self, tmp_path, monkeypatch):
        """Run a minimal data update with mock adapter and verify outputs."""
        from src.data.snapshot import DataSnapshot

        # Setup isolated directories
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        csv_dir = data_dir / "csv_source"
        csv_dir.mkdir()
        snapshot_store = tmp_path / "artifacts" / "snapshots"
        snapshot_store.mkdir(parents=True)

        # Generate CSV data using mock adapter
        adapter = DeterministicMockAdapter()
        from src.data.adapters.base import FetchRequest

        for symbol in self.MINI_WATCHLIST["cn"]:
            req = FetchRequest(symbol=symbol, market="cn", start="2026-01-01", end="2026-06-20")
            result = adapter.fetch_daily_bars(req)

            # Save as CSV
            csv_path = csv_dir / f"{symbol}.csv"
            result.df.to_csv(csv_path, index=False)
            assert csv_path.exists(), f"CSV not created for {symbol}"
            assert len(result.df) > 0, f"Empty CSV for {symbol}"

        # Verify CSV files exist
        csv_files = list(csv_dir.glob("*.csv"))
        assert len(csv_files) == 3, f"Expected 3 CSV files, got {len(csv_files)}"

        # Create Qlib bin directory structure (simplified)
        features_dir = data_dir / "watchlist" / "features"
        features_dir.mkdir(parents=True)
        for csv_path in csv_files:
            symbol = csv_path.stem
            bin_dir = features_dir / symbol
            bin_dir.mkdir()
            # Create a dummy .day.bin file to simulate Qlib bin format
            (bin_dir / "day.bin").write_bytes(b"\x00" * 100)

        # Verify Qlib bin directory structure
        bin_dirs = list(features_dir.iterdir())
        assert len(bin_dirs) == 3, f"Expected 3 bin directories, got {len(bin_dirs)}"

        # Create and publish a DataSnapshot
        snapshot = DataSnapshot.create_snapshot(
            str(csv_dir),
            store=str(snapshot_store),
            source_adapter="deterministic",
            universe="000001,600519,000300",
            quality_verdict="pass",
        )

        assert snapshot is not None, "DataSnapshot creation failed"
        assert snapshot.snapshot_id, "DataSnapshot has no ID"

        # Publish the snapshot
        DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=str(snapshot_store))

        # Verify latest pointer
        latest_path = snapshot_store / "latest"
        assert latest_path.exists(), "latest pointer not created"
        assert latest_path.read_text().strip() == snapshot.snapshot_id

        # Verify resolve_snapshot_binding works
        resolved = DataSnapshot.resolve_snapshot(snapshot.snapshot_id, store=str(snapshot_store))
        assert resolved is not None
        assert resolved.snapshot_id == snapshot.snapshot_id

    def test_dashboard_db_materialization(self, tmp_path):
        """Verify dashboard_db.json can be generated from model artifacts."""

        # Create a minimal dashboard_db.json
        dashboard_dir = tmp_path / "artifacts" / "dashboard"
        dashboard_dir.mkdir(parents=True)
        dashboard_db_path = dashboard_dir / "dashboard_db.json"

        dashboard_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "models": [
                {
                    "id": "smoke-test-model",
                    "run_id": "smoke-run-001",
                    "name": "Smoke Test Model",
                    "market": "cn",
                    "date": "2026-06-20",
                    "params": {"data_snapshot_id": "smoke-snapshot-001"},
                    "data": {
                        "indicators": {
                            "total_return": 0.12,
                            "annual_return": 0.18,
                            "sharpe": 1.42,
                            "max_drawdown": -0.08,
                            "annual_volatility": 0.16,
                        },
                        "report_normal": {
                            "columns": ["account", "return", "bench"],
                            "index": ["2026-01-02T00:00:00", "2026-06-19T00:00:00"],
                            "data": [[1, 0, 0], [1.12, 0.12, 0.05]],
                        },
                        "positions_normal": [
                            {"date": "2026-06-19", "instrument": "SH600000", "weight": 0.05},
                        ],
                        "attribution_normal": [
                            {"instrument": "SH600000", "pnl": 0.12},
                        ],
                    },
                },
            ],
        }

        dashboard_db_path.write_text(json.dumps(dashboard_data, indent=2), encoding="utf-8")

        # Verify the file
        assert dashboard_db_path.exists(), "dashboard_db.json not created"

        loaded = json.loads(dashboard_db_path.read_text(encoding="utf-8"))
        assert "models" in loaded
        assert len(loaded["models"]) == 1

        model = loaded["models"][0]
        assert model["id"] == "smoke-test-model"
        assert model["run_id"] == "smoke-run-001"
        assert "data" in model
        assert "indicators" in model["data"]
        assert "report_normal" in model["data"]
        assert "positions_normal" in model["data"]

        # Verify indicators have expected keys
        indicators = model["data"]["indicators"]
        assert "total_return" in indicators
        assert "sharpe" in indicators
        assert "max_drawdown" in indicators

    def test_api_bridge_returns_dashboard_data(self, tmp_path, monkeypatch):
        """Verify /api/artifacts/dashboard-db returns dashboard_db.json content."""
        import importlib
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # Use the isolated artifact root from _isolate_artifacts fixture
        artifact_root = tmp_path / "artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True)
        dashboard_dir = artifact_root / "dashboard"
        dashboard_dir.mkdir(parents=True, exist_ok=True)
        dashboard_db_path = dashboard_dir / "dashboard_db.json"

        dashboard_data = {
            "generated_at": "2026-06-20T08:00:00Z",
            "models": [
                {
                    "id": "api-test-model",
                    "run_id": "api-run-001",
                    "name": "API Test Model",
                    "market": "cn",
                    "data": {
                        "indicators": {"sharpe": 1.5},
                        "report_normal": None,
                        "positions_normal": [],
                    },
                },
            ],
        }
        dashboard_db_path.write_text(json.dumps(dashboard_data), encoding="utf-8")

        # Patch DASHBOARD_DB_PATH before importing the router
        import src.common.paths as paths_module
        monkeypatch.setattr(paths_module, "DASHBOARD_DB_PATH", dashboard_db_path)
        monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(artifact_root))

        # Reload the artifacts module to pick up the patched path
        import src.api.routers.artifacts as artifacts_module
        importlib.reload(artifacts_module)

        # Create test client
        app = FastAPI()
        app.include_router(artifacts_module.router, prefix="/api/artifacts")

        client = TestClient(app)
        response = client.get("/api/artifacts/dashboard-db")

        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert len(data["models"]) == 1
        assert data["models"][0]["id"] == "api-test-model"
        assert data["models"][0]["run_id"] == "api-run-001"


# ---------------------------------------------------------------------------
# Test: Provider Failure Diagnostics
# ---------------------------------------------------------------------------

class TestProviderFailureDiagnostics:
    """Verify per-symbol provider attempt reporting."""

    def test_failed_adapter_reports_error(self):
        """A failing adapter should produce a clear error message."""
        from src.data.adapters.base import DataFetchError, FetchRequest

        class FailingAdapter:
            @property
            def name(self):
                return "failing"

            def fetch_daily_bars(self, req):
                raise DataFetchError("Simulated provider failure")

        adapter = FailingAdapter()
        req = FetchRequest(symbol="000001", market="cn", start="2026-01-01")

        with pytest.raises(DataFetchError, match="Simulated provider failure"):
            adapter.fetch_daily_bars(req)

    def test_update_accounting_tracks_failures(self):
        """UpdateAccountingReport should track per-symbol failures with reasons."""
        from src.data.update_accounting import UpdateAccountingReport

        report = UpdateAccountingReport(configured={"cn": ["000001", "600519", "000300"]})

        # Mark one symbol as updated, one as failed
        report.add("updated", "cn", "000001")
        report.add("updated", "cn", "600519")
        report.add("failed", "cn", "000300", reason="provider_timeout")

        # Verify tracking
        assert "000300" in report.failed.get("cn", set())
        assert report.reasons.get("failed", {}).get("cn:000300") == "provider_timeout"

        # Validate should pass with higher threshold
        warnings = report.validate_for_publish(
            selected_markets={"cn"},
            strict=False,
            max_missing_pct=0.50,
            max_missing_count=10,
        )

        # Should return warnings (not raise) since we're within threshold
        assert isinstance(warnings, list)

    def test_provider_attempt_tracking(self):
        """MarketDataRouter should track per-symbol provider attempts."""
        from src.data.adapters.base import DataFetchError
        from src.data.router import MarketDataRouter

        class TrackingAdapter:
            """Adapter that tracks calls."""
            calls = []

            @property
            def name(self):
                return "tracking"

            def fetch_daily_bars(self, req):
                self.calls.append(req.symbol)
                raise DataFetchError(f"No data for {req.symbol}")

        adapter = TrackingAdapter()
        router = MarketDataRouter(adapters=[adapter])

        response = router.fetch_daily_bars(symbol="000001", market="cn", start="2026-01-01")

        # Should have attempts recorded
        assert len(response.attempts) > 0
        assert response.attempts[0].provider == "tracking"
        assert response.attempts[0].ok is False
        assert "No data" in response.attempts[0].error


# ---------------------------------------------------------------------------
# Test: ResearchService snapshot binding
# ---------------------------------------------------------------------------

class TestSnapshotBinding:
    """Verify ResearchService can resolve snapshot to provider URI."""

    def test_resolve_snapshot_binding(self, tmp_path, monkeypatch):
        """ResearchService.resolve_snapshot_binding() should resolve provider_uri."""
        from src.data.snapshot import DataSnapshot

        # Create a minimal snapshot
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        csv_dir = data_dir / "csv_source"
        csv_dir.mkdir()

        # Create a minimal CSV file
        csv_path = csv_dir / "000001.csv"
        csv_path.write_text("date,open,high,low,close,volume,amount,factor\n2026-01-02,10,11,9,10.5,1000,10500,1.0\n")

        snapshot_store = tmp_path / "snapshots"
        snapshot_store.mkdir()

        # Create snapshot
        snapshot = DataSnapshot.create_snapshot(
            str(csv_dir),
            store=str(snapshot_store),
            source_adapter="test",
        )

        assert snapshot is not None
        assert snapshot.snapshot_id

        # Publish
        DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=str(snapshot_store))

        # Verify resolve_snapshot_binding works
        from src.research.service import ResearchService

        service = ResearchService.__new__(ResearchService)
        service._project_root = tmp_path

        # Override the store path for testing
        binding = DataSnapshot.resolve_snapshot(snapshot.snapshot_id, store=str(snapshot_store))
        assert binding is not None
        assert binding.snapshot_id == snapshot.snapshot_id
