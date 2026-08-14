"""Issue #947 governed development replay for the CN x1.2 breadth-veto challenger.

Runs the frozen 17-factor signal (CN x1.1 14-factor ``cn_balanced_ohlcv`` plus
``qlib_alpha158`` cntd30/cord5/imin30) and frozen XGBoost path through the
maintained exact CN ranker portfolio primitives with exactly one regime delta:
``risk_on = breadth_vote AND (long_trend_vote OR medium_momentum_vote)``. The
incumbent ``baseline_cn_x1_1`` keeps the existing ``two_of_three`` rule, so the
two candidates share one runtime and differ only in the risk-on rule.

Development evidence is hard-stopped at 2026-06-30. The 2026H2 certification
holdout is never requested as a window, sampled as an evaluation date, or present
in the regime state, ledger, or period outputs; any violation fails closed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cn130_cross_sectional_ranking import (
    forward_returns,
    load_provider_panel,
    stack_return_frame,
)
from src.research.cn_ranker_exact_portfolio_replay import (
    BASE_COST_BPS,
    BENCHMARK,
    REPLAY_ID as EXACT_REPLAY_ID,
    STRESS_COST_BPS,
    _candidate_factor_contracts,
    _candidate_summary,
    _frame_hash,
    _ledger,
    _load_benchmark_returns,
    _score_hash,
    _write_json,
    economic_rebalance_dates,
    validate_benchmark_execution_economic_rebalance_dates,
    validate_execution_economic_rebalance_dates,
)
from src.research.cn_x1_1_regime_gated import (
    SUPPORTED_REGIME_RULES,
    RegimeGateSpec,
    build_regime_state,
    run_regime_portfolio,
)
from src.research.cross_sectional_experiment_runner import (
    CrossSectionalExperimentSpec,
    load_cross_sectional_experiment_spec,
)
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION as RETURN_EXPRESSION,
    benchmark_instrument as _benchmark_instrument,
    resolve_symbols as _resolve_symbols,
    runtime_for_market as _runtime_for_market,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window

DEVELOPMENT_RUNNER_ID = "cn_x1_2_breadth_veto_development_v1"
DEVELOPMENT_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2", "2026H1")
DEVELOPMENT_HARD_STOP = pd.Timestamp("2026-06-30")
RESERVED_HOLDOUT_START = pd.Timestamp("2026-07-01")
BASELINE_RULE = "two_of_three"
CHALLENGER_RULE = "breadth_veto"
AUTHORITY_ISSUE = 947
POOL_SIZE = 130


def _assert_no_2026h2(dates: Sequence[Any], *, label: str) -> None:
    """Fail closed when any date on or after the reserved 2026H2 holdout is seen."""

    forbidden = sorted(
        {pd.Timestamp(date) for date in dates if pd.Timestamp(date) >= RESERVED_HOLDOUT_START}
    )
    if forbidden:
        rendered = ", ".join(value.strftime("%Y-%m-%d") for value in forbidden[:5])
        raise ValueError(
            f"{label} crosses the reserved 2026H2 holdout "
            f"(on/after {RESERVED_HOLDOUT_START:%Y-%m-%d}): {rendered}"
        )


def _development_windows(
    spec: CrossSectionalExperimentSpec,
    runtime,
) -> tuple[list, dict[str, pd.DatetimeIndex]]:
    """Build the plan bounded by the paradigm hard stop and require exactly the five windows."""

    walk = spec.parent.walk_forward
    strategy = spec.parent.strategy
    requested_test_end = str(walk["test_end"])
    _assert_no_2026h2([requested_test_end], label="paradigm walk_forward.test_end")
    calendar = runtime.calendar(
        str(walk["requested_train_start"]),
        min(str(walk["test_end"]), spec.contract.cutoff),
    )
    if len(calendar) == 0:
        raise ValueError("provider calendar is empty for development range")
    _assert_no_2026h2(calendar, label="provider calendar")
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
    dates = horizon_eligible_dates_by_window(plan, calendar)
    required = set(DEVELOPMENT_WINDOWS)
    selected = [window for window in plan.selected_windows if window.label in required]
    labels = [window.label for window in selected]
    if labels != list(DEVELOPMENT_WINDOWS):
        raise ValueError(f"development windows drifted from the frozen five: {labels}")
    for window in selected:
        _assert_no_2026h2(
            [window.test_start, window.test_end],
            label=f"window {window.label}",
        )
    for label, window_dates in dates.items():
        _assert_no_2026h2(window_dates, label=f"evaluation dates {label}")
    return selected, dates


def _candidate_rule_map(spec: CrossSectionalExperimentSpec) -> dict[str, str]:
    """Resolve the per-candidate risk-on rule, defaulting to the exact portfolio rule."""

    exact_portfolio = (spec.raw.get("execution") or {}).get("exact_portfolio") or {}
    default_rule = str(exact_portfolio.get("regime_rule", BASELINE_RULE)).strip() or BASELINE_RULE
    rules: dict[str, str] = {}
    for row in spec.raw.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id", "")).strip()
        rules[candidate_id] = str(row.get("regime_rule", "")).strip() or default_rule
    missing = [
        candidate.candidate_id
        for candidate in spec.candidates
        if candidate.candidate_id not in rules
    ]
    if missing:
        raise ValueError(f"candidates missing regime rules: {missing}")
    unknown = sorted(set(rules.values()) - SUPPORTED_REGIME_RULES)
    if unknown:
        raise ValueError(f"unsupported regime rules: {unknown}")
    return rules


def _validate_rule_separation(
    spec: CrossSectionalExperimentSpec,
    rules: dict[str, str],
) -> str:
    """Require the incumbent two_of_three rule and the sole breadth-veto challenger."""

    baseline = next(candidate for candidate in spec.candidates if candidate.role == "baseline")
    challengers = [candidate for candidate in spec.candidates if candidate.role == "challenger"]
    if len(challengers) != 1:
        raise ValueError(
            f"breadth-veto development requires exactly one challenger; got {len(challengers)}"
        )
    if rules[baseline.candidate_id] != BASELINE_RULE:
        raise ValueError(
            f"baseline {baseline.candidate_id} must keep the {BASELINE_RULE} rule; "
            f"got {rules[baseline.candidate_id]!r}"
        )
    if rules[challengers[0].candidate_id] != CHALLENGER_RULE:
        raise ValueError(
            f"challenger {challengers[0].candidate_id} must use {CHALLENGER_RULE}; "
            f"got {rules[challengers[0].candidate_id]!r}"
        )
    return challengers[0].candidate_id


def _portfolio_contract(
    spec: CrossSectionalExperimentSpec,
) -> tuple[dict[str, dict[str, str]], str]:
    """Verify the shared exact CN economic contract and load the governed classification."""

    exact = dict((spec.raw.get("execution") or {}).get("exact_portfolio") or {})
    expected = {
        "replay_id": EXACT_REPLAY_ID,
        "sector_classification": "configs/research_classifications/cn130_sector_industry_v1.yaml",
        "sectors": 4,
        "names_per_sector": 1,
        "weighting": "equal_weight",
        "holding_sessions": 10,
        "rebalance_sessions": 10,
        "execution_delay_sessions": 1,
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return normalized, digest.hexdigest()


def _window_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty:
        raise ValueError("regime portfolio returned no per-window results")
    mapping = {str(row["window"]): dict(row) for row in frame.to_dict("records")}
    missing = sorted(set(DEVELOPMENT_WINDOWS) - set(mapping))
    if missing:
        raise ValueError(f"per-window results missing development windows: {missing}")
    return mapping


def _evaluate_development_gates(
    *,
    baseline: dict[str, Any],
    baseline_stress: dict[str, Any],
    challenger: dict[str, Any],
    challenger_stress: dict[str, Any],
    baseline_windows_20: pd.DataFrame,
    baseline_windows_60: pd.DataFrame,
    challenger_windows_20: pd.DataFrame,
    challenger_windows_60: pd.DataFrame,
    challenger_mean_rank_ic: float,
    deterministic_scores: bool,
    deterministic_portfolio: bool,
) -> dict[str, Any]:
    """Evaluate every Issue #947 development gate against the frozen thresholds."""

    base_20 = _window_map(baseline_windows_20)
    base_60 = _window_map(baseline_windows_60)
    chal_20 = _window_map(challenger_windows_20)
    chal_60 = _window_map(challenger_windows_60)
    h1 = "2026H1"
    drawdown_delta = float(challenger["max_drawdown"]) - float(baseline["max_drawdown"])
    h1_drawdown_delta = float(chal_20[h1]["max_drawdown"]) - float(base_20[h1]["max_drawdown"])
    risk_off_cost_gate = bool(
        float(challenger["risk_off_relative_excess"])
        >= -float(challenger["risk_off_total_cost"]) - 0.001
    )
    risk_on_share = float(challenger["risk_on_share"])
    checks = {
        "beats_incumbent_20bps": float(challenger["relative_excess"])
        > float(baseline["relative_excess"]),
        "beats_incumbent_60bps": float(challenger_stress["relative_excess"])
        > float(baseline_stress["relative_excess"]),
        "positive_relative_excess_20bps": float(challenger["relative_excess"]) > 0.0,
        "positive_relative_excess_60bps": float(challenger_stress["relative_excess"]) > 0.0,
        "at_least_four_of_five_positive_windows": int(challenger["positive_excess_windows"]) >= 4,
        "worst_max_drawdown_above_minus_25pct": float(challenger["max_drawdown"]) >= -0.25,
        "drawdown_worsening_within_3pp": drawdown_delta >= -0.03,
        "2026h1_drawdown_worsening_within_3pp": h1_drawdown_delta >= -0.03,
        "2026h1_beats_incumbent_20bps": float(chal_20[h1]["relative_excess"])
        > float(base_20[h1]["relative_excess"]),
        "2026h1_beats_incumbent_60bps": float(chal_60[h1]["relative_excess"])
        > float(base_60[h1]["relative_excess"]),
        "risk_on_relative_excess_positive": float(challenger["risk_on_relative_excess"]) > 0.0,
        "risk_off_relative_no_worse_than_cost_drag": risk_off_cost_gate,
        "risk_on_share_within_bounds": 0.25 <= risk_on_share <= 0.80,
        "risk_on_active_hit_rate_at_least_50pct": float(challenger["risk_on_active_hit_rate"])
        >= 0.50,
        "mean_rank_ic_non_negative": float(challenger_mean_rank_ic) >= 0.0,
        "exact_score_reproduction": bool(deterministic_scores),
        "exact_portfolio_reproduction": bool(deterministic_portfolio),
    }
    supported = all(checks.values())
    return {
        "checks": checks,
        "supported": supported,
        "metrics": {
            "improvement_vs_incumbent_20bps": float(challenger["relative_excess"])
            - float(baseline["relative_excess"]),
            "improvement_vs_incumbent_60bps": float(challenger_stress["relative_excess"])
            - float(baseline_stress["relative_excess"]),
            "worst_drawdown_delta_vs_incumbent": drawdown_delta,
            "worst_2026h1_drawdown_delta_vs_incumbent": h1_drawdown_delta,
            "positive_window_count": int(challenger["positive_excess_windows"]),
            "risk_on_share": risk_on_share,
            "risk_on_active_hit_rate": float(challenger["risk_on_active_hit_rate"]),
            "challenger_mean_rank_ic": float(challenger_mean_rank_ic),
        },
    }


