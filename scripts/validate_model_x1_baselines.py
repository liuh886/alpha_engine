#!/usr/bin/env python3
"""Validate governed x1 model artifacts against the Active Strategy Catalog."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.governance.active_strategy_catalog import load_active_strategy_catalog

EXPECTED_ACTIVE_BASELINES = {"us": "us_x1_2", "cn": "cn_x1_1"}
EXPECTED_X1_MODELS = (
    "cn_x1_0",
    "cn_x1_1",
    "us_x1_0",
    "us_x1_1",
    "us_x1_2",
)

# Historical artifact paths are lifecycle test inputs, not an active-product registry.
MODEL_ARTIFACTS: dict[str, dict[str, Any]] = {
    "cn_x1_0": {
        "display_name": "CN x1.0",
        "status": "historical_baseline_superseded",
        "config": "configs/models/cn_x1_0.yaml",
        "notebook": "notebooks/models/cn_x1_0_baseline.ipynb",
        "frozen_research_spec": "configs/research_paradigms/cn_x1_0_frozen_v1.yaml",
    },
    "cn_x1_1": {
        "display_name": "CN x1.1",
        "status": "accepted_formal_baseline",
        "config": "configs/models/cn_x1_1.yaml",
        "notebook": "notebooks/models/cn_x1_1_complete_backtest.ipynb",
        "frozen_research_spec": "configs/research_experiments/cn_x1_1_fallback_aware_certification_v1.yaml",
        "formal_package": "data/research/formal_backtests/cn_x1_1.json",
    },
    "us_x1_0": {
        "display_name": "US x1.0",
        "status": "historical_baseline_superseded",
        "config": "configs/models/us_x1_0.yaml",
        "notebook": "notebooks/models/us_x1_0_baseline.ipynb",
        "frozen_research_spec": "configs/research_paradigms/us_10d_xgb_optimization_frozen_v1.yaml",
    },
    "us_x1_1": {
        "display_name": "US x1.1",
        "status": "historical_baseline_superseded",
        "config": "configs/models/us_x1_1.yaml",
        "notebook": "notebooks/models/us_x1_1_baseline.ipynb",
        "frozen_research_spec": "configs/research_paradigms/us_x1_1_frozen_v1.yaml",
    },
    "us_x1_2": {
        "display_name": "US x1.2",
        "status": "baseline_research_active",
        "config": "configs/models/us_x1_2.yaml",
        "notebook": "notebooks/models/us_x1_2_baseline.ipynb",
        "frozen_research_spec": "configs/research_paradigms/us_x1_2_frozen_v1.yaml",
        "certification_receipt": "data/research/experiment_receipts/us_x1_2_certification_v1.json",
    },
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML must contain a mapping: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def _find_repo_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "configs").is_dir():
            return candidate
    raise FileNotFoundError("Could not locate Alpha Engine repository root")


def _validate_notebook(path: Path, *, model_id: str, display_name: str) -> None:
    notebook = _load_json(path)
    metadata = notebook.get("metadata", {}).get("alpha_engine", {})
    if notebook.get("nbformat") != 4 or metadata.get("model_id") != model_id:
        raise ValueError(f"{model_id}: notebook identity mismatch")
    text = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
    )
    required = (display_name, "trade_ready")
    missing = [token for token in required if token not in text]
    if missing:
        raise ValueError(f"{model_id}: notebook missing required tokens {missing}")


def _validate_cn_formal_extension(
    package: dict[str, Any],
    config: dict[str, Any],
) -> None:
    if package.get("evidence_completeness", {}).get("status") != "complete":
        raise ValueError("cn_x1_1: complete evidence is required")
    if package.get("evidence_completeness", {}).get("missing") != []:
        raise ValueError("cn_x1_1: package declares missing evidence")
    promotion = dict(
        dict(config.get("backtest_evidence", {})).get("complete_formal_path") or {}
    )
    minimum_rows = {
        "report": int(promotion.get("rebalance_count", 0)),
        "positions": int(promotion.get("position_rows", 0)),
        "trades": int(promotion.get("transaction_rows", 0)),
    }
    if any(value <= 0 for value in minimum_rows.values()):
        raise ValueError("cn_x1_1: frozen promotion row counts are invalid")
    for field, minimum in minimum_rows.items():
        rows = package.get(field)
        if not isinstance(rows, list) or len(rows) < minimum:
            raise ValueError(
                f"cn_x1_1: frozen {field} prefix is shorter than {minimum} rows"
            )
    try:
        frozen_cutoff = date.fromisoformat(
            str(config.get("provider_binding", {}).get("cutoff") or "")
        )
        published_cutoff = date.fromisoformat(str(package.get("evidence_cutoff") or ""))
    except ValueError as exc:
        raise ValueError("cn_x1_1: invalid evidence cutoff") from exc
    if published_cutoff < frozen_cutoff:
        raise ValueError("cn_x1_1: evidence cutoff predates frozen promotion evidence")


def _validate_common_model(
    root: Path,
    model_id: str,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    config_path = root / str(entry["config"])
    if not config_path.is_file():
        raise FileNotFoundError(config_path)
    config = _load_yaml(config_path)
    if config.get("model_id") != model_id:
        raise ValueError(f"{model_id}: config identity mismatch")
    if config.get("research_only") is not True or config.get("trade_ready") is not False:
        raise ValueError(f"{model_id}: research boundary mismatch")
    if str(entry.get("display_name")) != str(config.get("display_name")):
        raise ValueError(f"{model_id}: artifact/config display name mismatch")
    return config, config_path


def _validate_legacy_x1(
    root: Path,
    model_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    config, config_path = _validate_common_model(root, model_id, entry)
    strategy = dict(config.get("strategy", {}))
    if int(strategy.get("holding_sessions", 0)) != 10:
        raise ValueError(f"{model_id}: holding_sessions must remain 10")
    if int(strategy.get("rebalance_sessions", 0)) != 10:
        raise ValueError(f"{model_id}: rebalance_sessions must remain 10")
    if int(strategy.get("top_n", 0)) != 15:
        raise ValueError(f"{model_id}: Top-15 convention must remain frozen")
    if int(strategy.get("cost_bps", 0)) != 20:
        raise ValueError(f"{model_id}: cost must remain 20 bps")

    notebook_path = root / str(entry["notebook"])
    spec_path = root / str(entry["frozen_research_spec"])
    if not notebook_path.is_file() or not spec_path.is_file():
        raise FileNotFoundError(f"{model_id}: notebook or frozen spec is missing")
    spec = _load_yaml(spec_path)
    if spec.get("market") != config.get("market") or spec.get("benchmark") != config.get(
        "benchmark"
    ):
        raise ValueError(f"{model_id}: frozen spec identity mismatch")
    _validate_notebook(
        notebook_path,
        model_id=model_id,
        display_name=str(config["display_name"]),
    )
    return {
        "model_id": model_id,
        "display_name": str(config["display_name"]),
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "notebook": str(notebook_path.relative_to(root)),
        "frozen_spec": str(spec_path.relative_to(root)),
        "trade_ready": False,
    }


def _validate_us_x1_2(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    model_id = "us_x1_2"
    config, config_path = _validate_common_model(root, model_id, entry)
    if config.get("status") != "baseline_research_active":
        raise ValueError("us_x1_2: active baseline status mismatch")
    lineage = dict(config.get("lineage", {}))
    if lineage.get("parent") != "us_x1_1" or lineage.get("supersedes") != "us_x1_1":
        raise ValueError("us_x1_2: lineage mismatch")

    model = dict(config.get("model", {}))
    expected_model: dict[str, Any] = {
        "family": "xgb",
        "objective": "rank:ndcg",
        "tree_method": "hist",
        "grow_policy": "lossguide",
        "max_leaves": 31,
        "max_depth": 0,
        "min_child_weight": 1.0,
        "learning_rate": 0.05,
        "num_boost_round": 200,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
        "seed": 42,
    }
    for key, expected in expected_model.items():
        if model.get(key) != expected:
            raise ValueError(f"us_x1_2: XGBoost {key} mismatch")

    strategy = dict(config.get("strategy", {}))
    expected_strategy: dict[str, Any] = {
        "holding_sessions": 10,
        "rebalance_sessions": 10,
        "top_n": 15,
        "weighting": "equal_weight",
        "maximum_names_per_sector": 4,
        "cost_bps": 20,
        "fail_closed_if_unfillable": True,
    }
    for key, expected in expected_strategy.items():
        if strategy.get(key) != expected:
            raise ValueError(f"us_x1_2: strategy {key} mismatch")

    receipt_path = root / str(entry["certification_receipt"])
    receipt = _load_json(receipt_path)
    if receipt.get("selected_development_winner") != "r11_sampled":
        raise ValueError("us_x1_2: certification winner mismatch")
    if receipt.get("determinism", {}).get("exact") is not True:
        raise ValueError("us_x1_2: deterministic reproduction is required")
    if receipt.get("governance", {}).get("formal_acceptance_supported") is not False:
        raise ValueError("us_x1_2: prospective limitation must remain explicit")
    selected = dict(receipt.get("development_candidates", {}).get("r11_sampled") or {})
    if selected.get("all_development_gates_pass") is not True:
        raise ValueError("us_x1_2: development gates are not satisfied")

    notebook_path = root / str(entry["notebook"])
    spec_path = root / str(entry["frozen_research_spec"])
    if not notebook_path.is_file() or not spec_path.is_file():
        raise FileNotFoundError("us_x1_2: notebook or frozen spec is missing")
    spec = _load_yaml(spec_path)
    if spec.get("model_id") != model_id or spec.get("status") != "frozen_active_research_baseline":
        raise ValueError("us_x1_2: frozen spec status mismatch")
    if spec.get("promotion_boundary", {}).get("prospective_acceptance_pending") is not True:
        raise ValueError("us_x1_2: prospective acceptance boundary was weakened")
    _validate_notebook(notebook_path, model_id=model_id, display_name="US x1.2")

    return {
        "model_id": model_id,
        "display_name": "US x1.2",
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "notebook": str(notebook_path.relative_to(root)),
        "frozen_spec": str(spec_path.relative_to(root)),
        "certification_receipt": str(receipt_path.relative_to(root)),
        "selected_candidate": "r11_sampled",
        "prospective_acceptance_pending": True,
        "trade_ready": False,
    }


def _validate_cn_x1_1(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    model_id = "cn_x1_1"
    config, config_path = _validate_common_model(root, model_id, entry)
    package_path = root / str(entry["formal_package"])
    if not package_path.is_file():
        raise FileNotFoundError(package_path)
    package = _load_json(package_path)
    if config.get("status") != "accepted_formal_baseline":
        raise ValueError("cn_x1_1: formal status mismatch")
    if package.get("model_id") != model_id:
        raise ValueError("cn_x1_1: formal package identity mismatch")
    _validate_cn_formal_extension(package, config)
    return {
        "model_id": model_id,
        "display_name": "CN x1.1",
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "formal_package": str(package_path.relative_to(root)),
        "evidence_completeness": "complete",
        "trade_ready": False,
    }


def validate_model_config(
    root: Path,
    model_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    if model_id == "us_x1_2":
        return _validate_us_x1_2(root, entry)
    if model_id == "cn_x1_1":
        return _validate_cn_x1_1(root, entry)
    return _validate_legacy_x1(root, model_id, entry)


def validate_registry(root: Path) -> dict[str, Any]:
    catalog_path = root / "configs/strategies/registry.json"
    active_catalog = load_active_strategy_catalog(catalog_path)
    active_by_family = active_catalog.by_model_family_id
    observed_active = {
        "us": active_by_family["us_x"].model_version_id,
        "cn": active_by_family["cn_x"].model_version_id,
    }
    if observed_active != EXPECTED_ACTIVE_BASELINES:
        raise ValueError(
            f"Active Strategy Catalog x1 identities drifted: {observed_active}"
        )

    models = [
        validate_model_config(root, model_id, dict(MODEL_ARTIFACTS[model_id]))
        for model_id in EXPECTED_X1_MODELS
    ]
    return {
        "schema_version": "2.0",
        "status": "x1_lifecycle_valid",
        "active_strategy_catalog": str(catalog_path.relative_to(root)),
        "active_baselines": observed_active,
        "governed_x1_models": models,
        "models": models,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = _find_repo_root(args.root)
    payload = validate_registry(root)
    text = json.dumps(payload, indent=2)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
