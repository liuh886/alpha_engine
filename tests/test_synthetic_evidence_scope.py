"""Regression test: generated providers can test mechanics but never promotion."""

from __future__ import annotations

import copy
import json
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


def test_fixture_manifest_marks_evidence_test_only(tmp_path: Path) -> None:
    spec = _spec()
    provider = tmp_path / "generated_provider"
    provider.mkdir()
    _write(provider / "fixture_manifest.json", {"synthetic": True})

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        readiness = run_dir / "data_readiness.json"
        stability = run_dir / "walk_forward_stability.json"
        _write(readiness, {"sufficient": True, "skipped": False})
        _write(
            stability,
            {
                "schema_version": "1.0",
                "min_windows": 3,
                "partial_window_policy": "complete_windows_only",
                "n_reports": 3,
                "n_candidates": 1,
                "candidates": [
                    {
                        "candidate": "synthetic-perfect-candidate",
                        "stable_research_candidate": True,
                        "n_windows": 3,
                        "mean_icir": 10.0,
                        "mean_rank_ic": 1.0,
                        "mean_spread": 1.0,
                        "worst_drawdown": 0.0,
                        "ready_ratio": 1.0,
                        "positive_icir_ratio": 1.0,
                        "positive_spread_ratio": 1.0,
                    }
                ],
            },
        )
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            runtime_metadata={"provider_uri": str(provider)},
            evidence_paths={
                "data_readiness": str(readiness),
                "walk_forward_stability": str(stability),
            },
        )

    result = execute_spec_bound_research(
        spec,
        executor,
        output_dir=tmp_path / "runs",
    )
    run_dir = Path(result["run_dir"])
    readiness = json.loads(
        (run_dir / "data_readiness.json").read_text(encoding="utf-8")
    )
    promotion = json.loads(
        (run_dir / "promotion_decision.json").read_text(encoding="utf-8")
    )
    status = json.loads(
        (run_dir / "run_status.json").read_text(encoding="utf-8")
    )

    assert readiness["evidence_scope"] == "synthetic_ci"
    assert readiness["test_only"] is True
    assert promotion["status"] == "rejected"
    assert promotion["trade_ready"] is False
    assert promotion["failed_gates"] == ["evidence_scope"]
    assert status["trade_ready"] is False
