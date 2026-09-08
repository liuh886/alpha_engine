from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_v1_3_projected import (
    load_projected_discovery_contract,
    project_minimum_variance_weights,
    run_projected_recipe,
)
from src.research.cn27_v1_2 import compute_v1_2_features


SPEC = "configs/research_experiments/cn_27_v1_3_projected_concentration_discovery_v1.yaml"


def test_projected_contract_is_frozen_and_bound_to_failed_staggered_evidence() -> None:
    contract = load_projected_discovery_contract(SPEC)

    assert contract.spec["fresh_historical_holdout"] is False
    assert contract.spec["objective"]["projection_objective"].startswith("minimum squared")
    assert len(contract.spec["candidate_recipes"]) == 6


def test_minimum_distance_projection_satisfies_all_concentration_constraints() -> None:
    raw = pd.Series({"A": 0.50, "B": 0.25, "C": 0.10, "D": 0.08, "E": 0.07})
    sectors = {"A": "x", "B": "x", "C": "y", "D": "z", "E": "w"}

    projected, diagnostics = project_minimum_variance_weights(
        raw,
        sectors,
        maximum_single_share=0.30,
        maximum_sector_share=0.45,
        minimum_effective_names=4.0,
    )

    assert np.isclose(projected.sum(), 1.0)
    assert diagnostics["maximum_single_share"] <= 0.30 + 1e-8
    assert diagnostics["maximum_sector_share"] <= 0.45 + 1e-8
    assert diagnostics["effective_names"] >= 4.0 - 1e-8
    assert diagnostics["projection_distance"] > 0.0


def test_projected_recipe_runs_full_governed_path() -> None:
    contract = load_projected_discovery_contract(SPEC)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    result = run_projected_recipe(
        bars, features, contract, contract.spec["candidate_recipes"][0]
    )

    assert len(result.daily) == 729
    assert not bool(result.daily["pending_execution"].iloc[-1])
    assert result.daily["target_maximum_sector_share"].dropna().max() <= 0.52 + 1e-8


def test_projected_discovery_evidence_is_hash_bound_negative_result() -> None:
    evidence = "artifacts/evidence/cn_27_v1_3_projected_concentration_discovery_v1"
    manifest = json.loads(open(f"{evidence}/evidence_manifest.json", encoding="utf-8").read())
    body = dict(manifest)
    identity = body.pop("manifest_identity_sha256")

    assert canonical_sha256(body) == identity
    assert manifest["decision"] == "no_projected_candidate_passed_frozen_gate"
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False
    for name, expected in manifest["outputs"].items():
        assert sha256_file(f"{evidence}/{name}") == expected
