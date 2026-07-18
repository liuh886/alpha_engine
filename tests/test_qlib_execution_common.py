"""Tests for the market-neutral Qlib execution helper boundary."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pytest

from src.research.cn_qlib_execution_adapter import execute_cn_qlib_plan
from src.research.paradigm import load_research_paradigm_spec
from src.research.qlib_execution_common import (
    ExecutionRuntime,
    build_effective_execution_contract,
    execute_qlib_plan,
    materialize_ranker_candidates,
)
from src.research.spec_bound_execution import (
    assert_execution_contract_identity,
    build_spec_bound_execution_plan,
    execute_spec_bound_research,
)
from src.research.us_qlib_execution_adapter import execute_us_qlib_plan

CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")
US_SPEC = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")


# ---------------------------------------------------------------------------
# Pre-existing contract-identity tests
# ---------------------------------------------------------------------------


def test_common_helpers_preserve_cn_and_us_contract_identity() -> None:
    for spec_path in (CN_SPEC, US_SPEC):
        plan = build_spec_bound_execution_plan(
            load_research_paradigm_spec(spec_path)
        )
        candidates = materialize_ranker_candidates(plan)
        requested_symbols = [
            str(item)
            for item in plan.declared_contract["universe"]["requested_symbols"]
        ]
        effective = build_effective_execution_contract(
            plan,
            candidates=candidates,
            baselines=dict(plan.baseline_factors),
            requested_symbols=requested_symbols,
        )

        assert [candidate.name for candidate in candidates] == [
            str(item["name"]) for item in plan.candidates
        ]
        assert_execution_contract_identity(plan.declared_contract, effective)


def test_market_adapters_do_not_import_each_other() -> None:
    cn_source = Path(
        "src/research/cn_qlib_execution_adapter.py"
    ).read_text(encoding="utf-8")
    us_source = Path(
        "src/research/us_qlib_execution_adapter.py"
    ).read_text(encoding="utf-8")

    assert "from src.research.us_qlib_execution_adapter" not in cn_source
    assert "from src.research.cn_qlib_execution_adapter" not in us_source
    assert "from src.research.qlib_execution_common import" in cn_source
    assert "from src.research.qlib_execution_common import" in us_source


# ---------------------------------------------------------------------------
# Delegation and market-rejection tests (ADR-0008)
# ---------------------------------------------------------------------------


class _FakeRuntime:
    """Runtime that exercises the shared engine's skip path deterministically."""

    def __init__(self, symbols: Sequence[str], *, market: str) -> None:
        self.symbols = set(symbols)
        self.market = market
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
            symbol: {"first_valid_date": None, "last_valid_date": None}
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
        return {"provider": "fake", "market": self.market}


def test_cn_wrapper_delegates_to_shared_engine(tmp_path: Path) -> None:
    """execute_cn_qlib_plan delegates through execute_qlib_plan(market='cn')."""
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(CN_SPEC))
    runtime = _FakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"], market="cn"
    )
    result = execute_cn_qlib_plan(
        plan, tmp_path / plan.spec.experiment_id, runtime=runtime
    )
    assert result.status == "skipped"
    assert result.runtime_metadata["provider"] == "fake"
    assert result.runtime_metadata["market"] == "cn"


def test_us_wrapper_delegates_to_shared_engine(tmp_path: Path) -> None:
    """execute_us_qlib_plan delegates through execute_qlib_plan(market='us')."""
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(US_SPEC))
    runtime = _FakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"], market="us"
    )
    result = execute_us_qlib_plan(
        plan, tmp_path / plan.spec.experiment_id, runtime=runtime
    )
    assert result.status == "skipped"
    assert result.runtime_metadata["provider"] == "fake"
    assert result.runtime_metadata["market"] == "us"


def test_shared_engine_rejects_market_mismatch(tmp_path: Path) -> None:
    """The shared engine raises when plan.spec.market != the market arg."""
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(US_SPEC))
    runtime = _FakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"], market="us"
    )
    with pytest.raises(ValueError, match="market='cn'"):
        execute_qlib_plan(
            plan, tmp_path / plan.spec.experiment_id, market="cn", runtime=runtime
        )


