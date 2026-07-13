"""Spec-bound single-factor diagnostics for accepted real-market data.

The diagnostic path is deliberately separate from the legacy market-wide factor
scanner.  It consumes one canonical ResearchParadigmSpec and one accepted
real-market evidence report, uses the exact declared universe and factor library,
and never registers, promotes, or marks a factor trade-ready.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.research.factor_library import FactorSpec, load_factor_library
from src.research.factor_identity import (
    build_canonical_factor_row,
    expand_alias_rows,
    factor_identity_metadata,
    group_factor_specs_by_expression,
    validate_alias_metric_consistency,
)
from src.research.market_data_alignment import get_aligned_windows
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.spec_bound_execution import (
    build_declared_execution_contract,
    contract_sha256,
)

FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.2"
_REQUIRED_ACCEPTANCE_CHECKS = {
    "real_provider_scope",
    "calendar_coverage",
    "universe_provider_coverage",
    "benchmark_provider_coverage",
    "source_csv_integrity",
}


class FactorDiagnosticsRuntime(Protocol):
    """Minimal provider surface for factor diagnostics."""

    def initialize(self, repository_root: Path) -> None:
        """Initialize the underlying provider."""

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """Load expression values indexed by datetime and instrument."""

    def metadata(self) -> dict[str, Any]:
        """Return non-semantic provider metadata for audit output."""


@dataclass
class QlibFactorDiagnosticsRuntime:
    """Lazy real-Qlib implementation of FactorDiagnosticsRuntime."""

    market: str
    provider_uri: str | Path
    _resolved_provider_uri: str = ""

    def initialize(self, repository_root: Path) -> None:
        provider = Path(self.provider_uri)
        if not provider.is_absolute():
            provider = repository_root / provider
        self._resolved_provider_uri = str(provider.resolve())
        safe_qlib_init(
            build_qlib_init_cfg(
                None,
                market=self.market,
                provider_uri_default=self._resolved_provider_uri,
            )
        )

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
            "market": self.market,
        }


def _resolve_source(spec: ResearchParadigmSpec, source: str) -> Path:
    spec_dir = Path(spec.spec_path).parent if spec.spec_path else Path.cwd()
    for candidate in (spec_dir / source, Path.cwd() / source):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"research source not found: {source}")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_acceptance_report(path: str | Path) -> tuple[dict[str, Any], Path]:
    report_path = Path(path).resolve()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("real-market acceptance report must be a JSON object")
    return dict(payload), report_path


def _validate_acceptance(
    report: dict[str, Any],
    spec: ResearchParadigmSpec,
    declared_contract: dict[str, Any],
) -> None:
    if report.get("accepted") is not True:
        raise ValueError("factor diagnostics require accepted real-market evidence")
    if report.get("experiment_id") != spec.experiment_id:
        raise ValueError("acceptance experiment_id does not match research spec")
    if report.get("market") != spec.market:
        raise ValueError("acceptance market does not match research spec")

    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("acceptance report is missing inputs")
    expected_hash = contract_sha256(declared_contract)
    if inputs.get("declared_contract_sha256") != expected_hash:
        raise ValueError("acceptance contract hash does not match current research spec")

    checks = report.get("checks")
    if not isinstance(checks, list):
        raise ValueError("acceptance report is missing checks")
    statuses = {
        str(item.get("name")): str(item.get("status"))
        for item in checks
        if isinstance(item, dict)
    }
    missing = sorted(_REQUIRED_ACCEPTANCE_CHECKS - set(statuses))
    failed = sorted(
        name for name in _REQUIRED_ACCEPTANCE_CHECKS if statuses.get(name) != "pass"
    )
    if missing or failed:
        raise ValueError(
            "acceptance evidence is incomplete: "
            f"missing={missing}, non_passing={failed}"
        )

    provider_dir = Path(str(inputs.get("provider_dir", "")))
    if not provider_dir.is_dir():
        raise ValueError("accepted provider directory is no longer available")
    if any(provider_dir.rglob("fixture_manifest.json")):
        raise ValueError("synthetic/test provider cannot support factor diagnostics")


def _selected_factor_specs(spec: ResearchParadigmSpec) -> list[tuple[str, FactorSpec]]:
    factor_path = _resolve_source(spec, str(spec.factor_library["source"]))
    groups = load_factor_library(factor_path)
    selected: dict[str, tuple[str, FactorSpec]] = {}

    for group_name in spec.factor_library["groups"]:
        group = groups[str(group_name)]
        for factor in group.factors:
            selected[factor.id] = (group.name, factor)

    by_id = {
        factor.id: (group.name, factor)
        for group in groups.values()
        for factor in group.factors
    }
    for factor_id in spec.candidate_grid["factor_baselines"]:
        factor_key = str(factor_id)
        if factor_key not in by_id:
            raise ValueError(f"baseline factor is missing from factor library: {factor_key}")
        selected.setdefault(factor_key, by_id[factor_key])

    return list(selected.values())


def _finite_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Sequence[float]) -> float | None:
    return _finite_number(np.mean(values)) if values else None


def _std(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return _finite_number(np.std(values, ddof=1))


def _ratio_true(values: Sequence[bool]) -> float | None:
    return _finite_number(np.mean(values)) if values else None


def _icir(values: Sequence[float]) -> float | None:
    mean = _mean(values)
    std = _std(values)
    if mean is None or std is None or std <= 0.0:
        return None
    return _finite_number(mean / std)


def _window_date_map(
    available_dates: pd.DatetimeIndex,
    spec: ResearchParadigmSpec,
) -> tuple[dict[pd.Timestamp, str], list[dict[str, Any]]]:
    """Build non-overlapping rebalance dates whose labels stay inside each OOS window.

    A forward ``horizon_days`` return observed near a window boundary must not use
    prices from the next window.  The final horizon-sized tail of every window is
    therefore excluded before applying the declared rebalance cadence.
    """

    walk = spec.walk_forward
    windows = get_aligned_windows(
        str(walk["requested_train_start"]),
        str(walk["test_end"]),
        first_test_year=int(walk["first_test_year"]),
        last_test_year=int(walk["last_test_year"]),
    )
    if len(windows) < int(walk["min_windows"]):
        raise ValueError("declared walk-forward contract has too few diagnostic windows")

    cadence = int(spec.strategy["rebalance_days"])
    horizon = int(spec.strategy["horizon_days"])
    if cadence <= 0 or horizon <= 0:
        raise ValueError("diagnostic cadence and horizon must be positive")

    date_map: dict[pd.Timestamp, str] = {}
    window_rows: list[dict[str, Any]] = []
    for window in windows:
        start = pd.Timestamp(window.test_start)
        end = pd.Timestamp(window.test_end)
        dates = available_dates[(available_dates >= start) & (available_dates <= end)]
        if len(dates) > horizon:
            horizon_eligible = dates[:-horizon]
        else:
            horizon_eligible = dates[:0]
        sampled = horizon_eligible[::cadence]
        for date in sampled:
            date_map[pd.Timestamp(date)] = window.label
        window_rows.append(
            {
                **window.to_dict(),
                "available_sessions": int(len(dates)),
                "horizon_eligible_sessions": int(len(horizon_eligible)),
                "excluded_tail_sessions": int(len(dates) - len(horizon_eligible)),
                "label_horizon_sessions": horizon,
                "sampled_sessions": int(len(sampled)),
            }
        )
    if not date_map:
        raise ValueError("no horizon-contained rebalance dates are available for factor diagnostics")
    return date_map, window_rows

def _daily_factor_rows(
    factor: pd.Series,
    returns: pd.Series,
    *,
    date_map: dict[pd.Timestamp, str],
    top_n: int,
    bottom_n: int,
) -> tuple[list[dict[str, Any]], int]:
    joined = pd.concat(
        [factor.rename("factor"), returns.rename("return")],
        axis=1,
        join="inner",
    ).replace([np.inf, -np.inf], np.nan)
    joined = joined.dropna(subset=["factor", "return"])
    if joined.empty:
        return [], 0

    dates = joined.index.get_level_values("datetime")
    joined = joined.loc[dates.isin(date_map)]
    finite_pairs = int(len(joined))
    minimum_cross_section = top_n + bottom_n
    rows: list[dict[str, Any]] = []

    for date, day in joined.groupby(level="datetime", sort=True):
        day = day.droplevel("datetime")
        if len(day) < minimum_cross_section or day["factor"].nunique() < 2:
            continue
        pearson = _finite_number(day["factor"].corr(day["return"], method="pearson"))
        rank_ic = _finite_number(day["factor"].corr(day["return"], method="spearman"))
        if pearson is None or rank_ic is None:
            continue
        ordered = day.sort_values("factor", kind="mergesort")
        bottom = float(ordered.head(bottom_n)["return"].mean())
        top = float(ordered.tail(top_n)["return"].mean())
        spread = _finite_number(top - bottom)
        if spread is None:
            continue
        timestamp = pd.Timestamp(date)
        rows.append(
            {
                "date": timestamp.strftime("%Y-%m-%d"),
                "window": date_map[timestamp],
                "n_instruments": int(len(day)),
                "pearson_ic": pearson,
                "rank_ic": rank_ic,
                "top_bottom_spread": spread,
            }
        )
    return rows, finite_pairs


def _summarize_metric_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pearson = [float(row["pearson_ic"]) for row in rows]
    rank_ic = [float(row["rank_ic"]) for row in rows]
    spread = [float(row["top_bottom_spread"]) for row in rows]
    sizes = [int(row["n_instruments"]) for row in rows]
    return {
        "valid_dates": len(rows),
        "mean_cross_section_size": _mean(sizes),
        "mean_pearson_ic": _mean(pearson),
        "mean_rank_ic": _mean(rank_ic),
        "rank_ic_std": _std(rank_ic),
        "rank_icir": _icir(rank_ic),
        "positive_rank_ic_ratio": _ratio_true([value > 0.0 for value in rank_ic]),
        "mean_top_bottom_spread": _mean(spread),
        "positive_spread_ratio": _ratio_true([value > 0.0 for value in spread]),
    }


def _factor_diagnostic(
    group_name: str,
    factor_spec: FactorSpec,
    factor_values: pd.Series,
    returns: pd.Series,
    *,
    date_map: dict[pd.Timestamp, str],
    requested_symbol_count: int,
    top_n: int,
    bottom_n: int,
) -> dict[str, Any]:
    rows, finite_pairs = _daily_factor_rows(
        factor_values,
        returns,
        date_map=date_map,
        top_n=top_n,
        bottom_n=bottom_n,
    )
    summary = _summarize_metric_rows(rows)
    expected_pairs = len(date_map) * requested_symbol_count
    coverage_ratio = finite_pairs / expected_pairs if expected_pairs else 0.0

    window_metrics: list[dict[str, Any]] = []
    for window in sorted(set(date_map.values())):
        window_rows = [row for row in rows if row["window"] == window]
        window_metrics.append({"window": window, **_summarize_metric_rows(window_rows)})

    mean_rank_ic = summary["mean_rank_ic"]
    orientation = "invert_score" if mean_rank_ic is not None and mean_rank_ic < 0.0 else "keep_score"
    multiplier = -1.0 if orientation == "invert_score" else 1.0
    raw_spread = summary["mean_top_bottom_spread"]
    raw_icir = summary["rank_icir"]
    oriented_window_signs = [
        float(row["mean_rank_ic"]) * multiplier > 0.0
        for row in window_metrics
        if row["mean_rank_ic"] is not None
    ]
    direction_agreement = None
    if mean_rank_ic not in (None, 0.0) and raw_spread not in (None, 0.0):
        direction_agreement = bool(float(mean_rank_ic) * float(raw_spread) > 0.0)

    return {
        **factor_spec.to_dict(),
        "group": group_name,
        "coverage_ratio": _finite_number(coverage_ratio),
        **summary,
        "recommended_orientation": orientation,
        "oriented_mean_rank_ic": (
            None if mean_rank_ic is None else _finite_number(float(mean_rank_ic) * multiplier)
        ),
        "oriented_rank_icir": (
            None if raw_icir is None else _finite_number(float(raw_icir) * multiplier)
        ),
        "oriented_mean_top_bottom_spread": (
            None if raw_spread is None else _finite_number(float(raw_spread) * multiplier)
        ),
        "direction_agreement": direction_agreement,
        "positive_oriented_window_ratio": _ratio_true(oriented_window_signs),
        "window_metrics": window_metrics,
    }


def run_factor_diagnostics(
    spec: ResearchParadigmSpec,
    acceptance_report: dict[str, Any],
    *,
    repository_root: str | Path = ".",
    runtime: FactorDiagnosticsRuntime,
    acceptance_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run diagnostic-only single-factor research against accepted market data."""

    root = Path(repository_root).resolve()
    declared_contract = build_declared_execution_contract(spec)
    _validate_acceptance(acceptance_report, spec, declared_contract)
    runtime.initialize(root)

    requested_symbols = [
        row.normalized_symbol
        for row in normalize_market_symbols(
            spec.market,
            list(declared_contract["universe"]["requested_symbols"]),
        )
    ]
    factor_specs = _selected_factor_specs(spec)
    canonical_specs = group_factor_specs_by_expression(factor_specs)
    expressions = [item.evaluation_expression for item in canonical_specs]
    return_expression = str(spec.strategy["return_expression"])
    start = str(spec.walk_forward["requested_train_start"])
    end = str(spec.walk_forward["test_end"])

    features = normalize_qlib_frame_index(
        runtime.features(requested_symbols, expressions, start, end)
    ).replace([np.inf, -np.inf], np.nan)
    if len(features.columns) != len(expressions):
        raise ValueError("provider returned an unexpected factor column count")
    features.columns = expressions

    raw_returns = normalize_qlib_frame_index(
        runtime.features(requested_symbols, [return_expression], start, end)
    ).replace([np.inf, -np.inf], np.nan)
    if len(raw_returns.columns) != 1:
        raise ValueError("provider returned an unexpected return column count")
    raw_returns.columns = ["return"]
    raw_returns.attrs.update(
        {
            "provenance": str(spec.strategy["return_provenance"]),
            "horizon": int(spec.strategy["horizon_days"]),
            "expression": return_expression,
        }
    )

    available_dates = pd.DatetimeIndex(
        sorted(set(raw_returns.index.get_level_values("datetime")))
    )
    date_map, windows = _window_date_map(available_dates, spec)
    returns_series = raw_returns["return"]
    top_n = int(spec.strategy["top_n"])
    bottom_n = int(spec.strategy["bottom_n"])

    canonical_diagnostics: list[dict[str, Any]] = []
    for canonical_spec in canonical_specs:
        representative = canonical_spec.aliases[0]
        diagnostic = _factor_diagnostic(
            representative.group_name,
            representative.factor,
            features[canonical_spec.evaluation_expression],
            returns_series,
            date_map=date_map,
            requested_symbol_count=len(requested_symbols),
            top_n=top_n,
            bottom_n=bottom_n,
        )
        canonical_diagnostics.append(
            build_canonical_factor_row(canonical_spec, diagnostic)
        )

    canonical_diagnostics.sort(
        key=lambda row: (
            abs(float(row["oriented_rank_icir"] or 0.0)),
            abs(float(row["oriented_mean_rank_ic"] or 0.0)),
            float(row["coverage_ratio"] or 0.0),
        ),
        reverse=True,
    )
    for canonical_rank, row in enumerate(canonical_diagnostics, start=1):
        row["canonical_rank"] = canonical_rank

    factor_alias_rows = [
        alias_row
        for canonical_row in canonical_diagnostics
        for alias_row in expand_alias_rows(canonical_row)
    ]
    validate_alias_metric_consistency(factor_alias_rows)
    factor_alias_map = {
        str(row["id"]): str(row["canonical_expression_id"])
        for row in factor_alias_rows
    }


    acceptance_sha256 = ""
    if acceptance_path is not None:
        acceptance_sha256 = _sha256_file(Path(acceptance_path).resolve())

    return {
        "schema_version": FACTOR_DIAGNOSTICS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "benchmark": spec.benchmark,
        "diagnostic_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "promotion_evaluated": False,
        "declared_contract_sha256": contract_sha256(declared_contract),
        "acceptance_report_sha256": acceptance_sha256,
        "return_contract": {
            "expression": return_expression,
            "provenance": raw_returns.attrs["provenance"],
            "horizon_days": raw_returns.attrs["horizon"],
            "rebalance_days": int(spec.strategy["rebalance_days"]),
            "top_n": top_n,
            "bottom_n": bottom_n,
        },
        "universe": {
            "source": declared_contract["universe"]["source"],
            "source_sha256": declared_contract["universe"]["source_sha256"],
            "requested_symbol_count": len(requested_symbols),
            "survivorship_bias": bool(spec.universe.get("survivorship_bias", False)),
        },
        "provider": runtime.metadata(),
        "windows": windows,
        "sampled_rebalance_dates": len(date_map),
        "factor_count": len(canonical_diagnostics),
        "factor_id_count": len(factor_alias_rows),
        "unique_expression_count": len(canonical_diagnostics),
        "factor_identity": factor_identity_metadata(),
        "ranking_subject": "canonical_expression",
        "ranking_basis": [
            "absolute_oriented_rank_icir",
            "absolute_oriented_mean_rank_ic",
            "coverage_ratio",
        ],
        "factors": canonical_diagnostics,
        "factor_alias_rows": factor_alias_rows,
        "factor_alias_map": factor_alias_map,
    }


def run_factor_diagnostics_from_files(
    spec_path: str | Path,
    acceptance_path: str | Path,
    *,
    repository_root: str | Path = ".",
    provider_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    runtime: FactorDiagnosticsRuntime | None = None,
) -> dict[str, Any]:
    spec = load_research_paradigm_spec(spec_path)
    acceptance, report_path = load_acceptance_report(acceptance_path)
    accepted_provider = Path(str(acceptance.get("inputs", {}).get("provider_dir", ""))).resolve()
    selected_provider = Path(provider_dir).resolve() if provider_dir else accepted_provider
    if selected_provider != accepted_provider:
        raise ValueError("factor diagnostics must use the provider accepted by the report")

    selected_runtime = runtime or QlibFactorDiagnosticsRuntime(
        market=spec.market,
        provider_uri=selected_provider,
    )
    report = run_factor_diagnostics(
        spec,
        acceptance,
        repository_root=repository_root,
        runtime=selected_runtime,
        acceptance_path=report_path,
    )
    if output_path is None:
        output_path = (
            Path(repository_root)
            / "artifacts"
            / "research_runs"
            / spec.experiment_id
            / "factor_diagnostics.json"
        )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["output_path"] = str(output.resolve())
    return report
