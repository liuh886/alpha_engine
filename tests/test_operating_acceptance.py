from __future__ import annotations

import hashlib
import json

import pytest

from src.artifacts.operating_acceptance import build_acceptance_report


def _observation(root, run_id, day, attempt=1):
    path = root / f"{run_id}-{attempt}" / "operating-observation.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": "operating_observation_v1", "run_id": run_id, "run_attempt": attempt,
        "head_sha": "a" * 40, "research_only": True, "trade_ready": False,
        "expected_cutoffs": {"us": day}, "actual_cutoffs": {"us": day},
        "collection_blockers": [],
    }))
    return path


def test_retries_and_unreviewed_green_runs_do_not_count_as_accepted_sessions(tmp_path):
    _observation(tmp_path, 1, "2026-10-12")
    _observation(tmp_path, 1, "2026-10-12", attempt=2)
    report = build_acceptance_report(tmp_path, through="2026-10-14")
    assert report["observation_count"] == 2
    assert report["markets"]["us"]["observed_sessions"] == 1
    assert report["markets"]["us"]["qualified_sessions"] == 0
    assert report["markets"]["us"]["sessions"][-1]["status"] == "missing"
    assert set(report["manual_interventions"].values()) == {None}


def test_review_requires_exact_observation_and_final_actions_identity(tmp_path):
    path = _observation(tmp_path, 1, "2026-10-14")
    final = tmp_path / "final.json"
    final.write_text(json.dumps({"run": {"id": 1, "run_attempt": 1, "head_sha": "a" * 40, "status": "completed", "conclusion": "success", "path": ".github/workflows/formal-backtest-refresh.yml"}, "jobs": [{"status": "completed"}]}))
    declaration = tmp_path / "reviews.json"
    evidence = {"path": "final.json", "sha256": hashlib.sha256(final.read_bytes()).hexdigest()}
    review = {"1:1": {
        "observation_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "manual_interventions": 0, "reviewed_by": "operator",
        "cadence_and_freshness_verified": True,
        "decision_delivery_evidence": [evidence], "final_actions_metadata": evidence,
    }}
    declaration.write_text(json.dumps(review))
    report = build_acceptance_report(tmp_path, declarations=declaration, through="2026-10-14")
    assert report["markets"]["us"]["qualified_sessions"] == 0
    assert report["markets"]["us"]["twenty_session_evidence_complete"] is False
    review["1:1"]["operations_snapshot"] = evidence
    declaration.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="operations"):
        build_acceptance_report(tmp_path, declarations=declaration, through="2026-10-14")


def test_calendar_holiday_does_not_create_a_fake_gap(tmp_path):
    _observation(tmp_path, 1, "2026-07-02")
    _observation(tmp_path, 2, "2026-07-06")
    report = build_acceptance_report(tmp_path, through="2026-07-06")
    assert [row["session"] for row in report["markets"]["us"]["sessions"]] == ["2026-07-02", "2026-07-06"]


