"""Narrow-loop gates: the 23-name pool must close honestly or not at all."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.data.build_us_small_pool_bundle_components import (
    build_fundamental_component,
    build_price_component,
)


def _pool(tmp_path: Path) -> Path:
    pool = tmp_path / "pool.yaml"
    pool.write_text(
        yaml.safe_dump(
            {
                "pool_id": "us_small_pool_v2",
                "baskets": {
                    "a": {"symbols": ["AAA", "AAB"]},
                    "b": {"symbols": ["BBB"]},
                },
            }
        ),
        encoding="utf-8",
    )
    return pool


def test_price_component_marks_missing_candidates(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "canonical_symbol": "AAA",
                        "first_date": "2021-01-04",
                        "latest_date": "2026-09-08",
                    },
                    {
                        "canonical_symbol": "AAB",
                        "first_date": "2021-01-04",
                        "latest_date": "2026-09-08",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = build_price_component(
        candidates=["AAA", "AAB", "BBB"],
        coverage_path=coverage,
        cutoff="2026-09-08",
    )

    assert manifest["status"] == "partial"
    assert manifest["missing_symbols"] == ["BBB"]
    assert manifest["coverage_ratio"] == 2 / 3
    assert manifest["pool_id"] == "us_small_pool_v2"
    assert manifest["trade_ready"] is False


def test_price_component_ready_when_all_candidates_covered(
    tmp_path: Path,
) -> None:
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "canonical_symbol": "AAA",
                        "first_date": "2021-01-04",
                        "latest_date": "2026-09-08",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = build_price_component(
        candidates=["AAA"], coverage_path=coverage, cutoff="2026-09-08"
    )

    assert manifest["status"] == "ready"
    assert manifest["coverage_ratio"] == 1.0
    assert manifest["evidence_cutoff"] == "2026-09-08"


def test_fundamental_component_names_missing_symbols(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        json.dumps(
            {
                "rows": [
                    {"symbol": "AAA", "factor_ready": True},
                    {"symbol": "BBB", "factor_ready": False},
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = build_fundamental_component(
        candidates=["AAA", "BBB"], coverage_path=coverage, cutoff="2026-09-08"
    )

    assert manifest["status"] == "partial"
    assert manifest["missing_symbols"] == ["BBB"]
    assert manifest["coverage_ratio"] == 0.5


def test_restatement_keeps_first_seen_filing(tmp_path: Path) -> None:
    from src.research.fundamental_acceleration import load_fundamentals

    contract = {
        "point_in_time_input": {"accepted_form_types": ["10-Q"]},
    }
    fundamentals = tmp_path / "fundamentals.csv"
    pd.DataFrame(
        {
            "symbol": ["WDC", "WDC"],
            "fiscal_period_end": ["2023-09-29", "2023-09-29"],
            "filed_date": ["2023-11-07", "2024-10-31"],
            "revenue": [100.0, 101.0],
            "gross_profit": [30.0, 31.0],
            "currency": ["USD", "USD"],
            "form_type": ["10-Q", "10-Q"],
            "accession_id": ["a1", "a2"],
        }
    ).to_csv(fundamentals, index=False)
    resolved = load_fundamentals(fundamentals, contract, {"WDC"})

    # Restated comparative columns resolve to the first-seen filing: the
    # market traded on those numbers from the original filed_date.
    assert len(resolved) == 1
    assert str(resolved.iloc[0]["filed_date"].date()) == "2023-11-07"
    assert float(resolved.iloc[0]["revenue"]) == 100.0


def test_narrow_profile_matches_live_pool() -> None:
    contract = yaml.safe_load(
        Path("configs/data_contracts/model_data_bundle_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    profile = contract["profiles"]["us_small_pool_price_plus_fundamentals_v1"]
    pool = yaml.safe_load(
        Path("configs/pools/us_small_pool_v2.yaml").read_text(encoding="utf-8")
    )
    basket_symbols = [
        str(value).upper()
        for basket in pool["baskets"].values()
        for value in basket["symbols"]
    ]
    assert sorted(profile["candidate_symbols"]) == sorted(basket_symbols)
    assert profile["references"] == ["QQQ"]
    assert profile["candidate_pool_id"] == "us_small_pool_v2"
    assert {c["component_id"] for c in profile["required_components"]} == {
        "prices.us_small_pool_v2",
        "fundamentals.us_small_pool_v2",
    }


def test_narrow_experiment_verdict_is_manifest_bound() -> None:
    spec = yaml.safe_load(
        Path(
            "configs/research_experiments/us_small_pool_fundamental_acceleration_v1.yaml"
        ).read_text(encoding="utf-8")
    )
    receipt = json.loads(
        Path(
            "data/research/experiment_receipts/us_small_pool_fundamental_acceleration_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert spec["status"] == "completed_not_supported"
    assert spec["result_decision"] == "simple_fundamental_factor_not_supported"
    assert receipt["decision"] == spec["result_decision"]
    assert receipt["supported"] is False
    assert receipt["source_shas"]["decision"] == spec["result_decision_sha256"]
    assert spec["active"] is False
    assert spec["automatic_promotion_allowed"] is False
