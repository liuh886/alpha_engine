"""Test one fixed 50/50 baseline + cal_deeper rank blend on the CN portfolio path."""

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
    _fit_scores,
    _frame_hash,
    _ledger,
    _portfolio_contract,
    _score_hash,
    _windows,
    _write_json,
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

BLEND_REPLAY_ID = "cn_rank_blend_50_50_v1"
BASELINE_ID = "baseline_cn_x1_1"
CAL_DEEPER_ID = "cal_deeper"
BLEND_ID = "baseline_cal_deeper_rank_blend_50_50"
SECTOR_4X1 = PortfolioVariant(
    "sector_4x1",
    "sector_hierarchical",
    sectors=4,
    names_per_sector=1,
)
SECTOR_CAP4 = PortfolioVariant(
    "global_top15_sector_cap4",
    "global_sector_cap",
    top_k=15,
    sector_cap=4,
)


def _blend_contract(spec) -> None:
    raw = spec.raw.get("rank_blend_diagnostic")
    if not isinstance(raw, dict):
        raise ValueError("rank_blend_diagnostic mapping is required")
    expected = {
        "experiment_id": BLEND_REPLAY_ID,
        "baseline_candidate_id": BASELINE_ID,
        "secondary_candidate_id": CAL_DEEPER_ID,
        "blend_id": BLEND_ID,
        "rank_method": "average",
        "baseline_weight": 0.5,
        "secondary_weight": 0.5,
        "portfolio_mapping": SECTOR_CAP4.variant_id,
        "new_holdout_consumed": False,
    }
    for key, value in expected.items():
        if raw.get(key) != value:
            raise ValueError(f"rank blend contract drifted at {key}: {raw.get(key)!r}")


def _percentile_rank(scores: pd.DataFrame | pd.Series) -> pd.DataFrame:
    frame = normalize_qlib_frame_index(
        scores.rename("score").to_frame() if isinstance(scores, pd.Series) else scores.copy()
    )
    if len(frame.columns) != 1:
        raise ValueError("rank blend component must expose exactly one score column")
    frame.columns = ["score"]
    ranked = frame["score"].groupby(level="datetime").rank(method="average", pct=True)
    return ranked.rename("score").to_frame().sort_index()


def _blend_scores(baseline: pd.DataFrame, secondary: pd.DataFrame) -> pd.DataFrame:
    left = _percentile_rank(baseline).rename(columns={"score": "baseline_rank_pct"})
    right = _percentile_rank(secondary).rename(columns={"score": "secondary_rank_pct"})
    joined = left.join(right, how="inner", validate="one_to_one")
    if len(joined) != len(left) or len(joined) != len(right):
        raise ValueError("rank blend component coverage differs")
    joined["score"] = 0.5 * joined["baseline_rank_pct"] + 0.5 * joined["secondary_rank_pct"]
    return joined[["score"]].sort_index()


def _holding_contract(variant: PortfolioVariant, holdings: pd.DataFrame) -> bool:
    active = holdings.loc[holdings["instrument"] != BENCHMARK].copy()
    if active.empty:
        return False
    counts = active.groupby(["window", "datetime"]).size()
    expected = 4 if variant.variant_id == "sector_4x1" else 15
    if not counts.eq(expected).all():
        return False
    if variant.variant_id == SECTOR_CAP4.variant_id:
        sector_counts = active.groupby(["window", "datetime", "sector"]).size()
        return bool((sector_counts <= 4).all())
    return True


def _result_row(
    strategy_id: str,
    score_id: str,
    variant: PortfolioVariant,
    base: dict[str, Any],
    stress: dict[str, Any],
    deterministic: bool,
    holding_contract: bool,
) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "score_id": score_id,
        "portfolio_variant": variant.variant_id,
        "base_20bps": base,
        "stress_60bps": stress,
        "exact_portfolio_reproduction": deterministic,
        "holding_contract": holding_contract,
    }


