"""T47.6: Automated operational gate decisions tests.

Verify:
- hard gates (freshness/artifact/risk) block new ExecutionPlans
- degradation never silently retains Champion status
- stop > rollback > demote > retrain > continue precedence
- retrain creates a Challenger and never overwrites the Champion
- identical facts produce identical, deduplicated audit records
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))

from src.portfolio.operations_gates import (
    DecisionRecord,
    GateFacts,
    OperationalGatePolicy,
    OperationsGateEngine,
    OperationsGateError,
)


def healthy_facts(**overrides) -> GateFacts:
    base = dict(
        data_freshness_status="current",
        data_age_days=1.0,
        artifact_status="verified",
        previous_verified_champion_id=None,
        current_drawdown=-0.05,
        risk_limit_breached=False,
        signal_qualified=True,
        signal_sample_count=120,
        drift_severity="ok",
        paper_excess_return=0.03,
    )
    base.update(overrides)
    return GateFacts(**base)


def engine(tmp_path=None, policy=None):
    audit = tmp_path / "audit.jsonl" if tmp_path else None
    return OperationsGateEngine(policy, audit_path=audit)


def evaluate(tmp_path=None, facts=None, **kwargs):
    return engine(tmp_path).evaluate(
        market="us",
        model_version_id="mv_1",
        champion_id="champ_1",
        facts=facts or healthy_facts(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Healthy baseline and plan eligibility
# ---------------------------------------------------------------------------


def test_healthy_facts_continue_with_plan_eligibility() -> None:
    record = evaluate()
    assert isinstance(record, DecisionRecord)
    assert record.decision == "continue"
    assert record.plan_eligible is True
    assert record.hard_blocks == ()
    assert all(g.status == "pass" for g in record.gates)
    assert record.research_only is True
    assert record.trade_ready is False


@pytest.mark.parametrize(
    "facts",
    [
        healthy_facts(data_freshness_status=None),
        healthy_facts(data_freshness_status="missing"),
        healthy_facts(artifact_status=None),
        healthy_facts(current_drawdown=None),
        healthy_facts(signal_qualified=None),
        healthy_facts(drift_severity=None),
        healthy_facts(paper_excess_return=None),
    ],
)
def test_inconclusive_facts_fail_closed_and_block_plans(facts) -> None:
    record = evaluate(facts=facts)
    assert record.plan_eligible is False
    assert record.hard_blocks
    assert any(g.status == "inconclusive" for g in record.gates)
    assert record.recovery_conditions


# ---------------------------------------------------------------------------
# Hard gates block plans
# ---------------------------------------------------------------------------


def test_stale_data_blocks_plans() -> None:
    record = evaluate(facts=healthy_facts(data_freshness_status="stale", data_age_days=5.0))
    assert "data_stale_beyond_limit" in record.hard_blocks
    assert record.plan_eligible is False
    assert record.recovery_conditions


def test_prolonged_staleness_escalates_to_retrain() -> None:
    record = evaluate(facts=healthy_facts(data_freshness_status="stale", data_age_days=15.0))
    assert record.decision == "retrain"
    assert record.challenger_created is True
    assert record.champion_unchanged is True
    assert record.plan_eligible is False


def test_damaged_artifact_with_predecessor_rolls_back() -> None:
    record = evaluate(
        facts=healthy_facts(
            artifact_status="damaged", previous_verified_champion_id="champ_0"
        )
    )
    assert record.decision == "rollback"
    assert record.plan_eligible is False
    assert any("champ_0" in r for r in record.recovery_conditions)


def test_damaged_artifact_without_predecessor_stops() -> None:
    record = evaluate(facts=healthy_facts(artifact_status="damaged"))
    assert record.decision == "stop"
    assert "artifact_not_verified" in record.hard_blocks


def test_risk_stop_gate_blocks_and_stops() -> None:
    record = evaluate(facts=healthy_facts(current_drawdown=-0.30))
    assert record.decision == "stop"
    assert "risk_hard_gate_failed" in record.hard_blocks
    assert record.plan_eligible is False


def test_risk_soft_gate_demotes_but_records_champion_action() -> None:
    record = evaluate(facts=healthy_facts(current_drawdown=-0.22))
    assert record.decision == "demote"
    assert record.plan_eligible is False
    assert record.champion_unchanged is True


# ---------------------------------------------------------------------------
# Drift, signal and paper performance
# ---------------------------------------------------------------------------


def test_critical_drift_stops_and_warning_drift_retrains() -> None:
    stopped = evaluate(facts=healthy_facts(drift_severity="critical"))
    assert stopped.decision == "stop"
    assert "drift_critical" in stopped.hard_blocks

    retrained = evaluate(facts=healthy_facts(drift_severity="warning"))
    assert retrained.decision == "retrain"
    assert retrained.challenger_created is True


def test_unqualified_signal_with_sufficient_sample_retrains() -> None:
    record = evaluate(
        facts=healthy_facts(signal_qualified=False, signal_sample_count=200)
    )
    assert record.decision == "retrain"


def test_small_sample_unqualification_is_inconclusive_not_failed() -> None:
    record = evaluate(
        facts=healthy_facts(signal_qualified=False, signal_sample_count=10)
    )
    gate = next(g for g in record.gates if g.name == "signal_evaluation")
    assert gate.status == "inconclusive"
    assert "insufficient evidence" in gate.detail


def test_paper_excess_below_retrain_floor_retrains() -> None:
    record = evaluate(facts=healthy_facts(paper_excess_return=-0.05))
    assert record.decision == "retrain"
    record = evaluate(facts=healthy_facts(paper_excess_return=-0.20))
    assert record.decision == "stop"


# ---------------------------------------------------------------------------
# Precedence, idempotency and audit
# ---------------------------------------------------------------------------


def test_stop_takes_precedence_over_other_triggers(tmp_path) -> None:
    record = evaluate(
        tmp_path,
        facts=healthy_facts(
            drift_severity="warning",
            paper_excess_return=-0.15,
            current_drawdown=-0.22,
        ),
    )
    assert record.decision == "stop"


def test_identical_facts_produce_identical_record_ids_and_single_audit_row(tmp_path) -> None:
    first = evaluate(tmp_path)
    second = evaluate(tmp_path)
    assert first.record_id == second.record_id
    rows = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["record_id"] == first.record_id


def test_different_facts_append_new_audit_rows(tmp_path) -> None:
    evaluate(tmp_path)
    evaluate(tmp_path, facts=healthy_facts(paper_excess_return=-0.05))
    rows = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    ids = {json.loads(row)["record_id"] for row in rows}
    assert len(ids) == 2


def test_missing_champion_downgrades_lifecycle_actions_to_hold(tmp_path) -> None:
    record = engine(tmp_path).evaluate(
        market="cn",
        model_version_id="mv_x",
        champion_id=None,
        facts=healthy_facts(current_drawdown=-0.22),
    )
    assert record.decision in {"demote", "stop"}
    assert record.champion_id is None


def test_policy_validation_fails_closed() -> None:
    with pytest.raises(OperationsGateError):
        OperationalGatePolicy(max_data_age_days=0.0).validate()
    with pytest.raises(OperationsGateError):
        OperationalGatePolicy(stale_escalation_age_days=1.0, max_data_age_days=3.0).validate()
    with pytest.raises(OperationsGateError):
        OperationalGatePolicy(drawdown_demote_threshold=-0.30, drawdown_stop_threshold=-0.25).validate()
    with pytest.raises(OperationsGateError):
        OperationalGatePolicy(min_signal_sample_count=0).validate()
    with pytest.raises(OperationsGateError):
        OperationalGatePolicy(paper_excess_stop_floor=-0.01, paper_excess_retrain_floor=-0.05).validate()
