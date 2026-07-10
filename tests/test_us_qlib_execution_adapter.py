"""Qlib-free contract tests for the US spec-bound adapter."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pytest

from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.spec_bound_execution import (
    assert_execution_contract_identity,
    build_spec_bound_execution_plan,
    execute_spec_bound_research,
)
from src.research.us_qlib_execution_adapter import execute_us_qlib_plan

US_SPEC = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")
CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")


class SkippedUSRuntime:
    """Provider that has instruments but no valid date coverage."""

    def __init__(self, symbols: Sequence[str]) -> None:
        self.symbols = {str(item).upper() for item in symbols}
        self.initialized = False

    def initialize(self, repository_root: Path) -> None:
        assert (repository_root / "configs").is_dir()
        self.initialized = True

    def available_symbols(self) -> set[str]:
        assert self.initialized
        return set(self.symbols)

    def date_coverage(
        self,
        symbols: Sequence[str],
        start: str,
        end: str,
    ) -> dict[str, dict[str, Any]]:
        del start, end
        return {
            str(symbol): {"first_valid_date": None, "last_valid_date": None}
            for symbol in symbols
        }

    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        raise AssertionError(f"calendar must not run after coverage skip: {start}, {end}")

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        raise AssertionError(
            "features must not run after coverage skip: "
            f"{symbols}, {expressions}, {start}, {end}"
        )

    def metadata(self) -> dict[str, Any]:
        return {"provider": "fake", "market": "us"}


def _us_spec() -> ResearchParadigmSpec:
    return load_research_paradigm_spec(US_SPEC)


def test_us_plan_uses_declared_grid_and_top_n() -> None:
    plan = build_spec_bound_execution_plan(_us_spec())
    assert len(plan.candidates) == 16
    assert plan.declared_contract["strategy"]["top_n"] == 15
    assert plan.declared_contract["strategy"]["bottom_n"] == 15
    assert {
        item["feature_group"]["name"] for item in plan.candidates
    } == {
        "momentum",
        "momentum_volatility",
        "momentum_volatility_volume",
        "risk_controlled_momentum",
    }
    assert set(plan.baseline_factors) == {
        "factor:us_momentum_10d",
        "factor:us_risk_controlled_10d",
    }


def test_us_adapter_skips_before_features_when_coverage_is_missing(
    tmp_path: Path,
) -> None:
    plan = build_spec_bound_execution_plan(_us_spec())
    runtime = SkippedUSRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    result = execute_us_qlib_plan(
        plan,
        tmp_path / plan.spec.experiment_id,
        runtime=runtime,
    )
    assert result.status == "skipped"
    assert result.runtime_metadata["provider"] == "fake"
    assert result.runtime_metadata["top_n"] == 15
    assert result.runtime_metadata["bottom_n"] == 15
    assert_execution_contract_identity(
        plan.declared_contract,
        result.effective_contract,
    )
    for path in result.evidence_paths.values():
        assert Path(path).is_file()


def test_us_adapter_integrates_with_execution_identity_gate(tmp_path: Path) -> None:
    spec = _us_spec()
    plan = build_spec_bound_execution_plan(spec)
    runtime = SkippedUSRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    result = execute_spec_bound_research(
        spec,
        partial(execute_us_qlib_plan, runtime=runtime),
        output_dir=tmp_path,
    )
    assert result["status"] == "skipped"
    assert result["contract_identity_verified"] is True
    run_dir = Path(result["run_dir"])
    assert (run_dir / "execution_identity.json").is_file()
    assert (run_dir / "run_status.json").is_file()


def test_us_adapter_rejects_asymmetric_top_bottom(tmp_path: Path) -> None:
    spec = _us_spec()
    strategy = dict(spec.strategy)
    strategy["bottom_n"] = 10
    plan = build_spec_bound_execution_plan(replace(spec, strategy=strategy))
    runtime = SkippedUSRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    with pytest.raises(ValueError, match="top_n == bottom_n"):
        execute_us_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            runtime=runtime,
        )


def test_us_adapter_rejects_cn_spec(tmp_path: Path) -> None:
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(CN_SPEC))
    runtime = SkippedUSRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    with pytest.raises(ValueError, match="market='us'"):
        execute_us_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            runtime=runtime,
        )
