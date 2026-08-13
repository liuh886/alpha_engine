from __future__ import annotations

from pathlib import Path

import pytest

from scripts.data.refresh_selected_pool_prices_v2 import (
    _decorate_manifest,
    build_hardened_router,
)
from scripts.run_formal_refresh_transaction import build_task_plan, finalize_refresh
from src.artifacts.formal_refresh import (
    FormalRefreshError,
    common_provider_cutoff,
    load_object,
    write_object,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog

FORMAL_V2 = Path("data/research/formal_model_runs")


def _provider_manifest(path: Path, *, market: str, cutoff: str) -> Path:
    write_object(
        path,
        {
            "market": market,
            "status": "selected_pool_price_refresh_ready",
            "promotion_eligible": True,
            "records": [
                {"symbol": "AAA", "last_date": cutoff},
                {"symbol": "BBB", "last_date": cutoff},
            ],
            "research_only": True,
            "trade_ready": False,
        },
    )
    return path


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


def test_plan_is_formal_v2_catalog_driven() -> None:
    freshness = load_object(FORMAL_V2 / "freshness.json")
    plan = build_task_plan(
        formal_v2_root=FORMAL_V2,
        cutoffs=dict(freshness["markets"]),
        generated_at="2026-08-13T10:30:00Z",
    )
    active = load_active_strategy_catalog()
    assert plan["schema_version"] == "formal_refresh_plan_v3"
    assert plan["active_model_version_ids"] == list(active.active_model_version_ids)
    assert {task["publication_input"] for task in plan["tasks"]} == {"native_bundle_v2"}
    assert "governed_evidence_model_ids" not in plan


def test_future_cutoff_marks_v2_records_stale_without_flat_state() -> None:
    plan = build_task_plan(
        formal_v2_root=FORMAL_V2,
        cutoffs={"us": "2026-08-13", "cn": "2026-08-13"},
        generated_at="2026-08-13T10:30:00Z",
    )
    assert set(plan["stale_model_ids"]) == {
        "qqqi_qqq_tqqq_v4_3",
        "us_x1_3",
        "cn_x1_1",
        "byd_v1_3_recovery_event_low_vol_confirmation_v1",
    }


def test_finalize_writes_v2_freshness_and_receipt(tmp_path: Path) -> None:
    us = _provider_manifest(tmp_path / "us.json", market="us", cutoff="2026-08-10")
    cn = _provider_manifest(tmp_path / "cn.json", market="cn", cutoff="2026-08-12")
    fan_in = tmp_path / "fan-in.json"
    write_object(
        fan_in,
        {
            "schema_version": "formal_strategy_fan_in_v2",
            "status": "complete",
            "publication_contract": "active_preview_bundle_v2",
            "expected_strategy_ids": [
                row.strategy_id for row in load_active_strategy_catalog().strategies
            ],
            "preview_catalog_sha256": "a" * 64,
            "research_only": True,
            "trade_ready": False,
        },
    )
    freshness_path = tmp_path / "freshness" / "freshness.json"
    receipt_path = tmp_path / "receipt.json"
    receipt = finalize_refresh(
        us_provider_manifest=us,
        cn_provider_manifest=cn,
        generated_at="2026-08-13T10:30:00Z",
        fan_in_receipt=fan_in,
        freshness_output=freshness_path,
        receipt_path=receipt_path,
    )
    freshness = load_object(freshness_path)
    assert receipt["schema_version"] == "formal_refresh_receipt_v2"
    assert receipt["status"] == "candidate_ready_for_review"
    assert freshness["markets"] == {"cn": "2026-08-12", "us": "2026-08-10"}
    assert freshness["required_models"] == list(
        load_active_strategy_catalog().active_model_version_ids
    )


def test_formal_refresh_parallelizes_and_seals_provider_builds() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "providers:\n    needs: prepare" in workflow
    assert "market: [us, cn]" in workflow
    assert "uses: actions/cache/restore@v4" in workflow
    assert "uses: actions/cache/save@v4" in workflow
    assert "formal-provider-${{ matrix.market }}-${{ github.run_id }}" in workflow


def test_formal_refresh_is_bundle_v2_only() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    runner = Path("scripts/run_formal_strategy_refresh.py").read_text(encoding="utf-8")
    transaction = Path("scripts/run_formal_refresh_transaction.py").read_text(encoding="utf-8")
    for text in (workflow, runner, transaction):
        assert "data/research/formal_backtests" not in text
        assert "CURRENT_FORMAL_ROOT" not in text
        assert "CANDIDATE_FORMAL_ROOT" not in text
    assert "--formal-v2-root" in workflow
    assert "--freshness-output" in workflow
    assert "TemporaryDirectory" in runner
    assert "build_preview_bundle" in runner
    assert '"publication_input": "native_bundle_v2"' in transaction


def test_formal_refresh_fans_out_and_fans_in_preview_v2_atomically() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "plan:\n    needs: [prepare, providers]" in workflow
    assert "strategy:\n    needs: [prepare, plan]" in workflow
    assert "task: ${{ fromJson(needs.plan.outputs.task_matrix) }}" in workflow
    assert workflow.count("fail-fast: false") >= 2
    assert "uv run python scripts/run_formal_strategy_refresh.py" in workflow
    assert "pattern: formal-strategy-*-${{ github.run_id }}" in workflow
    assert "run_formal_refresh_transaction.py assemble" in workflow
    assert "--candidate-preview-root \"$CANDIDATE_PREVIEW_ROOT\"" in workflow
    assert "--native-root \"$CANDIDATE_PREVIEW_ROOT\"" in workflow


def test_formal_refresh_yaml_contains_no_model_execution_recipe() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    strategy_start = workflow.index("\n  strategy:\n")
    publish_start = workflow.index("\n  publish:\n", strategy_start)
    strategy_block = workflow[strategy_start:publish_start]
    assert "scripts/refresh_qqq_v4_3_formal.py" not in strategy_block
    assert "scripts/refresh_ranker_formal.py cn" not in strategy_block
    assert "scripts/refresh_byd_v1_3_formal.py" not in strategy_block
    assert "scripts/run_formal_strategy_refresh.py" in strategy_block


def test_strategy_results_are_uploaded_even_when_one_task_fails() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Upload bounded strategy receipt and evidence")
    end = workflow.index("\n\n  publish:", start)
    block = workflow[start:end]
    assert "if: always()" in block
    assert "artifacts/formal-refresh/strategy-result" in block


def test_cn_duplicate_evidence_concurrency_lives_in_repository_runner() -> None:
    runner = Path("scripts/run_formal_strategy_refresh.py").read_text(encoding="utf-8")
    assert "subprocess.Popen(" in runner
    assert 'for suffix in ("a", "b")' in runner
    assert "process.wait()" in runner
    assert "--ledger-a" in runner
    assert "--ledger-b" in runner


def test_market_evidence_is_content_addressed_and_parallel() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Build shared governed Market Evidence")
    end = workflow.index("      - name: Build shared Model Data Bundle")
    block = workflow[start:end]
    assert block.count("--reuse-root data/research/market_evidence") == 2
    assert 'us_pid="$!"' in block
    assert 'cn_pid="$!"' in block
    assert 'wait "$us_pid" || status=1' in block
    assert 'wait "$cn_pid" || status=1' in block


def test_formal_refresh_publishes_one_shared_model_data_bundle() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("scripts/data/build_model_data_bundle.py") == 1
    assert "data/research/model_data_bundle_v1" in workflow
    assert "cancel-in-progress: false" in workflow
