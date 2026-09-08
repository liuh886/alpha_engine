"""One-shot locked-test evaluation for the sealed CN_27 Sharpe discovery winner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.research.all_weather_alpha_rotation import (
    _return_metrics,
    canonical_sha256,
    sha256_file,
)
from src.research.cn27_sharpe_discovery import (
    compute_discovery_features,
    discovery_identity,
    load_discovery_contract,
    run_discovery_recipe,
    write_json,
)


def _verify_manifest_identity(payload: Mapping[str, Any]) -> None:
    body = dict(payload)
    expected = str(body.pop("manifest_identity_sha256", ""))
    if not expected or canonical_sha256(body) != expected:
        raise ValueError("screen manifest identity mismatch")


def _load_sealed_selection(
    screen_dir: Path,
    *,
    expected_experiment_contract_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = screen_dir / "evidence_manifest.json"
    selection_path = screen_dir / "selection.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    _verify_manifest_identity(manifest)
    for name, expected in manifest["outputs"].items():
        if sha256_file(screen_dir / name) != expected:
            raise ValueError(f"screen output hash mismatch: {name}")
    if manifest.get("locked_test_opened") is not False:
        raise ValueError("screen manifest does not prove a sealed locked test")
    if manifest["identity"]["experiment_contract_sha256"] != expected_experiment_contract_sha256:
        raise ValueError("screen used a different discovery contract")
    selection_body = dict(selection)
    selection_identity = str(selection_body.pop("selection_identity_sha256", ""))
    if canonical_sha256(selection_body) != selection_identity:
        raise ValueError("selection identity mismatch")
    if manifest.get("selection_identity_sha256") != selection_identity:
        raise ValueError("screen manifest does not bind the selected candidate")
    if selection.get("decision") != "candidate_selected_for_locked_test":
        raise ValueError("screen did not select a locked-test candidate")
    if selection.get("locked_test_metrics_observed") is not False:
        raise ValueError("selection was created after locked-test observation")
    return manifest, selection


def _load_cn27_v1_locked_metrics(
    contract: Mapping[str, Any],
    root: Path,
) -> tuple[dict[str, Any], str]:
    identity = contract["identity"]
    manifest_path = (root / str(identity["cn_27_v1_0_manifest"])).resolve()
    if sha256_file(manifest_path) != str(identity["cn_27_v1_0_manifest_file_sha256"]):
        raise ValueError("CN_27 V1.0 baseline manifest file hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    daily_path = manifest_path.parent / "daily.csv"
    if sha256_file(daily_path) != manifest["outputs"]["daily.csv"]:
        raise ValueError("CN_27 V1.0 baseline daily trace hash mismatch")
    daily = pd.read_csv(daily_path, parse_dates=["date"]).set_index("date")
    window = contract["windows"]["locked_test"]
    sample = daily.loc[str(window["start"]) : str(window["end"])]
    if len(sample) != int(window["sessions"]):
        raise ValueError("CN_27 V1.0 baseline locked-test session mismatch")
    metrics = _return_metrics(
        sample["net_return"],
        annual_sessions=252,
        annual_risk_free_rate=0.02,
    )
    metrics["annual_one_way_turnover"] = float(
        sample["one_way_turnover"].sum() / (len(sample) / 252.0)
    )
    metrics["transaction_cost_paid"] = float(sample["transaction_cost"].sum())
    return metrics, sha256_file(daily_path)


def run_locked_holdout(
    contract_path: str | Path,
    screen_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Reveal the locked test once for the immutable screen-selected recipe."""

    contract = load_discovery_contract(contract_path)
    screen = Path(screen_dir).resolve()
    screen_manifest, selection = _load_sealed_selection(
        screen,
        expected_experiment_contract_sha256=sha256_file(contract.spec_path),
    )
    selected_id = str(selection["selected_recipe_id"])
    recipe = next(
        row for row in contract.spec["candidate_recipes"] if str(row["id"]) == selected_id
    )
    if recipe != selection["selected_recipe"]:
        raise ValueError("sealed recipe differs from the frozen experiment contract")

    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_discovery_features(bars, contract)
    locked_end = str(contract.spec["windows"]["locked_test"]["end"])
    window_names = ("development", "selection_validation", "locked_test")
    primary = run_discovery_recipe(
        bars,
        features,
        contract,
        recipe,
        end_date=locked_end,
        window_names=window_names,
    )
    stress = run_discovery_recipe(
        bars,
        features,
        contract,
        recipe,
        end_date=locked_end,
        window_names=window_names,
        cost_multiplier=float(contract.spec["costs"]["stress_multiplier"]),
    )
    root = contract.spec_path.parents[2]
    baseline_metrics, baseline_daily_sha = _load_cn27_v1_locked_metrics(contract.spec, root)
    locked = primary.metrics_by_window["locked_test"]
    locked_stress = stress.metrics_by_window["locked_test"]
    gate = contract.spec["locked_test_gate"]
    gate_results = {
        "minimum_sharpe_log_excess": (
            locked["sharpe_log_excess"] >= float(gate["minimum_sharpe_log_excess"])
        ),
        "maximum_annual_one_way_turnover": (
            locked["annual_one_way_turnover"] <= float(gate["maximum_annual_one_way_turnover"])
        ),
        "maximum_drawdown_magnitude": (
            abs(locked["maximum_drawdown"]) <= float(gate["maximum_drawdown_magnitude"])
        ),
        "stress_cost_minimum_sharpe_log_excess": (
            locked_stress["sharpe_log_excess"]
            >= float(gate["stress_cost_minimum_sharpe_log_excess"])
        ),
        "outperform_cn_27_v1_0_sharpe": (
            locked["sharpe_log_excess"] > baseline_metrics["sharpe_log_excess"]
        ),
    }
    passed = all(gate_results.values())
    decision = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": (
            str(gate["target_decision"])
            if passed
            else "cn_27_sharpe_1_candidate_not_supported"
        ),
        "selected_recipe_id": selected_id,
        "locked_test_opened": True,
        "locked_test_opened_after_sealed_selection": True,
        "locked_test_gate_results": gate_results,
        "all_locked_test_gates_passed": passed,
        "fresh_historical_holdout": False,
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }
    metrics = {
        "schema_version": "1.0",
        "selected_recipe_id": selected_id,
        "primary_by_window": primary.metrics_by_window,
        "double_cost_by_window": stress.metrics_by_window,
        "cn_27_v1_0_locked_test": baseline_metrics,
    }

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    primary.daily.reset_index().to_csv(
        output / "selected_daily.csv", index=False, date_format="%Y-%m-%d"
    )
    stress.daily.reset_index().to_csv(
        output / "selected_double_cost_daily.csv", index=False, date_format="%Y-%m-%d"
    )
    write_json(output / "metrics.json", metrics)
    write_json(output / "decision.json", decision)
    outputs = {
        name: sha256_file(output / name)
        for name in (
            "selected_daily.csv",
            "selected_double_cost_daily.csv",
            "metrics.json",
            "decision.json",
        )
    }
    identity = discovery_identity(contract)
    identity.update(
        {
            "holdout_implementation_sha256": sha256_file(Path(__file__)),
            "screen_manifest_file_sha256": sha256_file(screen / "evidence_manifest.json"),
            "screen_manifest_identity_sha256": screen_manifest["manifest_identity_sha256"],
            "selection_identity_sha256": selection["selection_identity_sha256"],
            "cn_27_v1_0_daily_sha256": baseline_daily_sha,
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "stage": "locked_test_one_shot",
        "identity": identity,
        "outputs": outputs,
        "decision": decision["decision"],
        "research_only": True,
        "trade_ready": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(output / "evidence_manifest.json", manifest)
    return {
        "decision": decision["decision"],
        "selected_recipe_id": selected_id,
        "locked_test": locked,
        "double_cost_locked_test": locked_stress,
        "baseline_locked_test": baseline_metrics,
        "gate_results": gate_results,
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "research_only": True,
        "trade_ready": False,
    }
