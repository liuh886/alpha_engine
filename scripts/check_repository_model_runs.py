"""Validate published model-to-run bindings in the repository research store."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml


class RepositoryModelRunError(ValueError):
    """Raised when a published model/run bridge is incomplete or inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryModelRunError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise RepositoryModelRunError(f"JSON root must be an object: {path}")
    return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RepositoryModelRunError(f"invalid YAML file: {path}") from exc
    if not isinstance(payload, dict):
        raise RepositoryModelRunError(f"YAML root must be a mapping: {path}")
    return payload


def _safe_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RepositoryModelRunError(f"unsafe repository path: {value}")
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise RepositoryModelRunError(f"path escapes repository: {value}")
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
    if not isinstance(evidence, dict):
        return {}
    for key in ("frozen_challenge", "consumed_reporting_window"):
        value = evidence.get(key)
        if isinstance(value, dict):
            return value
    return {}


def canonical_model_metrics(model: dict[str, Any]) -> dict[str, float]:
    evidence = model.get("backtest_evidence") or {}
    development = evidence.get("development") or {}
    evaluation = _evaluation_window(model)
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
    metrics: dict[str, float] = {}
    for label, (source, key) in aliases.items():
        value = _number(source, key) if isinstance(source, dict) else None
        if value is not None:
            metrics[label] = value
    return metrics


def _assert_metrics_equal(
    expected: dict[str, float],
    actual: dict[str, Any],
    *,
    model_id: str,
) -> None:
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise RepositoryModelRunError(
            f"metric keys differ for {model_id}: missing={missing}, extra={extra}"
        )
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if not isinstance(actual_value, (int, float)) or isinstance(actual_value, bool):
            raise RepositoryModelRunError(f"metric is not numeric for {model_id}: {key}")
        if not math.isclose(float(actual_value), expected_value, rel_tol=0.0, abs_tol=1e-12):
            raise RepositoryModelRunError(
                f"metric mismatch for {model_id}/{key}: {actual_value} != {expected_value}"
            )


def _verify_inventory(run_dir: Path) -> None:
    inventory = _read_json(run_dir / "inventory.json")
    records = inventory.get("files")
    if not isinstance(records, list) or not records:
        raise RepositoryModelRunError(f"empty inventory: {run_dir}")
    declared: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RepositoryModelRunError(f"invalid inventory row: {run_dir}")
        name = str(record.get("path") or "")
        relative = Path(name)
        if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
            raise RepositoryModelRunError(f"unsafe inventory path: {run_dir}/{name}")
        path = run_dir / relative
        if not path.is_file():
            raise RepositoryModelRunError(f"missing inventory file: {path}")
        if path.stat().st_size != int(record.get("byte_size", -1)):
            raise RepositoryModelRunError(f"size mismatch: {path}")
        if _sha256(path) != str(record.get("sha256") or ""):
            raise RepositoryModelRunError(f"hash mismatch: {path}")
        declared.add(name)
    actual = {path.name for path in run_dir.iterdir() if path.is_file()} - {"inventory.json"}
    if actual != declared:
        raise RepositoryModelRunError(
            f"inventory coverage mismatch for {run_dir.name}: "
            f"undeclared={sorted(actual - declared)}, absent={sorted(declared - actual)}"
        )


