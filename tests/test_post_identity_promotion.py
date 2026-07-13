"""Tests for canonical promotion finalization after execution identity proof."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

from src.research.paradigm import ResearchParadigmSpec
from src.research.spec_bound_execution import (
    SpecBoundExecutionResult,
    execute_spec_bound_research,
)

CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")


def _spec() -> ResearchParadigmSpec:
    if not CN_SPEC.is_file():
        pytest.skip("CN structured research contract is unavailable")
    return ResearchParadigmSpec.from_yaml(CN_SPEC)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _stable_candidate() -> dict[str, object]:
    return {
        "candidate": "lgbm:fixture",
        "stable_research_candidate": True,
        "n_windows": 3,
        "mean_icir": 0.40,
        "mean_rank_ic": 0.04,
        "mean_spread": 0.02,
        "worst_drawdown": -0.10,
        "ready_ratio": 1.0,
        "positive_icir_ratio": 1.0,
        "positive_spread_ratio": 1.0,
    }


def test_complete_evidence_overwrites_adapter_decision_surfaces() -> None:
    spec = _spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        readiness = run_dir / "data_readiness.json"
        stability = run_dir / "walk_forward_stability.json"
        legacy_pack = run_dir / "model_decision_pack.json"
        metrics = run_dir / "metrics_summary.json"
        _write(readiness, {"sufficient": True, "skipped": False})
        _write(
            stability,
            {
                "schema_version": "1.0",
                "min_windows": 3,
                "partial_window_policy": "complete_windows_only",
                "n_reports": 3,
                "n_candidates": 1,
                "candidates": [_stable_candidate()],
            },
        )
        _write(
            legacy_pack,
            {
                "source": "adapter_legacy_decision",
                "decision": {"status": "research_candidate", "trade_ready": False},
            },
        )
        _write(
            metrics,
            {
                "schema_version": "1.0",
                "decision": {"status": "adapter_legacy", "trade_ready": False},
            },
        )
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            runtime_metadata={"decision_status": "adapter_legacy"},
            evidence_paths={
                "data_readiness": str(readiness),
                "walk_forward_stability": str(stability),
                "model_decision_pack": str(legacy_pack),
                "metrics_summary": str(metrics),
            },
        )

    with tempfile.TemporaryDirectory() as output_dir:
        result = execute_spec_bound_research(
            spec,
            executor,
            output_dir=output_dir,
        )
        run_dir = Path(result["run_dir"])
        promotion = json.loads(
            (run_dir / "promotion_decision.json").read_text(encoding="utf-8")
        )
        pack = json.loads(
            (run_dir / "model_decision_pack.json").read_text(encoding="utf-8")
        )
        frontend = json.loads(
            (run_dir / "frontend_payload.json").read_text(encoding="utf-8")
        )
        metrics = json.loads(
            (run_dir / "metrics_summary.json").read_text(encoding="utf-8")
        )
        status = json.loads(
            (run_dir / "run_status.json").read_text(encoding="utf-8")
        )

        assert promotion["status"] == "trade_guidance_candidate"
        assert promotion["trade_ready"] is True
        assert pack["source"] == "promotion_decision"
        assert pack["decision"]["status"] == promotion["status"]
        assert pack["decision"]["trade_ready"] is promotion["trade_ready"]
        assert frontend["decision_status"] == promotion["status"]
        assert frontend["trade_ready"] is promotion["trade_ready"]
        assert metrics["decision_source"] == "promotion_decision"
        assert metrics["decision"]["status"] == promotion["status"]
        assert status["trade_ready"] is promotion["trade_ready"]
        assert status["runtime_metadata"]["decision_status"] == promotion["status"]
        assert result["promotion_decision"]["status"] == promotion["status"]
        assert "promotion_decision" in result["evidence_paths"]
        assert "frontend_payload" in result["evidence_paths"]


def test_identity_match_with_missing_bundle_is_fail_closed() -> None:
    spec = _spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        adapter_evidence = run_dir / "adapter_evidence.json"
        _write(adapter_evidence, {"status": "ok"})
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            evidence_paths={"adapter_evidence": str(adapter_evidence)},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        result = execute_spec_bound_research(
            spec,
            executor,
            output_dir=output_dir,
        )
        run_dir = Path(result["run_dir"])
        promotion = json.loads(
            (run_dir / "promotion_decision.json").read_text(encoding="utf-8")
        )
        status = json.loads(
            (run_dir / "run_status.json").read_text(encoding="utf-8")
        )

        assert promotion["status"] == "missing_evidence"
        assert promotion["trade_ready"] is False
        assert set(promotion["missing_evidence"]) == {
            "data_readiness",
            "walk_forward_stability",
        }
        assert status["trade_ready"] is False
        assert status["promotion_decision"]["status"] == "missing_evidence"


def test_identity_mismatch_never_writes_promotion_artifact() -> None:
    spec = _spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        effective = copy.deepcopy(plan.declared_contract)
        effective["strategy"]["top_n"] = int(effective["strategy"]["top_n"]) + 1
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=effective,
        )

    with tempfile.TemporaryDirectory() as output_dir:
        with pytest.raises(ValueError, match="execution contract mismatch"):
            execute_spec_bound_research(spec, executor, output_dir=output_dir)
        run_dir = Path(output_dir) / spec.experiment_id
        assert not (run_dir / "promotion_decision.json").exists()
