import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.small_pool_rotation import run_small_pool_rotation


SPEC_PATH = Path("configs/research_paradigms/us_small_pool_sector_rotation_v1.yaml")
POOL_PATH = Path("configs/pools/us_small_pool_v1.yaml")


def _pool() -> dict:
    return yaml.safe_load(POOL_PATH.read_text(encoding="utf-8"))


def _synthetic_prices() -> pd.DataFrame:
    pool = _pool()
    dates = pd.bdate_range("2020-01-02", periods=520)
    basket_steps = {
        "semiconductor_compute": 0.35,
        "optical_networking": 0.28,
        "ai_infrastructure_power": 0.22,
        "mega_cap_platforms": 0.18,
        "china_consumer_internet": 0.10,
        "defensive_consumer": 0.06,
        "consumer_growth": 0.16,
    }
    symbol_steps = {
        symbol: basket_steps[basket_name]
        for basket_name, basket in pool["baskets"].items()
        for symbol in basket["symbols"]
    }
    symbol_steps["QQQ"] = 0.12
    symbol_steps["^SOX"] = 0.30

    rows: list[dict] = []
    for symbol, step in symbol_steps.items():
        close = 100.0 + step * np.arange(len(dates), dtype=float)
        for date, value in zip(dates, close, strict=True):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": value,
                    "high": value + 1.0,
                    "low": value - 1.0,
                    "close": value,
                    "volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def _read_rows(output_dir: Path, filename: str) -> list[dict]:
    payload = json.loads((output_dir / filename).read_text(encoding="utf-8"))
    return list(payload["rows"])


def test_rotation_selects_strong_baskets_and_excludes_references(
    tmp_path: Path,
) -> None:
    prices_path = tmp_path / "prices.csv"
    output_dir = tmp_path / "evidence"
    _synthetic_prices().to_csv(prices_path, index=False)

    decision = run_small_pool_rotation(
        spec_path=SPEC_PATH,
        prices_csv=prices_path,
        output_dir=output_dir,
    )
    rotations = _read_rows(output_dir, "rotation_history.json")
    active = [row for row in rotations if row["selected_baskets"]]

    assert decision["decision"] == "rotation_implementation_contract_passed"
    assert decision["candidate_count"] == 23
    assert decision["basket_count"] == 7
    assert active
    assert active[-1]["selected_baskets"] == [
        "semiconductor_compute",
        "optical_networking",
    ]
    assert active[-1]["actionable_from"] > active[-1]["date"]
    for row in active:
        assert len(row["selected_baskets"]) <= 2
        selected_symbols = {
            security["symbol"]
            for securities in row["selected_symbols_by_basket"].values()
            for security in securities
        }
        assert "QQQ" not in selected_symbols
        assert "SOX" not in selected_symbols
        assert all(
            len(securities) <= 2
            for securities in row["selected_symbols_by_basket"].values()
        )


def test_portfolio_is_cash_capable_and_gross_exposure_is_bounded(
    tmp_path: Path,
) -> None:
    prices_path = tmp_path / "prices.csv"
    output_dir = tmp_path / "evidence"
    _synthetic_prices().to_csv(prices_path, index=False)
    run_small_pool_rotation(
        spec_path=SPEC_PATH,
        prices_csv=prices_path,
        output_dir=output_dir,
    )

    portfolio = _read_rows(output_dir, "portfolio_state_history.json")
    assert portfolio
    assert all(0.0 <= row["gross_exposure"] <= 1.0 for row in portfolio)
    assert all(0.0 <= row["cash_weight"] <= 1.0 for row in portfolio)
    assert any(row["cash_weight"] == 1.0 for row in portfolio)
    assert any(row["gross_exposure"] > 0.0 for row in portfolio)


def test_future_prices_do_not_rewrite_prior_rotation_decisions(
    tmp_path: Path,
) -> None:
    base = _synthetic_prices()
    cutoff = pd.Timestamp("2021-06-30")

    base_path = tmp_path / "base.csv"
    base_output = tmp_path / "base-output"
    base.to_csv(base_path, index=False)
    run_small_pool_rotation(
        spec_path=SPEC_PATH,
        prices_csv=base_path,
        output_dir=base_output,
    )

    mutated = base.copy()
    future = pd.to_datetime(mutated["date"]) > cutoff
    mutated.loc[future, ["open", "high", "low", "close"]] *= 7.0
    mutated_path = tmp_path / "mutated.csv"
    mutated_output = tmp_path / "mutated-output"
    mutated.to_csv(mutated_path, index=False)
    run_small_pool_rotation(
        spec_path=SPEC_PATH,
        prices_csv=mutated_path,
        output_dir=mutated_output,
    )

    for filename in (
        "basket_score_history.json",
        "rotation_history.json",
        "portfolio_state_history.json",
    ):
        before = [
            row
            for row in _read_rows(base_output, filename)
            if pd.Timestamp(row["date"]) <= cutoff
        ]
        after = [
            row
            for row in _read_rows(mutated_output, filename)
            if pd.Timestamp(row["date"]) <= cutoff
        ]
        assert before == after


def test_missing_candidate_fails_closed(tmp_path: Path) -> None:
    prices = _synthetic_prices()
    prices = prices[prices["symbol"] != "KO"]
    prices_path = tmp_path / "missing.csv"
    prices.to_csv(prices_path, index=False)

    with pytest.raises(ValueError, match="KO"):
        run_small_pool_rotation(
            spec_path=SPEC_PATH,
            prices_csv=prices_path,
            output_dir=tmp_path / "evidence",
        )


def test_runner_writes_manifest_bound_non_performance_outputs(
    tmp_path: Path,
) -> None:
    prices_path = tmp_path / "prices.csv"
    output_dir = tmp_path / "evidence"
    _synthetic_prices().to_csv(prices_path, index=False)

    decision = run_small_pool_rotation(
        spec_path=SPEC_PATH,
        prices_csv=prices_path,
        output_dir=output_dir,
    )
    manifest = json.loads(
        (output_dir / "evidence_manifest.json").read_text(encoding="utf-8")
    )

    assert decision["performance_evaluated"] is False
    assert decision["reserved_performance_opened"] is False
    assert manifest["pool_membership_identity_sha256"]
    assert manifest["timing_formula_identity_sha256"]
    assert set(manifest["outputs"]) == {
        "pool_identity.json",
        "basket_score_history.json",
        "rotation_history.json",
        "portfolio_state_history.json",
        "decision.json",
    }
    for filename in (
        "pool_identity.json",
        "basket_score_history.json",
        "rotation_history.json",
        "portfolio_state_history.json",
        "decision.json",
        "evidence_manifest.json",
    ):
        assert (output_dir / filename).is_file()
