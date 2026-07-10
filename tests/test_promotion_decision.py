"""Tests for the evidence-backed promotion decision core."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research.promotion_decision import (
    PromotionDecision,
    PromotionStatus,
    build_promotion_decision,
    build_promotion_decision_from_run,
    finalize_promotion_decision,
)


def _identity(*, matched: bool = True) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "matched": matched,
        "declared_contract_sha256": "declared-hash",
        "effective_contract_sha256": "declared-hash" if matched else "other-hash",
        "differences": [] if matched else ["$.strategy.top_n"],
    }


def _readiness(*, sufficient: bool = True) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "sufficient": sufficient,
        "skipped": not sufficient,
        "skip_reason": None if sufficient else "not enough retained symbols",
        "retained_symbols": ["A", "B", "C"] if sufficient else [],
    }


def _candidate(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate": "lgbm:daily_ranker/test/original",
        "n_windows": 4,
        "mean_icir": 0.40,
        "mean_rank_ic": 0.04,
        "mean_spread": 0.02,
        "positive_icir_ratio": 0.75,
        "positive_spread_ratio": 0.75,
        "worst_drawdown": -0.10,
        "ready_ratio": 1.0,
        "stable_research_candidate": True,
    }
    row.update(overrides)
    return row


def _stability(*candidates: dict[str, object]) -> dict[str, object]:
    rows = list(candidates or (_candidate(),))
    return {
        "schema_version": "1.0",
        "min_windows": 3,
        "n_reports": 4,
        "n_candidates": len(rows),
        "candidates": rows,
        "best_candidate": rows[0]["candidate"] if rows else None,
    }


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _complete_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    _write(run_dir / "execution_identity.json", _identity())
    _write(run_dir / "data_readiness.json", _readiness())
    _write(run_dir / "walk_forward_stability.json", _stability())
    return run_dir


def test_missing_evidence_fails_closed(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    decision = build_promotion_decision_from_run(run_dir)
    assert decision.status is PromotionStatus.MISSING_EVIDENCE
    assert decision.trade_ready is False
    assert set(decision.missing_evidence) == {
        "execution_identity",
        "data_readiness",
        "walk_forward_stability",
    }


def test_execution_identity_mismatch_is_rejected() -> None:
    decision = build_promotion_decision(
        subject_id="run-1",
        execution_identity=_identity(matched=False),
        data_readiness=_readiness(),
        walk_forward_stability=_stability(),
    )
    assert decision.status is PromotionStatus.REJECTED
    assert decision.failed_gates == ("execution_identity",)
    assert decision.trade_ready is False


def test_insufficient_data_readiness_is_rejected() -> None:
    decision = build_promotion_decision(
        subject_id="run-1",
        execution_identity=_identity(),
        data_readiness=_readiness(sufficient=False),
        walk_forward_stability=_stability(),
    )
    assert decision.status is PromotionStatus.REJECTED
    assert decision.failed_gates == ("data_readiness",)
    assert "not enough retained symbols" in decision.rationale


def test_complete_strong_evidence_promotes_trade_guidance_candidate() -> None:
    decision = build_promotion_decision(
        subject_id="run-1",
        execution_identity=_identity(),
        data_readiness=_readiness(),
        walk_forward_stability=_stability(),
    )
    assert decision.status is PromotionStatus.TRADE_GUIDANCE_CANDIDATE
    assert decision.trade_ready is True
    assert decision.failed_gates == ()
    assert decision.contract_sha256 == "declared-hash"


def test_partial_metric_evidence_remains_research_only() -> None:
    decision = build_promotion_decision(
        subject_id="run-1",
        execution_identity=_identity(),
        data_readiness=_readiness(),
        walk_forward_stability=_stability(
            _candidate(
                mean_icir=0.22,
                ready_ratio=0.50,
                positive_icir_ratio=0.50,
            )
        ),
    )
    assert decision.status is PromotionStatus.STRONGER_RESEARCH_CANDIDATE
    assert decision.trade_ready is False
    assert set(decision.failed_gates) >= {
        "mean_icir",
        "ready_ratio",
        "positive_icir_ratio",
    }


def test_no_stable_candidate_is_rejected() -> None:
    decision = build_promotion_decision(
        subject_id="run-1",
        execution_identity=_identity(),
        data_readiness=_readiness(),
        walk_forward_stability=_stability(
            _candidate(stable_research_candidate=False)
        ),
    )
    assert decision.status is PromotionStatus.REJECTED
    assert decision.failed_gates == ("stable_research_candidate",)


def test_finalize_writes_evidence_refs_and_deterministic_hashes(
    tmp_path: Path,
) -> None:
    run_dir = _complete_run(tmp_path)
    first = finalize_promotion_decision(run_dir)
    second = finalize_promotion_decision(run_dir)

    assert first["status"] == "trade_guidance_candidate"
    assert first["trade_ready"] is True
    assert first["evidence_refs"] == second["evidence_refs"]
    assert Path(first["artifact_path"]).is_file()
    assert {item["name"] for item in first["evidence_refs"]} == {
        "execution_identity",
        "data_readiness",
        "walk_forward_stability",
    }
    assert all(len(item["sha256"]) == 64 for item in first["evidence_refs"])


def test_trade_ready_cannot_be_set_on_non_promoted_status() -> None:
    with pytest.raises(ValueError, match="trade_ready"):
        PromotionDecision(
            subject_id="run-1",
            status=PromotionStatus.RESEARCH_CANDIDATE,
            trade_ready=True,
        )
