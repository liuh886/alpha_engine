from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.focus_watchlist_signal import (
    compute_focus_indicators,
    generate_signal_history,
    load_long_ohlcv_csv,
    run_focus_watchlist_signal,
)


SPEC_PATH = Path("configs/research_paradigms/us_focus_watchlist_cycle_signal_v1.yaml")


def _spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _synthetic_prices() -> pd.DataFrame:
    spec = _spec()
    dates = pd.bdate_range("2024-01-02", periods=290)
    rows: list[dict] = []
    for symbol in spec["universe"]["symbols"]:
        provider_symbol = "^SOX" if symbol == "SOX" else symbol
        step = 0.10
        if symbol == "ALAB":
            step = 0.28
        elif symbol == "SOX":
            step = 0.14
        close = 100.0 + step * np.arange(len(dates), dtype=float)
        if symbol == "ALAB":
            close[-8:] = np.linspace(close[-9] * 0.96, close[-9] * 0.55, 8)
        for date, value in zip(dates, close, strict=True):
            rows.append(
                {
                    "date": date,
                    "symbol": provider_symbol,
                    "open": value,
                    "high": value + 1.0,
                    "low": value - 1.0,
                    "close": value,
                    "volume": 1_000_000,
                }
            )
    return pd.DataFrame(rows)


def test_alias_normalization_and_prior_high_excludes_current(tmp_path: Path) -> None:
    prices_path = tmp_path / "prices.csv"
    _synthetic_prices().to_csv(prices_path, index=False)
    prices = load_long_ohlcv_csv(prices_path, _spec())

    assert "SOX" in set(prices["symbol"])
    assert "^SOX" not in set(prices["symbol"])

    indicators = compute_focus_indicators(prices, _spec())
    alab = indicators[indicators["symbol"] == "ALAB"].sort_values("date").reset_index(drop=True)
    row = alab.iloc[25]
    expected = alab.loc[5:24, "close"].max()
    assert row["prior_high_20"] == expected
    assert row["close"] > row["prior_high_20"]


def test_state_machine_enters_holds_and_exits_without_ranking(tmp_path: Path) -> None:
    prices_path = tmp_path / "prices.csv"
    _synthetic_prices().to_csv(prices_path, index=False)
    prices = load_long_ohlcv_csv(prices_path, _spec())
    indicators = compute_focus_indicators(prices, _spec())
    history, references = generate_signal_history(indicators, _spec())

    alab = [row for row in history if row["symbol"] == "ALAB"]
    states = [row["state"] for row in alab]
    assert "ENTER" in states
    assert "HOLD" in states
    assert "EXIT" in states

    first_enter = next(row for row in alab if row["state"] == "ENTER")
    assert first_enter["actionable_from"] > first_enter["date"]
    assert first_enter["reason_codes"] == [
        "ENTER_BREAKOUT_TREND_RELATIVE_STRENGTH_CONFIRMED"
    ]
    assert {row["symbol"] for row in references} == {"QQQ", "SOX"}
    assert all(row["symbol"] not in {"QQQ", "SOX"} for row in history)


def test_future_price_changes_do_not_rewrite_prior_signals(tmp_path: Path) -> None:
    base = _synthetic_prices()
    prices_path = tmp_path / "base.csv"
    base.to_csv(prices_path, index=False)
    prices = load_long_ohlcv_csv(prices_path, _spec())
    indicators = compute_focus_indicators(prices, _spec())
    history, _ = generate_signal_history(indicators, _spec())

    cutoff = pd.Timestamp("2024-12-02")
    mutated = base.copy()
    mask = (pd.to_datetime(mutated["date"]) > cutoff) & (mutated["symbol"] == "ALAB")
    mutated.loc[mask, ["open", "high", "low", "close"]] *= 4.0
    mutated_path = tmp_path / "mutated.csv"
    mutated.to_csv(mutated_path, index=False)
    mutated_prices = load_long_ohlcv_csv(mutated_path, _spec())
    mutated_indicators = compute_focus_indicators(mutated_prices, _spec())
    mutated_history, _ = generate_signal_history(mutated_indicators, _spec())

    before = [
        row
        for row in history
        if row["symbol"] == "ALAB" and pd.Timestamp(row["date"]) <= cutoff
    ]
    after = [
        row
        for row in mutated_history
        if row["symbol"] == "ALAB" and pd.Timestamp(row["date"]) <= cutoff
    ]
    assert before == after


def test_runner_writes_manifest_bound_non_performance_outputs(tmp_path: Path) -> None:
    prices_path = tmp_path / "prices.csv"
    output_dir = tmp_path / "evidence"
    _synthetic_prices().to_csv(prices_path, index=False)

    decision = run_focus_watchlist_signal(
        spec_path=SPEC_PATH,
        prices_csv=prices_path,
        output_dir=output_dir,
    )

    assert decision["decision"] == "implementation_contract_passed"
    assert decision["performance_evaluated"] is False
    assert decision["reserved_performance_opened"] is False
    assert decision["focus_symbol_count"] == 19
    assert decision["signal_symbol_count"] == 17
    for filename in (
        "signal_history.json",
        "reference_history.json",
        "current_signals.json",
        "decision.json",
        "evidence_manifest.json",
    ):
        assert (output_dir / filename).is_file()
