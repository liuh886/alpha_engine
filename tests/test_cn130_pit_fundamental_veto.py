from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_cn130_pit_fundamental_veto import (
    _partial_corr,
    choose_architecture,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument": ["1", "2", "3", "4"],
            "sector": ["A", "A", "A", "A"],
            "score": [4.0, 3.0, 2.0, 1.0],
            "selected_fundamental_composite": [0.1, 0.9, 0.8, 0.2],
        }
    )


def test_shortlist_reranker_only_uses_r0_top3() -> None:
    chosen, fallback = choose_architecture(
        _frame(), "S1_r0_top3_fundamental_rerank"
    )
    assert fallback == 0
    assert chosen.iloc[0]["instrument"] == "2"


def test_bottom_tercile_veto_preserves_highest_surviving_r0() -> None:
    chosen, _ = choose_architecture(
        _frame(), "S2_fundamental_bottom_tercile_veto"
    )
    assert chosen.iloc[0]["instrument"] == "2"


def test_median_gate_uses_r0_after_quality_filter() -> None:
    chosen, fallback = choose_architecture(_frame(), "S3_fundamental_median_gate")
    assert fallback == 0
    assert chosen.iloc[0]["instrument"] == "2"


def test_partial_corr_removes_shared_control() -> None:
    control = pd.Series(np.arange(20, dtype=float))
    component = control * 2.0 + pd.Series(np.tile([-1.0, 1.0], 10))
    target = control * 3.0 + pd.Series(np.tile([-1.0, 1.0], 10))
    assert _partial_corr(component, target, control) > 0.99
