"""Tests for the market-neutral Qlib execution helper boundary."""

from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import pytest

from src.research.cn_qlib_execution_adapter import execute_cn_qlib_plan
from src.research.paradigm import load_research_paradigm_spec
from src.research.qlib_execution_common import (
    ExecutionRuntime,
    _resolve_benchmark_instrument,
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


# ---------------------------------------------------------------------------
# Benchmark loading and pass-through tests
# ---------------------------------------------------------------------------


def _make_window_index(dates, instruments):
    return pd.MultiIndex.from_product(
        [pd.to_datetime(dates), instruments],
        names=["datetime", "instrument"],
    )


def _benchmark_return_frame(dates, values):
    """Simulate a DatetimeIndex one-column ['return'] benchmark DataFrame."""
    return pd.DataFrame(
        {"return": values},
        index=pd.DatetimeIndex(pd.to_datetime(dates)),
    )


def _minimal_plan_with_benchmark(benchmark="QQQ"):
    """Build a minimal execution plan stub for benchmark-pass-through tests."""
    from src.research.paradigm import ResearchParadigmSpec

    strategy = {
        "horizon_days": 10,
        "holding_days": 10,
        "rebalance_days": 10,
        "top_n": 3,
        "bottom_n": 3,
        "return_expression": "Ref($close, -10) / $close - 1",
        "return_provenance": "raw_forward_return",
        "research_only": True,
    }
    universe = {
        "source": "configs/research_universes/us_curated_equities_v1.yaml",
        "market_key": "us",
        "min_symbols": 3,
        "alignment_mode": "auto",
    }
    factor_library = {
        "source": "configs/factor_libraries/us_ohlcv.yaml",
        "groups": ["momentum"],
    }
    candidate_grid = {
        "ranker": {
            "model_families": ["lgbm"],
            "calibrations": [
                {
                    "n_gain_bins": 5,
                    "num_boost_round": 10,
                    "num_leaves": 15,
                    "min_data_in_leaf": 5,
                }
            ],
        },
        "factor_baselines": [],
    }
    walk_forward = {
        "requested_train_start": "2021-01-01",
        "test_end": "2025-12-31",
        "first_test_year": 2024,
        "last_test_year": 2025,
        "min_windows": 3,
        "train_embargo_sessions": 10,
        "partial_window_policy": "complete_windows_only",
    }
    evaluation = {
        "benchmark_mode": "reference_only",
        "metrics": [
            "mean_icir",
            "mean_rank_ic",
            "mean_spread",
            "worst_drawdown",
            "ready_ratio",
            "positive_icir_ratio",
            "positive_spread_ratio",
        ],
        "gate_profile": "ten_day_model_gates_v1",
    }
    outputs = {"artifact_profile": "research_run_v1"}
    spec = ResearchParadigmSpec(
        experiment_id="test_benchmark",
        market="us",
        benchmark=benchmark,
        universe=universe,
        factor_library=factor_library,
        candidate_grid=candidate_grid,
        strategy=strategy,
        walk_forward=walk_forward,
        evaluation=evaluation,
        outputs=outputs,
        spec_path="test_spec.yaml",
        schema_version="1.1",
    )
    from src.research.spec_bound_execution import build_spec_bound_execution_plan

    return build_spec_bound_execution_plan(spec)


# ---------------------------------------------------------------------------
# Shared benchmark test helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_experiment(instruments, cal_dates, eval_dates):
    """Patch fit_ranker_scores and run_10d_experiment, yielding mock_run."""
    from unittest import mock

    import numpy as np

    with mock.patch(
        "src.research.qlib_execution_common.fit_ranker_scores",
        return_value=pd.DataFrame(
            {"score": np.random.normal(0, 1, len(eval_dates) * len(instruments))},
            index=_make_window_index(
                [d.strftime("%Y-%m-%d") for d in eval_dates], instruments
            ),
        ),
    ), mock.patch(
        "src.research.qlib_execution_common.run_10d_experiment",
        return_value={"status": "ok"},
    ) as mock_run:
        yield mock_run


class _BenchmarkTestRuntime:
    """Configurable runtime for benchmark pass-through/fail-closed tests.

    Parameters
    ----------
    instruments : sequence of str
        Tradable universe symbols (without the benchmark).
    cal_dates : DatetimeIndex
        Calendar dates for the test window.
    benchmark_features_fn : callable (start, end) -> DataFrame, optional
        Produces the benchmark features DataFrame. Default is random returns.
    provider : str
        Value returned by metadata()["provider"].
    """

    def __init__(
        self,
        instruments,
        cal_dates,
        *,
        benchmark_features_fn=None,
        provider="benchmark_test",
    ):
        self._instruments = set(instruments)
        self._cal_dates = cal_dates
        self._bm_fn = benchmark_features_fn or _default_benchmark_features
        self._provider = provider
        self.universe_calls = []

    def initialize(self, repo_root):
        pass

    def available_symbols(self):
        return self._instruments | {"QQQ"}

    def date_coverage(self, symbols, start, end):
        return {
            s: {"first_valid_date": "2021-01-04", "last_valid_date": "2025-12-31"}
            for s in symbols
        }

    def calendar(self, start, end):
        return self._cal_dates

    def features(self, symbols, expressions, start, end):
        self.universe_calls.append((list(symbols), list(expressions)))
        if isinstance(symbols, list) and len(symbols) == 1 and symbols[0] == "QQQ":
            return self._bm_fn(start, end)
        import numpy as np

        idx = _make_window_index(
            [d.strftime("%Y-%m-%d") for d in self._cal_dates], symbols
        )
        data = pd.DataFrame(
            np.random.normal(0, 0.02, size=(len(idx), len(expressions))),
            index=idx,
            columns=list(expressions),
        )
        data.attrs["provenance"] = "raw_forward_return"
        data.attrs["horizon"] = 10
        return data

    def metadata(self):
        return {"provider": self._provider}


def _default_benchmark_features(start, end):
    """Default: random normal daily returns."""
    import numpy as np

    benchmark_dates = pd.date_range(start, end, freq="B")
    return _benchmark_return_frame(
        [d.strftime("%Y-%m-%d") for d in benchmark_dates],
        np.random.normal(0.001, 0.01, len(benchmark_dates)),
    )


def _empty_benchmark_features(start, end):
    """Return empty DataFrame to simulate missing benchmark data."""
    return pd.DataFrame(
        index=pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([]), pd.Index([], dtype=object)],
            names=["datetime", "instrument"],
        ),
    )


