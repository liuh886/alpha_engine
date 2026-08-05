from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.cn130_tail_factor_discovery import (
    PORTFOLIO_VARIANTS,
    choose_holdings,
    sector_relative_factor,
)


def test_sector_relative_factor_preserves_index() -> None:
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp("2025-01-02")], ["000001", "000002", "000003", "000004"]],
        names=["datetime", "instrument"],
    )
    values = pd.Series([1.0, 2.0, 3.0, 4.0], index=index)
    sectors = pd.Series(["A", "A", "B", "B"], index=index)
    result = sector_relative_factor(values, sectors)
    assert result.index.equals(index)
    assert np.allclose(result.to_numpy(), [0.5, 1.0, 0.5, 1.0])


def test_global_sector_cap_obeys_cap() -> None:
    day = pd.DataFrame(
        {
            "instrument": [f"{i:06d}" for i in range(8)],
            "sector": ["A", "A", "A", "B", "B", "C", "D", "E"],
            "score": [8, 7, 6, 5, 4, 3, 2, 1],
            "execution_forward_return": [0.01] * 8,
        }
    )
    variant = next(v for v in PORTFOLIO_VARIANTS if v.variant_id == "global_top5_sector_cap1")
    chosen = choose_holdings(day, variant)
    assert len(chosen) == 5
    assert chosen["sector"].value_counts().max() == 1


def test_sector_3x2_selects_six_names() -> None:
    day = pd.DataFrame(
        {
            "instrument": [f"{i:06d}" for i in range(10)],
            "sector": ["A", "A", "A", "B", "B", "B", "C", "C", "D", "E"],
            "score": [10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
            "execution_forward_return": [0.01] * 10,
        }
    )
    variant = next(v for v in PORTFOLIO_VARIANTS if v.variant_id == "sector_3x2")
    chosen = choose_holdings(day, variant)
    assert len(chosen) == 6
    assert chosen["sector"].nunique() == 3
    assert chosen["sector"].value_counts().max() == 2
