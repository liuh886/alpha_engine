"""Observed-evidence validation for the deterministic focus-watchlist signal."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.focus_watchlist_signal import (
    compute_focus_indicators,
    generate_signal_history,
    load_focus_signal_spec,
    load_long_ohlcv_csv,
    sha256_file,
)
from src.research.research_artifacts import write_json


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _max_drawdown(returns: pd.Series) -> float:
    clean = returns.fillna(0.0).astype(float)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _compound(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod() - 1.0) if not clean.empty else 0.0


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if not np.isfinite(denominator) or abs(denominator) < 1e-12:
        return None
    return float(numerator / denominator)


def _average_holding_sessions(exposure: pd.Series) -> float:
    active = exposure.fillna(0.0).gt(0.0)
    if active.empty or not active.any():
        return 0.0
    starts = active & ~active.shift(1, fill_value=False)
    groups = starts.cumsum()
    lengths = active.groupby(groups).sum()
    lengths = lengths[lengths > 0]
    return float(lengths.mean()) if not lengths.empty else 0.0


def _false_exit_reentry_rate(states: pd.Series, horizon: int) -> tuple[int, int, float | None]:
    values = list(states.astype(str))
    exits = [index for index, state in enumerate(values) if state == "EXIT"]
    if not exits:
        return 0, 0, None
    reentries = 0
    for index in exits:
        if "ENTER" in values[index + 1 : index + 1 + horizon]:
            reentries += 1
    return len(exits), reentries, float(reentries / len(exits))


def _forward_returns_by_state(frame: pd.DataFrame, horizon: int) -> dict[str, dict[str, Any]]:
    entry_open = frame["open"].shift(-1)
    horizon_open = frame["open"].shift(-(horizon + 1))
    forward = horizon_open / entry_open - 1.0
    result: dict[str, dict[str, Any]] = {}
    for state in ("WATCH", "ENTER", "HOLD", "REDUCE", "EXIT"):
        values = forward[frame["state"] == state].dropna()
        result[state] = {
            "count": int(values.shape[0]),
            "mean": None if values.empty else float(values.mean()),
            "median": None if values.empty else float(values.median()),
            "positive_ratio": None if values.empty else float((values > 0).mean()),
        }
    return result


def _window_frame(
    symbol: str,
    prices: pd.DataFrame,
    signal_history: pd.DataFrame,
    qqq_returns: pd.DataFrame,
    start: str,
    end: str,
    exposure_map: Mapping[str, float],
    one_way_cost_bps: float,
) -> pd.DataFrame:
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    price = prices[prices["symbol"] == symbol].sort_values("date").copy()
    states = signal_history[signal_history["symbol"] == symbol][
        ["date", "state", "market_regime"]
    ].copy()
    all_rows = price.merge(states, on="date", how="inner", validate="one_to_one")
    prior = all_rows[all_rows["date"] < start_date]
    previous_exposure = 0.0
    if not prior.empty:
        previous_exposure = float(exposure_map[str(prior.iloc[-1]["state"])])

    frame = all_rows[
        (all_rows["date"] >= start_date) & (all_rows["date"] <= end_date)
    ].copy()
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame.empty:
        return frame

    frame["exposure"] = frame["state"].map(exposure_map).astype(float)
    frame["next_open_return"] = frame["open"].shift(-2) / frame["open"].shift(-1) - 1.0
    frame["return_end_date"] = frame["date"].shift(-2)
    frame.loc[frame["return_end_date"] > end_date, "next_open_return"] = np.nan
    frame["exposure_change"] = frame["exposure"].diff()
    frame.loc[frame.index[0], "exposure_change"] = (
        float(frame.iloc[0]["exposure"]) - previous_exposure
    )
    frame["cost"] = frame["exposure_change"].abs() * one_way_cost_bps / 10_000.0
    frame["strategy_return"] = frame["exposure"] * frame["next_open_return"] - frame["cost"]
    frame["buy_hold_return"] = frame["next_open_return"]
    return frame.merge(qqq_returns, on="date", how="left", validate="one_to_one")


def _evaluate_symbol_window(
    symbol: str,
    prices: pd.DataFrame,
    signal_history: pd.DataFrame,
    qqq_returns: pd.DataFrame,
    start: str,
    end: str,
    exposure_map: Mapping[str, float],
    one_way_cost_bps: float,
    false_exit_horizon: int,
    minimum_sessions: int,
) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame]:
    frame = _window_frame(
        symbol,
        prices,
        signal_history,
        qqq_returns,
        start,
        end,
        exposure_map,
        one_way_cost_bps,
    )
    history_sessions_total = int(
        prices[
            (prices["symbol"] == symbol) & (prices["date"] <= pd.Timestamp(end))
        ].shape[0]
    )
    if frame.empty:
        metrics = {
            "symbol": symbol,
            "sessions": 0,
            "history_sessions_total": history_sessions_total,
            "history_status": "unavailable",
            "gate_eligible": False,
            "strategy_total_return_after_costs": None,
        }
        return metrics, {"10d": {}, "20d": {}}, frame

    valid_returns = frame.dropna(subset=["strategy_return", "buy_hold_return", "qqq_return"])
    strategy_total = _compound(valid_returns["strategy_return"])
    buy_hold_total = _compound(valid_returns["buy_hold_return"])
    qqq_total = _compound(valid_returns["qqq_return"])
    strategy_drawdown = _max_drawdown(valid_returns["strategy_return"])
    buy_hold_drawdown = _max_drawdown(valid_returns["buy_hold_return"])
    drawdown_reduction = None
    if buy_hold_drawdown < 0:
        drawdown_reduction = float(
            1.0 - abs(strategy_drawdown) / max(abs(buy_hold_drawdown), 1e-12)
        )

    qqq_up = valid_returns["qqq_return"] > 0
    qqq_down = valid_returns["qqq_return"] < 0
    upside_capture = (
        _safe_ratio(
            float(valid_returns.loc[qqq_up, "strategy_return"].mean()),
            float(valid_returns.loc[qqq_up, "qqq_return"].mean()),
        )
        if qqq_up.any()
        else None
    )
    downside_capture = (
        _safe_ratio(
            float(valid_returns.loc[qqq_down, "strategy_return"].mean()),
            float(valid_returns.loc[qqq_down, "qqq_return"].mean()),
        )
        if qqq_down.any()
        else None
    )

    entries = int((frame["state"] == "ENTER").sum())
    span_days = max((frame["date"].max() - frame["date"].min()).days, 1)
    trades_per_year = float(entries * 365.25 / span_days)
    exit_count, rapid_reentries, false_exit_rate = _false_exit_reentry_rate(
        frame["state"], false_exit_horizon
    )
    full_history = history_sessions_total >= minimum_sessions
    metrics = {
        "symbol": symbol,
        "sessions": int(frame.shape[0]),
        "history_sessions_total": history_sessions_total,
        "history_status": "full" if full_history else "short_history",
        "gate_eligible": full_history,
        "strategy_total_return_after_costs": strategy_total,
        "same_security_buy_hold_return": buy_hold_total,
        "qqq_return": qqq_total,
        "qqq_relative_return": float(strategy_total - qqq_total),
        "maximum_drawdown": strategy_drawdown,
        "buy_hold_maximum_drawdown": buy_hold_drawdown,
        "drawdown_reduction_vs_buy_hold": drawdown_reduction,
        "upside_capture": upside_capture,
        "downside_capture": downside_capture,
        "average_holding_sessions": _average_holding_sessions(frame["exposure"]),
        "trades": entries,
        "trades_per_year": trades_per_year,
        "turnover": float(frame["exposure_change"].abs().sum()),
        "exit_count": exit_count,
        "rapid_reentry_count": rapid_reentries,
        "false_exit_reentry_rate": false_exit_rate,
    }
    forward = {
        "10d": _forward_returns_by_state(frame, 10),
        "20d": _forward_returns_by_state(frame, 20),
    }
    return metrics, forward, frame


def _qqq_return_frame(prices: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    end_date = pd.Timestamp(end)
    qqq = prices[prices["symbol"] == "QQQ"].sort_values("date").copy()
    qqq = qqq[(qqq["date"] >= pd.Timestamp(start)) & (qqq["date"] <= end_date)].copy()
    qqq["qqq_return"] = qqq["open"].shift(-2) / qqq["open"].shift(-1) - 1.0
    qqq["return_end_date"] = qqq["date"].shift(-2)
    qqq.loc[qqq["return_end_date"] > end_date, "qqq_return"] = np.nan
    return qqq[["date", "qqq_return"]]


def _aggregate_book(
    symbol_frames: Mapping[str, pd.DataFrame],
    risk_weights: Mapping[str, float],
    sox_regimes: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float]]:
    pieces: list[pd.DataFrame] = []
    contributions: dict[str, float] = {}
    for symbol, frame in symbol_frames.items():
        if frame.empty:
            continue
        part = frame[
            ["date", "strategy_return", "qqq_return", "market_regime", "exposure"]
        ].dropna(subset=["strategy_return", "qqq_return"]).copy()
        if part.empty:
            continue
        part["symbol"] = symbol
        part["risk_weight"] = float(risk_weights[symbol])
        part["weighted_exposure"] = part["exposure"] * part["risk_weight"]
        part["weighted_return"] = part["strategy_return"] * part["risk_weight"]
        pieces.append(part)
        contributions[symbol] = float(part["weighted_return"].sum())
    if not pieces:
        return {}, {}, contributions

    long = pd.concat(pieces, ignore_index=True)
    book = long.groupby("date", sort=True).agg(
        weighted_return=("weighted_return", "sum"),
        available_weight=("risk_weight", "sum"),
        weighted_exposure=("weighted_exposure", "sum"),
        qqq_return=("qqq_return", "first"),
        market_regime=("market_regime", "first"),
    ).reset_index()
    denominator = book["available_weight"].replace(0, np.nan)
    book["strategy_return"] = book["weighted_return"] / denominator
    book["average_exposure"] = book["weighted_exposure"] / denominator
    book = book.merge(sox_regimes, on="date", how="left", validate="one_to_one")

    strategy_total = _compound(book["strategy_return"])
    qqq_total = _compound(book["qqq_return"])
    aggregate = {
        "strategy_total_return_after_costs": strategy_total,
        "qqq_return": qqq_total,
        "qqq_relative_return": float(strategy_total - qqq_total),
        "maximum_drawdown": _max_drawdown(book["strategy_return"]),
        "average_exposure": float(book["average_exposure"].mean()),
        "sessions": int(book.shape[0]),
    }
    regime_metrics: dict[str, Any] = {"market": {}, "sox": {}}
    for column, key in (("market_regime", "market"), ("sox_regime", "sox")):
        for regime, group in book.groupby(column, dropna=False):
            label = "unavailable" if pd.isna(regime) else str(regime)
            strategy_return = _compound(group["strategy_return"])
            qqq_return = _compound(group["qqq_return"])
            regime_metrics[key][label] = {
                "sessions": int(group.shape[0]),
                "strategy_return": strategy_return,
                "qqq_return": qqq_return,
                "relative_return": float(strategy_return - qqq_return),
                "average_exposure": float(group["average_exposure"].mean()),
            }
    return aggregate, regime_metrics, contributions


def _profit_concentration(contributions: Mapping[str, float]) -> float:
    positive = [max(float(value), 0.0) for value in contributions.values()]
    total = sum(positive)
    return float(max(positive, default=0.0) / total) if total > 0 else 1.0


def _eligible_rows(metrics: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in metrics.values() if bool(row.get("gate_eligible"))]


def _common_observed_metrics(
    metrics: Mapping[str, Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    contributions: Mapping[str, float],
) -> dict[str, Any]:
    eligible = _eligible_rows(metrics)
    drawdowns = [
        float(row["drawdown_reduction_vs_buy_hold"])
        for row in eligible
        if row.get("drawdown_reduction_vs_buy_hold") is not None
    ]
    return {
        "gate_eligible_symbols": [str(row["symbol"]) for row in eligible],
        "diagnostic_symbols": [
            str(row["symbol"]) for row in metrics.values() if not row.get("gate_eligible")
        ],
        "median_drawdown_reduction_vs_buy_hold": (
            float(np.median(drawdowns)) if drawdowns else None
        ),
        "aggregate_qqq_relative_return_after_costs": aggregate.get("qqq_relative_return"),
        "maximum_single_symbol_profit_contribution": _profit_concentration(contributions),
        "median_trades_per_year": (
            float(np.median([float(row["trades_per_year"]) for row in eligible]))
            if eligible
            else None
        ),
        "median_average_holding_sessions": (
            float(np.median([float(row["average_holding_sessions"]) for row in eligible]))
            if eligible
            else None
        ),
        "positive_strategy_return_symbol_ratio": (
            float(np.mean([row["strategy_total_return_after_costs"] > 0 for row in eligible]))
            if eligible
            else 0.0
        ),
        "positive_qqq_relative_symbol_ratio": (
            float(np.mean([row["qqq_relative_return"] > 0 for row in eligible]))
            if eligible
            else 0.0
        ),
    }


def _development_gate_summary(
    metrics: Mapping[str, Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    regime_metrics: Mapping[str, Any],
    contributions: Mapping[str, float],
    forward_metrics: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Any],
) -> dict[str, Any]:
    observed = _common_observed_metrics(metrics, aggregate, contributions)
    eligible_symbols = set(observed["gate_eligible_symbols"])
    enter_means: list[float] = []
    for symbol in eligible_symbols:
        value = forward_metrics.get(symbol, {}).get("20d", {}).get("ENTER", {}).get("mean")
        if value is not None:
            enter_means.append(float(value))
    observed["positive_20d_enter_return_symbol_ratio"] = (
        float(np.mean([value > 0 for value in enter_means])) if enter_means else 0.0
    )
    supported_regimes = 0
    for row in regime_metrics.get("market", {}).values():
        if row["strategy_return"] > 0 or (
            row["qqq_return"] < 0 and row["relative_return"] > 0
        ):
            supported_regimes += 1
    observed["supported_market_regimes"] = supported_regimes

    comparisons = {
        "median_drawdown_reduction_vs_buy_hold_min": observed["median_drawdown_reduction_vs_buy_hold"] is not None and observed["median_drawdown_reduction_vs_buy_hold"] >= float(targets["median_drawdown_reduction_vs_buy_hold_min"]),
        "aggregate_qqq_relative_return_after_costs_min": observed["aggregate_qqq_relative_return_after_costs"] is not None and observed["aggregate_qqq_relative_return_after_costs"] >= float(targets["aggregate_qqq_relative_return_after_costs_min"]),
        "positive_20d_enter_return_symbol_ratio_min": observed["positive_20d_enter_return_symbol_ratio"] >= float(targets["positive_20d_enter_return_symbol_ratio_min"]),
        "maximum_single_symbol_profit_contribution": observed["maximum_single_symbol_profit_contribution"] <= float(targets["maximum_single_symbol_profit_contribution"]),
        "median_trades_per_year_max": observed["median_trades_per_year"] is not None and observed["median_trades_per_year"] <= float(targets["median_trades_per_year_max"]),
        "median_average_holding_sessions_min": observed["median_average_holding_sessions"] is not None and observed["median_average_holding_sessions"] >= float(targets["median_average_holding_sessions_min"]),
        "positive_strategy_return_symbol_ratio_min": observed["positive_strategy_return_symbol_ratio"] >= float(targets["positive_strategy_return_symbol_ratio_min"]),
        "positive_qqq_relative_symbol_ratio_min": observed["positive_qqq_relative_symbol_ratio"] >= float(targets["positive_qqq_relative_symbol_ratio_min"]),
        "minimum_supported_market_regimes": observed["supported_market_regimes"] >= int(targets["minimum_supported_market_regimes"]),
    }
    return {"observed": observed, "comparisons": comparisons, "all_passed": all(comparisons.values())}


def _falsification_gate_summary(
    metrics: Mapping[str, Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    contributions: Mapping[str, float],
    targets: Mapping[str, Any],
) -> dict[str, Any]:
    observed = _common_observed_metrics(metrics, aggregate, contributions)
    comparisons = {
        "median_drawdown_reduction_vs_buy_hold_min": observed["median_drawdown_reduction_vs_buy_hold"] is not None and observed["median_drawdown_reduction_vs_buy_hold"] >= float(targets["median_drawdown_reduction_vs_buy_hold_min"]),
        "aggregate_qqq_relative_return_after_costs_min": observed["aggregate_qqq_relative_return_after_costs"] is not None and observed["aggregate_qqq_relative_return_after_costs"] >= float(targets["aggregate_qqq_relative_return_after_costs_min"]),
        "maximum_single_symbol_profit_contribution": observed["maximum_single_symbol_profit_contribution"] <= float(targets["maximum_single_symbol_profit_contribution"]),
        "positive_strategy_return_symbol_ratio_min": observed["positive_strategy_return_symbol_ratio"] >= float(targets["positive_strategy_return_symbol_ratio_min"]),
        "positive_qqq_relative_symbol_ratio_min": observed["positive_qqq_relative_symbol_ratio"] >= float(targets["positive_qqq_relative_symbol_ratio_min"]),
    }
    return {"observed": observed, "comparisons": comparisons, "all_passed": all(comparisons.values())}


def run_focus_watchlist_validation(
    *,
    spec_path: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    prices_csv = Path(prices_csv)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = load_focus_signal_spec(spec_path)
    prices = load_long_ohlcv_csv(prices_csv, spec)

    reserved_start = pd.Timestamp(spec["evidence"]["independent_reserved"]["start"])
    observed_prices = prices[prices["date"] < reserved_start].copy()
    if observed_prices.empty:
        raise ValueError("no observed-evidence prices before the reserved boundary")
    required_end = pd.Timestamp(spec["evidence"]["falsification_only"]["end"])
    stale_symbols = sorted(
        symbol
        for symbol in spec["universe"]["symbols"]
        if observed_prices.loc[observed_prices["symbol"] == symbol, "date"].max()
        < required_end
    )
    if stale_symbols:
        raise ValueError(f"observed provider is stale for focus symbols: {stale_symbols}")

    indicators = compute_focus_indicators(observed_prices, spec)
    history_rows, reference_rows = generate_signal_history(indicators, spec)
    signal_history = pd.DataFrame(history_rows)
    signal_history["date"] = pd.to_datetime(signal_history["date"])
    reference_history = pd.DataFrame(reference_rows)
    reference_history["date"] = pd.to_datetime(reference_history["date"])
    sox_regimes = reference_history[reference_history["symbol"] == "SOX"][
        ["date", "regime"]
    ].rename(columns={"regime": "sox_regime"})

    assumptions = spec["evaluation"]["execution_assumptions"]
    exposure_map = assumptions["state_exposure"]
    one_way_cost = float(assumptions["cost_bps_per_unit_exposure_change"])
    false_exit_horizon = int(assumptions["false_exit_reentry_sessions"])
    minimum_sessions = int(spec["universe"]["minimum_sessions_for_full_evaluation"])
    risk_units = spec["risk"]["risk_units"]
    risk_weights = {
        symbol: float(risk_units[spec["risk"]["symbol_tiers"][symbol]])
        for symbol in spec["universe"]["signal_symbols"]
    }

    per_symbol: dict[str, Any] = {}
    forward_state: dict[str, Any] = {}
    aggregate: dict[str, Any] = {}
    regimes: dict[str, Any] = {}
    contributions_by_window: dict[str, Any] = {}

    for window_name in ("development_observed", "falsification_only"):
        window = spec["evidence"][window_name]
        qqq_returns = _qqq_return_frame(observed_prices, window["start"], window["end"])
        window_metrics: dict[str, Any] = {}
        window_forward: dict[str, Any] = {}
        symbol_frames: dict[str, pd.DataFrame] = {}
        for symbol in spec["universe"]["signal_symbols"]:
            metrics, forward, frame = _evaluate_symbol_window(
                symbol,
                observed_prices,
                signal_history,
                qqq_returns,
                window["start"],
                window["end"],
                exposure_map,
                one_way_cost,
                false_exit_horizon,
                minimum_sessions,
            )
            window_metrics[symbol] = metrics
            window_forward[symbol] = forward
            symbol_frames[symbol] = frame
        window_aggregate, window_regimes, contributions = _aggregate_book(
            symbol_frames, risk_weights, sox_regimes
        )
        window_aggregate["symbol_contributions"] = contributions
        per_symbol[window_name] = window_metrics
        forward_state[window_name] = window_forward
        aggregate[window_name] = window_aggregate
        regimes[window_name] = window_regimes
        contributions_by_window[window_name] = contributions

    development_gates = _development_gate_summary(
        per_symbol["development_observed"],
        aggregate["development_observed"],
        regimes["development_observed"],
        contributions_by_window["development_observed"],
        forward_state["development_observed"],
        spec["evaluation"]["development_targets"],
    )
    falsification_gates = _falsification_gate_summary(
        per_symbol["falsification_only"],
        aggregate["falsification_only"],
        contributions_by_window["falsification_only"],
        spec["evaluation"]["falsification_targets"],
    )
    all_passed = development_gates["all_passed"] and falsification_gates["all_passed"]
    decision = (
        "focus_signal_independent_validation_required"
        if all_passed
        else "focus_signal_not_supported_on_observed_evidence"
    )
    decision_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "decision": decision,
        "research_only": True,
        "trade_ready": False,
        "reserved_performance_opened": False,
        "observed_evidence_end": required_end.date().isoformat(),
        "development_gates": development_gates,
        "falsification_gates": falsification_gates,
    }

    payloads = {
        "per_symbol_metrics.json": {"schema_version": "1.0", "windows": per_symbol},
        "aggregate_metrics.json": {"schema_version": "1.0", "windows": aggregate},
        "regime_metrics.json": {"schema_version": "1.0", "windows": regimes},
        "forward_state_metrics.json": {"schema_version": "1.0", "windows": forward_state},
        "decision.json": decision_payload,
    }
    for filename, payload in payloads.items():
        write_json(output_dir / filename, payload)

    manifest_without_identity = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "provider_identity_sha256": sha256_file(prices_csv),
        "spec_identity_sha256": sha256_file(spec_path),
        "reserved_start": reserved_start.date().isoformat(),
        "observed_evidence_end": required_end.date().isoformat(),
        "reserved_performance_opened": False,
        "outputs": {
            filename: sha256_file(output_dir / filename) for filename in payloads
        },
    }
    manifest = {
        **manifest_without_identity,
        "manifest_identity_sha256": _canonical_sha256(manifest_without_identity),
    }
    write_json(output_dir / "validation_manifest.json", manifest)
    return decision_payload
