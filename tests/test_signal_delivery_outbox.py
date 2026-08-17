from __future__ import annotations

from types import SimpleNamespace

import scripts.run_signal_delivery_outbox as outbox


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
            "fingerprint": "abc",
            "action": "REBALANCE",
            "current_weights": {"AAA": 1.0},
            "target_weights": {"BBB": 1.0},
            "execution_time": "next_eligible_open",
            "reason_code": "test_reason",
        },
    )
    assert title == "[策略信号] test_model 2026-08-14"
    assert "signal-decision:test_model:2026-08-14:abc" in body
    assert "当前：AAA 100.0%" in telegram
    assert "目标：BBB 100.0%" in telegram


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
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("transport must not run")),
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
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("terminal receipt is immutable")),
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
