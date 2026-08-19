"""Build the governed US x1.3 research-preview evidence bundle.

Historical evidence is recomputed from the frozen model contract. Live forward
state is never inferred here independently: an already sealed canonical signal
may be supplied explicitly and projected into the preview for provisional MTM.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

import scripts.run_us_x1_1_rank_aware_sector_cap as sector_cap
from src.artifacts.model_run_exporter import RunExportPlan, SectionPlan
from src.data.market_provider import load_provider_manifest
from src.factors.model_contract import resolve_model_factor_inputs
from src.research.daily_ranker import prepare_ranker_frame
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

MODEL_ID = "us_x1_3"
MODEL_FAMILY_ID = "us_ranker"
MODEL_CONFIG = Path("configs/models/us_x1_3.yaml")
UNIVERSE_CONFIG = Path("configs/research_universes/us_selected_equities_v2.yaml")
CLASSIFICATION_CONFIG = Path(
    "configs/research_classifications/us87_sector_industry_v1.yaml"
)
FACTOR_LIBRARY = Path("configs/factor_libraries/ohlcv.yaml")
RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
DEVELOPMENT_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
RESEARCH_ONLY = True
TRADE_READY = False


class USX13PreviewError(ValueError):
    """The active research baseline cannot be published without drift."""


@dataclass(frozen=True)
class WindowEvidence:
    label: str
    role: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    result: Mapping[str, Any]
    periods: pd.DataFrame
    contributions: pd.DataFrame
    selections: pd.DataFrame
    score_sha256: str


def _yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise USX13PreviewError(f"expected YAML mapping: {path}")
    return payload


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _score_sha(scores: pd.DataFrame) -> str:
    body = scores.sort_index().to_csv(float_format="%.17g", lineterminator="\n")
    return hashlib.sha256(body.encode()).hexdigest()


def _finite(value: object) -> float | None:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _calibration(config: Mapping[str, Any]) -> XGBNativeCalibration:
    model = dict(config.get("model") or {})
    label = dict(config.get("label") or {})
    fields = {
        "n_gain_bins": label.get("gain_bins"),
        "num_boost_round": model.get("num_boost_round"),
        "max_leaves": model.get("max_leaves"),
        "max_depth": model.get("max_depth"),
        "min_child_weight": model.get("min_child_weight"),
        "learning_rate": model.get("learning_rate"),
        "subsample": model.get("subsample"),
        "colsample_bytree": model.get("colsample_bytree"),
        "reg_alpha": model.get("reg_alpha"),
        "reg_lambda": model.get("reg_lambda"),
        "seed": model.get("seed"),
    }
    if any(value is None for value in fields.values()):
        raise USX13PreviewError("US x1.3 native XGBoost contract is incomplete")
    return XGBNativeCalibration.from_dict(fields)


def _symbols(root: Path, runtime: QlibUSExecutionRuntime) -> list[str]:
    universe = _yaml(root / UNIVERSE_CONFIG)
    requested = [str(value) for value in universe.get("symbols", [])]
    expected = int(universe.get("candidate_count", 0))
    normalized = normalize_market_symbols(
        "us", requested, available_symbols=runtime.available_symbols()
    )
    result = [value.normalized_symbol for value in normalized]
    if len(result) != expected or len(result) != len(set(result)):
        raise USX13PreviewError("US x1.3 universe identity is not exact")
    return result


def _sectors(root: Path, symbols: list[str]) -> dict[str, str]:
    payload = _yaml(root / CLASSIFICATION_CONFIG)
    records = payload.get("records")
    if not isinstance(records, dict):
        raise USX13PreviewError("US sector classification is invalid")
    result = {
        str(symbol): str(record["sector"])
        for symbol, record in records.items()
        if isinstance(record, dict) and record.get("sector")
    }
    missing = sorted(set(symbols) - set(result))
    if missing:
        raise USX13PreviewError(f"US sector classification is incomplete: {missing}")
    return {symbol: result[symbol] for symbol in symbols}


def _windows(runtime: QlibUSExecutionRuntime) -> tuple[list[Any], dict[str, pd.DatetimeIndex]]:
    development_calendar = runtime.calendar("2021-01-01", "2025-12-31")
    development = build_window_sampling_plan(
        development_calendar,
        "2021-01-01",
        "2025-12-31",
        first_test_year=2024,
        last_test_year=2025,
        min_complete_windows=4,
        partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    if tuple(value.label for value in development.selected_windows) != DEVELOPMENT_WINDOWS:
        raise USX13PreviewError("US x1.3 development-window contract changed")

    current_calendar = runtime.calendar("2021-01-01", "2026-12-31")
    current_end = current_calendar.max().strftime("%Y-%m-%d")
    current = build_window_sampling_plan(
        current_calendar,
        "2021-01-01",
        current_end,
        first_test_year=2026,
        last_test_year=2026,
        min_complete_windows=1,
        partial_window_policy="allow_horizon_contained_partial_final_window",
        min_partial_window_eligible_sessions=10,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    windows = [*development.selected_windows, *current.selected_windows]
    dates = horizon_eligible_dates_by_window(development, development_calendar)
    dates.update(horizon_eligible_dates_by_window(current, current_calendar))
    return windows, dates


def _fit_window(
    runtime: QlibUSExecutionRuntime,
    *,
    symbols: list[str],
    sectors: Mapping[str, str],
    expressions: list[str],
    calibration: XGBNativeCalibration,
    window: Any,
    evaluation_dates: pd.DatetimeIndex,
) -> WindowEvidence:
    features = normalize_qlib_frame_index(
        runtime.features(symbols, expressions, window.train_start, window.test_end)
    ).replace([np.inf, -np.inf], np.nan)
    features.columns = [f"feature_{index}" for index in range(len(expressions))]
    returns = normalize_qlib_frame_index(
        runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
    )
    returns.columns = ["return"]
    dates = features.index.get_level_values("datetime")
    train_mask = (dates >= pd.Timestamp(window.train_start)) & (
        dates <= pd.Timestamp(window.train_end)
    )
    test_mask = dates.isin(evaluation_dates)
    train_features, train_returns = purge_training_tail(
        features.loc[train_mask].copy(),
        returns.loc[train_mask].copy(),
        holding_days=10,
    )
    valid, reason = validate_no_nan_inputs(
        train_features, context=f"US x1.3 preview/{window.label}"
    )
    if not valid:
        raise USX13PreviewError(reason)
    x_rank, y_rank, groups = prepare_ranker_frame(train_features, train_returns)
    fitted = fit_xgb_native_daily_ranker(
        x_rank, y_rank, groups, calibration=calibration
    )
    scores = predict_xgb_native_daily_ranker(fitted, features.loc[test_mask].copy())

    evaluated_returns = returns.loc[
        returns.index.get_level_values("datetime").isin(evaluation_dates)
    ]
    return_lookup = {
        pd.Timestamp(date): {
            str(row["instrument"]): float(row["return"])
            for row in group.reset_index().to_dict("records")
            if pd.notna(row["return"])
        }
        for date, group in evaluated_returns.groupby(level="datetime")
    }
    benchmark_frame = normalize_qlib_frame_index(
        runtime.features(
            ["QQQ"],
            [RETURN_EXPRESSION],
            evaluation_dates.min().strftime("%Y-%m-%d"),
            evaluation_dates.max().strftime("%Y-%m-%d"),
        )
    )
    benchmark_frame.columns = ["return"]
    benchmark = {
        pd.Timestamp(date): float(group["return"].iloc[0])
        for date, group in benchmark_frame.groupby(level="datetime")
    }
    result, periods, contributions, selections, _ = sector_cap._evaluate(
        scores.reset_index(),
        return_lookup,
        benchmark,
        dict(sectors),
        cost_bps=20,
        sector_cap=True,
    )
    role = (
        "development"
        if window.label in DEVELOPMENT_WINDOWS
        else "reporting_only"
        if pd.Timestamp(window.test_start) < pd.Timestamp("2026-07-01")
        else "prospective_partial"
    )
    return WindowEvidence(
        label=str(window.label),
        role=role,
        train_start=str(window.train_start),
        train_end=str(window.train_end),
        test_start=evaluation_dates.min().strftime("%Y-%m-%d"),
        test_end=evaluation_dates.max().strftime("%Y-%m-%d"),
        result=result,
        periods=periods,
        contributions=contributions,
        selections=selections,
        score_sha256=_score_sha(scores),
    )


def _price_panel(
    runtime: QlibUSExecutionRuntime,
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    frame = normalize_qlib_frame_index(
        runtime.features(symbols, ["$close", "$amount"], start, end)
    )
    frame.columns = ["price", "market_amount"]
    return frame.sort_index()


def _market_value(panel: pd.DataFrame, date: str, instrument: str, field: str) -> float | None:
    timestamp = pd.Timestamp(date)
    for candidate in (instrument, instrument.lower(), instrument.upper()):
        try:
            return _finite(panel.loc[(timestamp, candidate), field])
        except KeyError:
            continue
    return None


def _holding_end(calendar: list[str], signal_date: str) -> str:
    try:
        index = calendar.index(signal_date)
    except ValueError as exc:
        raise USX13PreviewError(f"signal date missing from provider calendar: {signal_date}") from exc
    if index + 10 >= len(calendar):
        raise USX13PreviewError(f"unrealized US x1.3 holding: {signal_date}")
    return calendar[index + 10]


def _next_due_signal(calendar: list[str], last_signal: str, cutoff: str) -> str | None:
    try:
        index = calendar.index(last_signal)
    except ValueError as exc:
        raise USX13PreviewError(f"last signal is absent from provider calendar: {last_signal}") from exc
    due = index + 10
    return calendar[due] if due < len(calendar) and calendar[due] <= cutoff else None


def _weights(value: object, *, label: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise USX13PreviewError(f"{label} weights are missing")
    weights = {str(key): float(weight) for key, weight in value.items()}
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise USX13PreviewError(f"{label} weights do not sum to one")
    return dict(sorted(weights.items()))


def _same_weights(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    return set(left) == set(right) and all(
        math.isclose(left[key], right[key], rel_tol=0.0, abs_tol=1e-12)
        for key in left
    )


def _project_current_signal(
    canonical_signal: Mapping[str, Any],
    *,
    expected_signal_date: str,
    previous: Mapping[str, float],
    sectors: Mapping[str, str],
    panel: pd.DataFrame,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if canonical_signal.get("model_version_id") != MODEL_ID:
        raise USX13PreviewError("US x1.3 forward signal model identity changed")
    signal_date = str(canonical_signal.get("signal_date") or "")
    if signal_date != expected_signal_date:
        raise USX13PreviewError(
            f"US x1.3 forward signal date mismatch: {signal_date} != {expected_signal_date}"
        )
    current = _weights(canonical_signal.get("current_weights"), label="canonical current")
    target = _weights(canonical_signal.get("target_weights"), label="canonical target")
    if not _same_weights(current, previous):
        raise USX13PreviewError("US x1.3 canonical current weights differ from settled state")
    if len(target) != 15:
        raise USX13PreviewError("US x1.3 canonical target must contain 15 names")

    expected_turnover = 0.5 * sum(
        abs(target.get(name, 0.0) - current.get(name, 0.0))
        for name in set(current) | set(target)
    )
    turnover = float(canonical_signal.get("turnover_units") or 0.0)
    if not math.isclose(expected_turnover, turnover, rel_tol=0.0, abs_tol=1e-12):
        raise USX13PreviewError("US x1.3 canonical turnover does not reconcile")

    diagnostics = canonical_signal.get("diagnostics")
    diagnostic_map = dict(diagnostics) if isinstance(diagnostics, Mapping) else {}
    ranks = diagnostic_map.get("selected_ranks")
    rank_map = dict(ranks) if isinstance(ranks, Mapping) else {}
    explanations = diagnostic_map.get("model_explanations")
    explanation_map: dict[str, Mapping[str, Any]] = {}
    if isinstance(explanations, Mapping):
        rows = explanations.get("rows")
        if isinstance(rows, list):
            explanation_map = {
                str(row.get("instrument")): row
                for row in rows
                if isinstance(row, Mapping) and row.get("instrument")
            }

    ranked_targets: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    for instrument, weight in target.items():
        price = _market_value(panel, signal_date, instrument, "price")
        if price is None or price <= 0:
            raise USX13PreviewError(
                f"canonical US x1.3 target has no governed entry price: {instrument}/{signal_date}"
            )
        rank = rank_map.get(instrument)
        explanation = explanation_map.get(instrument, {})
        score = _finite(explanation.get("score"))
        ranked_targets.append(
            {
                "instrument": instrument,
                "sector": sectors[instrument],
                "rank": int(rank) if rank is not None else None,
                "score": score,
                "target_weight": weight,
                "reference_price": price,
            }
        )
        positions.append(
            {
                "date": signal_date,
                "holding_end_date": None,
                "window": "current_target",
                "window_role": "prospective_unrealized",
                "instrument": instrument,
                "sector": sectors[instrument],
                "rank": int(rank) if rank is not None else None,
                "score": score,
                "weight": weight,
                "action": "BUY" if previous.get(instrument, 0.0) == 0 else "HOLD",
                "price": price,
                "price_basis": "governed_adjusted_close_signal_reference",
                "market_amount": _market_value(panel, signal_date, instrument, "market_amount"),
                "market_amount_semantics": "diagnostic_synthetic_adjusted_close_times_volume",
                "entry_price": price,
                "exit_price": None,
                "realized_return": None,
                "benchmark_return": None,
                "excess_return": None,
                "profitable": None,
                "beat_benchmark": None,
                "holding_status": "prospective_unrealized",
            }
        )

    trades: list[dict[str, Any]] = []
    for instrument in sorted(set(previous) | set(target)):
        old = previous.get(instrument, 0.0)
        new = target.get(instrument, 0.0)
        delta = new - old
        action = (
            "BUY" if old == 0 and new > 0 else
            "SELL" if old > 0 and new == 0 else
            "INCREASE" if delta > 0 else
            "DECREASE" if delta < 0 else "HOLD"
        )
        price = _market_value(panel, signal_date, instrument, "price")
        if new > 0 and (price is None or price <= 0):
            raise USX13PreviewError(
                f"canonical US x1.3 target has no governed execution price: {instrument}/{signal_date}"
            )
        trades.append(
            {
                "date": signal_date,
                "holding_end_date": None,
                "window": "current_target",
                "window_role": "prospective_unrealized",
                "instrument": instrument,
                "action": action,
                "previous_weight": old,
                "target_weight": new,
                "weight_delta": delta,
                "normalized_notional": abs(delta),
                "normalized_notional_unit": "portfolio_nav_equals_1",
                "quantity": None,
                "amount": None,
                "amount_unavailable_reason": "No governed portfolio capital or brokerage lot-size contract is declared.",
                "execution_price": price,
                "execution_price_basis": "governed_adjusted_close_signal_reference",
                "entry_price": price if new > 0 else None,
                "exit_price": price if new == 0 else None,
                "realized_return": None,
                "benchmark_return": None,
                "excess_return": None,
                "profitable": None,
                "beat_benchmark": None,
                "transaction_cost": abs(delta) * 20 / 10_000,
                "holding_status": "prospective_unrealized",
            }
        )

    signal = {
        "signal_date": signal_date,
        "holding_end_date": None,
        "window": "current_target",
        "window_role": "prospective_unrealized",
        "model_version_id": MODEL_ID,
        "previous_weights": dict(sorted(previous.items())),
        "target_weights": target,
        "ranked_targets": sorted(
            ranked_targets,
            key=lambda row: (row["rank"] is None, row["rank"] or 999, row["instrument"]),
        ),
        "execution_semantics": "signal_at_adjusted_close_target_applies_next_eligible_open",
        "cost_bps": 20,
        "turnover": turnover,
        "signal_state": "prospective_unrealized",
        "canonical_signal_fingerprint": canonical_signal.get("fingerprint"),
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    signal["signal_sha256"] = _canonical_sha(signal)
    return signal, positions, trades


def _trade_analytics(positions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    realized = [row for row in positions if _finite(row.get("realized_return")) is not None]
    winners = [row for row in realized if float(row["realized_return"]) > 0]
    losers = [row for row in realized if float(row["realized_return"]) <= 0]
    alpha_winners = [row for row in realized if float(row["excess_return"]) > 0]
    gains = sum(float(row["realized_return"]) for row in winners)
    losses = -sum(float(row["realized_return"]) for row in losers)
    return {
        "schema_version": "trade_outcome_analytics_v1",
        "outcome_unit": "completed_equal_weight_10_session_holding_episode",
        "episode_count": len(realized),
        "profitable_episode_count": len(winners),
        "win_rate": len(winners) / len(realized) if realized else None,
        "alpha_hit_rate": len(alpha_winners) / len(realized) if realized else None,
        "average_winner": float(np.mean([row["realized_return"] for row in winners])) if winners else None,
        "average_loser": float(np.mean([row["realized_return"] for row in losers])) if losers else None,
        "profit_factor": gains / losses if losses else None,
        "rebalance_event_count": len(trades),
        "normalized_notional": sum(abs(float(row["weight_delta"])) for row in trades),
        "normalized_notional_unit": "portfolio_nav_equals_1",
        "quantity_available": False,
        "quantity_unavailable_reason": "No governed portfolio capital or brokerage lot-size contract is declared.",
        "market_amount_semantics": "diagnostic synthetic adjusted_close_times_volume; not reported venue turnover",
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }


def _metric(metric_id: str, value: float | None, *, unit: str, direction: str, sample_count: int) -> dict[str, Any]:
    available = value is not None and math.isfinite(value)
    return {
        "metric_id": metric_id,
        "value": float(value) if available else None,
        "unit": unit,
        "direction": direction,
        "estimator": "governed_us_x1_3_preview_trace" if available else None,
        "annualization": "252_sessions" if metric_id in {"annualized_return", "annualized_volatility", "sharpe_ratio", "information_ratio"} and available else None,
        "sample_count": sample_count if available else None,
        "scope": "certification_development_plus_reporting_and_partial_prospective",
        "availability_status": "available" if available else "not_computed",
        "unavailable_reason": None if available else "The governed preview builder did not compute this metric.",
    }


def build_plan(
    root: Path,
    *,
    provider_dir: Path,
    generated_at: str,
    forward_signal: Mapping[str, Any] | None = None,
) -> RunExportPlan:
    root = root.resolve()
    provider_dir = provider_dir.resolve()
    config = _yaml(root / MODEL_CONFIG)
    if config.get("model_id") != MODEL_ID or config.get("status") != "baseline_research_active":
        raise USX13PreviewError("US x1.3 is not the active research baseline")
    selection = dict(config.get("selection_decision") or {})
    if selection.get("formal_acceptance") is not False or selection.get("research_baseline_promotion") is not True:
        raise USX13PreviewError("US x1.3 preview/formal boundary changed")

    runtime = QlibUSExecutionRuntime(provider_uri=provider_dir)
    runtime.initialize(root)
    provider = load_provider_manifest(
        provider_dir, expected_market="us", required=True, verify_files=True
    )
    if provider is None:
        raise USX13PreviewError("US provider manifest is unavailable")
    cutoff = str(provider["calendar"]["last_day"])
    symbols = _symbols(root, runtime)
    sectors = _sectors(root, symbols)
    calibration = _calibration(config)
    try:
        _, expressions = resolve_model_factor_inputs(
            root=root,
            features=dict(config.get("features") or {}),
            expected_library=FACTOR_LIBRARY,
            expected_count=13,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise USX13PreviewError(str(exc)) from exc
    windows, dates = _windows(runtime)
    evidence = [
        _fit_window(
            runtime,
            symbols=symbols,
            sectors=sectors,
            expressions=expressions,
            calibration=calibration,
            window=window,
            evaluation_dates=dates[window.label],
        )
        for window in windows
    ]

    calendar = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in runtime.calendar("2021-01-01", cutoff)]
    first_signal = min(row.test_start for row in evidence)
    panel = _price_panel(runtime, [*symbols, "QQQ"], first_signal, cutoff)
    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    attribution: dict[str, dict[str, Any]] = {}
    previous: dict[str, float] = {}
    account = benchmark_account = peak = 1.0
    global_period = 0
    period_returns: list[float] = []
    benchmark_returns: list[float] = []
    window_summary: list[dict[str, Any]] = []

    for window in evidence:
        contributions_by_period = {
            int(index): group
            for index, group in window.contributions.groupby("period_index")
        }
        for period in window.periods.sort_values("period_index").to_dict("records"):
            local_period = int(period["period_index"])
            signal_date = pd.Timestamp(period["rebalance_date"]).strftime("%Y-%m-%d")
            holding_end = _holding_end(calendar, signal_date)
            rows = contributions_by_period[local_period]
            held = rows.loc[rows["target_weight"] > 0].copy()
            target = {
                str(row.instrument): float(row.target_weight)
                for row in held.itertuples(index=False)
            }
            if len(target) != 15 or not math.isclose(sum(target.values()), 1.0, abs_tol=1e-9):
                raise USX13PreviewError(f"US x1.3 target is incomplete: {signal_date}")
            net_return = float(period["net_return"])
            benchmark_return = float(period["benchmark_return"])
            account *= 1.0 + net_return
            benchmark_account *= 1.0 + benchmark_return
            peak = max(peak, account)
            period_returns.append(net_return)
            benchmark_returns.append(benchmark_return)
            report.append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "window": window.label,
                    "window_role": window.role,
                    "period_index": global_period,
                    "period_return": net_return,
                    "benchmark_return": benchmark_return,
                    "excess_return": net_return - benchmark_return,
                    "turnover": float(period["turnover"]),
                    "transaction_cost": float(period["cost"]),
                    "account": account,
                    "bench_qqq": benchmark_account,
                    "drawdown": account / peak - 1.0,
                    "trace_frequency": "non_overlapping_10_session",
                }
            )
            signal_rows: list[dict[str, Any]] = []
            outcome_by_instrument: dict[str, dict[str, Any]] = {}
            for row in held.itertuples(index=False):
                instrument = str(row.instrument)
                realized = float(row.forward_10d_return)
                entry_price = _market_value(panel, signal_date, instrument, "price")
                exit_price = _market_value(panel, holding_end, instrument, "price")
                market_amount = _market_value(panel, signal_date, instrument, "market_amount")
                outcome = {
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "realized_return": realized,
                    "benchmark_return": benchmark_return,
                    "excess_return": realized - benchmark_return,
                    "profitable": realized > 0,
                    "beat_benchmark": realized > benchmark_return,
                }
                outcome_by_instrument[instrument] = outcome
                action = "BUY" if previous.get(instrument, 0.0) == 0 else "HOLD"
                position = {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "window": window.label,
                    "window_role": window.role,
                    "period_index": global_period,
                    "instrument": instrument,
                    "sector": sectors[instrument],
                    "rank": int(row.rank) if pd.notna(row.rank) else None,
                    "score": _finite(row.score),
                    "weight": float(row.target_weight),
                    "action": action,
                    "price": entry_price,
                    "price_basis": "governed_adjusted_close",
                    "market_amount": market_amount,
                    "market_amount_semantics": "diagnostic_synthetic_adjusted_close_times_volume",
                    **outcome,
                }
                positions.append(position)
                signal_rows.append(
                    {
                        "instrument": instrument,
                        "sector": sectors[instrument],
                        "rank": position["rank"],
                        "score": position["score"],
                        "target_weight": position["weight"],
                        "reference_price": entry_price,
                    }
                )
                item = attribution.setdefault(
                    instrument,
                    {
                        "instrument": instrument,
                        "name": instrument,
                        "sector": sectors[instrument],
                        "gross_contribution": 0.0,
                        "transaction_cost": 0.0,
                        "value": 0.0,
                        "periods_held": 0,
                        "profitable_periods": 0,
                        "alpha_positive_periods": 0,
                    },
                )
                item["gross_contribution"] += float(row.gross_contribution)
                item["transaction_cost"] += float(row.allocated_cost)
                item["value"] += float(row.net_contribution)
                item["periods_held"] += 1
                item["profitable_periods"] += int(realized > 0)
                item["alpha_positive_periods"] += int(realized > benchmark_return)

            for instrument in sorted(set(previous) | set(target)):
                old = previous.get(instrument, 0.0)
                new = target.get(instrument, 0.0)
                delta = new - old
                action = (
                    "BUY" if old == 0 and new > 0 else
                    "SELL" if old > 0 and new == 0 else
                    "INCREASE" if delta > 0 else
                    "DECREASE" if delta < 0 else "HOLD"
                )
                outcome = outcome_by_instrument.get(instrument, {})
                execution_price = _market_value(panel, signal_date, instrument, "price")
                trades.append(
                    {
                        "date": signal_date,
                        "holding_end_date": holding_end if new > 0 else None,
                        "window": window.label,
                        "window_role": window.role,
                        "period_index": global_period,
                        "instrument": instrument,
                        "action": action,
                        "previous_weight": old,
                        "target_weight": new,
                        "weight_delta": delta,
                        "normalized_notional": abs(delta),
                        "normalized_notional_unit": "portfolio_nav_equals_1",
                        "quantity": None,
                        "amount": None,
                        "amount_unavailable_reason": "No governed portfolio capital or brokerage lot-size contract is declared.",
                        "execution_price": execution_price,
                        "execution_price_basis": "governed_adjusted_close_model_evidence",
                        "entry_price": outcome.get("entry_price") if new > 0 else None,
                        "exit_price": outcome.get("exit_price") if new > 0 else execution_price,
                        "realized_return": outcome.get("realized_return"),
                        "benchmark_return": outcome.get("benchmark_return"),
                        "excess_return": outcome.get("excess_return"),
                        "profitable": outcome.get("profitable"),
                        "beat_benchmark": outcome.get("beat_benchmark"),
                        "transaction_cost": abs(delta) * 20 / 10_000,
                    }
                )
            signal = {
                "signal_date": signal_date,
                "holding_end_date": holding_end,
                "window": window.label,
                "window_role": window.role,
                "model_version_id": MODEL_ID,
                "target_weights": dict(sorted(target.items())),
                "ranked_targets": sorted(signal_rows, key=lambda row: int(row["rank"] or 999)),
                "execution_semantics": "adjusted_close_to_adjusted_close_10_session_research_evidence",
                "cost_bps": 20,
                "research_only": RESEARCH_ONLY,
                "trade_ready": TRADE_READY,
            }
            signal["signal_sha256"] = _canonical_sha(signal)
            signals.append(signal)
            previous = target
            global_period += 1

        window_summary.append(
            {
                "window": window.label,
                "role": window.role,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "start": window.test_start,
                "end": window.test_end,
                "periods": len(window.periods),
                "total_return": float(window.result["total_return"]),
                "benchmark_return": float(window.result["benchmark_return"]),
                "relative_excess_return": (1 + float(window.result["total_return"])) / (1 + float(window.result["benchmark_return"])) - 1,
                "max_drawdown": float(window.result["max_drawdown"]),
                "turnover": float(window.result["turnover"]),
                "transaction_cost": float(window.result["costs"]),
                "score_sha256": window.score_sha256,
            }
        )

    latest_realized_signal = signals[-1]
    due_signal = _next_due_signal(calendar, str(latest_realized_signal["signal_date"]), cutoff)
    if forward_signal is not None:
        if due_signal is None:
            raise USX13PreviewError("canonical US x1.3 forward signal exists before a due session")
        current_signal, current_positions, current_trades = _project_current_signal(
            forward_signal,
            expected_signal_date=due_signal,
            previous=previous,
            sectors=sectors,
            panel=panel,
        )
        signals.append(current_signal)
        positions.extend(current_positions)
        trades.extend(current_trades)
    elif due_signal is not None:
        # Settled evidence is still valid, but live state remains absent until the
        # canonical ledger owns the due decision.
        pass

    for item in attribution.values():
        periods_held = int(item["periods_held"])
        item["win_rate"] = item.pop("profitable_periods") / periods_held
        item["alpha_hit_rate"] = item.pop("alpha_positive_periods") / periods_held
    attribution_rows = sorted(
        attribution.values(), key=lambda row: abs(float(row["value"])), reverse=True
    )
    analytics = _trade_analytics(positions, trades)
    total_return = account - 1.0
    benchmark_return = benchmark_account - 1.0
    excess_return = account / benchmark_account - 1.0
    observations = len(period_returns)
    years = observations * 10 / 252 if observations else 0.0
    annualized_return = (account ** (1 / years) - 1) if years > 0 else None
    volatility = float(np.std(period_returns, ddof=1) * math.sqrt(252 / 10)) if observations > 1 else None
    sharpe = float(np.mean(period_returns) / np.std(period_returns, ddof=1) * math.sqrt(252 / 10)) if observations > 1 and np.std(period_returns, ddof=1) > 0 else None
    excess_periods = np.array(period_returns) - np.array(benchmark_returns)
    information_ratio = float(np.mean(excess_periods) / np.std(excess_periods, ddof=1) * math.sqrt(252 / 10)) if observations > 1 and np.std(excess_periods, ddof=1) > 0 else None
    max_drawdown = min(float(row["drawdown"]) for row in report)
    total_turnover = sum(float(row["turnover"]) for row in report)
    total_cost = sum(float(row["transaction_cost"]) for row in report)
    certification = dict(config.get("certification_evidence") or {})
    development = dict(certification.get("development") or {})
    metrics = [
        _metric("total_return", total_return, unit="ratio", direction="higher_is_better", sample_count=observations),
        _metric("annualized_return", annualized_return, unit="ratio", direction="higher_is_better", sample_count=observations),
        _metric("benchmark_return", benchmark_return, unit="ratio", direction="descriptive", sample_count=observations),
        _metric("excess_return", excess_return, unit="ratio", direction="higher_is_better", sample_count=observations),
        _metric("annualized_volatility", volatility, unit="ratio", direction="lower_is_better", sample_count=observations),
        _metric("sharpe_ratio", sharpe, unit="decimal", direction="higher_is_better", sample_count=observations),
        _metric("information_ratio", information_ratio, unit="decimal", direction="higher_is_better", sample_count=observations),
        _metric("max_drawdown", max_drawdown, unit="ratio", direction="higher_is_better", sample_count=observations),
        _metric("turnover", total_turnover, unit="ratio", direction="lower_is_better", sample_count=observations),
        _metric("transaction_cost", total_cost, unit="ratio", direction="lower_is_better", sample_count=observations),
        _metric("ic", None, unit="decimal", direction="higher_is_better", sample_count=observations),
        _metric("rank_ic", _finite(development.get("mean_rank_ic")), unit="decimal", direction="higher_is_better", sample_count=observations),
        _metric("icir", _finite(development.get("mean_icir")), unit="decimal", direction="higher_is_better", sample_count=observations),
    ]
    latest_signal = signals[-1]

    if latest_signal.get("signal_state") == "prospective_unrealized":
        signal_date = str(latest_signal["signal_date"])
        target_weights = {
            str(key): float(value)
            for key, value in dict(latest_signal["target_weights"]).items()
        }
        gross_mtm = 0.0
        for instrument, weight in target_weights.items():
            entry = _market_value(panel, signal_date, instrument, "price")
            current = _market_value(panel, cutoff, instrument, "price")
            if entry is None or current is None or entry <= 0:
                raise USX13PreviewError(
                    f"missing provisional MTM price for canonical target {instrument}: {signal_date}/{cutoff}"
                )
            gross_mtm += weight * (current / entry - 1.0)
        qqq_entry = _market_value(panel, signal_date, "QQQ", "price")
        qqq_current = _market_value(panel, cutoff, "QQQ", "price")
        if qqq_entry is None or qqq_current is None or qqq_entry <= 0:
            raise USX13PreviewError("missing QQQ provisional MTM price")
        mtm_cost = float(latest_signal.get("turnover") or 0.0) * 20 / 10_000
        net_mtm = gross_mtm - mtm_cost
        benchmark_mtm = qqq_current / qqq_entry - 1.0
        mtm_account = account * (1.0 + net_mtm)
        mtm_benchmark = benchmark_account * (1.0 + benchmark_mtm)
        settled_peak = max([1.0, *[float(row["account"]) for row in report]])
        report.append(
            {
                "date": cutoff,
                "signal_date": signal_date,
                "holding_end_date": cutoff,
                "window": "current_target",
                "window_role": "prospective_unrealized",
                "period_index": global_period,
                "period_return": net_mtm,
                "benchmark_return": benchmark_mtm,
                "excess_return": net_mtm - benchmark_mtm,
                "turnover": float(latest_signal.get("turnover") or 0.0),
                "transaction_cost": mtm_cost,
                "account": mtm_account,
                "bench_qqq": mtm_benchmark,
                "drawdown": mtm_account / max(settled_peak, mtm_account) - 1.0,
                "trace_frequency": "provisional_mtm_to_evidence_cutoff",
                "partial_window": True,
                "provisional_mtm": True,
                "settlement_status": "provisional_mtm",
                "mtm_as_of": cutoff,
                "research_only": True,
                "trade_ready": False,
            }
        )

    completeness = {
        "status": "complete",
        "performance": "retained_exact_period_trace",
        "holdings": "retained_with_entry_and_exit_model_prices",
        "trades": "retained_rebalance_events_with_normalized_notional_and_outcomes",
        "signals": "retained_hash_bound_rebalance_targets",
        "attribution": "retained_reconciled_name_contributions",
        "quantity": "not_applicable_without_governed_capital_contract",
        "missing": ["brokerage_quantity", "brokerage_fill_price"],
    }
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": MODEL_FAMILY_ID,
        "model_version_id": MODEL_ID,
        "run_id": f"{MODEL_ID}-through-{cutoff.replace('-', '_')}",
        "display_name": "US x1.3",
        "market": "us",
        "benchmark": "QQQ",
        "baseline_status": "active_research_baseline",
        "formal_acceptance_status": "prospective_gate_pending",
        "decision_status": "supported_research_baseline_not_formal",
        "metrics": metrics,
        "trade_analytics": analytics,
        "latest_signal": latest_signal,
        "latest_realized_signal": latest_realized_signal,
        "evidence_completeness": completeness,
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    performance = {
        "schema_version": "2.0.0",
        "report": report,
        "date_range": {"start": report[0]["date"], "end": report[-1]["holding_end_date"]},
        "benchmark": "QQQ",
        "trace_frequency": "non_overlapping_10_session",
        "performance_semantics": {
            "signal_time": "adjusted_close_of_signal_date",
            "execution_time": "same_adjusted_close_research_mark",
            "return_measurement": "adjusted_close_t_to_t_plus_10_sessions",
            "holding_end_offset_sessions": 10,
            "return_basis": "net_of_declared_transaction_cost",
            "price_basis": "governed_adjusted_close",
            "execution_model": "close_to_close_10_session_research_evidence",
            "cost_bps": 20,
            "cost": {
                "rate_bps": 20,
                "turnover_formula": "0.5 * sum(abs(target_weight - previous_weight))",
                "net_return_formula": "gross_return - turnover * 20 / 10000",
            },
        },
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    portfolio = {
        "schema_version": "2.0.0",
        "portfolio_contract": {
            "universe": "us_selected_equities_v2",
            "topk": 15,
            "weighting": "equal_weight",
            "maximum_names_per_sector": 4,
            "horizon_sessions": 10,
            "rebalance_sessions": 10,
            "cost_bps": 20,
            "return_expression": RETURN_EXPRESSION,
            "quantity_contract": "unavailable_without_governed_capital_base",
        },
        "positions": positions,
        "signals": signals,
        "latest_signal": latest_signal,
        "latest_realized_signal": latest_realized_signal,
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    trade_payload = {
        "schema_version": "trade_ledger_v2",
        "records": trades,
        "analytics": analytics,
        "price_semantics": "governed adjusted-close model evidence; not brokerage fills",
        "amount_semantics": "normalized_notional uses NAV=1; market_amount is a synthetic diagnostic",
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    risk = {
        "schema_version": "2.0.0",
        "metrics": [row for row in metrics if row["metric_id"] in {"annualized_volatility", "max_drawdown", "turnover", "transaction_cost"}],
        "trade_analytics": analytics,
        "interpretation_limit": "Research preview only; the untouched six-month prospective gate remains pending.",
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    robustness = {
        "schema_version": "2.0.0",
        "window_summary": window_summary,
        "interpretation_limit": "2026H1 is reporting-only and 2026H2 is an incomplete prospective window.",
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    diagnostics = {
        "schema_version": "2.0.0",
        "evidence_completeness": completeness,
        "interpretation_notes": [
            "US x1.3 is the active research baseline and is not the accepted formal baseline.",
            "Entry and exit prices are adjusted-close prices used by the governed research return contract, not brokerage fills.",
            "Live forward state is projected only from the canonical append-only signal ledger; preview inference does not create a second decision.",
            "Amount is exposed as normalized notional on NAV=1 because no governed portfolio capital or quantity contract exists.",
            "US market amount is synthetic adjusted close multiplied by volume and is diagnostic only.",
            "The six-month untouched prospective acceptance gate remains pending; trade_ready=false.",
        ],
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    lineage = {
        "schema_version": "2.0.0",
        "source_model_config": MODEL_CONFIG.as_posix(),
        "source_model_config_sha256": hashlib.sha256((root / MODEL_CONFIG).read_bytes()).hexdigest(),
        "builder_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "factor_library_sha256": hashlib.sha256((root / FACTOR_LIBRARY).read_bytes()).hexdigest(),
        "universe_config_sha256": hashlib.sha256((root / UNIVERSE_CONFIG).read_bytes()).hexdigest(),
        "classification_config_sha256": hashlib.sha256((root / CLASSIFICATION_CONFIG).read_bytes()).hexdigest(),
        "provider_identity_sha256": provider["provider_identity_sha256"],
        "calibration_identity": calibration.identity_manifest(),
        "selected_candidate": "mvv_plus_pressure",
        "certification_workflow_run_id": dict(config.get("lineage") or {}).get("certification_workflow_run_id"),
        "formal_baseline_superseded_for_research": "us_x1_2",
        "formal_acceptance_gate_passed": False,
        "historical_evidence_recomputed": True,
        "model_selection_reopened": False,
        "forward_decision_authority": "canonical_strategy_signal_ledger",
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    sections = (
        SectionPlan("summary", "available", True, _json_safe(summary)),
        SectionPlan("performance", "available", True, _json_safe(performance)),
        SectionPlan("risk", "available", False, _json_safe(risk)),
        SectionPlan("robustness", "available", True, _json_safe(robustness)),
        SectionPlan("portfolio", "available", True, _json_safe(portfolio)),
        SectionPlan("trades", "available", True, _json_safe(trade_payload)),
        SectionPlan("attribution", "available", False, _json_safe(attribution_rows)),
        SectionPlan("diagnostics", "available", False, _json_safe(diagnostics)),
        SectionPlan("lineage", "available", True, _json_safe(lineage)),
        SectionPlan("decision", "not_retained", False, reason="The governed promotion decision remains a companion repository artifact."),
    )
    return RunExportPlan(
        model_family_id=MODEL_FAMILY_ID,
        model_version_id=MODEL_ID,
        run_id=summary["run_id"],
        model_kind="cross_sectional_ranker",
        publication_channel="preview",
        publication_status="ci_validated_preview",
        generated_at=generated_at,
        evidence_cutoff=cutoff,
        comparability_key={
            "market": "us",
            "universe_id": "us_selected_equities_v2",
            "benchmark_id": "qqq",
            "start": report[0]["date"],
            "end": report[-1]["holding_end_date"],
            "trace_frequency": "non_overlapping_10_session",
            "horizon": "10_sessions",
            "rebalance_contract_id": "top15_sector4_10_sessions",
            "cost_contract_id": "cost_20_bps",
        },
        sections=sections,
        research_only=RESEARCH_ONLY,
        trade_ready=TRADE_READY,
    )
