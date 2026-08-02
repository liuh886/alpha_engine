"""Run bounded US87 XGBoost development and one frozen 2026H1 challenge.

Candidate selection uses only complete 2024H1--2025H2 windows. The selected
candidate and the immutable baseline are then evaluated once on 2026H1.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from scripts.run_us_feature_quality_validation import run as run_us_validation

DEV_SPEC = Path("configs/research_paradigms/us_10d_xgb_optimization_dev_v1.yaml")
BASELINE_SPEC = Path("configs/research_paradigms/us_10d_selected_pool_ranker_retest_v1.yaml")
BASELINE_NAME = (
    "xgb:daily_ranker:momentum_volatility_volume:"
    "gain5_round100_leaves31_leaf10_lr0.05"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _development_candidates(run_dir: Path) -> list[dict[str, Any]]:
    stability = _load_json(run_dir / "walk_forward_stability.json")
    manifest = _load_json(run_dir / "candidate_manifest.json")
    definitions = {
        str(item["name"]): item
        for item in manifest.get("candidates", [])
        if isinstance(item, dict) and item.get("model_family") == "xgb"
    }
    rows: list[dict[str, Any]] = []
    for raw in stability.get("candidates", []):
        if not isinstance(raw, dict):
            continue
        full_name = str(raw.get("candidate", ""))
        if not full_name.endswith("/xgb_rank_ndcg/original"):
            continue
        base_name = full_name.split("/", 1)[0]
        definition = definitions.get(base_name)
        if definition is None:
            continue
        row = dict(raw)
        row["base_name"] = base_name
        row["definition"] = definition
        drawdown_penalty = max(0.0, -float(row["worst_drawdown"]) - 0.20)
        row["selection_score"] = (
            float(row["compounded_relative_excess_return"])
            - 2.0 * drawdown_penalty
            + 0.15 * float(row["mean_icir"])
            + 0.10 * float(row["mean_rank_ic"])
            + 0.05 * float(row["positive_excess_ratio"])
        )
        row["eligible"] = bool(
            int(row["n_windows"]) >= 4
            and float(row["positive_excess_ratio"]) >= 0.75
            and float(row["mean_spread"]) > 0.0
            and float(row["mean_rank_ic"]) > 0.0
        )
        rows.append(row)
    return sorted(rows, key=lambda item: float(item["selection_score"]), reverse=True)


def _freeze_spec(
    root: Path,
    *,
    definition: dict[str, Any],
    experiment_id: str,
    output_path: Path,
) -> Path:
    payload = yaml.safe_load((root / DEV_SPEC).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("development spec must be a mapping")
    frozen = deepcopy(payload)
    frozen["experiment_id"] = experiment_id
    frozen["factor_library"]["groups"] = [
        str(definition["feature_group"]["name"])
    ]
    calibration = dict(definition["calibration"])
    calibration.pop("name", None)
    frozen["candidate_grid"]["ranker"] = {
        "model_families": ["xgb"],
        "calibrations": [calibration],
    }
    frozen["candidate_grid"]["factor_baselines"] = []
    frozen["walk_forward"]["test_end"] = "2026-06-30"
    frozen["walk_forward"]["last_test_year"] = 2026
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(frozen, sort_keys=False), encoding="utf-8")
    return output_path


def _baseline_definition(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / BASELINE_SPEC).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline spec must be a mapping")
    calibration = dict(payload["candidate_grid"]["ranker"]["calibrations"][0])
    return {
        "name": BASELINE_NAME,
        "model_family": "xgb",
        "feature_group": {
            "name": str(payload["factor_library"]["groups"][0]),
        },
        "calibration": calibration,
    }


def _challenge_row(run_dir: Path, experiment_id: str) -> dict[str, Any]:
    window_path = run_dir / "windows" / f"{experiment_id}_2026H1.json"
    payload = _load_json(window_path)
    report = payload.get("comparison_report", {})
    candidates = report.get("candidates", []) if isinstance(report, dict) else []
    matches = [
        dict(item)
        for item in candidates
        if isinstance(item, dict)
        and item.get("candidate_kind") == "xgb_rank_ndcg"
        and item.get("orientation") == "original"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one original XGBoost challenge row: {window_path}")
    return matches[0]


def _decision(selected: dict[str, Any], baseline: dict[str, Any]) -> str:
    selected_excess = float(selected["excess_return"])
    baseline_excess = float(baseline["excess_return"])
    selected_dd = float(selected["max_drawdown"])
    baseline_dd = float(baseline["max_drawdown"])
    signal_ok = float(selected["icir"]) > 0.0 and float(selected["rank_ic"]) > 0.0
    return_improved = selected_excess >= baseline_excess + 0.02
    risk_improved = selected_dd >= baseline_dd + 0.05 and selected_excess >= baseline_excess - 0.02
    if signal_ok and (return_improved or risk_improved):
        return "improvement_supported"
    return "baseline_only"


def run(
    root: Path,
    *,
    provider_uri: Path,
    output_dir: Path = Path("artifacts/evidence/us87_xgb_optimization_v1"),
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    dev_result = run_us_validation(
        root,
        spec_path=DEV_SPEC,
        output_dir=output_dir / "development",
        provider_uri=provider_uri,
    )
    dev_run_dir = output_dir / "development" / "us_10d_xgb_optimization_dev_v1"
    candidates = _development_candidates(dev_run_dir)
    eligible = [item for item in candidates if item["eligible"]]
    if not eligible:
        payload = {
            "schema_version": "1.0",
            "status": "ranking_signal_unstable",
            "research_only": True,
            "trade_ready": False,
            "development_result": dev_result,
            "candidates": candidates,
        }
        _write_json(output_dir / "optimization_decision.json", payload)
        return payload

    selected = eligible[0]
    generated_dir = output_dir / "generated_specs"
    selected_experiment = "us_10d_xgb_optimization_challenge_v1"
    baseline_experiment = "us_10d_xgb_baseline_challenge_v1"
    selected_spec = _freeze_spec(
        root,
        definition=dict(selected["definition"]),
        experiment_id=selected_experiment,
        output_path=generated_dir / f"{selected_experiment}.yaml",
    )
    baseline_spec = _freeze_spec(
        root,
        definition=_baseline_definition(root),
        experiment_id=baseline_experiment,
        output_path=generated_dir / f"{baseline_experiment}.yaml",
    )

    run_us_validation(
        root,
        spec_path=selected_spec,
        output_dir=output_dir / "challenge",
        provider_uri=provider_uri,
    )
    run_us_validation(
        root,
        spec_path=baseline_spec,
        output_dir=output_dir / "challenge",
        provider_uri=provider_uri,
    )
    selected_challenge = _challenge_row(
        output_dir / "challenge" / selected_experiment,
        selected_experiment,
    )
    baseline_challenge = _challenge_row(
        output_dir / "challenge" / baseline_experiment,
        baseline_experiment,
    )
    decision = _decision(selected_challenge, baseline_challenge)
    payload = {
        "schema_version": "1.0",
        "status": decision,
        "research_only": True,
        "trade_ready": False,
        "development_windows": ["2024H1", "2024H2", "2025H1", "2025H2"],
        "challenge_window": "2026H1",
        "attempted_development_variants": len(candidates),
        "selected_candidate": selected,
        "selected_challenge": selected_challenge,
        "baseline_challenge": baseline_challenge,
        "decision_rules": {
            "minimum_excess_improvement": 0.02,
            "minimum_drawdown_improvement": 0.05,
            "maximum_excess_sacrifice_for_risk_improvement": 0.02,
            "positive_challenge_icir_and_rank_ic_required": True,
        },
    }
    _write_json(output_dir / "optimization_decision.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/us87_xgb_optimization_v1"),
    )
    args = parser.parse_args()
    payload = run(
        args.root,
        provider_uri=args.provider_uri,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
