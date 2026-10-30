from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import scripts.run_signal_delivery_outbox as outbox
from src.artifacts.strategy_signal_ledger import append_signal_evaluation, read_latest_evaluation
from test_strategy_signal_ledger import MODEL, _signal

ROOT = Path(__file__).resolve().parents[1]


def _active_strategy():
    return SimpleNamespace(
        strategy_id="test_strategy",
        model_version_id="test_model",
        signal_ledger="data/research/strategy_signal_ledgers/test_model",
    )


def test_message_uses_common_signal_contract() -> None:
    title, body, telegram = outbox._message(
        "test_model",
        {
            "signal_date": "2026-08-14",
            "fingerprint": "a" * 20,
            "action": "REBALANCE",
            "current_weights": {"AAA": 1.0},
            "target_weights": {"BBB": 1.0},
            "execution_time": "next_eligible_open",
            "reason_code": "test_reason",
        },
    )
    assert title == "[策略投递回执] test_model 2026-08-14"
    assert f"signal-decision:test_model:2026-08-14:{'a' * 20}" in body
    for sensitive in ("AAA", "BBB", "100.0%", "REBALANCE", "test_reason", "next_eligible_open"):
        assert sensitive not in title + body
    assert "当前：AAA 100.0%" in telegram
    assert "目标：BBB 100.0%" in telegram


def test_public_receipt_does_not_copy_free_text_or_unknown_signal_fields():
    signal = {
        "signal_date": "2026-08-14", "fingerprint": "b" * 64,
        "title": "PRIVATE_TITLE", "action": "PRIVATE_ACTION",
        "reason_code": "PRIVATE_REASON", "execution_time": "PRIVATE_TIME",
        "current_weights": {"PRIVATE_ASSET": 0.25},
        "target_weights": {"PRIVATE_TARGET": 0.75},
        "future_private_field": "PRIVATE_FUTURE",
    }
    title, body, telegram = outbox._message("test_model", signal)
    assert "PRIVATE_" not in title + body
    assert "25.0%" not in body and "75.0%" not in body
    for value in ("PRIVATE_TITLE", "PRIVATE_ACTION", "PRIVATE_REASON", "PRIVATE_TIME",
                  "PRIVATE_ASSET 25.0%", "PRIVATE_TARGET 75.0%"):
        assert value in telegram
    assert "does not confirm delivery" in body


@pytest.mark.parametrize("field,value", [
    ("model", 'bad\"model'), ("model", "private\nmodel"),
    ("signal_date", "2026-02-30"), ("signal_date", "2026-08-14\nPRIVATE"),
    ("fingerprint", "<!-- PRIVATE -->"), ("fingerprint", "target-100-percent"),
])
def test_unsafe_public_identity_is_rejected_without_echoing_input(field, value):
    signal = {"signal_date": "2026-08-14", "fingerprint": "a" * 20}
    model = value if field == "model" else "test_model"
    if field != "model":
        signal[field] = value
    with pytest.raises(ValueError, match="invalid public delivery receipt") as error:
        outbox._message(model, signal)
    assert value not in str(error.value)


@pytest.fixture
def canonical_outbox(tmp_path, monkeypatch):
    ledger = tmp_path / MODEL
    signal = _signal(fingerprint="a" * 20)
    signal.update(title="PRIVATE_TITLE", action="PRIVATE_ACTION", reason_code="PRIVATE_REASON")
    append_signal_evaluation(ledger_root=ledger, model_version_id=MODEL, signal=signal,
        delivery_status="pending", workflow_run_id="seal", commit_sha="a" * 40,
        created_at_utc="2026-08-13T00:00:00Z")
    sealed = (ledger / "latest.json").read_bytes()
    strategy = SimpleNamespace(strategy_id="qqq_rotation", model_version_id=MODEL, signal_ledger=str(ledger))
    monkeypatch.setattr(outbox, "load_active_strategy_catalog", lambda: SimpleNamespace(strategies=(strategy,)))
    issues, messages, lookups = [], [], []

    def existing(repository, marker):
        lookups.append(marker)
        return 42 if issues else None

    def create(repository, title, body):
        issues.append((title, body))
        return 42

    def send(token, chat, text):
        messages.append(text)
        return 99

    monkeypatch.setattr(outbox, "_existing_issue", existing)
    monkeypatch.setattr(outbox, "_create_issue", create)
    monkeypatch.setattr(outbox, "_send_telegram", send)
    runs = 0

    def drain(*, configured=True, persist=None, created_at=None):
        nonlocal runs
        runs += 1
        result = outbox.drain_outbox(repository="owner/repo", workflow_run_id=f"delivery-{runs}",
            commit_sha="b" * 40, created_at_utc=created_at or f"2026-08-13T{runs:02d}:00:00Z",
            telegram_token="test-token" if configured else None,
            telegram_chat_id="test-chat" if configured else None, persist=persist)
        assert (ledger / "latest.json").read_bytes() == sealed
        return result[0]

    return SimpleNamespace(drain=drain, ledger=ledger, issues=issues, messages=messages, lookups=lookups, send=send)


def test_public_redaction_preserves_private_delivery_and_terminal_dedup(canonical_outbox):
    context = canonical_outbox
    result = context.drain()
    assert result.status == "sent" and result.github_issue_number == 42 and result.telegram_message_id == 99
    assert len(context.issues) == len(context.messages) == 1
    title, body = context.issues[0]
    assert "PRIVATE_" not in title + body
    assert body.splitlines()[0] == context.lookups[0]
    assert "PRIVATE_TITLE" in context.messages[0] and "QQQI 50.0%" in context.messages[0]
    latest = read_latest_evaluation(context.ledger, model_version_id=MODEL)
    assert latest["delivery"]["status"] == "sent"
    assert context.drain().status == "sent"
    assert len(context.issues) == len(context.messages) == len(context.lookups) == 1


def test_existing_legacy_issue_marker_blocks_ambiguous_pending_replay(canonical_outbox):
    context = canonical_outbox
    context.issues.append(("legacy detailed title", "legacy detailed body"))
    result = context.drain()
    assert result.status == "failed" and result.error == "ambiguous_external_delivery_state"
    assert result.github_issue_number == 42
    assert context.messages == []
    assert context.lookups == [f"<!-- signal-decision:{MODEL}:2026-08-12:{'a' * 20} -->"]
    assert context.drain().error == "ambiguous_external_delivery_state"
    assert len(context.lookups) == 1 and len(context.issues) == 1


@pytest.mark.parametrize("error", ["telegram_api_rejected", "telegram_transport_ambiguous"])
def test_private_delivery_failure_keeps_existing_retry_rules(canonical_outbox, monkeypatch, error):
    context = canonical_outbox

    def failed(*args):
        raise RuntimeError(error)

    monkeypatch.setattr(outbox, "_send_telegram", failed)
    assert context.drain().error == error
    title, body = context.issues[0]
    assert "PRIVATE_" not in title + body
    monkeypatch.setattr(outbox, "_send_telegram", context.send)
    retried = context.drain()
    if error == "telegram_api_rejected":
        assert retried.status == "sent" and len(context.messages) == 1
    else:
        assert retried.error == error and context.messages == []
    assert len(context.issues) == 1


def test_missing_telegram_configuration_keeps_public_receipt_generic(canonical_outbox):
    context = canonical_outbox
    assert context.drain(configured=False).status == "skipped_not_configured"
    assert context.messages == []
    assert "PRIVATE_" not in "".join(context.issues[0])