def run_cn_rank_blend_portfolio_replay(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_cross_sectional_experiment_spec(spec_path)
    if spec.market != "cn" or str(spec.raw.get("online_validation") or "") != REPLAY_ID:
        raise ValueError("rank blend replay requires exact CN online validation")
    if spec.contract.base_cost_bps != BASE_COST_BPS or spec.contract.stress_cost_bps != STRESS_COST_BPS:
        raise ValueError("rank blend replay requires 20/60 bps")
    if tuple(spec.contract.selection_windows) != SELECTION_WINDOWS:
        raise ValueError("rank blend replay requires the four frozen selection windows")
    _blend_contract(spec)

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "blend"
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
            "runner": BLEND_REPLAY_ID,
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
        raise ValueError("rank blend runtime universe must be exact CN130")
    benchmark_symbol = str(_benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark_symbol != BENCHMARK:
        raise ValueError(f"rank blend benchmark drifted: {benchmark_symbol}")

    classification, classification_identity = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise ValueError("CN130 runtime universe differs from governed classification")

    candidates = {item.candidate_id: item for item in spec.candidates}
    if set(candidates) != {BASELINE_ID, CAL_DEEPER_ID}:
        raise ValueError(f"rank blend must freeze baseline + cal_deeper; got {sorted(candidates)}")

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
    expressions_by_candidate = _factor_expressions(spec)
    union_expressions = list(
        dict.fromkeys(
            expression
            for candidate_id in (BASELINE_ID, CAL_DEEPER_ID)
            for expression in expressions_by_candidate[candidate_id]
        )
    )
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(union_expressions)
    }

    ledgers: dict[str, list[pd.DataFrame]] = {
        BASELINE_ID: [],
        CAL_DEEPER_ID: [],
        BLEND_ID: [],
    }
    score_hashes: dict[str, dict[str, str]] = {
        BASELINE_ID: {},
        CAL_DEEPER_ID: {},
        BLEND_ID: {},
    }
    diagnostics: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}

    for window in windows:
        dates = evaluation_dates[window.label]
        features_all = normalize_qlib_frame_index(
            runtime.features(symbols, union_expressions, window.train_start, window.test_end)
        ).replace([np.inf, -np.inf], np.nan)
        features_all.columns = [expression_columns[item] for item in union_expressions]
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

        scores: dict[str, pd.DataFrame] = {}
        for candidate_id in (BASELINE_ID, CAL_DEEPER_ID):
            candidate = candidates[candidate_id]
            scores[candidate_id] = _fit_scores(
                candidate,
                expressions_by_candidate[candidate_id],
                expression_columns,
                features_train,
                returns_train,
                features_test,
                window.label,
            )
        scores[BLEND_ID] = _blend_scores(scores[BASELINE_ID], scores[CAL_DEEPER_ID])

        for score_id, frame in scores.items():
            score_hashes[score_id][window.label] = _score_hash(frame)
            diagnostic = evaluate_candidate(
                frame,
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
                    "score_id": score_id,
                    "window": window.label,
                    "rank_ic": float(diagnostic["rank_ic"]),
                    "icir": float(diagnostic["icir"]),
                }
            )
            ledgers[score_id].append(_ledger(frame, execution_test, classification, window.label))

    full_ledgers = {key: pd.concat(value, ignore_index=True) for key, value in ledgers.items()}
    strategies = {
        "baseline_sector_4x1": (BASELINE_ID, SECTOR_4X1),
        "baseline_sector_cap4": (BASELINE_ID, SECTOR_CAP4),
        "cal_deeper_sector_cap4": (CAL_DEEPER_ID, SECTOR_CAP4),
        "blend_50_50_sector_cap4": (BLEND_ID, SECTOR_CAP4),
    }
    results: dict[str, dict[int, tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]]] = {}
    for strategy_id, (score_id, variant) in strategies.items():
        results[strategy_id] = {}
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            results[strategy_id][cost_bps] = run_regime_portfolio(
                full_ledgers[score_id],
                benchmark_execution,
                state,
                windows=SELECTION_WINDOWS,
                variant=variant,
                rule="two_of_three",
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
            )

    second_ledgers: dict[str, list[pd.DataFrame]] = {
        BASELINE_ID: [],
        CAL_DEEPER_ID: [],
        BLEND_ID: [],
    }
    score_reproduction: dict[str, dict[str, dict[str, str]]] = {
        BASELINE_ID: {},
        CAL_DEEPER_ID: {},
        BLEND_ID: {},
    }
    deterministic_scores = True
    for window in windows:
        cached = cache[window.label]
        replay: dict[str, pd.DataFrame] = {}
        for candidate_id in (BASELINE_ID, CAL_DEEPER_ID):
            candidate = candidates[candidate_id]
            replay[candidate_id] = _fit_scores(
                candidate,
                expressions_by_candidate[candidate_id],
                expression_columns,
                cached["features_train"],
                cached["returns_train"],
                cached["features_test"],
                window.label,
            )
        replay[BLEND_ID] = _blend_scores(replay[BASELINE_ID], replay[CAL_DEEPER_ID])
        for score_id, frame in replay.items():
            first_hash = score_hashes[score_id][window.label]
            second_hash = _score_hash(frame)
            score_reproduction[score_id][window.label] = {
                "first": first_hash,
                "second": second_hash,
            }
            deterministic_scores = deterministic_scores and first_hash == second_hash
            second_ledgers[score_id].append(
                _ledger(frame, cached["execution_test"], classification, window.label)
            )
    replay_ledgers = {
        key: pd.concat(value, ignore_index=True) for key, value in second_ledgers.items()
    }

    portfolio_reproduction: dict[str, dict[str, dict[str, str]]] = {}
    deterministic_by_strategy: dict[str, bool] = {}
    for strategy_id, (score_id, variant) in strategies.items():
        deterministic = True
        by_cost: dict[str, dict[str, str]] = {}
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            _, first_periods, first_holdings, _ = results[strategy_id][cost_bps]
            _, second_periods, second_holdings, _ = run_regime_portfolio(
                replay_ledgers[score_id],
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
            first_holdings_hash = _frame_hash(first_holdings, ["window", "datetime", "instrument"])
            second_holdings_hash = _frame_hash(second_holdings, ["window", "datetime", "instrument"])
            by_cost[str(cost_bps)] = {
                "first_periods": first_periods_hash,
                "second_periods": second_periods_hash,
                "first_holdings": first_holdings_hash,
                "second_holdings": second_holdings_hash,
            }
            deterministic = deterministic and (
                first_periods_hash == second_periods_hash
                and first_holdings_hash == second_holdings_hash
            )
        portfolio_reproduction[strategy_id] = by_cost
        deterministic_by_strategy[strategy_id] = deterministic

    rows: list[dict[str, Any]] = []
    for strategy_id, (score_id, variant) in strategies.items():
        rows.append(
            _result_row(
                strategy_id,
                score_id,
                variant,
                results[strategy_id][BASE_COST_BPS][0],
                results[strategy_id][STRESS_COST_BPS][0],
                deterministic_scores and deterministic_by_strategy[strategy_id],
                _holding_contract(variant, results[strategy_id][BASE_COST_BPS][2]),
            )
        )
    by_id = {row["strategy_id"]: row for row in rows}
    blend = by_id["blend_50_50_sector_cap4"]
    baseline_4x1 = by_id["baseline_sector_4x1"]
    baseline_cap = by_id["baseline_sector_cap4"]
    cal_cap = by_id["cal_deeper_sector_cap4"]
    blend_base = blend["base_20bps"]
    blend_stress = blend["stress_60bps"]

    checks = {
        "positive_relative_excess_20bps": float(blend_base["relative_excess"]) > 0.0,
        "positive_relative_excess_60bps": float(blend_stress["relative_excess"]) > 0.0,
        "beats_baseline_sector_cap4_20bps": float(blend_base["relative_excess"])
        > float(baseline_cap["base_20bps"]["relative_excess"]),
        "beats_baseline_sector_cap4_60bps": float(blend_stress["relative_excess"])
        > float(baseline_cap["stress_60bps"]["relative_excess"]),
        "beats_cal_deeper_sector_cap4_20bps": float(blend_base["relative_excess"])
        > float(cal_cap["base_20bps"]["relative_excess"]),
        "beats_cal_deeper_sector_cap4_60bps": float(blend_stress["relative_excess"])
        > float(cal_cap["stress_60bps"]["relative_excess"]),
        "beats_governed_baseline_4x1_20bps": float(blend_base["relative_excess"])
        > float(baseline_4x1["base_20bps"]["relative_excess"]),
        "beats_governed_baseline_4x1_60bps": float(blend_stress["relative_excess"])
        > float(baseline_4x1["stress_60bps"]["relative_excess"]),
        "at_least_three_of_four_positive_windows": int(blend_base["positive_excess_windows"]) >= 3,
        "max_drawdown_above_minus_25pct": float(blend_base["max_drawdown"]) >= -0.25,
        "risk_on_relative_excess_positive": float(blend_base["risk_on_relative_excess"]) > 0.0,
        "exact_score_reproduction": deterministic_scores,
        "exact_portfolio_reproduction": deterministic_by_strategy["blend_50_50_sector_cap4"],
        "holding_contract": bool(blend["holding_contract"]),
    }
    supported = all(checks.values())

    diagnostic_summary: dict[str, dict[str, float]] = {}
    for score_id in (BASELINE_ID, CAL_DEEPER_ID, BLEND_ID):
        subset = [row for row in diagnostics if row["score_id"] == score_id]
        diagnostic_summary[score_id] = {
            "mean_rank_ic": float(np.mean([row["rank_ic"] for row in subset])),
            "mean_icir": float(np.mean([row["icir"] for row in subset])),
        }

    receipt = {
        "schema_version": "1.0",
        "experiment_id": spec.experiment_id,
        "runner": BLEND_REPLAY_ID,
        "status": "completed",
        "decision": "cn_rank_blend_supported" if supported else "cn_rank_blend_not_supported",
        "observed_provider_identity_sha256": observed_provider,
        "sector_classification_sha256": classification_identity,
        "selection_windows": list(SELECTION_WINDOWS),
        "rank_blend_contract": spec.raw["rank_blend_diagnostic"],
        "diagnostic_summary": diagnostic_summary,
        "strategies": rows,
        "support_boundary": {
            "checks": checks,
            "supported": supported,
        },
        "score_reproduction": score_reproduction,
        "portfolio_reproduction": portfolio_reproduction,
        "new_holdout_consumed": False,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "stage_b_receipt.json", receipt)
    return receipt
