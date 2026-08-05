#!/usr/bin/env python3
"""Validate governed US and CN x1 baseline lifecycle contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

MODEL_VERSION = re.compile(r"^[A-Z]{2} x\d+\.\d+$")
EXPECTED_MODELS = {
    "us_x1_0": "US x1.0",
    "us_x1_1": "US x1.1",
    "cn_x1_0": "CN x1.0",
    "cn_x1_1": "CN x1.1",
}
EXPECTED_ACTIVE_BASELINES = {"us": "us_x1_1", "cn": "cn_x1_1"}
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


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def _find_repo_root(start: Path) -> Path:
    for candidate in (start.resolve(), *start.resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "configs"
        ).is_dir():
            return candidate
    raise FileNotFoundError("Could not locate Alpha Engine repository root")


def _validate_notebook(
    notebook_path: Path,
    *,
    model_id: str,
    display_name: str,
    required_tokens: list[str],
) -> None:
    notebook = _load_json(notebook_path)
    metadata = notebook.get("metadata", {}).get("alpha_engine", {})
    if notebook.get("nbformat") != 4 or metadata.get("model_id") != model_id:
        raise ValueError(f"{model_id}: notebook identity or nbformat mismatch")
    if not notebook.get("cells"):
        raise ValueError(f"{model_id}: notebook has no cells")
    text = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook.get("cells", [])
    )
    missing = [token for token in [display_name, *required_tokens] if token not in text]
    if missing:
        raise ValueError(f"{model_id}: notebook missing required tokens {missing}")


def _validate_legacy_xgb(
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
    if config.get("model_id") != model_id:
        raise ValueError(f"{model_id}: config identity mismatch")
    if config.get("display_name") != expected_name or not MODEL_VERSION.fullmatch(
        expected_name
    ):
        raise ValueError(f"{model_id}: display name mismatch")
    if config.get("research_only") is not True or config.get("trade_ready") is not False:
        raise ValueError(f"{model_id}: research boundary mismatch")

    strategy = dict(config.get("strategy", {}))
    if int(strategy.get("holding_sessions", 0)) != 10:
        raise ValueError(f"{model_id}: holding_sessions must remain 10")
    if int(strategy.get("rebalance_sessions", 0)) != 10:
        raise ValueError(f"{model_id}: rebalance_sessions must remain 10")
    if int(strategy.get("top_n", 0)) != 15:
        raise ValueError(f"{model_id}: Top-15 convention must remain frozen")
    if int(strategy.get("cost_bps", 0)) != 20:
        raise ValueError(f"{model_id}: cost must remain 20 bps")

    model = dict(config.get("model", {}))
    if model.get("family") != "xgb":
        raise ValueError(f"{model_id}: model family must remain xgb")
    for key, expected in EXPECTED_XGB_RUNTIME.items():
        actual = model.get(key)
        if isinstance(expected, float):
            if abs(float(actual) - expected) > 1e-12:
                raise ValueError(f"{model_id}: XGBoost {key} mismatch")
        elif actual != expected:
            raise ValueError(f"{model_id}: XGBoost {key} mismatch")

    if spec.get("market") != config.get("market"):
        raise ValueError(f"{model_id}: frozen market mismatch")
    if spec.get("benchmark") != config.get("benchmark"):
        raise ValueError(f"{model_id}: frozen benchmark mismatch")

    evidence = dict(config.get("evidence_identity", {}))
    _validate_notebook(
        notebook_path,
        model_id=model_id,
        display_name=expected_name,
        required_tokens=[
            "trade_ready=false",
            str(evidence.get("workflow_run_id")),
            str(evidence.get("artifact_id")),
        ],
    )

    development = dict(config.get("backtest_evidence", {}).get("development", {}))
    strategy_return = float(development["compounded_strategy_return"])
    benchmark_return = float(development["compounded_benchmark_return"])
    expected_relative = (1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0
    recorded_relative = float(development["compounded_relative_excess_return"])
    if abs(expected_relative - recorded_relative) > 1e-10:
        raise ValueError(f"{model_id}: relative-excess formula does not tie")

    return {
        "model_id": model_id,
        "display_name": expected_name,
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "notebook": str(notebook_path.relative_to(root)),
        "frozen_spec": str(spec_path.relative_to(root)),
        "provider_identity": config["provider_binding"][
            "canonical_evidence_provider_identity_sha256"
        ],
        "effective_xgb_learning_rate": float(model["learning_rate"]),
        "trade_ready": False,
    }


def _validate_cn_x1_1(
    root: Path,
    entry: dict[str, Any],
) -> dict[str, Any]:
    model_id = "cn_x1_1"
    config_path = root / str(entry["config"])
    notebook_path = root / str(entry["notebook"])
    spec_path = root / str(entry["frozen_research_spec"])
    package_path = root / str(entry["formal_package"])
    evidence_root = root / "data/research/cn_x1_1_regime_gated_candidate_v1"
    for path in (config_path, notebook_path, spec_path, package_path, evidence_root):
        if not path.exists():
            raise FileNotFoundError(path)

    config = _load_yaml(config_path)
    package = _load_json(package_path)
    decision = _load_json(evidence_root / "decision.json")
    evidence_manifest = _load_json(evidence_root / "evidence_manifest.json")

    if config.get("model_id") != model_id or config.get("display_name") != "CN x1.1":
        raise ValueError("cn_x1_1: config identity mismatch")
    if config.get("status") != "accepted_formal_baseline":
        raise ValueError("cn_x1_1: formal status mismatch")
    if config.get("research_only") is not True or config.get("trade_ready") is not False:
        raise ValueError("cn_x1_1: research boundary mismatch")
    if config.get("lineage", {}).get("parent") != "cn_x1_0":
        raise ValueError("cn_x1_1: parent lineage mismatch")
    if config.get("lineage", {}).get("supersedes") != "cn_x1_0":
        raise ValueError("cn_x1_1: supersession lineage mismatch")

    construction = dict(config.get("portfolio_construction", {}))
    if construction.get("selected_sectors") != 4:
        raise ValueError("cn_x1_1: selected sector count must remain four")
    if construction.get("names_per_sector") != 1:
        raise ValueError("cn_x1_1: names_per_sector must remain one")
    if float(construction.get("risk_on_position_weight", 0.0)) != 0.25:
        raise ValueError("cn_x1_1: risk-on weights must remain equal")

    execution = dict(config.get("execution", {}))
    expected_execution = {
        "holding_sessions": 10,
        "rebalance_sessions": 10,
        "execution_delay_sessions": 1,
        "cost_bps_per_unit_turnover": 20,
    }
    for key, expected in expected_execution.items():
        if int(execution.get(key, 0)) != expected:
            raise ValueError(f"cn_x1_1: {key} mismatch")
    if int(config.get("regime_gate", {}).get("votes_required", 0)) != 2:
        raise ValueError("cn_x1_1: regime vote threshold mismatch")

    if decision.get("candidate_authorized") is not True:
        raise ValueError("cn_x1_1: candidate authorization missing")
    if not all(bool(value) for value in decision.get("gates", {}).values()):
        raise ValueError("cn_x1_1: an authorization gate is not satisfied")
    for row in evidence_manifest.get("files", []):
        path = evidence_root / str(row["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"cn_x1_1: evidence hash mismatch for {row['path']}")

    if package.get("model_id") != model_id:
        raise ValueError("cn_x1_1: formal package identity mismatch")
    if package.get("publication_status") != "accepted_formal_baseline":
        raise ValueError("cn_x1_1: package is not formal")
    if package.get("evidence_completeness", {}).get("status") != "complete":
        raise ValueError("cn_x1_1: complete evidence is required")
    if package.get("evidence_completeness", {}).get("missing") != []:
        raise ValueError("cn_x1_1: package declares missing evidence")
    if len(package.get("report", [])) != 102:
        raise ValueError("cn_x1_1: expected 102 report periods")
    if len(package.get("positions", [])) != 252:
        raise ValueError("cn_x1_1: expected 252 retained positions")
    if len(package.get("trades", [])) != 372:
        raise ValueError("cn_x1_1: expected 372 reconstructed transactions")
    if package.get("evidence_cutoff") != "2026-08-03":
        raise ValueError("cn_x1_1: evidence cutoff mismatch")

    evidence = dict(config["evidence_identity"])
    _validate_notebook(
        notebook_path,
        model_id=model_id,
        display_name="CN x1.1",
        required_tokens=[
            "research_only=true",
            "trade_ready=false",
            str(evidence["workflow_run_id"]),
            str(evidence["artifact_id"]),
            "102 non-overlapping 10-session rebalances",
        ],
    )

    return {
        "model_id": model_id,
        "display_name": "CN x1.1",
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "notebook": str(notebook_path.relative_to(root)),
        "frozen_spec": str(spec_path.relative_to(root)),
        "formal_package": str(package_path.relative_to(root)),
        "provider_identity": config["provider_binding"][
            "canonical_evidence_provider_identity_sha256"
        ],
        "evidence_completeness": "complete",
        "trade_ready": False,
    }


def validate_model_config(
    root: Path,
    model_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    if model_id == "cn_x1_1":
        return _validate_cn_x1_1(root, entry)
    return _validate_legacy_xgb(root, model_id, entry)


def validate_registry(root: Path) -> dict[str, Any]:
    registry_path = root / "configs/models/model_registry_v1.yaml"
    registry = _load_yaml(registry_path)
    if registry.get("trade_ready") is not False:
        raise ValueError("Registry must remain trade_ready=false")

    registered_models = registry.get("models", {})
    if not isinstance(registered_models, dict):
        raise ValueError("Registry models must be a mapping")
    missing = sorted(set(EXPECTED_MODELS) - set(registered_models))
    if missing:
        raise ValueError(f"Registry is missing governed x1 versions: {missing}")

    active_baselines = registry.get("active_baselines", {})
    if not isinstance(active_baselines, dict):
        raise ValueError("Registry active baselines must be a mapping")
    for market, expected_model in EXPECTED_ACTIVE_BASELINES.items():
        if active_baselines.get(market) != expected_model:
            raise ValueError(f"Registry active {market} baseline must be {expected_model}")

    policy = registry.get("versioning_policy", {})
    if policy.get("immutable_released_versions") is not True:
        raise ValueError("Released model versions must be immutable")
    if policy.get("final_holdout_reuse_for_selection_allowed") is not False:
        raise ValueError("Final holdout reuse must be forbidden")
    if registered_models["us_x1_0"].get("superseded_by") != "us_x1_1":
        raise ValueError("US x1.0 must be superseded by US x1.1")
    if registered_models["cn_x1_0"].get("superseded_by") != "cn_x1_1":
        raise ValueError("CN x1.0 must be superseded by CN x1.1")
    if registered_models["cn_x1_1"].get("status") != "accepted_formal_baseline":
        raise ValueError("CN x1.1 must be the active accepted CN baseline")

    models = [
        validate_model_config(root, model_id, dict(registered_models[model_id]))
        for model_id in sorted(EXPECTED_MODELS)
    ]
    return {
        "schema_version": "1.4",
        "status": "baseline_model_registry_valid",
        "registry": str(registry_path.relative_to(root)),
        "active_baselines": dict(active_baselines),
        "governed_x1_models": models,
        "models": models,
        "additional_registered_models": sorted(
            set(registered_models) - set(EXPECTED_MODELS)
        ),
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
