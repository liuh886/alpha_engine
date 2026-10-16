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


@pytest.mark.parametrize("scenario", ["missing_latest", "bad_hash", "unsafe_member"])
def test_remote_collection_never_falls_back_or_accepts_unbound_archives(tmp_path, monkeypatch, scenario):
    import io
    import zipfile
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from src.artifacts.operating_acceptance import collect_operating_review

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.json" if scenario == "unsafe_member" else "operating-observation.json", "{}")
    raw = buffer.getvalue()
    artifact = {"id": 7, "name": "formal-backtest-refresh-2-attempt-1", "expired": False, "size_in_bytes": len(raw), "digest": "sha256:" + ("0" * 64 if scenario == "bad_hash" else hashlib.sha256(raw).hexdigest())}
    called = []

    def remote(args, **kwargs):
        endpoint = args[-1]
        called.append(endpoint)
        if endpoint.endswith("/zip"):
            return SimpleNamespace(stdout=raw)
        if "workflows/" in endpoint:
            payload = {"workflow_runs": [{"id": 2, "run_attempt": 1}]}
        elif "/jobs?" in endpoint:
            payload = {"jobs": [{"status": "completed"}], "total_count": 1}
        elif "/artifacts?" in endpoint:
            payload = {"artifacts": [] if scenario == "missing_latest" else [artifact], "total_count": 0 if scenario == "missing_latest" else 1}
        else:
            payload = {"id": 2, "run_attempt": 1, "head_branch": "main", "event": "schedule", "repository": {"full_name": "owner/repo"}, "path": ".github/workflows/formal-backtest-refresh.yml", "status": "completed", "conclusion": "failure"}
        return SimpleNamespace(stdout=json.dumps(payload).encode())

    monkeypatch.setattr("subprocess.run", remote)
    kwargs = {"input_root": tmp_path, "repository_root": tmp_path, "now_utc": datetime(2026, 10, 16, 3, tzinfo=timezone.utc)}
    if scenario == "missing_latest":
        result = collect_operating_review("owner/repo", **kwargs)
        assert result["run_id"] == 2 and result["qualification_status"] == "blocked"
        assert result["manual_interventions"] is None
        assert "missing or expired" in result["blockers"][0]
    else:
        with pytest.raises(ValueError, match="hash or size mismatch" if scenario == "bad_hash" else "unsafe"):
            collect_operating_review("owner/repo", **kwargs)
    assert all("runs/1/" not in endpoint for endpoint in called)
    assert not (tmp_path.parent / "escape.json").exists()


