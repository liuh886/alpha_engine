"""CN Qlib execution adapter for the fixed-10D spec-bound research contract.

The adapter consumes a :class:`SpecBoundExecutionPlan` and never rebuilds the
universe policy, candidate grid, factor baselines, dates, Top/Bottom N, or
return semantics from module-level defaults.

Qlib imports are lazy. Unit tests can inject a runtime implementation without
installing or initializing Qlib.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_lgbm_daily_ranker,
    predict_lgbm_daily_ranker,
)
from src.research.market_data_alignment import (
    align_train_start_to_coverage,
    get_aligned_windows,
)
from src.research.multi_market_readiness import (
    MarketReadinessSpec,
    check_market_data_coverage,
    normalize_market_symbols,
)
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import ResearchSessionConfig
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


class CNExecutionRuntime(Protocol):
    """Minimal market-data surface used by the CN adapter."""

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


@dataclass
class QlibCNExecutionRuntime:
    """Production Qlib implementation of :class:`CNExecutionRuntime`."""

    provider_uri: str | Path | None = None
    _resolved_provider_uri: str = ""

    def initialize(self, repository_root: Path) -> None:
        provider = Path(self.provider_uri) if self.provider_uri else repository_root / "data" / "watchlist"
        self._resolved_provider_uri = str(provider.resolve())
        safe_qlib_init(
            build_qlib_init_cfg(
                None,
                market="cn",
                provider_uri_default=self._resolved_provider_uri,
            )
        )

    def available_symbols(self) -> set[str]:
        from qlib.data import D

        instruments = D.list_instruments(D.instruments("all"), level="market")
        if hasattr(instruments, "tolist"):
            return {str(item) for item in instruments.tolist()}
        return {str(item) for item in instruments}

    def date_coverage(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
    ) -> dict[str, dict[str, Any]]:
        return load_symbol_date_coverage(list(symbols), start, end)

    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        from qlib.data import D

        values = D.calendar(start_time=start, end_time=end, freq="day")
        return pd.DatetimeIndex(values)

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        from qlib.data import D

        return D.features(
            list(symbols),
            list(expressions),
            start_time=start,
            end_time=end,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": "qlib",
            "provider_uri": self._resolved_provider_uri,
            "market": "cn",
        }


def _repository_root(plan: SpecBoundExecutionPlan) -> Path:
    spec_path = Path(plan.spec.spec_path).resolve() if plan.spec.spec_path else None
    if spec_path is not None:
        for parent in spec_path.parents:
            if (parent / "configs").is_dir() and (parent / "src").is_dir():
                return parent
    return Path.cwd()


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.index.names == ["instrument", "datetime"]:
        return frame.swaplevel().sort_index()
    return frame.sort_index()


def _candidates_from_plan(
    plan: SpecBoundExecutionPlan,
) -> tuple[RankerGridCandidate, ...]:
    candidates: list[RankerGridCandidate] = []
    for raw in plan.candidates:
        feature_raw = dict(raw["feature_group"])
        calibration_raw = dict(raw["calibration"])
        candidate = RankerGridCandidate(
            feature_group=RankerFeatureGroup(
                name=str(feature_raw["name"]),
                expressions=tuple(str(item) for item in feature_raw["expressions"]),
            ),
            calibration=RankerCalibration(
                n_gain_bins=int(calibration_raw["n_gain_bins"]),
                num_boost_round=int(calibration_raw["num_boost_round"]),
                num_leaves=int(calibration_raw["num_leaves"]),
                min_data_in_leaf=int(calibration_raw["min_data_in_leaf"]),
                learning_rate=float(calibration_raw.get("learning_rate", 0.05)),
            ),
        )
        if candidate.name != str(raw["name"]):
            raise ValueError(
                "Candidate identity changed while materializing execution plan: "
                f"{raw['name']!r} != {candidate.name!r}"
            )
        candidates.append(candidate)
    return tuple(candidates)


def _effective_contract(
    plan: SpecBoundExecutionPlan,
    *,
    candidates: Sequence[RankerGridCandidate],
    baselines: dict[str, str],
    requested_symbols: Sequence[str],
) -> dict[str, Any]:
    """Rebuild the contract from the exact values consumed by the adapter."""

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


def _fit_ranker_scores(
    candidate: RankerGridCandidate,
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    features_test: pd.DataFrame,
    expression_columns: dict[str, str],
) -> pd.DataFrame:
    columns = [expression_columns[item] for item in candidate.feature_group.expressions]
    x_rank, y_rank, groups = prepare_ranker_frame(
        features_train.loc[:, columns],
        returns_train,
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


def _skip_result(
    plan: SpecBoundExecutionPlan,
    *,
    paths: ResearchRunPaths,
    effective_contract: dict[str, Any],
    reason: str,
    runtime_metadata: dict[str, Any],
    evidence_paths: dict[str, str],
) -> SpecBoundExecutionResult:
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
        evidence_paths={**evidence_paths, "execution_skipped": str(skip_path)},
    )


def execute_cn_qlib_plan(
    plan: SpecBoundExecutionPlan,
    run_dir: Path,
    *,
    runtime: CNExecutionRuntime | None = None,
) -> SpecBoundExecutionResult:
    """Execute the CN research plan and return identity-bound evidence paths."""

    if plan.spec.market != "cn":
        raise ValueError("CN Qlib adapter requires a market='cn' research spec")

    strategy = plan.spec.strategy
    top_n = int(strategy["top_n"])
    bottom_n = int(strategy["bottom_n"])
    if top_n != bottom_n:
        raise ValueError(
            "Current comparison evaluator requires top_n == bottom_n; "
            "asymmetric portfolio intent belongs to the PortfolioIntent stage"
        )

    candidates = _candidates_from_plan(plan)
    baselines = dict(plan.baseline_factors)
    requested_symbols = [
        str(item) for item in plan.declared_contract["universe"]["requested_symbols"]
    ]
    effective_contract = _effective_contract(
        plan,
        candidates=candidates,
        baselines=baselines,
        requested_symbols=requested_symbols,
    )

    paths = ResearchRunPaths(run_dir)
    paths.ensure_dir()
    repository_root = _repository_root(plan)
    market_runtime = runtime or QlibCNExecutionRuntime()
    market_runtime.initialize(repository_root)

    available_symbols = market_runtime.available_symbols()
    normalization = normalize_market_symbols(
        "cn",
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

    if len(normalized_symbols) < min_symbols:
        readiness = {
            "schema_version": "1.0",
            "market": "cn",
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
        return _skip_result(
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

    readiness_spec = MarketReadinessSpec(
        market="cn",
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
        "market": "cn",
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
        return _skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=str(alignment.skip_reason or "coverage alignment skipped"),
            runtime_metadata=runtime_metadata,
            evidence_paths=base_evidence,
        )

    retained_symbols = list(alignment.retained_symbols)
    if len(retained_symbols) <= max(top_n, bottom_n):
        return _skip_result(
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

    calendar = market_runtime.calendar(alignment.aligned_train_start, test_end)
    if calendar.empty:
        return _skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason="CN Qlib calendar is empty in the aligned range",
            runtime_metadata=runtime_metadata,
            evidence_paths=base_evidence,
        )
    available_end = min(pd.Timestamp(test_end), calendar.max()).strftime("%Y-%m-%d")
    windows = get_aligned_windows(
        alignment.aligned_train_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    window_payload = {
        "schema_version": "1.0",
        "experiment_id": plan.spec.experiment_id,
        "requested_min_windows": min_windows,
        "available_end": available_end,
        "windows": [window.to_dict() for window in windows],
    }
    write_json(paths.walk_forward_windows, window_payload)
    runtime_metadata["windows"] = window_payload["windows"]
    evidence_with_windows = {
        **base_evidence,
        "walk_forward_windows": str(paths.walk_forward_windows),
    }
    if len(windows) < min_windows:
        return _skip_result(
            plan,
            paths=paths,
            effective_contract=effective_contract,
            reason=(
                f"only {len(windows)} aligned windows available; "
                f"need at least {min_windows}"
            ),
            runtime_metadata=runtime_metadata,
            evidence_paths=evidence_with_windows,
        )

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

    reports: list[dict[str, Any]] = []
    survived_windows: list[str] = []
    skipped_windows: list[dict[str, str]] = []
    window_output_dir = paths.run_dir / "windows"
    for window in windows:
        config = ResearchSessionConfig(
            market="cn",
            symbols=retained_symbols,
            benchmark=plan.spec.benchmark,
            train_start=window.train_start,
            train_end=window.train_end,
            test_start=window.test_start,
            test_end=window.test_end,
            holding_days=int(strategy["holding_days"]),
            rebalance_days=int(strategy["rebalance_days"]),
            topk=top_n,
            model_type="spec_bound_cn_daily_ranker",
            factor_expressions=feature_expressions,
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
        features_all = _normalize_index(features_all).replace(
            [np.inf, -np.inf],
            np.nan,
        )
        features_all.columns = [
            expression_columns[expression] for expression in feature_expressions
        ]
        raw_returns_all = _normalize_index(raw_returns_all)
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
        test_mask = (dates >= pd.Timestamp(window.test_start)) & (
            dates <= pd.Timestamp(window.test_end)
        )
        features_train, returns_train = purge_training_tail(
            features_all.loc[train_mask].copy(),
            raw_returns_all.loc[train_mask].copy(),
            holding_days=config.holding_days,
        )
        valid, reason = validate_no_nan_inputs(
            features_train,
            context=f"CN spec-bound train/{window.label}",
        )
        if not valid:
            skipped_windows.append({"window": window.label, "reason": reason})
            continue

        features_test = features_all.loc[test_mask].copy()
        returns_test = raw_returns_all.loc[test_mask].copy()
        returns_test.attrs.update(raw_returns_all.attrs)
        candidate_scores: dict[str, pd.DataFrame] = {}
        for candidate in candidates:
            candidate_scores[candidate.name] = _fit_ranker_scores(
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
            baseline = _normalize_index(baseline)
            baseline.columns = ["score"]
            baseline.attrs.update(
                {
                    "provenance": "factor_baseline",
                    "expression": expression,
                }
            )
            candidate_scores[name] = baseline

        reports.append(
            run_10d_experiment(
                config=config,
                candidates=candidate_scores,
                raw_returns=returns_test,
                output_dir=window_output_dir,
            )
        )
        survived_windows.append(window.label)

    runtime_metadata["survived_windows"] = survived_windows
    runtime_metadata["skipped_windows"] = skipped_windows
    if len(reports) < min_windows:
        return _skip_result(
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
