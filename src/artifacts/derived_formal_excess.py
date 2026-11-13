"""Derive a descriptive compounded excess return from an accepted formal run.

Bundle v2 only packages metrics retained by the governed formal source. The
accepted QQQ Rotation v4.3 source retains strategy and benchmark returns but not
an excess-return metric, so Bundle v2 correctly reports ``not_retained``. This
module derives the missing descriptive metric from that run's own retained
performance trace. It never rewrites, re-seals or reinterprets sealed evidence.

Method, identical to the retained convention in the ``us_x1_3`` and
``cn_27_v1_3`` formal bundles::

    excess = (1 + strategy_cumulative_return) / (1 + benchmark_cumulative_return) - 1
           = strategy_terminal_wealth / benchmark_terminal_wealth - 1

Both cumulative returns are geometric products over the same retained daily
observations, in chronological order, with no interpolation, substitution,
forward fill or re-weighting. The retained summary metrics are used only to
reconcile the recomputation; the derived value is computed from the series.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_bundle_reader import FormalRun, load_formal_run

SCHEMA_VERSION = "1.0"
EVIDENCE_TYPE = "derived_formal_benchmark_excess"
DEFAULT_FORMAL_ROOT = Path("data/research/formal_model_runs")
DEFAULT_ARTIFACT_PATH = Path(
    "data/research/derived_metrics/qqqi_qqq_tqqq_v4_3_excess_vs_qqq_v1.json"
)
RECONCILIATION_TOLERANCE = 1e-12

METHOD_ID = "compounded_relative_excess"
METHOD_FORMULA = (
    "(1 + strategy_cumulative_return) / (1 + benchmark_cumulative_return) - 1"
)
METHOD_EQUIVALENT_FORMULA = (
    "strategy_terminal_wealth / benchmark_terminal_wealth - 1"
)
METHOD_DESCRIPTION = (
    "Geometric compounded relative excess: both cumulative returns are sequential "
    "products over the identical retained daily observations of the formal run; "
    "strategy returns are net of the declared transaction-cost contract and no "
    "benchmark value is synthesized, interpolated or forward-filled."
)
INPUT_SECTION_IDS = ("summary", "performance", "lineage")


class FormalExcessDerivationError(ValueError):
    """Raised when a formal run cannot yield an exact, non-invented excess value."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_derived_json_bytes(value: object) -> bytes:
    """Encode a derived artifact deterministically for byte-stable publication."""

    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FormalExcessDerivationError(f"{label} must be an object")
    return value


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormalExcessDerivationError(f"{label} is not a retained number")
    number = float(value)
    if not math.isfinite(number):
        raise FormalExcessDerivationError(f"{label} is not finite")
    return number


def _retained_metric(
    summary: Mapping[str, Any],
    *,
    metric_id: str,
    observation_count: int,
) -> float:
    rows = summary.get("metrics")
    if not isinstance(rows, list):
        raise FormalExcessDerivationError("formal summary metrics are missing")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("metric_id") == metric_id
    ]
    if len(matches) != 1:
        raise FormalExcessDerivationError(
            f"expected exactly one summary metric for {metric_id}, found {len(matches)}"
        )
    metric = matches[0]
    if metric.get("availability_status") != "available":
        raise FormalExcessDerivationError(f"summary metric {metric_id} is not available")
    if metric.get("sample_count") != observation_count:
        raise FormalExcessDerivationError(
            f"summary metric {metric_id} sample_count does not match the retained series"
        )
    return _finite_number(metric.get("value"), label=f"summary metric {metric_id}")


