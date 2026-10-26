from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cli import main as cli
from src.research import formal_model_replay as replay
from src.research.replay_comparison import compare_package_sections


@pytest.fixture
def qqq_replay_context(tmp_path, monkeypatch):
    from src.research import qqq_authoritative_replay

    source = tmp_path / "etf" / "bundle_manifest.json"
    source.parent.mkdir()
    source.write_text('{"source_policy": "yahoo_research_v2"}')
    manifest = tmp_path / "strategy.json"
    document = {
        "professional_source_ready": False,
        "details": {"source_etf_manifest_path": str(source),
                    "source_etf_manifest_sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
    }
    manifest.write_text(json.dumps(document))
    candidate = {"model_id": "qqqi_qqq_tqqq_v4_3", "evidence_cutoff": "2026-10-23"}
    accepted = SimpleNamespace(identity={"bundle_id": "accepted-source"},
                               evidence_cutoff="2026-10-23", refresh_state=lambda: candidate)
    monkeypatch.setattr(replay, "load_formal_run", lambda *args: accepted)
    monkeypatch.setattr(replay, "prepare_data_recipe", lambda *args, **kwargs: {"product_manifest_path": str(manifest)})
    calls = []

    def verify(root, *, package_path, bundle_dir):
        calls.append((root, bundle_dir))
        assert json.loads(package_path.read_text()) == candidate
        assert bundle_dir == source.parent
        return {
            "trace_reproduction": {"exact": True, "frozen_economic_prefix": {"exact": True}},
            "data_identity": {"professional_source_ready": document["professional_source_ready"]},
            "frozen_economic_identity": {"historical_economics_recomputed_from_current_provider": False},
            "source_evidence": {"professional_source_ready": document["professional_source_ready"]},
            "historical_challenger_policy": "prospective_window_or_immutable_original_source_snapshot_required",
        }

    monkeypatch.setattr(qqq_authoritative_replay, "verify_qqq_authoritative_replay", verify)
    return SimpleNamespace(root=tmp_path, manifest=manifest, document=document,
                           source=source, calls=calls, authority=qqq_authoritative_replay)


@pytest.mark.parametrize("professional", [False, True])
def test_qqq_cli_reuses_authoritative_gate_without_promoting_source(qqq_replay_context, professional):
    context = qqq_replay_context
    context.document["professional_source_ready"] = professional
    context.manifest.write_text(json.dumps(context.document))
    result = replay.replay_qqq_v4_3(root=context.root)
    assert result["decision"] == "exact_replay"
    assert len(context.calls) == 1
    assert result["data_identity"]["professional_source_ready"] is professional
    assert result["data_identity"]["source_evidence"]["professional_source_ready"] is professional
    assert result["data_identity"]["frozen_economic_identity"]["historical_economics_recomputed_from_current_provider"] is False
    assert result["promotion_authorized"] is False and result["trade_ready"] is False


def test_qqq_cli_rejects_source_manifest_drift_before_evaluation(qqq_replay_context):
    context = qqq_replay_context
    context.source.write_text('{"changed": true}')
    result = replay.replay_qqq_v4_3(root=context.root)
    assert result["decision"] == "data_blocked"
    assert "hash mismatch" in result["reason"]
    assert context.calls == []


def test_qqq_cli_preserves_authoritative_identity_or_economic_rejection(qqq_replay_context, monkeypatch):
    from src.research.rules_formal_replay_gate import RulesFormalReplayError

    context = qqq_replay_context

    def reject(*args, **kwargs):
        raise RulesFormalReplayError("accepted decision or economic identity mismatch")

    monkeypatch.setattr(context.authority, "verify_qqq_authoritative_replay", reject)
    result = replay.replay_qqq_v4_3(root=context.root)
    assert result["decision"] == "invalid_evidence"
    assert "identity mismatch" in result["reason"]


@pytest.mark.parametrize("details", [None, [], {}, {"source_etf_manifest_path": None}, {"source_etf_manifest_path": ""}])
def test_qqq_cli_does_not_invent_an_unbound_source(qqq_replay_context, details):
    context = qqq_replay_context
    context.manifest.write_text(json.dumps({"professional_source_ready": False, "details": details}))
    result = replay.replay_qqq_v4_3(root=context.root)
    assert result["decision"] == "invalid_evidence"
    assert context.calls == []


def _package(value: float) -> dict:
    return {
        "portfolio_contract": {"cost_bps": 10},
        "report": [
            {
                "date": "2026-08-07",
                "period_return": value,
                "turnover": 0.5,
            }
        ],
        "positions": [
            {
                "date": "2026-08-07",
                "instrument": "QQQ",
                "weight": 1.0,
                "price": 100.0,
            }
        ],
        "trades": [
            {
                "date": "2026-08-07",
                "instrument": "QQQ",
                "previous_weight": 0.0,
                "target_weight": 1.0,
            }
        ],
    }


def test_trace_comparison_accepts_machine_precision_noise() -> None:
    expected = _package(0.01)
    observed = _package(0.01 + 5e-13)

    result = compare_package_sections(expected, observed)

    assert result["exact"] is True
    assert result["sections"]["report"]["first_mismatch"] is None


def test_trace_comparison_rejects_economic_drift() -> None:
    expected = _package(0.01)
    observed = _package(0.011)

    result = compare_package_sections(expected, observed)

    assert result["exact"] is False
    mismatch = result["sections"]["report"]["first_mismatch"]
    assert mismatch["field"] == "period_return"


def test_all_replay_requires_every_model_to_match(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        replay,
        "replay_qqq_v4_3",
        lambda **kwargs: {"decision": "exact_replay"},
    )
    monkeypatch.setattr(
        "src.research.cn27_v1_3_replay.replay_cn_27_v1_3",
        lambda **kwargs: {"decision": "exact_replay"},
    )
    monkeypatch.setattr(
        replay,
        "replay_byd_v1_3",
        lambda **kwargs: {"decision": "invalid_evidence"},
    )

    result = replay.replay_formal_models("all", root=tmp_path)

    assert result["status"] == "blocked"
    assert result["decision"] == "replay_failed"
    assert result["promotion_authorized"] is False


def test_cli_replay_returns_nonzero_when_exact_replay_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(
        replay,
        "replay_formal_models",
        lambda *args, **kwargs: {
            "status": "blocked",
            "decision": "replay_failed",
            "results": [],
            "research_only": True,
            "trade_ready": False,
        },
    )

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "research",
            "replay",
            replay.QQQ_REPLAY_ID,
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["decision"] == "replay_failed"


def test_cli_replay_returns_zero_on_exact_replay(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(
        replay,
        "replay_formal_models",
        lambda *args, **kwargs: {
            "status": "completed",
            "decision": "exact_replay",
            "results": [],
            "research_only": True,
            "trade_ready": False,
        },
    )

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "research",
            "replay",
            replay.BYD_REPLAY_ID,
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["decision"] == "exact_replay"


def test_committed_byd_v1_3_replays_exactly_from_bundle_v2_baseline() -> None:
    result = replay.replay_byd_v1_3(root=Path.cwd())

    assert result["decision"] == "exact_replay", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
    baseline = result["baseline"]
    assert baseline["manifest_path"].startswith("data/research/formal_model_runs/")
    assert "formal_backtests" not in baseline["manifest_path"]
    assert len(baseline["manifest_sha256"]) == 64