def test_typed_strategy_review_binds_formal_decision_and_delivery(tmp_path):
    from src.artifacts.operating_acceptance import _review_strategies
    from src.artifacts.strategy_signal_ledger import seal_signal_decision, record_signal_delivery
    from tests.test_strategy_signal_ledger import _signal, MODEL

    signal = _signal(signal_date="2026-10-14", target_state=0)
    kwargs = {"ledger_root": tmp_path / "ledger", "model_version_id": MODEL, "signal": signal, "workflow_run_id": "2", "commit_sha": "b" * 40, "created_at_utc": "2026-10-14T21:00:00Z"}
    decision_path = seal_signal_decision(**kwargs)
    delivery_path = record_signal_delivery(**kwargs, delivery_status="not_required")
    decision = json.loads(decision_path.read_text())
    formal = {"model_version_id": MODEL, "bundle_id": "c" * 64, "run_id": "formal-run", "evidence_cutoff": "2026-10-14", "market": "us"}
    operations = {"schema_version": "2.2.0", "generated_at": "2026-10-14T21:00:00Z", "research_only": True, "trade_ready": False, "records": [{
        "strategy_id": "qqq_rotation", "model_version_id": MODEL,
        "status": "current_no_change", "state_detail": "current", "as_of": "2026-10-14",
        "latest_completed_session": "2026-10-14", "data_freshness": "current",
        "factor_freshness": "current", "signal_data_freshness": "current", "factor_evidence": [{}],
        "decision_schedule": {"state": "within_cadence"}, "staleness": {"stale": False},
        "delivery_status": "not_required",
        "source_identity": {"formal_bundle_id": formal["bundle_id"], "formal_run_id": formal["run_id"], "formal_evidence_cutoff": formal["evidence_cutoff"], "signal_sha256": decision["signal_sha256"], "ledger_fingerprint": decision["fingerprint"]},
    }]}
    ops = tmp_path / "operations.json"
    ops.write_text(json.dumps(operations))

    def binding(path):
        return {"path": str(path.relative_to(tmp_path)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    review = {"operations_snapshot": binding(ops), "decision_delivery_evidence": [{"strategy_id": "qqq_rotation", "decision": binding(decision_path), "delivery": binding(delivery_path)}]}
    row = {"formal_identities": {"qqq_rotation": formal}, "active_strategy_ids": ["qqq_rotation"], "actual_cutoffs": {"us": "2026-10-14"}}
    _review_strategies(row, review, tmp_path)
    review["decision_delivery_evidence"][0]["delivery"] = binding(decision_path)
    with pytest.raises(ValueError, match="delivery receipt"):
        _review_strategies(row, review, tmp_path)


def test_periodic_due_cycle_requires_a_verified_previous_anchor():
    from src.artifacts.operating_acceptance import _due_cycle_verified
    record = {"model_version_id": "us_x1_3", "decision_schedule": {"cadence_sessions": 10, "signal_date": "2026-10-14"}}
    current = {"signal_date": "2026-10-14", "latest_data_date": "2026-10-14", "signal": {}}
    previous = {"signal_date": "2026-09-30", "latest_data_date": "2026-09-30", "signal": {}}
    assert _due_cycle_verified(record, current, previous, market="us", cutoff="2026-10-14")
    assert not _due_cycle_verified(record, current, None, market="us", cutoff="2026-10-14")
    record["decision_schedule"]["cadence_sessions"] = 30
    assert not _due_cycle_verified(record, current, previous, market="us", cutoff="2026-10-14")
    # A daily valuation changes signal_date but retains its last rebalance anchor.
    current["signal"]["diagnostics"] = {"last_rebalance_date": "2026-09-30"}
    assert not _due_cycle_verified(record, current, previous, market="us", cutoff="2026-10-14")
    record["model_version_id"] = "cn_27_v1_3"
    record["decision_schedule"]["cadence_sessions"] = 1
    assert not _due_cycle_verified(record, current, previous, market="cn", cutoff="2026-10-14")
    record["decision_schedule"]["cadence_sessions"] = 30
    current["signal"] = {}
    previous.update(signal_date="2026-07-01", latest_data_date="2026-07-01")
    assert not _due_cycle_verified(record, current, previous, market="cn", cutoff="2026-10-14")


def test_not_due_ranker_accepts_current_operating_inputs_without_relabelling_old_signal(tmp_path):
    from src.artifacts.operating_acceptance import _review_strategies
    from src.artifacts.strategy_signal_ledger import seal_signal_decision, record_signal_delivery
    from tests.test_strategy_operations import _ranker_signal

    signal = _ranker_signal(family="us_ranker", group="momentum_volatility_volume", current={"AAPL": 1.0}, target={"AAPL": 1.0})
    kwargs = {"ledger_root": tmp_path / "ledger", "model_version_id": "us_x1_3", "signal": signal, "workflow_run_id": "2", "commit_sha": "b" * 40, "created_at_utc": "2026-08-07T21:00:00Z"}
    decision_path = seal_signal_decision(**kwargs)
    delivery_path = record_signal_delivery(**kwargs, delivery_status="not_required")
    decision = json.loads(decision_path.read_text())
    formal = {"model_version_id": "us_x1_3", "bundle_id": "c" * 64, "run_id": "formal-run", "evidence_cutoff": "2026-08-10", "market": "us"}
    record = {
        "strategy_id": "us_x", "model_version_id": "us_x1_3", "status": "current_no_change", "state_detail": "degraded_delayed",
        "as_of": "2026-08-07", "latest_completed_session": "2026-08-07", "data_freshness": "stale", "factor_freshness": "stale", "signal_data_freshness": "current", "factor_evidence": [{}],
        "decision_schedule": {"state": "within_cadence", "cadence_sessions": 10, "signal_date": "2026-08-07", "completed_through": "2026-08-10"},
        "staleness": {"stale": True, "as_of": "2026-08-07", "expected_cutoff": "2026-08-10", "sessions_behind": 1}, "delivery_status": "not_required",
        "source_identity": {"formal_bundle_id": formal["bundle_id"], "formal_run_id": formal["run_id"], "formal_evidence_cutoff": formal["evidence_cutoff"], "signal_sha256": decision["signal_sha256"], "ledger_fingerprint": decision["fingerprint"]},
    }
    boundary = {"research_only": True, "trade_ready": False}
    operations = {**boundary, "schema_version": "2.2.0", "generated_at": "2026-08-10T21:00:00Z", "records": [record]}
    task = {"strategy_id": "us_x", "model_version_id": "us_x1_3", "planned_provider_cutoff": "2026-08-10", "formal_refresh_required": False, "mtm_refresh_required": True}

    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload))
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def binding(path):
        return {"path": str(path.relative_to(tmp_path)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    plan = write("plan.json", {**boundary, "tasks": [task]})
    fan = write("fan.json", {**boundary, "status": "complete", "retained_strategy_ids": []})
    provider = write("provider.json", {**boundary, "market": "us", "status": "selected_pool_price_refresh_ready", "promotion_eligible": True, "all_sources_ready": True, "failure_count": 0, "records": [{"symbol": "QQQ", "last_date": "2026-08-10"}]})
    review = {"operations_snapshot": write("operations.json", operations), "decision_delivery_evidence": [{"strategy_id": "us_x", "decision": binding(decision_path), "delivery": binding(delivery_path)}]}
    row = {"formal_identities": {"us_x": formal}, "active_strategy_ids": ["us_x"], "actual_cutoffs": {"us": "2026-08-10"}, "receipt_sha256": {"plan/plan.json": plan["sha256"], "strategy-fan-in-receipt.json": fan["sha256"], "provider-us/artifacts/selected_pool_price_refresh_manifest.json": provider["sha256"]}}
    with pytest.raises(ValueError, match="observation-bound"):
        _review_strategies(row, review, tmp_path)
    review["operating_inputs"] = {"plan": plan, "fan_in": fan, "providers": {"us": provider}}
    assert _review_strategies(row, review, tmp_path) == []  # Qualified operation, no due cycle.
    assert record["as_of"] == "2026-08-07" and record["factor_freshness"] == "stale"
    task["formal_refresh_required"] = True
    changed = write("plan.json", {**boundary, "tasks": [task]})
    review["operating_inputs"]["plan"] = changed
    row["receipt_sha256"]["plan/plan.json"] = changed["sha256"]
    with pytest.raises(ValueError, match="operating inputs are blocked"):
        _review_strategies(row, review, tmp_path)
