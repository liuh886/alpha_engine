from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from src.data.adapters.base import FetchRequest, FetchResult
from src.data.etf_reference_bundle import build_etf_reference_bundle
from src.data.strategy_data_bundle import (
    STRATEGY_DATA_SYMBOLS,
    StrategyDataBundleError,
    build_strategy_data_bundle,
    load_strategy_data_bundle,
    verify_strategy_data_bundle,
)


def _bars(symbol: str, *, start: str = "2024-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=30)
    base = 10.0 + (sum(ord(value) for value in symbol) % 20)
    values = pd.Series(range(len(dates)), dtype=float) * 0.1 + base
    return pd.DataFrame(
        {
            "date": dates,
            "open": values,
            "high": values + 0.5,
            "low": values - 0.5,
            "close": values + 0.2,
            "volume": 1000.0,
            "amount": (values + 0.2) * 1000.0,
            "factor": 1.0,
            "cash_distribution": 0.0,
            "split_factor": 1.0,
        }
    )


@dataclass
class FakeAdapter:
    name: str

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        start = "2024-01-30" if req.symbol == "QQQI" else "2024-01-02"
        frame = _bars(req.symbol, start=start)
        if req.end:
            frame = frame.loc[frame["date"] <= pd.Timestamp(req.end)].copy()
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=frame,
            provider_symbol=req.symbol,
        )


def _build_etf_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "etf"
    build_etf_reference_bundle(
        contract_path=Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml"),
        output_root=root,
        end="2024-03-15",
        primary_adapter=FakeAdapter("tiingo"),
        fallback_adapter=FakeAdapter("yfinance"),
    )
    return root


def test_strategy_bundle_binds_all_tradables_and_signal_references(tmp_path: Path) -> None:
    etf_root = _build_etf_bundle(tmp_path)
    output = tmp_path / "strategy"
    manifest = build_strategy_data_bundle(
        etf_bundle_root=etf_root,
        output_root=output,
        start="2024-01-01",
        end="2024-03-15",
        reference_adapter=FakeAdapter("yfinance"),
    )

    assert manifest["status"] == "ready"
    assert manifest["expected_symbol_count"] == 6
    assert manifest["ready_symbol_count"] == 6
    assert manifest["symbols"] == list(STRATEGY_DATA_SYMBOLS)
    assert manifest["roles"]["QQQI"] == "tradable"
    assert manifest["roles"]["SGOV"] == "tradable"
    assert manifest["roles"]["^VIX"] == "signal_reference"
    assert manifest["roles"]["^VXN"] == "signal_reference"
    assert manifest["first_date"] == "2024-01-30"
    assert manifest["professional_source_ready"] is True

    bars, coverage, loaded = load_strategy_data_bundle(output)
    assert set(bars) == set(STRATEGY_DATA_SYMBOLS)
    assert set(coverage["status"]) == {"ready"}
    assert loaded["component_kind"] == "strategy_data_bundle"
    assert loaded["trade_ready"] is False


def test_strategy_bundle_detects_tampered_reference_file(tmp_path: Path) -> None:
    etf_root = _build_etf_bundle(tmp_path)
    output = tmp_path / "strategy"
    build_strategy_data_bundle(
        etf_bundle_root=etf_root,
        output_root=output,
        start="2024-01-01",
        end="2024-03-15",
        reference_adapter=FakeAdapter("yfinance"),
    )
    path = output / "canonical" / "INDEX_VIX.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(StrategyDataBundleError, match="hash mismatch"):
        verify_strategy_data_bundle(output)
