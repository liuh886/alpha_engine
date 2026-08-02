"""Deterministic local smoke tests for the artifact-producing research path.

The supported path is data -> snapshot -> research artifacts. No HTTP bridge is
required or tested.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


class DeterministicMockAdapter:
    SYMBOLS = {
        "000001": {"base_price": 12.50},
        "600519": {"base_price": 1800.00},
        "000300": {"base_price": 3800.00},
    }

    @property
    def name(self) -> str:
        return "deterministic"

    def fetch_daily_bars(self, request):
        from src.data.adapters.base import DataFetchError, FetchResult

        symbol = request.symbol.split(".")[0]
        info = self.SYMBOLS.get(symbol)
        if info is None:
            raise DataFetchError(f"Unknown symbol: {symbol}")
        frame = self._generate_bars(
            symbol,
            request.start,
            request.end or "2026-06-20",
            info["base_price"],
        )
        return FetchResult(
            provider=self.name,
            symbol=request.symbol,
            market=request.market,
            start=request.start,
            end=request.end,
            df=frame,
        )

    @staticmethod
    def _generate_bars(symbol: str, start: str, end: str, base_price: float) -> pd.DataFrame:
        current = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        dates = []
        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)

        seed = hash(symbol) % 10000
        price = base_price
        rows = []
        for index, date in enumerate(dates):
            change = ((seed + index * 7) % 100 - 50) / 10000.0
            price *= 1 + change
            close = round(price, 2)
            volume = int((seed + index * 13) % 1_000_000 + 100_000)
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "open": round(price * 0.998, 2),
                    "high": round(price * 1.005, 2),
                    "low": round(price * 0.995, 2),
                    "close": close,
                    "volume": volume,
                    "amount": round(volume * close, 2),
                    "factor": 1.0,
                }
            )
        return pd.DataFrame(rows)


class TestArtifactFlowSmoke:
    symbols = ("000001", "600519", "000300")

    def test_data_update_produces_snapshot(self, tmp_path):
        from src.data.adapters.base import FetchRequest
        from src.data.snapshot import DataSnapshot

        csv_dir = tmp_path / "data" / "csv_source"
        csv_dir.mkdir(parents=True)
        snapshot_store = tmp_path / "artifacts" / "snapshots"
        snapshot_store.mkdir(parents=True)
        adapter = DeterministicMockAdapter()

        for symbol in self.symbols:
            result = adapter.fetch_daily_bars(
                FetchRequest(
                    symbol=symbol,
                    market="cn",
                    start="2026-01-01",
                    end="2026-06-20",
                )
            )
            result.df.to_csv(csv_dir / f"{symbol}.csv", index=False)
            assert not result.df.empty

        assert len(list(csv_dir.glob("*.csv"))) == len(self.symbols)
        snapshot = DataSnapshot.create_snapshot(
            str(csv_dir),
            store=str(snapshot_store),
            source_adapter=adapter.name,
            universe=",".join(self.symbols),
            quality_verdict="pass",
        )
        DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=str(snapshot_store))
        resolved = DataSnapshot.resolve_snapshot(snapshot.snapshot_id, store=str(snapshot_store))
        assert resolved is not None
        assert resolved.snapshot_id == snapshot.snapshot_id
        assert (snapshot_store / "latest").read_text().strip() == snapshot.snapshot_id

    def test_dashboard_artifact_materialization(self, tmp_path):
        dashboard_path = tmp_path / "artifacts" / "dashboard" / "dashboard_db.json"
        dashboard_path.parent.mkdir(parents=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "models": [
                {
                    "id": "smoke-test-model",
                    "run_id": "smoke-run-001",
                    "name": "Smoke Test Model",
                    "market": "cn",
                    "params": {"data_snapshot_id": "smoke-snapshot-001"},
                    "data": {
                        "indicators": {
                            "total_return": 0.12,
                            "annual_return": 0.18,
                            "sharpe": 1.42,
                            "max_drawdown": -0.08,
                        },
                        "report_normal": {
                            "columns": ["account", "return", "bench"],
                            "index": ["2026-01-02T00:00:00", "2026-06-19T00:00:00"],
                            "data": [[1, 0, 0], [1.12, 0.12, 0.05]],
                        },
                        "positions_normal": [
                            {"date": "2026-06-19", "instrument": "SH600000", "weight": 0.05}
                        ],
                    },
                }
            ],
        }
        dashboard_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        loaded = json.loads(dashboard_path.read_text(encoding="utf-8"))
        model = loaded["models"][0]
        assert model["id"] == "smoke-test-model"
        assert model["params"]["data_snapshot_id"] == "smoke-snapshot-001"
        assert model["data"]["report_normal"]
        assert model["data"]["positions_normal"]


class TestProviderFailureDiagnostics:
    def test_failed_adapter_reports_error(self):
        from src.data.adapters.base import DataFetchError, FetchRequest

        class FailingAdapter:
            @property
            def name(self):
                return "failing"

            def fetch_daily_bars(self, request):
                raise DataFetchError("Simulated provider failure")

        with pytest.raises(DataFetchError, match="Simulated provider failure"):
            FailingAdapter().fetch_daily_bars(
                FetchRequest(symbol="000001", market="cn", start="2026-01-01")
            )

    def test_update_accounting_tracks_failures(self):
        from src.data.update_accounting import UpdateAccountingReport

        report = UpdateAccountingReport(configured={"cn": list(TestArtifactFlowSmoke.symbols)})
        report.add("updated", "cn", "000001")
        report.add("updated", "cn", "600519")
        report.add("failed", "cn", "000300", reason="provider_timeout")
        assert "000300" in report.failed.get("cn", set())
        assert report.reasons.get("failed", {}).get("cn:000300") == "provider_timeout"
        warnings = report.validate_for_publish(
            selected_markets={"cn"},
            strict=False,
            max_missing_pct=0.50,
            max_missing_count=10,
        )
        assert isinstance(warnings, list)
