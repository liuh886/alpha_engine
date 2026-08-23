from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from scripts.data.refresh_selected_pool_prices_v2 import (
    MANIFEST_RELATIVE_PATH,
    refresh_selected_pool_prices_v2,
)
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
from src.data.selected_pool_price_publication import (
    PUBLICATION_MANIFEST_NAME,
    SelectedPoolPricePublicationError,
    verify_selected_pool_price_publication_manifest,
    write_selected_pool_price_publication_manifest,
)
from src.data.strategy_data_bundle import (
    STRATEGY_MANIFEST_NAME,
    build_strategy_data_bundle,
    verify_strategy_data_bundle,
)

RECIPE_REGISTRY_PATH = Path("configs/data_recipes/registry_v1.yaml")
ALLOWED_BUILDERS = {"strategy_bundle", "selected_pool_prices"}


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
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_recipe_registry(root: str | Path = Path.cwd()) -> dict[str, dict[str, str]]:
    """Load the versioned recipe registry and reject undeclared builders."""

    normalized_root = Path(root).resolve()
    path = (normalized_root / RECIPE_REGISTRY_PATH).resolve()
    if not path.is_file():
        raise DataRecipeError(f"data recipe registry is missing: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DataRecipeError("data recipe registry must be a mapping")
    if payload.get("trade_ready") is not False:
        raise DataRecipeError("data recipe registry violates trade-ready boundary")
    declared_builders = {
        str(value).strip() for value in payload.get("allowed_builders", []) if str(value).strip()
    }
    if not declared_builders or not declared_builders.issubset(ALLOWED_BUILDERS):
        raise DataRecipeError(
            f"unsupported recipe builders: {sorted(declared_builders - ALLOWED_BUILDERS)}"
        )
    raw = payload.get("recipes", {})
    if not isinstance(raw, dict) or not raw:
        raise DataRecipeError("data recipe registry has no recipes")
    recipes: dict[str, dict[str, str]] = {}
    for recipe_id, entry in raw.items():
        if not isinstance(entry, dict):
            raise DataRecipeError(f"recipe registry entry must be a mapping: {recipe_id}")
        path_value = str(entry.get("path", "")).strip()
        builder = str(entry.get("builder", "")).strip()
        if not path_value or builder not in declared_builders:
            raise DataRecipeError(f"invalid recipe registry entry: {recipe_id}")
        recipes[str(recipe_id)] = {"path": path_value, "builder": builder}
    return recipes


def data_recipe_catalog(root: str | Path = Path.cwd()) -> dict[str, Any]:
    """Return discoverable recipe and research-command identities."""

    normalized_root = Path(root).resolve()
    rows: list[dict[str, Any]] = []
    commands: dict[str, list[str]] = {}
    for recipe_id in sorted(load_recipe_registry(normalized_root)):
        _, recipe = _load_recipe(normalized_root, recipe_id)
        research = recipe.get("research_commands", {})
        command_ids = sorted(research) if isinstance(research, dict) else []
        rows.append(
            {
                "recipe_id": recipe_id,
                "builder": recipe["builder"],
                "description": recipe.get("description"),
                "research_commands": command_ids,
            }
        )
        commands[recipe_id] = command_ids
    return {
        "schema_version": "1.0",
        "recipes": rows,
        "research_commands": commands,
        "research_only": True,
        "trade_ready": False,
    }


def _load_recipe(root: Path, recipe_id: str) -> tuple[Path, dict[str, Any]]:
    registry = load_recipe_registry(root)
    entry = registry.get(recipe_id)
    if entry is None:
        raise DataRecipeError(f"unknown data recipe: {recipe_id}")
    path = _resolve(root, entry["path"])
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
    builder = str(payload.get("builder") or entry["builder"]).strip()
    if builder != entry["builder"] or builder not in ALLOWED_BUILDERS:
        raise DataRecipeError(
            f"data recipe builder mismatch: registry={entry['builder']}, recipe={builder}"
        )
    if payload.get("trade_ready") is not False:
        raise DataRecipeError("data recipe violates trade-ready boundary")
    payload["builder"] = builder
    return path, payload


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


def _verify_model_profile(
    *,
    model_root: Path,
    profile_id: str,
    candidate_pool_id: str,
    requested_cutoff: str,
) -> dict[str, Any]:
    verify_model_data_bundle(model_root)
    return check_profile(
        model_root,
        profile_id,
        expected_pool_id=candidate_pool_id,
        maximum_evidence_cutoff=requested_cutoff,
    )


def _verify_cache(
    *,
    pointer: Mapping[str, Any],
    recipe_sha256: str,
    requested_cutoff: str,
    recipe: Mapping[str, Any],
) -> dict[str, Any] | None:
    if pointer.get("recipe_sha256") != recipe_sha256:
        return None
    if pointer.get("requested_cutoff") != requested_cutoff:
        return None
    if pointer.get("builder") != recipe.get("builder"):
        return None

    model_data = recipe.get("model_data", {})
    if not isinstance(model_data, dict):
        return None
    model_root = Path(str(pointer.get("model_data_bundle_root", "")))
    model_manifest = model_root / "model-data-bundle.json"
    if not model_manifest.is_file():
        return None
    if _sha256(model_manifest) != pointer.get("model_manifest_sha256"):
        return None

    product_manifest = Path(str(pointer.get("product_manifest_path", "")))
    if not product_manifest.is_file():
        return None
    if _sha256(product_manifest) != pointer.get("product_manifest_sha256"):
        return None

    try:
        if recipe.get("builder") == "strategy_bundle":
            verify_strategy_data_bundle(product_manifest.parent)
        elif recipe.get("builder") == "selected_pool_prices":
            payload = _read_json(product_manifest)
            if not payload or payload.get("promotion_eligible") is not True:
                return None
        else:
            return None
        gate = _verify_model_profile(
            model_root=model_root,
            profile_id=str(model_data["profile_id"]),
            candidate_pool_id=str(model_data["candidate_pool_id"]),
            requested_cutoff=requested_cutoff,
        )
    except (ValueError, ModelDataBundleError):
        return None
    return {**dict(pointer), "status": "reused", "profile_gate": gate}


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


def _strategy_symbol_contract(
    recipe: Mapping[str, Any],
) -> tuple[list[str], dict[str, str]]:
    symbols = recipe.get("symbols", {})
    if not isinstance(symbols, dict):
        raise DataRecipeError("strategy recipe symbols must be a mapping")
    supplemental: list[str] = []
    roles: dict[str, str] = {}
    declared = symbols.get("supplemental")
    if isinstance(declared, dict):
        for symbol, role in declared.items():
            normalized_symbol = str(symbol).strip().upper()
            normalized_role = str(role).strip()
            if not normalized_symbol or normalized_role not in {
                "tradable",
                "signal_reference",
            }:
                raise DataRecipeError(f"invalid supplemental symbol role: {symbol}={role}")
            supplemental.append(normalized_symbol)
            roles[normalized_symbol] = normalized_role
    else:
        for symbol in symbols.get("signal_references", []):
            normalized_symbol = str(symbol).strip().upper()
            if normalized_symbol:
                supplemental.append(normalized_symbol)
                roles[normalized_symbol] = "signal_reference"
    return supplemental, roles


def _build_strategy_recipe(
    *,
    normalized_root: Path,
    recipe: Mapping[str, Any],
    requested_cutoff: str,
    source_etf_bundle: str | Path | None,
    primary_adapter: MarketDataAdapter | None,
    fallback_adapter: MarketDataAdapter | None,
    reference_adapter: MarketDataAdapter | None,
) -> tuple[Path, Path]:
    source_products = recipe.get("source_products", {})
    model_data = recipe.get("model_data", {})
    if not isinstance(source_products, dict) or not isinstance(model_data, dict):
        raise DataRecipeError("data recipe source_products and model_data are required")

    etf_root = (
        Path(source_etf_bundle).resolve()
        if source_etf_bundle is not None
        else _resolve(normalized_root, source_products["etf_bundle_root"])
    )
    if source_etf_bundle is None and not _can_reuse_etf_bundle(etf_root, requested_cutoff):
        build_etf_reference_bundle(
            contract_path=_resolve(normalized_root, source_products["etf_contract"]),
            output_root=etf_root,
            end=requested_cutoff,
            primary_adapter=primary_adapter,
            fallback_adapter=fallback_adapter,
        )
    load_etf_reference_bundle(etf_root, require_strategy_ready=True)

    supplemental, roles = _strategy_symbol_contract(recipe)
    strategy_root = _resolve(normalized_root, source_products["strategy_bundle_root"])
    manifest = build_strategy_data_bundle(
        etf_bundle_root=etf_root,
        output_root=strategy_root,
        start=str(recipe.get("history", {}).get("requested_start", "2010-01-01")),
        end=requested_cutoff,
        component_id=str(model_data["component_id"]),
        pool_id=str(model_data["candidate_pool_id"]),
        reference_adapter=reference_adapter,
        supplemental_symbols=supplemental,
        supplemental_roles=roles,
        bundle_id=str(
            recipe.get("bundle_id")
            or f"{str(recipe['recipe_id']).replace('-', '_')}_strategy_data_v1"
        ),
    )
    if manifest.get("status") != "ready":
        raise DataRecipeError(
            f"strategy data bundle is blocked: missing={manifest.get('missing_symbols', [])}"
        )
    return strategy_root / STRATEGY_MANIFEST_NAME, strategy_root


def _build_selected_pool_recipe(
    *,
    normalized_root: Path,
    recipe: Mapping[str, Any],
    requested_cutoff: str,
    refresh: bool,
    selected_pool_refresher: Callable[..., Mapping[str, Any]] | None,
) -> tuple[Path, Path]:
    source_products = recipe.get("source_products", {})
    build = recipe.get("selected_pool_refresh", {})
    if not isinstance(source_products, dict) or not isinstance(build, dict):
        raise DataRecipeError("selected-pool recipe configuration is incomplete")
    output_root = _resolve(normalized_root, source_products["output_root"])
    manifest_path = output_root / MANIFEST_RELATIVE_PATH
    publication_path = output_root / "artifacts" / PUBLICATION_MANIFEST_NAME

    def product_manifest(payload: Mapping[str, Any]) -> Path:
        try:
            if not publication_path.is_file():
                write_selected_pool_price_publication_manifest(publication_path, payload)
            verify_selected_pool_price_publication_manifest(publication_path, payload)
        except SelectedPoolPricePublicationError as exc:
            raise DataRecipeError(str(exc)) from exc
        return publication_path

    if not refresh:
        cached = _read_json(manifest_path)
        if (
            cached
            and cached.get("promotion_eligible") is True
            and str(
                cached.get("evidence_cutoff")
                or cached.get("cutoff")
                or cached.get("requested_cutoff")
                or ""
            )[:10]
            == requested_cutoff
        ):
            provider_root = output_root / str(source_products["provider_relative_path"])
            return product_manifest(cached), provider_root

    refresher = selected_pool_refresher or refresh_selected_pool_prices_v2
    refresher(
        root=normalized_root,
        market=str(build["market"]),
        source_csv_dir=_resolve(normalized_root, build["source_csv_dir"]),
        output_root=output_root,
        start=str(build.get("start", "2021-01-01")),
        cutoff=requested_cutoff,
        max_rounds=int(build.get("max_rounds", 2)),
        full_refresh=bool(build.get("full_refresh", True)),
    )
    payload = _read_json(manifest_path)
    if not payload or payload.get("promotion_eligible") is not True:
        raise DataRecipeError(
            "selected-pool provider is blocked: "
            f"{(payload or {}).get('promotion_blocker', 'manifest missing')}"
        )
    provider_root = output_root / str(source_products["provider_relative_path"])
    if not provider_root.is_dir():
        raise DataRecipeError(f"selected-pool provider is missing: {provider_root}")
    return product_manifest(payload), provider_root


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
    selected_pool_refresher: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build or reuse one fully governed researcher-facing data product."""

    normalized_root = Path(root).resolve()
    recipe_path, recipe = _load_recipe(normalized_root, recipe_id)
    requested_cutoff = _effective_cutoff(recipe, cutoff)
    recipe_hash = _sha256(recipe_path)
    pointer_path = _cache_pointer_path(normalized_root, recipe)
    if not refresh:
        cached = _read_json(pointer_path)
        if cached:
            verified = _verify_cache(
                pointer=cached,
                recipe_sha256=recipe_hash,
                requested_cutoff=requested_cutoff,
                recipe=recipe,
            )
            if verified is not None:
                return verified

    if recipe["builder"] == "strategy_bundle":
        product_manifest, product_root = _build_strategy_recipe(
            normalized_root=normalized_root,
            recipe=recipe,
            requested_cutoff=requested_cutoff,
            source_etf_bundle=source_etf_bundle,
            primary_adapter=primary_adapter,
            fallback_adapter=fallback_adapter,
            reference_adapter=reference_adapter,
        )
        strategy_bundle_root: str | None = str(product_root)
        selected_pool_provider_root: str | None = None
    elif recipe["builder"] == "selected_pool_prices":
        product_manifest, product_root = _build_selected_pool_recipe(
            normalized_root=normalized_root,
            recipe=recipe,
            requested_cutoff=requested_cutoff,
            refresh=refresh,
            selected_pool_refresher=selected_pool_refresher,
        )
        strategy_bundle_root = None
        selected_pool_provider_root = str(product_root)
    else:
        raise DataRecipeError(f"unsupported data recipe builder: {recipe['builder']}")

    source_products = recipe["source_products"]
    model_data = recipe["model_data"]
    model_root = _resolve(normalized_root, source_products["model_data_bundle_root"])
    frontend_dir = _resolve(normalized_root, source_products["frontend_data_dir"])
    build_model_data_bundle(
        root=normalized_root,
        contract_path=_resolve(normalized_root, model_data["contract"]),
        component_specs=[
            ComponentSpec(
                component_id=str(model_data["component_id"]),
                component_kind=str(model_data["component_kind"]),
                manifest_path=product_manifest,
                market=str(model_data.get("market", recipe.get("market", "us"))),
            )
        ],
        output_root=model_root,
        evidence_cutoff=requested_cutoff,
        frontend_data_dir=frontend_dir,
    )
    profile_gate = _verify_model_profile(
        model_root=model_root,
        profile_id=str(model_data["profile_id"]),
        candidate_pool_id=str(model_data["candidate_pool_id"]),
        requested_cutoff=requested_cutoff,
    )
    gate_path = model_root / f"{recipe_id}-profile-gate.json"
    _write_json(gate_path, profile_gate)

    model_manifest_path = model_root / "model-data-bundle.json"
    pointer = {
        "schema_version": "1.0",
        "recipe_id": recipe_id,
        "builder": recipe["builder"],
        "recipe_path": str(recipe_path),
        "recipe_sha256": recipe_hash,
        "requested_cutoff": requested_cutoff,
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "built",
        "product_manifest_path": str(product_manifest),
        "product_manifest_sha256": _sha256(product_manifest),
        "strategy_bundle_root": strategy_bundle_root,
        "selected_pool_provider_root": selected_pool_provider_root,
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
    verified = _verify_cache(
        pointer=pointer,
        recipe_sha256=_sha256(recipe_path),
        requested_cutoff=requested_cutoff,
        recipe=recipe,
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
        raise DataRecipeError(
            f"research command {command_id!r} is not declared by recipe {recipe_id!r}"
        )
    runner = _resolve(normalized_root, command["runner"])
    if not runner.is_file():
        raise DataRecipeError(f"research runner is missing: {runner}")
    args_spec = command.get("runner_arguments", {})
    if not isinstance(args_spec, dict):
        raise DataRecipeError("runner_arguments must be a mapping")
    data_flag = str(args_spec.get("data_bundle_flag", "--etf-data-bundle"))
    output_flag = str(args_spec.get("output_flag", "--output-dir"))
    cutoff_flag = str(args_spec.get("cutoff_flag", "--end-date"))
    bundle_root = prepared.get("strategy_bundle_root")
    if not bundle_root:
        raise DataRecipeError(f"research command requires a strategy bundle: recipe={recipe_id}")
    args = [
        sys.executable,
        str(runner),
        data_flag,
        str(bundle_root),
        output_flag,
        str(_resolve(normalized_root, command["output_dir"])),
    ]
    strategy_run_dir = command.get("strategy_run_dir")
    if strategy_run_dir:
        args.extend(
            [
                str(args_spec.get("strategy_run_dir_flag", "--strategy-run-dir")),
                str(_resolve(normalized_root, strategy_run_dir)),
            ]
        )
    if prepared.get("requested_cutoff") and cutoff_flag:
        args.extend([cutoff_flag, str(prepared["requested_cutoff"])])
    completed = subprocess.run(args, cwd=normalized_root, check=False)
    if completed.returncode != 0:
        raise DataRecipeError(f"research command failed: {command_id}; exit={completed.returncode}")
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
