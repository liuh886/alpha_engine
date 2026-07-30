import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.data.adapters.akshare_adapter import _INDEX_PROVIDER_SYMBOLS
from src.research.cn_pool_provider import build_cn_pool_provider


CONTRACT_PATH = Path("configs/providers/cn_small_pool_v1_provider_contract.yaml")
POOL_PATH = Path("configs/pools/cn_small_pool_v1.yaml")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _provider_symbol(canonical: str, pool: dict) -> str:
    metadata = pool.get("symbol_metadata", {}).get(canonical)
    if metadata is None:
        metadata = pool["references"][canonical]
    return str(metadata["provider_symbol"])


def _fixture_inputs(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pool = _load(POOL_PATH)
    candidates = [
        symbol
        for basket in pool["baskets"].values()
        for symbol in basket["symbols"]
    ]
    references = list(pool["references"])
    dates = pd.to_datetime(
        ["2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01"]
    )

    bars: list[dict] = []
    status: list[dict] = []
    for index, canonical in enumerate([*candidates, *references]):
        provider_symbol = _provider_symbol(canonical, pool)
        is_reference = canonical in references
        for offset, date in enumerate(dates):
            value = 20.0 + index + offset * 0.1
            bars.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": provider_symbol,
                    "open": value,
                    "high": value + 0.5,
                    "low": value - 0.5,
                    "close": value + 0.1,
                    "volume": 1_000_000,
                    "amount": None if is_reference else 100_000_000,
                    "adjustment_convention": (
                        "unadjusted_index" if is_reference else "qfq"
                    ),
                    "source_bar_provider": (
                        "fixture_index_bars" if is_reference else "fixture_stock_bars"
                    ),
                }
            )
            status.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": provider_symbol,
                    "listed": True,
                    "suspended": False,
                    "st": False,
                    "delisted": False,
                    "limit_up_at_open": False,
                    "limit_down_at_open": False,
                    "tradable_at_open": True,
                    "source_status_provider": "fixture_point_in_time_status",
                }
            )

    calendar = [
        {
            "date": date.date().isoformat(),
            "is_open": True,
            "source_calendar_provider": "fixture_cn_calendar",
        }
        for date in dates
    ]
    bars_path = tmp_path / "bars.csv"
    status_path = tmp_path / "status.csv"
    calendar_path = tmp_path / "calendar.csv"
    pd.DataFrame(bars).to_csv(bars_path, index=False)
    pd.DataFrame(status).to_csv(status_path, index=False)
    pd.DataFrame(calendar).to_csv(calendar_path, index=False)
    return bars_path, status_path, calendar_path, pool


def _run(tmp_path: Path, bars_path: Path, status_path: Path, calendar_path: Path) -> dict:
    return build_cn_pool_provider(
        contract_path=CONTRACT_PATH,
        bars_csv=bars_path,
        status_csv=status_path,
        calendar_csv=calendar_path,
        output_dir=tmp_path / "output",
    )


def test_cn_reference_provider_aliases_cover_benchmark_and_style_context() -> None:
    assert _INDEX_PROVIDER_SYMBOLS == {
        "000300": "sh000300",
        "399006": "sz399006",
    }


