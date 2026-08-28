from __future__ import annotations

import json
from pathlib import Path

import scripts.setup_cron as setup_cron
from scripts.summarize_daily_us_decision_run import build_summary

WORKFLOW = Path(".github/workflows/daily-us-low-turnover-decision.yml")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_posix_cron_contains_post_close_daily_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(setup_cron, "_project_root", lambda: tmp_path)

    cron_path = Path(setup_cron.setup_posix_cron())
    content = cron_path.read_text(encoding="utf-8")

    assert "30 7 * * 2-6" in content
    assert "scripts/run_latest_us_low_turnover_decision.py" in content
    assert "artifacts/logs/daily_us_decision.log" in content
    assert "\\" not in content
    assert "SEC_USER_AGENT must be available" in content


def test_windows_setup_writes_fail_closed_daily_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(setup_cron, "_project_root", lambda: tmp_path)

    daily_path = Path(setup_cron.setup_windows_task())
    content = daily_path.read_text(encoding="utf-8")
    assert "if not defined SEC_USER_AGENT" in content
    assert "run_latest_us_low_turnover_decision.py" in content
    assert "daily_us_decision.log" in content


def test_scheduled_workflow_restores_and_saves_state_in_order() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")

    restore = content.index("Restore prior Decision Desk state")
    live_run = content.index("Run latest complete US decision cycle")
    summary = content.index("Build answer-first run summary")
    upload = content.index("Upload diagnostic artifacts")
    save = content.index("Save Decision Desk state")
    failure = content.index("Preserve governed failure status")

    assert restore < live_run < summary < upload < save < failure
    assert "actions/cache/restore@v4" in content
    assert "actions/cache/save@v4" in content
    assert "artifacts/decision_ledger" in content
    assert "artifacts/factor_registry.db" in content
    assert "daily-us-decision-state-${{ github.run_id }}-${{ github.run_attempt }}" in content
    assert "--state-restored" in content


def test_scheduled_workflow_wires_governed_sec_egress_without_relaxing_gate() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    live_run = content.index("Run latest complete US decision cycle")
    summary = content.index("Build answer-first run summary")
    live_block = content[live_run:summary]

    assert "SEC_EGRESS_MODE: ${{ vars.SEC_EGRESS_MODE || 'direct' }}" in live_block
    assert "SEC_EGRESS_PROXY_ID: ${{ vars.SEC_EGRESS_PROXY_ID || '' }}" in live_block
    assert "SEC_EGRESS_PROXY_URL: ${{ secrets.SEC_EGRESS_PROXY_URL || '' }}" in live_block
    assert "SEC_EGRESS_PROXY_URL" not in content[:live_run]
    assert "SEC_EGRESS_PROXY_URL" not in content[summary:]
    assert "Preserve governed failure status" in content
    assert 'exit "$status"' in content


def test_summary_surfaces_source_blockers_ticket_and_restored_state(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "market_snapshots" / "us_small_pool_v1" / "2026-07-31" / "decision.json",
        {
            "resolved_as_of_date": "2026-07-31",
            "symbol_count": 25,
            "row_count": 7000,
        },
    )
    run_root = tmp_path / "forward_shadow_runs" / "us_low_turnover_pipeline" / "2026-07-31"
    _write_json(
        run_root / "sec_companyfacts" / "decision.json",
        {
            "decision": "sec_companyfacts_source_ready_with_partial_coverage",
            "factor_ready_count": 22,
            "candidate_count": 23,
        },
    )
    _write_json(
        run_root / "sec_companyfacts" / "coverage_report.json",
        {
            "rows": [
                {
                    "symbol": "SNDK",
                    "factor_ready": False,
                    "blockers": ["INSUFFICIENT_QUARTERS"],
                }
            ]
        },
    )
    _write_json(
        run_root / "low_turnover_multifactor" / "decision.json",
        {
            "decision": "multifactor_diagnostic_candidate_ready",
            "turnover_diagnostics": {"turnover_gate_passed": True},
        },
    )
    _write_json(
        tmp_path / "decision_ledger" / "us" / "2026-07-31.json",
        {
            "as_of_date": "2026-07-31",
            "ticket_identity_sha256": "ticket-123",
            "securities": [{"symbol": "AAPL"}],
        },
    )
    operations = tmp_path / "operations"
    operations.mkdir()
    (operations / "daily_us_decision.log").write_text(
        "line one\nline two\n",
        encoding="utf-8",
    )

    completed = build_summary(
        artifacts_root=tmp_path,
        exit_code=0,
        state_restored=True,
    )
    blocked = build_summary(
        artifacts_root=tmp_path,
        exit_code=1,
        state_restored=False,
    )

    assert "Daily US Decision — COMPLETED" in completed
    assert "Prior Decision Desk state restored: `true`" in completed
    assert "Resolved complete session: `2026-07-31`" in completed
    assert "SNDK: INSUFFICIENT_QUARTERS" in completed
    assert "Ticket identity: `ticket-123`" in completed
    assert "Daily US Decision — BLOCKED" in blocked
    assert "Prior Decision Desk state restored: `false`" in blocked
