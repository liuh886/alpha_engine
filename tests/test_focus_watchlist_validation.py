import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.focus_watchlist_signal import load_long_ohlcv_csv
from src.research.focus_watchlist_validation import run_focus_watchlist_validation


SPEC_PATH = Path("configs/research_paradigms/us_focus_watchlist_cycle_signal_v1.yaml")


def _spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _synthetic_prices() -> pd.DataFrame:
    spec = _spec()
    dates = pd.bdate_range("2019-01-02", "2026-08-31")
    index = np.arange(len(dates), dtype=float)
    rows: list[dict] = []
    for offset, symbol in enumerate(spec["universe"]["symbols"]):
        provider_symbol = "^SOX" if symbol == "SOX" else symbol
        if symbol == "QQQ":
            close = 100.0 + 0.045 * index + 11.0 * np.sin(index / 75.0)
        elif symbol == "SOX":
            close = 90.0 + 0.060 * index + 16.0 * np.sin(index / 58.0)
        else:
            drift = 0.035 + (offset % 6) * 0.012
            amplitude = 7.0 + (offset % 5) * 2.0
            close = 40.0 + offset + drift * index + amplitude * np.sin(
                index / (42.0 + offset % 7)
            )
        close = np.maximum(close, 5.0)
        for date, value in zip(dates, close, strict=True):
            rows.append(
                {
                    "date": date,
                    "symbol": provider_symbol,
                    "open": value * 0.998,
                    "high": value * 1.012,
                    "low": value * 0.988,
                    "close": value,
                    "volume": 1_000_000 + offset * 10_000,
                }
            )
    return pd.DataFrame(rows)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_validation_writes_complete_observed_evidence_outputs(tmp_path: Path) -> None:
    prices_path = tmp_path / "prices.csv"
    output_dir = tmp_path / "validation"
    _synthetic_prices().to_csv(prices_path, index=False)

    decision = run_focus_watchlist_validation(
        spec_path=SPEC_PATH,
        prices_csv=prices_path,
        output_dir=output_dir,
    )

    assert decision["decision"] in {
        "focus_signal_not_supported_on_observed_evidence",
        "focus_signal_independent_validation_required",
    }
    assert decision["reserved_performance_opened"] is False
    assert decision["observed_evidence_end"] == "2026-06-30"
    for filename in (
        "per_symbol_metrics.json",
        "aggregate_metrics.json",
        "regime_metrics.json",
        "forward_state_metrics.json",
        "validation_manifest.json",
        "decision.json",
    ):
        assert (output_dir / filename).is_file()

    per_symbol = _read_json(output_dir / "per_symbol_metrics.json")["windows"]
    expected = set(_spec()["universe"]["signal_symbols"])
    assert set(per_symbol["development_observed"]) == expected
    assert set(per_symbol["falsification_only"]) == expected
    assert "QQQ" not in expected
    assert "SOX" not in expected


def test_reserved_price_mutation_cannot_change_observed_metrics(tmp_path: Path) -> None:
    base = _synthetic_prices()
    base_path = tmp_path / "base.csv"
    base.to_csv(base_path, index=False)
    base_output = tmp_path / "base_output"
    run_focus_watchlist_validation(
        spec_path=SPEC_PATH,
        prices_csv=base_path,
        output_dir=base_output,
    )

    mutated = base.copy()
    reserved = pd.to_datetime(mutated["date"]) >= pd.Timestamp("2026-07-01")
    mutated.loc[reserved, ["open", "high", "low", "close"]] *= 9.0
    mutated_path = tmp_path / "mutated.csv"
    mutated.to_csv(mutated_path, index=False)
    mutated_output = tmp_path / "mutated_output"
    run_focus_watchlist_validation(
        spec_path=SPEC_PATH,
        prices_csv=mutated_path,
        output_dir=mutated_output,
    )

    for filename in (
        "per_symbol_metrics.json",
        "aggregate_metrics.json",
        "regime_metrics.json",
        "forward_state_metrics.json",
        "decision.json",
    ):
        assert _read_json(base_output / filename) == _read_json(mutated_output / filename)


def test_validation_fails_if_reference_or_target_is_missing(tmp_path: Path) -> None:
    prices = _synthetic_prices()
    prices = prices[prices["symbol"] != "AMD"]
    prices_path = tmp_path / "missing.csv"
    prices.to_csv(prices_path, index=False)

    with pytest.raises(ValueError, match="missing required focus symbols"):
        load_long_ohlcv_csv(prices_path, _spec())