def test_no_change_is_finalized_without_transport(monkeypatch) -> None:
    strategy = _active_strategy()
    monkeypatch.setattr(
        outbox,
        "load_active_strategy_catalog",
        lambda: SimpleNamespace(strategies=(strategy,)),
    )
    monkeypatch.setattr(
        outbox,
        "read_latest_evaluation",
        lambda *args, **kwargs: {
            "signal_date": "2026-08-14",
            "delivery": {"status": "pending", "error": None},
            "signal": {
                "signal_date": "2026-08-14",
                "fingerprint": "abc",
                "should_alert": False,
            },
        },
    )
    recorded = []
    monkeypatch.setattr(outbox, "_record", lambda **kwargs: recorded.append(kwargs))
    monkeypatch.setattr(
        outbox,
        "_existing_issue",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("transport must not run")
        ),
    )

    results = outbox.drain_outbox(
        repository="owner/repo",
        workflow_run_id="1",
        commit_sha="abc",
        created_at_utc="2026-08-14T00:00:00Z",
        telegram_token=None,
        telegram_chat_id=None,
    )

    assert results[0].status == "not_required"
    assert recorded[0]["status"] == "not_required"


def test_terminal_delivery_is_not_replayed(monkeypatch) -> None:
    strategy = _active_strategy()
    monkeypatch.setattr(
        outbox,
        "load_active_strategy_catalog",
        lambda: SimpleNamespace(strategies=(strategy,)),
    )
    monkeypatch.setattr(
        outbox,
        "read_latest_evaluation",
        lambda *args, **kwargs: {
            "signal_date": "2026-08-14",
            "delivery": {
                "status": "sent",
                "github_issue_number": 10,
                "telegram_message_id": 20,
                "error": None,
            },
            "signal": {
                "signal_date": "2026-08-14",
                "fingerprint": "abc",
                "should_alert": True,
            },
        },
    )
    monkeypatch.setattr(
        outbox,
        "_record",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("terminal receipt is immutable")
        ),
    )

    results = outbox.drain_outbox(
        repository="owner/repo",
        workflow_run_id="1",
        commit_sha="abc",
        created_at_utc="2026-08-14T00:00:00Z",
        telegram_token="token",
        telegram_chat_id="chat",
    )

    assert results[0].status == "sent"
    assert results[0].github_issue_number == 10
    assert results[0].telegram_message_id == 20


def test_model_workflows_delegate_all_external_delivery_to_outbox() -> None:
    model_workflows = [
        ROOT / ".github/workflows/qqq-v4-3-signal-alert.yml",
        ROOT / ".github/workflows/byd-daily-signal-alert.yml",
        ROOT / ".github/workflows/ranker-10d-current-target.yml",
    ]
    for path in model_workflows:
        text = path.read_text(encoding="utf-8")
        assert "TELEGRAM_BOT_TOKEN" not in text
        assert "api.telegram.org" not in text
        assert "gh issue create" not in text
        assert "--delivery-status pending" in text

    delivery = (ROOT / ".github/workflows/strategy-signal-delivery-outbox.yml").read_text(
        encoding="utf-8"
    )
    assert "TELEGRAM_BOT_TOKEN" in delivery
    assert "TELEGRAM_CHAT_ID" in delivery
    assert "scripts/run_signal_delivery_outbox.py" in delivery