def _section_input(run: FormalRun, section_id: str) -> dict[str, Any]:
    declarations = [
        row
        for row in run.manifest.get("sections", [])
        if isinstance(row, Mapping) and row.get("section_id") == section_id
    ]
    if len(declarations) != 1:
        raise FormalExcessDerivationError(
            f"formal manifest does not declare exactly one {section_id} section"
        )
    declaration = declarations[0]
    if declaration.get("availability_status") != "available":
        raise FormalExcessDerivationError(f"formal {section_id} section is unavailable")
    path = (run.manifest_path.parent / str(declaration.get("path") or "")).resolve()
    try:
        path.relative_to(run.manifest_path.parent)
    except ValueError as exc:
        raise FormalExcessDerivationError(
            f"formal {section_id} section escapes the sealed run directory"
        ) from exc
    if not path.is_file():
        raise FormalExcessDerivationError(f"formal {section_id} section file is missing")
    data = path.read_bytes()
    if len(data) != declaration.get("byte_size"):
        raise FormalExcessDerivationError(f"formal {section_id} section byte size changed")
    digest = _sha256_bytes(data)
    if digest != declaration.get("sha256"):
        raise FormalExcessDerivationError(f"formal {section_id} section digest changed")
    return {
        "role": f"formal_{section_id}",
        "path": path.relative_to(run.root).as_posix(),
        "sha256": digest,
        "bytes": len(data),
        "manifest_section": section_id,
    }


def _manifest_input(run: FormalRun) -> dict[str, Any]:
    data = run.manifest_path.read_bytes()
    return {
        "role": "formal_manifest",
        "path": run.manifest_path.relative_to(run.root).as_posix(),
        "sha256": _sha256_bytes(data),
        "bytes": len(data),
        "manifest_section": None,
    }


def _benchmark_source_identity(
    lineage: Mapping[str, Any], *, benchmark: str
) -> dict[str, Any]:
    source_evidence = _mapping(lineage.get("source_evidence"), label="lineage source_evidence")
    coverage = source_evidence.get("coverage")
    if not isinstance(coverage, list):
        raise FormalExcessDerivationError("lineage source coverage is missing")
    entries = [
        row
        for row in coverage
        if isinstance(row, Mapping) and row.get("symbol") == benchmark
    ]
    if len(entries) != 1:
        raise FormalExcessDerivationError(
            f"lineage coverage must retain exactly one {benchmark} source identity"
        )
    entry = entries[0]
    for key in ("path", "sha256", "rows", "first_date", "last_date", "provider", "data_mode"):
        if entry.get(key) in (None, ""):
            raise FormalExcessDerivationError(
                f"lineage {benchmark} coverage is missing {key}"
            )
    data_identity = _mapping(
        source_evidence.get("data_identity"), label="lineage data_identity"
    )
    identity = {
        "bundle_id": data_identity.get("bundle_id"),
        "component_id": data_identity.get("component_id"),
        "component_manifest_sha256": data_identity.get("manifest_sha256"),
        "source_role": entry.get("role"),
        "path": entry.get("path"),
        "sha256": entry.get("sha256"),
        "provider": entry.get("provider"),
        "rows": entry.get("rows"),
        "first_date": entry.get("first_date"),
        "last_date": entry.get("last_date"),
        "data_mode": entry.get("data_mode"),
    }
    for key, value in identity.items():
        if value in (None, ""):
            raise FormalExcessDerivationError(
                f"benchmark source identity is missing {key}"
            )
    return identity


def _reconcile(
    *, recomputed: float, retained: float, label: str
) -> float:
    difference = abs(recomputed - retained)
    if difference > RECONCILIATION_TOLERANCE:
        raise FormalExcessDerivationError(
            f"retained {label} does not reconcile with the retained series "
            f"(difference {difference:.3e} exceeds {RECONCILIATION_TOLERANCE:.0e})"
        )
    return difference


