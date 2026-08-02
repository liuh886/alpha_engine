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
        if isinstance(source, dict):
            value = _number(source, key)
            if value is not None:
                metrics[label] = value
    return metrics


def _normalize_model(
    model: dict[str, Any],
    source: str,
    contract_path: str,
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
    run_id = str(evidence.get("workflow_run_id") or evidence.get("artifact_id") or model_id)
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
        source = str(entry.get("source") or "")
        path = _safe_repo_path(source)
        model = _read_yaml(path)
        expected_id = str(entry.get("model_id") or "")
        if str(model.get("model_id") or "") != expected_id:
            raise RepositoryResearchStoreError(
                f"catalog/model ID mismatch: {expected_id} != {model.get('model_id')}"
            )

        contract_destination = contract_root / f"{expected_id}.yaml"
        shutil.copy2(path, contract_destination)
        contract_path = f"docs/models/{contract_destination.name}"
        models.append(_normalize_model(model, source, contract_path))

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
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "repository-catalog.json", catalog)
    _write_json(output_dir / "models.json", models)
    _write_json(output_dir / "reports.json", reports)
    _write_json(output_dir / "arena.json", {"arena_name": "N/A", "leaderboard": []})
    (output_dir / "curves").mkdir(parents=True, exist_ok=True)

    catalog_bytes = catalog_path.read_bytes()
    snapshot_id = hashlib.sha256(catalog_bytes).hexdigest()
    manifest = {
        "generated_at": str(catalog.get("published_at") or ""),
        "evidence_cutoff": max(evidence_cutoffs) if evidence_cutoffs else None,
        "snapshot_id": snapshot_id,
        "release_id": str(catalog.get("release_id") or ""),
        "source": "repository_research_store",
        "catalog_path": "data/repository-catalog.json",
        "market": "all",
        "stats": {"total_models": len(models), "total_reports": len(reports)},
        "warnings": [
            "Only evidence explicitly allow-listed by data/research/catalog.json is published.",
            "Run-level curves, holdings and attribution appear only after immutable "
            "repository run records are promoted.",
        ],
        "blocked_gates": ["run_level_series_not_yet_promoted"],
        "promotion_decision": "research_baselines_published",
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest
