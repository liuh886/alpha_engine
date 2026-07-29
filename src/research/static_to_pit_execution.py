"""Repository-level orchestration for static-to-PIT decomposition."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.data.market_provider import load_provider_manifest
from src.research.market_data_alignment import align_train_start_to_coverage
from src.research.multi_market_readiness import (
    MarketReadinessSpec,
    normalize_market_symbols,
)
from src.research.ndx_window_start_universe import (
    load_snapshot,
    plan_ndx_window_universe,
)
from src.research.notebook_research_api import sanitize_factor_name
from src.research.paradigm import load_research_paradigm_spec
from src.research.qlib_execution_common import (
    _resolve_benchmark_instrument,
    materialize_ranker_candidates,
)
from src.research.research_artifacts import write_json
from src.research.spec_bound_execution import build_spec_bound_execution_plan
from src.research.static_to_pit_contract import (
    build_four_cell_matrix,
    canonical_sha256,
    final_stop_decision,
    validate_endpoint_reproduction,
    validate_frozen_spec_pair,
)
from src.research.static_to_pit_reporting import render_markdown_report
from src.research.static_to_pit_window import (
    WindowExecutionContext,
    execute_decomposition_window,
)
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.walk_forward_stability import summarize_walk_forward_reports
from src.research.window_policy import (
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)


DEFAULT_STATIC_SPEC = Path(
    "configs/research_paradigms/us_10d_lgbm_xgb_ranker_comparison.yaml"
)
DEFAULT_PIT_SPEC = Path(
    "configs/research_paradigms/us_10d_lgbm_xgb_ranker_pit_robustness.yaml"
)
DEFAULT_OUTPUT = Path("artifacts/evidence/static_to_pit_alpha_decomposition")
_PROVIDER_EFFECT_METRICS: tuple[str, ...] = (
    "mean_icir",
    "mean_rank_ic",
    "mean_spread",
    "compounded_total_return",
    "compounded_benchmark_return",
    "compounded_relative_excess_return",
    "worst_drawdown",
    "positive_excess_ratio",
    "ready_ratio",
)


def _repo_path(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _first_snapshot_by_symbol(snapshot: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in sorted(snapshot.snapshot_dates, key=lambda item: item.date):
        for symbol in entry.symbols:
            result.setdefault(str(symbol), str(entry.date))
    return result


def _latest_snapshot_symbols(snapshot: Any) -> tuple[str, ...]:
    latest = max(snapshot.snapshot_dates, key=lambda item: item.date)
    return tuple(map(str, latest.symbols))


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _require_manifest_identity(metadata: Mapping[str, Any], *, label: str) -> str:
    identity = str(metadata.get("provider_identity_sha256", "")).strip()
    if not identity:
        raise ValueError(
            f"{label} must be a manifest-bound provider with a non-empty "
            "provider_identity_sha256"
        )
    return identity


def _original_rows(stability: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in stability.get("candidates", []):
        candidate = str(raw.get("candidate", ""))
        if not candidate.endswith("/original"):
            continue
        name = candidate.split("/", 1)[0]
        if name.startswith(("lgbm:", "xgb:")):
            result[name] = dict(raw)
    return result


def _provider_repair_effect(
    reference_static: Mapping[str, Any],
    controlled_static: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate data-provider repair from the controlled membership matrix."""

    before = _original_rows(reference_static)
    after = _original_rows(controlled_static)
    result: dict[str, Any] = {}
    for candidate in sorted(set(before).intersection(after)):
        metrics: dict[str, Any] = {}
        for metric in _PROVIDER_EFFECT_METRICS:
            left = before[candidate].get(metric)
            right = after[candidate].get(metric)
            if left is None or right is None:
                continue
            metrics[metric] = {
                "published_static_reference": float(left),
                "controlled_repaired_provider_S/S": float(right),
                "provider_repair_effect": float(right) - float(left),
            }
        result[candidate] = metrics
    return result


