"""Issue #966 Phase-6 certification of the selected US feature set.

Selection is already frozen by the Phase-6 subset decision. This module performs
one exact deterministic reproduction of that selected candidate and then applies
the previously approved skew exposure control exactly once. It never compares
control variants or reopens feature selection.
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
    STRESS_COST_BPS,
    _benchmark_instrument,
    _benchmark_map,
    _return_map,
    _score_frame,
    _score_hash,
    _sectors,
    _windows,
    _resolve_symbols,
)
from src.research.us_skew_exposure_control import (
    HIGH_RISK_EXPOSURE,
    NORMAL_EXPOSURE,
    RISK_FACTOR_ID,
    _aggregate,
    _evaluate_scaled,
    _period_hash,
    _risk_state,
)

RUNNER_ID = "issue966_phase6_selected_certification_v1"
EXPECTED_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
CONTROL_SPEC = PROJECT_ROOT / "configs/research_experiments/us_issue966_phase4_skew_exposure_v1.yaml"


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _expected_observation(
    observations: list[dict[str, Any]],
    *,
    candidate_id: str,
    window: str,
    cost_bps: int,
) -> dict[str, Any]:
    matches = [
        row
        for row in observations
        if str(row.get("candidate_id")) == candidate_id
        and str(row.get("window")) == window
        and int(row.get("cost_bps", -1)) == cost_bps
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one Stage-B observation for {candidate_id}/{window}/{cost_bps}bps"
        )
    return matches[0]


def _observation_reproduced(exact: dict[str, Any], expected: dict[str, Any]) -> bool:
    fields = ("total_return", "benchmark_return", "relative_excess", "worst_drawdown", "turnover")
    return all(
        field in expected
        and np.isclose(float(exact[field]), float(expected[field]), atol=1e-12, rtol=0.0)
        for field in fields
    )


def certify_selected_feature_set(
    spec_path: str | Path,
    decision_path: str | Path,
    observations_path: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    decision = _load_json(decision_path)
    observations_raw = _load_json(observations_path)
    if not isinstance(observations_raw, list):
        raise ValueError("Phase-6 certification observations must be a list")
    observations = [dict(row) for row in observations_raw if isinstance(row, dict)]
    if len(observations) != len(observations_raw):
        raise ValueError("Phase-6 certification observations contain non-mapping rows")
    if decision.get("experiment_id") != spec.experiment_id:
        raise ValueError("Phase-6 decision experiment identity drifted")
    selected_id = str(decision.get("selected_candidate_id") or "")
    if not selected_id:
        raise ValueError("Phase-6 certification requires a selected candidate")
    selected = next(
        (candidate for candidate in spec.candidates if candidate.candidate_id == selected_id),
        None,
    )
    if selected is None:
        raise ValueError(f"selected candidate is absent from Phase-6 spec: {selected_id}")
    if selected.role != "challenger":
        raise ValueError("Phase-6 selected candidate must be a challenger")
    if tuple(spec.contract.selection_windows) != EXPECTED_WINDOWS:
        raise ValueError("Phase-6 certification window contract drifted")
    reporting = dict(spec.raw.get("reporting_boundary") or {})
    if reporting.get("fresh_untouched_us_holdout_available") is not False:
        raise ValueError("Phase-6 certification must preserve the no-fresh-holdout boundary")

    runtime = runtime_for_market("us")
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    if observed_provider != spec.contract.provider_identity_sha256:
        raise ValueError("Phase-6 certification provider identity drifted")
    symbols = _resolve_symbols(spec, runtime)
    sectors, sector_identity = _sectors(spec, symbols)
    benchmark_symbol = _benchmark_instrument(spec, runtime)
    windows, evaluation_dates = _windows(spec, runtime)

    contracts = candidate_factor_contracts(spec)
    selected_contract = contracts[selected_id]
    expressions = list(selected_contract["expressions"])
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(expressions)
    }

    control = yaml.safe_load(CONTROL_SPEC.read_text(encoding="utf-8"))
    if not isinstance(control, dict):
        raise ValueError("Phase-4 skew control contract is malformed")
    risk_signal = dict(control.get("risk_signal") or {})
    risk_library = load_factor_library(PROJECT_ROOT / str(risk_signal["factor_library"]))
    risk_definition = risk_library.factor(RISK_FACTOR_ID)
    state = _risk_state(
        runtime,
        symbols,
        expression=risk_definition.expression,
        start=str(spec.parent.walk_forward["requested_train_start"]),
        end=spec.contract.cutoff,
    )
    gate_policy = dict(control.get("gate4_policy") or {})

    full_window_rows: dict[int, list[dict[str, Any]]] = {
        BASE_COST_BPS: [],
        STRESS_COST_BPS: [],
    }
    controlled_window_rows: dict[int, list[dict[str, Any]]] = {
        BASE_COST_BPS: [],
        STRESS_COST_BPS: [],
    }
    full_periods: dict[int, list[pd.DataFrame]] = {BASE_COST_BPS: [], STRESS_COST_BPS: []}
    controlled_periods: dict[int, list[pd.DataFrame]] = {
        BASE_COST_BPS: [],
        STRESS_COST_BPS: [],
    }
    score_reproduction: dict[str, bool] = {}
    full_exposure_reproduction: dict[str, dict[str, bool]] = {}
    control_reproduction: dict[str, dict[str, bool]] = {}
    stage_b_reproduction: dict[str, dict[str, bool]] = {}
    score_hashes: dict[str, dict[str, str]] = {}

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
        first_scores = fit_predict_ranker_scores(
            expressions=expressions,
            expression_columns=expression_columns,
            features_train=features_train,
            returns_train=returns_train,
            features_test=features_test,
            calibration=selected.calibration,
            context=f"Issue966 Phase6 certification/{window.label}/{selected_id}",
        )
        second_scores = fit_predict_ranker_scores(
            expressions=expressions,
            expression_columns=expression_columns,
            features_train=features_train,
            returns_train=returns_train,
            features_test=features_test,
            calibration=selected.calibration,
            context=f"Issue966 Phase6 certification/{window.label}/{selected_id}",
        )
        first_hash = _score_hash(first_scores)
        second_hash = _score_hash(second_scores)
        score_hashes[window.label] = {"first": first_hash, "second": second_hash}
        score_reproduction[window.label] = first_hash == second_hash

        score_frame = _score_frame(first_scores)
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
            raise ValueError(f"skew threshold lacks prior-history warm-up in {window.label}")
        controlled_exposure = {
            pd.Timestamp(date): float(value)
            for date, value in threshold_rows["exposure"].items()
        }
        full_exposure = {date: NORMAL_EXPOSURE for date in rebalance_dates}
        full_exposure_reproduction[window.label] = {}
        control_reproduction[window.label] = {}
        stage_b_reproduction[window.label] = {}

        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            exact_result, exact_period_frame, _, _, _ = sector_cap._evaluate(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                cost_bps=cost_bps,
                sector_cap=True,
            )
            reproduced_result, reproduced_period_frame = _evaluate_scaled(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                full_exposure,
                cost_bps=cost_bps,
            )
            full_exposure_reproduction[window.label][str(cost_bps)] = bool(
                np.allclose(
                    reproduced_period_frame["net_return"].to_numpy(dtype=float),
                    exact_period_frame["net_return"].to_numpy(dtype=float),
                    atol=1e-12,
                    rtol=0.0,
                )
                and all(
                    np.isclose(
                        float(reproduced_result[key]),
                        float(exact_result[key]),
                        atol=1e-12,
                        rtol=0.0,
                    )
                    for key in ("total_return", "benchmark_return", "max_drawdown", "turnover", "costs")
                )
            )
            expected = _expected_observation(
                observations,
                candidate_id=selected_id,
                window=window.label,
                cost_bps=cost_bps,
            )
            stage_b_reproduction[window.label][str(cost_bps)] = _observation_reproduced(
                exact_result,
                expected,
            )

            controlled_result, controlled_frame = _evaluate_scaled(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                controlled_exposure,
                cost_bps=cost_bps,
            )
            repeated_result, repeated_frame = _evaluate_scaled(
                score_frame,
                returns_by_date,
                benchmark_by_date,
                sectors,
                controlled_exposure,
                cost_bps=cost_bps,
            )
            control_reproduction[window.label][str(cost_bps)] = bool(
                _period_hash(controlled_frame) == _period_hash(repeated_frame)
                and all(
                    np.isclose(
                        float(controlled_result[key]),
                        float(repeated_result[key]),
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
                    float(exact_result["total_return"]),
                    float(exact_result["benchmark_return"]),
                ),
                "max_drawdown": float(exact_result["max_drawdown"]),
                "turnover": float(exact_result["turnover"]),
                "costs": float(exact_result["costs"]),
                "high_risk_periods": 0,
            }
            full_window_rows[cost_bps].append(exact_window)
            controlled_window_rows[cost_bps].append(
                {"window": window.label, **controlled_result}
            )
            full_periods[cost_bps].append(
                exact_period_frame.loc[:, ["rebalance_date", "net_return"]].assign(
                    window=window.label
                )
            )
            controlled_periods[cost_bps].append(
                controlled_frame.assign(window=window.label)
            )

    full = {
        str(cost): _aggregate(full_window_rows[cost], full_periods[cost])
        for cost in (BASE_COST_BPS, STRESS_COST_BPS)
    }
    controlled = {
        str(cost): _aggregate(controlled_window_rows[cost], controlled_periods[cost])
        for cost in (BASE_COST_BPS, STRESS_COST_BPS)
    }
    full20 = full[str(BASE_COST_BPS)]
    full60 = full[str(STRESS_COST_BPS)]
    control20 = controlled[str(BASE_COST_BPS)]
    control60 = controlled[str(STRESS_COST_BPS)]
    drawdown_improvement = float(control20["max_drawdown"]) - float(full20["max_drawdown"])
    retention20 = float(control20["compounded_relative_excess"]) / float(
        full20["compounded_relative_excess"]
    )
    retention60 = float(control60["compounded_relative_excess"]) / float(
        full60["compounded_relative_excess"]
    )
    checks = {
        "selected_score_reproduction": all(score_reproduction.values()),
        "selected_stage_b_reproduction": all(
            all(costs.values()) for costs in stage_b_reproduction.values()
        ),
        "full_exposure_evaluator_reproduction": all(
            all(costs.values()) for costs in full_exposure_reproduction.values()
        ),
        "skew_control_reproduction": all(
            all(costs.values()) for costs in control_reproduction.values()
        ),
        "skew_drawdown_improvement": drawdown_improvement
        >= float(gate_policy["minimum_drawdown_improvement_20bps"]),
        "skew_relative_excess_retention_20bps": retention20
        >= float(gate_policy["minimum_relative_excess_retention_ratio_20bps"]),
        "skew_relative_excess_retention_60bps": retention60
        >= float(gate_policy["minimum_relative_excess_retention_ratio_60bps"]),
        "skew_positive_windows_20bps": int(control20["positive_windows"])
        >= int(gate_policy["minimum_positive_windows_20bps"]),
    }
    risk_state_hash = hashlib.sha256(
        state.to_csv(index=True, lineterminator="\n", float_format="%.17g").encode("utf-8")
    ).hexdigest()
    return_payload = {
        "schema_version": "1.0",
        "issue": 966,
        "phase": 6,
        "runner": RUNNER_ID,
        "experiment_id": spec.experiment_id,
        "status": "completed",
        "provider_identity_sha256": observed_provider,
        "selection_windows": list(EXPECTED_WINDOWS),
        "selected_candidate_id": selected_id,
        "selected_factor_ids": list(selected_contract["factor_ids"]),
        "selected_factor_count": len(selected_contract["factor_ids"]),
        "selected_implementation_hashes": dict(selected_contract["implementation_hashes"]),
        "sector_classification_sha256": sector_identity,
        "score_hashes": score_hashes,
        "stage_b_reproduction": stage_b_reproduction,
        "full_exposure_reproduction": full_exposure_reproduction,
        "skew_control_reproduction": control_reproduction,
        "risk_factor": {
            "factor_id": risk_definition.factor_id,
            "implementation_hash": risk_definition.implementation_hash,
            "expression": risk_definition.expression,
        },
        "risk_state_sha256": risk_state_hash,
        "full_exposure": full,
        "skew_controlled": controlled,
        "gate6_certification": {
            "checks": checks,
            "pass": all(checks.values()),
            "metrics": {
                "drawdown_improvement_20bps": drawdown_improvement,
                "relative_excess_retention_ratio_20bps": retention20,
                "relative_excess_retention_ratio_60bps": retention60,
                "high_risk_periods_20bps": int(control20["high_risk_periods"]),
            },
        },
        "reporting_boundary": reporting,
        "fresh_untouched_us_holdout_available": False,
        "promotion_eligible": False,
        "promotion_blocker": "no_fresh_untouched_us_holdout",
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(return_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return return_payload
