"""Canaries exercise real handlers; private output is never their stdout."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.artifacts.strategy_signal_ledger import StrategySignalLedgerError, public_signal_write_receipt
from src.governance.active_strategy_catalog import load_active_strategy_catalog

ROOT = Path(__file__).resolve().parents[1]


def signal(model):
    return {"model_id": model, "model_version_id": model, "signal_date": "2026-10-29",
        "current_weights": {"PRIVATE_CURRENT": 0.25}, "target_weights": {"PRIVATE_TARGET": 0.75},
        "title": "PRIVATE_TITLE", "markdown": "PRIVATE_MARKDOWN", "telegram_text": "PRIVATE_TELEGRAM",
        "unknown_future_field": "PRIVATE_FUTURE", "fingerprint": "a" * 20,
        "should_alert": True, "data_freshness_ok": True, "transition_type": "initialize",
        "open_research_eligible": True}


def assert_public_and_private(output, public):
    payload = json.loads(public)
    assert set(payload) == {"schema_version", "status", "model_version_id", "signal_date", "research_only", "trade_ready"}
    assert payload["status"] == "written" and "PRIVATE_" not in public
    private = json.loads(output.read_bytes())
    assert private["target_weights"] == {"PRIVATE_TARGET": 0.75}
    assert private["unknown_future_field"] == "PRIVATE_FUTURE"


def test_qqq_handler_writes_private_signal_but_only_logs_receipt(tmp_path, monkeypatch, capsys):
    import scripts.run_qqq_v4_3_signal_alert as command

    source = tmp_path / "summary.json"
    source.write_text("{}")
    out = tmp_path / "out"
    github = tmp_path / "github-output"
    monkeypatch.setattr(command, "build_v4_3_signal_alert", lambda summary: signal("qqqi_qqq_tqqq_v4_3"))
    monkeypatch.setattr(command, "build_strategy_factor_snapshot", lambda **kwargs: {"freshness": "current"})
    monkeypatch.setattr(sys, "argv", ["qqq", "--summary", str(source), "--output-dir", str(out), "--github-output", str(github)])
    assert command.main() == 0
    assert_public_and_private(out / "signal_alert.json", capsys.readouterr().out)
    assert "title=" not in github.read_text() and "PRIVATE_" not in github.read_text()


def test_cn_handler_writes_private_signal_but_only_logs_receipt(tmp_path, monkeypatch, capsys):
    import scripts.run_cn_27_current_target as command

    monkeypatch.setattr(command, "_strategy", lambda: (SimpleNamespace(signal_ledger=str(tmp_path)), None))
    monkeypatch.setattr(command, "score_cn_27_current_target", lambda **kwargs: signal(command.MODEL_ID))
    output = tmp_path / "signal.json"
    args = SimpleNamespace(formal_root=tmp_path, signal_date="2026-10-29", market_cutoff="2026-10-29", output=output)
    assert command._build(args) == 0
    assert_public_and_private(output, capsys.readouterr().out)


def test_byd_new_decision_handler_does_not_log_private_payload(tmp_path, monkeypatch, capsys):
    import scripts.run_byd_signal_alert as command

    monkeypatch.setattr(command, "_latest_observation", lambda path: {"signal_date": "2026-10-29"})
    monkeypatch.setattr(command, "_previous_alert", lambda path: None)
    monkeypatch.setattr(command, "_manifest_sha256", lambda path: "a" * 64)
    monkeypatch.setattr(command, "build_byd_signal_alert", lambda *args, **kwargs: signal(command.MODEL_ID))
    monkeypatch.setattr(command, "close_evidence_is_current", lambda observation: True)
    monkeypatch.setattr(command, "build_strategy_factor_snapshot", lambda **kwargs: {"freshness": "current"})
    monkeypatch.setattr(command, "bind_final_signal_identity", lambda alert: None)
    monkeypatch.setattr(command, "_render_markdown", lambda alert: "PRIVATE_MARKDOWN")
    monkeypatch.setattr(command, "_render_telegram", lambda alert: "PRIVATE_TELEGRAM")
    output = tmp_path / "signal.json"
    monkeypatch.setattr(command, "_write_outputs", lambda path, alert: output.write_text(json.dumps(alert)))
    monkeypatch.setattr(sys, "argv", ["byd", "--source-store", str(tmp_path), "--output-dir", str(tmp_path)])
    assert command.main() == 0
    assert_public_and_private(output, capsys.readouterr().out)


@pytest.mark.parametrize("field,value", [("signal_date", "PRIVATE_DATE"), ("model", "PRIVATE MODEL"), ("status", "PRIVATE_STATUS")])
def test_public_receipt_rejects_unsafe_identity_without_echo(field, value):
    args = {"model_version_id": "test_model", "status": "written"}
    payload = {"signal_date": "2026-10-29", "target_weights": {"PRIVATE_TARGET": 1.0}}
    if field == "signal_date":
        payload[field] = value
    else:
        args["model_version_id" if field == "model" else "status"] = value
    with pytest.raises(StrategySignalLedgerError) as error:
        public_signal_write_receipt(payload, **args)
    assert "PRIVATE_" not in str(error.value)


def test_active_runtime_ledgers_are_not_git_tracked_and_fresh_hydration_is_ignored():
    for model in load_active_strategy_catalog(ROOT / "configs/strategies/registry.json").active_model_version_ids:
        path = f"data/research/strategy_signal_ledgers/{model}"
        tracked = subprocess.check_output(["git", "ls-files", "--", path], cwd=ROOT)
        assert not tracked, f"active runtime ledger was added to public Git: {model}"
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "-q", "--", f"{path}/latest.json"], cwd=ROOT)
        assert ignored.returncode == 0


def test_outbox_dispatch_accumulates_private_changes_even_when_last_write_is_noop(tmp_path, monkeypatch, capsys):
    import scripts.run_signal_delivery_outbox as command
    from src.artifacts import private_signal_ledger as private

    receipt = tmp_path / "private.json"
    receipt.write_text("{}")
    calls = []

    def persist(**kwargs):
        calls.append(True)
        return {**kwargs["base"], "changed": len(calls) == 1}

    def drain(**kwargs):
        kwargs["persist"]()
        kwargs["persist"]()
        return []

    monkeypatch.setattr(private, "persist_private_ledgers", persist)
    monkeypatch.setattr(command, "drain_outbox", drain)
    monkeypatch.setattr(sys, "argv", ["outbox", "--repository", "owner/repo", "--workflow-run-id", "1",
        "--commit-sha", "a" * 40, "--created-at-utc", "2026-10-29T00:00:00Z",
        "--output", str(tmp_path / "public-result.json"), "--private-ledger-receipt", str(receipt)])
    assert command.main() == 0
    persisted = json.loads(receipt.read_bytes())
    assert persisted["changed"] is False and persisted["any_changed"] is True
    assert "weights" not in capsys.readouterr().out