def test_cn_provider_builds_manifest_bound_outputs_and_preserves_symbols(
    tmp_path: Path,
) -> None:
    bars_path, status_path, calendar_path, _ = _fixture_inputs(tmp_path)

    decision = _run(tmp_path, bars_path, status_path, calendar_path)

    assert decision["decision"] == "cn_provider_contract_ready"
    assert decision["pool_id"] == "cn_small_pool_v1"
    assert decision["candidate_count"] == 21
    assert decision["reference_count"] == 2
    assert decision["provider_contract_passed"] is True
    assert decision["live_provider_run_completed"] is False
    assert decision["authoritative_provider_artifact"] is False
    assert decision["performance_evaluated"] is False
    assert decision["reserved_performance_opened"] is False
    assert decision["trade_ready"] is False

    output = tmp_path / "output"
    for filename in (
        "cn_pool_bars.csv",
        "cn_pool_status.csv",
        "cn_trading_calendar.csv",
        "provider_manifest.json",
        "data_quality_report.json",
        "decision.json",
    ):
        assert (output / filename).is_file()

    bars = pd.read_csv(output / "cn_pool_bars.csv", dtype={"symbol": "string"})
    status = pd.read_csv(output / "cn_pool_status.csv", dtype={"symbol": "string"})
    assert "000021.SZ" in set(bars["symbol"])
    assert "000300.SH" in set(bars["symbol"])
    assert "399006.SZ" in set(status["symbol"])
    assert pd.to_datetime(bars["date"]).max() == pd.Timestamp("2026-06-30")
    assert pd.to_datetime(status["date"]).max() == pd.Timestamp("2026-06-30")

    quality = json.loads((output / "data_quality_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "provider_manifest.json").read_text(encoding="utf-8"))
    assert quality["excluded_reserved_rows"] == {
        "bars": 23,
        "calendar": 1,
        "status": 23,
    }
    assert quality["missing_required_identities"] == []
    assert quality["providers"]["stock_bars"] == ["fixture_stock_bars"]
    assert quality["providers"]["reference_bars"] == ["fixture_index_bars"]
    assert quality["live_provider_run_completed"] is False
    assert manifest["reserved_start"] == "2026-07-01"
    assert manifest["live_provider_run_completed"] is False
    assert len(manifest["manifest_identity_sha256"]) == 64
    assert set(manifest["outputs"]) == {
        "cn_pool_bars.csv",
        "cn_pool_status.csv",
        "cn_trading_calendar.csv",
        "data_quality_report.json",
        "decision.json",
    }


def test_cn_provider_fails_when_one_bar_lacks_point_in_time_status(tmp_path: Path) -> None:
    bars_path, status_path, calendar_path, _ = _fixture_inputs(tmp_path)
    status = pd.read_csv(status_path, dtype={"symbol": "string"})
    status = status.iloc[1:].copy()
    status.to_csv(status_path, index=False)

    with pytest.raises(ValueError, match="every bar row"):
        _run(tmp_path, bars_path, status_path, calendar_path)


def test_cn_provider_rejects_contradictory_tradability(tmp_path: Path) -> None:
    bars_path, status_path, calendar_path, _ = _fixture_inputs(tmp_path)
    status = pd.read_csv(status_path, dtype={"symbol": "string"})
    status.loc[0, "suspended"] = True
    status.loc[0, "tradable_at_open"] = True
    status.to_csv(status_path, index=False)

    with pytest.raises(ValueError, match="logically impossible tradable"):
        _run(tmp_path, bars_path, status_path, calendar_path)


def test_cn_provider_rejects_mixed_candidate_bar_providers(tmp_path: Path) -> None:
    bars_path, status_path, calendar_path, pool = _fixture_inputs(tmp_path)
    bars = pd.read_csv(bars_path, dtype={"symbol": "string"})
    target = _provider_symbol("688008.SH", pool)
    bars.loc[bars["symbol"] == target, "source_bar_provider"] = "second_stock_source"
    bars.to_csv(bars_path, index=False)

    with pytest.raises(ValueError, match="candidate bars must use one provider"):
        _run(tmp_path, bars_path, status_path, calendar_path)


def test_cn_provider_rejects_mixed_adjustment_or_invalid_ohlc(tmp_path: Path) -> None:
    bars_path, status_path, calendar_path, pool = _fixture_inputs(tmp_path)
    bars = pd.read_csv(bars_path, dtype={"symbol": "string"})
    target = _provider_symbol("000021.SZ", pool)
    first = bars.index[bars["symbol"] == target][0]
    bars.loc[first, "adjustment_convention"] = "unadjusted"
    bars.to_csv(bars_path, index=False)

    with pytest.raises(ValueError, match="one declared adjustment convention"):
        _run(tmp_path, bars_path, status_path, calendar_path)

    bars_path, status_path, calendar_path, pool = _fixture_inputs(tmp_path / "second")
    bars = pd.read_csv(bars_path, dtype={"symbol": "string"})
    target = _provider_symbol("002156.SZ", pool)
    first = bars.index[bars["symbol"] == target][0]
    bars.loc[first, "high"] = bars.loc[first, "low"] - 1.0
    bars.to_csv(bars_path, index=False)

    with pytest.raises(ValueError, match="OHLC internal consistency"):
        _run(tmp_path / "second", bars_path, status_path, calendar_path)
