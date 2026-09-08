from __future__ import annotations

from pathlib import Path
import copy
from dataclasses import replace
import json

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import (
    AllWeatherBacktestResult,
    _exit_reasons,
    _one_way_cost,
    compute_all_weather_indicators,
    evaluate_byd_v1_3_challenge,
    load_all_weather_contract,
    materialize_all_weather_evidence,
    run_all_weather_backtest,
    sha256_file,
)


SPEC = Path("configs/research_paradigms/cn_all_weather_alpha_rotation_v1.yaml")
SELECTED = Path("configs/research_universes/cn_selected_equities_v3.yaml")


def _bars(periods: int = 90) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=periods)
    close = 20.0 + np.arange(periods) * 0.08 + 0.1 * np.sin(np.arange(periods) / 3.0)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": "002594",
            "open": close - 0.03,
            "high": close + 0.10,
            "low": close - 0.10,
            "close": close,
            "volume": 1_000_000.0,
        }
    )


def test_contract_keeps_strategy_pool_and_references_role_separated() -> None:
    contract = load_all_weather_contract(SPEC)
    selected = set(yaml.safe_load(SELECTED.read_text(encoding="utf-8"))["symbols"])

    assert len(contract.candidate_symbols) == 27
    assert len(selected.intersection(contract.candidate_symbols)) == 22
    assert set(contract.candidate_symbols) - selected == {
        "002156",
        "002281",
        "300274",
        "601939",
        "688183",
    }
    assert contract.defensive_etf_symbol == "515180"
    assert contract.benchmark_symbol == "000300"
    assert contract.defensive_etf_symbol not in contract.candidate_symbols
    assert contract.benchmark_symbol not in contract.candidate_symbols
    assert contract.spec["research_only"] is True
    assert contract.spec["trade_ready"] is False
    assert contract.spec["selected_pool_readiness_claim_allowed"] is False


def test_indicators_follow_documented_formulas() -> None:
    contract = load_all_weather_contract(SPEC)
    raw = _bars()
    result = compute_all_weather_indicators(raw, contract.spec).set_index("date")
    date = result.index[-1]
    close = raw.set_index("date")["close"]

    assert np.isclose(result.loc[date, "sma20"], close.iloc[-20:].mean())
    assert np.isclose(result.loc[date, "bias20"], close.iloc[-1] / close.iloc[-20:].mean() - 1.0)
    expected_tr = pd.concat(
        [(close - close.shift()).abs(), (close - raw.set_index("date")["open"]).abs()], axis=1
    ).max(axis=1)
    assert np.isclose(result.loc[date, "atr14"], expected_tr.iloc[-14:].mean())
    assert np.isclose(result.loc[date, "close_ratio_20"], close.iloc[-1] / close.iloc[-21])


def test_three_session_relative_sma20_slope_is_supported_without_rewriting_v1() -> None:
    contract = load_all_weather_contract(SPEC)
    v1 = compute_all_weather_indicators(_bars(), contract.spec).set_index("date")
    revised_spec = copy.deepcopy(contract.spec)
    revised_spec["factors"]["sma20_slope_definition"] = "three_session_relative"
    revised_spec["factors"]["sma20_slope_periods"] = 3
    revised = compute_all_weather_indicators(_bars(), revised_spec).set_index("date")
    date = revised.index[-1]

    expected_v1 = v1.loc[date, "sma20"] - v1["sma20"].shift(1).loc[date]
    expected_revised = revised.loc[date, "sma20"] / revised["sma20"].shift(3).loc[date] - 1.0
    assert np.isclose(v1.loc[date, "sma20_slope"], expected_v1)
    assert np.isclose(revised.loc[date, "sma20_slope"], expected_revised)
    assert not np.isclose(v1.loc[date, "sma20_slope"], revised.loc[date, "sma20_slope"])


