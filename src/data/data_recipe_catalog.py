"""Read recipe identities without loading market providers or model executors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

RECIPE_REGISTRY_PATH = Path("configs/data_recipes/registry_v1.yaml")
ALLOWED_BUILDERS = {"strategy_bundle", "selected_pool_prices"}


class DataRecipeError(ValueError):
    """Raised when a researcher-facing data recipe cannot pass its contracts."""


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
    value = Path(entry["path"])
    path = value if value.is_absolute() else root / value
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


