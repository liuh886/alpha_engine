from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.byd_v1_2_recovery_state import (
    CANONICAL_ADJUSTED_SHA256,
    CANONICAL_CUTOFF,
    CANONICAL_MANIFEST_SHA256,
    CANONICAL_SCHEMA,
    MODEL_FACTORS,
    MODEL_RULES,
    OPEN_LABEL_POLICY,
    build_research_dataset,
    build_v1_2_decision_position,
    dataframe_sha256,
    execute_next_eligible_open,
    load_canonical_snapshot,
)


def _bars(periods: int = 1300) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2011-01-03", periods=periods)
    rng = np.random.default_rng(513)
    regime = np.where(
        (np.arange(periods) // 180) % 2 == 0,
        0.0007,
        -0.0002,
    )
    returns = regime + rng.normal(0.0, 0.018, periods)
    close = 25.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.003, periods))
    high = np.maximum(open_, close) * (
        1.0 + rng.uniform(0.001, 0.015, periods)
    )
    low = np.minimum(open_, close) * (
        1.0 - rng.uniform(0.001, 0.015, periods)
    )
    bars = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(
                1_000_000,
                20_000_000,
                periods,
            ).astype(float),
        }
    )
    sessions = pd.DataFrame(
        {
            "date": dates,
            "open_research_eligible": np.ones(periods, dtype=bool),
        }
    )
    return bars, sessions


def test_model_contract_is_frozen_and_low_dimensional() -> None:
    assert MODEL_FACTORS == (
        "drawdown_252",
        "mom_120",
        "distance_from_low_20",
        "momentum_accel_20_60",
        "open_return_autocorr_20",
    )
    assert MODEL_RULES["core_position"] == 0.75
    assert MODEL_RULES["full_position"] == 1.0


def test_future_mutation_does_not_change_prior_features() -> None:
    bars, sessions = _bars()
    first = build_research_dataset(bars, sessions)
    changed = bars.copy()
    changed.loc[
        changed.index >= 1200,
        ["open", "high", "low", "close"],
    ] *= 1.5
    second = build_research_dataset(changed, sessions)
    cutoff = first.index[1199]
    pd.testing.assert_frame_equal(
        first.loc[:cutoff, list(MODEL_FACTORS)],
        second.loc[:cutoff, list(MODEL_FACTORS)],
    )


def test_forward_labels_require_eligible_entry_and_exit_opens() -> None:
    bars, sessions = _bars(500)
    sessions.loc[120, "open_research_eligible"] = False
    dataset = build_research_dataset(bars, sessions)
    signal_for_entry = dataset.index[119]
    signal_for_exit_10 = dataset.index[109]
    assert np.isnan(dataset.loc[signal_for_entry, "forward_open_return_10"])
    assert np.isnan(dataset.loc[signal_for_exit_10, "forward_open_return_10"])


def test_execution_defers_position_change_on_quarantined_open() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="D")
    decision = pd.Series([0.75, 1.0, 1.0, 0.75, 0.75], index=index)
    eligible = pd.Series([True, True, False, True, True], index=index)
    executed = execute_next_eligible_open(
        decision,
        eligible,
        initial_position=0.75,
    )
    assert executed.tolist() == [0.75, 0.75, 0.75, 1.0, 0.75]


def test_state_model_uses_only_declared_positions() -> None:
    bars, sessions = _bars()
    dataset = build_research_dataset(bars, sessions)
    position = build_v1_2_decision_position(dataset)
    assert set(position.unique()).issubset({0.75, 1.0})


def test_canonical_loader_fails_closed_on_wrong_identity(
    tmp_path: Path,
) -> None:
    bars, sessions = _bars(20)
    adjusted = bars.copy()
    manifest = {
        "schema_version": CANONICAL_SCHEMA,
        "adjusted_sha256": dataframe_sha256(adjusted),
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "cutoff": CANONICAL_CUTOFF,
        "open_label_policy": OPEN_LABEL_POLICY,
        "data_quality_status": "canonical_v1_pass",
        "cross_provider_stitching": False,
        "rows": len(adjusted),
    }
    adjusted.to_csv(
        tmp_path / "adjusted_ohlcv.csv",
        index=False,
        float_format="%.12f",
    )
    sessions.to_csv(tmp_path / "session_audit.csv", index=False)
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="adjusted_sha256"):
        load_canonical_snapshot(tmp_path)
    assert manifest["adjusted_sha256"] != CANONICAL_ADJUSTED_SHA256
