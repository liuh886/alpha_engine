from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scripts.data.refresh_selected_pool_prices_v2 import (
    _decorate_manifest,
    build_hardened_router,
)
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
        "trace_frequency": (
            "daily" if model_id.startswith("qqq") else "non_overlapping_10_session"
        ),
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


def test_formal_planner_accepts_governed_cn_auxiliary_yahoo_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    manifest_path = tmp_path / "cn-manifest.json"
    write_object(
        manifest_path,
        {
            "market": "cn",
            "status": "selected_pool_price_refresh_ready",
            "records": [
                {
                    "symbol": "515180",
                    "action": "fetched_full_refresh",
                    "provider": "yfinance",
                    "first_date": "2021-01-04",
                    "last_date": "2026-08-07",
                    "attempts": [
                        {"provider": "akshare_sina", "ok": False},
                        {"provider": "akshare", "ok": False},
                        {"provider": "baostock", "ok": False},
                        {"provider": "efinance", "ok": False},
                        {
                            "provider": "yfinance",
                            "provider_symbol": "515180.SS",
                            "ok": True,
                        },
                    ],
                }
            ],
            "failures": [],
            "research_only": True,
            "trade_ready": False,
        },
    )
    manifest = _decorate_manifest(manifest_path, build_hardened_router("cn"))
    assert manifest["promotion_eligible"] is True
    assert manifest["formal_auxiliary_fallback_symbols"] == ["515180"]
    assert common_provider_cutoff(manifest, market="cn") == "2026-08-07"


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


def test_finalize_accepts_stale_candidate_catalog_hashes_and_reseals(
    tmp_path: Path,
) -> None:
    current_root = tmp_path / "current"
    candidate_root = tmp_path / "candidate"
    current_packages = [
        _package("us_x1_1", "us", "2026-08-01"),
        _package("cn_x1_1", "cn", "2026-08-01"),
    ]
    _write_tree(current_root, current_packages)
    _write_tree(candidate_root, current_packages)

    for model_id, cutoff in (
        ("us_x1_1", "2026-08-05"),
        ("cn_x1_1", "2026-08-04"),
    ):
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


def test_committed_operations_identity_matches_formal_bundle_catalog() -> None:
    catalog = load_object(Path("data/research/formal_model_runs/catalog.json"))
    operations = load_object(Path("data/research/strategy_operations/snapshots.json"))
    formal_by_id = {row["model_version_id"]: row for row in catalog["records"]}
    operation_by_id = {
        row["model_version_id"]: row for row in operations["records"]
    }
    assert set(operation_by_id) == set(formal_by_id)
    for model_id, record in operation_by_id.items():
        formal = formal_by_id[model_id]
        identity = record["source_identity"]
        assert identity["formal_bundle_id"] == formal["bundle_id"]
        assert identity["formal_run_id"] == formal["run_id"]
        assert identity["formal_evidence_cutoff"] == formal["evidence_cutoff"]


def test_us_x1_1_refresh_uses_locked_project_python() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Reproduce and refresh US x1.1 twice")
    end = workflow.index("      - name: Reproduce and refresh CN x1.1 twice")
    us_refresh = workflow[start:end]

    assert "uv run python - <<'PY'" in us_refresh
    assert "\n          python - <<'PY'\n" not in us_refresh
    assert "for suffix in a b; do" in us_refresh
    assert "scripts/run_us_feature_quality_validation.py" in us_refresh
    assert "--provider-uri artifacts/formal-refresh/provider-us/data/providers/us" in us_refresh
    assert "scripts/refresh_ranker_formal.py us" in us_refresh


def test_production_refresh_runs_allocation_regressions_before_network_work() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Validate refresh implementation before network work")
    end = workflow.index("      - name: Resolve transaction timestamp")
    preflight = workflow[start:end]
    assert "tests/test_refresh_allocation_formal.py" in preflight


def test_reviewed_refresh_waits_for_matching_pages_release_before_current_status() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    release_start = workflow.index(
        "      - name: Wait for candidate checks, merge reviewed refresh, and verify Pages"
    )
    status_start = workflow.index("      - name: Upsert refresh operating status")
    release = workflow[release_start:status_start]

    assert "gh workflow run deploy-pages.yml" not in release
    assert "--workflow deploy-pages.yml" in release
    assert "--event push" in release
    assert 'select(.headSha == \\"${merge_sha}\\")' in release
    assert 'gh run watch "$pages_run"' in release
    assert 'test "$pages_conclusion" = "success"' in release
    assert "pages_run_id=$pages_run" in release
    assert release_start < status_start

    status = workflow[status_start:]
    assert "PAGES_RUN_ID: ${{ steps.release.outputs.pages_run_id }}" in status
    assert "Pages live acceptance: required before current/closed status" in status
