import asyncio

import pytest

from src.api.routers.factors import AttributionRequest, attribute_factor_returns
from src.research import factor_attribution


class _FakeReport:
    def to_dict(self):
        return {
            "total_return": 4.2,
            "excess_return": 1.1,
            "factor_coverage": 63.0,
            "attribution_confidence": 0.72,
            "unexplained_return": 0.4,
            "factor_contributions": [
                {
                    "factor_name": "momentum",
                    "factor_expression": "$close / Ref($close, 20) - 1",
                    "factor_ic": 0.08,
                    "return_contribution_pct": 12.5,
                    "risk_contribution_pct": 25.0,
                    "exposure": 0.4,
                }
            ],
        }


def test_attribution_api_exposes_r_squared_and_stable_factor_ids(monkeypatch):
    monkeypatch.setattr(factor_attribution, "attribute_returns", lambda **_: _FakeReport())

    response = asyncio.run(attribute_factor_returns(AttributionRequest()))

    assert response["summary"]["factor_coverage"] == pytest.approx(0.72)
    assert response["factors"][0]["factor_id"] == 1
    assert response["factors"][0]["risk_contribution"] == pytest.approx(25.0)
