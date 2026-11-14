from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

import src.data.strategy_data_bundle as strategy_data_bundle
from src.data.adapters.base import FetchRequest, FetchResult
from src.data.etf_reference_bundle import build_etf_reference_bundle
from src.data.strategy_data_bundle import (
    STRATEGY_MANIFEST_NAME,
    STRATEGY_SGOV_DATA_SYMBOLS,
    StrategyDataBundleError,
    build_strategy_data_bundle,
    load_strategy_data_bundle,
    verify_strategy_data_bundle,
)

HOLIDAY = "2024-01-15"
WEEKEND = "2024-01-13"


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


@dataclass
class HolidayAwareAdapter:
    name: str
    excluded_dates: tuple[str, ...] = ()

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        start = "2024-01-30" if req.symbol == "QQQI" else "2024-01-02"
        frame = _bars(req.symbol, start=start)
        if self.excluded_dates:
            excluded = pd.to_datetime(list(self.excluded_dates))
            frame = frame.loc[~frame["date"].isin(excluded)].copy()
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


@dataclass
class StubSignalReferenceAdapter:
    name: str
    extra_dates: dict[str, tuple[str, ...]]

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        frame = _bars(req.symbol)
        extras = list(self.extra_dates.get(req.symbol, ()))
        if extras:
            extra_frame = _bars(req.symbol).iloc[: len(extras)].copy()
            extra_frame["date"] = pd.to_datetime(extras)
            frame = pd.concat([frame, extra_frame], ignore_index=True)
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


def _build_etf_bundle(tmp_path: Path, adapter: object | None = None) -> Path:
    root = tmp_path / "etf"
    build_etf_reference_bundle(
        contract_path=Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml"),
        output_root=root,
        end="2024-03-15",
        primary_adapter=adapter or FakeAdapter("tiingo"),
        fallback_adapter=adapter or FakeAdapter("yfinance"),
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
        supplemental_symbols=("SGOV", "^VIX", "^VXN"),
        supplemental_roles={
            "SGOV": "tradable",
            "^VIX": "signal_reference",
            "^VXN": "signal_reference",
        },
    )

    assert manifest["status"] == "ready"
    assert manifest["expected_symbol_count"] == 6
    assert manifest["ready_symbol_count"] == 6
    assert manifest["symbols"] == list(STRATEGY_SGOV_DATA_SYMBOLS)
    assert manifest["roles"]["QQQI"] == "tradable"
    assert manifest["roles"]["SGOV"] == "tradable"
    assert manifest["roles"]["^VIX"] == "signal_reference"
    assert manifest["roles"]["^VXN"] == "signal_reference"
    assert manifest["first_date"] == "2024-01-30"
    assert manifest["professional_source_ready"] is True

    bars, coverage, loaded = load_strategy_data_bundle(output)
    assert set(bars) == set(STRATEGY_SGOV_DATA_SYMBOLS)
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


def test_signal_references_are_restricted_to_equity_sessions(tmp_path: Path) -> None:
    etf_root = _build_etf_bundle(
        tmp_path,
        adapter=HolidayAwareAdapter("tiingo", excluded_dates=(HOLIDAY,)),
    )
    output = tmp_path / "strategy"
    manifest = build_strategy_data_bundle(
        etf_bundle_root=etf_root,
        output_root=output,
        start="2024-01-01",
        end="2024-03-15",
        reference_adapter=StubSignalReferenceAdapter(
            "yfinance",
            extra_dates={"^VIX": (WEEKEND,), "^VXN": (WEEKEND,)},
        ),
    )

    assert manifest["status"] == "ready"
    session_filter = manifest["details"]["signal_reference_session_filter"]
    assert session_filter["policy_id"] == "us_equity_session_only_v1"
    assert session_filter["authority_symbol"] == "QQQ"
    vix_filter = session_filter["symbols"]["^VIX"]
    assert vix_filter["removed_dates"] == [WEEKEND, HOLIDAY]
    assert vix_filter["removed_count"] == 2
    assert session_filter["symbols"]["^VXN"]["removed_dates"] == [WEEKEND, HOLIDAY]

    qqq = pd.read_csv(etf_root / "canonical" / "QQQ.csv")
    expected_sessions = set(pd.to_datetime(qqq["date"]).dt.strftime("%Y-%m-%d"))
    assert vix_filter["retained_rows"] == len(expected_sessions)

    actual = pd.read_csv(output / "canonical" / "INDEX_VIX.csv")
    assert set(actual["date"]) == expected_sessions
    assert pd.to_datetime(actual["date"]).is_monotonic_increasing

    expected = _bars("^VIX")
    expected["date"] = pd.to_datetime(expected["date"]).dt.strftime("%Y-%m-%d")
    expected = expected.set_index("date")
    retained = sorted(expected.index.intersection(expected_sessions))
    actual = actual.set_index("date")
    assert actual.index.tolist() == retained
    pd.testing.assert_series_equal(
        actual["open"], expected.loc[retained, "open"], check_names=False
    )
    pd.testing.assert_series_equal(
        actual["close"], expected.loc[retained, "close"], check_names=False
    )


