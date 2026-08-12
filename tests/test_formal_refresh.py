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


def test_formal_refresh_parallelizes_and_seals_provider_builds() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "providers:\n    needs: prepare" in workflow
    assert "market: [us, cn]" in workflow
    assert "uses: actions/cache/restore@v4" in workflow
    assert "uses: actions/cache/save@v4" in workflow
    assert "-m scripts.govern_formal_provider_cache seal" in workflow
    assert "formal-provider-${{ matrix.market }}-${{ github.run_id }}" in workflow


def test_formal_refresh_fans_out_active_strategies_and_fans_in_atomically() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "plan:\n    needs: [prepare, providers]" in workflow
    assert "strategy:\n    needs: [prepare, plan]" in workflow
    assert "task: ${{ fromJson(needs.plan.outputs.task_matrix) }}" in workflow
    assert workflow.count("fail-fast: false") >= 2
    assert "uv run python scripts/run_formal_strategy_refresh.py" in workflow
    assert "publish:\n    needs: [prepare, providers, plan, strategy]\n    if: always()" in workflow
    assert "pattern: formal-strategy-*-${{ github.run_id }}" in workflow
    assert "merge-multiple: true" in workflow
    assert "run_formal_refresh_transaction.py assemble" in workflow
    assert '--fan-in-receipt "$FAN_IN_RECEIPT"' in workflow
    assert "--native-root \"$CANDIDATE_PREVIEW_ROOT\"" in workflow


def test_formal_refresh_yaml_contains_no_model_execution_recipe() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    for obsolete_step in (
        "Refresh QQQ Rotation v4.3 append-only",
        "Reproduce and refresh US x1.1 twice",
        "Rebuild active US x1.2 research preview with complete evidence",
        "Reproduce and refresh CN x1.1 twice",
        "Extend canonical inputs and refresh BYD v1.3",
    ):
        assert obsolete_step not in workflow
    assert "scripts/refresh_qqq_v4_3_formal.py" not in workflow
    assert "scripts/refresh_ranker_formal.py cn" not in workflow
    assert "scripts/refresh_byd_v1_3_formal.py" not in workflow
    assert "scripts/build_us_x1_2_preview.py" not in workflow


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
    assert (
        "prices.us_selected_equities_v2:selected_pool_prices:${CANDIDATE_MODEL_DATA_ROOT}"
        in workflow
    )
    assert (
        "prices.cn_selected_equities_v3:selected_pool_prices:${CANDIDATE_MODEL_DATA_ROOT}"
        in workflow
    )
    assert "data/research/model_data_bundle_v1" in workflow
    assert "cancel-in-progress: false" in workflow


def test_formal_refresh_frontend_validation_paths_are_complete() -> None:
    required = (
        '"qlib-dashboard/scripts/**"',
        '"qlib-dashboard/src/**"',
        '"qlib-dashboard/package.json"',
        '"qlib-dashboard/package-lock.json"',
        '"qlib-dashboard/vite.config.*"',
        '"qlib-dashboard/tsconfig*.json"',
    )
    for path in (
        Path(".github/workflows/formal-backtest-refresh.yml"),
        Path(".github/workflows/formal-backtest-refresh-ci.yml"),
    ):
        workflow = path.read_text(encoding="utf-8")
        for trigger in required:
            assert trigger in workflow
    live = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    preflight_start = live.index(
        "      - name: Validate refresh implementation before network work"
    )
    clock_start = live.index("      - name: Resolve transaction timestamp")
    assert "npm run check:account" in live[preflight_start:clock_start]


def test_reviewed_refresh_dispatches_exact_merge_to_pages_before_current_status() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    release_start = workflow.index(
        "      - name: Wait for candidate checks, merge reviewed refresh, and verify Pages"
    )
    status_start = workflow.index("      - name: Upsert refresh operating status")
    release = workflow[release_start:status_start]

    assert 'CANDIDATE_SHA: ${{ steps.pull_request.outputs.candidate_sha }}' in release
    assert "gh workflow run formal-backtest-refresh-ci.yml" in release
    assert '--ref "$REFRESH_BRANCH"' in release
    assert '-f "candidate_sha=${CANDIDATE_SHA}"' in release
    assert 'gh run watch "$validation_run"' in release
    assert 'test "$validation_conclusion" = "success"' in release
    assert 'current_main="$(gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main"' in release
    assert 'test "$current_main" = "$merge_sha"' in release
    assert "actions/workflows/deploy-pages.yml/dispatches" in release
    assert "X-GitHub-Api-Version: 2026-03-10" in release
    assert "inputs:{target_sha:$target_sha}" in release
    assert ".workflow_run_id // empty" in release
    assert 'gh run watch "$pages_run"' in release
    assert 'test "$pages_conclusion" = "success"' in release
    assert "pages_run_id=$pages_run" in release
    assert release_start < status_start

    status = workflow[status_start:]
    assert "PAGES_RUN_ID: ${{ steps.release.outputs.pages_run_id }}" in status
    assert "Pages live acceptance: required before current/closed status" in status


def test_formal_refresh_contract_can_validate_an_exact_dispatched_candidate() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh-ci.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in workflow
    assert "candidate_sha:" in workflow
    assert "pr_number:" in workflow
    assert "ref: ${{ inputs.candidate_sha || github.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"' in workflow
    assert "git diff --name-only origin/main...HEAD" in workflow


def test_manual_pages_release_checks_out_and_verifies_target_sha() -> None:
    workflow = Path(".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "target_sha:" in workflow
    assert "RELEASE_SHA: ${{ inputs.target_sha || github.sha }}" in workflow
    assert workflow.count("ref: ${{ inputs.target_sha || github.sha }}") == 2
    assert 'test "$(git rev-parse HEAD)" = "$RELEASE_SHA"' in workflow
    assert '"commit_sha": os.environ["RELEASE_SHA"]' in workflow
    assert '--expected-commit "$RELEASE_SHA"' in workflow
