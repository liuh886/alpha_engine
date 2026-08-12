from __future__ import annotations

import json
from pathlib import Path

from src.data.model_data_bundle import ComponentSpec, build_model_data_bundle

CONTRACT = Path("configs/data_contracts/model_data_bundle_v1.yaml")
POOL_ID = "cn_selected_equities_v3"
PRICE_ID = "prices.cn_selected_equities_v3"
FACTOR_ID = "factors.qlib_alpha158.panel.cn.v1"


def _write_component(
    path: Path,
    *,
    component_id: str,
    component_kind: str,
    status: str,
    ready: int,
    not_yet_applicable: list[str] | None = None,
    missing: list[str] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "component_id": component_id,
                "component_kind": component_kind,
                "status": status,
                "market": "cn",
                "pool_id": POOL_ID,
                "evidence_cutoff": "2026-07-31",
                "expected_symbol_count": 130,
                "ready_symbol_count": ready,
                "coverage_ratio": ready / 130,
                "not_yet_applicable_symbols": not_yet_applicable or [],
                "missing_symbols": missing or [],
                "invalid_symbols": [],
                "quarantined_symbols": [],
                "providers": ["fixture"],
                "research_only": True,
                "trade_ready": False,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _build(tmp_path: Path, factor_manifest: Path) -> dict:
    price_manifest = _write_component(
        tmp_path / "prices.json",
        component_id=PRICE_ID,
        component_kind="selected_pool_prices",
        status="ready",
        ready=130,
    )
    return build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(PRICE_ID, "selected_pool_prices", price_manifest, "cn"),
            ComponentSpec(FACTOR_ID, "factor_panel", factor_manifest, "cn"),
        ],
        output_root=tmp_path / "output",
        evidence_cutoff="2026-07-31",
    )


def test_cn_alpha158_allows_only_lifecycle_not_yet_applicable(tmp_path: Path) -> None:
    factor_manifest = _write_component(
        tmp_path / "alpha158.json",
        component_id=FACTOR_ID,
        component_kind="factor_panel",
        status="partial",
        ready=129,
        not_yet_applicable=["301666"],
    )
    manifest = _build(tmp_path, factor_manifest)
    profile = next(
        row
        for row in manifest["training_profiles"]
        if row["profile_id"] == "cn_selected_alpha158_v1"
    )
    factor_gate = next(
        row for row in profile["required_components"] if row["component_id"] == FACTOR_ID
    )

    assert profile["status"] == "ready"
    assert profile["failed_gates"] == []
    assert factor_gate["coverage_basis"] == "applicable_symbols"
    assert factor_gate["applicable_coverage_ratio"] == 1.0
    assert factor_gate["observed"]["coverage_ratio"] == 129 / 130
    assert factor_gate["observed"]["not_yet_applicable_symbols"] == ["301666"]


def test_cn_alpha158_still_blocks_real_missing_symbol(tmp_path: Path) -> None:
    factor_manifest = _write_component(
        tmp_path / "alpha158.json",
        component_id=FACTOR_ID,
        component_kind="factor_panel",
        status="partial",
        ready=128,
        not_yet_applicable=["301666"],
        missing=["000001"],
    )
    manifest = _build(tmp_path, factor_manifest)
    profile = next(
        row
        for row in manifest["training_profiles"]
        if row["profile_id"] == "cn_selected_alpha158_v1"
    )

    assert profile["status"] == "blocked"
    assert any(
        "lifecycle_allowance_requires_no_missing_invalid_or_quarantined" in gate
        for gate in profile["failed_gates"]
    )