def test_byd_challenge_requires_hash_bound_exact_common_sessions(
    monkeypatch, tmp_path: Path
) -> None:
    dates = pd.bdate_range("2025-01-02", periods=3)
    performance = {
        "trace_frequency": "daily_open_to_open",
        "report": [
            {
                "date": date.date().isoformat(),
                "period_return": value,
                "turnover": 0.1,
                "transaction_cost": 0.0002,
            }
            for date, value in zip(dates, [0.0, 0.01, -0.005], strict=True)
        ],
    }
    performance_path = tmp_path / "performance.json"
    performance_path.write_text(json.dumps(performance), encoding="utf-8")
    manifest = {
        "model_version_id": "byd_v1_3_recovery_event_low_vol_confirmation_v1",
        "research_only": True,
        "trade_ready": False,
        "sections": [
            {
                "section_id": "performance",
                "path": performance_path.name,
                "sha256": sha256_file(performance_path),
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    contract = load_all_weather_contract("configs/research_paradigms/cn_27_v1_0.yaml")
    spec = copy.deepcopy(contract.spec)
    spec["challenge"].update(
        {
            "benchmark_manifest": manifest_path.name,
            "benchmark_manifest_sha256": sha256_file(manifest_path),
            "benchmark_performance_sha256": sha256_file(performance_path),
            "common_window": {
                "start": dates[0].date().isoformat(),
                "end": dates[-1].date().isoformat(),
                "required_sessions": 3,
            },
        }
    )
    monkeypatch.setattr(
        "src.research.all_weather_alpha_rotation._repository_root", lambda _path: tmp_path
    )
    contract = replace(contract, spec=spec)
    daily = pd.DataFrame(
        {
            "net_return": [0.0, 0.02, -0.002],
            "one_way_turnover": [0.0, 0.1, 0.0],
            "transaction_cost": [0.0, 0.0001, 0.0],
        },
        index=dates,
    )
    result = AllWeatherBacktestResult(
        daily=daily,
        trades=pd.DataFrame(),
        round_trips=pd.DataFrame(),
        coverage=pd.DataFrame(),
        indicators=pd.DataFrame(),
        metrics={},
    )

    comparison, paired = evaluate_byd_v1_3_challenge(result, contract)

    assert comparison["common_window"]["sessions"] == 3
    assert comparison["historical_risk_return_dominance"] is True
    assert comparison["all_frozen_gates_passed"] is True
    assert list(paired["date"]) == list(dates)


def test_future_prices_do_not_rewrite_prior_indicators() -> None:
    contract = load_all_weather_contract(SPEC)
    base = _bars(100)
    cutoff = base.loc[79, "date"]
    before = compute_all_weather_indicators(base, contract.spec)
    changed = base.copy()
    changed.loc[changed["date"] > cutoff, ["open", "high", "low", "close"]] *= 9.0
    after = compute_all_weather_indicators(changed, contract.spec)

    columns = ["sma20", "macd_hist", "rsi14", "atr14", "score", "entry_eligible"]
    pd.testing.assert_frame_equal(
        before.loc[before["date"] <= cutoff, columns].reset_index(drop=True),
        after.loc[after["date"] <= cutoff, columns].reset_index(drop=True),
    )


def test_stock_and_etf_costs_are_charged_by_side() -> None:
    before = {"AAA": 0.20, "BBB": 0.00, "515180": 0.80, "CASH": 0.0}
    after = {"AAA": 0.00, "BBB": 0.15, "515180": 0.85, "CASH": 0.0}
    cost, turnover, buys, sells = _one_way_cost(
        before,
        after,
        candidate_symbols=("AAA", "BBB"),
        defensive_symbol="515180",
        cost_spec={
            "stock_buy_rate": 0.0005,
            "stock_sell_rate": 0.0010,
            "etf_buy_rate": 0.0002,
            "etf_sell_rate": 0.0002,
        },
    )

    assert np.isclose(cost, 0.15 * 0.0005 + 0.20 * 0.0010 + 0.05 * 0.0002)
    assert np.isclose(turnover, (0.15 + 0.20 + 0.05) / 2.0)
    assert buys == 0.15
    assert sells == 0.20


def test_exit_rules_preserve_all_triggered_reasons() -> None:
    reasons = _exit_reasons(
        pd.Series(
            {
                "rsi14": 75.0,
                "macd_hist": 0.1,
                "previous_macd_hist": 0.2,
                "close": 94.0,
                "macd": -0.1,
                "macd_signal": 0.0,
                "sma20": 100.0,
            }
        ),
        entry_price=100.0,
        peak_high=116.0,
        exit_spec=load_all_weather_contract(SPEC).spec["exit"],
    )

    assert reasons == [
        "divergence_take_profit",
        "trailing_profit_protection",
        "trend_break",
        "hard_stop",
    ]


def test_close_signal_executes_at_next_open(monkeypatch, tmp_path: Path) -> None:
    contract = load_all_weather_contract(SPEC)
    dates = pd.bdate_range("2023-09-01", periods=4)
    rows = []
    required = (*contract.candidate_symbols, contract.defensive_etf_symbol, contract.benchmark_symbol)
    for symbol in required:
        for index, date in enumerate(dates):
            price = 100.0
            if symbol == "002594" and index == 1:
                price = 95.0
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": 100.0,
                    "high": max(101.0, price + 1.0),
                    "low": min(99.0, price - 1.0),
                    "close": price,
                    "volume": 1_000_000.0,
                }
            )
    bars = pd.DataFrame(rows)

    def fake_indicators(_bars, _spec):
        return pd.DataFrame(
            [
                {
                    "date": date,
                    "symbol": "002594",
                    "close": 95.0 if index == 1 else 100.0,
                    "sma20": 100.0,
                    "macd": 1.0,
                    "macd_signal": 0.0,
                    "macd_hist": 0.3,
                    "rsi14": 50.0,
                    "score": 1.0,
                    "entry_eligible": index == 0,
                }
                for index, date in enumerate(dates)
            ]
        )

    monkeypatch.setattr(
        "src.research.all_weather_alpha_rotation.compute_all_weather_indicators",
        fake_indicators,
    )
    result = run_all_weather_backtest(bars, contract)
    stock_trades = result.trades.loc[result.trades["symbol"].eq("002594")].reset_index(drop=True)

    assert list(stock_trades["side"]) == ["buy", "sell"]
    assert stock_trades.loc[0, "signal_date"] == dates[0]
    assert stock_trades.loc[0, "date"] == dates[1]
    assert stock_trades.loc[1, "signal_date"] == dates[1]
    assert stock_trades.loc[1, "date"] == dates[2]
    assert "hard_stop" in stock_trades.loc[1, "reason"]
    assert result.daily.loc[dates[0], "etf_weight"] == 1.0
    assert result.daily.loc[dates[1], "stock_weight"] == 0.15
    assert result.metrics["research_only"] is True
    assert result.metrics["trade_ready"] is False

    source = tmp_path / "source.csv"
    bars.to_csv(source, index=False)
    decision = materialize_all_weather_evidence(
        output_dir=tmp_path / "evidence",
        source_prices_path=source,
        contract=contract,
        result=result,
    )
    assert decision["research_only"] is True
    assert decision["trade_ready"] is False
    for filename in contract.spec["evidence"]["expected_outputs"]:
        assert (tmp_path / "evidence" / filename).is_file()
    assert (tmp_path / "evidence" / "factor_signal_history.csv").is_file()
    assert (tmp_path / "evidence" / "round_trips.csv").is_file()
