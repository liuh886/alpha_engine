from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_core_tactical_v1 import (
    CANDIDATE_NAMES,
    build_candidate_positions,
    build_features,
    evaluate_research,
)


def _synthetic_ohlcv(
    periods: int = 3900, start: str = "2010-01-04"
) -> pd.DataFrame:
    index = pd.bdate_range(start, periods=periods)
    rng = np.random.default_rng(500)
    returns = rng.normal(0.0007, 0.021, periods)
    returns[650:850] -= 0.0018
    returns[1600:1780] += 0.0015
    returns[2600:2780] -= 0.0012
    close = 18.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.003, periods))
    high = np.maximum(open_, close) * (
        1.0 + rng.uniform(0.001, 0.018, periods)
    )
    low = np.minimum(open_, close) * (
        1.0 - rng.uniform(0.001, 0.018, periods)
    )
    return pd.DataFrame(
        {
            "date": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1_000_000, 9_000_000, periods),
        }
    )


def test_candidate_set_and_position_boundaries_are_frozen() -> None:
    features = build_features(_synthetic_ohlcv(800))
    positions = build_candidate_positions(features)
    assert tuple(positions) == CANDIDATE_NAMES
    for position in positions.values():
        assert float(position.min()) >= 0.50
        assert float(position.max()) <= 1.00
        assert set(position.unique()).issubset({0.50, 0.75, 1.00})


def test_future_mutation_cannot_change_prior_targets() -> None:
    original = _synthetic_ohlcv(900)
    features_a = build_features(original)
    targets_a = build_candidate_positions(features_a)

    changed = original.copy()
    changed.loc[changed.index >= 780, ["open", "high", "low", "close"]] *= 1.8
    features_b = build_features(changed)
    targets_b = build_candidate_positions(features_b)

    cutoff = features_a.index[779]
    for name in CANDIDATE_NAMES:
        pd.testing.assert_series_equal(
            targets_a[name].loc[:cutoff],
            targets_b[name].loc[:cutoff],
            check_names=True,
        )


def test_regime_momentum_uses_hysteresis() -> None:
    features = build_features(_synthetic_ohlcv(1000))
    positions = build_candidate_positions(features)
    core75 = positions["core75_regime_mom_120"]
    core50 = positions["core50_regime_mom_120"]
    assert np.allclose((core75 - 0.75) * 2.0, core50 - 0.50)
    assert core75.nunique() >= 1


def test_research_result_preserves_governance_boundary() -> None:
    daily = _synthetic_ohlcv()
    cutoff = pd.Timestamp(daily["date"].iloc[-1])
    contract = {
        "experiment_id": "test_byd_core_tactical",
        "parent_issue": 500,
        "costs": {
            "primary_bps_per_turnover_unit": 20,
            "stress_bps_per_turnover_unit": [10, 20, 40],
        },
        "windows": {
            "development_start": "2012-01-01",
            "development_end": "2020-12-31",
            "validation_start": "2021-01-01",
            "validation_end": "2022-12-31",
            "retrospective_holdout_start": "2023-01-01",
            "retrospective_holdout_end": cutoff.strftime("%Y-%m-%d"),
        },
    }
    summary = evaluate_research(daily, contract)
    assert summary["decision"] in {
        "byd_v1_0_core_tactical_supported",
        "byd_v1_0_core_tactical_not_supported",
    }
    assert len(summary["candidate_rows"]) == len(CANDIDATE_NAMES)
    assert summary["research_only"] is True
    assert summary["trade_ready"] is False
    assert summary["prospective_confirmation_required"] is True
    if summary["selected_candidate"] is not None:
        assert summary["selected_latest_close_target_for_next_open"] in {
            0.50,
            0.75,
            1.00,
        }