def test_cn_wrapper_rejects_us_spec(tmp_path: Path) -> None:
    """The CN wrapper rejects a US spec with a clear message."""
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(US_SPEC))
    runtime = _FakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"], market="cn"
    )
    with pytest.raises(ValueError, match="market='cn'"):
        execute_cn_qlib_plan(
            plan, tmp_path / plan.spec.experiment_id, runtime=runtime
        )


def test_us_wrapper_rejects_cn_spec(tmp_path: Path) -> None:
    """The US wrapper rejects a CN spec with a clear message."""
    plan = build_spec_bound_execution_plan(load_research_paradigm_spec(CN_SPEC))
    runtime = _FakeRuntime(
        plan.declared_contract["universe"]["requested_symbols"], market="us"
    )
    with pytest.raises(ValueError, match="market='us'"):
        execute_us_qlib_plan(
            plan, tmp_path / plan.spec.experiment_id, runtime=runtime
        )


def test_market_specific_metadata_preserved(tmp_path: Path) -> None:
    """CN and US runtimes produce different market metadata through the shared engine."""
    cn_plan = build_spec_bound_execution_plan(load_research_paradigm_spec(CN_SPEC))
    us_plan = build_spec_bound_execution_plan(load_research_paradigm_spec(US_SPEC))

    cn_runtime = _FakeRuntime(
        cn_plan.declared_contract["universe"]["requested_symbols"], market="cn"
    )
    us_runtime = _FakeRuntime(
        us_plan.declared_contract["universe"]["requested_symbols"], market="us"
    )

    cn_result = execute_qlib_plan(
        cn_plan,
        tmp_path / cn_plan.spec.experiment_id,
        market="cn",
        runtime=cn_runtime,
    )
    us_result = execute_qlib_plan(
        us_plan,
        tmp_path / us_plan.spec.experiment_id,
        market="us",
        runtime=us_runtime,
    )

    assert cn_result.runtime_metadata["market"] == "cn"
    assert us_result.runtime_metadata["market"] == "us"
    assert cn_result.runtime_metadata["provider"] == "fake"
    assert us_result.runtime_metadata["provider"] == "fake"


def test_both_wrappers_integrate_with_identity_gate(tmp_path: Path) -> None:
    """Both market wrappers survive the full identity-gate round-trip."""
    for spec_path, executor in (
        (CN_SPEC, execute_cn_qlib_plan),
        (US_SPEC, execute_us_qlib_plan),
    ):
        spec = load_research_paradigm_spec(spec_path)
        plan = build_spec_bound_execution_plan(spec)
        runtime = _FakeRuntime(
            plan.declared_contract["universe"]["requested_symbols"],
            market=spec.market,
        )
        result = execute_spec_bound_research(
            spec,
            partial(executor, runtime=runtime),
            output_dir=tmp_path / spec.experiment_id,
        )
        assert result["status"] == "skipped"
        assert result["contract_identity_verified"] is True


def test_shared_runtime_protocol_is_structural() -> None:
    """ExecutionRuntime is a structural Protocol — compatible objects satisfy it."""
    runtime = _FakeRuntime(["SH600000"], market="cn")
    # The Protocol check is structural; isinstance is not required.
    assert hasattr(runtime, "initialize")
    assert hasattr(runtime, "available_symbols")
    assert hasattr(runtime, "date_coverage")
    assert hasattr(runtime, "calendar")
    assert hasattr(runtime, "features")
    assert hasattr(runtime, "metadata")


def test_thin_adapters_do_not_duplicate_execution_logic() -> None:
    """Thin adapters delegate to execute_qlib_plan; they must not re-implement it."""
    cn_source = Path(
        "src/research/cn_qlib_execution_adapter.py"
    ).read_text(encoding="utf-8")
    us_source = Path(
        "src/research/us_qlib_execution_adapter.py"
    ).read_text(encoding="utf-8")

    # Thin adapters must delegate, not own execution logic.
    assert "execute_qlib_plan(" in cn_source
    assert "execute_qlib_plan(" in us_source

    # These execution-only identifiers must NOT appear in the thin adapters.
    for forbidden in (
        "build_window_sampling_plan",
        "purge_training_tail",
        "run_10d_experiment",
        "summarize_walk_forward_reports",
    ):
        assert forbidden not in cn_source, (
            f"CN adapter must not own {forbidden}"
        )
        assert forbidden not in us_source, (
            f"US adapter must not own {forbidden}"
        )
