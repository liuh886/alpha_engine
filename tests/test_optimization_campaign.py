from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from src.data.model_data_bundle import ComponentSpec, build_model_data_bundle
from src.research.optimization_campaign import (
    OptimizationCampaignError,
    compile_optimization_campaign,
    verify_compiled_optimization_campaign,
)


def _write_yaml(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    for raw in (
        "src/research/cross_sectional_experiment_runner.py",
        "src/research/experiment_harness.py",
        "src/research/xgb_native_calibration.py",
        "src/research/optimization_campaign.py",
        "uv.lock",
    ):
        runtime_file = root / raw
        runtime_file.parent.mkdir(parents=True, exist_ok=True)
        runtime_file.write_text(f"fixture runtime: {raw}\n", encoding="utf-8")
    factor = _write_yaml(root / "configs/factors.yaml", {"library_id": "fixture"})
    frozen = _write_yaml(root / "configs/frozen.yaml", {"model_id": "fixture"})
    base = _write_yaml(
        root / "configs/base.yaml",
        {
            "schema_version": "1.0",
            "experiment_id": "base_experiment",
            "runner": "cross_sectional_xgb_ranker_v1",
            "active": False,
            "research_only": True,
            "trade_ready": False,
            "snapshot": {
                "provider_identity_sha256": "a" * 64,
                "cutoff": "2026-07-31",
            },
            "fixed_model": {
                "model_id": "us_x1_1",
                "frozen_spec": "configs/frozen.yaml",
            },
            "factor_library": {"source": "configs/factors.yaml"},
            "candidates": [
                {
                    "candidate_id": "baseline",
                    "role": "baseline",
                    "factor_groups": ["core"],
                    "xgb_native": {
                        "learning_rate": 0.05,
                        "colsample_bytree": 0.8,
                        "seed": 42,
                    },
                },
                {
                    "candidate_id": "template",
                    "role": "challenger",
                    "factor_groups": ["core", "risk"],
                    "xgb_native": {
                        "learning_rate": 0.05,
                        "colsample_bytree": 0.8,
                        "seed": 42,
                    },
                },
            ],
            "windows": {
                "candidate_selection": ["2024H1", "2024H2"],
                "consumed_reporting_only": ["2025H1"],
                "consumed_reporting_may_enter_selection": False,
            },
            "execution": {"base_cost_bps": 20, "cost_stress_bps": [20, 30]},
            "evaluation": {
                "baseline_candidate_id": "baseline",
                "stress_cost_bps": 30,
                "decision": "propose_only",
            },
        },
    )
    data_contract = _write_yaml(
        root / "configs/data-contract.yaml",
        {
            "schema_version": "1.0",
            "contract_id": "fixture_model_data",
            "profiles": {
                "us_price_ready": {
                    "market": "us",
                    "candidate_pool_id": "fixture",
                    "candidate_symbols": ["AAPL"],
                    "references": [],
                    "required_components": [
                        {
                            "component_id": "factors.fixture",
                            "accepted_statuses": ["ready"],
                            "minimum_coverage_ratio": 1.0,
                        }
                    ],
                }
            },
        },
    )
    component = root / "data/price-component.json"
    component.parent.mkdir(parents=True, exist_ok=True)
    component.write_text(
        json.dumps(
            {
                "component_id": "factors.fixture",
                "component_kind": "selected_pool_prices",
                "status": "ready",
                "market": "us",
                "pool_id": "fixture",
                "evidence_cutoff": "2026-07-31",
                "expected_symbol_count": 1,
                "ready_symbol_count": 1,
                "coverage_ratio": 1.0,
                "missing_symbols": [],
                "invalid_symbols": [],
                "quarantined_symbols": [],
                "providers": ["fixture"],
                "details": {"provider_identity_sha256": "a" * 64},
                "research_only": True,
                "trade_ready": False,
            }
        ),
        encoding="utf-8",
    )
    model_data_root = root / "data/model-data"
    bundle = build_model_data_bundle(
        root=root,
        contract_path=data_contract,
        component_specs=[
            ComponentSpec(
                "factors.fixture",
                "selected_pool_prices",
                component,
                "us",
            )
        ],
        output_root=model_data_root,
        evidence_cutoff="2026-07-31",
    )
    campaign = _write_yaml(
        root / "configs/campaign.yaml",
        {
            "schema_version": "1.0",
            "campaign_id": "us_x1_2_agent_tuning",
            "research_only": True,
            "trade_ready": False,
            "base_experiment": {
                "path": "configs/base.yaml",
                "sha256": _sha256(base),
            },
            "immutable_files": [
                {"path": "configs/factors.yaml", "sha256": _sha256(factor)},
                {"path": "configs/frozen.yaml", "sha256": _sha256(frozen)},
            ],
            "model_data_bundle": {
                "root": "data/model-data",
                "bundle_id": bundle["bundle_id"],
                "required_ready_profiles": ["us_price_ready"],
            },
            "baseline_candidate_id": "baseline",
            "candidate_template_id": "template",
            "max_challengers": 4,
            "search_space": {
                "factor_groups": [["core"], ["core", "risk"]],
                "xgb_native": {
                    "learning_rate": [0.03, 0.05],
                    "colsample_bytree": [0.8, 1.0],
                },
            },
        },
    )
    submissions = _write_yaml(
        root / "configs/submissions.yaml",
        {
            "schema_version": "1.0",
            "campaign_id": "us_x1_2_agent_tuning",
            "research_only": True,
            "trade_ready": False,
            "candidates": [
                {
                    "candidate_id": "agent_a_lower_lr",
                    "xgb_native": {"learning_rate": 0.03},
                },
                {
                    "candidate_id": "agent_b_full_columns",
                    "factor_groups": ["core"],
                    "xgb_native": {"colsample_bytree": 1.0},
                },
            ],
        },
    )
    return root, campaign, submissions, factor


def test_campaign_compiles_all_agents_into_one_fixed_context(tmp_path: Path) -> None:
    root, campaign, submissions, _ = _fixture(tmp_path)
    compiled = compile_optimization_campaign(
        campaign.relative_to(root),
        submissions.relative_to(root),
        tmp_path / "output",
        repository_root=root,
    )

    spec = yaml.safe_load(compiled.compiled_spec_path.read_text(encoding="utf-8"))
    assert [row["candidate_id"] for row in spec["candidates"]] == [
        "baseline",
        "agent_a_lower_lr",
        "agent_b_full_columns",
    ]
    assert {row["xgb_native"]["seed"] for row in spec["candidates"]} == {42}
    assert spec["windows"]["candidate_selection"] == ["2024H1", "2024H2"]
    assert spec["optimization_campaign"]["context_sha256"] == compiled.context_sha256
    assert spec["optimization_campaign"]["automatic_promotion"] is False
    assert len(set(compiled.candidate_trial_ids.values())) == 2
    verified = verify_compiled_optimization_campaign(
        compiled.manifest_path,
        repository_root=root,
    )
    assert verified["candidate_count"] == 2


def test_campaign_rejects_immutable_context_drift(tmp_path: Path) -> None:
    root, campaign, submissions, factor = _fixture(tmp_path)
    factor.write_text("library_id: drifted\n", encoding="utf-8")

    with pytest.raises(OptimizationCampaignError, match="immutable file drift"):
        compile_optimization_campaign(
            campaign.relative_to(root),
            submissions.relative_to(root),
            tmp_path / "output",
            repository_root=root,
        )


def test_campaign_rejects_forbidden_agent_delta(tmp_path: Path) -> None:
    root, campaign, submissions, _ = _fixture(tmp_path)
    payload = yaml.safe_load(submissions.read_text(encoding="utf-8"))
    payload["candidates"][0]["snapshot"] = {"cutoff": "2026-08-01"}
    _write_yaml(submissions, payload)

    with pytest.raises(OptimizationCampaignError, match="forbidden fields"):
        compile_optimization_campaign(
            campaign.relative_to(root),
            submissions.relative_to(root),
            tmp_path / "output",
            repository_root=root,
        )


def test_campaign_rejects_duplicate_computation(tmp_path: Path) -> None:
    root, campaign, submissions, _ = _fixture(tmp_path)
    payload = yaml.safe_load(submissions.read_text(encoding="utf-8"))
    payload["candidates"][1] = {
        "candidate_id": "agent_b_duplicate",
        "xgb_native": {"learning_rate": 0.03},
    }
    _write_yaml(submissions, payload)

    with pytest.raises(OptimizationCampaignError, match="waste computation"):
        compile_optimization_campaign(
            campaign.relative_to(root),
            submissions.relative_to(root),
            tmp_path / "output",
            repository_root=root,
        )


def test_campaign_rejects_candidate_identical_to_frozen_baseline(
    tmp_path: Path,
) -> None:
    root, campaign, submissions, _ = _fixture(tmp_path)
    payload = yaml.safe_load(submissions.read_text(encoding="utf-8"))
    payload["candidates"] = [
        {
            "candidate_id": "agent_baseline_clone",
            "factor_groups": ["core"],
            "xgb_native": {"learning_rate": 0.05},
        }
    ]
    _write_yaml(submissions, payload)

    with pytest.raises(OptimizationCampaignError, match="waste computation"):
        compile_optimization_campaign(
            campaign.relative_to(root),
            submissions.relative_to(root),
            tmp_path / "output",
            repository_root=root,
        )


def test_compiled_manifest_detects_optimizer_runtime_drift(tmp_path: Path) -> None:
    root, campaign, submissions, _ = _fixture(tmp_path)
    compiled = compile_optimization_campaign(
        campaign.relative_to(root),
        submissions.relative_to(root),
        tmp_path / "output",
        repository_root=root,
    )
    (root / "src/research/cross_sectional_experiment_runner.py").write_text(
        "changed runtime\n", encoding="utf-8"
    )

    with pytest.raises(OptimizationCampaignError, match="runtime identity drift"):
        verify_compiled_optimization_campaign(
            compiled.manifest_path,
            repository_root=root,
        )


def test_compiled_manifest_detects_spec_tampering(tmp_path: Path) -> None:
    root, campaign, submissions, _ = _fixture(tmp_path)
    compiled = compile_optimization_campaign(
        campaign.relative_to(root),
        submissions.relative_to(root),
        tmp_path / "output",
        repository_root=root,
    )
    compiled.compiled_spec_path.write_text(
        compiled.compiled_spec_path.read_text(encoding="utf-8") + "# changed\n",
        encoding="utf-8",
    )

    with pytest.raises(OptimizationCampaignError, match="hash mismatch"):
        verify_compiled_optimization_campaign(
            compiled.manifest_path,
            repository_root=root,
        )


def test_research_workflow_runs_campaign_as_two_verified_phases() -> None:
    workflow = Path(".github/workflows/research-experiment.yml").read_text(
        encoding="utf-8"
    )
    assert "campaign:" in workflow
    assert "submissions:" in workflow
    assert workflow.count("scripts/run_model_optimization_campaign.py") == 4
    assert '--spec "$output/compiled-experiment.yaml"' in workflow
    assert '--manifest "$output/campaign-manifest.json"' in workflow
    assert "artifacts/model_optimization_campaigns/" in workflow