def derive_formal_benchmark_excess(
    repository_root: str | Path,
    model_version_id: str,
    *,
    relative_root: Path = DEFAULT_FORMAL_ROOT,
) -> dict[str, Any]:
    """Return the governed derived-excess artifact for one accepted formal run."""

    repository = Path(repository_root).resolve()
    run = load_formal_run(repository, model_version_id, relative_root=relative_root)
    manifest = run.manifest
    performance = _mapping(run.section("performance"), label="formal performance")
    summary = _mapping(run.section("summary"), label="formal summary")
    lineage = _mapping(run.section("lineage"), label="formal lineage")

    benchmark = str(performance.get("benchmark") or "")
    if not benchmark:
        raise FormalExcessDerivationError("formal performance benchmark is missing")
    if str(summary.get("benchmark") or "") != benchmark:
        raise FormalExcessDerivationError("formal summary and performance benchmarks disagree")
    comparability = _mapping(
        manifest.get("comparability_key"), label="formal comparability_key"
    )
    if str(comparability.get("benchmark_id") or "").lower() != benchmark.lower():
        raise FormalExcessDerivationError(
            "formal comparability benchmark does not match the retained benchmark"
        )

    rows = performance.get("report")
    if not isinstance(rows, list) or not rows:
        raise FormalExcessDerivationError("formal performance trace is empty")
    date_range = _mapping(performance.get("date_range"), label="formal performance date_range")
    start = str(date_range.get("start") or "")
    end = str(date_range.get("end") or "")
    if not start or not end:
        raise FormalExcessDerivationError("formal performance date_range is incomplete")
    if str(comparability.get("start")) != start or str(comparability.get("end")) != end:
        raise FormalExcessDerivationError(
            "formal comparability window does not match the retained performance trace"
        )

    strategy_wealth = 1.0
    benchmark_wealth = 1.0
    dates: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FormalExcessDerivationError(f"formal performance row {index} is not an object")
        date = str(row.get("date") or "")
        if not date:
            raise FormalExcessDerivationError(f"formal performance row {index} has no date")
        if dates and date <= dates[-1]:
            raise FormalExcessDerivationError(
                "formal performance dates are not strictly increasing"
            )
        dates.append(date)
        period_return = _finite_number(
            row.get("period_return"), label=f"performance row {date} period_return"
        )
        benchmark_return = _finite_number(
            row.get("bench"), label=f"performance row {date} benchmark return"
        )
        strategy_wealth *= 1.0 + period_return
        benchmark_wealth *= 1.0 + benchmark_return

    if dates[0] != start or dates[-1] != end:
        raise FormalExcessDerivationError(
            "formal performance trace boundaries do not match the declared window"
        )
    if benchmark_wealth <= 0.0:
        raise FormalExcessDerivationError("benchmark terminal wealth is not positive")

    observation_count = len(rows)
    retained_total = _retained_metric(
        summary, metric_id="total_return", observation_count=observation_count
    )
    retained_benchmark = _retained_metric(
        summary, metric_id="benchmark_return", observation_count=observation_count
    )
    strategy_total = strategy_wealth - 1.0
    benchmark_total = benchmark_wealth - 1.0
    strategy_difference = _reconcile(
        recomputed=strategy_total, retained=retained_total, label="total_return"
    )
    benchmark_difference = _reconcile(
        recomputed=benchmark_total, retained=retained_benchmark, label="benchmark_return"
    )

    excess = strategy_wealth / benchmark_wealth - 1.0

    semantics = _mapping(
        performance.get("performance_semantics"), label="formal performance_semantics"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": EVIDENCE_TYPE,
        "derivation_id": f"{model_version_id}_excess_vs_{benchmark.lower()}_v1",
        "strategy": {
            "model_family_id": run.manifest["model_family_id"],
            "model_version_id": run.model_version_id,
            "model_kind": run.manifest["model_kind"],
            "run_id": run.run_id,
            "bundle_id": run.manifest["bundle_id"],
            "publication_status": run.manifest["publication_status"],
            "generated_at": run.generated_at,
            "manifest_path": run.manifest_path.relative_to(run.root).as_posix(),
            "manifest_sha256": _sha256_bytes(run.manifest_path.read_bytes()),
        },
        "benchmark": {
            "declared_identity": benchmark,
            "comparability_id": comparability["benchmark_id"],
            "series_field": "bench",
            "series_semantics": semantics.get("return_measurement"),
            "source_identity": _benchmark_source_identity(lineage, benchmark=benchmark),
            "registry_note": (
                "The reviewed qqq_reference pin in configs/data/formal_model_data_sources_v1.yaml "
                "(workflow run 38757752731, evidence cutoff 2026-10-14) ends before the run "
                "window boundary and cannot supply the identical window; the formal bundle's own "
                "retained benchmark series from its governed strategy data bundle is used instead. "
                "No benchmark value is fetched, synthesized or interpolated."
            ),
        },
        "window": {
            "declared_start": start,
            "declared_end": end,
            "observed_start": dates[0],
            "observed_end": dates[-1],
            "observation_count": observation_count,
            "evidence_cutoff": run.evidence_cutoff,
            "trace_frequency": performance.get("trace_frequency"),
            "holding_end_offset_sessions": semantics.get("holding_end_offset_sessions"),
            "price_basis": semantics.get("price_basis"),
        },
        "method": {
            "method_id": METHOD_ID,
            "formula": METHOD_FORMULA,
            "equivalent_formula": METHOD_EQUIVALENT_FORMULA,
            "compounding": "geometric",
            "difference_basis": "compounded_relative_excess",
            "observation_set": (
                "all retained formal daily observations, in chronological order, "
                "with the strategy and benchmark rows sharing one index"
            ),
            "strategy_return_basis": (
                "retained net formal period_return, after the declared transaction-cost contract"
            ),
            "benchmark_return_basis": (
                f"retained {benchmark} next-open return for the same row; no substitution, "
                "interpolation or provider refresh"
            ),
            "precedent": (
                "same convention as the retained Compounded Relative Excess Return in the "
                "us_x1_3 and cn_27_v1_3 formal bundles"
            ),
            "description": METHOD_DESCRIPTION,
        },
        "result": {
            "strategy_cumulative_return": strategy_total,
            "benchmark_cumulative_return": benchmark_total,
            "excess_return": excess,
        },
        "reconciliation": {
            "summary_total_return": retained_total,
            "summary_benchmark_return": retained_benchmark,
            "summary_sample_count": observation_count,
            "total_return_absolute_difference": strategy_difference,
            "benchmark_return_absolute_difference": benchmark_difference,
            "tolerance": RECONCILIATION_TOLERANCE,
            "summary_excess_return_availability": "not_retained",
            "sealed_summary_modified": False,
        },
        "inputs": [
            _manifest_input(run),
            *(_section_input(run, section_id) for section_id in INPUT_SECTION_IDS),
        ],
        "boundaries": {
            "research_only": True,
            "trade_ready": False,
            "descriptive_historical_metric": True,
            "pit_certified": False,
            "live_signal": False,
            "sealed_formal_evidence_rewritten": False,
            "formal_catalog_modified": False,
            "source_registry_pins_modified": False,
        },
        "consumer_note": (
            "Bundle v2 summary metrics are sealed and this artifact does not alter them. "
            "A consumer may surface the value only by binding this derivation to the canonical "
            "model_version_id/run_id/manifest_sha256 and labeling it as derived from the retained "
            "formal trace, not as a retained source metric."
        ),
    }


def _assert_not_sealed(repository: Path, output_path: Path) -> None:
    sealed = (repository / DEFAULT_FORMAL_ROOT).resolve()
    try:
        output_path.resolve().relative_to(sealed)
    except ValueError:
        return
    raise FormalExcessDerivationError(
        "derived artifacts must not be written inside sealed formal run directories"
    )


def write_derived_formal_excess(
    artifact: Mapping[str, Any],
    output_path: str | Path,
    *,
    repository_root: str | Path,
) -> Path:
    """Write one deterministic derived artifact outside the sealed formal store."""

    repository = Path(repository_root).resolve()
    output = Path(output_path)
    if not output.is_absolute():
        output = repository / output
    _assert_not_sealed(repository, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_derived_json_bytes(dict(artifact)))
    return output
