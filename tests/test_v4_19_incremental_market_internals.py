from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.v4_19_incremental_market_internals import (
    _evaluate_family,
    _rolling_percentile,
    audit_source_admissibility,
    benjamini_hochberg,
    build_market_internal_feature_blocks,
)

CONTRACT_PATH = Path(
    "configs/research_paradigms/"
    "qqqi_market_internal_incremental_factors_v4_19_research.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _bars(
    symbol: str,
    index: pd.DatetimeIndex,
    *,
    offset: float = 0.0,
) -> pd.DataFrame:
    location = np.arange(len(index), dtype=float)
    if symbol.startswith("^"):
        close = 20.0 + offset + 3.0 * np.sin(location / 23.0)
    else:
        close = (
            100.0
            + offset
            + 0.05 * location
            + 4.0 * np.sin(location / 31.0)
        )
    open_price = close * (1.0 + 0.001 * np.cos(location / 17.0))
    return pd.DataFrame(
        {"date": index, "open": open_price, "close": close}
    )


def _all_bars(index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    symbols = [
        "QQQ",
        "TQQQ",
        "VOO",
        "BIL",
        "SGOV",
        "QQQI",
        "^VIX",
        "^VXN",
        "^VIX9D",
        "^VIX3M",
        "^VVIX",
        "HYG",
        "LQD",
        "SHY",
        "IEF",
        "TLT",
        "SPY",
        "RSP",
        "IWM",
    ]
    return {
        symbol: _bars(symbol, index, offset=float(position))
        for position, symbol in enumerate(symbols)
    }


def _coverage(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "provider": "unit",
                "provider_symbol": symbol,
                "first_date": frame["date"].min().date().isoformat(),
                "last_date": frame["date"].max().date().isoformat(),
                "rows": len(frame),
            }
            for symbol, frame in bars.items()
        ]
    )


def test_builds_exact_frozen_family_blocks() -> None:
    index = pd.date_range("2010-01-04", periods=900, freq="B")
    blocks = build_market_internal_feature_blocks(
        _all_bars(index), index
    )
    contract = _contract()
    assert set(blocks) == set(contract["families"])
    for family, specification in contract["families"].items():
        expected = specification["minimum_feature_block"]
        assert blocks[family].columns.tolist() == expected
        assert blocks[family].index.equals(index)


def test_close_features_do_not_change_before_future_perturbation() -> None:
    index = pd.date_range("2010-01-04", periods=900, freq="B")
    original = _all_bars(index)
    perturbed = {
        symbol: frame.copy() for symbol, frame in original.items()
    }
    cutoff = index[700]
    for frame in perturbed.values():
        future = frame["date"].gt(cutoff)
        frame.loc[future, ["open", "close"]] *= 3.0
    before = build_market_internal_feature_blocks(original, index)
    after = build_market_internal_feature_blocks(perturbed, index)
    for family in before:
        pd.testing.assert_frame_equal(
            before[family].loc[:cutoff],
            after[family].loc[:cutoff],
        )


def test_observation_percentile_survives_sparse_calendar_gap() -> None:
    index = pd.date_range("2010-01-04", periods=600, freq="B")
    series = pd.Series(np.arange(600, dtype=float), index=index)
    series.iloc[400] = np.nan
    percentile = _rolling_percentile(series, 252)
    assert np.isnan(percentile.iloc[400])
    assert np.isfinite(percentile.iloc[401])
    assert np.isclose(percentile.iloc[401], 1.0)


def test_phase_zero_rejects_only_dependent_missing_family() -> None:
    index = pd.date_range("2010-01-04", periods=900, freq="B")
    bars = _all_bars(index)
    del bars["^VVIX"]
    source, families = audit_source_admissibility(
        bars,
        _coverage(bars),
        {"^VVIX": "provider unavailable"},
        _contract(),
    )
    term = families.set_index("family").loc[
        "implied_volatility_term_structure"
    ]
    assert not bool(term["admissible"])
    assert "^VVIX" in term["unavailable_symbols"]
    assert bool(
        families.set_index("family").loc[
            "credit_duration_risk_appetite", "admissible"
        ]
    )
    vvix = source.set_index("symbol").loc["^VVIX"]
    assert vvix["rejection_reason"] == "fetch_failed"


def test_benjamini_hochberg_is_monotone_and_family_level() -> None:
    table = benjamini_hochberg(
        {"a": 0.01, "b": 0.04, "c": 0.20, "d": 0.80}
    ).sort_values("rank")
    assert table["family"].tolist() == ["a", "b", "c", "d"]
    assert table["qvalue"].is_monotonic_increasing
    assert np.isclose(table.iloc[0]["qvalue"], 0.04)
    assert table["qvalue"].between(0.0, 1.0).all()


def test_family_comparator_uses_identical_shared_rows() -> None:
    index = pd.date_range("2010-01-04", "2024-01-31", freq="B")
    location = np.arange(len(index), dtype=float)
    base_features = tuple(f"base_{position}" for position in range(29))
    targets = tuple(_contract()["action_targets"])
    frame = pd.DataFrame(index=index)
    for position, feature in enumerate(base_features):
        frame[feature] = np.sin(location / (position + 7.0))
    for position, target in enumerate(targets):
        frame[target] = (
            0.01 * np.sin(location / (position + 13.0))
            + 0.002 * np.cos(location / 19.0)
        )
    frame["v4_2_execution_state"] = location.astype(int) % 3
    frame["global_training_sample"] = (
        location.astype(int) % 10
    ) == 0
    family = pd.DataFrame(
        {
            "family_a": np.cos(location / 29.0),
            "family_b": np.sin(location / 37.0),
        },
        index=index,
    )
    family.loc[index[1200:1210], "family_a"] = np.nan
    predictions, _, _, coverage, _ = _evaluate_family(
        "unit_family",
        frame,
        base_features,
        targets,
        family,
        _contract(),
    )
    assert not predictions.empty
    assert predictions["position_state"].notna().all()
    for action in (
        "cash_defense",
        "broad_equity",
        "nasdaq_core",
        "nasdaq_acceleration",
    ):
        assert predictions[f"base_predicted_{action}"].notna().all()
        assert predictions[f"candidate_predicted_{action}"].notna().all()
    assert (coverage["training_samples"] >= 100).all()
    assert (coverage["test_samples"] > 0).all()


def test_phase_one_contract_forbids_portfolio_selection() -> None:
    contract = _contract()
    assert contract["boundaries"]["no_portfolio_policy_in_phase_1"]
    assert contract["phase_1_comparison"]["no_portfolio_policy"]
    assert contract["multiple_testing"]["families_tested"] == 4
    assert contract["base_comparator"]["alpha"] == 100.0