def test_benchmark_passed_to_run_10d_experiment(tmp_path):
    """Benchmark returns are loaded separately and passed to run_10d_experiment."""
    from src.research.qlib_execution_common import execute_qlib_plan

    plan = _minimal_plan_with_benchmark("QQQ")
    instruments = list(plan.declared_contract["universe"]["requested_symbols"])[:5]
    cal_dates = pd.date_range("2021-01-04", "2025-12-31", freq="B")
    eval_dates = cal_dates[-5:]

    with _patch_experiment(instruments, cal_dates, eval_dates) as mock_run:
        execute_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            market="us",
            runtime=_BenchmarkTestRuntime(instruments, cal_dates),
        )
        assert mock_run.call_count >= 1
        for call_args in mock_run.call_args_list:
            _, kwargs = call_args
            bm = kwargs.get("benchmark_returns")
            assert bm is not None, "benchmark_returns must be passed to run_10d_experiment"
            assert list(bm.columns) == ["return"]
            assert isinstance(bm.index, pd.DatetimeIndex)


def test_missing_benchmark_data_skips_window_with_reason(tmp_path):
    """When benchmark data is empty, the window is skipped with a clear reason."""
    from src.research.qlib_execution_common import execute_qlib_plan

    plan = _minimal_plan_with_benchmark("QQQ")
    instruments = list(plan.declared_contract["universe"]["requested_symbols"])[:5]
    cal_dates = pd.date_range("2021-01-04", "2025-12-31", freq="B")
    eval_dates = cal_dates[-5:]

    with _patch_experiment(instruments, cal_dates, eval_dates) as mock_run:
        result = execute_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            market="us",
            runtime=_BenchmarkTestRuntime(
                instruments, cal_dates,
                benchmark_features_fn=_empty_benchmark_features,
                provider="empty_benchmark_test",
            ),
        )
        mock_run.assert_not_called()
        skipped = result.runtime_metadata.get("skipped_windows", [])
        assert len(skipped) >= 1
        assert any("empty data" in str(w.get("reason", "")) for w in skipped)


