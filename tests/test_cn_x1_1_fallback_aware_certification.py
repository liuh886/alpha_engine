from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research.cn_x1_1_fallback_aware_certification import (
    build_certified_decision,
    verify_frozen_economic_identity,
)


def test_certification_replaces_only_all_period_hit_gate() -> None:
    original = {
        "gates": {
            "historical_relative_excess_positive": True,
            "historical_all_period_hit_rate_at_least_50pct": False,
            "risk_off_relative_no_worse_than_cost_drag": True,
        }
    }

    decision = build_certified_decision(
        original,
        active_hit_rate=0.5897,
        frozen_identity_verified=True,
    )

    assert decision["candidate_authorized"]
    assert decision["decision"] == "cn_x1_1_regime_gated_candidate_authorized"
    assert "historical_all_period_hit_rate_at_least_50pct" not in decision["gates"]
    assert decision["gates"]["historical_risk_on_active_hit_rate_at_least_50pct"]
    assert decision["model_rules_changed"] is False
    assert decision["economic_evidence_changed"] is False


def test_certification_fails_when_active_hit_rate_is_below_threshold() -> None:
    original = {
        "gates": {
            "historical_relative_excess_positive": True,
            "historical_all_period_hit_rate_at_least_50pct": False,
            "risk_off_relative_no_worse_than_cost_drag": True,
        }
    }

    decision = build_certified_decision(
        original,
        active_hit_rate=0.49,
        frozen_identity_verified=True,
    )

    assert not decision["candidate_authorized"]
    assert decision["decision"] == "fallback_aware_candidate_gate_failed"


def test_frozen_identity_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "evidence.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="identity mismatch"):
        verify_frozen_economic_identity(
            tmp_path,
            expected={"evidence.csv": "0" * 64},
        )


def test_frozen_identity_accepts_exact_hash(tmp_path: Path) -> None:
    path = tmp_path / "decision.json"
    path.write_text(json.dumps({"ok": True}, sort_keys=True), encoding="utf-8")
    import hashlib

    expected = hashlib.sha256(path.read_bytes()).hexdigest()

    observed = verify_frozen_economic_identity(
        tmp_path,
        expected={"decision.json": expected},
    )

    assert observed == {"decision.json": expected}
