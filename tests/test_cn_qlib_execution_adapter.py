"""Tests for the CN spec-bound Qlib adapter without importing Qlib."""

from __future__ import annotations

import json
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pytest

from scripts.run_cn_feature_quality_validation import _record_unhandled_failure
from src.research.cn_qlib_execution_adapter import execute_cn_qlib_plan
from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.research_artifacts import (
    build_research_run_paths,
    write_run_status,
)
from src.research.spec_bound_execution import (
    assert_execution_contract_identity,
    build_spec_bound_execution_plan,
    execute_spec_bound_research,
)

CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")
US_SPEC = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")


class SkippedFakeRuntime:
    """Runtime that proves the adapter can fail closed without Qlib."""

    def __init__(self, symbols: Sequence[str]) -> None:
        self.symbols = set(symbols)
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
            symbol: {
                "first_valid_date": None,
                "last_valid_date": None,
            }
            for symbol in symbols
        }

    def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
        raise AssertionError(
            f"calendar must not be called for skipped coverage: {start}, {end}"
        )

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        raise AssertionError(
            "features must not be called for skipped coverage: "
            f"{symbols}, {expressions}, {start}, {end}"
        )

    def metadata(self) -> dict[str, Any]:
        return {"provider": "fake", "market": "cn"}


def _cn_spec() -> ResearchParadigmSpec:
    return load_research_paradigm_spec(CN_SPEC)


def test_cn_plan_uses_declared_grid_and_top_n() -> None:
    plan = build_spec_bound_execution_plan(_cn_spec())
    assert len(plan.candidates) == 8
    assert plan.declared_contract["strategy"]["top_n"] == 15
    assert plan.declared_contract["strategy"]["bottom_n"] == 15
    assert {
        item["feature_group"]["name"] for item in plan.candidates
    } == {
        "cn_short_reversal_liquidity",
        "cn_volatility_reversal",
        "cn_price_volume_pressure",
        "cn_balanced_ohlcv",
    }
    assert set(plan.baseline_factors) == {
        "factor:cn_momentum_10d",
        "factor:cn_reversal_5d",
        "factor:cn_volatility_10d",
        "factor:cn_volume_shock_10d",
    }


def test_cn_adapter_skips_before_market_features_when_coverage_is_missing(
    tmp_path: Path,
) -> None:
    plan = build_spec_bound_execution_plan(_cn_spec())
    runtime = SkippedFakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    result = execute_cn_qlib_plan(
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


def test_cn_adapter_integrates_with_identity_gate_on_skip(tmp_path: Path) -> None:
    spec = _cn_spec()
    plan = build_spec_bound_execution_plan(spec)
    runtime = SkippedFakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    executor = partial(execute_cn_qlib_plan, runtime=runtime)
    result = execute_spec_bound_research(
        spec,
        executor,
        output_dir=tmp_path,
    )
    assert result["status"] == "skipped"
    assert result["contract_identity_verified"] is True
    run_dir = Path(result["run_dir"])
    assert (run_dir / "declared_execution_contract.json").is_file()
    assert (run_dir / "effective_execution_contract.json").is_file()
    assert (run_dir / "execution_identity.json").is_file()
    assert (run_dir / "run_status.json").is_file()


def test_unhandled_cli_failure_replaces_stale_prepared_status(tmp_path: Path) -> None:
    experiment_id = "cn_failure_test"
    paths = build_research_run_paths(None, experiment_id, output_dir=tmp_path)
    write_run_status(
        paths,
        experiment_id=experiment_id,
        status="prepared",
        reason="contract prepared",
    )
    _record_unhandled_failure(
        root=Path.cwd(),
        output_dir=tmp_path,
        experiment_id=experiment_id,
        exc=RuntimeError("provider failed"),
    )
    payload = json.loads(paths.run_status.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_stage"] == "cn_qlib_execution"
    assert payload["trade_ready"] is False
    assert payload["exception_type"] == "RuntimeError"


def test_unhandled_cli_failure_preserves_identity_failure(tmp_path: Path) -> None:
    experiment_id = "cn_identity_failure_test"
    paths = build_research_run_paths(None, experiment_id, output_dir=tmp_path)
    write_run_status(
        paths,
        experiment_id=experiment_id,
        status="failed",
        failed_stage="execution_identity",
        reason="contract mismatch",
    )
    _record_unhandled_failure(
        root=Path.cwd(),
        output_dir=tmp_path,
        experiment_id=experiment_id,
        exc=RuntimeError("secondary failure"),
    )
    payload = json.loads(paths.run_status.read_text(encoding="utf-8"))
    assert payload["failed_stage"] == "execution_identity"
    assert payload["reason"] == "contract mismatch"


def test_cn_adapter_rejects_asymmetric_top_bottom_contract(tmp_path: Path) -> None:
    spec = _cn_spec()
    strategy = dict(spec.strategy)
    strategy["bottom_n"] = 10
    asymmetric = replace(spec, strategy=strategy)
    plan = build_spec_bound_execution_plan(asymmetric)
    runtime = SkippedFakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    with pytest.raises(ValueError, match="top_n == bottom_n"):
        execute_cn_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            runtime=runtime,
        )


def test_cn_adapter_rejects_non_cn_spec(tmp_path: Path) -> None:
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(US_SPEC))
    runtime = SkippedFakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    with pytest.raises(ValueError, match="market='cn'"):
        execute_cn_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            runtime=runtime,
        )
