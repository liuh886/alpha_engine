"""Tests for spec-bound execution identity and evidence acceptance."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import pytest

from src.research.paradigm import ResearchParadigmSpec
from src.research.spec_bound_execution import (
    DECLARED_EXECUTION_CONTRACT_FILENAME,
    EFFECTIVE_EXECUTION_CONTRACT_FILENAME,
    EXECUTION_IDENTITY_FILENAME,
    SpecBoundExecutionResult,
    build_declared_execution_contract,
    build_spec_bound_execution_plan,
    contract_sha256,
    execute_spec_bound_research,
)

CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")


def _load_cn_spec() -> ResearchParadigmSpec:
    if not CN_SPEC.is_file():
        pytest.skip("CN structured research contract is unavailable")
    return ResearchParadigmSpec.from_yaml(CN_SPEC)


def test_declared_contract_is_deterministic() -> None:
    spec = _load_cn_spec()
    first = build_declared_execution_contract(spec)
    second = build_declared_execution_contract(spec)
    assert first == second
    assert contract_sha256(first) == contract_sha256(second)
    assert first["experiment_id"] == spec.experiment_id
    assert first["universe"]["requested_symbols"]
    assert first["factors"]["candidates"]
    assert first["factors"]["baseline_factors"]


def test_plan_contains_exact_declared_candidates() -> None:
    spec = _load_cn_spec()
    plan = build_spec_bound_execution_plan(spec)
    declared = plan.declared_contract
    assert list(plan.candidates) == declared["factors"]["candidates"]
    assert plan.baseline_factors == declared["factors"]["baseline_factors"]
    assert plan.declared_contract_sha256 == contract_sha256(declared)


def test_matching_effective_contract_accepts_evidence() -> None:
    spec = _load_cn_spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        evidence = run_dir / "adapter_evidence.json"
        evidence.write_text('{"status":"ok"}', encoding="utf-8")
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            runtime_metadata={"retained_symbol_count": 50},
            evidence_paths={"adapter_evidence": "adapter_evidence.json"},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        result = execute_spec_bound_research(
            spec,
            executor,
            output_dir=output_dir,
        )
        run_dir = Path(result["run_dir"])
        assert result["status"] == "passed"
        assert result["contract_identity_verified"] is True
        assert result["declared_contract_sha256"] == result["effective_contract_sha256"]
        assert (run_dir / DECLARED_EXECUTION_CONTRACT_FILENAME).is_file()
        assert (run_dir / EFFECTIVE_EXECUTION_CONTRACT_FILENAME).is_file()
        identity = json.loads(
            (run_dir / EXECUTION_IDENTITY_FILENAME).read_text(encoding="utf-8")
        )
        assert identity["matched"] is True
        assert identity["differences"] == []
        status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        assert status["status"] == "passed"
        assert status["failed_stage"] == ""
        assert status["research_only"] is True
        assert status["trade_ready"] is False


def test_contract_mismatch_fails_before_evidence_acceptance() -> None:
    spec = _load_cn_spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        effective = copy.deepcopy(plan.declared_contract)
        effective["strategy"]["top_n"] = int(effective["strategy"]["top_n"]) + 1
        evidence = run_dir / "must_not_be_accepted.json"
        evidence.write_text('{"status":"should_not_attach"}', encoding="utf-8")
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=effective,
            evidence_paths={"invalid": str(evidence)},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        with pytest.raises(ValueError, match="execution contract mismatch"):
            execute_spec_bound_research(spec, executor, output_dir=output_dir)
        run_dir = Path(output_dir) / spec.experiment_id
        identity = json.loads(
            (run_dir / EXECUTION_IDENTITY_FILENAME).read_text(encoding="utf-8")
        )
        assert identity["matched"] is False
        assert any("strategy.top_n" in item for item in identity["differences"])
        status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        assert status["status"] == "failed"
        assert status["failed_stage"] == "execution_identity"
        assert status["trade_ready"] is False


def test_missing_declared_evidence_file_fails_closed() -> None:
    spec = _load_cn_spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            evidence_paths={"missing": "missing.json"},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        with pytest.raises(FileNotFoundError, match="missing evidence file"):
            execute_spec_bound_research(spec, executor, output_dir=output_dir)
