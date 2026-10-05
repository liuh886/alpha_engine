"""Production-contract tests for BYD v1.3 signal evidence binding."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from src.research.byd_signal_evidence import (
    BYDSignalEvidenceError,
    bind_final_signal_identity,
    bind_manifest_observation_identity,
    close_evidence_is_current,
)
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID
import scripts.run_byd_signal_alert as signal_cli
from src.artifacts.strategy_signal_ledger import StrategySignalLedgerError, seal_signal_decision


def _observation() -> dict:
    return {
        "schema_version": "byd_v1_3_low_vol_prospective_v1",
        "candidate_model_id": MODEL_ID,
        "signal_date": "2026-08-10",
        "data_version": "v1-3-2026-08-10",
        "common_open_eligible": True,
        "source": {"recovery_event_observation_sha256": "a" * 64},
        "targets": {MODEL_ID: {"byd_weight": 0.75, "etf_weight": 0.25, "cash_weight": 0.0}},
        "champion": {"model_id": "byd_v1_2_convex_momentum_budget_v1"},
        "factors": {
            "market_state": "bear",
            "vol_state": "high",
            "mom_20": 0.01,
            "mom_60": -0.08,
            "drawdown_252": -0.20,
        },
    }


def _alert() -> dict:
    return {
        "fingerprint": "decision-identity",
        "markdown": "<!-- signal-fingerprint:decision-identity -->\n",
        "data_provenance": {
            "v1_3_source_manifest_sha256": "a" * 64,
            "source_observation_sha256": "b" * 64,
            "source_workflow": "byd-daily-signal-alert",
        },
        "factor_evidence": {
            "catalog_implementation_hash": "d" * 64,
            "source_sha256": "e" * 64,
        },
    }


def test_formal_close_freshness_uses_final_governed_observation_not_forward_label() -> None:
    observation = _observation()
    observation["prospective_eligible"] = False
    observation["prelaunch_seed"] = True
    assert close_evidence_is_current(observation) is True


def test_formal_close_freshness_accepts_exact_immutable_legacy_seed() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation.update(
        {
            "kind": "v1_3_low_vol_recovery_observation",
            "launch_after": "2026-08-10",
            "prelaunch_seed": True,
        }
    )
    assert close_evidence_is_current(observation) is True


def test_formal_close_freshness_rejects_missing_identity_after_legacy_seed() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation.update(
        {
            "kind": "v1_3_low_vol_recovery_observation",
            "launch_after": "2026-08-10",
            "prelaunch_seed": False,
            "signal_date": "2026-08-11",
        }
    )
    assert close_evidence_is_current(observation) is False


def test_manifest_hash_binds_immutable_observation_with_legacy_missing_field() -> None:
    observation = _observation()
    observation.pop("candidate_model_id")
    observation["signal_date"] = "2026-08-11"
    bound = bind_manifest_observation_identity(
        observation,
        observation_sha256="a" * 64,
        manifest={
            "schema_version": observation["schema_version"],
            "candidate_model_id": MODEL_ID,
            "observation_sha256": {"2026-08-11": "a" * 64},
        },
    )
    assert bound["candidate_model_id"] == MODEL_ID
    assert "candidate_model_id" not in observation


def test_manifest_binding_rejects_unsealed_observation() -> None:
    with pytest.raises(BYDSignalEvidenceError, match="not sealed"):
        bind_manifest_observation_identity(
            _observation(),
            observation_sha256="b" * 64,
            manifest={
                "schema_version": "byd_v1_3_low_vol_prospective_v1",
                "candidate_model_id": MODEL_ID,
                "observation_sha256": {"2026-08-10": "a" * 64},
            },
        )


def test_close_freshness_fails_when_final_source_identity_is_missing() -> None:
    observation = _observation()
    observation["source"] = {}
    assert close_evidence_is_current(observation) is False


def test_close_freshness_fails_on_wrong_model_identity() -> None:
    observation = _observation()
    observation["candidate_model_id"] = "wrong"
    assert close_evidence_is_current(observation) is False


def test_final_fingerprint_binds_factor_and_source_identity() -> None:
    first = bind_final_signal_identity(deepcopy(_alert()))
    changed = _alert()
    changed["factor_evidence"]["catalog_implementation_hash"] = "f" * 64
    second = bind_final_signal_identity(changed)

    assert first["decision_fingerprint"] == second["decision_fingerprint"]
    assert first["fingerprint"] != second["fingerprint"]
    assert f"signal-fingerprint:{first['fingerprint']}" in first["markdown"]
    assert "signal-fingerprint:decision-identity" not in first["markdown"]


@pytest.fixture
def sealed_cli(tmp_path: Path, monkeypatch):
    source_store = tmp_path / "source"
    ledger = tmp_path / "ledger"
    observation = _observation()
    observation.update({"prices": {"byd_open": 90.0, "etf_open": 1.41},
                        "lifecycle": {}, "detector": {}, "entry_confirmation": {}})
    raw = json.dumps(observation).encode("utf-8")
    (source_store / "observations").mkdir(parents=True)
    (source_store / "observations/2026-08-10.json").write_bytes(raw)
    (source_store / "manifest.json").write_text(json.dumps({
        "schema_version": observation["schema_version"],
        "candidate_model_id": MODEL_ID,
        "observation_sha256": {"2026-08-10": hashlib.sha256(raw).hexdigest()},
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "run_byd_signal_alert.py", "--source-store", str(source_store),
        "--state-store", str(ledger), "--output-dir", str(tmp_path / "seed-output"),
    ])
    assert signal_cli.main() == 0
    signal = json.loads((tmp_path / "seed-output/signal_alert.json").read_text())
    seal_signal_decision(ledger_root=ledger, model_version_id=MODEL_ID, signal=signal,
                         workflow_run_id="fixture-seal", commit_sha="a" * 40,
                         created_at_utc="2026-08-10T12:00:00Z")
    monkeypatch.setattr(sys, "argv", [
        "run_byd_signal_alert.py", "--source-store", str(source_store),
        "--state-store", str(ledger), "--output-dir", str(tmp_path / "outputs"),
        "--github-output", str(tmp_path / "github-output"),
    ])
    return source_store, ledger


def test_same_observation_reuses_sealed_factor_identity(tmp_path: Path, monkeypatch, sealed_cli) -> None:
    expected = signal_cli._previous_alert(sealed_cli[1])
    assert expected is not None
    def unexpected_evaluation(*args, **kwargs):
        pytest.fail("a sealed observation must not be re-evaluated or re-factorized")
    monkeypatch.setattr(signal_cli, "build_byd_signal_alert", unexpected_evaluation)
    monkeypatch.setattr(signal_cli, "build_strategy_factor_snapshot", unexpected_evaluation)
    assert signal_cli.main() == 0
    actual = json.loads((tmp_path / "outputs/signal_alert.json").read_text(encoding="utf-8"))
    assert actual == expected
    latest_before = (sealed_cli[1] / "latest.json").read_bytes()
    seal_signal_decision(ledger_root=sealed_cli[1], model_version_id=MODEL_ID, signal=actual,
                         workflow_run_id="fixture-retry", commit_sha="b" * 40,
                         created_at_utc="2026-08-11T12:00:00Z")
    assert (sealed_cli[1] / "latest.json").read_bytes() == latest_before
    assert "reused_sealed_decision=true" in (tmp_path / "github-output").read_text()
    assert (tmp_path / "outputs/signal_alert.md").is_file()


def test_same_date_source_revision_requires_correction(tmp_path: Path, monkeypatch, sealed_cli) -> None:
    monkeypatch.setattr(signal_cli, "_manifest_sha256", lambda path: "f" * 64)
    with pytest.raises(BYDSignalEvidenceError, match="governed correction"):
        signal_cli.main()
    assert not (tmp_path / "outputs/signal_alert.json").exists()


def test_new_observation_still_evaluates(tmp_path: Path, monkeypatch, sealed_cli) -> None:
    observation = signal_cli._latest_observation(sealed_cli[0])
    assert observation is not None
    observation["signal_date"] = "2026-10-08"
    monkeypatch.setattr(signal_cli, "_latest_observation", lambda path: observation)
    class EvaluationRequired(Exception):
        pass
    def evaluate(*args, **kwargs):
        raise EvaluationRequired()
    monkeypatch.setattr(signal_cli, "build_byd_signal_alert", evaluate)
    with pytest.raises(EvaluationRequired):
        signal_cli.main()


def test_prior_signal_is_read_through_ledger_validation(tmp_path: Path, sealed_cli) -> None:
    record = json.loads((sealed_cli[1] / "latest.json").read_text(encoding="utf-8"))
    record["signal"]["target_weights"]["BYD"] = 99.0
    (tmp_path / "latest.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StrategySignalLedgerError):
        signal_cli._previous_alert(tmp_path)