def test_typed_strategy_review_binds_formal_decision_and_delivery(tmp_path, monkeypatch):
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

    from dataclasses import replace
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from src.artifacts.operating_acceptance import prepare_operating_review
    from src.governance.active_strategy_catalog import load_active_strategy_catalog

    strategy = replace(load_active_strategy_catalog().by_model_version_id[MODEL], signal_ledger="ledger")
    catalog = SimpleNamespace(strategies=(strategy,), by_model_version_id={MODEL: strategy})
    monkeypatch.setattr("src.governance.active_strategy_catalog.load_active_strategy_catalog", lambda *args: catalog)
    monkeypatch.setattr("src.artifacts.strategy_operations.build_operations_payload", lambda **kwargs: operations)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    (tmp_path / "lineage.json").write_text("{}")
    monkeypatch.setattr("src.artifacts.formal_bundle_reader.load_formal_run", lambda *args: SimpleNamespace(manifest_path=manifest))
    source = tmp_path / "source"
    source.mkdir()
    captured = {**row, "schema_version": "operating_observation_v1", "run_id": 2, "run_attempt": 1, "head_sha": "b" * 40, "expected_cutoffs": {"us": "2026-10-14"}, "research_only": True, "trade_ready": False}
    (source / "operating-observation.json").write_text(json.dumps(captured))
    metadata = {"run": {"id": 2, "run_attempt": 1, "head_sha": "b" * 40, "status": "completed", "conclusion": "success", "path": ".github/workflows/formal-backtest-refresh.yml"}, "jobs": [{"status": "completed"}]}
    now = datetime(2026, 10, 14, 22, tzinfo=timezone.utc)
    prepared = prepare_operating_review(source, metadata=metadata, repository_root=tmp_path, output_root=tmp_path, now_utc=now)
    assert prepared["mechanically_ready"] is True
    assert prepared["qualification_status"] == "awaiting_independent_review"
    draft = json.loads((tmp_path / "review-draft.json").read_text())["2:1"]
    assert draft["manual_interventions"] is None and draft["reviewed_by"] is None
    assert draft["cadence_and_freshness_verified"] is False
    report = build_acceptance_report(source, declarations=tmp_path / "review-draft.json", through="2026-10-14")
    assert report["markets"]["us"]["qualified_sessions"] == 0
    metadata["run"]["conclusion"] = "failure"
    failed = prepare_operating_review(source, metadata=metadata, repository_root=tmp_path, output_root=tmp_path, now_utc=now)
    assert failed["mechanically_ready"] is False and failed["blockers"]
    metadata["run"]["conclusion"] = "success"
    delivery_path.unlink()
    missing = prepare_operating_review(source, metadata=metadata, repository_root=tmp_path, output_root=tmp_path, now_utc=now)
    assert missing["mechanically_ready"] is False
    assert "delivery receipt is missing" in missing["strategy_checks"][0]["blocker"]

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
    task = {"strategy_id": "us_x", "model_version_id": "us_x1_3", "market": "us", "planned_provider_cutoff": "2026-08-10", "formal_refresh_required": False, "mtm_refresh_required": True}

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
    assert row["verified_retained_target_strategy_ids"] == ["us_x"]
    assert record["as_of"] == "2026-08-07" and record["factor_freshness"] == "stale"
    task["formal_refresh_required"] = True
    changed = write("plan.json", {**boundary, "tasks": [task]})
    review["operating_inputs"]["plan"] = changed
    row["receipt_sha256"]["plan/plan.json"] = changed["sha256"]
    with pytest.raises(ValueError, match="formal settlement lacks verified"):
        _review_strategies(row, review, tmp_path)

    from pathlib import Path
    from src.artifacts.model_run_bundle_v2 import compute_bundle_id

    # A formal catch-up must bind the executed preview to the promoted bundle.
    repository = Path(__file__).resolve().parents[1]
    manifest_path = next((repository / "data/research/formal_model_runs/us_ranker/us_x1_3").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    lineage = write("lineage.json", {**boundary, "publication_contract": "native_formal_bundle_v2", "model_selection_reopened": False, "source_preview_bundle_id": "d" * 64})
    section = next(value for value in manifest["sections"] if value["section_id"] == "lineage")
    section.update(sha256=lineage["sha256"], byte_size=(tmp_path / "lineage.json").stat().st_size)
    manifest.update(run_id=formal["run_id"], evidence_cutoff=formal["evidence_cutoff"])
    manifest["comparability_key"]["end"] = formal["evidence_cutoff"]
    manifest["bundle_id"] = compute_bundle_id(manifest)
    formal["bundle_id"] = manifest["bundle_id"]
    record["source_identity"]["formal_bundle_id"] = formal["bundle_id"]
    review["operations_snapshot"] = write("operations.json", operations)
    item = review["decision_delivery_evidence"][0]
    item.update(formal_manifest=write("manifest.json", manifest), formal_lineage=lineage)
    receipt = {**boundary, **task, "schema_version": "formal_strategy_refresh_receipt_v2", "execution_status": "refreshed", "model_family_id": "us_ranker", "publication_input": "native_bundle_v2", "candidate_evidence_cutoff": formal["evidence_cutoff"], "candidate_bundle_id": "d" * 64, "replay_verdict": "deterministic_native_bundle_rebuild"}

    def fan_receipt():
        updated = write("fan.json", {**boundary, "status": "complete", "retained_strategy_ids": [], "receipts": [receipt]})
        review["operating_inputs"]["fan_in"] = updated
        row["receipt_sha256"]["strategy-fan-in-receipt.json"] = updated["sha256"]

    fan_receipt()
    assert _review_strategies(row, review, tmp_path) == []
    receipt["candidate_bundle_id"] = "e" * 64
    fan_receipt()
    with pytest.raises(ValueError, match="formal settlement lacks verified"):
        _review_strategies(row, review, tmp_path)
    receipt["candidate_bundle_id"] = "d" * 64
    receipt["execution_status"] = "blocked"
    fan_receipt()
    with pytest.raises(ValueError, match="formal settlement lacks verified"):
        _review_strategies(row, review, tmp_path)
    receipt["execution_status"] = "refreshed"
    fan_receipt()
    item["formal_lineage"] = write("lineage.json", {**boundary, "source_preview_bundle_id": "d" * 64})
    with pytest.raises(ValueError, match="formal settlement lacks verified"):
        _review_strategies(row, review, tmp_path)
