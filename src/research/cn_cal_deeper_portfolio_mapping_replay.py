"""Test cal_deeper portfolio mappings under the frozen CN regime gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn130_tail_factor_discovery import PortfolioVariant
from src.research.cn_ranker_exact_portfolio_replay import (
    BASE_COST_BPS,
    BENCHMARK,
    EXECUTION_RETURN_EXPRESSION,
    REPLAY_ID,
    SELECTION_WINDOWS,
    STRESS_COST_BPS,
    _frame_hash,
    _ledger,
    _portfolio_contract,
    _score_hash,
    _windows,
    _write_json,
    _fit_scores,
)
from src.research.cn_x1_1_regime_gated import RegimeGateSpec, build_regime_state, run_regime_portfolio
from src.research.cross_sectional_experiment_runner import (
    RETURN_EXPRESSION,
    _benchmark_instrument,
    _factor_expressions,
    _resolve_symbols,
    _runtime_for_market,
    load_cross_sectional_experiment_spec,
)
from src.research.qlib_execution_common import load_window_benchmark_returns, normalize_qlib_frame_index
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate

MAPPING_REPLAY_ID = "cn_cal_deeper_portfolio_mapping_v1"
CHALLENGER_ID = "cal_deeper"
VARIANTS: tuple[PortfolioVariant, ...] = (
    PortfolioVariant("sector_4x1", "sector_hierarchical", sectors=4, names_per_sector=1),
    PortfolioVariant("global_top15", "global", top_k=15),
    PortfolioVariant(
        "global_top15_sector_cap4",
        "global_sector_cap",
        top_k=15,
        sector_cap=4,
    ),
)


def _mapping_contract(spec) -> None:
    raw = spec.raw.get("portfolio_mapping_diagnostic")
    if not isinstance(raw, dict):
        raise ValueError("portfolio_mapping_diagnostic mapping is required")
    expected = {
        "experiment_id": MAPPING_REPLAY_ID,
        "candidate_id": CHALLENGER_ID,
        "keep_regime_gate": True,
        "variants": [variant.variant_id for variant in VARIANTS],
        "new_holdout_consumed": False,
    }
    for key, value in expected.items():
        if raw.get(key) != value:
            raise ValueError(f"portfolio mapping contract drifted at {key}: {raw.get(key)!r}")


def _holding_contract(variant: PortfolioVariant, holdings: pd.DataFrame) -> bool:
    active = holdings.loc[holdings["instrument"] != BENCHMARK].copy()
    if active.empty:
        return False
    counts = active.groupby(["window", "datetime"]).size()
    if variant.variant_id == "sector_4x1":
        return bool(counts.eq(4).all())
    if not counts.eq(15).all():
        return False
    if variant.variant_id == "global_top15_sector_cap4":
        sector_counts = active.groupby(["window", "datetime", "sector"]).size()
        return bool((sector_counts <= 4).all())
    return True


def _summary_row(
    variant: PortfolioVariant,
    base: dict[str, Any],
    stress: dict[str, Any],
    control_base: dict[str, Any],
    control_stress: dict[str, Any],
    deterministic: bool,
    holding_contract: bool,
) -> dict[str, Any]:
    checks = {
        "positive_relative_excess_20bps": float(base["relative_excess"]) > 0.0,
        "positive_relative_excess_60bps": float(stress["relative_excess"]) > 0.0,
        "beats_4x1_20bps": float(base["relative_excess"]) > float(control_base["relative_excess"]),
        "beats_4x1_60bps": float(stress["relative_excess"])
        > float(control_stress["relative_excess"]),
        "at_least_three_of_four_positive_windows": int(base["positive_excess_windows"]) >= 3,
        "max_drawdown_above_minus_25pct": float(base["max_drawdown"]) >= -0.25,
        "risk_on_relative_excess_positive": float(base["risk_on_relative_excess"]) > 0.0,
        "exact_portfolio_reproduction": deterministic,
        "holding_contract": holding_contract,
    }
    broad = variant.variant_id != "sector_4x1"
    return {
        "variant_id": variant.variant_id,
        "selector": variant.selector,
        "top_k": variant.top_k,
        "sector_cap": variant.sector_cap,
        "base_20bps": base,
        "stress_60bps": stress,
        "improvement_vs_4x1_20bps": float(base["relative_excess"])
        - float(control_base["relative_excess"]),
        "improvement_vs_4x1_60bps": float(stress["relative_excess"])
        - float(control_stress["relative_excess"]),
        "checks": checks,
        "broad_mapping_supported": broad and all(checks.values()),
    }


def run_cal_deeper_portfolio_mapping_replay(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    if spec.market != "cn" or str(spec.raw.get("online_validation") or "") != REPLAY_ID:
        raise ValueError("mapping replay requires exact CN online validation")
    if spec.contract.base_cost_bps != BASE_COST_BPS or spec.contract.stress_cost_bps != STRESS_COST_BPS:
        raise ValueError("mapping replay requires 20/60 bps")
    if tuple(spec.contract.selection_windows) != SELECTION_WINDOWS:
        raise ValueError("mapping replay requires the four frozen selection windows")
    _mapping_contract(spec)

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "mapping"
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
            "runner": MAPPING_REPLAY_ID,
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
        raise ValueError("mapping replay runtime universe must be exact CN130")
    benchmark_symbol = str(_benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark_symbol != BENCHMARK:
        raise ValueError(f"mapping replay benchmark drifted: {benchmark_symbol}")

    classification, classification_identity = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise ValueError("CN130 runtime universe differs from governed classification")

    candidate = next(
        (item for item in spec.candidates if item.candidate_id == CHALLENGER_ID),
        None,
    )
    if candidate is None:
        raise ValueError("mapping replay requires frozen cal_deeper candidate")

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
    expressions = _factor_expressions(spec)[CHALLENGER_ID]
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(expressions)
    }

    ledgers: list[pd.DataFrame] = []
    score_hashes: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}

    for window in windows:
        dates = evaluation_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, list(expressions), window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in expressions]
        returns_all = normalize_qlib_frame_index(
            runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
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

        scores = _fit_scores(
            candidate,
            expressions,
            expression_columns,
            features_train,
            returns_train,
            features_test,
            window.label,
        )
        score_hashes[window.label] = _score_hash(scores)
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
                "window": window.label,
                "rank_ic": float(diagnostic["rank_ic"]),
                "icir": float(diagnostic["icir"]),
            }
        )
        ledgers.append(_ledger(scores, execution_test, classification, window.label))

    ledger = pd.concat(ledgers, ignore_index=True)
    results: dict[str, dict[int, tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]]] = {}
    for variant in VARIANTS:
        results[variant.variant_id] = {}
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            results[variant.variant_id][cost_bps] = run_regime_portfolio(
                ledger,
                benchmark_execution,
                state,
                windows=SELECTION_WINDOWS,
                variant=variant,
                rule="two_of_three",
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
            )

    second_ledgers: list[pd.DataFrame] = []
    score_reproduction: dict[str, dict[str, str]] = {}
    deterministic_scores = True
    for window in windows:
        cached = cache[window.label]
        scores = _fit_scores(
            candidate,
            expressions,
            expression_columns,
            cached["features_train"],
            cached["returns_train"],
            cached["features_test"],
            window.label,
        )
        first_hash = score_hashes[window.label]
        second_hash = _score_hash(scores)
        score_reproduction[window.label] = {"first": first_hash, "second": second_hash}
        deterministic_scores = deterministic_scores and first_hash == second_hash
        second_ledgers.append(
            _ledger(scores, cached["execution_test"], classification, window.label)
        )
    replay_ledger = pd.concat(second_ledgers, ignore_index=True)

    portfolio_reproduction: dict[str, dict[str, dict[str, str]]] = {}
    deterministic_by_variant: dict[str, bool] = {}
    for variant in VARIANTS:
        variant_reproduction: dict[str, dict[str, str]] = {}
        deterministic = True
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            _, first_periods, first_holdings, _ = results[variant.variant_id][cost_bps]
            _, second_periods, second_holdings, _ = run_regime_portfolio(
                replay_ledger,
                benchmark_execution,
                state,
                windows=SELECTION_WINDOWS,
                variant=variant,
                rule="two_of_three",
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
            )
            first_periods_hash = _frame_hash(first_periods, ["window", "datetime"])
            second_periods_hash = _frame_hash(second_periods, ["window", "datetime"])
            first_holdings_hash = _frame_hash(
                first_holdings,
                ["window", "datetime", "instrument"],
            )
            second_holdings_hash = _frame_hash(
                second_holdings,
                ["window", "datetime", "instrument"],
            )
            variant_reproduction[str(cost_bps)] = {
                "first_periods": first_periods_hash,
                "second_periods": second_periods_hash,
                "first_holdings": first_holdings_hash,
                "second_holdings": second_holdings_hash,
            }
            deterministic = deterministic and (
                first_periods_hash == second_periods_hash
                and first_holdings_hash == second_holdings_hash
            )
        portfolio_reproduction[variant.variant_id] = variant_reproduction
        deterministic_by_variant[variant.variant_id] = deterministic

    control_base = results["sector_4x1"][BASE_COST_BPS][0]
    control_stress = results["sector_4x1"][STRESS_COST_BPS][0]
    variant_rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        base = results[variant.variant_id][BASE_COST_BPS][0]
        stress = results[variant.variant_id][STRESS_COST_BPS][0]
        holding_contract = _holding_contract(
            variant,
            results[variant.variant_id][BASE_COST_BPS][2],
        )
        variant_rows.append(
            _summary_row(
                variant,
                base,
                stress,
                control_base,
                control_stress,
                deterministic_scores and deterministic_by_variant[variant.variant_id],
                holding_contract,
            )
        )

    supported_rows = [row for row in variant_rows if row["broad_mapping_supported"]]
    supported_rows.sort(
        key=lambda row: (
            float(row["base_20bps"]["relative_excess"]),
            float(row["stress_60bps"]["relative_excess"]),
        ),
        reverse=True,
    )
    leader = str(supported_rows[0]["variant_id"]) if supported_rows else None
    mean_rank_ic = float(np.mean([row["rank_ic"] for row in diagnostics]))
    mean_icir = float(np.mean([row["icir"] for row in diagnostics]))

    receipt = {
        "schema_version": "1.0",
        "experiment_id": spec.experiment_id,
        "runner": MAPPING_REPLAY_ID,
        "status": "completed",
        "decision": (
            "cal_deeper_broad_mapping_supported"
            if supported_rows
            else "cal_deeper_broad_mapping_not_supported"
        ),
        "observed_provider_identity_sha256": observed_provider,
        "sector_classification_sha256": classification_identity,
        "selection_windows": list(SELECTION_WINDOWS),
        "candidate_id": CHALLENGER_ID,
        "factor_groups": list(candidate.factor_groups),
        "mean_rank_ic": mean_rank_ic,
        "mean_icir": mean_icir,
        "portfolio_mapping_contract": spec.raw["portfolio_mapping_diagnostic"],
        "variants": variant_rows,
        "supported_variant": leader,
        "score_reproduction": score_reproduction,
        "portfolio_reproduction": portfolio_reproduction,
        "exact_score_reproduction": deterministic_scores,
        "new_holdout_consumed": False,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "stage_b_receipt.json", receipt)
    return receipt
