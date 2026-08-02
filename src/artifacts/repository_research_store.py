from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "research" / "catalog.json"


class RepositoryResearchStoreError(ValueError):
    """Raised when repository-backed research evidence is incomplete or invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryResearchStoreError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise RepositoryResearchStoreError(f"JSON root must be an object: {path}")
    return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RepositoryResearchStoreError(f"invalid YAML file: {path}") from exc
    if not isinstance(payload, dict):
        raise RepositoryResearchStoreError(f"YAML root must be a mapping: {path}")
    return payload


def _safe_repo_path(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RepositoryResearchStoreError(f"unsafe repository path: {value}")
    path = (PROJECT_ROOT / relative).resolve()
    if PROJECT_ROOT not in path.parents:
        raise RepositoryResearchStoreError(f"path escapes repository: {value}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _evaluation_window(model: dict[str, Any]) -> dict[str, Any]:
    evidence = model.get("backtest_evidence") or {}
    for key in ("frozen_challenge", "consumed_reporting_window"):
        value = evidence.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _model_metrics(model: dict[str, Any]) -> dict[str, float]:
    evidence = model.get("backtest_evidence") or {}
    development = evidence.get("development") or {}
    evaluation = _evaluation_window(model)
    metrics: dict[str, float] = {}

    aliases = {
        "Compounded Strategy Return": (development, "compounded_strategy_return"),
        "Compounded Benchmark Return": (development, "compounded_benchmark_return"),
        "Compounded Relative Excess Return": (
            development,
            "compounded_relative_excess_return",
        ),
        "Mean ICIR": (development, "mean_icir"),
        "Mean Rank IC": (development, "mean_rank_ic"),
        "Mean Top-Bottom Spread": (development, "mean_top_bottom_spread"),
        "Development Worst Drawdown": (development, "worst_drawdown"),
        "Total Return": (evaluation, "total_return"),
        "Benchmark Return": (evaluation, "benchmark_return"),
        "Excess Return": (evaluation, "simple_excess_return"),
        "IC": (evaluation, "ic"),
        "ICIR": (evaluation, "icir"),
        "Rank IC": (evaluation, "rank_ic"),
        "Top-Bottom Spread": (evaluation, "top_bottom_spread"),
        "Max Drawdown": (evaluation, "max_drawdown"),
        "Turnover": (evaluation, "turnover"),
        "Sharpe Ratio": (evaluation, "sharpe"),
    }
    for label, (source, key) in aliases.items():
        value = _number(source, key) if isinstance(source, dict) else None
        if value is not None:
            metrics[label] = value
    return metrics


def _normalize_model(
    model: dict[str, Any],
    source: str,
    contract_path: str,
    *,
    primary_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if model.get("research_only") is not True or model.get("trade_ready") is not False:
        raise RepositoryResearchStoreError(
            f"invalid research boundary for {source}: "
            "expected research_only=true and trade_ready=false"
        )
    model_id = str(model.get("model_id") or "").strip()
    if not model_id:
        raise RepositoryResearchStoreError(f"model_id is missing: {source}")

    evidence = model.get("evidence_identity") or {}
    provider = model.get("provider_binding") or {}
    runtime = model.get("model") or {}
    metrics = _model_metrics(model)
    snapshot_id = str(
        provider.get("canonical_evidence_provider_identity_sha256")
        or provider.get("provider_identity_sha256")
        or ""
    )
    run_id = str(
        (primary_run or {}).get("run_id")
        or evidence.get("workflow_run_id")
        or evidence.get("artifact_id")
        or model_id
    )
    backtest_evidence = model.get("backtest_evidence") or {}

    params = {
        "repository_source": source,
        "repository_contract_path": contract_path,
        "universe": model.get("universe") or {},
        "provider_binding": provider,
        "features": model.get("features") or {},
        "label": model.get("label") or {},
        "model": runtime,
        "strategy": model.get("strategy") or {},
        "evidence_identity": evidence,
        "primary_repository_run": primary_run or {},
        "known_limitations": model.get("known_limitations") or [],
        "next_version_gate": model.get("next_version_gate") or {},
        "research_only": True,
        "trade_ready": False,
    }
    return {
        "id": model_id,
        "tag": str(model.get("display_name") or model_id),
        "name": str(model.get("display_name") or model_id),
        "market": str(model.get("market") or ""),
        "model_type": str(runtime.get("family") or ""),
        "path": contract_path,
        "run_id": run_id,
        "created_at": str(model.get("release_date") or ""),
        "stage": str(model.get("status") or "baseline_research"),
        "description": str(model.get("objective") or ""),
        "snapshot_id": snapshot_id,
        "metrics": metrics,
        "params": params,
        "payload": {
            "backtest": {
                "metrics": metrics,
                "development": backtest_evidence.get("development") or {},
                "evaluation_window": _evaluation_window(model),
            }
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_and_export_runs(
    catalog: dict[str, Any],
    output_dir: Path,
) -> dict[str, dict[str, Any]]:
    listed_runs = catalog.get("published_runs", [])
    if not isinstance(listed_runs, list):
        raise RepositoryResearchStoreError("catalog published_runs must be a list")

    exported: dict[str, dict[str, Any]] = {}
    run_output_root = output_dir / "runs"
    curve_output_root = output_dir / "curves"
    run_output_root.mkdir(parents=True, exist_ok=True)
    curve_output_root.mkdir(parents=True, exist_ok=True)

    for entry in listed_runs:
        if not isinstance(entry, dict):
            raise RepositoryResearchStoreError("published run entry must be an object")
        expected_id = str(entry.get("run_id") or "")
        source = _safe_repo_path(str(entry.get("source") or ""))
        if not source.is_dir():
            raise RepositoryResearchStoreError(f"published run directory is missing: {source}")

        run = _read_json(source / "run.json")
        metrics = _read_json(source / "metrics.json")
        inventory = _read_json(source / "inventory.json")
        if str(run.get("run_id") or "") != expected_id:
            raise RepositoryResearchStoreError(
                f"catalog/run ID mismatch: {expected_id} != {run.get('run_id')}"
            )
        if run.get("research_only") is not True or run.get("trade_ready") is not False:
            raise RepositoryResearchStoreError(
                f"invalid research boundary for published run: {expected_id}"
            )
        files = inventory.get("files")
        if not isinstance(files, list) or not files:
            raise RepositoryResearchStoreError(
                f"published run inventory is empty: {expected_id}"
            )
        for record in files:
            if not isinstance(record, dict):
                raise RepositoryResearchStoreError(
                    f"invalid inventory record for run: {expected_id}"
                )
            relative = Path(str(record.get("path") or ""))
            if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
                raise RepositoryResearchStoreError(
                    f"unsafe run inventory path: {relative.as_posix()}"
                )
            path = source / relative
            if not path.is_file():
                raise RepositoryResearchStoreError(
                    f"published run artifact is missing: {expected_id}/{relative}"
                )
            if path.stat().st_size != int(record.get("byte_size", -1)):
                raise RepositoryResearchStoreError(
                    f"published run artifact size mismatch: {expected_id}/{relative}"
                )
            if _sha256(path) != str(record.get("sha256") or ""):
                raise RepositoryResearchStoreError(
                    f"published run artifact hash mismatch: {expected_id}/{relative}"
                )

        destination = run_output_root / expected_id
        shutil.copytree(source, destination)
        curve = source / "equity_curve.json"
        if curve.is_file():
            shutil.copy2(curve, curve_output_root / f"{expected_id}.json")
        exported[expected_id] = {
            "run_id": expected_id,
            "model_id": str(run.get("model_id") or ""),
            "market": str(run.get("market") or ""),
            "benchmark": str(run.get("benchmark") or ""),
            "data_snapshot_id": str(run.get("data_snapshot_id") or ""),
            "generated_at": str(run.get("generated_at") or ""),
            "metrics": metrics,
            "path": f"data/runs/{expected_id}/run.json",
        }
    return exported


def export_repository_research_data(
    output_dir: Path,
    *,
    catalog_path: Path = DEFAULT_CATALOG,
) -> dict[str, Any]:
    catalog = _read_json(catalog_path)
    if catalog.get("research_only") is not True or catalog.get("trade_ready") is not False:
        raise RepositoryResearchStoreError("repository catalog has an invalid research boundary")

    listed_models = catalog.get("published_models")
    if not isinstance(listed_models, list) or not listed_models:
        raise RepositoryResearchStoreError("repository catalog publishes no models")

    output_dir.mkdir(parents=True, exist_ok=True)
    published_runs = _verify_and_export_runs(catalog, output_dir)
    models: list[dict[str, Any]] = []
    evidence_cutoffs: list[str] = []
    reports: list[dict[str, Any]] = []
    site_root = output_dir.parent
    report_root = site_root / "reports"
    contract_root = site_root / "docs" / "models"
    report_root.mkdir(parents=True, exist_ok=True)
    contract_root.mkdir(parents=True, exist_ok=True)

    for entry in listed_models:
        if not isinstance(entry, dict):
            raise RepositoryResearchStoreError("published model entry must be an object")
        source_text = str(entry.get("source") or "")
        path = _safe_repo_path(source_text)
        model = _read_yaml(path)
        expected_id = str(entry.get("model_id") or "")
        if str(model.get("model_id") or "") != expected_id:
            raise RepositoryResearchStoreError(
                f"catalog/model ID mismatch: {expected_id} != {model.get('model_id')}"
            )

        primary_run_id = str(entry.get("primary_run_id") or "")
        primary_run = published_runs.get(primary_run_id) if primary_run_id else None
        if primary_run_id and primary_run is None:
            raise RepositoryResearchStoreError(
                f"primary run is not published for model {expected_id}: {primary_run_id}"
            )
        if primary_run and primary_run["model_id"] != expected_id:
            raise RepositoryResearchStoreError(
                f"primary run/model mismatch: {primary_run_id} != {expected_id}"
            )

        contract_destination = contract_root / f"{expected_id}.yaml"
        shutil.copy2(path, contract_destination)
        contract_path = f"docs/models/{contract_destination.name}"
        models.append(
            _normalize_model(
                model,
                source_text,
                contract_path,
                primary_run=primary_run,
            )
        )

        provider = model.get("provider_binding") or {}
        cutoff = provider.get("cutoff")
        if cutoff:
            evidence_cutoffs.append(str(cutoff))

        evidence = model.get("evidence_identity") or {}
        report_source = evidence.get("result_report")
        if report_source:
            report_path = _safe_repo_path(str(report_source))
            if not report_path.is_file():
                raise RepositoryResearchStoreError(
                    f"declared report is missing: {report_source}"
                )
            destination = report_root / report_path.name
            shutil.copy2(report_path, destination)
            static_path = f"reports/{destination.name}"
            reports.append(
                {
                    "id": f"{expected_id}-result-report",
                    "title": f"{model.get('display_name', expected_id)} result report",
                    "date": str(model.get("release_date") or ""),
                    "paths": {"document": str(report_source)},
                    "static_path": static_path,
                    "static_html_path": static_path,
                    "model_id": expected_id,
                }
            )

    models.sort(key=lambda row: (row["market"], row["id"]))
    reports.sort(key=lambda row: row["id"])
    _write_json(output_dir / "repository-catalog.json", catalog)
    _write_json(output_dir / "models.json", models)
    _write_json(output_dir / "reports.json", reports)
    _write_json(output_dir / "arena.json", {"arena_name": "N/A", "leaderboard": []})

    catalog_bytes = catalog_path.read_bytes()
    snapshot_id = hashlib.sha256(catalog_bytes).hexdigest()
    blocked_gates = [] if published_runs else ["run_level_series_not_yet_promoted"]
    warnings = [
        "Only evidence explicitly allow-listed by data/research/catalog.json is published."
    ]
    if not published_runs:
        warnings.append(
            "Run-level curves, holdings and attribution appear only after immutable "
            "repository run records are promoted."
        )
    manifest = {
        "generated_at": str(catalog.get("published_at") or ""),
        "evidence_cutoff": max(evidence_cutoffs) if evidence_cutoffs else None,
        "snapshot_id": snapshot_id,
        "release_id": str(catalog.get("release_id") or ""),
        "source": "repository_research_store",
        "catalog_path": "data/repository-catalog.json",
        "market": "all",
        "stats": {
            "total_models": len(models),
            "total_reports": len(reports),
            "total_runs": len(published_runs),
        },
        "warnings": warnings,
        "blocked_gates": blocked_gates,
        "promotion_decision": "research_baselines_published",
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest
