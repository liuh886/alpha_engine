"""Issue #954 governed development replay for the CN x1.2 breadth-scaled challenger.

Runs the frozen 17-factor signal (CN x1.1 14-factor ``cn_balanced_ohlcv`` plus
``qlib_alpha158`` cntd30/cord5/imin30) and frozen XGBoost path through the
maintained exact CN ranker portfolio primitives with exactly one mechanism delta:
eligibility stays the existing ``two_of_three`` rule, but the active sleeve is
scaled to ``clamp(breadth_value / 0.50, 0, 1)`` and the remainder is allocated to
the CSI300 benchmark sleeve. The incumbent ``baseline_cn_x1_1`` keeps the existing
``two_of_three`` rule with full exposure, so the two candidates share one runtime
and differ only in the injected exposure policy.

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
    EXPOSURE_POLICIES,
    SUPPORTED_REGIME_RULES,
    RegimeGateSpec,
    build_regime_state,
    clamped_active_share,
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
from src.research.resumable_score_artifacts import (
    RunStateTracker,
    ScoreCheckpointStore,
    canonical_sha256,
    file_sha256,
)
from src.research.rolling_windows import purge_training_tail
from src.research.signal_discovery import CandidateKind, ScoreOrientation, evaluate_candidate
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window

DEVELOPMENT_RUNNER_ID = "cn_x1_2_breadth_scaled_development_v1"
DEVELOPMENT_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2", "2026H1")
DEVELOPMENT_HARD_STOP = pd.Timestamp("2026-06-30")
RESERVED_HOLDOUT_START = pd.Timestamp("2026-07-01")
BASELINE_RULE = "two_of_three"
CHALLENGER_RULE = "two_of_three"
BASELINE_EXPOSURE_POLICY = "full_exposure"
CHALLENGER_EXPOSURE_POLICY = "breadth_scaled"
AUTHORITY_ISSUE = 954
POOL_SIZE = 130
SCORE_CONTRACT_SCHEMA_VERSION = "1.0"
SIGNAL_RUNNER_ID = "cn_x1_2_frozen_signal_v1"
PRIMARY_PASS_ID = "primary"
REPRODUCTION_PASS_ID = "reproduction"


def _governed_file_identity(raw_path: str) -> dict[str, str]:
    path = (PROJECT_ROOT / raw_path).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": raw_path, "sha256": file_sha256(path)}


def _score_artifact_contract(
    *,
    spec: CrossSectionalExperimentSpec,
    observed_provider: str,
    symbols: Sequence[str],
    benchmark_symbol: str,
    factor_contract: dict[str, Any],
    expression_columns: dict[str, str],
    calibration_identity: dict[str, Any],
    window: Any,
    evaluation_dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    """Build the policy-independent identity of one fitted score trace."""

    expressions = tuple(str(value) for value in factor_contract["expressions"])
    exact = dict((spec.raw.get("execution") or {}).get("exact_portfolio") or {})
    snapshot = dict(spec.raw.get("snapshot") or {})
    factor_sources = [
        _governed_file_identity(str(value)) for value in factor_contract["library_sources"]
    ]
    universe_source = str(spec.parent.universe.get("source") or "")
    return {
        "schema_version": SCORE_CONTRACT_SCHEMA_VERSION,
        "runner": SIGNAL_RUNNER_ID,
        "market": spec.market,
        "provider_identity_sha256": observed_provider,
        "source_component_identity_sha256": str(
            snapshot.get("source_component_identity_sha256") or ""
        ),
        "selected_pool": {
            "contract": dict(spec.parent.universe),
            "source": _governed_file_identity(universe_source),
            "registry": _governed_file_identity("configs/pools/selected_pool_registry_v1.yaml"),
            "resolved_symbols_sha256": canonical_sha256(sorted(str(value) for value in symbols)),
        },
        "reference_instrument": {
            "instrument": benchmark_symbol,
            "registry": _governed_file_identity(
                "configs/pools/reference_instrument_registry_v1.yaml"
            ),
        },
        "factor_contract": {
            "library_sources": factor_sources,
            "factor_ids": list(factor_contract["factor_ids"]),
            "expressions": list(expressions),
            "expression_columns": {
                expression: expression_columns[expression] for expression in expressions
            },
            "implementation_hashes": dict(factor_contract["implementation_hashes"]),
        },
        "calibration_identity": calibration_identity,
        "window": {
            "label": str(window.label),
            "train_start": pd.Timestamp(window.train_start).strftime("%Y-%m-%d"),
            "train_end": pd.Timestamp(window.train_end).strftime("%Y-%m-%d"),
            "test_start": pd.Timestamp(window.test_start).strftime("%Y-%m-%d"),
            "test_end": pd.Timestamp(window.test_end).strftime("%Y-%m-%d"),
            "evaluation_dates_sha256": canonical_sha256(
                [pd.Timestamp(value).strftime("%Y-%m-%d") for value in evaluation_dates]
            ),
        },
        "label_contract": {
            "return_expression": RETURN_EXPRESSION,
            "return_provenance": "raw_forward_return",
            "horizon_sessions": 10,
            "purged_training_tail_sessions": 10,
        },
        "execution_contract": {
            "benchmark": benchmark_symbol,
            "execution_delay_sessions": int(exact["execution_delay_sessions"]),
            "holding_sessions": int(exact["holding_sessions"]),
            "rebalance_sessions": int(exact["rebalance_sessions"]),
        },
    }


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


def _candidate_exposure_map(spec: CrossSectionalExperimentSpec) -> dict[str, str]:
    """Resolve the per-candidate exposure policy, defaulting to full exposure."""

    exposures: dict[str, str] = {}
    for row in spec.raw.get("candidates") or []:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id", "")).strip()
        exposures[candidate_id] = (
            str(row.get("exposure_policy", "")).strip() or BASELINE_EXPOSURE_POLICY
        )
    missing = [
        candidate.candidate_id
        for candidate in spec.candidates
        if candidate.candidate_id not in exposures
    ]
    if missing:
        raise ValueError(f"candidates missing exposure policies: {missing}")
    unknown = sorted(set(exposures.values()) - EXPOSURE_POLICIES)
    if unknown:
        raise ValueError(f"unsupported exposure policies: {unknown}")
    return exposures


def _validate_candidate_separation(
    spec: CrossSectionalExperimentSpec,
    rules: dict[str, str],
    exposures: dict[str, str],
) -> str:
    """Require the incumbent two_of_three/full_exposure and the sole scaled challenger."""

    baseline = next(candidate for candidate in spec.candidates if candidate.role == "baseline")
    challengers = [candidate for candidate in spec.candidates if candidate.role == "challenger"]
    if len(challengers) != 1:
        raise ValueError(
            f"breadth-scaled development requires exactly one challenger; got {len(challengers)}"
        )
    if rules[baseline.candidate_id] != BASELINE_RULE:
        raise ValueError(
            f"baseline {baseline.candidate_id} must keep the {BASELINE_RULE} rule; "
            f"got {rules[baseline.candidate_id]!r}"
        )
    if exposures[baseline.candidate_id] != BASELINE_EXPOSURE_POLICY:
        raise ValueError(
            f"baseline {baseline.candidate_id} must keep {BASELINE_EXPOSURE_POLICY} exposure; "
            f"got {exposures[baseline.candidate_id]!r}"
        )
    if rules[challengers[0].candidate_id] != CHALLENGER_RULE:
        raise ValueError(
            f"challenger {challengers[0].candidate_id} must use {CHALLENGER_RULE} "
            "eligibility; "
            f"got {rules[challengers[0].candidate_id]!r}"
        )
    if exposures[challengers[0].candidate_id] != CHALLENGER_EXPOSURE_POLICY:
        raise ValueError(
            f"challenger {challengers[0].candidate_id} must use "
            f"{CHALLENGER_EXPOSURE_POLICY} exposure; "
            f"got {exposures[challengers[0].candidate_id]!r}"
        )
    return challengers[0].candidate_id


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
    risk_on_active_share_mean: float,
    risk_on_active_share_max: float,
    benchmark_sleeve_periods: int,
    benchmark_sleeve_weight_sum: float,
    mixed_weights_sum_to_one: bool,
    exact_four_finite_unique_selections: bool,
) -> dict[str, Any]:
    """Evaluate every Issue #954 development gate against the frozen thresholds."""

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
        "active_share_scaling_engaged": 0.0 < risk_on_active_share_mean < 1.0,
        "active_share_within_unit_bounds": 0.0 < risk_on_active_share_max <= 1.0,
        "benchmark_sleeve_present": benchmark_sleeve_periods > 0
        and benchmark_sleeve_weight_sum > 0.0,
        "mixed_weights_sum_to_one": bool(mixed_weights_sum_to_one),
        "exact_four_finite_unique_selections": bool(exact_four_finite_unique_selections),
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


