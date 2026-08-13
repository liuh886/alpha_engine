"""Exact CN ranker Stage-B replay under the governed CN x1.1 portfolio path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.factors.model_contract import resolve_canonical_factor_ids
from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn_x1_1_regime_gated import RegimeGateSpec, build_regime_state, run_regime_portfolio
from src.research.cross_sectional_experiment_runner import (
    RETURN_EXPRESSION,
    _benchmark_instrument,
    _resolve_symbols,
    _runtime_for_market,
    load_cross_sectional_experiment_spec,
)
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window

REPLAY_ID = "exact_cn_ranker_portfolio_v1"
EXECUTION_RETURN_EXPRESSION = "Ref($close,-11)/Ref($close,-1)-1"
BENCHMARK = "000300"
BASE_COST_BPS = 20
STRESS_COST_BPS = 60
SELECTION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_clean(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _score_hash(scores: pd.DataFrame | pd.Series) -> str:
    frame = scores.rename("score").to_frame() if isinstance(scores, pd.Series) else scores.copy()
    frame = normalize_qlib_frame_index(frame).sort_index()
    payload = frame.to_csv(index=True, lineterminator="\n", float_format="%.17g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _frame_hash(frame: pd.DataFrame, sort_columns: list[str]) -> str:
    ordered = frame.copy()
    for column in sort_columns:
        if column == "datetime" and column in ordered.columns:
            ordered[column] = pd.to_datetime(ordered[column])
    ordered = ordered.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    payload = ordered.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _portfolio_contract(spec) -> tuple[dict[str, dict[str, str]], str]:
    exact = dict((spec.raw.get("execution") or {}).get("exact_portfolio") or {})
    expected = {
        "replay_id": REPLAY_ID,
        "sector_classification": "configs/research_classifications/cn130_sector_industry_v1.yaml",
        "sectors": 4,
        "names_per_sector": 1,
        "weighting": "equal_weight",
        "holding_sessions": 10,
        "rebalance_sessions": 10,
        "execution_delay_sessions": 1,
        "regime_rule": "two_of_three",
        "regime_long_ma_sessions": 200,
        "regime_momentum_sessions": 60,
        "regime_breadth_ma_sessions": 60,
        "regime_breadth_threshold": 0.50,
        "regime_votes_required": 2,
        "risk_off_fallback": BENCHMARK,
    }
    for key, value in expected.items():
        if exact.get(key) != value:
            raise ValueError(f"exact CN portfolio contract drifted at {key}: {exact.get(key)!r}")

    path = (PROJECT_ROOT / str(exact["sector_classification"])).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(symbols, dict):
        raise ValueError("CN classification must expose a symbols mapping")
    normalized = {str(key).zfill(6): dict(value) for key, value in symbols.items()}
    return normalized, _sha256_file(path)


def _windows(spec, runtime):
    walk = spec.parent.walk_forward
    strategy = spec.parent.strategy
    calendar = runtime.calendar(
        str(walk["requested_train_start"]),
        min(str(walk["test_end"]), spec.contract.cutoff),
    )
    if len(calendar) == 0:
        raise ValueError("provider calendar is empty")
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
        min_partial_window_eligible_sessions=int(walk["min_partial_window_eligible_sessions"]),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    dates = horizon_eligible_dates_by_window(plan, calendar)
    required = set(SELECTION_WINDOWS)
    selected = [window for window in plan.selected_windows if window.label in required]
    missing = sorted(required - {window.label for window in selected})
    if missing:
        raise ValueError(f"CN Stage-B selection windows unavailable: {missing}")
    return selected, dates


def _raw_candidate_map(spec) -> dict[str, dict[str, Any]]:
    rows = spec.raw.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("CN exact replay requires candidate mappings")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CN exact replay candidate entries must be mappings")
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in result:
            raise ValueError(f"invalid or duplicate candidate id: {candidate_id!r}")
        result[candidate_id] = row
    expected = {candidate.candidate_id for candidate in spec.candidates}
    if set(result) != expected:
        raise ValueError("parsed candidate metadata differs from validated experiment candidates")
    return result


def _candidate_factor_contracts(spec) -> dict[str, dict[str, Any]]:
    """Resolve deterministic candidate features across maintained canonical libraries."""

    factor_cfg = spec.raw.get("factor_library") or {}
    primary_source = str(factor_cfg.get("source", "")).strip()
    if not primary_source:
        raise ValueError("exact CN replay requires factor_library.source")
    primary = load_factor_library(spec.factor_library_path)
    raw_candidates = _raw_candidate_map(spec)

    contracts: dict[str, dict[str, Any]] = {}
    for candidate in spec.candidates:
        base_definitions = primary.factors_for_groups(candidate.factor_groups)
        factor_ids = [definition.factor_id for definition in base_definitions]
        library_sources = [primary_source]

        additions = raw_candidates[candidate.candidate_id].get("canonical_factor_additions")
        if additions is not None:
            if not isinstance(additions, dict):
                raise ValueError(
                    f"candidate {candidate.candidate_id} canonical_factor_additions "
                    "must be a mapping"
                )
            raw_sources = additions.get("library_sources")
            raw_ids = additions.get("factor_ids")
            if not isinstance(raw_sources, list) or not raw_sources:
                raise ValueError(
                    f"candidate {candidate.candidate_id} additions require library_sources"
                )
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ValueError(
                    f"candidate {candidate.candidate_id} additions require factor_ids"
                )
            library_sources.extend(str(value).strip() for value in raw_sources)
            factor_ids.extend(str(value).strip() for value in raw_ids)

        definitions = resolve_canonical_factor_ids(
            root=PROJECT_ROOT,
            library_sources=library_sources,
            factor_ids=factor_ids,
        )
        contracts[candidate.candidate_id] = {
            "library_sources": tuple(library_sources),
            "factor_ids": tuple(definition.factor_id for definition in definitions),
            "expressions": tuple(definition.expression for definition in definitions),
            "implementation_hashes": {
                definition.factor_id: definition.implementation_hash
                for definition in definitions
            },
        }
    return contracts


def _ledger(
    scores: pd.DataFrame,
    execution_returns: pd.DataFrame,
    classification: dict[str, dict[str, str]],
    window: str,
) -> pd.DataFrame:
    joined = normalize_qlib_frame_index(scores).join(
        normalize_qlib_frame_index(execution_returns), how="left"
    )
    joined = joined.rename(columns={execution_returns.columns[0]: "execution_forward_return"})
    frame = joined.reset_index()
    frame["instrument"] = frame["instrument"].astype(str).str.zfill(6)
    missing = sorted(set(frame["instrument"]) - set(classification))
    if missing:
        raise ValueError(f"classification missing CN symbols: {missing}")
    frame["entity"] = frame["instrument"].map(
        lambda symbol: str(classification[symbol].get("entity", symbol))
    )
    frame["sector"] = frame["instrument"].map(
        lambda symbol: str(classification[symbol]["sector"])
    )
    frame["industry"] = frame["instrument"].map(
        lambda symbol: str(classification[symbol].get("industry", ""))
    )
    frame["window"] = window
    return frame[
        [
            "window",
            "datetime",
            "instrument",
            "entity",
            "sector",
            "industry",
            "score",
            "execution_forward_return",
        ]
    ].sort_values(["datetime", "score", "instrument"], ascending=[True, False, True])


def _candidate_summary(
    candidate_id: str,
    factor_groups: tuple[str, ...],
    factor_contract: dict[str, Any],
    parameter_identity: dict[str, object],
    diagnostic_rows: list[dict[str, Any]],
    base: dict[str, Any],
    stress: dict[str, Any],
) -> dict[str, Any]:
    rank_ic = [
        float(row["rank_ic"])
        for row in diagnostic_rows
        if row["candidate_id"] == candidate_id
    ]
    icir = [
        float(row["icir"])
        for row in diagnostic_rows
        if row["candidate_id"] == candidate_id
    ]
    return {
        "candidate_id": candidate_id,
        "factor_groups": list(factor_groups),
        "factor_library_sources": list(factor_contract["library_sources"]),
        "factor_ids": list(factor_contract["factor_ids"]),
        "factor_implementation_hashes": dict(factor_contract["implementation_hashes"]),
        "factor_count": len(factor_contract["factor_ids"]),
        "parameter_identity": parameter_identity,
        "mean_rank_ic": float(np.mean(rank_ic)) if rank_ic else 0.0,
        "mean_icir": float(np.mean(icir)) if icir else 0.0,
        "base_20bps": base,
        "stress_60bps": stress,
    }


def run_exact_cn_ranker_portfolio_replay(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    if spec.market != "cn" or str(spec.raw.get("online_validation") or "") != REPLAY_ID:
        raise ValueError("spec is not opted into exact CN online replay")
    if (
        spec.contract.base_cost_bps != BASE_COST_BPS
        or spec.contract.stress_cost_bps != STRESS_COST_BPS
    ):
        raise ValueError("exact CN replay requires 20/60 bps")
    if tuple(spec.contract.selection_windows) != SELECTION_WINDOWS:
        raise ValueError("exact CN replay requires the four frozen selection windows")

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT
        / "artifacts"
        / "research_experiments"
        / spec.experiment_id
        / "stage_b"
    )
    output.mkdir(parents=True, exist_ok=True)

    runtime = _runtime_for_market("cn")
    runtime.initialize(PROJECT_ROOT)
    observed_provider = str(runtime.metadata().get("provider_identity_sha256") or "")
    expected_provider = spec.contract.provider_identity_sha256
    if observed_provider != expected_provider:
        blocked = {
            "schema_version": "1.0",
            "experiment_id": spec.experiment_id,
            "runner": REPLAY_ID,
            "status": "data_blocked",
            "decision": "provider_identity_mismatch",
            "expected_provider_identity_sha256": expected_provider,
            "observed_provider_identity_sha256": observed_provider,
            "research_only": True,
            "trade_ready": False,
        }
        _write_json(output / "stage_b_receipt.json", blocked)
        return blocked

    symbols = [str(value).zfill(6) for value in _resolve_symbols(spec, runtime)]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise ValueError("CN Stage-B runtime universe must be exact CN130")
    benchmark_symbol = str(_benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark_symbol != BENCHMARK:
        raise ValueError(f"CN Stage-B benchmark drifted: {benchmark_symbol}")

    classification, classification_identity = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise ValueError("CN130 runtime universe differs from governed classification")

    provider_dir = PROJECT_ROOT / "data" / "providers" / "cn"
    panel = load_provider_panel(provider_dir, [*symbols, BENCHMARK], fields=("close",))
    gate = RegimeGateSpec(cost_bps=BASE_COST_BPS)
    state = build_regime_state(
        panel.fields["close"],
        symbols=symbols,
        benchmark=BENCHMARK,
        long_ma_sessions=gate.long_ma_sessions,
        momentum_sessions=gate.momentum_sessions,
        breadth_ma_sessions=gate.breadth_ma_sessions,
        breadth_threshold=gate.breadth_threshold,
    )
    benchmark_execution = forward_returns(
        panel.fields["close"][[BENCHMARK]],
        horizon=gate.horizon_sessions,
        delay=gate.execution_delay_sessions,
    )[BENCHMARK]

    windows, evaluation_dates = _windows(spec, runtime)
    factor_contracts = _candidate_factor_contracts(spec)
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
        expression: f"feature_{index}"
        for index, expression in enumerate(union_expressions)
    }

    ledgers: dict[str, list[pd.DataFrame]] = {
        candidate.candidate_id: [] for candidate in spec.candidates
    }
    score_hashes: dict[str, dict[str, str]] = {
        candidate.candidate_id: {} for candidate in spec.candidates
    }
    diagnostics: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}

    for window in windows:
        dates = evaluation_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                union_expressions,
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in union_expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                [RETURN_EXPRESSION],
                window.train_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        returns_all.columns = ["return"]
        returns_all.attrs.update(
            {
                "provenance": "raw_forward_return",
                "horizon": 10,
                "expression": RETURN_EXPRESSION,
            }
        )
        execution_all = normalize_qlib_frame_index(
            runtime.features(
                symbols,
                [EXECUTION_RETURN_EXPRESSION],
                window.test_start,
                window.test_end,
            )
        ).replace([np.inf, -np.inf], np.nan)
        execution_all.columns = ["execution_forward_return"]

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
        execution_dates = execution_all.index.get_level_values("datetime")
        execution_test = execution_all.loc[execution_dates.isin(dates)].copy()
        benchmark_raw = load_window_benchmark_returns(
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
                context=f"CN exact replay train/{window.label}/{candidate_id}",
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
                    "rank_ic": float(diagnostic["rank_ic"]),
                    "icir": float(diagnostic["icir"]),
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
                windows=SELECTION_WINDOWS,
                variant=gate.variant(),
                rule="two_of_three",
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
            )

    baseline_id = spec.contract.baseline_candidate_id
    challenger_ids = [
        candidate.candidate_id
        for candidate in spec.candidates
        if candidate.candidate_id != baseline_id
    ]
    if len(challenger_ids) != 1:
        raise ValueError(
            f"CN Stage-B requires exactly one declared challenger; got {challenger_ids}"
        )
    challenger_id = challenger_ids[0]

    candidate_rows: list[dict[str, Any]] = []
    for candidate in spec.candidates:
        base = results[candidate.candidate_id][BASE_COST_BPS][0]
        stress = results[candidate.candidate_id][STRESS_COST_BPS][0]
        candidate_rows.append(
            _candidate_summary(
                candidate.candidate_id,
                candidate.factor_groups,
                factor_contracts[candidate.candidate_id],
                candidate.calibration.identity_manifest(),
                diagnostics,
                base,
                stress,
            )
        )

    baseline_base = results[baseline_id][BASE_COST_BPS][0]
    baseline_stress = results[baseline_id][STRESS_COST_BPS][0]
    challenger_base = results[challenger_id][BASE_COST_BPS][0]
    challenger_stress = results[challenger_id][STRESS_COST_BPS][0]
    drawdown_delta = float(
        challenger_base["max_drawdown"] - baseline_base["max_drawdown"]
    )

    second_ledgers: list[pd.DataFrame] = []
    reproduction: dict[str, dict[str, str]] = {}
    challenger = next(
        item for item in spec.candidates if item.candidate_id == challenger_id
    )
    deterministic_scores = True
    for window in windows:
        cached = cache[window.label]
        replay_scores = fit_predict_ranker_scores(
            expressions=expressions_by_candidate[challenger_id],
            expression_columns=expression_columns,
            features_train=cached["features_train"],
            returns_train=cached["returns_train"],
            features_test=cached["features_test"],
            calibration=challenger.calibration,
            context=f"CN exact replay train/{window.label}/{challenger_id}",
        )
        second_hash = _score_hash(replay_scores)
        first_hash = score_hashes[challenger_id][window.label]
        reproduction[window.label] = {
            "first": first_hash,
            "second": second_hash,
        }
        deterministic_scores = deterministic_scores and first_hash == second_hash
        second_ledgers.append(
            _ledger(
                replay_scores,
                cached["execution_test"],
                classification,
                window.label,
            )
        )

    replay_ledger = pd.concat(second_ledgers, ignore_index=True)
    portfolio_reproduction: dict[str, dict[str, str]] = {}
    deterministic_portfolio = True
    for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
        _, first_periods, first_holdings, _ = results[challenger_id][cost_bps]
        _, second_periods, second_holdings, _ = run_regime_portfolio(
            replay_ledger,
            benchmark_execution,
            state,
            windows=SELECTION_WINDOWS,
            variant=gate.variant(),
            rule="two_of_three",
            rebalance_sessions=gate.rebalance_sessions,
            cost_bps=cost_bps,
        )
        first_period_hash = _frame_hash(first_periods, ["window", "datetime"])
        second_period_hash = _frame_hash(second_periods, ["window", "datetime"])
        first_holdings_hash = _frame_hash(
            first_holdings,
            ["window", "datetime", "instrument"],
        )
        second_holdings_hash = _frame_hash(
            second_holdings,
            ["window", "datetime", "instrument"],
        )
        portfolio_reproduction[str(cost_bps)] = {
            "first_periods": first_period_hash,
            "second_periods": second_period_hash,
            "first_holdings": first_holdings_hash,
            "second_holdings": second_holdings_hash,
        }
        deterministic_portfolio = deterministic_portfolio and (
            first_period_hash == second_period_hash
            and first_holdings_hash == second_holdings_hash
        )

    positive_windows = int(challenger_base["positive_excess_windows"])
    risk_off_cost_gate = bool(
        float(challenger_base["risk_off_relative_excess"])
        >= -float(challenger_base["risk_off_total_cost"]) - 0.001
    )
    checks = {
        "beats_incumbent_20bps": float(challenger_base["relative_excess"])
        > float(baseline_base["relative_excess"]),
        "beats_incumbent_60bps": float(challenger_stress["relative_excess"])
        > float(baseline_stress["relative_excess"]),
        "stress_relative_excess_positive": float(
            challenger_stress["relative_excess"]
        )
        > 0.0,
        "at_least_three_of_four_positive_windows": positive_windows >= 3,
        "max_drawdown_above_minus_25pct": float(challenger_base["max_drawdown"])
        >= -0.25,
        "drawdown_worsening_within_3pp": drawdown_delta >= -0.03,
        "risk_on_relative_excess_positive": float(
            challenger_base["risk_on_relative_excess"]
        )
        > 0.0,
        "risk_off_relative_no_worse_than_cost_drag": risk_off_cost_gate,
        "exact_score_reproduction": deterministic_scores,
        "exact_portfolio_reproduction": deterministic_portfolio,
    }
    supported = all(checks.values())
    support = {
        "challenger": challenger_id,
        "baseline": baseline_id,
        "improvement_vs_incumbent_20bps": float(
            challenger_base["relative_excess"]
        )
        - float(baseline_base["relative_excess"]),
        "improvement_vs_incumbent_60bps": float(
            challenger_stress["relative_excess"]
        )
        - float(baseline_stress["relative_excess"]),
        "worst_drawdown_delta_vs_incumbent": drawdown_delta,
        "positive_window_count": positive_windows,
        "checks": checks,
        "supported": supported,
    }

    receipt = {
        "schema_version": "1.1",
        "experiment_id": spec.experiment_id,
        "runner": REPLAY_ID,
        "status": "completed",
        "decision": (
            f"{challenger_id}_full_path_supported"
            if supported
            else f"{challenger_id}_full_path_rejected"
        ),
        "observed_provider_identity_sha256": observed_provider,
        "sector_classification_sha256": classification_identity,
        "selection_windows": list(SELECTION_WINDOWS),
        "portfolio_contract": (spec.raw.get("execution") or {}).get(
            "exact_portfolio"
        ),
        "candidates": candidate_rows,
        "support_boundary": support,
        "score_reproduction": reproduction,
        "portfolio_reproduction": portfolio_reproduction,
        "stage_b_supported": supported,
        "new_holdout_consumed": False,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "stage_b_receipt.json", receipt)
    return receipt
