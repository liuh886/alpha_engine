"""Market-neutral helpers and the shared fixed-10D Qlib execution engine.

This module owns the full plan execution implementation once: readiness,
alignment, complete windows, 10-session purge, per-window ranker fitting,
baseline loading, raw 10D evaluation, report/stability aggregation, skip
results, and evidence writing.

Market adapters (:mod:`cn_qlib_execution_adapter` and
:mod:`us_qlib_execution_adapter`) are thin wrappers that supply only their
concrete Qlib runtime and the ``market`` discriminator.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    fit_xgb_daily_ranker,
    predict_lgbm_daily_ranker,
    predict_xgb_daily_ranker,
)
from src.research.evaluation_context import SpecBoundEvaluationContext
from src.research.market_data_alignment import align_train_start_to_coverage
from src.research.multi_market_readiness import (
    MarketReadinessSpec,
    check_market_data_coverage,
    normalize_market_symbols,
)
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_research_api import sanitize_factor_name
from src.research.ranker_calibration_grid import (
    RankerCalibration,
    RankerFeatureGroup,
    RankerGridCandidate,
)
from src.research.research_artifacts import ResearchRunPaths, write_json
from src.research.rolling_windows import purge_training_tail
from src.research.spec_bound_execution import (
    SpecBoundExecutionPlan,
    SpecBoundExecutionResult,
)
from src.research.universe_robustness import (
    load_symbol_date_coverage,
    validate_no_nan_inputs,
)
from src.research.walk_forward_stability import summarize_walk_forward_reports
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)


# ---------------------------------------------------------------------------
# Shared runtime Protocol
# ---------------------------------------------------------------------------


class ExecutionRuntime(Protocol):
    """Minimal market-data surface used by every Qlib execution adapter.

    Concrete implementations (e.g. ``QlibCNExecutionRuntime``,
    ``QlibUSExecutionRuntime``) live in the thin market-adapter modules and
    supply only the provider initialisation, symbol discovery, and market
    metadata that differ between CN and US.
    """

    def initialize(self, repository_root: Path) -> None:
        """Initialize the underlying data provider."""

    def available_symbols(self) -> set[str]:
        """Return symbols discoverable by the provider."""

    def date_coverage(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
    ) -> dict[str, dict[str, Any]]:
        """Return first/last valid dates for every requested symbol."""

    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        """Return the provider trading calendar."""

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Load provider feature expressions for the requested range."""

    def metadata(self) -> dict[str, Any]:
        """Return non-contract provider metadata for audit output."""


# ---------------------------------------------------------------------------
# Market-neutral helpers (pre-existing — unchanged)
# ---------------------------------------------------------------------------


def resolve_repository_root(plan: SpecBoundExecutionPlan) -> Path:
    """Resolve the repository root from a plan's source spec when possible."""

    spec_path = Path(plan.spec.spec_path).resolve() if plan.spec.spec_path else None
    if spec_path is not None:
        for parent in spec_path.parents:
            if (parent / "configs").is_dir() and (parent / "src").is_dir():
                return parent
    return Path.cwd()


