#!/usr/bin/env python3
"""Validate the canonical US x1.0 and CN x1.0 model lifecycle contracts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

MODEL_VERSION = re.compile(r"^[A-Z]{2} x\d+\.\d+$")
EXPECTED_MODELS = {"us_x1_0": "US x1.0", "cn_x1_0": "CN x1.0"}
EXPECTED_XGB_RUNTIME = {
    "objective": "rank:ndcg",
    "tree_method": "hist",
    "grow_policy": "lossguide",
    "max_leaves": 31,
    "max_depth": 0,
    "learning_rate": 0.05,
    "seed": 42,
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML must contain a mapping: {path}")
    return payload


def _find_repo_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "configs"
        ).is_dir():
            return candidate
    raise FileNotFoundError("Could not locate Alpha Engine repository root")


def _single_calibration(spec: dict[str, Any]) -> dict[str, Any]:
    calibrations = spec["candidate_grid"]["ranker"]["calibrations"]
    if not isinstance(calibrations, list) or len(calibrations) != 1:
        raise ValueError("Frozen model spec must declare exactly one calibration")
    return dict(calibrations[0])


def _validate_xgb_parameter_identity(
    model_id: str,
    config: dict[str, Any],
    calibration: dict[str, Any],
) -> None:
    model = dict(config["model"])
    identity = dict(config["candidate_calibration_identity"])
    mapping = dict(identity["effective_xgb_mapping"])

    if model.get("family") != "xgb":
        raise ValueError(f"{model_id}: canonical model family must be xgb")
    if model.get("parameter_identity_status") != "effective_runtime_verified":
        raise ValueError(f"{model_id}: effective runtime identity is not verified")
    if "min_data_in_leaf" in model:
        raise ValueError(
            f"{model_id}: min_data_in_leaf must not be represented as an "
            "effective XGBoost runtime parameter"
        )

    for key, expected in EXPECTED_XGB_RUNTIME.items():
        actual = model.get(key)
        if isinstance(expected, float):
            if abs(float(actual) - expected) > 1e-12:
                raise ValueError(
                    f"{model_id}: effective XGBoost {key}={actual!r}, "
                    f"expected {expected!r}"
                )
        elif actual != expected:
            raise ValueError(
                f"{model_id}: effective XGBoost {key}={actual!r}, "
                f"expected {expected!r}"
            )

    declared = {
        "n_gain_bins": int(calibration["n_gain_bins"]),
        "num_boost_round": int(calibration["num_boost_round"]),
        "num_leaves": int(calibration["num_leaves"]),
        "min_data_in_leaf": int(calibration["min_data_in_leaf"]),
        "learning_rate": float(calibration["learning_rate"]),
    }
    recorded = {
        "n_gain_bins": int(identity["n_gain_bins"]),
        "num_boost_round": int(identity["num_boost_round"]),
        "num_leaves": int(identity["legacy_num_leaves_field"]),
        "min_data_in_leaf": int(identity["legacy_min_data_in_leaf_field"]),
        "learning_rate": float(identity["legacy_learning_rate_field"]),
    }
    if declared != recorded:
        raise ValueError(
            f"{model_id}: frozen spec/legacy identity mismatch: "
            f"{declared} != {recorded}"
        )

    if int(config["label"]["gain_bins"]) != declared["n_gain_bins"]:
        raise ValueError(f"{model_id}: effective gain-bin identity mismatch")
    if int(model["num_boost_round"]) != declared["num_boost_round"]:
        raise ValueError(f"{model_id}: effective boosting-round identity mismatch")

    expected_mapping = {
        "n_gain_bins": "consumed",
        "num_boost_round": "consumed",
        "num_leaves": "not_consumed_by_xgb_adapter",
        "min_data_in_leaf": "not_consumed_by_xgb_adapter",
        "learning_rate": "not_consumed_by_xgb_adapter",
    }
    if mapping != expected_mapping:
        raise ValueError(f"{model_id}: invalid XGBoost calibration mapping")


def validate_model_config(
    root: Path,
    model_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    expected_name = EXPECTED_MODELS[model_id]
    config_path = root / str(entry["config"])
    notebook_path = root / str(entry["notebook"])
    spec_path = root / str(entry["frozen_research_spec"])

    for path in (config_path, notebook_path, spec_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    config = _load_yaml(config_path)
    spec = _load_yaml(spec_path)
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))

    if config.get("model_id") != model_id:
        raise ValueError(f"{model_id}: config model_id mismatch")
    if config.get("display_name") != expected_name or not MODEL_VERSION.fullmatch(
        expected_name
    ):
        raise ValueError(f"{model_id}: invalid display_name")
    if entry.get("display_name") != expected_name:
        raise ValueError(f"{model_id}: registry display_name mismatch")
    if config.get("trade_ready") is not False or config.get("research_only") is not True:
        raise ValueError(f"{model_id}: baseline must remain research-only")

    strategy = config["strategy"]
    for key in ("holding_sessions", "rebalance_sessions"):
        if int(strategy.get(key, 0)) != 10:
            raise ValueError(f"{model_id}: {key} must be 10")
    if int(strategy.get("top_n", 0)) != 15 or int(strategy.get("cost_bps", 0)) != 20:
        raise ValueError(f"{model_id}: Top-15 and 20 bps conventions must be frozen")

    if spec.get("market") != config.get("market") or spec.get("benchmark") != config.get(
        "benchmark"
    ):
        raise ValueError(f"{model_id}: frozen spec market/benchmark mismatch")
    groups = spec["factor_library"]["groups"]
    if groups != [config["features"]["group"]]:
        raise ValueError(f"{model_id}: frozen spec factor group mismatch")
    families = spec["candidate_grid"]["ranker"]["model_families"]
    if families != ["xgb"]:
        raise ValueError(f"{model_id}: frozen spec must contain only xgb")

    calibration = _single_calibration(spec)
    _validate_xgb_parameter_identity(model_id, config, calibration)

    metadata = notebook.get("metadata", {}).get("alpha_engine", {})
    if notebook.get("nbformat") != 4 or metadata.get("model_id") != model_id:
        raise ValueError(f"{model_id}: notebook identity or nbformat mismatch")
    if not notebook.get("cells"):
        raise ValueError(f"{model_id}: notebook has no cells")
    notebook_text = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
    )
    required_tokens = [
        expected_name,
        "compounded_relative_excess",
        "trade_ready=false",
        "effective_runtime_parameters",
        "learning_rate=0.05",
        str(config["evidence_identity"]["workflow_run_id"]),
        str(config["evidence_identity"]["artifact_id"]),
    ]
    missing = [token for token in required_tokens if token not in notebook_text]
    if missing:
        raise ValueError(f"{model_id}: notebook missing required tokens {missing}")

    development = config["backtest_evidence"]["development"]
    strategy_return = float(development["compounded_strategy_return"])
    benchmark_return = float(development["compounded_benchmark_return"])
    expected_relative = (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0
    recorded_relative = float(development["compounded_relative_excess_return"])
    if abs(expected_relative - recorded_relative) > 1e-10:
        raise ValueError(f"{model_id}: relative-excess formula does not tie")

    return {
        "model_id": model_id,
        "display_name": expected_name,
        "config": str(config_path.relative_to(root)),
        "notebook": str(notebook_path.relative_to(root)),
        "frozen_spec": str(spec_path.relative_to(root)),
        "provider_identity": config["provider_binding"][
            "canonical_evidence_provider_identity_sha256"
        ],
        "effective_xgb_learning_rate": float(config["model"]["learning_rate"]),
        "trade_ready": False,
    }


def validate_registry(root: Path) -> dict[str, Any]:
    registry_path = root / "configs/models/model_registry_v1.yaml"
    registry = _load_yaml(registry_path)
    if registry.get("trade_ready") is not False:
        raise ValueError("Registry must remain trade_ready=false")
    if set(registry.get("models", {})) != set(EXPECTED_MODELS):
        raise ValueError("Registry must contain exactly US x1.0 and CN x1.0")
    policy = registry.get("versioning_policy", {})
    if policy.get("immutable_released_versions") is not True:
        raise ValueError("Released model versions must be immutable")
    if policy.get("final_holdout_reuse_for_selection_allowed") is not False:
        raise ValueError("Final holdout reuse must be forbidden")

    models = [
        validate_model_config(root, model_id, dict(registry["models"][model_id]))
        for model_id in sorted(EXPECTED_MODELS)
    ]
    return {
        "schema_version": "1.1",
        "status": "baseline_model_registry_valid",
        "registry": str(registry_path.relative_to(root)),
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
