from __future__ import annotations

from pathlib import Path

from src.artifacts.formal_bundle_reader import load_formal_run
from src.governance.active_strategy_catalog import load_active_strategy_catalog


def test_every_active_formal_run_is_readable_from_bundle_v2() -> None:
    active = load_active_strategy_catalog()
    for strategy in active.strategies:
        run = load_formal_run(Path.cwd(), strategy.model_version_id)
        assert run.model_version_id == strategy.model_version_id
        assert run.manifest["publication_channel"] == "formal"
        assert run.manifest["publication_status"] == "accepted_formal_baseline"
        assert run.manifest["research_only"] is True
        assert run.manifest["trade_ready"] is False
        assert "formal_backtests" not in run.identity["manifest_path"]
        trace = run.replay_trace()
        assert trace["report"]
        assert trace["positions"]
        assert isinstance(trace["trades"], list)
        assert trace["portfolio_contract"]


def test_active_bundle_reader_exposes_digest_bound_identity() -> None:
    run = load_formal_run(Path.cwd(), "byd_v1_3_recovery_event_low_vol_confirmation_v1")
    identity = run.identity
    assert identity["bundle_id"] == run.manifest["bundle_id"]
    assert identity["evidence_cutoff"] == run.manifest["evidence_cutoff"]
    assert len(identity["manifest_sha256"]) == 64
    assert identity["manifest_path"].startswith("data/research/formal_model_runs/")