def validate_repository_model_runs(
    root: Path,
    *,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    catalog_file = (
        catalog_path.resolve()
        if catalog_path is not None
        else root / "data" / "research" / "catalog.json"
    )
    catalog = _read_json(catalog_file)
    if catalog.get("research_only") is not True or catalog.get("trade_ready") is not False:
        raise RepositoryModelRunError("catalog research boundary is invalid")

    models = catalog.get("published_models")
    runs = catalog.get("published_runs")
    if not isinstance(models, list) or not models:
        raise RepositoryModelRunError("catalog publishes no models")
    if not isinstance(runs, list) or not runs:
        raise RepositoryModelRunError("catalog publishes no runs")

    run_entries = {
        str(item.get("run_id")): item
        for item in runs
        if isinstance(item, dict) and item.get("run_id")
    }
    if len(run_entries) != len(runs):
        raise RepositoryModelRunError("published run IDs must be unique and non-empty")

    validated: list[dict[str, Any]] = []
    for entry in models:
        if not isinstance(entry, dict):
            raise RepositoryModelRunError("published model entry must be an object")
        model_id = str(entry.get("model_id") or "")
        primary_run_id = str(entry.get("primary_run_id") or "")
        if not model_id or not primary_run_id:
            raise RepositoryModelRunError(
                f"published model requires model_id and primary_run_id: {entry}"
            )
        run_entry = run_entries.get(primary_run_id)
        if run_entry is None:
            raise RepositoryModelRunError(
                f"primary run is not published for {model_id}: {primary_run_id}"
            )

        model_path = _safe_path(root, str(entry.get("source") or ""))
        run_dir = _safe_path(root, str(run_entry.get("source") or ""))
        if not model_path.is_file() or not run_dir.is_dir():
            raise RepositoryModelRunError(f"missing model/run evidence for {model_id}")

        model = _read_yaml(model_path)
        run = _read_json(run_dir / "run.json")
        metrics = _read_json(run_dir / "metrics.json")
        training_log = _read_json(run_dir / "training_log.json")
        model_record = _read_json(run_dir / "model.json")
        _verify_inventory(run_dir)

        if str(model.get("model_id") or "") != model_id:
            raise RepositoryModelRunError(f"model ID mismatch in {model_path}")
        if str(run.get("run_id") or "") != primary_run_id:
            raise RepositoryModelRunError(f"run ID mismatch in {run_dir}")
        if str(run.get("model_id") or "") != model_id:
            raise RepositoryModelRunError(
                f"primary run/model mismatch: {primary_run_id} != {model_id}"
            )
        if run.get("research_only") is not True or run.get("trade_ready") is not False:
            raise RepositoryModelRunError(f"invalid run boundary: {primary_run_id}")
        if model_record.get("model_id") != model_id:
            raise RepositoryModelRunError(f"model.json mismatch: {primary_run_id}")

        provider = model.get("provider_binding") or {}
        provider_id = str(
            provider.get("canonical_evidence_provider_identity_sha256")
            or provider.get("provider_identity_sha256")
            or ""
        )
        if str(run.get("data_snapshot_id") or "") != f"sha256:{provider_id}":
            raise RepositoryModelRunError(f"provider identity mismatch: {model_id}")

        evidence = model.get("evidence_identity") or {}
        source = run.get("source_artifact") or {}
        for model_key, run_key in (
            ("workflow_run_id", "workflow_run_id"),
            ("artifact_id", "artifact_id"),
            ("artifact_digest", "artifact_digest"),
        ):
            if str(evidence.get(model_key) or "") != str(source.get(run_key) or ""):
                raise RepositoryModelRunError(
                    f"source artifact mismatch for {model_id}: {model_key}"
                )

        _assert_metrics_equal(canonical_model_metrics(model), metrics, model_id=model_id)

        curve_path = run_dir / "equity_curve.json"
        completeness = run.get("evidence_completeness") or {}
        curve_status = (completeness.get("equity_curve") or {}).get("status")
        if curve_path.is_file():
            if curve_status not in {"retained_exact", "generated_exact_from_frozen_snapshot"}:
                raise RepositoryModelRunError(
                    f"curve file exists without exact status: {primary_run_id}"
                )
        elif curve_status != "unavailable_source_artifact_did_not_retain_trace":
            raise RepositoryModelRunError(
                f"missing curve is not explicitly governed: {primary_run_id}"
            )

        if training_log.get("normalization_decision") != (
            "publish_metrics_and_selection_evidence_without_curve"
        ):
            raise RepositoryModelRunError(
                f"historical normalization decision is missing: {primary_run_id}"
            )
        prohibited = set(training_log.get("prohibited_actions") or [])
        required_prohibitions = {
            "do_not_infer_curve_from_half_year_returns",
            "do_not_rerun_against_a_different_provider_snapshot",
            "do_not_restate_snapshot_specific_performance",
        }
        if not required_prohibitions.issubset(prohibited):
            raise RepositoryModelRunError(
                f"historical evidence prohibitions are incomplete: {primary_run_id}"
            )

        validated.append(
            {
                "model_id": model_id,
                "primary_run_id": primary_run_id,
                "curve_status": curve_status,
                "metric_count": len(metrics),
                "source_artifact_id": source.get("artifact_id"),
            }
        )

    return {
        "status": "repository_model_run_bridge_valid",
        "catalog": str(catalog_file.relative_to(root)),
        "models": validated,
        "model_count": len(validated),
        "published_run_count": len(run_entries),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--catalog", type=Path, default=None)
    args = parser.parse_args()
    result = validate_repository_model_runs(args.root, catalog_path=args.catalog)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
