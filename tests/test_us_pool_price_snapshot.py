from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
import pytest
import yaml

from src.data.adapters.base import FetchRequest, FetchResult
from src.data.us_pool_price_snapshot import (
    build_us_pool_price_snapshot,
    resolve_safe_request_through,
)
from src.decision_support.latest_us_low_turnover_run import (
    run_latest_us_low_turnover_decision,
)

POOL = Path("configs/pools/us_small_pool_v1.yaml")
AS_OF = "2026-07-31"


def _pool_maps() -> tuple[dict[str, str], dict[str, str]]:
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    basket_by_canonical = {
        str(symbol): str(basket)
        for basket, meta in pool["baskets"].items()
        for symbol in meta["symbols"]
    }
    provider_to_canonical = {symbol: symbol for symbol in basket_by_canonical}
    for canonical, meta in pool["references"].items():
        provider_to_canonical[str(meta["provider_symbol"])] = str(canonical)
    return basket_by_canonical, provider_to_canonical


class FakeUsBarsAdapter:
    name = "fake_yfinance"

    def __init__(self, *, stale_provider_symbol: str | None = None) -> None:
        self.basket_by_canonical, self.provider_to_canonical = _pool_maps()
        self.stale_provider_symbol = stale_provider_symbol

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        canonical = self.provider_to_canonical[req.symbol]
        end = pd.Timestamp(req.end)
        periods = 340
        dates = pd.bdate_range(end=end, periods=periods)
        if req.symbol == self.stale_provider_symbol:
            dates = dates[:-1]
        symbols = sorted(self.provider_to_canonical.values())
        symbol_index = symbols.index(canonical)
        basket = self.basket_by_canonical.get(canonical, "reference")
        baskets = sorted(set(self.basket_by_canonical.values()))
        basket_index = baskets.index(basket) if basket in baskets else len(baskets)
        slope = [0.0009, 0.00035, 0.00065, 0.00045, 0.00075, 0.00030, 0.00055][
            basket_index
        ]
        shock = [0.022, 0.0, 0.014, 0.006, 0.018, 0.010, 0.004][basket_index]
        phase = symbol_index * 0.73
        rows = []
        previous_close = 50.0 + symbol_index * 2.0
        for day_index, day in enumerate(dates):
            trend = np.exp(slope * day_index)
            wave = 1.0 + 0.004 * np.sin(day_index / (12.0 + symbol_index % 5) + phase)
            late_shock = 1.0
            if day_index >= len(dates) - 25:
                progress = (day_index - (len(dates) - 25)) / 24.0
                late_shock = 1.0 - shock * progress
            close = (50.0 + symbol_index * 2.0) * trend * wave * late_shock
            open_price = previous_close * (1.0 + 0.0005 * np.sin(day_index + phase))
            rows.append(
                {
                    "date": day,
                    "open": open_price,
                    "high": max(open_price, close) * 1.006,
                    "low": min(open_price, close) * 0.994,
                    "close": close,
                    "volume": 1_000_000 + symbol_index * 10_000 + day_index * 100,
                    "amount": close * (1_000_000 + symbol_index * 10_000),
                    "factor": 1.0,
                }
            )
            previous_close = close
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market="us",
            start=req.start,
            end=req.end,
            df=pd.DataFrame(rows),
            provider_symbol=req.symbol,
        )


def _write_fundamentals(path: Path) -> None:
    basket_by_symbol, _ = _pool_maps()
    period_ends = pd.date_range("2024-03-31", periods=8, freq="QE")
    rows = []
    symbol_count = len(basket_by_symbol)
    for symbol_index, symbol in enumerate(basket_by_symbol):
        base = 90.0 + symbol_index * 4.0
        acceleration = 0.00035 + 0.000035 * symbol_index
        margin_slope_rank = (symbol_index * 7) % symbol_count
        margin_slope = 0.0007 + 0.000055 * margin_slope_rank
        for quarter_index, period_end in enumerate(period_ends):
            revenue = base * (
                1.0
                + 0.035 * quarter_index
                + acceleration * quarter_index * quarter_index
            )
            margin = (
                0.31
                + 0.0015 * (symbol_index % 4)
                + margin_slope * quarter_index
            )
            rows.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period_end.date().isoformat(),
                    "filed_date": (period_end + pd.Timedelta(days=35)).date().isoformat(),
                    "revenue": revenue,
                    "gross_profit": revenue * margin,
                    "currency": "USD",
                    "form_type": "10-Q" if quarter_index % 4 != 3 else "10-K",
                    "accession_id": f"{symbol}-{quarter_index}",
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_safe_cutoff_excludes_open_us_session() -> None:
    before_close = datetime(2026, 7, 31, 17, 0, tzinfo=timezone.utc)
    after_close = datetime(2026, 7, 31, 23, 0, tzinfo=timezone.utc)

    assert resolve_safe_request_through(now_utc=before_close).isoformat() == "2026-07-30"
    assert resolve_safe_request_through(now_utc=after_close).isoformat() == "2026-07-31"


def test_builds_complete_hash_bound_snapshot(tmp_path: Path) -> None:
    decision = build_us_pool_price_snapshot(
        output_root=tmp_path / "snapshots",
        requested_through=AS_OF,
        adapter=FakeUsBarsAdapter(),
    )

    assert decision["decision"] == "us_pool_price_snapshot_ready"
    assert decision["resolved_as_of_date"] == AS_OF
    assert decision["symbol_count"] == 25
    prices_path = Path(decision["prices_csv"])
    frame = pd.read_csv(prices_path)
    assert frame["symbol"].nunique() == 25
    assert frame["date"].max() == AS_OF
    coverage = json.loads(
        (prices_path.parent / "coverage_report.json").read_text(encoding="utf-8")
    )
    assert coverage["all_latest_session_complete"] is True
    provider_symbols = {
        row["canonical_symbol"]: row["provider_symbol"] for row in coverage["rows"]
    }
    assert provider_symbols["SOX"] == "^SOX"


def test_mixed_latest_session_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="latest-session coverage is inconsistent"):
        build_us_pool_price_snapshot(
            output_root=tmp_path / "snapshots",
            requested_through=AS_OF,
            adapter=FakeUsBarsAdapter(stale_provider_symbol="POET"),
        )


def test_latest_runner_generates_immutable_decision_ticket(tmp_path: Path) -> None:
    fundamentals = tmp_path / "fundamentals.csv"
    _write_fundamentals(fundamentals)
    manifest = run_latest_us_low_turnover_decision(
        registry_db=tmp_path / "factor.db",
        ledger_dir=tmp_path / "ledger",
        workspace_dir=tmp_path / "workspace",
        snapshot_root=tmp_path / "snapshots",
        requested_through=AS_OF,
        fundamentals_csv=fundamentals,
        price_adapter=FakeUsBarsAdapter(),
    )

    assert manifest["run_id"] == "latest_us_low_turnover_decision_v1"
    assert manifest["as_of_date"] == AS_OF
    assert manifest["trade_ready"] is False
    ticket = json.loads(
        (tmp_path / "ledger" / "us" / f"{AS_OF}.json").read_text(encoding="utf-8")
    )
    assert ticket["ticket_identity_sha256"] == manifest["outputs"][
        "ticket_identity_sha256"
    ]
    assert ticket["mode"] == "diagnostic_only"
