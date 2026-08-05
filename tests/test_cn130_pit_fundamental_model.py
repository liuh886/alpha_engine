from __future__ import annotations

import pandas as pd

from scripts.run_cn130_pit_fundamental_model import (
    build_period_facts,
    choose_holdings,
    latest_pit_snapshot,
    robust_growth,
    score_snapshot,
)


def _events() -> pd.DataFrame:
    rows = []
    for year, available, revenue, income, assets, liabilities, equity in (
        (2022, "2023-04-01", 100.0, 10.0, 200.0, 80.0, 120.0),
        (2023, "2024-04-01", 120.0, 15.0, 220.0, 84.0, 136.0),
    ):
        for field, value in {
            "revenue": revenue,
            "net_income": income,
            "total_assets": assets,
            "total_liabilities": liabilities,
            "stockholders_equity": equity,
            "basic_eps": income / 10.0,
        }.items():
            rows.append(
                {
                    "symbol": "000001",
                    "fiscal_period_end": f"{year}-12-31",
                    "fiscal_year": year,
                    "fiscal_period": "FY",
                    "available_at": pd.Timestamp(available),
                    "field": field,
                    "value": value,
                    "revision_sequence": 0,
                    "event_id": f"{year}-{field}",
                }
            )
    return pd.DataFrame(rows)


def test_period_facts_use_same_period_prior_year() -> None:
    facts = build_period_facts(_events())
    row = facts.loc[facts["fiscal_year"] == 2023].iloc[0]
    assert abs(row["revenue_yoy"] - 0.20) < 1e-12
    assert row["available_component_count"] >= 6


def test_pit_snapshot_never_uses_future_disclosure() -> None:
    facts = build_period_facts(_events())
    before = latest_pit_snapshot(facts, pd.Timestamp("2024-03-31"))
    after = latest_pit_snapshot(facts, pd.Timestamp("2024-04-02"))
    assert int(before.iloc[0]["fiscal_year"]) == 2022
    assert int(after.iloc[0]["fiscal_year"]) == 2023


def test_robust_growth_handles_negative_base() -> None:
    result = robust_growth(
        pd.Series([5.0]), pd.Series([-5.0]), pd.Series([100.0])
    )
    assert result.notna().all()
    assert float(result.iloc[0]) == 2.0


def test_fallback_candidate_uses_r0_when_sector_coverage_is_low() -> None:
    frame = pd.DataFrame(
        {
            "instrument": ["000001", "000002"],
            "sector": ["A", "A"],
            "score": [2.0, 1.0],
            "fundamental_composite": [0.1, 0.9],
        }
    )
    chosen, fallback = choose_holdings(
        frame, ["A"], "F3_half_blend_fallback", {"A": 0.5}
    )
    assert fallback == 1
    assert chosen.iloc[0]["instrument"] == "000001"


def test_score_snapshot_normalizes_nullable_object_boolean_mask() -> None:
    frame = pd.DataFrame(
        {
            "sector": ["A", "A", "A"],
            "fiscal_period": ["FY", "FY", "FY"],
            "staleness_days": [30, 30, 30],
            "usable_fundamental": pd.Series([True, False, None], dtype="object"),
            "revenue_yoy": [0.1, 0.2, 0.3],
            "net_income_yoy_robust": [0.1, 0.2, 0.3],
            "net_margin": [0.1, 0.2, 0.3],
            "roe_proxy": [0.1, 0.2, 0.3],
            "asset_turnover": [0.1, 0.2, 0.3],
            "inverse_leverage": [0.1, 0.2, 0.3],
        }
    )
    scored = score_snapshot(frame)
    assert scored["usable_fundamental"].dtype == bool
    assert pd.notna(scored.loc[0, "fundamental_composite"])
    assert pd.isna(scored.loc[1, "fundamental_composite"])
    assert pd.isna(scored.loc[2, "fundamental_composite"])
