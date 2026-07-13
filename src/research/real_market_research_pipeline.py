"""Orchestrate real-market acceptance and diagnostic-only factor research."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.research.paradigm import load_research_paradigm_spec
from src.research.real_market_acceptance import run_real_market_acceptance
from src.research.spec_bound_factor_diagnostics import run_factor_diagnostics_from_files

PIPELINE_SCHEMA_VERSION = "1.1"
AcceptanceRunner = Callable[..., dict[str, Any]]
DiagnosticsRunner = Callable[..., dict[str, Any]]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_report(path: Path, payload: dict[str, Any]) -> None:
    if not path.is_file():
        _write_json(path, payload)


def run_real_market_research_pipeline(
    spec_path: str | Path,
    *,
    repository_root: str | Path = ".",
    provider_dir: str | Path | None = None,
    csv_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    acceptance_runner: AcceptanceRunner = run_real_market_acceptance,
    diagnostics_runner: DiagnosticsRunner = run_factor_diagnostics_from_files,
) -> dict[str, Any]:
    """Run acceptance first and factor diagnostics only when acceptance passes."""

    root = Path(repository_root).resolve()
    spec_file = Path(spec_path).resolve()
    spec = load_research_paradigm_spec(spec_file)
    run_dir = (
        Path(output_dir).resolve()
        if output_dir is not None
        else root / "artifacts" / "research_runs" / spec.experiment_id
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    acceptance_path = run_dir / "real_market_acceptance.json"
    diagnostics_path = run_dir / "factor_diagnostics.json"
    manifest_path = run_dir / "real_market_research_manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "status": "running",
        "diagnostic_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "promotion_evaluated": False,
        "trade_ready": False,
        "stages": {
            "real_market_acceptance": "running",
            "factor_diagnostics": "not_started",
        },
        "artifacts": {
            "acceptance": str(acceptance_path),
            "factor_diagnostics": str(diagnostics_path),
            "manifest": str(manifest_path),
        },
    }
    _write_json(manifest_path, manifest)

    try:
        acceptance = acceptance_runner(
            spec_file,
            root=root,
            provider_dir=provider_dir,
            csv_dir=csv_dir,
            output_path=acceptance_path,
        )
        _ensure_report(acceptance_path, acceptance)
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failed_stage"] = "real_market_acceptance"
        manifest["error"] = str(exc)
        manifest["stages"]["real_market_acceptance"] = "failed"
        _write_json(manifest_path, manifest)
        raise

    manifest["acceptance_sha256"] = _sha256(acceptance_path)
    if acceptance.get("accepted") is not True:
        manifest["status"] = "blocked"
        manifest["blocking_stage"] = "real_market_acceptance"
        manifest["stages"]["real_market_acceptance"] = "rejected"
        manifest["stages"]["factor_diagnostics"] = "not_run"
        manifest["acceptance_summary"] = acceptance.get("summary", {})
        _write_json(manifest_path, manifest)
        return manifest

    manifest["stages"]["real_market_acceptance"] = "passed"
    manifest["stages"]["factor_diagnostics"] = "running"
    _write_json(manifest_path, manifest)

    try:
        diagnostics = diagnostics_runner(
            spec_file,
            acceptance_path,
            repository_root=root,
            provider_dir=provider_dir,
            output_path=diagnostics_path,
        )
        _ensure_report(diagnostics_path, diagnostics)
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failed_stage"] = "factor_diagnostics"
        manifest["error"] = str(exc)
        manifest["stages"]["factor_diagnostics"] = "failed"
        _write_json(manifest_path, manifest)
        raise

    manifest["status"] = "completed"
    manifest["stages"]["factor_diagnostics"] = "passed"
    manifest["factor_diagnostics_sha256"] = _sha256(diagnostics_path)
    manifest["factor_count"] = diagnostics.get("factor_count")
    manifest["factor_id_count"] = diagnostics.get(
        "factor_id_count", diagnostics.get("factor_count")
    )
    manifest["unique_expression_count"] = diagnostics.get(
        "unique_expression_count"
    )
    manifest["sampled_rebalance_dates"] = diagnostics.get("sampled_rebalance_dates")
    manifest["next_step"] = (
        "Review factor_diagnostics.json. Updating factor libraries or running model "
        "research requires a separate reviewed change; this pipeline never promotes."
    )
    _write_json(manifest_path, manifest)
    return manifest
