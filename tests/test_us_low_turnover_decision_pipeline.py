from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.decision_support.us_low_turnover_decision_pipeline import (
    run_us_low_turnover_decision_pipeline,
)

POOL = Path("configs/pools/us_small_pool_v1.yaml")
AS_OF = "2026-07-31"


def _membership() -> tuple[dict[str, str], list[str]]:
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    basket_by_symbol = {
        str(symbol): str(basket)
        for basket, meta in pool["baskets"].items()
        for symbol in meta["symbols"]
    }
    return basket_by_symbol, list(pool["references"])


def _write_prices(path: Path) -> None:
    basket_by_symbol, references = _membership()
    dates = pd.bdate_range(end=AS_OF, periods=340)
    baskets = sorted(set(basket_by_symbol.values()))
    slopes = {
        basket: [0.0009, 0.00035, 0.00065, 0.00045, 0.00075, 0.00030][
            index % 6
        ]
        for index, basket in enumerate(baskets)
    }
    shocks = {
        basket: [0.022, 0.0, 0.014, 0.006, 0.018, 0.010][index % 6]
        for index, basket in enumerate(baskets)
    }
    rows = []
    all_symbols = [*basket_by_symbol, *references]
    for symbol_index, symbol in enumerate(all_symbols):
        basket = basket_by_symbol.get(symbol, "reference")
        slope = slopes.get(basket, 0.00055)
        shock = shocks.get(basket, 0.004 if symbol != "QQQ" else 0.0)
        phase = symbol_index * 0.73
        previous_close = 50.0 + symbol_index * 2.0
        for day_index, day in enumerate(dates):
            trend = np.exp(slope * day_index)
            wave = 1.0 + 0.004 * np.sin(day_index / (12.0 + symbol_index % 5) + phase)
            late_shock = 1.0
            if day_index >= len(dates) - 25:
                progress = (day_index - (len(dates) - 25)) / 24.0
                late_shock = 1.0 - shock * progress
            close = (50.0 + symbol_index * 2.0) * trend * wave * late_shock
            open_price = previous_close * (1.0 + 0.0005 * np.sin(day_index + phase))
            high = max(open_price, close) * 1.006
            low = min(open_price, close) * 0.994
            rows.append(
                {
                    "date": day.date().isoformat(),
                    "symbol": symbol,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1_000_000 + symbol_index * 10_000 + day_index * 100,
                }
            )
            previous_close = close
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_fundamentals(path: Path) -> None:
    basket_by_symbol, _ = _membership()
    period_ends = pd.date_range("2024-03-31", periods=8, freq="QE")
    rows = []
    symbol_count = len(basket_by_symbol)
    for symbol_index, symbol in enumerate(basket_by_symbol):
        base = 90.0 + symbol_index * 4.0
        acceleration = 0.00035 + 0.000035 * symbol_index
        margin_slope_rank = (symbol_index * 7) % symbol_count
        margin_slope = 0.0007 + 0.000055 * margin_slope_rank
        for quarter_index, period_end in enumerate(period_ends):
            revenue = base * (
                1.0
                + 0.035 * quarter_index
                + acceleration * quarter_index * quarter_index
            )
            margin = (
                0.31
                + 0.0015 * (symbol_index % 4)
                + margin_slope * quarter_index
            )
            rows.append(
                {
                    "symbol": symbol,
                    "fiscal_period_end": period_end.date().isoformat(),
                    "filed_date": (period_end + pd.Timedelta(days=35)).date().isoformat(),
                    "revenue": revenue,
                    "gross_profit": revenue * margin,
                    "currency": "USD",
                    "form_type": "10-Q" if quarter_index % 4 != 3 else "10-K",
                    "accession_id": f"{symbol}-{quarter_index}",
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def _run(tmp_path: Path) -> dict:
    prices = tmp_path / "prices.csv"
    fundamentals = tmp_path / "fundamentals.csv"
    _write_prices(prices)
    _write_fundamentals(fundamentals)
    return run_us_low_turnover_decision_pipeline(
        as_of_date=AS_OF,
        prices_csv=prices,
        fundamentals_csv=fundamentals,
        registry_db=tmp_path / "factor.db",
        ledger_dir=tmp_path / "ledger",
        workspace_dir=tmp_path / "workspace",
    )


def test_complete_no_network_pipeline_writes_multifactor_shadow_ticket(
    tmp_path: Path,
) -> None:
    manifest = _run(tmp_path)

    assert manifest["pipeline_id"] == "us_low_turnover_decision_pipeline_v1"
    assert manifest["research_only"] is True
    assert manifest["diagnostic_only"] is True
    assert manifest["trade_ready"] is False
    assert manifest["automatic_order_routing"] is False
    assert manifest["outputs"]["ticket_identity_sha256"]
    ticket_path = tmp_path / "ledger" / "us" / f"{AS_OF}.json"
    ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
    assert ticket["mode"] == "diagnostic_only"
    assert ticket["trade_ready"] is False
    assert ticket["securities"]
    run_root = tmp_path / "workspace" / "us_low_turnover_pipeline" / AS_OF
    relationship = json.loads(
        (run_root / "factor_relationship_map" / "factor_relationships.json").read_text(
            encoding="utf-8"
        )
    )
    assert relationship["factor_count"] == 4
    multifactor = json.loads(
        (run_root / "low_turnover_multifactor" / "decision.json").read_text(
            encoding="utf-8"
        )
    )
    assert multifactor["turnover_diagnostics"]["turnover_gate_passed"] is True


def test_same_inputs_are_idempotent(tmp_path: Path) -> None:
    first = _run(tmp_path)
    prices = tmp_path / "prices.csv"
    fundamentals = tmp_path / "fundamentals.csv"
    second = run_us_low_turnover_decision_pipeline(
        as_of_date=AS_OF,
        prices_csv=prices,
        fundamentals_csv=fundamentals,
        registry_db=tmp_path / "factor.db",
        ledger_dir=tmp_path / "ledger",
        workspace_dir=tmp_path / "workspace",
    )

    assert second["pipeline_run_identity_sha256"] == first[
        "pipeline_run_identity_sha256"
    ]


def test_missing_frozen_symbol_fails_closed(tmp_path: Path) -> None:
    prices = tmp_path / "prices.csv"
    fundamentals = tmp_path / "fundamentals.csv"
    _write_prices(prices)
    _write_fundamentals(fundamentals)
    frame = pd.read_csv(prices)
    missing_symbol = next(iter(_membership()[0]))
    frame = frame[frame["symbol"] != missing_symbol]
    frame.to_csv(prices, index=False)

    with pytest.raises(ValueError, match="missing frozen symbols"):
        run_us_low_turnover_decision_pipeline(
            as_of_date=AS_OF,
            prices_csv=prices,
            fundamentals_csv=fundamentals,
            registry_db=tmp_path / "factor.db",
            ledger_dir=tmp_path / "ledger",
            workspace_dir=tmp_path / "workspace",
        )
