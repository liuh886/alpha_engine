from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.data.check_model_data_profile import check_profile
from src.data.model_data_bundle import (
    ComponentSpec,
    ModelDataBundleError,
    build_model_data_bundle,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _contract(tmp_path: Path, *, minimum_coverage: float = 1.0) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "contract_id": "profile_gate_fixture",
                "profiles": {
                    "fixture_training": {
                        "market": "us",
                        "candidate_pool_id": "fixture_pool",
                        "candidate_symbols": ["AAA", "BBB"],
                        "references": ["QQQ"],
                        "required_components": [
                            {
                                "component_id": "fixture.prices",
                                "accepted_statuses": ["ready", "partial"],
                                "minimum_coverage_ratio": minimum_coverage,
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _component(
    tmp_path: Path,
    *,
    status: str = "ready",
    ready: int = 2,
) -> Path:
    return _write_json(
        tmp_path / "component.json",
        {
            "component_id": "fixture.prices",
            "component_kind": "selected_pool_prices",
            "status": status,
            "market": "us",
            "pool_id": "fixture_pool",
            "evidence_cutoff": "2026-06-18",
            "expected_symbol_count": 2,
            "ready_symbol_count": ready,
            "coverage_ratio": ready / 2,
            "missing_symbols": [] if ready == 2 else ["BBB"],
            "invalid_symbols": [],
            "quarantined_symbols": [],
            "providers": ["fixture"],
            "research_only": True,
            "trade_ready": False,
        },
    )


def _build(
    tmp_path: Path,
    *,
    minimum_coverage: float = 1.0,
    status: str = "ready",
    ready: int = 2,
) -> Path:
    output = tmp_path / "bundle"
    build_model_data_bundle(
        root=Path.cwd(),
        contract_path=_contract(tmp_path, minimum_coverage=minimum_coverage),
        component_specs=[
            ComponentSpec(
                component_id="fixture.prices",
                component_kind="selected_pool_prices",
                manifest_path=_component(tmp_path, status=status, ready=ready),
                market="us",
            )
        ],
        output_root=output,
        evidence_cutoff="2026-06-18",
    )
    return output


def test_ready_profile_returns_verified_training_identity(tmp_path: Path) -> None:
    output = _build(tmp_path)

    result = check_profile(
        output,
        "fixture_training",
        expected_pool_id="fixture_pool",
        maximum_evidence_cutoff="2026-06-18",
    )

    assert result["status"] == "ready"
    assert result["candidate_pool_id"] == "fixture_pool"
    assert result["candidate_count"] == 2
    assert result["references"] == ["QQQ"]
    assert result["trade_ready"] is False
    assert result["verified_indexes"] == [
        "data-components.json",
        "model-data-readiness.json",
        "training-profiles.json",
    ]


def test_blocked_profile_prevents_training(tmp_path: Path) -> None:
    output = _build(
        tmp_path,
        minimum_coverage=1.0,
        status="partial",
        ready=1,
    )

    with pytest.raises(ModelDataBundleError, match="training profile is blocked"):
        check_profile(output, "fixture_training")


def test_profile_gate_rejects_pool_mismatch(tmp_path: Path) -> None:
    output = _build(tmp_path)

    with pytest.raises(ModelDataBundleError, match="pool mismatch"):
        check_profile(
            output,
            "fixture_training",
            expected_pool_id="different_pool",
        )


def test_profile_gate_rejects_later_bundle_cutoff(tmp_path: Path) -> None:
    output = _build(tmp_path)

    with pytest.raises(ModelDataBundleError, match="cutoff exceeds"):
        check_profile(
            output,
            "fixture_training",
            maximum_evidence_cutoff="2026-06-17",
        )


def test_profile_gate_detects_source_manifest_tampering(tmp_path: Path) -> None:
    output = _build(tmp_path)
    component = tmp_path / "component.json"
    component.write_text(component.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ModelDataBundleError, match="source component hash mismatch"):
        check_profile(output, "fixture_training")
