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
        rows: dict[str, np.ndarray] = {}

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
            [
                symbol_axis + 0.25 * np.cos(day / 17.0) * pattern
                for day in date_index
            ]
        )

        for expression in expressions:
            if expression == "RAW_10D_RETURN":
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
                "schema_version": "1.0",
                "groups": {
                    "signals": {
                        "description": "deterministic diagnostics",
                        "factors": [
                            {
                                "id": "test:positive",
                                "expression": "POSITIVE_SIGNAL",
                                "family": "signal",
                            },
                            {
                                "id": "test:negative",
                                "expression": "NEGATIVE_SIGNAL",
                                "family": "signal",
                            },
                            {
                                "id": "test:sparse",
                                "expression": "SPARSE_SIGNAL",
                                "family": "coverage",
                            },
                        ],
                    },
                    "factor_baselines": {
                        "description": "baseline",
                        "factors": [
                            {
                                "id": "factor:test_baseline",
                                "expression": "BASELINE_SIGNAL",
                                "family": "baseline",
                            }
                        ],
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
                "schema_version": "1.0",
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
                    "groups": ["signals"],
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
                    "factor_baselines": ["factor:test_baseline"],
                },
                "strategy": {
                    "horizon_days": 10,
                    "holding_days": 10,
                    "rebalance_days": 10,
                    "top_n": 5,
                    "bottom_n": 5,
                    "return_expression": "RAW_10D_RETURN",
                    "return_provenance": "raw_forward_return",
                    "research_only": True,
                },
                "walk_forward": {
                    "requested_train_start": "2021-01-01",
                    "test_end": "2026-06-18",
                    "first_test_year": 2024,
                    "last_test_year": 2026,
                    "min_windows": 3,
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
    provider.mkdir()
    spec = load_research_paradigm_spec(spec_path)
    contract = build_declared_execution_contract(spec)
    return {
        "schema_version": "1.0",
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
    return {row["id"]: row for row in report["factors"]}


def test_factor_diagnostics_are_spec_bound_and_diagnostic_only(tmp_path: Path) -> None:
    spec_path, symbols = _write_spec(tmp_path)
    spec = load_research_paradigm_spec(spec_path)
    acceptance = _acceptance(tmp_path, spec_path)

    report = run_factor_diagnostics(
        spec,
        acceptance,
        repository_root=tmp_path,
        runtime=FakeFactorRuntime(symbols),
    )

    factors = _by_id(report)
    assert report["diagnostic_only"] is True
    assert report["promotion_eligible"] is False
    assert report["promotion_evaluated"] is False
    assert report["trade_ready"] is False
    assert report["return_contract"]["rebalance_days"] == 10
    assert report["return_contract"]["horizon_days"] == 10
    assert report["sampled_rebalance_dates"] > 50
    assert report["factor_count"] == 4

    assert factors["test:positive"]["recommended_orientation"] == "keep_score"
    assert factors["test:positive"]["oriented_mean_rank_ic"] > 0.8
    assert factors["test:positive"]["oriented_mean_top_bottom_spread"] > 0.0
    assert factors["test:negative"]["recommended_orientation"] == "invert_score"
    assert factors["test:negative"]["oriented_mean_rank_ic"] > 0.8
    assert factors["test:negative"]["oriented_mean_top_bottom_spread"] > 0.0
    assert factors["test:sparse"]["coverage_ratio"] < factors["test:positive"]["coverage_ratio"]
    assert len(factors["test:positive"]["window_metrics"]) >= 3


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
            runtime=FakeFactorRuntime(symbols),
        )
