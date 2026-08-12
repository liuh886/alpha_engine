from pathlib import Path

from scripts.factors.audit_existing_factor_assets import audit


def test_factor_asset_inventory_preserves_exact_public_set_decision() -> None:
    payload = audit(Path.cwd())

    assert payload["inventory_id"] == "factor_asset_inventory_v1"
    assert payload["alpha158_intended_public_set"] is True
    assert payload["alpha158_canonical_maintained"] is True
    assert payload["alpha161_alias_allowed"] is False
    assert payload["legacy261_claim_preserved"] is True
    assert payload["asset_count"] >= 8
    assert payload["present_asset_count"] >= 6

    alpha158 = next(
        row
        for row in payload["assets"]
        if row["path"] == "src/factors/sets/qlib_alpha158.py"
    )
    assert alpha158["asset_type"] == "canonical_factor_library_source"
    assert alpha158["formula_recovery_status"] == "canonical_maintained"
    assert len(alpha158["sha256"]) == 64


def test_inventory_does_not_claim_old_files_are_complete_formulas() -> None:
    payload = audit(Path.cwd())

    historical = [
        row
        for row in payload["assets"]
        if row["asset_type"] != "canonical_factor_library_source"
    ]
    assert all(
        row["formula_recovery_status"]
        in {"requires_content_classification", "not_present_in_checkout"}
        for row in historical
    )
    assert "historical" in payload["interpretation"]
