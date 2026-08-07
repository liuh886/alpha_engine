from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.artifacts.formal_refresh import (
    FormalRefreshError,
    build_plan,
    common_provider_cutoff,
    finalize_candidate_tree,
    load_object,
    sha256,
    verify_append_only_package,
    write_object,
)


def _package(model_id: str, market: str, cutoff: str) -> dict[str, object]:
    benchmark_key = "bench_hs300" if market == "cn" else "bench_qqq"
    return {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": f"{model_id}-accepted",
        "model_id": model_id,
        "display_name": model_id,
        "market": market,
        "benchmark": "CSI300" if market == "cn" else "QQQ",
        "publication_status": "accepted_formal_baseline",
        "generated_at": "2026-08-01T00:00:00Z",
        "evidence_cutoff": cutoff,
        "date_range": {"start": "2026-01-01", "end": cutoff},
        "trace_frequency": "daily" if model_id.startswith("qqq") else "non_overlapping_10_session",
        "portfolio_contract": {"rebalance_sessions": 10},
        "report": [
            {
                "date": cutoff,
                "account": 1.1,
                benchmark_key: 1.05,
                "holding_end_date": cutoff,
            }
        ],
        "positions": [{"date": cutoff, "instrument": "AAA", "weight": 1.0}],
        "trades": [{"date": cutoff, "instrument": "AAA", "period_index": 1}],
        "attribution": [],
        "metrics": {},
        "freshness": {
            "status": "current",
            "required_cutoff": cutoff,
            "latest_completed_session": cutoff,
            "model_selection_reopened": False,
        },
        "research_only": True,
        "trade_ready": False,
    }


def _write_tree(root: Path, packages: list[dict[str, object]]) -> None:
    records = []
    for index, package in enumerate(packages, start=1):
        model_id = str(package["model_id"])
        path = f"{model_id}.json"
        digest = write_object(root / path, package)
        records.append(
            {
                "model_id": model_id,
                "display_name": model_id,
                "display_order": index,
                "path": path,
                "publication_status": "accepted_formal_baseline",
                "sha256": digest,
            }
        )
    write_object(
        root / "catalog.json",
        {
            "schema_version": "1.0.0",
            "publication_policy": "formal_named_baselines_only",
            "published_at": "2026-08-01T00:00:00Z",
            "records": records,
            "research_only": True,
            "trade_ready": False,
        },
    )
    write_object(
        root / "freshness.json",
        {
            "schema_version": "1.0.0",
            "cutoff_policy": "latest_completed_trading_session",
            "markets": {"us": "2026-08-01", "cn": "2026-08-01"},
            "next_session_close_utc": {
                "us": "2026-08-04T23:30:00+00:00",
                "cn": "2026-08-04T08:30:00+00:00",
            },
            "required_models": [str(package["model_id"]) for package in packages],
            "research_only": True,
            "trade_ready": False,
        },
    )


def test_common_provider_cutoff_is_conservative() -> None:
    manifest = {
        "market": "us",
        "status": "selected_pool_price_refresh_ready",
        "promotion_eligible": True,
        "records": [
            {"symbol": "AAA", "last_date": "2026-08-05"},
            {"symbol": "BBB", "last_date": "2026-08-04"},
        ],
        "research_only": True,
        "trade_ready": False,
    }
    assert common_provider_cutoff(manifest, market="us") == "2026-08-04"


def test_common_provider_cutoff_rejects_ineligible_provider() -> None:
    manifest = {
        "market": "us",
        "status": "selected_pool_price_refresh_ready",
        "promotion_eligible": False,
        "records": [{"symbol": "AAA", "last_date": "2026-08-05"}],
        "research_only": True,
        "trade_ready": False,
    }
    with pytest.raises(FormalRefreshError, match="not promotion eligible"):
        common_provider_cutoff(manifest, market="us")


def test_plan_is_catalog_driven(tmp_path: Path) -> None:
    root = tmp_path / "formal"
    _write_tree(
        root,
        [
            _package("qqqi_qqq_tqqq_v4_2", "us", "2026-08-01"),
            _package("cn_x1_1", "cn", "2026-08-01"),
        ],
    )
    plan = build_plan(
        root,
        target_cutoffs={"us": "2026-08-05", "cn": "2026-08-04"},
        generated_at="2026-08-06T00:00:00+00:00",
    )
    assert plan.refresh_required is True
    assert plan.stale_model_ids == ("qqqi_qqq_tqqq_v4_2", "cn_x1_1")
    assert [record.model_id for record in plan.models] == [
        "qqqi_qqq_tqqq_v4_2",
        "cn_x1_1",
    ]


def test_append_only_verifier_rejects_historical_rewrite() -> None:
    current = _package("us_x1_1", "us", "2026-08-01")
    candidate = copy.deepcopy(current)
    candidate["evidence_cutoff"] = "2026-08-05"
    candidate["date_range"]["end"] = "2026-08-05"  # type: ignore[index]
    candidate["freshness"] = {
        "status": "current",
        "required_cutoff": "2026-08-05",
        "latest_completed_session": "2026-08-05",
        "model_selection_reopened": False,
    }
    candidate["report"][0]["account"] = 9.0  # type: ignore[index]
    with pytest.raises(FormalRefreshError, match="immutable prefix"):
        verify_append_only_package(current, candidate, target_cutoff="2026-08-05")


def test_finalize_accepts_stale_candidate_catalog_hashes_and_reseals(tmp_path: Path) -> None:
    current_root = tmp_path / "current"
    candidate_root = tmp_path / "candidate"
    current_packages = [
        _package("us_x1_1", "us", "2026-08-01"),
        _package("cn_x1_1", "cn", "2026-08-01"),
    ]
    _write_tree(current_root, current_packages)
    _write_tree(candidate_root, current_packages)

    for model_id, cutoff in (("us_x1_1", "2026-08-05"), ("cn_x1_1", "2026-08-04")):
        path = candidate_root / f"{model_id}.json"
        package = load_object(path)
        package["evidence_cutoff"] = cutoff
        package["date_range"]["end"] = cutoff
        package["freshness"] = {
            "status": "current",
            "required_cutoff": cutoff,
            "latest_completed_session": cutoff,
            "model_selection_reopened": False,
        }
        write_object(path, package)

    receipt = finalize_candidate_tree(
        current_root,
        candidate_root,
        target_cutoffs={"us": "2026-08-05", "cn": "2026-08-04"},
        generated_at="2026-08-06T00:00:00+00:00",
        receipt_path=tmp_path / "receipt.json",
    )
    assert receipt["status"] == "candidate_ready_for_review"
    catalog = load_object(candidate_root / "catalog.json")
    for row in catalog["records"]:
        assert row["sha256"] == sha256(candidate_root / row["path"])
