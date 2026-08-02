from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult
from src.data.etf_reference_bundle import (
    ETFReferenceBundleError,
    build_etf_reference_bundle,
    load_etf_reference_bundle,
    reconcile_adjusted_bars,
)
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars

CONTRACT = Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml")


def _bars(
    symbol: str,
    *,
    start: str,
    periods: int = 25,
    professional: bool = False,
) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    base = {"QQQ": 400.0, "QQQI": 50.0, "TQQQ": 60.0, "VIX": 18.0}[symbol]
    close = pd.Series(base * np.cumprod(np.full(periods, 1.001)), index=dates)
    open_price = close * 0.999
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": open_price.values,
            "high": (close * 1.01).values,
            "low": (open_price * 0.99).values,
            "close": close.values,
            "volume": np.arange(periods, dtype=float) + 1000.0,
            "amount": close.values * (np.arange(periods, dtype=float) + 1000.0),
            "factor": np.ones(periods),
        }
    )
    if professional:
        frame["raw_open"] = frame["open"] / 0.95
        frame["raw_high"] = frame["high"] / 0.95
        frame["raw_low"] = frame["low"] / 0.95
        frame["raw_close"] = frame["close"] / 0.95
        frame["raw_volume"] = frame["volume"]
        frame["cash_distribution"] = 0.0
        frame["split_factor"] = 1.0
        if symbol == "QQQI":
            frame.loc[10, "cash_distribution"] = 0.60
        if symbol == "TQQQ":
            frame.loc[12, "split_factor"] = 2.0
    return frame


@dataclass
class FakeAdapter:
    _name: str
    frames: dict[str, pd.DataFrame]

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = req.symbol.upper()
        if symbol not in self.frames:
            raise DataFetchError(f"missing fixture for {symbol}")
        frame = self.frames[symbol].copy()
        frame.attrs["provider_metadata"] = {
            "ticker": symbol,
            "name": f"{symbol} fixture",
        }
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=frame,
            provider_symbol=symbol,
        )


def _fallback_frames() -> dict[str, pd.DataFrame]:
    return {
        "QQQ": _bars("QQQ", start="2024-01-29"),
        "QQQI": _bars("QQQI", start="2024-01-30"),
        "TQQQ": _bars("TQQQ", start="2024-01-29"),
    }


def _primary_frames() -> dict[str, pd.DataFrame]:
    return {
        symbol: frame.assign(
            raw_open=frame["open"] / 0.95,
            raw_high=frame["high"] / 0.95,
            raw_low=frame["low"] / 0.95,
            raw_close=frame["close"] / 0.95,
            raw_volume=frame["volume"],
            cash_distribution=0.0,
            split_factor=1.0,
        )
        for symbol, frame in _fallback_frames().items()
    }


def test_yahoo_only_bundle_is_strategy_ready_but_not_professional(tmp_path: Path) -> None:
    manifest = build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=None,
        fallback_adapter=FakeAdapter("yfinance", _fallback_frames()),
    )

    assert manifest["strategy_data_ready"] is True
    assert manifest["professional_source_ready"] is False
    assert manifest["common_history_start"] == "2024-01-30"
    assert manifest["selected_providers"] == {
        "QQQ": "yfinance",
        "QQQI": "yfinance",
        "TQQQ": "yfinance",
    }
    qqqi = pd.read_csv(tmp_path / "canonical" / "QQQI.csv")
    assert qqqi["date"].min().startswith("2024-01-30")


def test_professional_bundle_retains_distributions_splits_and_hashes(
    tmp_path: Path,
) -> None:
    primary = _primary_frames()
    primary["QQQI"].loc[10, "cash_distribution"] = 0.60
    primary["TQQQ"].loc[12, "split_factor"] = 2.0
    manifest = build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=FakeAdapter("tiingo", primary),
        fallback_adapter=FakeAdapter("yfinance", _fallback_frames()),
    )

    assert manifest["strategy_data_ready"] is True
    assert manifest["professional_source_ready"] is True
    assert set(manifest["reconciliation_status"].values()) == {"consensus"}
    assert set(manifest["selected_providers"].values()) == {"tiingo"}
    actions = pd.read_csv(tmp_path / "corporate_actions.csv")
    assert actions.loc[actions["symbol"].eq("QQQI"), "cash_distribution"].tolist() == [
        pytest.approx(0.60)
    ]
    assert actions.loc[actions["symbol"].eq("TQQQ"), "split_factor"].tolist() == [
        pytest.approx(2.0)
    ]

    bars, coverage, loaded = load_etf_reference_bundle(tmp_path)
    assert sorted(bars) == ["QQQ", "QQQI", "TQQQ"]
    assert len(coverage) == 3
    assert loaded["professional_source_ready"] is True


def test_unexplained_provider_disagreement_quarantines_primary(tmp_path: Path) -> None:
    primary = _primary_frames()
    primary["QQQ"].loc[8, ["open", "high", "low", "close"]] = [
        800.0,
        810.0,
        790.0,
        805.0,
    ]
    manifest = build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=FakeAdapter("tiingo", primary),
        fallback_adapter=FakeAdapter("yfinance", _fallback_frames()),
    )

    assert manifest["strategy_data_ready"] is True
    assert manifest["professional_source_ready"] is False
    assert manifest["reconciliation_status"]["QQQ"] == "quarantine"
    assert manifest["selected_providers"]["QQQ"] == "yfinance"


def test_bundle_loader_rejects_modified_canonical_file(tmp_path: Path) -> None:
    build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=None,
        fallback_adapter=FakeAdapter("yfinance", _fallback_frames()),
    )
    path = tmp_path / "canonical" / "QQQ.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ETFReferenceBundleError, match="hash mismatch"):
        load_etf_reference_bundle(tmp_path)


def test_strategy_loader_uses_bundle_for_etfs_and_direct_fetch_for_vix(
    tmp_path: Path,
) -> None:
    build_etf_reference_bundle(
        contract_path=CONTRACT,
        output_root=tmp_path,
        primary_adapter=None,
        fallback_adapter=FakeAdapter("yfinance", _fallback_frames()),
    )
    vix_adapter = FakeAdapter("yfinance", {"VIX": _bars("VIX", start="2024-01-29")})
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=["QQQI", "QQQ", "TQQQ", "VIX"],
        start="2024-01-30",
        bundle_dir=tmp_path,
        adapter=vix_adapter,
    )

    assert sorted(bars) == ["QQQ", "QQQI", "TQQQ", "VIX"]
    assert identity["mode"] == "governed_etf_bundle"
    assert identity["strategy_data_ready"] is True
    assert set(coverage["data_mode"]) == {
        "governed_etf_bundle",
        "direct_reference_fetch",
    }


def test_reconciliation_can_explain_action_window_difference() -> None:
    fallback = _bars("QQQI", start="2024-01-30", periods=25)
    primary = _bars("QQQI", start="2024-01-30", periods=25, professional=True)
    primary.loc[10, "cash_distribution"] = 0.60
    primary.loc[10, ["open", "high", "low", "close"]] *= 1.02
    primary.loc[11, ["open", "high", "low", "close"]] *= 1.02
    result = reconcile_adjusted_bars(
        primary,
        fallback,
        symbol="QQQI",
        settings={
            "minimum_overlap_sessions": 20,
            "consensus_p99_adjusted_close_return_diff": 0.001,
            "consensus_max_adjusted_close_return_diff": 0.01,
            "material_return_difference": 0.01,
            "corporate_action_window_sessions": 1,
        },
    )
    assert result["status"] == "explainable_corporate_action_difference"
