"""Issue #966 Phase-4 distribution-state diagnostics.

Return skewness and kurtosis are evaluated as risk-state diagnostics first. The
runner keeps the frozen market baseline ranker, universe, 10-session outcome
semantics and development windows, then asks whether cross-sectional distribution
state contains incremental information beyond maintained momentum/volatility/
breadth risk signals. It does not change model features or portfolio exposure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION,
    benchmark_instrument,
    candidate_factor_contracts,
    resolve_symbols,
    runtime_for_market,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window

SCHEMA_VERSION = "1.0"
DISTRIBUTION_LIBRARY = PROJECT_ROOT / "configs/factor_libraries/distribution_risk_research.yaml"
DISTRIBUTION_GROUP = "distribution_risk_20d"
EXISTING_RISK_COLUMNS = (
    "risk_benchmark_vol20",
    "risk_neg_benchmark_momentum60",
    "risk_neg_benchmark_ma200_distance",
    "risk_low_breadth60",
)
OUTCOME_COLUMNS = (
    "future_benchmark_loss_10d",
    "future_drawdown_severity_10d",
    "future_breadth_deterioration_10d",
    "ranker_failure_10d",
)
DIRECT_SPEARMAN_MIN = 0.08
PARTIAL_SPEARMAN_MIN = 0.05
MIN_POSITIVE_WINDOW_SHARE = 0.60
MIN_STRONG_OUTCOMES = 2


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _wide_field(frame: pd.DataFrame, expression: str) -> pd.DataFrame:
    normalized = normalize_qlib_frame_index(frame.copy())
    if len(normalized.columns) != 1:
        raise ValueError(f"expected one provider column for {expression}")
    normalized.columns = [expression]
    return normalized[expression].unstack("instrument").sort_index()


def _daily_rank_ic(scores: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    frame = scores[["score"]].join(returns[["return"]], how="inner").replace(
        [np.inf, -np.inf], np.nan
    )
    rows: dict[pd.Timestamp, float] = {}
    for date, group in frame.groupby(level="datetime"):
        clean = group.dropna()
        if len(clean) < 10:
            continue
        left = clean["score"].rank(method="average")
        right = clean["return"].rank(method="average")
        value = left.corr(right)
        if np.isfinite(value):
            rows[pd.Timestamp(date)] = float(value)
    return pd.Series(rows, name="daily_rank_ic", dtype=float).sort_index()


def _spearman(left: pd.Series, right: pd.Series) -> float:
    frame = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    if len(frame) < 20:
        return 0.0
    value = frame["left"].corr(frame["right"], method="spearman")
    return float(value) if np.isfinite(value) else 0.0


def _partial_spearman(
    signal: pd.Series,
    outcome: pd.Series,
    controls: pd.DataFrame,
) -> float:
    frame = pd.concat([signal.rename("signal"), outcome.rename("outcome"), controls], axis=1)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 30:
        return 0.0
    ranked = frame.rank(method="average", pct=True)
    x = ranked.loc[:, list(controls.columns)].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    signal_values = ranked["signal"].to_numpy(dtype=float)
    outcome_values = ranked["outcome"].to_numpy(dtype=float)
    signal_fit, *_ = np.linalg.lstsq(x, signal_values, rcond=None)
    outcome_fit, *_ = np.linalg.lstsq(x, outcome_values, rcond=None)
    signal_residual = signal_values - x @ signal_fit
    outcome_residual = outcome_values - x @ outcome_fit
    if signal_residual.std() <= 1e-12 or outcome_residual.std() <= 1e-12:
        return 0.0
    value = np.corrcoef(signal_residual, outcome_residual)[0, 1]
    return float(value) if np.isfinite(value) else 0.0


def _tail_spread(signal: pd.Series, outcome: pd.Series) -> float:
    frame = pd.concat([signal.rename("signal"), outcome.rename("outcome")], axis=1).dropna()
    if len(frame) < 50:
        return 0.0
    low = float(frame["signal"].quantile(0.20))
    high = float(frame["signal"].quantile(0.80))
    low_mean = float(frame.loc[frame["signal"] <= low, "outcome"].mean())
    high_mean = float(frame.loc[frame["signal"] >= high, "outcome"].mean())
    return high_mean - low_mean


def _window_correlations(
    signal: pd.Series,
    outcome: pd.Series,
    window_labels: pd.Series,
) -> dict[str, float]:
    frame = pd.concat(
        [signal.rename("signal"), outcome.rename("outcome"), window_labels.rename("window")],
        axis=1,
    ).dropna()
    result: dict[str, float] = {}
    for label, group in frame.groupby("window"):
        result[str(label)] = _spearman(group["signal"], group["outcome"])
    return result


def _future_drawdown_severity(close: pd.Series, horizon: int = 10) -> pd.Series:
    future = pd.concat([close.shift(-step) for step in range(1, horizon + 1)], axis=1)
    future_min = future.min(axis=1, skipna=False)
    drawdown = future_min / close - 1.0
    return (-drawdown).rename("future_drawdown_severity_10d")


def _market_state(close: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    benchmark_close = close[benchmark].astype(float)
    benchmark_ret = benchmark_close.pct_change()
    ma60 = close.rolling(60, min_periods=60).mean()
    breadth60 = (close.drop(columns=[benchmark]) > ma60.drop(columns=[benchmark])).mean(axis=1)
    benchmark_ma200 = benchmark_close.rolling(200, min_periods=200).mean()
    state = pd.DataFrame(index=close.index)
    state["risk_benchmark_vol20"] = benchmark_ret.rolling(20, min_periods=20).std()
    state["risk_neg_benchmark_momentum60"] = -(
        benchmark_close / benchmark_close.shift(60) - 1.0
    )
    state["risk_neg_benchmark_ma200_distance"] = -(
        benchmark_close / benchmark_ma200 - 1.0
    )
    state["risk_low_breadth60"] = 1.0 - breadth60
    state["future_benchmark_loss_10d"] = -(
        benchmark_close.shift(-10) / benchmark_close - 1.0
    )
    state["future_drawdown_severity_10d"] = _future_drawdown_severity(benchmark_close)
    state["future_breadth_deterioration_10d"] = -(breadth60.shift(-10) - breadth60)
    return state


def _selected_windows(spec, runtime) -> tuple[list[Any], dict[str, pd.DatetimeIndex]]:
    walk = spec.parent.walk_forward
    strategy = spec.parent.strategy
    calendar = runtime.calendar(
        str(walk["requested_train_start"]),
        min(str(walk["test_end"]), spec.contract.cutoff),
    )
    if len(calendar) == 0:
        raise ValueError("Phase-4 provider calendar is empty")
    available_end = min(
        pd.Timestamp(spec.contract.cutoff),
        pd.Timestamp(calendar.max()),
        pd.Timestamp(str(walk["test_end"])),
    ).strftime("%Y-%m-%d")
    plan = build_window_sampling_plan(
        calendar,
        str(walk["requested_train_start"]),
        available_end,
        first_test_year=int(walk["first_test_year"]),
        last_test_year=int(walk["last_test_year"]),
        min_complete_windows=int(walk["min_windows"]),
        partial_window_policy=str(walk["partial_window_policy"]),
        min_partial_window_eligible_sessions=walk.get("min_partial_window_eligible_sessions"),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    eligible = horizon_eligible_dates_by_window(plan, calendar)
    selected = [window for window in plan.selected_windows if window.label in spec.contract.selection_windows]
    labels = [window.label for window in selected]
    if labels != list(spec.contract.selection_windows):
        raise ValueError(
            f"Phase-4 selection windows drifted: expected={list(spec.contract.selection_windows)}, observed={labels}"
        )
    return selected, eligible


def evaluate_distribution_risk(
    phase2_spec_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate skew/kurt risk state without changing ranker or portfolio policy."""

    spec = load_cross_sectional_experiment_spec(phase2_spec_path)
    if spec.raw.get("research_only") is not True:
        raise ValueError("Phase-4 requires a research-only frozen baseline spec")
    runtime = runtime_for_market(spec.market)
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    if observed_provider != spec.contract.provider_identity_sha256:
        raise ValueError(
            "Phase-4 provider identity mismatch: "
            f"expected={spec.contract.provider_identity_sha256}, observed={observed_provider}"
        )

    symbols = resolve_symbols(spec, runtime)
    benchmark = benchmark_instrument(spec, runtime)
    factor_library = load_factor_library(DISTRIBUTION_LIBRARY)
    distribution_definitions = factor_library.factors_for_groups([DISTRIBUTION_GROUP])
    if len(distribution_definitions) != 2:
        raise ValueError("Phase-4 distribution library must contain exactly skew20 and kurt20")
    distribution_expressions = [definition.expression for definition in distribution_definitions]
    distribution_ids = [definition.factor_id for definition in distribution_definitions]

    contracts = candidate_factor_contracts(spec)
    baseline_id = spec.contract.baseline_candidate_id
    baseline_contract = contracts[baseline_id]
    baseline_candidate = next(
        candidate for candidate in spec.candidates if candidate.candidate_id == baseline_id
    )
    baseline_expressions = list(baseline_contract["expressions"])

    windows, eligible_by_window = _selected_windows(spec, runtime)
    all_evaluation_dates = pd.DatetimeIndex(
        sorted(
            {
                pd.Timestamp(date)
                for window in windows
                for date in eligible_by_window[window.label]
            }
        )
    )
    if spec.market == "cn" and any(date >= pd.Timestamp("2026-07-01") for date in all_evaluation_dates):
        raise ValueError("Phase-4 CN diagnostics crossed the reserved 2026H2 holdout")

    start = str(spec.parent.walk_forward["requested_train_start"])
    end = spec.contract.cutoff
    close = _wide_field(
        runtime.features([*symbols, benchmark], ["$close"], start, end),
        "$close",
    )
    market_state = _market_state(close, benchmark)

    distribution_raw = normalize_qlib_frame_index(
        runtime.features(symbols, distribution_expressions, start, end)
    ).replace([np.inf, -np.inf], np.nan)
    distribution_raw.columns = distribution_ids
    distribution_daily = distribution_raw.groupby(level="datetime").median()
    state = market_state.join(distribution_daily, how="left")
    state["risk_neg_median_skew20"] = -state["distribution_risk_research.ret_skew_20d"]
    state["risk_median_kurt20"] = state["distribution_risk_research.ret_kurt_20d"]

    rank_ic_parts: list[pd.Series] = []
    window_label_parts: list[pd.Series] = []
    for window in windows:
        dates = eligible_by_window[window.label]
        baseline_raw = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                baseline_expressions,
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        baseline_columns = {expression: f"feature_{index}" for index, expression in enumerate(baseline_expressions)}
        baseline_raw.columns = [baseline_columns[expression] for expression in baseline_expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                [TEN_SESSION_RETURN_EXPRESSION],
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": TEN_SESSION_RETURN_EXPRESSION,
            }
        )
        all_dates = baseline_raw.index.get_level_values("datetime")
        train_mask = (all_dates >= pd.Timestamp(window.train_start)) & (
            all_dates <= pd.Timestamp(window.train_end)
        )
        test_mask = all_dates.isin(dates)
        features_train, returns_train = purge_training_tail(
            baseline_raw.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        features_test = baseline_raw.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        returns_test.attrs.update(returns_all.attrs)
        scores = fit_predict_ranker_scores(
            expressions=baseline_expressions,
            expression_columns=baseline_columns,
            features_train=features_train,
            returns_train=returns_train,
            features_test=features_test,
            calibration=baseline_candidate.calibration,
            context=f"Issue966 Phase4 baseline/{spec.market}/{window.label}",
        )
        daily_ic = _daily_rank_ic(scores, returns_test)
        rank_ic_parts.append(daily_ic)
        window_label_parts.append(
            pd.Series(window.label, index=daily_ic.index, dtype="object")
        )

    rank_ic = pd.concat(rank_ic_parts).sort_index()
    window_labels = pd.concat(window_label_parts).sort_index()
    state["ranker_failure_10d"] = -rank_ic
    state = state.loc[state.index.isin(all_evaluation_dates)].copy()
    window_labels = window_labels.reindex(state.index)

    controls = state.loc[:, list(EXISTING_RISK_COLUMNS)]
    signals = {
        "negative_median_skew20": state["risk_neg_median_skew20"],
        "median_kurt20": state["risk_median_kurt20"],
    }
    diagnostics: dict[str, Any] = {}
    for signal_name, signal in signals.items():
        outcomes: dict[str, Any] = {}
        strong_count = 0
        key_stress_strong = False
        for outcome_name in OUTCOME_COLUMNS:
            outcome = state[outcome_name]
            direct = _spearman(signal, outcome)
            partial = _partial_spearman(signal, outcome, controls)
            tail = _tail_spread(signal, outcome)
            window_corr = _window_correlations(signal, outcome, window_labels)
            positive_share = (
                sum(value > 0 for value in window_corr.values()) / len(window_corr)
                if window_corr
                else 0.0
            )
            strong = bool(
                direct >= DIRECT_SPEARMAN_MIN
                and partial >= PARTIAL_SPEARMAN_MIN
                and tail > 0
                and positive_share >= MIN_POSITIVE_WINDOW_SHARE
            )
            strong_count += int(strong)
            if outcome_name in {"future_benchmark_loss_10d", "future_drawdown_severity_10d"}:
                key_stress_strong = key_stress_strong or strong
            outcomes[outcome_name] = {
                "direct_spearman": direct,
                "partial_spearman_controlling_existing_risk": partial,
                "top_minus_bottom_risk_quintile_outcome_spread": tail,
                "window_spearman": window_corr,
                "positive_window_share": positive_share,
                "strong": strong,
            }
        diagnostic_useful = strong_count >= MIN_STRONG_OUTCOMES
        control_candidate = bool(diagnostic_useful and key_stress_strong)
        diagnostics[signal_name] = {
            "strong_outcome_count": strong_count,
            "diagnostic_useful": diagnostic_useful,
            "control_candidate": control_candidate,
            "outcomes": outcomes,
        }

    existing_risk: dict[str, Any] = {}
    for signal_name in EXISTING_RISK_COLUMNS:
        existing_risk[signal_name] = {
            outcome_name: _spearman(state[signal_name], state[outcome_name])
            for outcome_name in OUTCOME_COLUMNS
        }

    control_candidates = [
        name for name, row in diagnostics.items() if row["control_candidate"]
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "issue": 966,
        "phase": 4,
        "market": spec.market,
        "experiment_id": spec.experiment_id,
        "scope": "distribution_state_diagnostic_only",
        "provider_identity_sha256": observed_provider,
        "cutoff": spec.contract.cutoff,
        "selection_windows": list(spec.contract.selection_windows),
        "universe_count": len(symbols),
        "baseline_candidate_id": baseline_id,
        "baseline_factor_ids": list(baseline_contract["factor_ids"]),
        "distribution_factor_ids": distribution_ids,
        "thresholds": {
            "direct_spearman_min": DIRECT_SPEARMAN_MIN,
            "partial_spearman_min": PARTIAL_SPEARMAN_MIN,
            "minimum_positive_window_share": MIN_POSITIVE_WINDOW_SHARE,
            "minimum_strong_outcomes": MIN_STRONG_OUTCOMES,
        },
        "row_count": int(len(state)),
        "diagnostics": diagnostics,
        "existing_risk_signal_correlations": existing_risk,
        "control_candidates": control_candidates,
        "decision": (
            "eligible_for_single_use_control_test"
            if control_candidates
            else "keep_distribution_factors_diagnostic_only"
        ),
        "state_frame_sha256": hashlib.sha256(
            state.to_csv(index=True, lineterminator="\n", float_format="%.17g").encode("utf-8")
        ).hexdigest(),
        "research_only": True,
        "trade_ready": False,
        "model_features_changed": False,
        "portfolio_policy_changed": False,
    }
    if output_path is not None:
        _write_json(Path(output_path), payload)
    return payload