def _scaled_diagnostics(
    periods: pd.DataFrame,
    holdings: pd.DataFrame,
) -> dict[str, Any]:
    """Compute the Issue #954 active-share and benchmark-sleeve diagnostics."""

    active = periods.loc[periods["risk_on"]]
    risk_on_active_share_mean = float(active["active_share"].mean()) if len(active) else 0.0
    risk_on_active_share_max = float(active["active_share"].max()) if len(active) else 0.0
    risk_on_eligible_share = float(periods["risk_on_eligible"].mean()) if len(periods) else 0.0
    sleeve = holdings.loc[holdings["entity"] == "CSI300 sleeve"]
    benchmark_sleeve_periods = int(len(sleeve))
    benchmark_sleeve_weight_sum = float(sleeve["weight"].sum())
    mixed_weights_sum_to_one = bool(
        np.isclose(
            periods["active_share"].to_numpy() + periods["benchmark_sleeve"].to_numpy(),
            1.0,
        ).all()
    )
    active_names = holdings.loc[holdings["instrument"] != "000300"]
    exact_four = False
    if len(active_names):
        grouped = active_names.groupby(["window", "datetime"])
        exact_four = bool(
            all(
                len(group) == 4
                and group["instrument"].is_unique
                and np.isfinite(group["raw_return"].to_numpy()).all()
                for _, group in grouped
            )
        )
    return {
        "risk_on_eligible_share": risk_on_eligible_share,
        "risk_on_active_share_mean": risk_on_active_share_mean,
        "risk_on_active_share_max": risk_on_active_share_max,
        "benchmark_sleeve_periods": benchmark_sleeve_periods,
        "benchmark_sleeve_weight_sum": benchmark_sleeve_weight_sum,
        "mixed_weights_sum_to_one": mixed_weights_sum_to_one,
        "exact_four_finite_unique_selections": exact_four,
    }


