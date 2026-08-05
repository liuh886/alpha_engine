from __future__ import annotations

import numpy as np
import pandas as pd

from src.research.byd_defensive_sleeve_governance import (
    build_period_contribution,
    relative_terminal_return,
)


def test_relative_terminal_return_uses_wealth_ratio() -> None:
    actual = relative_terminal_return(4.440453, 4.336358)
    expected = (1.0 + 4.440453) / (1.0 + 4.336358) - 1.0
    assert np.isclose(actual, expected)
    assert not np.isclose(actual, 4.440453 - 4.336358)


def test_period_contribution_reproduces_governed_515180_shares() -> None:
    rows = []
    values = {
        "development": {"cash": 4.336358, "515180.SH": 4.440453},
        "fixed_validation": {"cash": 0.114394, "515180.SH": 0.145043},
        "retrospective_2025_plus": {"cash": 0.065099, "515180.SH": 0.094483},
    }
    for window, candidates in values.items():
        for candidate, total_return in candidates.items():
            rows.append(
                {
                    "candidate": candidate,
                    "cost_bps": 20.0,
                    "window": window,
                    "total_return": total_return,
                }
            )
    periods = build_period_contribution(pd.DataFrame(rows), ("515180.SH",))
    shares = periods.set_index("window")["positive_contribution_share"]
    assert np.isclose(shares["development"], 0.2615, atol=0.001)
    assert np.isclose(shares["fixed_validation"], 0.3687, atol=0.001)
    assert np.isclose(shares["retrospective_2025_plus"], 0.3698, atol=0.001)
    assert float(shares.max()) < 0.60
