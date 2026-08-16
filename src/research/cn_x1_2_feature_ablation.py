"""Issue #966 Phase-2 exact feature ablation for the current CN x1.2 baseline.

This runner changes only ranker factor inputs. It reuses the maintained CN130
provider, score training, two-of-three regime state, breadth-scaled four-name
portfolio, delay-1 execution returns and 20/60 bps cost semantics. 2026H2 is a
hard forbidden boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cn130_cross_sectional_ranking import (
    forward_returns,
    load_provider_panel,
    stack_return_frame,
)
from src.research.cn_ranker_exact_portfolio_replay import (
    BASE_COST_BPS,
    BENCHMARK,
    STRESS_COST_BPS,
    _frame_hash,
    _ledger,
    _load_benchmark_returns,
    _score_hash,
    _write_json,
    economic_rebalance_dates,
    validate_benchmark_execution_economic_rebalance_dates,
    validate_execution_economic_rebalance_dates,
)
from src.research.cn_x1_1_regime_gated import RegimeGateSpec, build_regime_state, run_regime_portfolio
from src.research.cn_x1_2_breadth_scaled_development import (
    DEVELOPMENT_HARD_STOP,
    DEVELOPMENT_WINDOWS,
    RESERVED_HOLDOUT_START,
    _assert_no_2026h2,
    _development_windows,
    _portfolio_contract,
)
from src.research.cross_sectional_experiment_runner import load_cross_sectional_experiment_spec
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION as RETURN_EXPRESSION,
    benchmark_instrument as _benchmark_instrument,
    candidate_factor_contracts,
    resolve_symbols as _resolve_symbols,
    runtime_for_market as _runtime_for_market,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate

RUNNER_ID = "cn_x1_2_feature_ablation_v1"
POOL_SIZE = 130
RULE = "two_of_three"
EXPOSURE_POLICY = "breadth_scaled"


def _candidate_policy_map(spec) -> dict[str, tuple[str, str]]:
    rows = spec.raw.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("Phase-2 CN candidates must be mappings")
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Phase-2 CN candidate entry must be a mapping")
        candidate_id = str(row.get("candidate_id", "")).strip()
        rule = str(row.get("regime_rule", "")).strip()
        exposure = str(row.get("exposure_policy", "")).strip()
        if rule != RULE or exposure != EXPOSURE_POLICY:
            raise ValueError(
                f"candidate {candidate_id} must keep {RULE}/{EXPOSURE_POLICY}; "
                f"got {rule}/{exposure}"
            )
        result[candidate_id] = (rule, exposure)
    expected = {candidate.candidate_id for candidate in spec.candidates}
    if set(result) != expected:
        raise ValueError("candidate policy metadata differs from parsed candidates")
    return result


def _mean(rows: Sequence[dict[str, Any]], field: str) -> float:
    values = [float(row[field]) for row in rows]
    return float(np.mean(values)) if values else 0.0


def _diagnostic_summary(rows: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    selected = [row for row in rows if row["candidate_id"] == candidate_id]
    if len(selected) != len(DEVELOPMENT_WINDOWS):
        raise ValueError(
            f"candidate {candidate_id} has {len(selected)} diagnostics; "
            f"expected {len(DEVELOPMENT_WINDOWS)}"
        )
    return {
        "mean_ic": _mean(selected, "ic"),
        "mean_rank_ic": _mean(selected, "rank_ic"),
        "mean_icir": _mean(selected, "icir"),
        "mean_positive_ic_ratio": _mean(selected, "positive_ic_ratio"),
        "mean_top_minus_bottom_spread": _mean(selected, "top_minus_bottom_spread"),
        "windows": selected,
    }


def _candidate_rows(spec) -> dict[str, Any]:
    rows = spec.raw.get("candidates") or []
    return {
        str(row["candidate_id"]): row
        for row in rows
        if isinstance(row, dict) and row.get("candidate_id")
    }


def _gate2_economic_checks(
    *,
    spec,
    baseline: dict[int, tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]],
    challenger: dict[int, tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]],
    deterministic_scores: bool,
    deterministic_portfolio: bool,
) -> dict[str, Any]:
    policy = dict(spec.raw.get("gate2_policy") or {})
    base20 = baseline[BASE_COST_BPS][0]
    base60 = baseline[STRESS_COST_BPS][0]
    chal20 = challenger[BASE_COST_BPS][0]
    chal60 = challenger[STRESS_COST_BPS][0]
    drawdown_delta = float(chal20["max_drawdown"]) - float(base20["max_drawdown"])
    checks = {
        "beats_baseline_20bps": float(chal20["relative_excess"])
        > float(base20["relative_excess"]),
        "beats_baseline_60bps": float(chal60["relative_excess"])
        > float(base60["relative_excess"]),
        "positive_window_count": int(chal20["positive_excess_windows"])
        >= int(policy["minimum_positive_selection_windows"]),
        "drawdown_worsening_within_limit": drawdown_delta
        >= -float(policy["maximum_drawdown_worsening_vs_baseline"]),
        "exact_score_reproduction": bool(deterministic_scores),
        "exact_portfolio_reproduction": bool(deterministic_portfolio),
    }
    return {
        "checks": checks,
        "economic_pass": all(checks.values()),
        "metrics": {
            "relative_excess_20bps": float(chal20["relative_excess"]),
            "baseline_relative_excess_20bps": float(base20["relative_excess"]),
            "improvement_vs_baseline_20bps": float(chal20["relative_excess"])
            - float(base20["relative_excess"]),
            "relative_excess_60bps": float(chal60["relative_excess"]),
            "baseline_relative_excess_60bps": float(base60["relative_excess"]),
            "improvement_vs_baseline_60bps": float(chal60["relative_excess"])
            - float(base60["relative_excess"]),
            "max_drawdown_20bps": float(chal20["max_drawdown"]),
            "baseline_max_drawdown_20bps": float(base20["max_drawdown"]),
            "drawdown_delta": drawdown_delta,
            "positive_window_count": int(chal20["positive_excess_windows"]),
            "turnover_20bps": float(chal20["turnover"]),
            "baseline_turnover_20bps": float(base20["turnover"]),
            "risk_on_active_hit_rate": float(chal20["risk_on_active_hit_rate"]),
        },
    }


def run_cn_x1_2_feature_ablation(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen CN x1.2 Phase-2 factor matrix through exact economics."""

    spec = load_cross_sectional_experiment_spec(spec_path)
    if spec.market != "cn" or str(spec.raw.get("phase2_runner") or "") != RUNNER_ID:
        raise ValueError("spec is not an Issue #966 CN x1.2 Phase-2 ablation")
    if spec.raw.get("research_only") is not True or spec.raw.get("trade_ready") is not False:
        raise ValueError("Phase-2 ablation must remain research_only=true, trade_ready=false")
    if tuple(spec.contract.selection_windows) != DEVELOPMENT_WINDOWS:
        raise ValueError("Phase-2 CN selection windows must equal current x1.2 development windows")
    if spec.contract.cutoff != DEVELOPMENT_HARD_STOP.strftime("%Y-%m-%d"):
        raise ValueError("Phase-2 CN cutoff must remain 2026-06-30")
    if pd.Timestamp(spec.parent.walk_forward["test_end"]) >= RESERVED_HOLDOUT_START:
        raise ValueError("Phase-2 CN paradigm crosses the reserved 2026H2 holdout")
    if spec.contract.base_cost_bps != BASE_COST_BPS or spec.contract.stress_cost_bps != STRESS_COST_BPS:
        raise ValueError("Phase-2 CN ablation requires frozen 20/60 bps costs")
    _candidate_policy_map(spec)

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "phase2"
    )
    output.mkdir(parents=True, exist_ok=True)

    runtime = _runtime_for_market("cn")
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    if observed_provider != spec.contract.provider_identity_sha256:
        blocked = {
            "schema_version": "1.0",
            "experiment_id": spec.experiment_id,
            "runner": RUNNER_ID,
            "status": "data_blocked",
            "decision": "provider_identity_mismatch",
            "expected_provider_identity_sha256": spec.contract.provider_identity_sha256,
            "observed_provider_identity_sha256": observed_provider,
            "research_only": True,
            "trade_ready": False,
        }
        _write_json(output / "phase2_receipt.json", blocked)
        return blocked

    symbols = [str(value).zfill(6) for value in _resolve_symbols(spec, runtime)]
    if len(symbols) != POOL_SIZE or len(set(symbols)) != POOL_SIZE:
        raise ValueError("Phase-2 CN runtime universe must be exact CN130")
    benchmark_symbol = str(_benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark_symbol != BENCHMARK:
        raise ValueError(f"Phase-2 CN benchmark drifted: {benchmark_symbol}")

    classification, classification_identity = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise ValueError("CN130 runtime universe differs from governed classification")

    provider_dir = PROJECT_ROOT / "data" / "providers" / "cn"
    panel = load_provider_panel(provider_dir, [*symbols, BENCHMARK], fields=("close",))
    close = panel.fields["close"].loc[panel.fields["close"].index <= DEVELOPMENT_HARD_STOP]
    _assert_no_2026h2(close.index, label="Phase-2 close panel")
    gate = RegimeGateSpec(cost_bps=BASE_COST_BPS)
    state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=BENCHMARK,
        long_ma_sessions=gate.long_ma_sessions,
        momentum_sessions=gate.momentum_sessions,
        breadth_ma_sessions=gate.breadth_ma_sessions,
        breadth_threshold=gate.breadth_threshold,
    )
    benchmark_execution = forward_returns(
        close[[BENCHMARK]],
        horizon=gate.horizon_sessions,
        delay=gate.execution_delay_sessions,
    )[BENCHMARK]

    windows, evaluation_dates = _development_windows(spec, runtime)
    factor_contracts = candidate_factor_contracts(spec)
    expressions_by_candidate = {
        candidate_id: tuple(contract["expressions"])
        for candidate_id, contract in factor_contracts.items()
    }
    union_expressions = list(
        dict.fromkeys(
            expression
            for expressions in expressions_by_candidate.values()
            for expression in expressions
        )
    )
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(union_expressions)
    }

    ledgers: dict[str, list[pd.DataFrame]] = {
        candidate.candidate_id: [] for candidate in spec.candidates
    }
    score_hashes: dict[str, dict[str, str]] = {
        candidate.candidate_id: {} for candidate in spec.candidates
    }
    diagnostics: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}

    execution_wide = forward_returns(
        close.loc[:, symbols],
        horizon=gate.horizon_sessions,
        delay=gate.execution_delay_sessions,
    )
    execution_all = normalize_qlib_frame_index(
        stack_return_frame(execution_wide, name="execution_forward_return")
    )

    for window in windows:
        dates = evaluation_dates[window.label]
        _assert_no_2026h2(dates, label=f"Phase-2 evaluation dates {window.label}")
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, union_expressions, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in union_expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {"provenance": "raw_forward_return", "horizon": 10, "expression": RETURN_EXPRESSION}
        )
        execution_test = execution_all.loc[
            execution_all.index.get_level_values("datetime").isin(dates)
        ].copy()
        rebalance_dates = economic_rebalance_dates(dates, gate.rebalance_sessions)
        validate_execution_economic_rebalance_dates(execution_test, rebalance_dates, window.label)
        validate_benchmark_execution_economic_rebalance_dates(
            benchmark_execution, rebalance_dates, window.label
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
        benchmark_raw = _load_benchmark_returns(
            runtime,
            benchmark_instrument=BENCHMARK,
            return_expression=RETURN_EXPRESSION,
            evaluation_dates=dates,
            start=window.test_start,
            end=window.test_end,
            provenance="raw_forward_return",
            horizon=10,
        )
        cache[window.label] = {
            "features_train": features_train,
            "returns_train": returns_train,
            "features_test": features_test,
            "execution_test": execution_test,
        }

        for candidate in spec.candidates:
            candidate_id = candidate.candidate_id
            scores = fit_predict_ranker_scores(
                expressions=expressions_by_candidate[candidate_id],
                expression_columns=expression_columns,
                features_train=features_train,
                returns_train=returns_train,
                features_test=features_test,
                calibration=candidate.calibration,
                context=f"CN Issue966 Phase2 train/{window.label}/{candidate_id}",
            )
            score_hashes[candidate_id][window.label] = _score_hash(scores)
            diagnostic = evaluate_candidate(
                scores,
                returns_test,
                candidate_kind=CandidateKind.XGB_RANK_NDCG,
                orientation=ScoreOrientation.ORIGINAL,
                benchmark_returns=benchmark_raw,
                topk=15,
                rebalance_days=10,
                cost_bps=BASE_COST_BPS,
            ).to_dict()
            diagnostics.append(
                {
                    "candidate_id": candidate_id,
                    "window": window.label,
                    "ic": float(diagnostic["ic"]),
                    "rank_ic": float(diagnostic["rank_ic"]),
                    "icir": float(diagnostic["icir"]),
                    "positive_ic_ratio": float(diagnostic["positive_ic_ratio"]),
                    "top_minus_bottom_spread": float(
                        diagnostic["score_direction"]["top_minus_bottom_spread"]
                    ),
                }
            )
            ledgers[candidate_id].append(
                _ledger(scores, execution_test, classification, window.label)
            )

    results: dict[
        str,
        dict[int, tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]],
    ] = {}
    for candidate in spec.candidates:
        candidate_id = candidate.candidate_id
        ledger = pd.concat(ledgers[candidate_id], ignore_index=True)
        results[candidate_id] = {}
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            results[candidate_id][cost_bps] = run_regime_portfolio(
                ledger,
                benchmark_execution,
                state,
                windows=DEVELOPMENT_WINDOWS,
                variant=gate.variant(),
                rule=RULE,
                exposure_policy=EXPOSURE_POLICY,
                breadth_threshold=gate.breadth_threshold,
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
                validate_holdings=True,
            )

    score_reproduction: dict[str, dict[str, dict[str, str]]] = {}
    portfolio_reproduction: dict[str, dict[str, dict[str, str]]] = {}
    deterministic_by_candidate: dict[str, dict[str, bool]] = {}
    for candidate in spec.candidates:
        candidate_id = candidate.candidate_id
        replay_ledgers: list[pd.DataFrame] = []
        score_reproduction[candidate_id] = {}
        score_ok = True
        for window in windows:
            cached = cache[window.label]
            replay_scores = fit_predict_ranker_scores(
                expressions=expressions_by_candidate[candidate_id],
                expression_columns=expression_columns,
                features_train=cached["features_train"],
                returns_train=cached["returns_train"],
                features_test=cached["features_test"],
                calibration=candidate.calibration,
                context=f"CN Issue966 Phase2 train/{window.label}/{candidate_id}",
            )
            second_hash = _score_hash(replay_scores)
            first_hash = score_hashes[candidate_id][window.label]
            score_reproduction[candidate_id][window.label] = {
                "first": first_hash,
                "second": second_hash,
            }
            score_ok = score_ok and first_hash == second_hash
            replay_ledgers.append(
                _ledger(replay_scores, cached["execution_test"], classification, window.label)
            )

        replay_ledger = pd.concat(replay_ledgers, ignore_index=True)
        portfolio_reproduction[candidate_id] = {}
        portfolio_ok = True
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            _, first_periods, first_holdings, _ = results[candidate_id][cost_bps]
            _, second_periods, second_holdings, _ = run_regime_portfolio(
                replay_ledger,
                benchmark_execution,
                state,
                windows=DEVELOPMENT_WINDOWS,
                variant=gate.variant(),
                rule=RULE,
                exposure_policy=EXPOSURE_POLICY,
                breadth_threshold=gate.breadth_threshold,
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
                validate_holdings=True,
            )
            first_period_hash = _frame_hash(first_periods, ["window", "datetime"])
            second_period_hash = _frame_hash(second_periods, ["window", "datetime"])
            first_holdings_hash = _frame_hash(
                first_holdings, ["window", "datetime", "instrument"]
            )
            second_holdings_hash = _frame_hash(
                second_holdings, ["window", "datetime", "instrument"]
            )
            portfolio_reproduction[candidate_id][str(cost_bps)] = {
                "first_periods": first_period_hash,
                "second_periods": second_period_hash,
                "first_holdings": first_holdings_hash,
                "second_holdings": second_holdings_hash,
            }
            portfolio_ok = portfolio_ok and (
                first_period_hash == second_period_hash
                and first_holdings_hash == second_holdings_hash
            )
        deterministic_by_candidate[candidate_id] = {
            "scores": score_ok,
            "portfolio": portfolio_ok,
        }

    baseline_id = spec.contract.baseline_candidate_id
    if baseline_id not in results:
        raise ValueError("Phase-2 baseline candidate is missing")
    raw_candidates = _candidate_rows(spec)
    baseline_factor_ids = set(factor_contracts[baseline_id]["factor_ids"])
    candidates: list[dict[str, Any]] = []
    gate2: dict[str, Any] = {}
    for candidate in spec.candidates:
        candidate_id = candidate.candidate_id
        contract = factor_contracts[candidate_id]
        row = {
            "candidate_id": candidate_id,
            "role": candidate.role,
            "factor_ids": list(contract["factor_ids"]),
            "factor_count": len(contract["factor_ids"]),
            "added_factor_ids": [
                factor_id for factor_id in contract["factor_ids"] if factor_id not in baseline_factor_ids
            ],
            "factor_library_sources": list(contract["library_sources"]),
            "factor_implementation_hashes": dict(contract["implementation_hashes"]),
            "parameter_identity": candidate.calibration.identity_manifest(),
            "diagnostics": _diagnostic_summary(diagnostics, candidate_id),
            "base_20bps": results[candidate_id][BASE_COST_BPS][0],
            "stress_60bps": results[candidate_id][STRESS_COST_BPS][0],
            "determinism": deterministic_by_candidate[candidate_id],
        }
        candidates.append(row)
        if candidate.role == "challenger":
            gate2[candidate_id] = _gate2_economic_checks(
                spec=spec,
                baseline=results[baseline_id],
                challenger=results[candidate_id],
                deterministic_scores=deterministic_by_candidate[candidate_id]["scores"],
                deterministic_portfolio=deterministic_by_candidate[candidate_id]["portfolio"],
            )

    receipt = {
        "schema_version": "1.0",
        "experiment_id": spec.experiment_id,
        "runner": RUNNER_ID,
        "status": "completed",
        "market": "cn",
        "observed_provider_identity_sha256": observed_provider,
        "cutoff": spec.contract.cutoff,
        "selection_windows": list(DEVELOPMENT_WINDOWS),
        "reserved_holdout_start": RESERVED_HOLDOUT_START.strftime("%Y-%m-%d"),
        "portfolio_contract": (spec.raw.get("execution") or {}).get("exact_portfolio"),
        "classification_sha256": classification_identity,
        "resolved_non_incremental_mechanisms": spec.raw.get(
            "resolved_non_incremental_mechanisms"
        ),
        "candidates": candidates,
        "economic_gate2": gate2,
        "score_reproduction": score_reproduction,
        "portfolio_reproduction": portfolio_reproduction,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "phase2_receipt.json", receipt)
    return receipt
