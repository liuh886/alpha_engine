from __future__ import annotations

import pytest

from scripts.refresh_qqq_v4_3_formal import QqqV43RefreshError, _verify_historical_prefix


def _package(weight_sgov: float = 0.5) -> dict[str, object]:
    return {
        "report": [
            {
                "date": "2026-08-05",
                "period_return": 0.01,
                "gross_return": 0.011,
                "transaction_cost": 0.001,
                "weight_QQQI": 0.5,
                "weight_QQQ": 0.0,
                "weight_TQQQ": 0.0,
                "weight_SGOV": weight_sgov,
                "position_state": 0,
            }
        ]
    }


def test_refresh_prefix_accepts_exact_v43_history() -> None:
    _verify_historical_prefix(_package(), _package())


def test_refresh_prefix_rejects_changed_sgov_history() -> None:
    with pytest.raises(QqqV43RefreshError, match="weight_SGOV"):
        _verify_historical_prefix(_package(), _package(weight_sgov=0.4))
