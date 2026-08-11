from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from src.research.paradigm import load_research_paradigm_spec
from src.research.spec_bound_execution import (
    build_declared_execution_contract,
    contract_sha256,
)
from src.research.spec_bound_factor_diagnostics import (
    _selected_factor_specs,
    _window_date_map,
    run_factor_diagnostics,
    run_factor_diagnostics_from_files,
)


class FakeFactorRuntime:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self.initialized = False

    def initialize(self, repository_root: Path) -> None:
        assert repository_root.is_dir()
        self.initialized = True

    def features(
        self,
        symbols: list[str],
        expressions: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        assert self.initialized
        assert symbols == self.symbols
        dates = pd.bdate_range(start, end)
        index = pd.MultiIndex.from_product(
            [dates, symbols], names=["datetime", "instrument"]
        )
        n_dates = len(dates)
        n_symbols = len(symbols)
        symbol_axis = np.linspace(-1.0, 1.0, n_symbols)
        pattern = np.sin(np.arange(n_symbols) * 0.7)
        date_index = np.arange(n_dates, dtype=float)
        return_values = np.concatenate(
            [
                symbol_axis
                + 0.18 * np.sin(day / 19.0) * pattern
                + 0.05 * np.cos(day / 7.0) * pattern[::-1]
                for day in date_index
            ]
        )
        positive_values = np.concatenate(
            [symbol_axis + 0.25 * np.cos(day / 17.0) * pattern for day in date_index]
        )

        rows: dict[str, np.ndarray] = {}
        for expression in expressions:
            if expression == "Ref($close, -10) / $close - 1":
                rows[expression] = return_values
            elif expression == "POSITIVE_SIGNAL":
                rows[expression] = positive_values
            elif expression == "NEGATIVE_SIGNAL":
                rows[expression] = -positive_values
            elif expression == "SPARSE_SIGNAL":
                sparse = positive_values.copy()
                mask = np.tile(np.arange(n_symbols) % 3 == 0, n_dates)
                sparse[mask] = np.nan
                rows[expression] = sparse
            elif expression == "BASELINE_SIGNAL":
                rows[expression] = np.tile(symbol_axis, n_dates)
            else:
                raise AssertionError(f"unexpected expression: {expression}")
        return pd.DataFrame(rows, index=index)

    def metadata(self) -> dict[str, Any]:
        return {"provider": "fake_real", "market": "us"}


def _write_spec(tmp_path: Path) -> tuple[Path, list[str]]:
    symbols = [f"S{i:03d}" for i in range(40)]
    universe_path = tmp_path / "universe.yaml"
    universe_path.write_text(
        yaml.safe_dump(
            {
                "metadata": {
                    "universe_id": "test_equities_v1",
                    "membership_mode": "static_curated",
                    "membership_as_of": "2026-07-11",
                    "asset_type": "equity",
                    "survivorship_bias": True,
                },
                "us": symbols,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    factor_path = tmp_path / "factors.yaml"
    factor_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2.0",
                "catalog": {"id": "test_factors", "version": "1.0"},
                "defaults": {
                    "namespace": "test",
                    "factor_version": "1.0",
                    "source_name": "unit-test",
                    "source_version": "1.0",
                    "source_reference": "unit-test",
                    "availability_lag_sessions": 0,
                    "adjustment_requirement": "adjusted",
                    "output_frequency": "day",
                    "output_dtype": "float64",
                    "missing_value_policy": "preserve_nan_after_warmup",
                    "status": "unvalidated_formula",
                },
                "factors": {
                    "test.positive": {
                        "display_name": "Positive",
                        "information_family": "signal",
                        "expression": "POSITIVE_SIGNAL",
                        "required_fields": ["close"],
                        "markets": ["us"],
                        "minimum_lookback": 0,
                    },
                    "test.negative": {
                        "display_name": "Negative",
                        "information_family": "signal",
                        "expression": "NEGATIVE_SIGNAL",
                        "required_fields": ["close"],
                        "markets": ["us"],
                        "minimum_lookback": 0,
                    },
                    "test.sparse": {
                        "display_name": "Sparse",
                        "information_family": "coverage",
                        "expression": "SPARSE_SIGNAL",
                        "required_fields": ["close"],
                        "markets": ["us"],
                        "minimum_lookback": 0,
                    },
                    "test.baseline": {
                        "display_name": "Baseline",
                        "information_family": "baseline",
                        "expression": "BASELINE_SIGNAL",
                        "required_fields": ["close"],
                        "markets": ["us"],
                        "minimum_lookback": 0,
                    },
                },
                "groups": {
                    "signals": {
                        "description": "deterministic diagnostics",
                        "factor_ids": ["test.positive", "test.negative", "test.sparse"],
                    },
                    "reuse_positive": {
                        "description": "group reuse without redefinition",
                        "factor_ids": ["test.positive"],
                    },
                    "factor_baselines": {
                        "description": "baseline",
                        "factor_ids": ["test.baseline"],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.1",
                "experiment_id": "test_factor_diagnostics",
                "market": "us",
                "benchmark": "QQQ",
                "universe": {
                    "source": str(universe_path),
                    "market_key": "us",
                    "universe_id": "test_equities_v1",
                    "membership_mode": "static_curated",
                    "membership_as_of": "2026-07-11",
                    "asset_type": "equity",
                    "survivorship_bias": True,
                    "min_symbols": 30,
                    "alignment_mode": "strict",
                },
                "factor_library": {
                    "source": str(factor_path),
                    "groups": ["signals", "reuse_positive"],
                },
                "candidate_grid": {
                    "ranker": {
                        "calibrations": [
                            {
                                "n_gain_bins": 5,
                                "num_boost_round": 10,
                                "num_leaves": 7,
                                "min_data_in_leaf": 2,
                                "learning_rate": 0.05,
                            }
                        ]
                    },
                    "factor_baselines": ["test.baseline"],
                },
                "strategy": {
                    "horizon_days": 10,
                    "holding_days": 10,
                    "rebalance_days": 10,
                    "top_n": 5,
                    "bottom_n": 5,
                    "return_expression": "Ref($close, -10) / $close - 1",
                    "return_provenance": "raw_forward_return",
                    "research_only": True,
                },
                "walk_forward": {
                    "requested_train_start": "2021-01-01",
                    "test_end": "2026-06-18",
                    "first_test_year": 2024,
                    "last_test_year": 2026,
                    "min_windows": 3,
                    "partial_window_policy": "complete_windows_only",
                    "train_embargo_sessions": 10,
                },
                "evaluation": {
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
                },
                "outputs": {"artifact_profile": "research_run_v1"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return spec_path, symbols


def _acceptance(tmp_path: Path, spec_path: Path) -> dict[str, Any]:
    provider = tmp_path / "provider"
    provider.mkdir(exist_ok=True)
    spec = load_research_paradigm_spec(spec_path)
    contract = build_declared_execution_contract(spec)
    return {
        "schema_version": "1.1",
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "accepted": True,
        "inputs": {
            "provider_dir": str(provider.resolve()),
            "declared_contract_sha256": contract_sha256(contract),
        },
        "checks": [
            {"name": name, "status": "pass", "message": "ok", "details": {}}
            for name in (
                "real_provider_scope",
                "calendar_coverage",
                "universe_provider_coverage",
                "benchmark_provider_coverage",
                "source_csv_integrity",
            )
        ],
    }


def _by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["factor_id"]: row for row in report["factors"]}


def test_factor_diagnostics_are_canonical_id_bound(tmp_path: Path) -> None:
    spec_path, symbols = _write_spec(tmp_path)
    spec = load_research_paradigm_spec(spec_path)
    selected = _selected_factor_specs(spec)
    assert [definition.factor_id for _, definition in selected] == [
        "test.positive",
        "test.negative",
        "test.sparse",
        "test.baseline",
    ]
    assert selected[0][0] == ("signals", "reuse_positive")

    report = run_factor_diagnostics(
        spec,
        _acceptance(tmp_path, spec_path),
        repository_root=tmp_path,
        runtime=FakeFactorRuntime(symbols),
    )
    factors = _by_id(report)

    assert report["schema_version"] == "2.0"
    assert report["diagnostic_only"] is True
    assert report["promotion_eligible"] is False
    assert report["trade_ready"] is False
    assert report["factor_count"] == 4
    assert report["ranking_subject"] == "factor_id"
    assert report["factor_library"]["catalog_id"] == "test_factors"
    assert len(report["factor_library"]["catalog_implementation_hash"]) == 64
    assert factors["test.positive"]["groups"] == ["signals", "reuse_positive"]
    assert len(factors["test.positive"]["implementation_hash"]) == 64
    assert factors["test.positive"]["recommended_orientation"] == "keep_score"
    assert factors["test.positive"]["oriented_mean_rank_ic"] > 0.8
    assert factors["test.negative"]["recommended_orientation"] == "invert_score"
    assert factors["test.sparse"]["coverage_ratio"] < factors["test.positive"]["coverage_ratio"]


def test_production_factor_libraries_have_no_duplicate_selected_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(repository_root)
    for spec_name in ("cn_10d_csi300_baseline.yaml", "us_10d_qqq_baseline.yaml"):
        spec = load_research_paradigm_spec(
            repository_root / "configs" / "research_paradigms" / spec_name
        )
        selected = _selected_factor_specs(spec)
        ids = [definition.factor_id for _, definition in selected]
        expressions = [definition.expression for _, definition in selected]
        assert len(ids) == len(set(ids))
        assert len(expressions) == len(set(expressions))


def test_factor_diagnostics_fail_closed_on_rejected_or_stale_acceptance(
    tmp_path: Path,
) -> None:
    spec_path, symbols = _write_spec(tmp_path)
    spec = load_research_paradigm_spec(spec_path)
    acceptance = _acceptance(tmp_path, spec_path)

    rejected = dict(acceptance)
    rejected["accepted"] = False
    with pytest.raises(ValueError, match="accepted real-market evidence"):
        run_factor_diagnostics(
            spec,
            rejected,
            repository_root=tmp_path,
            runtime=FakeFactorRuntime(symbols),
        )

    stale = json.loads(json.dumps(acceptance))
    stale["inputs"]["declared_contract_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="contract hash"):
        run_factor_diagnostics(
            spec,
            stale,
            repository_root=tmp_path,
            runtime=FakeFactorRuntime(symbols),
        )


def test_file_entrypoint_binds_acceptance_hash_and_provider(tmp_path: Path) -> None:
    spec_path, symbols = _write_spec(tmp_path)
    acceptance = _acceptance(tmp_path, spec_path)
    acceptance_path = tmp_path / "real_market_acceptance.json"
    acceptance_path.write_text(json.dumps(acceptance), encoding="utf-8")
    output = tmp_path / "factor_diagnostics.json"

    report = run_factor_diagnostics_from_files(
        spec_path,
        acceptance_path,
        repository_root=tmp_path,
        output_path=output,
        runtime=FakeFactorRuntime(symbols),
    )
    assert output.is_file()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["acceptance_report_sha256"] == report["acceptance_report_sha256"]
    assert len(report["acceptance_report_sha256"]) == 64

    other_provider = tmp_path / "other_provider"
    other_provider.mkdir()
    with pytest.raises(ValueError, match="provider accepted by the report"):
        run_factor_diagnostics_from_files(
            spec_path,
            acceptance_path,
            repository_root=tmp_path,
            provider_dir=other_provider,
            output_path=output,
            runtime=FakeFactorRuntime(symbols),
        )


def test_window_mapping_preserves_horizon_containment(tmp_path: Path) -> None:
    spec_path, _ = _write_spec(tmp_path)
    spec = load_research_paradigm_spec(spec_path)
    available = pd.bdate_range("2021-01-01", "2026-06-18")
    date_map, windows, policy = _window_date_map(available, spec)
    assert date_map
    assert windows
    assert policy["horizon_sessions"] == 10
    assert all(
        row["excluded_tail_sessions"] == 10
        for row in windows
        if row["status"] == "included"
    )
