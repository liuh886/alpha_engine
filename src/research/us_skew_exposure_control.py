"""Issue #966 Phase-4 single-use US skew exposure-control experiment.

The experiment keeps the frozen US x1.2 score, selection, sector cap, 10-session
holding cadence and 20/60 bps cost semantics. The only changed quantity is gross
risky exposure: 100% normally and 50% when negative cross-sectional median
20-session return skew exceeds its strictly lagged trailing 252-session 80th
percentile. No threshold or exposure search is performed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

import scripts.run_us_x1_1_drawdown_attribution_phase_a as phase_a
import scripts.run_us_x1_1_rank_aware_sector_cap as sector_cap
from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec
from src.research.economics import relative_excess
from src.research.qlib_execution_common import load_window_benchmark_returns, normalize_qlib_frame_index
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION as RETURN_EXPRESSION,
    candidate_factor_contracts,
    runtime_for_market,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.us_ranker_exact_portfolio_replay import (
    BASE_COST_BPS,
    MAX_NAMES_PER_SECTOR,
    STRESS_COST_BPS,
    TOP_N,
    _benchmark_instrument,
    _benchmark_map,
    _return_map,
    _score_frame,
    _score_hash,
    _sectors,
    _windows,
    _resolve_symbols,
)

RUNNER_ID = "us_skew_exposure_control_v1"
RISK_FACTOR_ID = "distribution_risk_research.ret_skew_20d"
EXPECTED_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
LOOKBACK_SESSIONS = 252
THRESHOLD_QUANTILE = 0.80
HIGH_RISK_EXPOSURE = 0.50
NORMAL_EXPOSURE = 1.00


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_control_contract(path: str | Path) -> tuple[dict[str, Any], Path]:
    source = Path(path)
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    source = source.resolve()
    source.relative_to(PROJECT_ROOT.resolve())
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Phase-4 skew exposure contract must be a mapping")
    if payload.get("experiment_id") != "us_issue966_phase4_skew_exposure_v1":
        raise ValueError("unexpected Phase-4 skew exposure experiment_id")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise ValueError("Phase-4 skew exposure test must remain research-only")
    signal = dict(payload.get("risk_signal") or {})
    control = dict(payload.get("control") or {})
    threshold = dict(control.get("threshold") or {})
    frozen = dict(payload.get("frozen") or {})
    expected = {
        "factor_id": signal.get("factor_id"),
        "use": control.get("use"),
        "lookback_sessions": threshold.get("lookback_sessions"),
        "quantile": threshold.get("quantile"),
        "lag_sessions": threshold.get("lag_sessions"),
        "normal_exposure": control.get("normal_exposure"),
        "high_risk_exposure": control.get("high_risk_exposure"),
        "selection_windows": tuple(frozen.get("selection_windows") or ()),
        "costs_bps": tuple(frozen.get("costs_bps") or ()),
    }
    required = {
        "factor_id": RISK_FACTOR_ID,
        "use": "exposure_scaling",
        "lookback_sessions": LOOKBACK_SESSIONS,
        "quantile": THRESHOLD_QUANTILE,
        "lag_sessions": 1,
        "normal_exposure": NORMAL_EXPOSURE,
        "high_risk_exposure": HIGH_RISK_EXPOSURE,
        "selection_windows": EXPECTED_WINDOWS,
        "costs_bps": (BASE_COST_BPS, STRESS_COST_BPS),
    }
    if expected != required:
        raise ValueError(f"Phase-4 skew exposure contract drifted: {expected}")
    return payload, source


def _risk_state(
    runtime,
    symbols: list[str],
    *,
    expression: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    raw = normalize_qlib_frame_index(
        runtime.features(symbols, [expression], start, end)
    ).replace([np.inf, -np.inf], np.nan)
    if len(raw.columns) != 1:
        raise ValueError("skew exposure control expected one canonical risk factor")
    raw.columns = ["skew20"]
    median_skew = raw["skew20"].groupby(level="datetime").median().sort_index()
    risk = -median_skew
    threshold = (
        risk.shift(1)
        .rolling(LOOKBACK_SESSIONS, min_periods=LOOKBACK_SESSIONS)
        .quantile(THRESHOLD_QUANTILE)
    )
    exposure = pd.Series(
        np.where(risk > threshold, HIGH_RISK_EXPOSURE, NORMAL_EXPOSURE),
        index=risk.index,
        name="exposure",
        dtype=float,
    )
    state = pd.DataFrame(
        {
            "negative_median_skew20": risk,
            "lagged_trailing_80pct_threshold": threshold,
            "exposure": exposure,
        }
    )
    return state


def _evaluate_scaled(
    scores: pd.DataFrame,
    returns: dict[pd.Timestamp, dict[str, float]],
    benchmark: dict[pd.Timestamp, float],
    sector_by_symbol: dict[str, str],
    exposure_by_date: dict[pd.Timestamp, float],
    *,
    cost_bps: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())][
        :: phase_a.REBALANCE_DAYS
    ]
    missing = [date for date in dates if date not in exposure_by_date]
    if missing:
        raise ValueError(f"risk-control exposure missing rebalance dates: {missing[:5]}")

    holdings: dict[str, float] = {}
    nav = [1.0]
    benchmark_nav = [1.0]
    rows: list[dict[str, Any]] = []
    total_turnover = 0.0
    total_cost = 0.0

    for period_index, date in enumerate(dates):
        exposure = float(exposure_by_date[date])
        if exposure not in {NORMAL_EXPOSURE, HIGH_RISK_EXPOSURE}:
            raise ValueError(f"unexpected exposure {exposure} at {date}")
        ranked = sector_cap._ranked_day(scores, date)
        selected, _, _ = sector_cap._select_names(
            ranked,
            sector_by_symbol,
            sector_cap=True,
        )
        target = {name: exposure / TOP_N for name in selected}
        union = sorted(set(holdings) | set(target))
        abs_delta = float(
            sum(abs(target.get(name, 0.0) - holdings.get(name, 0.0)) for name in union)
        )
        turnover = abs_delta / 2.0
        cost = turnover * cost_bps / 10_000.0
        date_returns = returns.get(date, {})
        effective = phase_a._effective_return_weights(target, date_returns)
        gross_return = float(
            sum(weight * date_returns[name] for name, weight in effective.items())
        )
        net_return = gross_return - cost
        benchmark_return = float(benchmark.get(date, 0.0))
        nav.append(nav[-1] * (1.0 + net_return))
        benchmark_nav.append(benchmark_nav[-1] * (1.0 + benchmark_return))
        total_turnover += turnover
        total_cost += cost
        rows.append(
            {
                "period_index": period_index,
                "rebalance_date": date,
                "exposure": exposure,
                "turnover": turnover,
                "cost": cost,
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "nav": nav[-1],
                "benchmark_nav": benchmark_nav[-1],
            }
        )
        holdings = target

    periods = pd.DataFrame(rows)
    result = {
        "cost_bps": int(cost_bps),
        "total_return": float(nav[-1] - 1.0),
        "benchmark_return": float(benchmark_nav[-1] - 1.0),
        "relative_excess": relative_excess(float(nav[-1] - 1.0), float(benchmark_nav[-1] - 1.0)),
        "max_drawdown": phase_a._max_drawdown(nav),
        "turnover": total_turnover,
        "costs": total_cost,
        "n_periods": len(periods),
        "high_risk_periods": int((periods["exposure"] == HIGH_RISK_EXPOSURE).sum()),
    }
    return result, periods


def _period_hash(frame: pd.DataFrame) -> str:
    ordered = frame.copy()
    ordered["rebalance_date"] = pd.to_datetime(ordered["rebalance_date"])
    payload = ordered.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aggregate(window_rows: list[dict[str, Any]], period_rows: list[pd.DataFrame]) -> dict[str, Any]:
    if len(window_rows) != len(EXPECTED_WINDOWS):
        raise ValueError("skew exposure aggregate requires all four US selection windows")
    strategy_nav = float(np.prod([1.0 + float(row["total_return"]) for row in window_rows]))
    benchmark_nav = float(
        np.prod([1.0 + float(row["benchmark_return"]) for row in window_rows])
    )
    combined = pd.concat(period_rows, ignore_index=True)
    nav = np.cumprod(1.0 + combined["net_return"].to_numpy(dtype=float))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    return {
        "compounded_total_return": strategy_nav - 1.0,
        "compounded_benchmark_return": benchmark_nav - 1.0,
        "compounded_relative_excess": strategy_nav - benchmark_nav,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "turnover": float(sum(float(row["turnover"]) for row in window_rows)),
        "costs": float(sum(float(row["costs"]) for row in window_rows)),
        "positive_windows": int(sum(float(row["relative_excess"]) > 0.0 for row in window_rows)),
        "high_risk_periods": int(sum(int(row["high_risk_periods"]) for row in window_rows)),
        "period_count": int(len(combined)),
    }


def run_us_skew_exposure_control(
    control_spec_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    contract, contract_path = _load_control_contract(control_spec_path)
    baseline_path = PROJECT_ROOT / str(contract["baseline_experiment"])
    baseline_spec = load_cross_sectional_experiment_spec(baseline_path)
    if baseline_spec.market != "us":
        raise ValueError("skew exposure control requires the frozen US baseline experiment")
    if baseline_spec.contract.baseline_candidate_id != contract["baseline_candidate_id"]:
        raise ValueError("skew exposure baseline candidate drifted")
    if tuple(baseline_spec.contract.selection_windows) != EXPECTED_WINDOWS:
        raise ValueError("skew exposure test must use the Phase-2 US selection windows")

    runtime = runtime_for_market("us")
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    if observed_provider != baseline_spec.contract.provider_identity_sha256:
        raise ValueError("skew exposure provider identity differs from Phase-2 baseline")
    symbols = _resolve_symbols(baseline_spec, runtime)
    sectors, sector_identity = _sectors(baseline_spec, symbols)
    benchmark_symbol = _benchmark_instrument(baseline_spec, runtime)
    windows, evaluation_dates = _windows(baseline_spec, runtime)

    risk_library_path = PROJECT_ROOT / str(contract["risk_signal"]["factor_library"])
    risk_library = load_factor_library(risk_library_path)
    risk_definition = risk_library.factor(RISK_FACTOR_ID)
    state = _risk_state(
        runtime,
        symbols,
        expression=risk_definition.expression,
        start=str(baseline_spec.parent.walk_forward["requested_train_start"]),
        end=baseline_spec.contract.cutoff,
    )

    factor_contract = candidate_factor_contracts(baseline_spec)[baseline_spec.contract.baseline_candidate_id]
    baseline_candidate = next(
        candidate
        for candidate in baseline_spec.candidates
        if candidate.candidate_id == baseline_spec.contract.baseline_candidate_id
    )
    expressions = list(factor_contract["expressions"])
    expression_columns = {expression: f"feature_{index}" for index, expression in enumerate(expressions)}

    by_cost_baseline: dict[int, list[dict[str, Any]]] = {BASE_COST_BPS: [], STRESS_COST_BPS: []}
    by_cost_control: dict[int, list[dict[str, Any]]] = {BASE_COST_BPS: [], STRESS_COST_BPS: []}
    baseline_periods: dict[int, list[pd.DataFrame]] = {BASE_COST_BPS: [], STRESS_COST_BPS: []}
    control_periods: dict[int, list[pd.DataFrame]] = {BASE_COST_BPS: [], STRESS_COST_BPS: []}
    baseline_reproduction: dict[str, dict[str, bool]] = {}
    control_reproduction: dict[str, dict[str, bool]] = {}
    score_hashes: dict[str, str] = {}

    for window in windows:
        dates = evaluation_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, expressions, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[expression] for expression in expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {"provenance": "raw_forward_return", "horizon": 10, "expression": RETURN_EXPRESSION}
        )
        all_dates = features_all.index.get_level_values("datetime")
        train_mask = (all_dates >= pd.Timestamp(window.train_start)) & (
            all_dates <= pd.Timestamp(window.train_end)
        )
        test_mask = all_dates.isin(dates)
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            returns_all.loc[train_mask].copy(),
            holding_days=10,
        )
        features_test = features_all.loc[test_mask].copy()
        returns_test = returns_all.loc[test_mask].copy()
        returns_test.attrs.update(returns_all.attrs)
        scores = fit_predict_ranker_scores(
            expressions=expressions,
            expression_columns=expression_columns,
            features_train=features_train,
            returns_train=returns_train,
            features_test=features_test,
            calibration=baseline_candidate.calibration,
            context=f"Issue966 Phase4 skew control/{window.label}",
        )
        score_hashes[window.label] = _score_hash(scores)
        score_frame = _score_frame(scores)
        returns_by_date = _return_map(returns_test)
        benchmark = load_window_benchmark_returns(
            runtime,
            benchmark_instrument=benchmark_symbol,
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=dates,
            start=window.test_start,
            end=window.test_end,
            provenance="raw_forward_return",
            horizon=10,
        )
        benchmark_by_date = _benchmark_map(benchmark)
        rebalance_dates = [
            pd.Timestamp(value) for value in sorted(score_frame["datetime"].unique())
        ][:: phase_a.REBALANCE_DAYS]
        threshold_rows = state.reindex(rebalance_dates)
        if threshold_rows["lagged_trailing_80pct_threshold"].isna().any():
            raise ValueError(f"risk threshold lacks strictly historical warm-up in {window.label}")
        controlled_exposure = {
            pd.Timestamp(date): float(value)
            for date, value in threshold_rows["exposure"].items()
        }
        full_exposure = {date: NORMAL_EXPOSURE for date in rebalance_dates}
        baseline_reproduction[window.label] = {}
        control_reproduction[window.label] = {}

        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            exact_result, exact_periods, _, _, _ = sector_cap._evaluate(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                cost_bps=cost_bps,
                sector_cap=True,
            )
            reproduced_result, reproduced_periods = _evaluate_scaled(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                full_exposure,
                cost_bps=cost_bps,
            )
            economic_match = all(
                np.isclose(
                    float(reproduced_result[key]),
                    float(exact_result[key]),
                    atol=1e-12,
                    rtol=0.0,
                )
                for key in ("total_return", "benchmark_return", "max_drawdown", "turnover", "costs")
            )
            period_match = np.allclose(
                reproduced_periods["net_return"].to_numpy(dtype=float),
                exact_periods["net_return"].to_numpy(dtype=float),
                atol=1e-12,
                rtol=0.0,
            )
            baseline_reproduction[window.label][str(cost_bps)] = bool(
                economic_match and period_match
            )

            control_result, controlled_period_frame = _evaluate_scaled(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                controlled_exposure,
                cost_bps=cost_bps,
            )
            second_result, second_period_frame = _evaluate_scaled(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                controlled_exposure,
                cost_bps=cost_bps,
            )
            control_reproduction[window.label][str(cost_bps)] = bool(
                _period_hash(controlled_period_frame) == _period_hash(second_period_frame)
                and all(
                    np.isclose(
                        float(control_result[key]),
                        float(second_result[key]),
                        atol=1e-12,
                        rtol=0.0,
                    )
                    for key in ("total_return", "benchmark_return", "max_drawdown", "turnover", "costs")
                )
            )
            exact_window = {
                "window": window.label,
                "cost_bps": cost_bps,
                "total_return": float(exact_result["total_return"]),
                "benchmark_return": float(exact_result["benchmark_return"]),
                "relative_excess": relative_excess(
                    float(exact_result["total_return"]), float(exact_result["benchmark_return"])
                ),
                "max_drawdown": float(exact_result["max_drawdown"]),
                "turnover": float(exact_result["turnover"]),
                "costs": float(exact_result["costs"]),
                "high_risk_periods": 0,
            }
            controlled_window = {"window": window.label, **control_result}
            by_cost_baseline[cost_bps].append(exact_window)
            by_cost_control[cost_bps].append(controlled_window)
            baseline_periods[cost_bps].append(
                exact_periods.loc[:, ["rebalance_date", "net_return"]].assign(window=window.label)
            )
            control_periods[cost_bps].append(
                controlled_period_frame.assign(window=window.label)
            )

    baseline = {
        str(cost): _aggregate(by_cost_baseline[cost], baseline_periods[cost])
        for cost in (BASE_COST_BPS, STRESS_COST_BPS)
    }
    controlled = {
        str(cost): _aggregate(by_cost_control[cost], control_periods[cost])
        for cost in (BASE_COST_BPS, STRESS_COST_BPS)
    }
    policy = dict(contract["gate4_policy"])
    base20 = baseline[str(BASE_COST_BPS)]
    base60 = baseline[str(STRESS_COST_BPS)]
    control20 = controlled[str(BASE_COST_BPS)]
    control60 = controlled[str(STRESS_COST_BPS)]
    drawdown_improvement = float(control20["max_drawdown"]) - float(base20["max_drawdown"])
    retention20 = float(control20["compounded_relative_excess"]) / float(
        base20["compounded_relative_excess"]
    )
    retention60 = float(control60["compounded_relative_excess"]) / float(
        base60["compounded_relative_excess"]
    )
    baseline_exact = all(
        all(costs.values()) for costs in baseline_reproduction.values()
    )
    control_deterministic = all(
        all(costs.values()) for costs in control_reproduction.values()
    )
    checks = {
        "drawdown_improvement": drawdown_improvement
        >= float(policy["minimum_drawdown_improvement_20bps"]),
        "relative_excess_retention_20bps": retention20
        >= float(policy["minimum_relative_excess_retention_ratio_20bps"]),
        "relative_excess_retention_60bps": retention60
        >= float(policy["minimum_relative_excess_retention_ratio_60bps"]),
        "positive_windows_20bps": int(control20["positive_windows"])
        >= int(policy["minimum_positive_windows_20bps"]),
        "exact_full_exposure_baseline_reproduction": baseline_exact,
        "deterministic_control_reproduction": control_deterministic,
    }

    receipt = {
        "schema_version": "1.0",
        "issue": 966,
        "phase": 4,
        "experiment_id": contract["experiment_id"],
        "runner": RUNNER_ID,
        "status": "completed",
        "provider_identity_sha256": observed_provider,
        "selection_windows": list(EXPECTED_WINDOWS),
        "risk_factor": {
            "factor_id": risk_definition.factor_id,
            "implementation_hash": risk_definition.implementation_hash,
            "expression": risk_definition.expression,
            "state": "negative_cross_sectional_median",
        },
        "control": contract["control"],
        "sector_classification_sha256": sector_identity,
        "baseline": baseline,
        "controlled": controlled,
        "baseline_reproduction": baseline_reproduction,
        "control_reproduction": control_reproduction,
        "score_hashes": score_hashes,
        "risk_state_sha256": hashlib.sha256(
            state.to_csv(index=True, lineterminator="\n", float_format="%.17g").encode("utf-8")
        ).hexdigest(),
        "gate4": {
            "checks": checks,
            "pass": all(checks.values()),
            "metrics": {
                "drawdown_improvement_20bps": drawdown_improvement,
                "relative_excess_retention_ratio_20bps": retention20,
                "relative_excess_retention_ratio_60bps": retention60,
                "high_risk_periods_20bps": int(control20["high_risk_periods"]),
            },
        },
        "contract_path": str(contract_path.relative_to(PROJECT_ROOT)),
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    if output_path is not None:
        _write_json(Path(output_path), receipt)
    return receipt
