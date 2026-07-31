from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.research.factor_knowledge_registry import FactorKnowledgeRegistry
from src.research.fundamental_acceleration import (
    build_factor_history,
    compute_pit_features,
    register_factor_cards,
)


def _contract() -> dict:
    return {
        "benchmark": "QQQ",
        "stable_factor_key": "fundamental_acceleration_equal_weight",
        "factor_version": "1.0.0",
        "components": {
            "revenue_growth_acceleration": {
                "definition": "latest YoY revenue growth minus previous quarter YoY growth"
            },
            "gross_margin_yoy_change": {
                "definition": "latest gross margin minus same quarter one year earlier"
            },
        },
        "portfolio": {
            "evaluation_interval_sessions": 20,
            "minimum_holding_sessions": 40,
            "entry_top_fraction": 0.30,
            "retention_top_fraction": 0.60,
            "retention_min_percentile": 0.40,
            "maximum_replacements_per_basket_per_evaluation": 1,
            "maximum_holdings_per_basket": 2,
            "eligibility": {"price_above_sma_sessions": 100},
        },
    }


def _pool() -> dict:
    return {
        "references": {"QQQ": {"role": "benchmark"}},
        "baskets": {
            "test_basket": {
                "symbols": ["AAA", "BBB", "CCC"],
            }
        },
    }


def test_quarterly_features_use_growth_acceleration_and_margin_change() -> None:
    periods = pd.date_range("2024-03-31", periods=6, freq="QE")
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"] * 6,
            "fiscal_period_end": periods,
            "filed_date": periods + pd.Timedelta(days=35),
            "revenue": [100.0, 110.0, 120.0, 130.0, 125.0, 150.0],
            "gross_profit": [40.0, 44.0, 48.0, 52.0, 55.0, 66.0],
            "currency": ["USD"] * 6,
            "form_type": ["10-Q"] * 6,
            "accession_id": [f"a{i}" for i in range(6)],
        }
    )
    features = compute_pit_features(frame)
    latest = features.iloc[-1]

    current_yoy = 150.0 / 110.0 - 1.0
    previous_yoy = 125.0 / 100.0 - 1.0
    assert latest["revenue_growth_acceleration"] == pytest_approx(current_yoy - previous_yoy)
    assert latest["gross_margin_yoy_change"] == pytest_approx(66.0 / 150.0 - 44.0 / 110.0)


def test_currency_change_invalidates_comparisons() -> None:
    periods = pd.date_range("2024-03-31", periods=6, freq="QE")
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"] * 6,
            "fiscal_period_end": periods,
            "filed_date": periods + pd.Timedelta(days=30),
            "revenue": [100, 110, 120, 130, 140, 150],
            "gross_profit": [40, 44, 48, 52, 56, 60],
            "currency": ["USD", "USD", "USD", "USD", "EUR", "EUR"],
            "form_type": ["10-Q"] * 6,
            "accession_id": [f"a{i}" for i in range(6)],
        }
    )
    features = compute_pit_features(frame)
    assert pd.isna(features.iloc[-1]["revenue_growth_acceleration"])
    assert pd.isna(features.iloc[-1]["gross_margin_yoy_change"])


def test_pit_selection_uses_filed_date_and_low_turnover_rules() -> None:
    dates = pd.bdate_range("2025-01-02", periods=150)
    price_rows = []
    for symbol, start in {"AAA": 100.0, "BBB": 90.0, "CCC": 80.0, "QQQ": 300.0}.items():
        for index, day in enumerate(dates):
            price_rows.append({"date": day, "symbol": symbol, "close": start + index * 0.3})
    prices = pd.DataFrame(price_rows)

    first_filing = dates[95]
    second_filing = dates[115]
    rows = []
    initial = {
        "AAA": (0.30, 0.12),
        "BBB": (0.20, 0.08),
        "CCC": (0.10, 0.04),
    }
    revised = {
        "AAA": (-0.20, -0.10),
        "BBB": (0.25, 0.10),
        "CCC": (0.40, 0.20),
    }
    for symbol in ["AAA", "BBB", "CCC"]:
        rows.append(
            {
                "symbol": symbol,
                "filed_date": first_filing,
                "fiscal_period_end": first_filing - pd.Timedelta(days=35),
                "revenue_growth_acceleration": initial[symbol][0],
                "gross_margin_yoy_change": initial[symbol][1],
            }
        )
        rows.append(
            {
                "symbol": symbol,
                "filed_date": second_filing,
                "fiscal_period_end": second_filing - pd.Timedelta(days=35),
                "revenue_growth_acceleration": revised[symbol][0],
                "gross_margin_yoy_change": revised[symbol][1],
            }
        )
    features = pd.DataFrame(rows)

    scores, selections = build_factor_history(
        contract=_contract(),
        pool=_pool(),
        features=features,
        prices=prices,
    )
    composite = [
        row for row in scores
        if row["stable_factor_key"] == "fundamental_acceleration_equal_weight"
    ]
    before_second_filing = [
        row for row in composite
        if row["date"] < second_filing.date().isoformat() and row["symbol"] == "AAA"
    ]
    assert before_second_filing[-1]["filed_date"] == first_filing.date().isoformat()

    basket_rows = [row for row in selections if row["basket"] == "test_basket"]
    first_nonempty = next(row for row in basket_rows if row["selected_symbols"])
    assert first_nonempty["selected_symbols"] == ["AAA"]
    overlap = next(row for row in basket_rows if len(row["selected_symbols"]) == 2)
    assert overlap["selected_symbols"] == ["AAA", "CCC"]
    assert overlap["added_symbols"] == ["CCC"]


def test_registers_three_current_standard_cards(tmp_path: Path) -> None:
    card_ids = register_factor_cards(tmp_path / "factor.db", _contract())
    registry = FactorKnowledgeRegistry(tmp_path / "factor.db")
    cards = registry.list_cards()

    assert len(card_ids) == 3
    assert {card["stable_factor_key"] for card in cards} == {
        "revenue_growth_acceleration",
        "gross_margin_yoy_change",
        "fundamental_acceleration_equal_weight",
    }
    assert {card["status"] for card in cards} == {"data_blocked"}


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value)
