#!/usr/bin/env python3
"""Validate the current governed x1 baselines from the Active Strategy Catalog."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.artifacts.formal_bundle_reader import load_formal_run
from src.governance.active_strategy_catalog import load_active_strategy_catalog

EXPECTED_ACTIVE_BASELINES = {"us": "us_x1_3", "cn": "cn_x1_2"}
ACTIVE_MODEL_ARTIFACTS: dict[str, dict[str, Any]] = {
    "cn_x1_2": {
        "display_name": "CN x1.2",
        "status": "accepted_formal_baseline",
        "config": "configs/models/cn_x1_2.yaml",
        "experiment_receipt": "data/research/experiment_receipts/cn_x1_2_alpha158_breadth_scaled_v1.json",
        "promotion_receipt": "data/research/experiment_receipts/cn_x1_2_user_directed_promotion_v1.json",
    },
    "us_x1_3": {
        "display_name": "US x1.3",
        "status": "baseline_research_active",
        "config": "configs/models/us_x1_3.yaml",
        "stage_b_spec": "configs/research_experiments/us_x1_3_stage_b_v1.yaml",
        "stage_b_receipt": "data/research/experiment_receipts/us_x1_3_stage_b_v1.json",
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


def _validate_common_model(
    root: Path, model_id: str, entry: dict[str, Any]
) -> tuple[dict[str, Any], Path]:
    config_path = root / str(entry["config"])
    if not config_path.is_file():
        raise FileNotFoundError(config_path)
    config = _load_yaml(config_path)
    if config.get("model_id") != model_id:
        raise ValueError(f"{model_id}: config identity mismatch")
    if config.get("research_only") is not True or config.get("trade_ready") is not False:
        raise ValueError(f"{model_id}: research boundary mismatch")
    if str(entry["display_name"]) != str(config.get("display_name")):
        raise ValueError(f"{model_id}: artifact/config display name mismatch")
    return config, config_path


def _validate_us_x1_3(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    model_id = "us_x1_3"
    config, config_path = _validate_common_model(root, model_id, entry)
    if config.get("status") != "baseline_research_active":
        raise ValueError("us_x1_3: active baseline status mismatch")
    lineage = dict(config.get("lineage", {}))
    if (
        lineage.get("parent") != "us_x1_2"
        or lineage.get("supersedes") != "us_x1_2"
        or lineage.get("selected_candidate") != "mvv_plus_pressure"
    ):
        raise ValueError("us_x1_3: lineage mismatch")
    expected_factors = [
        "ohlcv.momentum.ret_5d",
        "ohlcv.momentum.ret_10d",
        "ohlcv.momentum.ret_20d",
        "ohlcv.volatility.std_ret_10d",
        "ohlcv.volatility.std_ret_20d",
        "ohlcv.volume.momentum_10d",
        "ohlcv.liquidity.volume_vs_ma_20d",
        "ohlcv.momentum.ret_3d",
        "ohlcv.liquidity.volume_vs_ma_5d",
        "ohlcv.liquidity.volume_vs_ma_10d",
        "ohlcv.pressure.ret1_x_volume_shock_5d",
        "ohlcv.pressure.ret5_x_volume_shock_10d",
        "ohlcv.pressure.high_low_ratio",
    ]
    features = dict(config.get("features", {}))
    if (
        features.get("source_factor_groups")
        != ["momentum_volatility_volume", "us_price_volume_pressure"]
        or features.get("factor_ids") != expected_factors
    ):
        raise ValueError("us_x1_3: Stage-B factor identity/order mismatch")
    expected_model = {
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
    model = dict(config.get("model", {}))
    for key, expected in expected_model.items():
        if model.get(key) != expected:
            raise ValueError(f"us_x1_3: XGBoost {key} mismatch")
    strategy = dict(config.get("strategy", {}))
    expected_strategy = {
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
            raise ValueError(f"us_x1_3: strategy {key} mismatch")
    spec_path = root / str(entry["stage_b_spec"])
    receipt_path = root / str(entry["stage_b_receipt"])
    spec = _load_yaml(spec_path)
    receipt = _load_json(receipt_path)
    if (
        spec.get("status") != "completed_supported"
        or spec.get("result", {}).get("supported") is not True
        or spec.get("result", {}).get("winner") != "mvv_plus_pressure"
    ):
        raise ValueError("us_x1_3: Stage-B experiment is not supported")
    if (
        receipt.get("decision") != "us_x1_3_stage_b_candidate_supported"
        or receipt.get("winner") != "mvv_plus_pressure"
        or receipt.get("stage_b_supported") is not True
        or receipt.get("supported") is not True
        or receipt.get("research_only") is not True
        or receipt.get("trade_ready") is not False
    ):
        raise ValueError("us_x1_3: Stage-B receipt boundary mismatch")
    candidate = dict(receipt.get("candidate_metadata", {}).get("mvv_plus_pressure") or {})
    if candidate.get("factor_count") != 13 or candidate.get("factor_groups") != [
        "momentum_volatility_volume",
        "us_price_volume_pressure",
    ]:
        raise ValueError("us_x1_3: Stage-B candidate metadata mismatch")
    reproduction = receipt.get("score_reproduction")
    if (
        not isinstance(reproduction, dict)
        or not reproduction
        or any(
            not isinstance(row, dict) or row.get("first") != row.get("second")
            for row in reproduction.values()
        )
    ):
        raise ValueError("us_x1_3: deterministic score reproduction failed")
    support = dict(receipt.get("support_boundary") or {})
    if (
        support.get("supported") is not True
        or support.get("leader") != "mvv_plus_pressure"
        or support.get("positive_window_count") != 4
        or support.get("exact_score_reproduction") is not True
    ):
        raise ValueError("us_x1_3: Stage-B support gates are incomplete")
    return {
        "model_id": model_id,
        "display_name": "US x1.3",
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "stage_b_spec": str(spec_path.relative_to(root)),
        "stage_b_receipt": str(receipt_path.relative_to(root)),
        "selected_candidate": "mvv_plus_pressure",
        "factor_count": 13,
        "prospective_acceptance_pending": True,
        "trade_ready": False,
    }


def _validate_cn_x1_2(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    model_id = "cn_x1_2"
    config, config_path = _validate_common_model(root, model_id, entry)
    if config.get("status") != "accepted_formal_baseline":
        raise ValueError("cn_x1_2: formal status mismatch")
    lineage = dict(config.get("lineage") or {})
    if lineage.get("parent") != "cn_x1_1" or lineage.get("supersedes") != "cn_x1_1":
        raise ValueError("cn_x1_2: lineage mismatch")
    if lineage.get("promotion_authority") != "explicit_user_direction_2026_08_14":
        raise ValueError("cn_x1_2: promotion authority mismatch")
    features = dict(config.get("features") or {})
    if len(features.get("factor_ids") or []) != 17:
        raise ValueError("cn_x1_2: frozen 17-factor identity is required")
    experiment_path = root / str(entry["experiment_receipt"])
    promotion_path = root / str(entry["promotion_receipt"])
    experiment = _load_json(experiment_path)
    promotion = _load_json(promotion_path)
    boundary = dict(experiment.get("development_boundary") or {})
    if experiment.get("decision") != "cn_x1_2_alpha158_breadth_scaled_development_rejected":
        raise ValueError("cn_x1_2: rejected source decision was rewritten")
    if boundary.get("supported") is not False:
        raise ValueError("cn_x1_2: failed source boundary was rewritten")
    failed = [key for key, value in dict(boundary.get("checks") or {}).items() if value is not True]
    if failed != ["2026h1_drawdown_worsening_within_3pp"]:
        raise ValueError("cn_x1_2: failed gate identity mismatch")
    gate = dict(promotion.get("preregistered_gate_result") or {})
    governance = dict(promotion.get("governance_interpretation") or {})
    if promotion.get("decision") != "promoted_by_explicit_user_governance_exception":
        raise ValueError("cn_x1_2: promotion decision mismatch")
    if gate.get("passed") != 21 or gate.get("total") != 22 or gate.get("supported") is not False:
        raise ValueError("cn_x1_2: promotion gate disclosure mismatch")
    if governance.get("formal_acceptance_supported_by_preregistered_gates") is not False:
        raise ValueError("cn_x1_2: promotion must not claim formal gate support")
    if promotion.get("research_only") is not True or promotion.get("trade_ready") is not False:
        raise ValueError("cn_x1_2: promotion research boundary mismatch")
    package = load_formal_run(root, model_id).refresh_state()
    completeness = dict(package.get("evidence_completeness") or {})
    cutoff = str(package.get("evidence_cutoff") or "")
    try:
        cutoff_date = date.fromisoformat(cutoff)
    except ValueError as exc:
        raise ValueError("cn_x1_2: formal evidence cutoff is invalid") from exc
    if (
        package.get("model_id") != model_id
        or completeness.get("status") != "complete"
        or completeness.get("missing") != []
        or cutoff_date < date(2026, 6, 30)
    ):
        raise ValueError("cn_x1_2: complete formal Bundle v2 identity mismatch")
    publication = dict(config.get("formal_publication") or {})
    if (
        publication.get("transition_status") != "maintained_append_only_formal_refresh"
        or publication.get("evidence_completeness") != "complete_frontend_bundle_v2"
    ):
        raise ValueError("cn_x1_2: materialized publication binding mismatch")
    evidence = dict(package.get("evidence") or {})
    if cutoff == "2026-06-30":
        if publication.get("formal_manifest_sha256") != evidence.get(
            "accepted_formal_manifest_sha256"
        ):
            raise ValueError("cn_x1_2: initial formal publication binding mismatch")
    elif (
        evidence.get("refresh_adapter") != "refresh_ranker_formal.cn_x1_2"
        or evidence.get("model_selection_reopened") is not False
        or evidence.get("prospective_reporting_start") != "2026-07-01"
    ):
        raise ValueError("cn_x1_2: prospective formal refresh binding mismatch")
    return {
        "model_id": model_id,
        "display_name": "CN x1.2",
        "status": str(entry["status"]),
        "config": str(config_path.relative_to(root)),
        "experiment_receipt": str(experiment_path.relative_to(root)),
        "promotion_receipt": str(promotion_path.relative_to(root)),
        "promotion_authority": str(lineage["promotion_authority"]),
        "formal_acceptance_supported": False,
        "failed_gate": failed[0],
        "formal_bundle_transition": str(publication["transition_status"]),
        "evidence_completeness": "complete",
        "trade_ready": False,
    }


def validate_registry(root: Path) -> dict[str, Any]:
    catalog_path = root / "configs/strategies/registry.json"
    active_catalog = load_active_strategy_catalog(catalog_path)
    active_by_strategy = active_catalog.by_strategy_id
    observed_active = {
        "us": active_by_strategy["us_x"].model_version_id,
        "cn": active_by_strategy["cn_x"].model_version_id,
    }
    if observed_active != EXPECTED_ACTIVE_BASELINES:
        raise ValueError(f"Active Strategy Catalog x1 identities drifted: {observed_active}")
    models = [
        _validate_cn_x1_2(root, ACTIVE_MODEL_ARTIFACTS["cn_x1_2"]),
        _validate_us_x1_3(root, ACTIVE_MODEL_ARTIFACTS["us_x1_3"]),
    ]
    return {
        "schema_version": "3.0",
        "status": "active_x1_baselines_valid",
        "active_strategy_catalog": catalog_path.relative_to(root).as_posix(),
        "active_baselines": observed_active,
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