def _run_breadth_scaled_development_impl(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    checkpoint_dir: str | Path | None = None,
    resume: bool = False,
    tracker: RunStateTracker,
) -> dict[str, Any]:
    """Execute the Issue #954 breadth-scaled development replay and emit its receipt."""

    spec = load_cross_sectional_experiment_spec(spec_path)
    if (
        spec.market != "cn"
        or str(spec.raw.get("development_runner") or "") != DEVELOPMENT_RUNNER_ID
    ):
        raise ValueError("spec is not opted into the CN breadth-scaled development replay")
    if spec.raw.get("research_only") is not True or spec.raw.get("trade_ready") is not False:
        raise ValueError("development replay must remain research_only=true, trade_ready=false")
    if (
        spec.contract.base_cost_bps != BASE_COST_BPS
        or spec.contract.stress_cost_bps != STRESS_COST_BPS
    ):
        raise ValueError("breadth-scaled development requires 20/60 bps")
    if tuple(spec.contract.selection_windows) != DEVELOPMENT_WINDOWS:
        raise ValueError("breadth-scaled development requires the five frozen development windows")
    if int(spec.raw.get("authority_issue", 0)) != AUTHORITY_ISSUE:
        raise ValueError("breadth-scaled development requires authority_issue=954")
    rejected_parent = str(spec.raw.get("rejected_parent_candidate") or "").strip()
    if not rejected_parent:
        raise ValueError("breadth-scaled development requires rejected_parent_candidate")

    rules = _candidate_rule_map(spec)
    exposures = _candidate_exposure_map(spec)
    challenger_id = _validate_candidate_separation(spec, rules, exposures)
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
        raise ValueError("CN breadth-scaled runtime universe must be exact CN130")
    benchmark_symbol = str(_benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark_symbol != BENCHMARK:
        raise ValueError(f"CN breadth-scaled benchmark drifted: {benchmark_symbol}")

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
    score_store = ScoreCheckpointStore(
        Path(checkpoint_dir).resolve()
        if checkpoint_dir is not None
        else output / "score_checkpoints"
    )

    ledgers: dict[str, list[pd.DataFrame]] = {
        candidate.candidate_id: [] for candidate in spec.candidates
    }
    score_hashes: dict[str, dict[str, str]] = {
        candidate.candidate_id: {} for candidate in spec.candidates
    }
    diagnostics: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}
    score_artifacts: dict[str, dict[str, dict[str, Any]]] = {
        candidate.candidate_id: {} for candidate in spec.candidates
    }

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
            score_contract = _score_artifact_contract(
                spec=spec,
                observed_provider=observed_provider,
                symbols=symbols,
                benchmark_symbol=benchmark_symbol,
                factor_contract=factor_contracts[candidate_id],
                expression_columns=expression_columns,
                calibration_identity=candidate.calibration.identity_manifest(),
                window=window,
                evaluation_dates=dates,
            )
            unit_key = f"{PRIMARY_PASS_ID}/{candidate_id}/{window.label}"
            tracker.begin_unit(
                {
                    "unit_key": unit_key,
                    "pass_id": PRIMARY_PASS_ID,
                    "candidate_id": candidate_id,
                    "window": window.label,
                }
            )
            scores, checkpoint = score_store.load_or_fit(
                contract=score_contract,
                window=window.label,
                pass_id=PRIMARY_PASS_ID,
                resume=resume,
                fit=lambda candidate=candidate, candidate_id=candidate_id: (
                    fit_predict_ranker_scores(
                        expressions=expressions_by_candidate[candidate_id],
                        expression_columns=expression_columns,
                        features_train=features_train,
                        returns_train=returns_train,
                        features_test=features_test,
                        calibration=candidate.calibration,
                        context=(f"CN breadth-scaled dev train/{window.label}/{candidate_id}"),
                    )
                ),
                score_hash=_score_hash,
            )
            tracker.complete_unit(unit_key, checkpoint)
            score_artifacts[candidate_id].setdefault(window.label, {})[PRIMARY_PASS_ID] = {
                key: checkpoint[key]
                for key in (
                    "contract_identity_sha256",
                    "score_sha256",
                    "content_sha256",
                    "path",
                    "reused",
                )
            }
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

    tracker.set_phase("portfolio_evaluation")
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
                exposure_policy=exposures[candidate_id],
                breadth_threshold=gate.breadth_threshold,
                rebalance_sessions=gate.rebalance_sessions,
                cost_bps=cost_bps,
                validate_holdings=True,
            )

    baseline_id = spec.contract.baseline_candidate_id
    candidate_rows: list[dict[str, Any]] = []
    for candidate in spec.candidates:
        base = results[candidate.candidate_id][BASE_COST_BPS][0]
        stress = results[candidate.candidate_id][STRESS_COST_BPS][0]
        row = _candidate_summary(
            candidate.candidate_id,
            candidate.factor_groups,
            factor_contracts[candidate.candidate_id],
            candidate.calibration.identity_manifest(),
            diagnostics,
            base,
            stress,
        )
        row["exposure_policy"] = exposures[candidate.candidate_id]
        candidate_rows.append(row)

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
        score_contract = _score_artifact_contract(
            spec=spec,
            observed_provider=observed_provider,
            symbols=symbols,
            benchmark_symbol=benchmark_symbol,
            factor_contract=factor_contracts[challenger_id],
            expression_columns=expression_columns,
            calibration_identity=challenger.calibration.identity_manifest(),
            window=window,
            evaluation_dates=evaluation_dates[window.label],
        )
        unit_key = f"{REPRODUCTION_PASS_ID}/{challenger_id}/{window.label}"
        tracker.begin_unit(
            {
                "unit_key": unit_key,
                "pass_id": REPRODUCTION_PASS_ID,
                "candidate_id": challenger_id,
                "window": window.label,
            }
        )
        replay_scores, checkpoint = score_store.load_or_fit(
            contract=score_contract,
            window=window.label,
            pass_id=REPRODUCTION_PASS_ID,
            resume=resume,
            fit=lambda window=window, cached=cached: fit_predict_ranker_scores(
                expressions=expressions_by_candidate[challenger_id],
                expression_columns=expression_columns,
                features_train=cached["features_train"],
                returns_train=cached["returns_train"],
                features_test=cached["features_test"],
                calibration=challenger.calibration,
                context=f"CN breadth-scaled dev replay/{window.label}/{challenger_id}",
            ),
            score_hash=_score_hash,
        )
        tracker.complete_unit(unit_key, checkpoint)
        score_artifacts[challenger_id].setdefault(window.label, {})[REPRODUCTION_PASS_ID] = {
            key: checkpoint[key]
            for key in (
                "contract_identity_sha256",
                "score_sha256",
                "content_sha256",
                "path",
                "reused",
            )
        }
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

    tracker.set_phase("portfolio_reproduction")
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
            rule=rules[challenger_id],
            exposure_policy=exposures[challenger_id],
            breadth_threshold=gate.breadth_threshold,
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
    scaled = _scaled_diagnostics(
        results[challenger_id][BASE_COST_BPS][1],
        results[challenger_id][BASE_COST_BPS][2],
    )
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
        risk_on_active_share_mean=scaled["risk_on_active_share_mean"],
        risk_on_active_share_max=scaled["risk_on_active_share_max"],
        benchmark_sleeve_periods=scaled["benchmark_sleeve_periods"],
        benchmark_sleeve_weight_sum=scaled["benchmark_sleeve_weight_sum"],
        mixed_weights_sum_to_one=scaled["mixed_weights_sum_to_one"],
        exact_four_finite_unique_selections=scaled["exact_four_finite_unique_selections"],
    )

    per_window_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for candidate_id in (baseline_id, challenger_id):
        per_window_metrics[candidate_id] = {}
        for cost_bps in (BASE_COST_BPS, STRESS_COST_BPS):
            per_window_metrics[candidate_id][str(cost_bps)] = _window_map(
                results[candidate_id][cost_bps][3]
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
        "candidate_exposure_policies": dict(exposures),
        "candidates": candidate_rows,
        "development_boundary": boundary,
        "per_window_metrics": per_window_metrics,
        "active_share_benchmark_sleeve": scaled,
        "score_reproduction": reproduction,
        "portfolio_reproduction": portfolio_reproduction,
        "score_artifact_contract_version": SCORE_CONTRACT_SCHEMA_VERSION,
        "score_checkpoint_root": str(score_store.root),
        "score_artifacts": score_artifacts,
        "resume_requested": bool(resume),
        "run_state": str(output / "run_state.json"),
        "progress_log": str(output / "run_progress.jsonl"),
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion": False,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    _write_json(output / "per_window_metrics.json", per_window_metrics)
    _write_json(output / "active_share_benchmark_sleeve.json", scaled)
    _write_json(output / "development_receipt.json", receipt)
    return receipt


def run_breadth_scaled_development(
    spec_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    checkpoint_dir: str | Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Execute #954 with durable progress state and explicit checkpoint recovery."""

    spec = load_cross_sectional_experiment_spec(spec_path)
    output = (
        Path(output_dir).resolve()
        if output_dir is not None
        else PROJECT_ROOT / "artifacts" / "research_experiments" / spec.experiment_id / "stage_b"
    )
    spec_identity = canonical_sha256(
        {
            "experiment": spec.raw,
            "paradigm": spec.parent.to_dict(),
            "runner": DEVELOPMENT_RUNNER_ID,
        }
    )
    total_fit_units = len(spec.candidates) * len(DEVELOPMENT_WINDOWS) + len(DEVELOPMENT_WINDOWS)
    tracker = RunStateTracker(
        output,
        experiment_id=spec.experiment_id,
        runner=DEVELOPMENT_RUNNER_ID,
        spec_identity_sha256=spec_identity,
        total_fit_units=total_fit_units,
        resume=resume,
    )
    tracker.start()
    try:
        receipt = _run_breadth_scaled_development_impl(
            spec_path,
            output_dir=output,
            checkpoint_dir=checkpoint_dir,
            resume=resume,
            tracker=tracker,
        )
    except BaseException as exc:
        tracker.fail(exc)
        raise
    tracker.finish(
        status=str(receipt.get("status") or "completed"),
        decision=str(receipt.get("decision") or "") or None,
    )
    return receipt
