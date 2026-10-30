"""Consumer ordering is a safety gate, not merely a YAML style convention."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())


@pytest.mark.parametrize("filename,consumer", [
    ("qqq-v4-3-signal-alert.yml", "Check sealed QQQ decision before data work"),
    ("byd-daily-signal-alert.yml", "Build exact formal V1.3 decision"),
    ("ranker-10d-current-target.yml", "Evaluate active markets independently"),
    ("cn27-current-target.yml", "Evaluate CN_27 current target"),
])
def test_every_producer_restores_before_due_and_persists_before_public_mirror(filename, consumer):
    steps = workflow(filename)["jobs"]["evaluate"]["steps"]
    names = [step.get("name") for step in steps]
    restore = names.index("Restore authoritative private ledgers")
    assert restore < names.index(consumer)
    body = "\n".join(step.get("run", "") for step in steps)
    assert body.index("private-ledgers restore") < body.index("private-ledgers persist") < body.index("git add data/research/strategy_signal_ledgers")
    assert "continue-on-error" not in steps[restore]
    if filename == "cn27-current-target.yml":
        assert steps[restore]["if"] == "github.event_name != 'pull_request'"


def test_formal_transaction_pins_one_private_revision_across_all_consumers():
    jobs = workflow("formal-backtest-refresh.yml")["jobs"]
    assert jobs["prepare"]["outputs"]["private_commit"] == "${{ steps.private_ledgers.outputs.private_commit }}"
    for name in ("prepare", "plan", "strategy", "publish"):
        steps = jobs[name]["steps"]
        restored = [step for step in steps if step.get("name") == "Restore authoritative private ledgers"]
        assert len(restored) == 1
        if name != "prepare":
            assert '--revision "${{ needs.prepare.outputs.private_commit }}"' in restored[0]["run"]
        assert "continue-on-error" not in restored[0]
    plan_steps = jobs["plan"]["steps"]
    plan = next(step for step in plan_steps if step.get("name") == "Build pure active-strategy plan")
    assert plan["run"].lstrip().startswith("uv run python -m scripts.run_formal_refresh_transaction plan")
    setup = next(i for i, step in enumerate(plan_steps) if step.get("uses") == "./.github/actions/setup-python-uv")
    assert setup < plan_steps.index(plan)


def test_operations_resolves_private_content_before_cache_lookup():
    steps = workflow("strategy-operations-release.yml")["jobs"]["publish-operations"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Restore authoritative private ledgers") < names.index("Restore publication idempotency receipt")
    keys = [step["with"]["key"] for step in steps if str(step.get("uses", "")).startswith("actions/cache/")]
    assert len(keys) == 2 and keys[0] == keys[1]
    assert "steps.private_ledgers.outputs.archive_sha256" in keys[0]


def test_outbox_private_probe_cannot_invoke_notifications_or_dispatch():
    jobs = workflow("strategy-signal-delivery-outbox.yml")["jobs"]
    job = jobs["deliver"]
    assert "TELEGRAM_BOT_TOKEN" not in job["env"]
    steps = {step.get("name"): step for step in job["steps"]}
    probe = steps["Verify private state without external delivery"]
    assert probe["if"] == "inputs.verify_private_state_only == true"
    assert "private-ledgers persist" in probe["run"]
    for name in ("Drain canonical pending decisions", "Materialize Strategy Operations evidence",
                 "Commit append-only delivery receipts", "Request strategy operations publication"):
        assert "inputs.verify_private_state_only != true" in steps[name]["if"]
    drain = steps["Drain canonical pending decisions"]
    assert '--private-ledger-receipt "$RUNNER_TEMP/private-ledgers.json"' in drain["run"]
    assert "test -f artifacts/signal-delivery-outbox/result.json" in drain["run"]
    assert "TELEGRAM_BOT_TOKEN" in drain["env"]