def normalize_qlib_frame_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the canonical ``(datetime, instrument)`` sorted index layout."""

    if frame.index.names == ["instrument", "datetime"]:
        return frame.swaplevel().sort_index()
    return frame.sort_index()


def materialize_ranker_candidates(
    plan: SpecBoundExecutionPlan,
) -> tuple[RankerGridCandidate, ...]:
    """Reconstruct typed candidates without changing declared identities."""

    candidates: list[RankerGridCandidate] = []
    for raw in plan.candidates:
        feature_raw = dict(raw["feature_group"])
        calibration_raw = dict(raw["calibration"])
        candidate = RankerGridCandidate(
            feature_group=RankerFeatureGroup(
                name=str(feature_raw["name"]),
                expressions=tuple(
                    str(item) for item in feature_raw["expressions"]
                ),
            ),
            calibration=RankerCalibration(
                n_gain_bins=int(calibration_raw["n_gain_bins"]),
                num_boost_round=int(calibration_raw["num_boost_round"]),
                num_leaves=int(calibration_raw["num_leaves"]),
                min_data_in_leaf=int(calibration_raw["min_data_in_leaf"]),
                learning_rate=float(calibration_raw.get("learning_rate", 0.05)),
            ),
            model_family=str(raw.get("model_family", "lgbm")),
        )
        if candidate.name != str(raw["name"]):
            raise ValueError(
                "Candidate identity changed while materializing execution plan: "
                f"{raw['name']!r} != {candidate.name!r}"
            )
        candidates.append(candidate)
    return tuple(candidates)


def build_effective_execution_contract(
    plan: SpecBoundExecutionPlan,
    *,
    candidates: Sequence[RankerGridCandidate],
    baselines: dict[str, str],
    requested_symbols: Sequence[str],
) -> dict[str, Any]:
    """Rebuild the contract from the exact values consumed by an adapter."""

    declared = plan.declared_contract
    return {
        "schema_version": declared["schema_version"],
        "experiment_id": plan.spec.experiment_id,
        "market": plan.spec.market,
        "benchmark": plan.spec.benchmark,
        "universe": {
            "source": declared["universe"]["source"],
            "source_sha256": declared["universe"]["source_sha256"],
            "market_key": plan.spec.universe["market_key"],
            "requested_symbols": list(requested_symbols),
            "min_symbols": int(plan.spec.universe["min_symbols"]),
            "alignment_mode": str(plan.spec.universe["alignment_mode"]),
        },
        "factors": {
            "source": declared["factors"]["source"],
            "source_sha256": declared["factors"]["source_sha256"],
            "selected_groups": [
                str(item) for item in plan.spec.factor_library["groups"]
            ],
            "candidates": [candidate.to_dict() for candidate in candidates],
            "baseline_factors": dict(sorted(baselines.items())),
        },
        "strategy": dict(plan.spec.strategy),
        "walk_forward": dict(plan.spec.walk_forward),
        "evaluation": dict(plan.spec.evaluation),
        "outputs": dict(plan.spec.outputs),
    }


def fit_ranker_scores(
    candidate: RankerGridCandidate,
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test: pd.DataFrame,
    expression_columns: dict[str, str],
) -> pd.DataFrame:
    """Fit one declared ranker and return test-period scores.

    Dispatches to the LightGBM or XGBoost adapter based on the candidate's
    ``model_family``. Both adapters receive identical processed daily rank
    target, groups, selected feature columns, ``n_gain_bins``, and
    ``num_boost_round``. LightGBM-specific calibration params (``num_leaves``,
    ``min_data_in_leaf``, ``learning_rate``) are **not** translated into XGB
    params — the XGB adapter owns its own structural configuration.
    """

    columns = [
        expression_columns[item]
        for item in candidate.feature_group.expressions
    ]
    x_rank, y_rank, groups = prepare_ranker_frame(
        features_train.loc[:, columns],
        returns_train,
    )
    if candidate.model_family == "xgb":
        ranker = fit_xgb_daily_ranker(
            x_rank,
            y_rank,
            groups,
            n_gain_bins=candidate.calibration.n_gain_bins,
            params=None,
            num_boost_round=candidate.calibration.num_boost_round,
        )
        return predict_xgb_daily_ranker(
            ranker,
            features_test.loc[:, columns],
        )
    ranker = fit_lgbm_daily_ranker(
        x_rank,
        y_rank,
        groups,
        n_gain_bins=candidate.calibration.n_gain_bins,
        params=candidate.calibration.params(),
        num_boost_round=candidate.calibration.num_boost_round,
    )
    return predict_lgbm_daily_ranker(
        ranker,
        features_test.loc[:, columns],
    )


def load_window_benchmark_returns(
    runtime: ExecutionRuntime,
    *,
    benchmark_instrument: str,
    return_expression: str,
    evaluation_dates: pd.DatetimeIndex,
    start: str,
    end: str,
    provenance: str,
    horizon: int,
) -> pd.DataFrame:
    """Load complete raw benchmark returns for one OOS evaluation window."""

    raw = normalize_qlib_frame_index(
        runtime.features(
            [benchmark_instrument],
            [return_expression],
            start,
            end,
        )
    )
    if raw.empty:
        raise ValueError(
            f"Benchmark '{benchmark_instrument}' produced empty data "
            f"in [{start}, {end}]"
        )
    if isinstance(raw.index, pd.MultiIndex):
        raw = raw.xs(benchmark_instrument, level="instrument")
    series = raw.iloc[:, 0] if isinstance(raw, pd.DataFrame) else raw
    result = series.to_frame("return").sort_index()
    if not result.index.is_unique:
        raise ValueError(
            f"Benchmark '{benchmark_instrument}' contains duplicate dates"
        )

    required_dates = pd.DatetimeIndex(evaluation_dates)
    missing_dates = required_dates.difference(result.index)
    if len(missing_dates) > 0:
        raise ValueError(
            f"Benchmark '{benchmark_instrument}' is missing "
            f"{len(missing_dates)} of {len(required_dates)} evaluation dates "
            f"in [{start}, {end}]"
        )
    result = result.loc[required_dates].copy()
    finite = np.isfinite(result["return"].to_numpy())
    if not finite.all():
        raise ValueError(
            f"Benchmark '{benchmark_instrument}' has "
            f"{int((~finite).sum())} non-finite return value(s) on "
            f"evaluation dates in [{start}, {end}]"
        )
    result.attrs.update(
        {
            "provenance": provenance,
            "horizon": horizon,
            "expression": return_expression,
        }
    )
    return result


def _resolve_benchmark_instrument(
    market: str,
    declared_benchmark: str,
    available_symbols: set[str],
) -> str:
    """Resolve a declared benchmark to an instrument symbol available in the provider.

    For CN markets, index benchmarks with ``000XXX`` codes use SH prefix even
    though the general stock normalization maps ``000XXX`` codes to SZ. This
    function adds CN index-aware aliases and performs case-insensitive matching.

    For US markets, delegates to the general :func:`normalize_market_symbols`.

    Raises
    ------
    ValueError
        When no candidate resolves against the available symbols.
    """

    if market == "cn":
        available_upper = {s.upper(): s for s in available_symbols}

        # 1. Generate candidates using the general symbol rule
        general = normalize_market_symbols(
            market,
            [declared_benchmark],
            available_symbols=None,
        )
        candidates: list[str] = (
            list(general[0].candidates) if general else []
        )

        # 2. For CN indexes with 000XXX codes, add SH-prefixed aliases
        #    (000XXX indexes trade on Shanghai, unlike 000XXX stocks which are SZ)
        raw = str(declared_benchmark).strip().upper()
        code = raw
        for prefix in ("SZ", "SH"):
            if code.startswith(prefix) and code[len(prefix) :].isdigit():
                code = code[len(prefix) :]
                break
        for suffix in (".SZ", ".SH"):
            if code.endswith(suffix):
                code = code[: -len(suffix)]
                break
        if code.isdigit():
            six_digit = code.zfill(6)[-6:]
            if six_digit.startswith("000"):
                index_aliases = [
                    f"SH{six_digit}",
                    f"{six_digit}.SH",
                    f"sh{six_digit.lower()}",
                ]
                for alias in index_aliases:
                    if alias not in candidates:
                        candidates.append(alias)

        # 3. Case-insensitive match against available symbols
        for candidate in candidates:
            if candidate.upper() in available_upper:
                return available_upper[candidate.upper()]

        raise ValueError(
            f"Benchmark '{declared_benchmark}' could not be resolved "
            f"against {len(available_symbols)} available symbols. "
            f"Tried candidates: {candidates}"
        )

    # US market: use general normalization unchanged
    normalized = normalize_market_symbols(
        market,
        [declared_benchmark],
        available_symbols=available_symbols or None,
    )
    if not normalized:
        raise ValueError(
            f"Benchmark '{declared_benchmark}' could not be normalized "
            f"against available symbols"
        )
    result = normalized[0].normalized_symbol
    if result.upper() not in {s.upper() for s in available_symbols}:
        raise ValueError(
            f"Benchmark '{declared_benchmark}' could not be normalized "
            f"against available symbols — resolved to '{result}' which is "
            f"not in the available set"
        )
    return result


def build_skip_result(
    plan: SpecBoundExecutionPlan,
    *,
    paths: ResearchRunPaths,
    effective_contract: dict[str, Any],
    reason: str,
    runtime_metadata: dict[str, Any],
    evidence_paths: dict[str, str],
) -> SpecBoundExecutionResult:
    """Write one auditable skipped-execution artifact and result."""

    skip_path = paths.run_dir / "execution_skipped.json"
    write_json(
        skip_path,
        {
            "schema_version": "1.0",
            "experiment_id": plan.spec.experiment_id,
            "status": "skipped",
            "reason": reason,
            "research_only": True,
            "trade_ready": False,
            "runtime_metadata": runtime_metadata,
        },
    )
    return SpecBoundExecutionResult(
        status="skipped",
        effective_contract=effective_contract,
        runtime_metadata={**runtime_metadata, "skip_reason": reason},
        evidence_paths={
            **evidence_paths,
            "execution_skipped": str(skip_path),
        },
    )


# ---------------------------------------------------------------------------
# Shared execution engine — the single Implementation for both markets
# ---------------------------------------------------------------------------


def execute_qlib_plan(
    plan: SpecBoundExecutionPlan,
    run_dir: Path,
    *,
    market: str,
    runtime: ExecutionRuntime,
) -> SpecBoundExecutionResult:
    """Execute a fixed-10D research plan for a single *market*.

    All readiness, alignment, window sampling, ranker fitting, baseline
    loading, 10D evaluation, report aggregation, skip handling, and evidence
    writing live here exactly once.  The ``market`` discriminator ("cn" or
    "us") controls every market-specific string so the two thin adapter
    wrappers need only supply their concrete runtime and the market tag.
    """

    # ── market gate ──────────────────────────────────────────────────────
    if plan.spec.market != market:
        raise ValueError(
            f"{market.upper()} Qlib adapter requires a market={market!r} "
            f"research spec"
        )

    # ── contract materialisation ─────────────────────────────────────────
    strategy = plan.spec.strategy
    top_n = int(strategy["top_n"])
    bottom_n = int(strategy["bottom_n"])
    if top_n != bottom_n:
        raise ValueError(
            "Current comparison evaluator requires top_n == bottom_n; "
            "asymmetric portfolio intent belongs to the PortfolioIntent stage"
        )

    candidates = materialize_ranker_candidates(plan)
    baselines = dict(plan.baseline_factors)
    requested_symbols = [
        str(item) for item in plan.declared_contract["universe"]["requested_symbols"]
    ]
    effective_contract = build_effective_execution_contract(
        plan,
        candidates=candidates,
        baselines=baselines,
        requested_symbols=requested_symbols,
    )

    paths = ResearchRunPaths(run_dir)
    paths.ensure_dir()
    repository_root = resolve_repository_root(plan)
    market_runtime = runtime
    market_runtime.initialize(repository_root)

    available_symbols = market_runtime.available_symbols()
    normalization = normalize_market_symbols(
        market,
        requested_symbols,
        available_symbols=available_symbols or None,
    )
    normalized_symbols = tuple(item.normalized_symbol for item in normalization)
    min_symbols = int(plan.spec.universe["min_symbols"])
    walk_forward = plan.spec.walk_forward
    requested_train_start = str(walk_forward["requested_train_start"])
    test_end = str(walk_forward["test_end"])
    first_test_year = int(walk_forward["first_test_year"])
    last_test_year = int(walk_forward["last_test_year"])
    min_windows = int(walk_forward["min_windows"])
    partial_window_policy = str(walk_forward["partial_window_policy"])
    raw_partial_minimum = walk_forward.get(
        "min_partial_window_eligible_sessions"
    )
    min_partial_window_eligible_sessions = (
        None
        if raw_partial_minimum is None
        else int(raw_partial_minimum)
    )

    runtime_metadata: dict[str, Any] = {
        **market_runtime.metadata(),
        "repository_root": str(repository_root),
        "available_symbol_count": len(available_symbols),
        "requested_symbols": requested_symbols,
        "normalization": [item.to_dict() for item in normalization],
        "normalized_symbols": list(normalized_symbols),
        "candidate_names": [candidate.name for candidate in candidates],
        "baseline_factor_ids": list(baselines),
        "top_n": top_n,
        "bottom_n": bottom_n,
    }

    # ── minimum-symbol skip ──────────────────────────────────────────────
    if len(normalized_symbols) < min_symbols:
        readiness = {
            "schema_version": "1.0",
            "market": market,
            "benchmark": plan.spec.benchmark,
            "requested_symbols": requested_symbols,
            "normalized_symbols": list(normalized_symbols),
            "retained_symbols": [],
            "dropped_symbols": list(normalized_symbols),
            "min_symbols": min_symbols,
            "sufficient": False,
            "skipped": True,
            "skip_reason": (
                f"normalization retained {len(normalized_symbols)} symbols, "
                f"below min_symbols={min_symbols}"
            ),
        }
        write_json(paths.data_readiness, readiness)
        write_json(paths.universe_report, readiness)
        return build_skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=str(readiness["skip_reason"]),
            runtime_metadata=runtime_metadata,
            evidence_paths={
                "data_readiness": str(paths.data_readiness),
                "universe_report": str(paths.universe_report),
            },
        )

    # ── coverage alignment ───────────────────────────────────────────────
    readiness_spec = MarketReadinessSpec(
        market=market,
        symbols=normalized_symbols,
        benchmark=plan.spec.benchmark,
        train_start=requested_train_start,
        test_end=test_end,
        min_symbols=min_symbols,
    )
    date_coverage = market_runtime.date_coverage(
        normalized_symbols,
        requested_train_start,
        test_end,
    )
    alignment = align_train_start_to_coverage(
        readiness_spec,
        date_coverage,
        alignment_mode=str(plan.spec.universe["alignment_mode"]),
        min_viable_windows=min_windows,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    readiness = check_market_data_coverage(
        readiness_spec,
        available_symbols=available_symbols or None,
        date_coverage_data=date_coverage,
    )
    readiness.update(alignment.to_dict())
    write_json(paths.data_readiness, readiness)

    universe_report = {
        "schema_version": "1.0",
        "market": market,
        "benchmark": plan.spec.benchmark,
        "requested_symbols": requested_symbols,
        "normalization": [item.to_dict() for item in normalization],
        "normalized_symbols": list(normalized_symbols),
        "retained_symbols": list(alignment.retained_symbols),
        "dropped_symbols": list(alignment.dropped_symbols),
        "drop_reasons": dict(alignment.drop_reasons),
        "aligned_train_start": alignment.aligned_train_start,
        "test_end": test_end,
    }
    write_json(paths.universe_report, universe_report)
    runtime_metadata.update(
        {
            "retained_symbols": list(alignment.retained_symbols),
            "dropped_symbols": list(alignment.dropped_symbols),
            "aligned_train_start": alignment.aligned_train_start,
        }
    )
    base_evidence = {
        "data_readiness": str(paths.data_readiness),
        "universe_report": str(paths.universe_report),
    }

    if alignment.skipped:
        return build_skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=str(alignment.skip_reason or "coverage alignment skipped"),
            runtime_metadata=runtime_metadata,
            evidence_paths=base_evidence,
        )

    # ── post-alignment size check ────────────────────────────────────────
    retained_symbols = list(alignment.retained_symbols)
    if len(retained_symbols) <= max(top_n, bottom_n):
        return build_skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=(
                f"retained universe has {len(retained_symbols)} symbols, "
                f"but Top/Bottom N requires more than {max(top_n, bottom_n)}"
            ),
            runtime_metadata=runtime_metadata,
            evidence_paths=base_evidence,
        )

    # ── window sampling ──────────────────────────────────────────────────
    calendar = market_runtime.calendar(alignment.aligned_train_start, test_end)
    if calendar.empty:
        return build_skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=(
                f"{market.upper()} Qlib calendar is empty in the aligned range"
            ),
            runtime_metadata=runtime_metadata,
            evidence_paths=base_evidence,
        )
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar,
        alignment.aligned_train_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
        min_complete_windows=min_windows,
        partial_window_policy=partial_window_policy,
        min_partial_window_eligible_sessions=(
            min_partial_window_eligible_sessions
        ),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    windows = list(window_plan.selected_windows)
    evaluation_dates_by_window = horizon_eligible_dates_by_window(
        window_plan, calendar
    )
    window_payload = {
        **window_plan.to_dict(),
        "experiment_id": plan.spec.experiment_id,
        "available_end": available_end,
        "partial_windows_count_toward_min": False,
    }
    readiness.update(
        {
            "viable_windows": window_plan.complete_window_count,
            "viable_windows_policy": "complete_windows_only",
            "partial_windows_count_toward_min": False,
            "viability_evidence_scope": "session_aware",
            "partial_window_policy": partial_window_policy,
            "partial_window_count": window_plan.partial_window_count,
            "complete_minimum_satisfied": (
                window_plan.complete_minimum_satisfied
            ),
        }
    )
    write_json(paths.data_readiness, readiness)
    write_json(paths.walk_forward_windows, window_payload)
    runtime_metadata["windows"] = window_payload["windows"]
    runtime_metadata["window_policy"] = {
        key: value
        for key, value in window_payload.items()
        if key != "windows"
    }
    evidence_with_windows = {
        **base_evidence,
        "walk_forward_windows": str(paths.walk_forward_windows),
    }
    if not window_plan.complete_minimum_satisfied:
        return build_skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=(
                f"only {window_plan.complete_window_count} complete, "
                "session-eligible aligned windows available; "
                f"need at least {min_windows}"
            ),
            runtime_metadata=runtime_metadata,
            evidence_paths=evidence_with_windows,
        )

    # ── feature expression preparation ───────────────────────────────────
    feature_expressions = sorted(
        {
            expression
            for candidate in candidates
            for expression in candidate.feature_group.expressions
        }
    )
    expression_columns = {
        expression: sanitize_factor_name(expression)
        for expression in feature_expressions
    }
    if len(set(expression_columns.values())) != len(expression_columns):
        raise ValueError("Feature expression sanitization produced duplicate columns")

    # ── benchmark resolution ────────────────────────────────────────────
    benchmark_instrument = _resolve_benchmark_instrument(
        market,
        plan.spec.benchmark,
        available_symbols,
    )

    # ── per-window execution ─────────────────────────────────────────────
    model_type = f"spec_bound_{market}_daily_ranker"
    reports: list[dict[str, Any]] = []
    survived_windows: list[str] = []
    skipped_windows: list[dict[str, str]] = []
    window_output_dir = paths.run_dir / "windows"
    for window in windows:
        evaluation_dates = evaluation_dates_by_window[window.label]
        evaluation_start = evaluation_dates.min().strftime("%Y-%m-%d")
        evaluation_end = evaluation_dates.max().strftime("%Y-%m-%d")
        config = SpecBoundEvaluationContext(
            market=market,
            symbols=tuple(retained_symbols),
            benchmark=plan.spec.benchmark,
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=evaluation_start,
            test_end=evaluation_end,
            holding_days=int(strategy["holding_days"]),
            rebalance_days=int(strategy["rebalance_days"]),
            topk=top_n,
            model_type=model_type,
            factor_expressions=tuple(feature_expressions),
            return_expression=str(strategy["return_expression"]),
            experiment_id=f"{plan.spec.experiment_id}_{window.label}",
        )
        features_all = market_runtime.features(
            retained_symbols,
            feature_expressions,
            window.train_start,
            window.test_end,
        )
        raw_returns_all = market_runtime.features(
            retained_symbols,
            [config.return_expression],
            window.train_start,
            window.test_end,
        )
        features_all = normalize_qlib_frame_index(features_all).replace(
            [np.inf, -np.inf],
            np.nan,
        )
        features_all.columns = [
            expression_columns[expression] for expression in feature_expressions
        ]
        raw_returns_all = normalize_qlib_frame_index(raw_returns_all)
        raw_returns_all.columns = ["return"]
        raw_returns_all.attrs.update(
            {
                "provenance": str(strategy["return_provenance"]),
                "horizon": int(strategy["horizon_days"]),
                "expression": config.return_expression,
            }
        )

        dates = features_all.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(window.train_start)) & (
            dates <= pd.Timestamp(window.train_end)
        )
        test_mask = dates.isin(evaluation_dates)
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            raw_returns_all.loc[train_mask].copy(),
            holding_days=config.holding_days,
        )
        valid, reason = validate_no_nan_inputs(
            features_train,
            context=f"{market.upper()} spec-bound train/{window.label}",
        )
        if not valid:
            skipped_windows.append({"window": window.label, "reason": reason})
            continue

        features_test = features_all.loc[test_mask].copy()
        returns_test = raw_returns_all.loc[test_mask].copy()
        returns_test.attrs.update(raw_returns_all.attrs)
        candidate_scores: dict[str, pd.DataFrame] = {}
        for candidate in candidates:
            candidate_scores[candidate.name] = fit_ranker_scores(
                candidate,
                features_train,
                returns_train,
                features_test,
                expression_columns,
            )
        for name, expression in baselines.items():
            baseline = market_runtime.features(
                retained_symbols,
                [expression],
                window.test_start,
                window.test_end,
            )
            baseline = normalize_qlib_frame_index(baseline)
            baseline_dates = baseline.index.get_level_values("datetime")
            baseline = baseline.loc[baseline_dates.isin(evaluation_dates)].copy()
            baseline.columns = ["score"]
            baseline.attrs.update(
                {
                    "provenance": "factor_baseline",
                    "expression": expression,
                }
            )
            candidate_scores[name] = baseline

        # ── benchmark loading (per-window, separate from tradable universe) ─
        try:
            window_benchmark_returns = load_window_benchmark_returns(
                market_runtime,
                benchmark_instrument=benchmark_instrument,
                return_expression=config.return_expression,
                evaluation_dates=evaluation_dates,
                start=config.test_start,
                end=config.test_end,
                provenance=str(strategy["return_provenance"]),
                horizon=int(strategy["horizon_days"]),
            )
        except Exception as exc:
            skipped_windows.append(
                {"window": window.label, "reason": str(exc)}
            )
            continue

        reports.append(
            run_10d_experiment(
                config=config,
                candidates=candidate_scores,
                raw_returns=returns_test,
                benchmark_returns=window_benchmark_returns,
                output_dir=window_output_dir,
            )
        )
        survived_windows.append(window.label)

    runtime_metadata["evaluation_dates_by_window"] = {
        label: [date.strftime("%Y-%m-%d") for date in dates]
        for label, dates in evaluation_dates_by_window.items()
    }
    runtime_metadata["survived_windows"] = survived_windows
    runtime_metadata["skipped_windows"] = skipped_windows
    if len(reports) < min_windows:
        return build_skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=(
                f"only {len(reports)} reports survived validation; "
                f"need at least {min_windows}"
            ),
            runtime_metadata=runtime_metadata,
            evidence_paths=evidence_with_windows,
        )

    stability = summarize_walk_forward_reports(reports, min_windows=min_windows)
    write_json(paths.walk_forward_stability, stability)
    metrics_summary = {
        "schema_version": "1.0",
        "experiment_id": plan.spec.experiment_id,
        "n_reports": stability.get("n_reports"),
        "n_candidates": stability.get("n_candidates"),
        "best_candidate": stability.get("best_candidate"),
    }
    write_json(paths.metrics_summary, metrics_summary)

    runtime_metadata["report_count"] = len(reports)
    return SpecBoundExecutionResult(
        status="passed",
        effective_contract=effective_contract,
        runtime_metadata=runtime_metadata,
        evidence_paths={
            **evidence_with_windows,
            "walk_forward_stability": str(paths.walk_forward_stability),
            "metrics_summary": str(paths.metrics_summary),
        },
    )