def test_benchmark_not_in_tradable_universe(tmp_path):
    """The benchmark instrument is loaded separately and never enters
    the tradable universe (retained_symbols)."""
    from src.research.qlib_execution_common import execute_qlib_plan

    plan = _minimal_plan_with_benchmark("QQQ")
    instruments = list(plan.declared_contract["universe"]["requested_symbols"])[:5]
    cal_dates = pd.date_range("2021-01-04", "2025-12-31", freq="B")
    eval_dates = cal_dates[-5:]

    runtime = _BenchmarkTestRuntime(
        instruments, cal_dates, provider="universe_check_test"
    )
    with _patch_experiment(instruments, cal_dates, eval_dates):
        execute_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            market="us",
            runtime=runtime,
        )

    # QQQ may appear only in its dedicated one-symbol benchmark call, never
    # co-mingled with the tradable universe.
    for symbols, _ in runtime.universe_calls:
        if "QQQ" in symbols:
            assert symbols == ["QQQ"]


# ---------------------------------------------------------------------------
# Benchmark symbol resolution for CN index codes
# ---------------------------------------------------------------------------


def test_cn_benchmark_resolves_sh000300() -> None:
    """CN benchmark '000300' resolves to 'SH000300' when available."""
    result = _resolve_benchmark_instrument(
        "cn", "000300", {"SH000300", "SH600001", "SZ000001"}
    )
    assert result == "SH000300"


def test_cn_benchmark_resolves_sh000688() -> None:
    """CN benchmark '000688' (STAR 50) resolves to 'SH000688'."""
    result = _resolve_benchmark_instrument(
        "cn", "000688", {"SH000688", "SH600001"}
    )
    assert result == "SH000688"


def test_cn_benchmark_case_insensitive() -> None:
    """CN benchmark resolution matches case-insensitively."""
    result = _resolve_benchmark_instrument(
        "cn", "000300", {"sh000300", "SH600001", "SZ000001"}
    )
    assert result == "sh000300"


def test_cn_benchmark_raises_on_missing() -> None:
    """CN benchmark raises ValueError when no symbol matches."""
    with pytest.raises(ValueError, match="could not be resolved"):
        _resolve_benchmark_instrument(
            "cn", "000300", {"QQQ"}
        )


def test_cn_benchmark_raises_on_empty_available() -> None:
    """CN benchmark raises ValueError when available symbols is empty."""
    with pytest.raises(ValueError, match="could not be resolved"):
        _resolve_benchmark_instrument("cn", "000300", set())


def test_us_benchmark_resolution_unchanged() -> None:
    """US benchmark resolution via the general path stays unchanged."""
    result = _resolve_benchmark_instrument(
        "us", "QQQ", {"QQQ", "AAPL", "MSFT"}
    )
    assert result == "QQQ"


def test_us_benchmark_case_insensitive() -> None:
    """US benchmark resolution matches case-insensitively."""
    result = _resolve_benchmark_instrument(
        "us", "qqq", {"QQQ", "AAPL"}
    )
    assert result == "QQQ"


def test_us_benchmark_raises_on_missing() -> None:
    """US benchmark raises ValueError when no match."""
    with pytest.raises(ValueError, match="could not be normalized"):
        _resolve_benchmark_instrument("us", "QQQ", {"SPY", "AAPL"})


def test_us_benchmark_raises_on_empty_available_symbols() -> None:
    """US benchmark resolution fails closed when provider inventory is empty."""
    with pytest.raises(ValueError, match="could not be normalized"):
        _resolve_benchmark_instrument("us", "QQQ", set())