def run_breadth_veto_development(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Execute the Issue #947 breadth-veto development replay and emit its receipt."""

    spec = load_cross_sectional_experiment_spec(spec_path)
    if (
        spec.market != "cn"
        or str(spec.raw.get("development_runner") or "") != DEVELOPMENT_RUNNER_ID
    ):
        raise ValueError("spec is not opted into the CN breadth-veto development replay")
    if spec.raw.get("research_only") is not True or spec.raw.get("trade_ready") is not False:
        raise ValueError("development replay must remain research_only=true, trade_ready=false")
    if (
        spec.contract.base_cost_bps != BASE_COST_BPS
        or spec.contract.stress_cost_bps != STRESS_COST_BPS
    ):
        raise ValueError("breadth-veto development requires 20/60 bps")
    if tuple(spec.contract.selection_windows) != DEVELOPMENT_WINDOWS:
        raise ValueError("breadth-veto development requires the five frozen development windows")
    if int(spec.raw.get("authority_issue", 0)) != AUTHORITY_ISSUE:
        raise ValueError("breadth-veto development requires authority_issue=947")
    rejected_parent = str(spec.raw.get("rejected_parent_candidate") or "").strip()
    if not rejected_parent:
        raise ValueError("breadth-veto development requires rejected_parent_candidate")

    rules = _candidate_rule_map(spec)
    challenger_id = _validate_rule_separation(spec, rules)
    _assert_no_2026h2(
        [spec.parent.walk_forward["test_end"]],
        label="paradigm walk_forward.test_end",
    )

    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "stage_b"
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
            "runner": DEVELOPMENT_RUNNER_ID,
            "status": "data_blocked",
            "decision": "provider_identity_mismatch",
            "expected_provider_identity_sha256": expected_provider,
            "observed_provider_identity_sha256": observed_provider,
            "authority_issue": AUTHORITY_ISSUE,
            "research_only": True,
            "trade_ready": False,
            "automatic_promotion": False,
        }
        _write_json(output / "development_receipt.json", blocked)
        return blocked

    symbols = [str(value).zfill(6) for value in _resolve_symbols(spec, runtime)]
    if len(symbols) != POOL_SIZE or len(set(symbols)) != POOL_SIZE:
        raise ValueError("CN breadth-veto runtime universe must be exact CN130")
    benchmark_symbol = str(_benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark_symbol != BENCHMARK:
        raise ValueError(f"CN breadth-veto benchmark drifted: {benchmark_symbol}")

    classification, classification_identity = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise ValueError("CN130 runtime universe differs from governed classification")

    provider_dir = PROJECT_ROOT / "data" / "providers" / "cn"
    panel = load_provider_panel(provider_dir, [*symbols, BENCHMARK], fields=("close",))
    close = panel.fields["close"].loc[panel.fields["close"].index <= DEVELOPMENT_HARD_STOP]
    _assert_no_2026h2(close.index, label="provider close panel")

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
    _assert_no_2026h2(state.index, label="regime state")
    benchmark_execution = forward_returns(
        close[[BENCHMARK]],
        horizon=gate.horizon_sessions,
        delay=gate.execution_delay_sessions,
    )[BENCHMARK]
    _assert_no_2026h2(benchmark_execution.index, label="benchmark execution returns")

    windows, evaluation_dates = _development_windows(spec, runtime)
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

    for window in windows:
        dates = evaluation_dates[window.label]
        _assert_no_2026h2(dates, label=f"evaluation dates {window.label}")
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
        execution_wide = forward_returns(
            close.loc[:, symbols],
            horizon=gate.horizon_sessions,
            delay=gate.execution_delay_sessions,
        )
        execution_all = normalize_qlib_frame_index(
            stack_return_frame(execution_wide, name="execution_forward_return")
        )
        execution_test = execution_all.loc[
            execution_all.index.get_level_values("datetime").isin(dates)
        ]
        rebalance_dates = economic_rebalance_dates(dates, gate.rebalance_sessions)
        validate_execution_economic_rebalance_dates(
            execution_test,
            rebalance_dates,
            window.label,
        )
        validate_benchmark_execution_economic_rebalance_dates(
            benchmark_execution,
            rebalance_dates,
            window.label,
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
            required_dates=rebalance_dates,
            require_finite=False,
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
                context=f"CN breadth-veto dev train/{window.label}/{candidate_id}",
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
                windows=DEVELOPMENT_WINDOWS,
                variant=gate.variant(),
                rule=rules[candidate_id],
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
                validate_holdings=True,
            )

    baseline_id = spec.contract.baseline_candidate_id
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

    second_ledgers: list[pd.DataFrame] = []
    reproduction: dict[str, dict[str, str]] = {}
    challenger = next(item for item in spec.candidates if item.candidate_id == challenger_id)
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
            context=f"CN breadth-veto dev replay/{window.label}/{challenger_id}",
        )
        second_hash = _score_hash(replay_scores)
        first_hash = score_hashes[challenger_id][window.label]
        reproduction[window.label] = {"first": first_hash, "second": second_hash}
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
            windows=DEVELOPMENT_WINDOWS,
            variant=gate.variant(),
            rule=CHALLENGER_RULE,
            rebalance_sessions=gate.rebalance_sessions,
            cost_bps=cost_bps,
            validate_holdings=True,
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
            first_period_hash == second_period_hash and first_holdings_hash == second_holdings_hash
        )

    challenger_row = next(row for row in candidate_rows if row["candidate_id"] == challenger_id)
    boundary = _evaluate_development_gates(
        baseline=baseline_base,
        baseline_stress=baseline_stress,
        challenger=challenger_base,
        challenger_stress=challenger_stress,
        baseline_windows_20=results[baseline_id][BASE_COST_BPS][3],
        baseline_windows_60=results[baseline_id][STRESS_COST_BPS][3],
        challenger_windows_20=results[challenger_id][BASE_COST_BPS][3],
        challenger_windows_60=results[challenger_id][STRESS_COST_BPS][3],
        challenger_mean_rank_ic=float(challenger_row["mean_rank_ic"]),
        deterministic_scores=deterministic_scores,
        deterministic_portfolio=deterministic_portfolio,
    )

    receipt = {
        "schema_version": "1.1",
        "experiment_id": spec.experiment_id,
        "runner": DEVELOPMENT_RUNNER_ID,
        "status": "completed",
        "decision": (
            f"{challenger_id}_development_supported"
            if boundary["supported"]
            else f"{challenger_id}_development_rejected"
        ),
        "authority_issue": AUTHORITY_ISSUE,
        "rejected_parent_candidate": rejected_parent,
        "observed_provider_identity_sha256": observed_provider,
        "sector_classification_sha256": classification_identity,
        "development_windows": list(DEVELOPMENT_WINDOWS),
        "development_hard_stop": DEVELOPMENT_HARD_STOP.strftime("%Y-%m-%d"),
        "reserved_holdout_start": RESERVED_HOLDOUT_START.strftime("%Y-%m-%d"),
        "no_2026h2_evidence_consumed": True,
        "portfolio_contract": (spec.raw.get("execution") or {}).get("exact_portfolio"),
        "candidate_regime_rules": dict(rules),
        "candidates": candidate_rows,
        "development_boundary": boundary,
        "score_reproduction": reproduction,
        "portfolio_reproduction": portfolio_reproduction,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "development_receipt.json", receipt)
    return receipt
