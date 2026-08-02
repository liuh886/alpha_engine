from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

RUN_SCHEMA_VERSION = "1.0.0"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_FILES = ("run.json", "metrics.json")
OPTIONAL_FILES = (
    "equity_curve.json",
    "attribution.json",
    "training_log.json",
    "model.json",
    "holdings.parquet",
    "predictions.parquet",
    "model.pkl",
    "model.bin",
    "model.joblib",
    "model.onnx",
)
ALLOWED_FILES = frozenset((*REQUIRED_FILES, *OPTIONAL_FILES))
RUN_TYPES = frozenset({"training", "backtest", "training_backtest"})


class RepositoryRunStoreError(ValueError):
    """Raised when a local run cannot become durable repository evidence."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryRunStoreError(f"invalid JSON file: {path}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_files(source: Path) -> list[Path]:
    if not source.is_dir():
        raise RepositoryRunStoreError(f"run source is not a directory: {source}")
    files: list[Path] = []
    for item in sorted(source.iterdir(), key=lambda value: value.name):
        if item.is_symlink():
            raise RepositoryRunStoreError(f"run source may not contain symlinks: {item.name}")
        if item.is_dir():
            raise RepositoryRunStoreError(
                f"run source v1 accepts top-level files only: {item.name}"
            )
        if item.name not in ALLOWED_FILES:
            raise RepositoryRunStoreError(f"unsupported run artifact: {item.name}")
        files.append(item)
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise RepositoryRunStoreError(
            f"run source is missing required files: {', '.join(missing)}"
        )
    return files


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RepositoryRunStoreError(f"run.json requires non-empty string: {key}")
    return value.strip()


def _validate_run(source: Path) -> tuple[dict[str, Any], dict[str, Any], list[Path]]:
    files = _validate_source_files(source)
    run = _read_json(source / "run.json")
    metrics = _read_json(source / "metrics.json")
    if not isinstance(run, dict):
        raise RepositoryRunStoreError("run.json root must be an object")
    if not isinstance(metrics, dict) or not metrics:
        raise RepositoryRunStoreError("metrics.json root must be a non-empty object")

    schema = _required_text(run, "schema_version")
    if schema.split(".")[0] != RUN_SCHEMA_VERSION.split(".")[0]:
        raise RepositoryRunStoreError(f"unsupported run schema version: {schema}")
    run_id = _required_text(run, "run_id")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise RepositoryRunStoreError(f"invalid run_id: {run_id}")
    _required_text(run, "model_id")
    run_type = _required_text(run, "run_type")
    if run_type not in RUN_TYPES:
        raise RepositoryRunStoreError(f"unsupported run_type: {run_type}")
    for key in (
        "market",
        "benchmark",
        "universe_id",
        "data_snapshot_id",
        "generated_at",
    ):
        _required_text(run, key)
    for key in ("windows", "effective_parameters", "costs"):
        if not isinstance(run.get(key), dict) or not run[key]:
            raise RepositoryRunStoreError(f"run.json requires non-empty object: {key}")
    if run.get("research_only") is not True or run.get("trade_ready") is not False:
        raise RepositoryRunStoreError(
            "run boundary must be research_only=true and trade_ready=false"
        )

    curve_path = source / "equity_curve.json"
    if curve_path.is_file():
        curve = _read_json(curve_path)
        if isinstance(curve, dict):
            if str(curve.get("run_id") or "") != run_id:
                raise RepositoryRunStoreError("equity_curve.json run_id does not match run.json")
            points = curve.get("points")
        else:
            points = curve
        if not isinstance(points, list) or not points:
            raise RepositoryRunStoreError("equity_curve.json requires a non-empty points list")

    return run, metrics, files


def _inventory(files: list[Path]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "files": [
            {
                "path": path.name,
                "byte_size": path.stat().st_size,
                "sha256": _sha256(path),
                "storage": (
                    "git_lfs"
                    if path.suffix.lower() in {".parquet", ".pkl", ".bin", ".joblib", ".onnx"}
                    else "git"
                ),
            }
            for path in files
        ],
    }


def _same_inventory(destination: Path, inventory: dict[str, Any]) -> bool:
    existing_path = destination / "inventory.json"
    if not existing_path.is_file():
        return False
    existing = _read_json(existing_path)
    return existing == inventory


def _update_catalog(
    catalog_path: Path,
    *,
    run: dict[str, Any],
    set_primary: bool,
) -> None:
    catalog = _read_json(catalog_path)
    if not isinstance(catalog, dict):
        raise RepositoryRunStoreError("repository catalog root must be an object")
    if catalog.get("research_only") is not True or catalog.get("trade_ready") is not False:
        raise RepositoryRunStoreError("repository catalog has an invalid research boundary")

    run_id = str(run["run_id"])
    source = f"data/research/runs/{run_id}"
    published_runs = catalog.setdefault("published_runs", [])
    if not isinstance(published_runs, list):
        raise RepositoryRunStoreError("catalog published_runs must be a list")
    current = {str(item.get("run_id")): item for item in published_runs if isinstance(item, dict)}
    current[run_id] = {"run_id": run_id, "source": source}
    catalog["published_runs"] = [current[key] for key in sorted(current)]

    if set_primary:
        model_id = str(run["model_id"])
        models = catalog.get("published_models")
        if not isinstance(models, list):
            raise RepositoryRunStoreError("catalog published_models must be a list")
        matched = False
        for item in models:
            if isinstance(item, dict) and item.get("model_id") == model_id:
                item["primary_run_id"] = run_id
                matched = True
        if not matched:
            raise RepositoryRunStoreError(
                f"cannot set primary run for unpublished model: {model_id}"
            )

    catalog["published_at"] = str(run["generated_at"])
    _write_json(catalog_path, catalog)


def import_local_run(
    source: Path,
    *,
    root: Path,
    publish: bool = False,
    set_primary: bool = False,
) -> dict[str, Any]:
    """Validate and copy a local run into immutable Git-tracked repository data."""

    if set_primary and not publish:
        raise RepositoryRunStoreError("--set-primary requires --publish")
    source = source.resolve()
    root = root.resolve()
    run, metrics, files = _validate_run(source)
    run_id = str(run["run_id"])
    destination_root = root / "data" / "research" / "runs"
    destination = destination_root / run_id
    inventory = _inventory(files)

    if destination.exists():
        if not destination.is_dir() or not _same_inventory(destination, inventory):
            raise RepositoryRunStoreError(
                f"run_id already exists with different evidence: {run_id}"
            )
        status = "already_present"
    else:
        destination_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{run_id}-", dir=destination_root) as temp:
            staged = Path(temp)
            for path in files:
                shutil.copy2(path, staged / path.name)
            _write_json(staged / "inventory.json", inventory)
            staged.rename(destination)
        status = "imported"

    if publish:
        _update_catalog(
            root / "data" / "research" / "catalog.json",
            run=run,
            set_primary=set_primary,
        )

    return {
        "status": status,
        "run_id": run_id,
        "model_id": str(run["model_id"]),
        "destination": str(destination.relative_to(root).as_posix()),
        "file_count": len(files),
        "metrics_count": len(metrics),
        "published": publish,
        "primary_for_model": set_primary,
        "research_only": True,
        "trade_ready": False,
    }
