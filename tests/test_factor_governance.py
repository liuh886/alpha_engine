from __future__ import annotations

import json
from pathlib import Path

from src.factors.governance import build_factor_governance_manifest


def _panel(status: str) -> dict[str, object]:
    return {
        "component_id": "factors.qlib_alpha158.panel.cn.v1",
        "status": status,
        "expected_symbol_count": 130,
        "ready_symbol_count": 130 if status == "ready" else 126,
        "coverage_ratio": 1.0 if status == "ready" else 126 / 130,
        "catalog_sha256": "a" * 64,
        "invalid_symbols": [] if status == "ready" else ["000425"],
    }


def test_factor_governance_separates_readiness_from_effectiveness(
    tmp_path: Path,
) -> None:
    output = tmp_path / "factor_governance.json"
    manifest = build_factor_governance_manifest(
        root=Path.cwd(),
        market="cn",
        pool_id="cn_selected_equities_v3",
        evidence_cutoff="2026-07-31",
        factor_panel_manifest=_panel("ready"),
        model_data_manifest={
            "training_profiles": [
                {
                    "profile_id": "cn_selected_alpha158_v1",
                    "status": "ready",
                    "blockers": [],
                }
            ]
        },
        output_path=output,
    )

    assert manifest["formula_catalog"]["factor_count"] == 158
    assert manifest["formula_catalog"]["status_counts"] == {
        "unvalidated_formula": 158
    }
    assert manifest["training_gate"]["status"] == "open_for_frozen_experiment"
    assert manifest["effectiveness_claim"]["status"] == "not_established"
    assert manifest["effectiveness_claim"]["alpha158_validated_factor_count"] == 0
    assert manifest["historical_research_memory"]["factor_count"] == 25
    assert manifest["historical_research_memory"]["supported_factor_count"] == 0
    assert json.loads(output.read_text(encoding="utf-8")) == manifest


def test_factor_governance_blocks_when_panel_is_incomplete(tmp_path: Path) -> None:
    manifest = build_factor_governance_manifest(
        root=Path.cwd(),
        market="cn",
        pool_id="cn_selected_equities_v3",
        evidence_cutoff="2026-07-31",
        factor_panel_manifest=_panel("partial"),
        model_data_manifest=None,
        output_path=tmp_path / "factor_governance.json",
    )
    assert manifest["training_gate"]["status"] == "blocked"
    assert manifest["training_gate"]["blockers"] == [
        "model_data_manifest_missing"
    ]
