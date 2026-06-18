import yaml
from fastapi import APIRouter, HTTPException

from src.common.paths import CONFIG_DIR
from src.assistant.services.strategy_compiler_service import StrategyCompilerService
from src.strategies.registry import StrategyRegistry

router = APIRouter(tags=["strategy"])


@router.post("/compile")
def compile_strategy_from_nl(payload: dict):
    """
    Compile natural language strategy description into Qlib workflow YAML.
    Body: { "text": "Strategy description...", "market": "us|cn" (optional) }
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="missing 'text' field")

    market = payload.get("market")

    from pathlib import Path

    project_root = Path(__file__).resolve().parents[2]
    service = StrategyCompilerService(project_root=project_root)
    result = service.compile_from_nl(text=text, market=market)
    return {"ok": True, **result}


@router.get("/list")
def list_strategies():
    files = list(CONFIG_DIR.glob("*.yaml")) + list(CONFIG_DIR.glob("*.json"))
    return {"ok": True, "files": [f.name for f in files]}


@router.get("/content/{filename}")
def get_strategy_content(filename: str):
    cfg_path = CONFIG_DIR / filename
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    content = cfg_path.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "filename": filename, "content": content}


@router.post("/save")
def save_strategy(payload: dict):
    filename = str(payload.get("filename") or "").strip()
    content = str(payload.get("content") or "")
    if not filename:
        raise HTTPException(status_code=400, detail="missing filename")

    # Validation: Ensure it's valid YAML before saving
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"Invalid YAML syntax: {str(e)}")

    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=403, detail="invalid filename")

    cfg_path = CONFIG_DIR / filename
    try:
        cfg_path.write_text(content, encoding="utf-8")
        return {"ok": True, "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compile-with-factors")
def compile_with_factors(payload: dict):
    """Compile a strategy config with registered Active factors.

    Body::

        {
            "base_config": "us_lgbm_workflow.yaml",  // optional
            "market": "us",                           // optional
            "merge_mode": "append"                    // "append" or "replace"
        }
    """
    base_config = payload.get("base_config", "us_lgbm_workflow.yaml")
    market = payload.get("market", "us")
    merge_mode = payload.get("merge_mode", "append")

    try:
        from src.research.factor_compiler import compile_factors_to_config

        result = compile_factors_to_config(
            base_config_path=base_config,
            market=market,
            merge_mode=merge_mode,
        )
        return {"ok": True, **result.to_dict()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plugins")
def list_strategy_plugins():
    """List all registered strategy plugins with metadata."""
    registry = StrategyRegistry.get_instance()
    plugins = registry.list_strategies()
    return {"ok": True, "plugins": [p.to_dict() for p in plugins]}


@router.get("/plugins/{name}/schema")
def get_plugin_schema(name: str):
    """Return JSON Schema for a plugin's parameters."""
    registry = StrategyRegistry.get_instance()
    plugin = registry.get(name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    return {"ok": True, "name": name, "schema": plugin.param_schema}


@router.post("/plugins/{name}/validate")
def validate_plugin_params(name: str, payload: dict):
    """Validate parameters against a plugin's JSON Schema."""
    registry = StrategyRegistry.get_instance()
    plugin = registry.get(name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

    schema = plugin.param_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    errors: list[str] = []

    # Check required fields
    for field in required:
        if field not in payload:
            errors.append(f"Missing required parameter: '{field}'")

    # Check types
    TYPE_CHECKS = {
        "integer": int,
        "number": (int, float),
        "string": str,
        "boolean": bool,
    }
    for key, value in payload.items():
        if key not in properties:
            continue
        expected_type = properties[key].get("type")
        check = TYPE_CHECKS.get(expected_type)
        if check and not isinstance(value, check):
            errors.append(
                f"Parameter '{key}' expected {expected_type}, got {type(value).__name__}"
            )

    if errors:
        return {"ok": False, "errors": errors}

    return {"ok": True, "message": "All parameters valid", "params": payload}


@router.get("/schema/{filename}")
def get_strategy_schema(filename: str):
    """
    Returns the schema definition based on the target config filename.
    """
    is_us = "us" in filename.lower()
    return {
        "ok": True,
        "schema": {
            "workflow": {
                "title": "Global Workflow Params",
                "fields": {
                    "start_time": {
                        "type": "date",
                        "label": "Backtest Start",
                        "default": "2025-01-01",
                    },
                    "end_time": {"type": "date", "label": "Backtest End", "default": "latest"},
                    "market": {
                        "type": "select",
                        "options": ["cn", "us"],
                        "label": "Primary Market",
                        "default": "us" if is_us else "cn",
                    },
                },
            },
            "model": {
                "title": "LGBM Hyperparameters",
                "fields": {
                    "learning_rate": {
                        "type": "number",
                        "min": 0.001,
                        "max": 0.5,
                        "step": 0.001,
                        "label": "Learning Rate",
                    },
                    "num_leaves": {"type": "number", "min": 2, "max": 128, "label": "Num Leaves"},
                    "n_estimators": {
                        "type": "number",
                        "min": 10,
                        "max": 1000,
                        "label": "N Estimators",
                    },
                },
            },
            "strategy": {
                "title": "Portfolio Strategy",
                "fields": {
                    "topk": {"type": "number", "min": 1, "max": 50, "label": "Top K Selection"},
                    "n_drop": {"type": "number", "min": 0, "max": 10, "label": "N Drop"},
                },
            },
        },
    }