def test_outbox_workflow_triggers_and_fallback_schedule() -> None:
    workflow_path = ROOT / ".github/workflows/strategy-signal-delivery-outbox.yml"
    text = workflow_path.read_text(encoding="utf-8")
    assert 'cron: "15 */6 * * *"' in text
    assert 'cron: "15 * * * *"' not in text

    content = yaml.safe_load(text)
    triggers = content.get("on") if "on" in content else content.get(True)
    assert triggers is not None
    assert "workflow_run" in triggers
    assert triggers["workflow_run"]["workflows"] == [
        "QQQ Rotation v4.3 Signal Alert",
        "10D Ranker Current Target",
        "CN27 Current Target",
    ]
    assert triggers["workflow_run"]["types"] == ["completed"]
    assert triggers["repository_dispatch"]["types"] == ["strategy_signal_delivery"]
    assert "schedule" in triggers
    assert triggers["schedule"] == [{"cron": "15 */6 * * *"}]
    assert "workflow_dispatch" in triggers
    assert "pull_request" in triggers
    steps = content["jobs"]["deliver"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Record private delivery persistence receipt") < names.index("Request strategy operations publication") < names.index("Fail after persisting delivery failure evidence")
    dispatch = next(step for step in steps if step.get("name") == "Request strategy operations publication")
    assert 'event_type: "strategy_operations_publication"' in dispatch["run"]
    assert dispatch["if"] == "inputs.verify_private_state_only != true && (steps.receipts.outputs.changed == 'true' || github.event_name == 'workflow_dispatch' || github.event_name == 'schedule')"
    receipt = next(step for step in steps if step.get("name") == "Record private delivery persistence receipt")
    assert receipt["id"] == "receipts"
    assert "any_changed" in receipt["run"] and "GITHUB_OUTPUT" in receipt["run"]
    assert "git " not in receipt["run"]
    uploads = [step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"] == "artifacts/signal-delivery-outbox/result.json"
    assert uploads[0]["if"] == "always()"


def test_private_claim_is_persisted_before_transport_and_final_status_after(canonical_outbox):
    context = canonical_outbox
    persisted = []

    def persist():
        delivery = read_latest_evaluation(context.ledger, model_version_id=MODEL)["delivery"]
        persisted.append(delivery["status"])
        if len(persisted) == 1:
            assert delivery["error"] == "ambiguous_external_delivery_state"
            assert context.issues == context.messages == []
        else:
            assert len(context.messages) == 1

    assert context.drain(persist=persist).status == "sent"
    assert persisted == ["failed", "sent"]


def test_failed_private_claim_prevents_all_external_side_effects(canonical_outbox):
    context = canonical_outbox

    def conflict():
        raise RuntimeError("CAS conflict")

    with pytest.raises(RuntimeError, match="CAS conflict"):
        context.drain(persist=conflict)
    assert context.issues == context.messages == []


def test_failed_final_persistence_retains_ambiguity_fence_for_recovery(canonical_outbox):
    context = canonical_outbox
    persisted = []

    def persist():
        if persisted:
            raise RuntimeError("private store unavailable after send")
        persisted.append(True)

    with pytest.raises(RuntimeError, match="after send"):
        context.drain(persist=persist)
    assert len(context.messages) == 1
    # Simulate restoring the private authority, which contains only the claim.
    (context.ledger / "deliveries" / "2026-08-12" / "delivery-1.json").unlink()
    result = context.drain(persist=persist)
    assert result.error == "ambiguous_external_delivery_state"
    assert len(context.messages) == 1


def test_one_second_retry_claim_wins_over_prior_rejection_and_prevents_replay(canonical_outbox, monkeypatch):
    context = canonical_outbox

    def rejected(*args):
        raise RuntimeError("telegram_api_rejected")

    monkeypatch.setattr(outbox, "_send_telegram", rejected)
    assert context.drain(created_at="2026-08-13T01:00:00Z").error == "telegram_api_rejected"
    monkeypatch.setattr(outbox, "_send_telegram", context.send)
    claims = []

    def persist():
        if claims:
            raise RuntimeError("final persistence failed")
        claims.append(True)
        assert read_latest_evaluation(context.ledger, model_version_id=MODEL)["delivery"]["error"] == "ambiguous_external_delivery_state"

    with pytest.raises(RuntimeError, match="final persistence"):
        context.drain(persist=persist, created_at="2026-08-13T01:00:01Z")
    (context.ledger / "deliveries" / "2026-08-12" / "delivery-2.json").unlink()
    assert context.drain().error == "ambiguous_external_delivery_state"
    assert len(context.messages) == 1
