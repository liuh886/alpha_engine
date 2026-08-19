import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.hierarchical_pool_rotation import (
    _security_scores,
    run_hierarchical_pool_rotation,
)


US_SPEC_PATH = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2_draft.yaml"
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pool_from_spec(spec_path: Path) -> dict:
    spec = _load(spec_path)
    return _load(Path(spec["pool_spec"]))


def _provider_symbol(display: str, pool: dict) -> str:
    if display in pool.get("references", {}):
        return str(pool["references"][display].get("provider_symbol", display))
    if display in pool.get("symbol_metadata", {}):
        return str(pool["symbol_metadata"][display].get("provider_symbol", display))
    return display


def _synthetic_prices(spec_path: Path) -> pd.DataFrame:
    spec = _load(spec_path)
    pool = _pool_from_spec(spec_path)
    dates = pd.bdate_range("2020-01-02", periods=520)
    basket_steps = {
        name: 0.32 - 0.035 * index
        for index, name in enumerate(pool["baskets"])
    }
    steps = {
        symbol: basket_steps[name] - 0.008 * member_index
        for name, basket in pool["baskets"].items()
        for member_index, symbol in enumerate(basket["symbols"])
    }
    benchmark = str(spec["market_regime"]["reference"])
    context = str(spec["sector_context"]["reference"])
    steps[benchmark] = 0.10
    steps[context] = 0.20

    rows: list[dict] = []
    for display, step in steps.items():
        provider = _provider_symbol(display, pool)
        base = 100.0 + step * np.arange(len(dates), dtype=float)
        phase = (sum(ord(char) for char in display) % 11) / 10.0
        close = base + 0.35 * np.sin(np.arange(len(dates)) / 7.0 + phase)
        for date, value in zip(dates, close, strict=True):
            rows.append(
                {
                    "date": date,
                    "symbol": provider,
                    "open": value - 0.10,
                    "high": value + 0.80,
                    "low": value - 0.80,
                    "close": value,
                    "volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def _rows(output_dir: Path, filename: str) -> list[dict]:
    payload = json.loads((output_dir / filename).read_text(encoding="utf-8"))
    return list(payload["rows"])


def test_within_basket_composite_score_overrides_state_priority() -> None:
    spec = _load(US_SPEC_PATH)
    spec = copy.deepcopy(spec)
    spec["rotation"]["maximum_selected_symbols_per_basket"] = 2
    date = pd.Timestamp("2025-01-02")
    indicators = pd.DataFrame(
        [
            {
                "date": date,
                "symbol": "LOW_ENTER",
                "relative_momentum_63_vs_benchmark": 0.01,
                "momentum_20": 0.01,
                "drawdown_from_63d_high": -0.20,
                "realized_volatility_20": 0.08,
            },
            {
                "date": date,
                "symbol": "HIGH_HOLD",
                "relative_momentum_63_vs_benchmark": 0.20,
                "momentum_20": 0.20,
                "drawdown_from_63d_high": -0.01,
                "realized_volatility_20": 0.01,
            },
            {
                "date": date,
                "symbol": "MID_HOLD",
                "relative_momentum_63_vs_benchmark": 0.10,
                "momentum_20": 0.10,
                "drawdown_from_63d_high": -0.05,
                "realized_volatility_20": 0.02,
            },
        ]
    )
    states = pd.DataFrame(
        [
            {
                "date": date,
                "symbol": "LOW_ENTER",
                "state": "ENTER",
                "reason_codes": ["ENTER"],
                "trailing_stop_3atr": 90.0,
            },
            {
                "date": date,
                "symbol": "HIGH_HOLD",
                "state": "HOLD",
                "reason_codes": ["HOLD"],
                "trailing_stop_3atr": 95.0,
            },
            {
                "date": date,
                "symbol": "MID_HOLD",
                "state": "HOLD",
                "reason_codes": ["HOLD"],
                "trailing_stop_3atr": 93.0,
            },
        ]
    )

    selected, score_rows = _security_scores(
        date,
        "test_basket",
        ["LOW_ENTER", "HIGH_HOLD", "MID_HOLD"],
        indicators,
        states,
        spec,
    )

    assert [row["symbol"] for row in selected] == ["HIGH_HOLD", "MID_HOLD"]
    low = next(row for row in score_rows if row["symbol"] == "LOW_ENTER")
    assert low["state"] == "ENTER"
    assert low["within_basket_selected"] is False
    assert low["security_composite_percentile"] < 0.50


def test_us_v2_writes_security_scores_and_market_specific_outputs(
    tmp_path: Path,
) -> None:
    prices_path = tmp_path / "us.csv"
    output_dir = tmp_path / "us-output"
    _synthetic_prices(US_SPEC_PATH).to_csv(prices_path, index=False)

    decision = run_hierarchical_pool_rotation(
        spec_path=US_SPEC_PATH,
        prices_csv=prices_path,
        output_dir=output_dir,
    )

    assert decision["decision"] == "generic_hierarchical_rotation_engine_ready"
    assert decision["market"] == "us"
    assert decision["benchmark"] == "QQQ"
    assert decision["candidate_count"] == 23
    assert decision["performance_evaluated"] is False
    assert decision["reserved_performance_opened"] is False
    assert decision["authoritative_mode"] is False

    rotations = _rows(output_dir, "rotation_history.json")
    security_scores = _rows(output_dir, "security_score_history.json")
    portfolio = _rows(output_dir, "portfolio_state_history.json")
    assert rotations
    assert security_scores
    assert portfolio
    assert all(row["market"] == "us" and row["benchmark"] == "QQQ" for row in rotations)
    assert all(row["market"] == "us" and row["benchmark"] == "QQQ" for row in portfolio)
    selected_symbols = {
        position["symbol"]
        for row in portfolio
        for position in row["positions"]
        if position["target_weight"] > 0
    }
    assert "QQQ" not in selected_symbols
    assert "SOX" not in selected_symbols
    assert any(row["portfolio_selected"] for row in security_scores)
    assert all(
        0.0 <= float(row["cash_weight"]) <= 1.0
        and 0.0 <= float(row["gross_exposure"]) <= 1.0
        for row in portfolio
    )
    for filename in (
        "pool_identity.json",
        "basket_score_history.json",
        "security_score_history.json",
        "rotation_history.json",
        "portfolio_state_history.json",
        "decision.json",
        "evidence_manifest.json",
    ):
        assert (output_dir / filename).is_file()


def test_future_prices_do_not_rewrite_prior_hierarchical_selection(
    tmp_path: Path,
) -> None:
    base = _synthetic_prices(US_SPEC_PATH)
    cutoff = pd.Timestamp("2021-06-30")
    base_path = tmp_path / "base.csv"
    base_output = tmp_path / "base-output"
    base.to_csv(base_path, index=False)
    run_hierarchical_pool_rotation(
        spec_path=US_SPEC_PATH,
        prices_csv=base_path,
        output_dir=base_output,
    )

    mutated = base.copy()
    future = pd.to_datetime(mutated["date"]) > cutoff
    mutated.loc[future, ["open", "high", "low", "close"]] *= 7.0
    mutated_path = tmp_path / "mutated.csv"
    mutated_output = tmp_path / "mutated-output"
    mutated.to_csv(mutated_path, index=False)
    run_hierarchical_pool_rotation(
        spec_path=US_SPEC_PATH,
        prices_csv=mutated_path,
        output_dir=mutated_output,
    )

    for filename in (
        "basket_score_history.json",
        "security_score_history.json",
        "rotation_history.json",
        "portfolio_state_history.json",
    ):
        before = [
            row
            for row in _rows(base_output, filename)
            if pd.Timestamp(row["date"]) <= cutoff
        ]
        after = [
            row
            for row in _rows(mutated_output, filename)
            if pd.Timestamp(row["date"]) <= cutoff
        ]
        assert before == after


def test_missing_us_candidate_fails_closed(tmp_path: Path) -> None:
    prices = _synthetic_prices(US_SPEC_PATH)
    prices = prices[prices["symbol"] != "KO"]
    prices_path = tmp_path / "missing.csv"
    prices.to_csv(prices_path, index=False)

    with pytest.raises(ValueError, match="KO"):
        run_hierarchical_pool_rotation(
            spec_path=US_SPEC_PATH,
            prices_csv=prices_path,
            output_dir=tmp_path / "evidence",
        )
