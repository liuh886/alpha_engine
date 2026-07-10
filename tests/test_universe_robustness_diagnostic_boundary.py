"""Architecture guard for the historical universe-robustness diagnostic."""

from __future__ import annotations

from pathlib import Path


def test_universe_robustness_runner_cannot_issue_promotion_decisions() -> None:
    source = Path(
        "scripts/run_best_blend_universe_robustness.py"
    ).read_text(encoding="utf-8")

    assert "build_model_decision_pack" not in source
    assert "model_decision_pack_by_universe" not in source
    assert "promotion_eligible" in source
    assert '"diagnostic_only": True' in source
    assert '"trade_ready": False' in source
    assert '"promotion_eligible": False' in source
