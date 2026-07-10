"""Tests for the market-neutral Qlib execution helper boundary."""

from __future__ import annotations

from pathlib import Path

from src.research.paradigm import load_research_paradigm_spec
from src.research.qlib_execution_common import (
    build_effective_execution_contract,
    materialize_ranker_candidates,
)
from src.research.spec_bound_execution import (
    assert_execution_contract_identity,
    build_spec_bound_execution_plan,
)


def test_common_helpers_preserve_cn_and_us_contract_identity() -> None:
    for spec_path in (
        Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml"),
        Path("configs/research_paradigms/us_10d_qqq_baseline.yaml"),
    ):
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