def _run_static_reference(
    *,
    root: Path,
    static_spec: Any,
    provider_uri: str | Path,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reproduce #183 in a separate process so Qlib providers cannot bleed."""

    provider_path = Path(provider_uri).resolve()
    manifest = load_provider_manifest(
        provider_path,
        expected_market="us",
        required=True,
        verify_files=True,
    )
    if manifest is None:
        raise ValueError("static reference provider manifest is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(root / "scripts" / "run_us_feature_quality_validation.py"),
        "--spec",
        str(Path(static_spec.spec_path).resolve()),
        "--output-dir",
        str(output_dir.resolve()),
        "--provider-uri",
        str(provider_path),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            "static reference subprocess failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    expected = output_dir / static_spec.experiment_id / "walk_forward_stability.json"
    if expected.is_file():
        stability_path = expected
    else:
        candidates = list(output_dir.rglob("walk_forward_stability.json"))
        if len(candidates) != 1:
            raise ValueError(
                "static reference output must contain exactly one "
                f"walk_forward_stability.json; found {len(candidates)}"
            )
        stability_path = candidates[0]
    metadata = {
        "provider": "qlib",
        "provider_uri": str(provider_path),
        "provider_identity_sha256": str(manifest["provider_identity_sha256"]),
        "market": "us",
        "subprocess_command": command,
        "run_dir": str(stability_path.parent),
    }
    _require_manifest_identity(metadata, label="static reference provider")
    return _load_json(stability_path), metadata


def run_static_to_pit_decomposition(
    root: Path,
    *,
    static_reference_provider_uri: str | Path,
    decomposition_provider_uri: str | Path,
    static_spec_path: str | Path = DEFAULT_STATIC_SPEC,
    pit_spec_path: str | Path = DEFAULT_PIT_SPEC,
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Execute the frozen four-cell diagnosis with explicit provider separation.

    The published S/S endpoint is reproduced on its original manifest-bound
    provider. The controlled S/S, S/P, P/S, P/P matrix is run on one repaired
    provider so membership effects are not confounded by price-source changes.
    """

    root = root.resolve()
    out_root = _repo_path(root, output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    static_spec = load_research_paradigm_spec(
        _repo_path(root, static_spec_path)
    )
    pit_spec = load_research_paradigm_spec(_repo_path(root, pit_spec_path))
    frozen_contract = validate_frozen_spec_pair(static_spec, pit_spec)
    static_plan = build_spec_bound_execution_plan(static_spec)
    pit_plan = build_spec_bound_execution_plan(pit_spec)

    candidates = materialize_ranker_candidates(static_plan)
    pit_candidates = materialize_ranker_candidates(pit_plan)
    if [item.to_dict() for item in candidates] != [
        item.to_dict() for item in pit_candidates
    ]:
        raise ValueError("static and PIT candidate identities differ")

    reference_stability, reference_metadata = _run_static_reference(
        root=root,
        static_spec=static_spec,
        provider_uri=static_reference_provider_uri,
        output_dir=out_root / "reference_static",
    )

    strategy = static_spec.strategy
    top_n = int(strategy["top_n"])
    if top_n != int(strategy["bottom_n"]):
        raise ValueError("decomposition requires top_n == bottom_n")

    runtime = QlibUSExecutionRuntime(provider_uri=decomposition_provider_uri)
    runtime.initialize(root)
    provider_symbols = runtime.available_symbols()
    provider_metadata = runtime.metadata()
    _require_manifest_identity(
        provider_metadata,
        label="controlled decomposition provider",
    )

    static_requested = [
        str(item)
        for item in static_plan.declared_contract["universe"]["requested_symbols"]
    ]
    normalization = normalize_market_symbols(
        "us",
        static_requested,
        available_symbols=provider_symbols,
    )
    static_normalized = tuple(item.normalized_symbol for item in normalization)
    walk = dict(pit_spec.walk_forward)
    requested_train_start = str(walk["requested_train_start"])
    test_end = str(walk["test_end"])
    min_symbols = max(
        int(static_spec.universe["min_symbols"]),
        int(pit_spec.universe["min_symbols"]),
    )

    readiness_spec = MarketReadinessSpec(
        market="us",
        symbols=static_normalized,
        benchmark=static_spec.benchmark,
        train_start=requested_train_start,
        test_end=test_end,
        min_symbols=min_symbols,
    )
    coverage = runtime.date_coverage(
        static_normalized,
        requested_train_start,
        test_end,
    )
    static_alignment = align_train_start_to_coverage(
        readiness_spec,
        coverage,
        alignment_mode=str(static_spec.universe["alignment_mode"]),
        min_viable_windows=4,
        first_test_year=2024,
        last_test_year=2025,
    )
    if static_alignment.skipped:
        raise ValueError(
            f"static universe alignment skipped: {static_alignment.skip_reason}"
        )
    static_symbols = tuple(map(str, static_alignment.retained_symbols))
    if len(static_symbols) <= top_n:
        raise ValueError("static retained universe is too small for Top-N")

    calendar = runtime.calendar(static_alignment.aligned_train_start, test_end)
    if calendar.empty:
        raise ValueError("US provider returned an empty decomposition calendar")
    available_end = min(
        pd.Timestamp(test_end),
        calendar.max(),
    ).strftime("%Y-%m-%d")
    window_plan = build_window_sampling_plan(
        calendar,
        static_alignment.aligned_train_start,
        available_end,
        first_test_year=2024,
        last_test_year=2025,
        min_complete_windows=4,
        partial_window_policy="complete_windows_only",
        min_partial_window_eligible_sessions=None,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    windows = list(window_plan.selected_windows)
    expected_windows = ["2024H1", "2024H2", "2025H1", "2025H2"]
    if [window.label for window in windows] != expected_windows:
        raise ValueError(
            "decomposition must resolve exactly 2024H1--2025H2; got "
            f"{[window.label for window in windows]}"
        )
    evaluation_dates = horizon_eligible_dates_by_window(window_plan, calendar)

    snapshot_path = _repo_path(root, str(pit_spec.universe["source"]))
    snapshot = load_snapshot(
        snapshot_path,
        validate_hashes=True,
        validate_source=True,
    )
    first_snapshot = _first_snapshot_by_symbol(snapshot)
    latest_snapshot = _latest_snapshot_symbols(snapshot)

    feature_expressions = tuple(
        sorted(
            {
                expression
                for candidate in candidates
                for expression in candidate.feature_group.expressions
            }
        )
    )
    expression_columns = {
        expression: sanitize_factor_name(expression)
        for expression in feature_expressions
    }
    if len(set(expression_columns.values())) != len(expression_columns):
        raise ValueError("feature expression sanitization produced duplicates")

    benchmark_instrument = _resolve_benchmark_instrument(
        "us",
        static_spec.benchmark,
        provider_symbols,
    )
    per_window_dir = out_root / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)

    reports_by_cell: dict[str, list[dict[str, Any]]] = {
        cell.cell_id: [] for cell in build_four_cell_matrix()
    }
    payloads: list[dict[str, Any]] = []
    declared_membership = pit_plan.declared_contract["universe"][
        "pit_window_membership"
    ]

    for window in windows:
        declared_window = declared_membership[window.label]
        pit_window = plan_ndx_window_universe(
            snapshot=snapshot,
            provider_symbols=provider_symbols,
            window_label=window.label,
            train_start=static_alignment.aligned_train_start,
            train_end=window.train_end,
            test_start=window.test_start,
            test_end=window.test_end,
            oos_snapshot_date=str(declared_window["snapshot_date"]),
            min_symbols=int(pit_spec.universe["min_symbols"]),
            coverage_loader=runtime.date_coverage,
        )
        if pit_window.skipped:
            raise ValueError(
                f"PIT window {window.label} skipped: {pit_window.skip_reason}"
            )
        if (
            static_alignment.aligned_train_start
            != str(pit_window.aligned_train_start)
        ):
            raise ValueError(
                "static and PIT aligned train starts differ; the matrix would "
                "not be controlled: "
                f"static={static_alignment.aligned_train_start}, "
                f"pit={pit_window.aligned_train_start}"
            )

        context = WindowExecutionContext(
            market="us",
            benchmark=static_spec.benchmark,
            benchmark_instrument=benchmark_instrument,
            experiment_id="static_to_pit_alpha_decomposition",
            feature_expressions=feature_expressions,
            expression_columns=expression_columns,
            return_expression=str(strategy["return_expression"]),
            return_provenance=str(strategy["return_provenance"]),
            top_n=top_n,
            holding_days=int(strategy["holding_days"]),
            rebalance_days=int(strategy["rebalance_days"]),
            static_symbols=static_symbols,
            pit_train_symbols=tuple(map(str, pit_window.train_symbols)),
            pit_oos_symbols=tuple(map(str, pit_window.oos_symbols)),
            latest_snapshot_symbols=latest_snapshot,
            first_snapshot_by_symbol=first_snapshot,
            window_snapshot_date=str(pit_window.oos_snapshot_date),
            aligned_train_start=static_alignment.aligned_train_start,
            candidates=tuple(candidates),
            baseline_factors=dict(static_plan.baseline_factors),
            snapshot=snapshot,
            provider_symbols=provider_symbols,
            output_dir=per_window_dir,
        )
        payload = execute_decomposition_window(
            runtime=runtime,
            context=context,
            window=window,
            evaluation_dates=evaluation_dates[window.label],
        )
        payload["snapshot_hash"] = pit_window.oos_snapshot_hash
        write_json(per_window_dir / f"{window.label}.json", payload)
        payloads.append(payload)
        for cell_id, report in payload["cell_reports"].items():
            reports_by_cell[cell_id].append(report)

    stability = {
        cell_id: summarize_walk_forward_reports(reports, min_windows=4)
        for cell_id, reports in reports_by_cell.items()
    }
    reference_endpoints = {
        "S/S": reference_stability,
        "P/P": stability["P/P"],
    }
    endpoint_reproduction = validate_endpoint_reproduction(reference_endpoints)
    if not endpoint_reproduction["passed"]:
        write_json(
            out_root / "endpoint_reproduction_failure.json",
            endpoint_reproduction,
        )
        raise ValueError(
            "reference S/S or controlled P/P did not reproduce committed "
            "metrics; see endpoint_reproduction_failure.json"
        )

    provider_effect = _provider_repair_effect(
        reference_stability,
        stability["S/S"],
    )
    manifest_base = {
        "schema_version": "1.0",
        "experiment_id": "static_to_pit_alpha_decomposition",
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "frozen_contract": frozen_contract,
        "providers": {
            "published_static_reference": reference_metadata,
            "controlled_decomposition": provider_metadata,
        },
        "provider_separation_reason": (
            "#183 used the original static provider while PIT evidence used the "
            "repaired historical-membership provider. Endpoint reproduction is "
            "therefore separated from the one-provider controlled four-cell "
            "matrix."
        ),
        "static_spec": str(_repo_path(root, static_spec_path)),
        "pit_spec": str(_repo_path(root, pit_spec_path)),
        "static_declared_contract_sha256": (
            static_plan.declared_contract_sha256
        ),
        "pit_declared_contract_sha256": pit_plan.declared_contract_sha256,
        "static_alignment_on_controlled_provider": static_alignment.to_dict(),
        "windows": expected_windows,
        "cells": [cell.to_dict() for cell in build_four_cell_matrix()],
        "endpoint_reproduction": endpoint_reproduction,
    }
    manifest = {
        **manifest_base,
        "manifest_sha256": canonical_sha256(manifest_base),
    }
    aggregate = {
        "schema_version": "1.0",
        "experiment_id": "static_to_pit_alpha_decomposition",
        "endpoint_reproduction": endpoint_reproduction,
        "reference_stability": {"S/S": reference_stability},
        "controlled_stability_by_cell": stability,
        "provider_repair_effect": provider_effect,
        "per_window": [
            {
                "window": item["window"]["label"],
                "four_cell_effects": item["four_cell_effects"],
                "label_bin_migration": item["label_bin_migration"],
                "candidate_diagnostics": item["candidate_diagnostics"],
            }
            for item in payloads
        ],
        "decision": final_stop_decision(),
    }

    write_json(out_root / "evidence_manifest.json", manifest)
    write_json(out_root / "aggregate.json", aggregate)
    write_json(out_root / "decision.json", final_stop_decision())
    (out_root / "report.md").write_text(
        render_markdown_report(
            stability=stability,
            reference_stability=reference_stability,
            provider_repair_effect=provider_effect,
            per_window_payloads=payloads,
            endpoint_reproduction=endpoint_reproduction,
        ),
        encoding="utf-8",
    )
    return {
        "status": "completed",
        "output_dir": str(out_root),
        "manifest": manifest,
        "aggregate": aggregate,
    }
