from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file


ROOT = Path(__file__).resolve().parents[1]
CHALLENGER = ROOT / "configs/research_candidates/cn_27_v1_3_prospective_challenger.yaml"


@pytest.mark.parametrize(
    ("evidence_dir", "contract", "implementation", "expected_decision"),
    [
        (
            "cn_27_v1_3_concentration_discovery_v1",
            "configs/research_experiments/cn_27_v1_3_concentration_discovery_v1.yaml",
            "src/research/cn27_v1_3.py",
            "no_concentration_governed_candidate_passed_frozen_gate",
        ),
        (
            "cn_27_v1_3_staggered_sleeve_discovery_v1",
            "configs/research_experiments/cn_27_v1_3_staggered_sleeve_discovery_v1.yaml",
            "src/research/cn27_v1_3_staggered.py",
            "no_staggered_candidate_passed_frozen_gate",
        ),
        (
            "cn_27_v1_3_projected_concentration_discovery_v1",
            "configs/research_experiments/cn_27_v1_3_projected_concentration_discovery_v1.yaml",
            "src/research/cn27_v1_3_projected.py",
            "no_projected_candidate_passed_frozen_gate",
        ),
    ],
)
def test_v1_3_discovery_evidence_is_hash_bound_and_records_failure(
    evidence_dir: str,
    contract: str,
    implementation: str,
    expected_decision: str,
) -> None:
    artifact_dir = ROOT / "artifacts/evidence" / evidence_dir
    manifest_path = artifact_dir / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = dict(manifest)
    identity = body.pop("manifest_identity_sha256")

    assert canonical_sha256(body) == identity
    assert manifest["identity"]["contract_sha256"] == sha256_file(ROOT / contract)
    assert manifest["identity"]["implementation_sha256"] == sha256_file(
        ROOT / implementation
    )
    assert manifest["decision"] == expected_decision
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False
    for filename, expected_sha256 in manifest["outputs"].items():
        assert sha256_file(artifact_dir / filename) == expected_sha256


def test_v1_3_challenger_is_not_misclassified_as_formal_model() -> None:
    spec = yaml.safe_load(CHALLENGER.read_text(encoding="utf-8"))

    assert spec["status"] == "historical_gate_failed_prospective_observation_only"
    assert spec["research_only"] is True
    assert spec["trade_ready"] is False
    assert spec["promotion_authorized"] is False
    assert spec["decision"]["formal_v1_3_created"] is False
    assert spec["prospective_protocol"]["parameter_mutation_allowed"] is False
    assert spec["prospective_protocol"]["minimum_calendar_months"] == 12
    assert not (ROOT / "configs/research_paradigms/cn_27_v1_3.yaml").exists()


def test_v1_3_challenger_lineage_and_metrics_match_projected_evidence() -> None:
    spec = yaml.safe_load(CHALLENGER.read_text(encoding="utf-8"))
    lineage = spec["lineage"]
    contract = ROOT / lineage["discovery_contract"]
    manifest_path = ROOT / lineage["discovery_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = dict(manifest)
    identity = body.pop("manifest_identity_sha256")

    assert sha256_file(contract) == lineage["discovery_contract_sha256"]
    assert sha256_file(manifest_path) == lineage["discovery_manifest_file_sha256"]
    assert canonical_sha256(body) == identity == lineage["discovery_manifest_identity_sha256"]
    assert manifest["decision"] == "no_projected_candidate_passed_frozen_gate"
    summary = pd.read_csv(manifest_path.parent / "candidate_summary.csv")
    row = summary.loc[summary["recipe_id"].eq(spec["frozen_challenger"]["recipe_id"])].iloc[0]
    audit = spec["historical_audit"]
    expected = {
        "full_sharpe_log_excess": "full_sharpe_log_excess",
        "maximum_drawdown": "full_maximum_drawdown",
        "annual_one_way_turnover": "full_annual_one_way_turnover",
        "double_cost_sharpe_log_excess": "double_cost_full_sharpe",
        "fold_sharpe_25th_percentile": "fold_sharpe_25th_percentile",
        "parameter_neighborhood_minimum_sharpe": "parameter_neighborhood_minimum_sharpe",
        "leave_one_sector_out_minimum_sharpe": "leave_one_sector_out_minimum_sharpe",
        "maximum_post_drift_sector_equity_sleeve_share": "maximum_post_drift_sector_equity_sleeve_share",
        "post_drift_effective_names_median": "post_drift_effective_names_median",
        "bootstrap_probability_sharpe_above_one": "bootstrap_probability_sharpe_above_one",
    }
    for audit_key, column in expected.items():
        assert np.isclose(float(audit[audit_key]), float(row[column]), atol=5e-10)
    assert row["failure_reasons"] == "timing_perturbation_sharpe+bootstrap_p05"
