from pathlib import Path

from scripts.factors.audit_existing_factor_assets import audit


def test_factor_asset_inventory_preserves_exact_public_set_decision() -> None:
    payload = audit(Path.cwd())

    assert payload["inventory_id"] == "factor_asset_inventory_v1"
    assert payload["alpha158_intended_public_set"] is True
    assert payload["alpha161_alias_allowed"] is False
    assert payload["legacy261_claim_preserved"] is True
    assert payload["asset_count"] >= 7
    assert payload["present_asset_count"] >= 5


def test_inventory_does_not_claim_old_files_are_complete_formulas() -> None:
    payload = audit(Path.cwd())

    assert all(
        row["formula_recovery_status"]
        in {"requires_content_classification", "not_present_in_checkout"}
        for row in payload["assets"]
    )
    assert "does not prove" in payload["interpretation"]
