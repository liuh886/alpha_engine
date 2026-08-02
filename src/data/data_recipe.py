from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.data.adapters.base import MarketDataAdapter
from src.data.etf_reference_bundle import (
    build_etf_reference_bundle,
    load_etf_reference_bundle,
)
from src.data.model_data_bundle import (
    ComponentSpec,
    ModelDataBundleError,
    build_model_data_bundle,
    verify_model_data_bundle,
)
from src.data.model_data_profile import check_profile
from src.data.strategy_data_bundle import (
    STRATEGY_MANIFEST_NAME,
    build_strategy_data_bundle,
    verify_strategy_data_bundle,
)

RECIPE_FILES = {
    "qqq-rotation": Path("configs/data_recipes/qqq_rotation_v1.yaml"),
}


class DataRecipeError(ValueError):
    """Raised when a researcher-facing data recipe cannot pass its contracts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _load_recipe(root: Path, recipe_id: str) -> tuple[Path, dict[str, Any]]:
    relative = RECIPE_FILES.get(recipe_id)
    if relative is None:
        raise DataRecipeError(f"unknown data recipe: {recipe_id}")
    path = (root / relative).resolve()
    if not path.is_file():
        raise DataRecipeError(f"data recipe is missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DataRecipeError("data recipe must be a mapping")
    if str(payload.get("recipe_id", "")) != recipe_id:
        raise DataRecipeError(
            f"data recipe identity mismatch: expected={recipe_id}, "
            f"observed={payload.get('recipe_id')}"
        )
    if payload.get("trade_ready") is not False:
        raise DataRecipeError("data recipe violates trade-ready boundary")
    return path, payload


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _effective_cutoff(recipe: Mapping[str, Any], cutoff: str | None) -> str:
    value = str(cutoff or recipe.get("history", {}).get("default_cutoff") or "").strip()
    if not value:
        value = datetime.now(timezone.utc).date().isoformat()
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise DataRecipeError(f"invalid cutoff: {value}") from exc


def _cache_pointer_path(root: Path, recipe: Mapping[str, Any]) -> Path:
    return _resolve(root, recipe.get("cache", {}).get("pointer"))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _verify_cache(
    *,
    pointer: Mapping[str, Any],
    recipe_sha256: str,
    requested_cutoff: str,
    profile_id: str,
    candidate_pool_id: str,
) -> dict[str, Any] | None:
    if pointer.get("recipe_sha256") != recipe_sha256:
        return None
    if pointer.get("requested_cutoff") != requested_cutoff:
        return None
    strategy_root = Path(str(pointer.get("strategy_bundle_root", "")))
    model_root = Path(str(pointer.get("model_data_bundle_root", "")))
    strategy_manifest = strategy_root / STRATEGY_MANIFEST_NAME
    model_manifest = model_root / "model-data-bundle.json"
    if not strategy_manifest.is_file() or not model_manifest.is_file():
        return None
    if _sha256(strategy_manifest) != pointer.get("strategy_manifest_sha256"):
        return None
    if _sha256(model_manifest) != pointer.get("model_manifest_sha256"):
        return None
    try:
        verify_strategy_data_bundle(strategy_root)
        verify_model_data_bundle(model_root)
        gate = check_profile(
            model_root,
            profile_id,
            expected_pool_id=candidate_pool_id,
            maximum_evidence_cutoff=requested_cutoff,
        )
    except (ValueError, ModelDataBundleError):
        return None
    return {
        **dict(pointer),
        "status": "reused",
        "profile_gate": gate,
    }


def _can_reuse_etf_bundle(path: Path, cutoff: str) -> bool:
    manifest_path = path / "bundle_manifest.json"
    manifest = _read_json(manifest_path)
    if not manifest or manifest.get("strategy_data_ready") is not True:
        return False
    if str(manifest.get("requested_end") or "") != cutoff:
        return False
    try:
        load_etf_reference_bundle(path, require_strategy_ready=True)
    except Exception:
        return False
    return True


def prepare_data_recipe(
    recipe_id: str,
    *,
    root: str | Path = Path.cwd(),
    cutoff: str | None = None,
    refresh: bool = False,
    source_etf_bundle: str | Path | None = None,
    primary_adapter: MarketDataAdapter | None = None,
    fallback_adapter: MarketDataAdapter | None = None,
    reference_adapter: MarketDataAdapter | None = None,
) -> dict[str, Any]:
    """Build or reuse one fully governed researcher-facing data product."""

    normalized_root = Path(root).resolve()
    recipe_path, recipe = _load_recipe(normalized_root, recipe_id)
    requested_cutoff = _effective_cutoff(recipe, cutoff)
    recipe_hash = _sha256(recipe_path)
    source_products = recipe.get("source_products", {})
    model_data = recipe.get("model_data", {})
    if not isinstance(source_products, dict) or not isinstance(model_data, dict):
        raise DataRecipeError("data recipe source_products and model_data are required")

    pointer_path = _cache_pointer_path(normalized_root, recipe)
    if not refresh:
        cached = _read_json(pointer_path)
        if cached:
            verified = _verify_cache(
                pointer=cached,
                recipe_sha256=recipe_hash,
                requested_cutoff=requested_cutoff,
                profile_id=str(model_data["profile_id"]),
                candidate_pool_id=str(model_data["candidate_pool_id"]),
            )
            if verified is not None:
                return verified

    etf_root = (
        Path(source_etf_bundle).resolve()
        if source_etf_bundle is not None
        else _resolve(normalized_root, source_products["etf_bundle_root"])
    )
    if source_etf_bundle is None and (
        refresh or not _can_reuse_etf_bundle(etf_root, requested_cutoff)
    ):
        build_etf_reference_bundle(
            contract_path=_resolve(normalized_root, source_products["etf_contract"]),
            output_root=etf_root,
            end=requested_cutoff,
            primary_adapter=primary_adapter,
            fallback_adapter=fallback_adapter,
        )
    load_etf_reference_bundle(etf_root, require_strategy_ready=True)

    strategy_root = _resolve(
        normalized_root, source_products["strategy_bundle_root"]
    )
    strategy_manifest = build_strategy_data_bundle(
        etf_bundle_root=etf_root,
        output_root=strategy_root,
        start=str(recipe.get("history", {}).get("requested_start", "2010-01-01")),
        end=requested_cutoff,
        component_id=str(model_data["component_id"]),
        pool_id=str(model_data["candidate_pool_id"]),
        reference_adapter=reference_adapter,
    )
    if strategy_manifest.get("status") != "ready":
        raise DataRecipeError(
            "strategy data bundle is blocked: "
            f"missing={strategy_manifest.get('missing_symbols', [])}"
        )

    model_root = _resolve(
        normalized_root, source_products["model_data_bundle_root"]
    )
    frontend_dir = _resolve(
        normalized_root, source_products["frontend_data_dir"]
    )
    strategy_manifest_path = strategy_root / STRATEGY_MANIFEST_NAME
    build_model_data_bundle(
        root=normalized_root,
        contract_path=_resolve(normalized_root, model_data["contract"]),
        component_specs=[
            ComponentSpec(
                component_id=str(model_data["component_id"]),
                component_kind=str(model_data["component_kind"]),
                manifest_path=strategy_manifest_path,
                market="us",
            )
        ],
        output_root=model_root,
        evidence_cutoff=requested_cutoff,
        frontend_data_dir=frontend_dir,
    )
    profile_gate = check_profile(
        model_root,
        str(model_data["profile_id"]),
        expected_pool_id=str(model_data["candidate_pool_id"]),
        maximum_evidence_cutoff=requested_cutoff,
    )
    gate_path = model_root / "qqq-rotation-profile-gate.json"
    _write_json(gate_path, profile_gate)

    model_manifest_path = model_root / "model-data-bundle.json"
    pointer = {
        "schema_version": "1.0",
        "recipe_id": recipe_id,
        "recipe_path": str(recipe_path),
        "recipe_sha256": recipe_hash,
        "requested_cutoff": requested_cutoff,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "built",
        "etf_bundle_root": str(etf_root),
        "strategy_bundle_root": str(strategy_root),
        "strategy_manifest_sha256": _sha256(strategy_manifest_path),
        "model_data_bundle_root": str(model_root),
        "model_manifest_sha256": _sha256(model_manifest_path),
        "profile_gate": profile_gate,
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(pointer_path, pointer)
    return pointer


def data_recipe_status(
    recipe_id: str,
    *,
    root: str | Path = Path.cwd(),
    cutoff: str | None = None,
) -> dict[str, Any]:
    normalized_root = Path(root).resolve()
    recipe_path, recipe = _load_recipe(normalized_root, recipe_id)
    requested_cutoff = _effective_cutoff(recipe, cutoff)
    pointer = _read_json(_cache_pointer_path(normalized_root, recipe))
    if pointer is None:
        return {
            "recipe_id": recipe_id,
            "status": "not_prepared",
            "requested_cutoff": requested_cutoff,
            "research_only": True,
            "trade_ready": False,
        }
    model_data = recipe["model_data"]
    verified = _verify_cache(
        pointer=pointer,
        recipe_sha256=_sha256(recipe_path),
        requested_cutoff=requested_cutoff,
        profile_id=str(model_data["profile_id"]),
        candidate_pool_id=str(model_data["candidate_pool_id"]),
    )
    if verified is None:
        return {
            "recipe_id": recipe_id,
            "status": "stale_or_blocked",
            "requested_cutoff": requested_cutoff,
            "cache_pointer": str(_cache_pointer_path(normalized_root, recipe)),
            "research_only": True,
            "trade_ready": False,
        }
    return verified


def run_research_recipe(
    command_id: str,
    *,
    recipe_id: str = "qqq-rotation",
    root: str | Path = Path.cwd(),
    cutoff: str | None = None,
    refresh: bool = False,
    source_etf_bundle: str | Path | None = None,
) -> dict[str, Any]:
    normalized_root = Path(root).resolve()
    _, recipe = _load_recipe(normalized_root, recipe_id)
    prepared = prepare_data_recipe(
        recipe_id,
        root=normalized_root,
        cutoff=cutoff,
        refresh=refresh,
        source_etf_bundle=source_etf_bundle,
    )
    commands = recipe.get("research_commands", {})
    command = commands.get(command_id) if isinstance(commands, dict) else None
    if not isinstance(command, dict):
        raise DataRecipeError(f"unknown research command: {command_id}")
    runner = _resolve(normalized_root, command["runner"])
    if not runner.is_file():
        raise DataRecipeError(f"research runner is missing: {runner}")

    args = [
        sys.executable,
        str(runner),
        "--etf-data-bundle",
        str(prepared["strategy_bundle_root"]),
        "--output-dir",
        str(_resolve(normalized_root, command["output_dir"])),
        "--strategy-run-dir",
        str(_resolve(normalized_root, command["strategy_run_dir"])),
    ]
    if prepared.get("requested_cutoff"):
        args.extend(["--end-date", str(prepared["requested_cutoff"])])
    completed = subprocess.run(
        args,
        cwd=normalized_root,
        check=False,
    )
    if completed.returncode != 0:
        raise DataRecipeError(
            f"research command failed: {command_id}; exit={completed.returncode}"
        )
    return {
        "recipe_id": recipe_id,
        "command_id": command_id,
        "status": "completed",
        "requested_cutoff": prepared.get("requested_cutoff"),
        "strategy_bundle_root": prepared.get("strategy_bundle_root"),
        "model_data_bundle_root": prepared.get("model_data_bundle_root"),
        "profile_gate": prepared.get("profile_gate"),
        "research_only": True,
        "trade_ready": False,
    }