def test_signal_reference_sessions_fail_closed_without_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    etf_root = _build_etf_bundle(tmp_path)
    load = strategy_data_bundle.load_etf_reference_bundle

    def load_without_qqq(*args, **kwargs):
        bars, coverage, manifest = load(*args, **kwargs)
        bars.pop("QQQ")
        return bars, coverage, manifest

    monkeypatch.setattr(strategy_data_bundle, "load_etf_reference_bundle", load_without_qqq)

    with pytest.raises(StrategyDataBundleError, match="authority calendar is absent"):
        build_strategy_data_bundle(
            etf_bundle_root=etf_root,
            output_root=tmp_path / "strategy",
            start="2024-01-01",
            end="2024-03-15",
            reference_adapter=FakeAdapter("yfinance"),
        )


def test_signal_reference_sessions_fail_closed_on_empty_authority() -> None:
    empty = _bars("QQQ").iloc[0:0]

    with pytest.raises(StrategyDataBundleError, match="authority calendar is empty"):
        strategy_data_bundle._equity_session_calendar(
            {"QQQ": empty},
            {"QQQ": "tradable"},
        )


def test_signal_reference_session_filter_is_byte_stable(tmp_path: Path) -> None:
    etf_root = _build_etf_bundle(tmp_path)
    extra_dates = {"^VIX": (WEEKEND,), "^VXN": (WEEKEND,)}
    first, second = (
        build_strategy_data_bundle(
            etf_bundle_root=etf_root,
            output_root=tmp_path / name,
            start="2024-01-01",
            end="2024-03-15",
            reference_adapter=StubSignalReferenceAdapter("yfinance", extra_dates),
        )
        for name in ("one", "two")
    )

    first_section = json.dumps(
        first["details"]["signal_reference_session_filter"], sort_keys=True
    )
    second_section = json.dumps(
        second["details"]["signal_reference_session_filter"], sort_keys=True
    )
    assert first_section == second_section
    assert (tmp_path / "one" / STRATEGY_MANIFEST_NAME).read_bytes() == (
        tmp_path / "two" / STRATEGY_MANIFEST_NAME
    ).read_bytes()


def test_existing_bundle_load_does_not_retroactively_filter(tmp_path: Path) -> None:
    etf_root = _build_etf_bundle(tmp_path)
    output = tmp_path / "strategy"
    built = build_strategy_data_bundle(
        etf_bundle_root=etf_root,
        output_root=output,
        start="2024-01-01",
        end="2024-03-15",
        reference_adapter=FakeAdapter("yfinance"),
    )
    path = output / "canonical" / "INDEX_VIX.csv"
    stored = pd.read_csv(path)
    extra = pd.DataFrame([{"date": WEEKEND, "open": 1.0, "close": 2.0}])
    pd.concat([stored, extra], ignore_index=True).to_csv(path, index=False)

    manifest_path = output / STRATEGY_MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = str(path.relative_to(output))
    payload["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    bars, _, loaded = load_strategy_data_bundle(output)
    assert pd.Timestamp(WEEKEND) in set(bars["^VIX"]["date"])
    assert (
        loaded["details"]["signal_reference_session_filter"]
        == built["details"]["signal_reference_session_filter"]
    )
