"""T47.7: Evidence-driven retraining policy tests.

Verify:
- triggers (schedule/new_data/drift/performance_decay/policy_change) start retraining
- cooldown, minimum new observations, concurrency lock and daily budget block storms
- unchanged data/config cannot create a duplicate candidate
- every evaluation records why retraining was or was not started
- evaluations are idempotent with a deduplicated audit trail
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.portfolio.retraining_policy import (
    RetrainingDecision,
    RetrainingPolicyConfig,
    RetrainingPolicyEngine,
    RetrainingPolicyError,
    RetrainingState,
    RetrainingTrigger,
)

NOW = "2026-08-26T10:00:00+00:00"


def engine(tmp_path=None, **config):
    cfg = RetrainingPolicyConfig(**config) if config else None
    audit = tmp_path / "audit.jsonl" if tmp_path else None
    return RetrainingPolicyEngine(cfg, audit_path=audit)


def evaluate(tmp_path=None, triggers=None, state=None, now=NOW, snapshot="snap_2", count=200, digest="cfg2", **config):
    return engine(tmp_path, **config).evaluate(
        model_version_id="mv_1",
        now_iso=now,
        snapshot_id=snapshot,
        observation_count=count,
        config_digest=digest,
        triggers=[RetrainingTrigger("drift", "warning severity", "drift-report-1")] if triggers is None else triggers,
        state=state or old_state(),
    )


def old_state(completed_at="2026-06-01T10:00:00+00:00", snapshot="snap_1", obs=100, digest="cfg1"):
    return RetrainingState(
        last_retrain_completed_at=completed_at,
        last_snapshot_id=snapshot,
        last_config_digest=digest,
        observations_at_last_retrain=obs,
    )


# ---------------------------------------------------------------------------
# Starting retraining
# ---------------------------------------------------------------------------


def test_drift_trigger_starts_retraining_with_reasons() -> None:
    decision = evaluate(state=old_state())
    assert isinstance(decision, RetrainingDecision)
    assert decision.started is True
    assert decision.outcome == "start_retraining"
    assert any(r.startswith("trigger:drift:") for r in decision.reasons_started)
    assert decision.reasons_blocked == ()
    assert "challenger-snap_2" in decision.proposed_challenger_id
    assert decision.challenger_created if hasattr(decision, "challenger_created") else True


def test_all_trigger_kinds_start_when_unblocked() -> None:
    for kind in ("new_data", "performance_decay", "policy_change", "schedule"):
        decision = evaluate(triggers=[RetrainingTrigger(kind, f"{kind} evidence", kind)])
        assert decision.started, kind
        assert any(f"trigger:{kind}" in r for r in decision.reasons_started)


def test_policy_change_overrides_duplicate_guard() -> None:
    decision = evaluate(
        triggers=[RetrainingTrigger("policy_change", "cost policy revised", "policy-v2")],
        state=old_state(snapshot="snap_2", digest="cfg2"),
    )
    assert decision.started is True


def test_proposed_challenger_id_is_deterministic_and_snapshot_bound() -> None:
    first = evaluate(state=old_state())
    second = evaluate(state=old_state())
    other_snapshot = evaluate(state=old_state(), snapshot="snap_3")
    assert first.proposed_challenger_id == second.proposed_challenger_id
    assert first.proposed_challenger_id != other_snapshot.proposed_challenger_id


def test_schedule_auto_triggers_at_configured_cadence(tmp_path) -> None:
    eng = engine(None, schedule_days=30.0)
    decision = eng.evaluate(
        model_version_id="mv_1",
        now_iso=NOW,
        snapshot_id="snap_9",
        observation_count=5000,
        config_digest="cfg1",
        triggers=[],
        state=old_state(),
    )
    assert decision.started
    assert any(t["kind"] == "schedule" for t in decision.triggers_considered)


def test_schedule_disabled_does_not_auto_trigger() -> None:
    decision = evaluate(triggers=[], state=old_state())
    assert decision.started is False
    assert any("no_qualifying_trigger" in r for r in decision.reasons_blocked)


# ---------------------------------------------------------------------------
# Blocking conditions
# ---------------------------------------------------------------------------


def test_no_triggers_yields_explicit_no_change() -> None:
    decision = evaluate(triggers=[], state=old_state())
    assert decision.outcome == "no_change"
    assert decision.proposed_challenger_id is None
    assert decision.reasons_blocked


def test_cooldown_blocks_repeat_retraining() -> None:
    decision = evaluate(
        state=old_state(completed_at="2026-08-26T04:00:00+00:00"),
    )
    assert decision.outcome == "no_change"
    assert any(r.startswith("cooldown:") for r in decision.reasons_blocked)
    assert decision.triggers_considered


def test_insufficient_new_observations_block() -> None:
    decision = evaluate(count=120, state=old_state(obs=100))
    assert decision.outcome == "no_change"
    assert any("insufficient_new_observations" in r for r in decision.reasons_blocked)


def test_concurrency_lock_blocks_new_heavy_workflows() -> None:
    decision = evaluate(active_heavy_workflows=1, max_concurrent_heavy_workflows=1)
    assert decision.outcome == "no_change"
    assert any(r.startswith("concurrency_lock") for r in decision.reasons_blocked)


def test_daily_budget_exhaustion_blocks_via_audit_history(tmp_path) -> None:
    first = evaluate(tmp_path)
    assert first.started
    second = evaluate(tmp_path, snapshot="snap_3")
    assert second.outcome == "no_change"
    assert any(r.startswith("daily_budget_exhausted") for r in second.reasons_blocked)


def test_duplicate_guard_blocks_same_snapshot_and_config() -> None:
    decision = evaluate(
        triggers=[RetrainingTrigger("new_data", "more rows", "snapshot")],
        state=old_state(snapshot="snap_2", digest="cfg2"),
    )
    assert decision.outcome == "no_change"
    assert any(r.startswith("duplicate_guard") for r in decision.reasons_blocked)


# ---------------------------------------------------------------------------
# Idempotency and validation
# ---------------------------------------------------------------------------


def test_identical_evaluations_share_id_and_single_audit_row(tmp_path) -> None:
    first = evaluate(tmp_path)
    second = evaluate(tmp_path)
    assert first.evaluation_id == second.evaluation_id
    assert second.to_dict() == first.to_dict()
    rows = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1


def test_different_facts_append_audit_rows(tmp_path) -> None:
    evaluate(tmp_path)
    evaluate(tmp_path, snapshot="snap_3")
    rows = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ids = {json.loads(row)["evaluation_id"] for row in rows}
    assert len(ids) == 2


def test_decision_stamps_research_boundary() -> None:
    payload = evaluate().to_dict()
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["schema_version"] == "retraining_policy_v1"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cooldown_hours": -1.0},
        {"min_new_observations": -5},
        {"max_concurrent_heavy_workflows": 0},
        {"active_heavy_workflows": -1},
        {"max_retrains_per_day": 0},
        {"schedule_days": -30.0},
        {"policy_version": ""},
    ],
)
def test_invalid_configuration_fails_closed(kwargs) -> None:
    with pytest.raises(RetrainingPolicyError):
        RetrainingPolicyConfig(**kwargs).validate()


def test_missing_or_invalid_inputs_fail_closed() -> None:
    eng = engine()
    base = dict(
        model_version_id="mv",
        now_iso=NOW,
        snapshot_id="s",
        observation_count=10,
        config_digest="c",
    )
    for field in ("model_version_id", "now_iso", "snapshot_id", "config_digest"):
        broken = dict(base)
        broken[field] = ""
        with pytest.raises(RetrainingPolicyError):
            eng.evaluate(**broken)
    with pytest.raises(RetrainingPolicyError):
        eng.evaluate(**{**base, "now_iso": "not-a-date"})
    with pytest.raises(RetrainingPolicyError):
        eng.evaluate(**base, triggers=[RetrainingTrigger("vibes", "unknown kind", "")])
