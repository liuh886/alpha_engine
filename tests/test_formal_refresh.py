from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

import src.artifacts.formal_refresh as formal_refresh
from scripts.data.refresh_selected_pool_prices_v2 import (
    _decorate_manifest,
    build_hardened_router,
)
from scripts.run_formal_refresh_transaction import (
    _latest_ledger_signal_date,
    _ranker_refresh_requirements,
    build_task_plan,
    finalize_refresh,
)
from src.artifacts.formal_provider_cache import build_provider_cache_contract
from src.artifacts.formal_bundle_reader import FormalBundleReader
from src.artifacts.formal_refresh import (
    FormalRefreshError,
    load_object,
    market_provider_cutoff,
    write_object,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import (
    RANKER_FORMAL_REFRESH_ADAPTERS,
    load_active_strategy_runtime_capabilities,
)

FORMAL_V2 = Path("data/research/formal_model_runs")


def test_legacy_single_file_refresh_runtime_is_not_exported() -> None:
    retired = {
        "FormalModelRecord",
        "FormalRefreshPlan",
        "accepted_records",
        "build_plan",
        "verify_append_only_package",
        "finalize_candidate_tree",
    }
    assert retired.isdisjoint(vars(formal_refresh))


def _provider_manifest(path: Path, *, market: str, cutoff: str) -> Path:
    clock = "QQQ" if market == "us" else "000300"
    write_object(
        path,
        {
            "market": market,
            "status": "selected_pool_price_refresh_ready",
            "promotion_eligible": True,
            "records": [
                {"symbol": clock, "last_date": cutoff},
                {"symbol": "AAA", "last_date": cutoff},
            ],
            "research_only": True,
            "trade_ready": False,
        },
    )
    return path


def _non_regressing_cutoffs() -> dict[str, str]:
    active = load_active_strategy_catalog()
    freshness = load_object(FORMAL_V2 / "freshness.json")
    cutoffs = {str(key): str(value) for key, value in freshness["markets"].items()}
    formal = load_object(FORMAL_V2 / "catalog.json")
    for record in formal["records"]:
        model_id = str(record["model_version_id"])
        strategy = active.by_model_version_id.get(model_id)
        if strategy is None:
            continue
        market = strategy.market
        cutoffs[market] = max(cutoffs[market], str(record["evidence_cutoff"]))
    capabilities = load_active_strategy_runtime_capabilities(active=active)
    for strategy in active.strategies:
        if (
            capabilities[strategy.strategy_id].formal_refresh.adapter_id
            not in RANKER_FORMAL_REFRESH_ADAPTERS
        ):
            continue
        cutoffs[strategy.market] = max(
            cutoffs[strategy.market],
            _latest_ledger_signal_date(
                Path(strategy.signal_ledger).parent,
                strategy.model_version_id,
            ),
        )
    return cutoffs


def test_market_provider_cutoff_uses_governed_benchmark_clock() -> None:
    manifest = {
        "market": "us",
        "status": "selected_pool_price_refresh_ready",
        "promotion_eligible": True,
        "records": [
            {"symbol": "QQQ", "last_date": "2026-08-05"},
            {"symbol": "EA", "last_date": "2026-08-04"},
        ],
        "research_only": True,
        "trade_ready": False,
    }
    assert market_provider_cutoff(manifest, market="us") == "2026-08-05"


def test_market_provider_cutoff_requires_market_clock() -> None:
    manifest = {
        "market": "us",
        "status": "selected_pool_price_refresh_ready",
        "promotion_eligible": True,
        "records": [{"symbol": "EA", "last_date": "2026-08-05"}],
        "research_only": True,
        "trade_ready": False,
    }
    with pytest.raises(FormalRefreshError, match="market clock QQQ"):
        market_provider_cutoff(manifest, market="us")


def test_market_provider_cutoff_rejects_ineligible_provider() -> None:
    manifest = {
        "market": "us",
        "status": "selected_pool_price_refresh_ready",
        "promotion_eligible": False,
        "records": [{"symbol": "QQQ", "last_date": "2026-08-05"}],
        "research_only": True,
        "trade_ready": False,
    }
    with pytest.raises(FormalRefreshError, match="not promotion eligible"):
        market_provider_cutoff(manifest, market="us")


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
                        {"provider": "tencent_qfq_history", "ok": False},
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


def test_plan_is_formal_v2_catalog_driven() -> None:
    plan = build_task_plan(
        formal_v2_root=FORMAL_V2,
        cutoffs=_non_regressing_cutoffs(),
        generated_at="2026-08-13T10:30:00Z",
    )
    active = load_active_strategy_catalog()
    assert plan["schema_version"] == "formal_refresh_plan_v5"
    assert plan["active_model_version_ids"] == list(active.active_model_version_ids)
    assert {task["publication_input"] for task in plan["tasks"]} == {"native_bundle_v2"}
    assert "governed_evidence_model_ids" not in plan
    cn = next(task for task in plan["tasks"] if task["strategy_id"] == "cn_x")
    assert cn["formal_refresh_capability_status"] == "available"
    assert cn["formal_refresh_adapter_id"] == "cn_x1_2_formal_refresh_v1"
    assert cn["formal_refresh_block_reason"] is None
    assert plan["blocked_model_ids"] == []
    expected_execution = [
        task
        for task in plan["tasks"]
        if task["formal_refresh_required"] or task["mtm_refresh_required"]
    ]
    assert plan["execution_task_matrix"] == expected_execution
    assert set(plan["planned_noop_strategy_ids"]) == {
        task["strategy_id"] for task in plan["tasks"] if task not in expected_execution
    }


def test_plan_never_rewinds_accepted_model_evidence() -> None:
    cutoffs = _non_regressing_cutoffs()
    cutoffs["us"] = "2026-08-10"
    plan = build_task_plan(
        formal_v2_root=FORMAL_V2,
        cutoffs=cutoffs,
        generated_at="2026-08-13T10:30:00Z",
    )
    us = next(task for task in plan["tasks"] if task["model_version_id"] == "us_x1_3")
    assert us["planned_provider_cutoff"] >= "2026-08-12"


def test_ranker_daily_cutoff_uses_mtm_without_settled_rebuild() -> None:
    performance = {
        "report": [
            {
                "date": "2026-07-16",
                "holding_end_date": "2026-07-30",
                "account": 1.1,
            }
        ]
    }
    settled, mtm = _ranker_refresh_requirements(
        model_id="us_x1_3",
        target="2026-08-07",
        formal_signal_date="2026-07-30",
        ledger_signal_date="2026-07-30",
        performance=performance,
    )
    assert settled is False
    assert mtm is True


def test_ranker_ledger_advance_is_the_settled_rebuild_trigger() -> None:
    performance = {
        "report": [
            {
                "date": "2026-07-16",
                "holding_end_date": "2026-07-30",
                "account": 1.1,
            }
        ]
    }
    settled, mtm = _ranker_refresh_requirements(
        model_id="us_x1_3",
        target="2026-08-13",
        formal_signal_date="2026-07-30",
        ledger_signal_date="2026-08-13",
        performance=performance,
    )
    assert settled is True
    assert mtm is False


def test_future_cutoff_still_marks_non_rankers_stale() -> None:
    cutoffs = {
        market: (date.fromisoformat(cutoff) + timedelta(days=1)).isoformat()
        for market, cutoff in _non_regressing_cutoffs().items()
    }
    plan = build_task_plan(
        formal_v2_root=FORMAL_V2,
        cutoffs=cutoffs,
        generated_at="2026-08-13T10:30:00Z",
    )
    assert {
        "qqqi_qqq_tqqq_v4_3",
        "byd_v1_3_recovery_event_low_vol_confirmation_v1",
    }.issubset(set(plan["stale_model_ids"]))


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
            "retained_strategy_ids": [],
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
    assert freshness["cutoff_policy"] == "governed_benchmark_market_session"
    assert freshness["required_models"] == list(
        load_active_strategy_catalog().active_model_version_ids
    )


def test_finalize_marks_retained_strategy_candidate_as_degraded(tmp_path: Path) -> None:
    us = _provider_manifest(tmp_path / "us.json", market="us", cutoff="2026-08-10")
    cn = _provider_manifest(tmp_path / "cn.json", market="cn", cutoff="2026-08-12")
    fan_in = tmp_path / "fan-in.json"
    write_object(
        fan_in,
        {
            "schema_version": "formal_strategy_fan_in_v2",
            "status": "degraded",
            "publication_contract": "active_preview_bundle_v2",
            "expected_strategy_ids": [
                row.strategy_id for row in load_active_strategy_catalog().strategies
            ],
            "preview_catalog_sha256": "a" * 64,
            "retained_strategy_ids": ["us_x"],
            "research_only": True,
            "trade_ready": False,
        },
    )

    receipt = finalize_refresh(
        us_provider_manifest=us,
        cn_provider_manifest=cn,
        generated_at="2026-08-13T10:30:00Z",
        fan_in_receipt=fan_in,
        freshness_output=tmp_path / "freshness.json",
        receipt_path=tmp_path / "receipt.json",
    )

    assert receipt["status"] == "candidate_ready_with_retained"
    assert receipt["retained_strategy_ids"] == ["us_x"]


def test_formal_refresh_parallelizes_and_seals_provider_builds() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    assert "providers:\n    needs: prepare" in workflow
    assert "market: [us, cn]" in workflow
    assert "uses: actions/cache/restore@v6" in workflow
    assert "uses: actions/cache/save@v6" in workflow
    assert workflow.count("uses: actions/cache/restore@v6") == 4
    assert workflow.count("uses: actions/cache/save@v6") == 2
    assert workflow.count("uses: actions/cache/") == 6
    assert "uses: actions/cache/restore@v4" not in workflow
    assert "uses: actions/cache/save@v4" not in workflow
    assert "uses: actions/cache/restore@v5" not in workflow
    assert "uses: actions/cache/save@v5" not in workflow
    assert "formal-provider-${{ matrix.market }}-${{ github.run_id }}" in workflow


def test_formal_prepare_job_checkout_only_preflight_inputs() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    prepare_start = workflow.index("\n  prepare:\n")
    providers_start = workflow.index("\n  providers:\n", prepare_start)
    prepare = workflow[prepare_start:providers_start]
    checkout_start = prepare.index("      - name: Check out triggering revision")
    checkout_end = prepare.index("      - name: Verify execution identity", checkout_start)
    checkout = prepare[checkout_start:checkout_end]

    assert "fetch-depth: 1" in checkout
    assert "lfs: true" in checkout
    assert "sparse-checkout-cone-mode: true" in checkout
    assert (
        "sparse-checkout: |\n"
        "            .github\n"
        "            configs\n"
        "            data/csv_clean\n"
        "            data/research/formal_model_runs\n"
        "            data/research/model_runs\n"
        "            data/research/model_data_bundle_v1\n"
        "            data/research/strategy_signal_ledgers\n"
        "            data/research/runs\n"
        "            data/research/historical_model_evidence\n"
        "            data/research/byd_prospective_shadow\n"
        "            data/research/byd_515180_prospective\n"
        "            data/research/cn_x1_1_regime_gated_candidate_v1\n"
        "            docs\n"
        "            qlib-dashboard\n"
        "            scripts\n"
        "            src\n"
        "            supabase\n"
        "            tests\n"
    ) in checkout
    assert "fetch-depth: 0" not in checkout
    assert "filter:" not in checkout
    assert "            data/research\n" not in checkout
    assert "            data/research/market_evidence\n" not in checkout

    active = load_active_strategy_catalog()
    for strategy in active.strategies:
        assert Path(strategy.model_contract).is_file()
        assert Path(strategy.signal_ledger).is_dir()

    reader = FormalBundleReader.open(Path("."), relative_root=FORMAL_V2)
    for model_version_id in reader.records:
        reader.load(model_version_id)

    research_catalog = json.loads(
        Path("data/research/catalog.json").read_text(encoding="utf-8")
    )
    for entry in research_catalog["published_models"]:
        source = Path(entry["source"])
        assert source.is_file()
        assert source.as_posix().startswith("configs/")
    for entry in research_catalog["published_runs"]:
        source = Path(entry["source"])
        assert source.is_dir()
        assert source.as_posix().startswith("data/research/runs/")


def test_formal_prepare_skips_unused_frontend_dependency_install() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    prepare_start = workflow.index("\n  prepare:\n")
    providers_start = workflow.index("\n  providers:\n", prepare_start)
    prepare = workflow[prepare_start:providers_start]

    setup_node_start = prepare.index("      - uses: actions/setup-node@v6")
    install_start = prepare.index(
        "      - name: Install locked Python preflight environment",
        setup_node_start,
    )
    setup_node = prepare[setup_node_start:install_start]
    validate_start = prepare.index(
        "      - name: Validate refresh implementation before network work",
        install_start,
    )
    install = prepare[install_start:validate_start]
    validate_end = prepare.index(
        "      - name: Resolve immutable workflow start",
        validate_start,
    )
    validate = prepare[validate_start:validate_end]

    assert "node-version: 22" in setup_node
    assert "cache:" not in setup_node
    assert "cache-dependency-path:" not in setup_node
    assert "uv sync --frozen --extra dev" in install
    assert "npm ci" not in install
    assert "npm run check:account" in validate
    assert "uv run ruff check" in validate
    assert "uv run mypy" in validate
    assert "uv run pytest" in validate


def test_formal_provider_jobs_checkout_only_provider_build_inputs() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    providers_start = workflow.index("\n  providers:\n")
    plan_start = workflow.index("\n  plan:\n", providers_start)
    providers = workflow[providers_start:plan_start]
    checkout_start = providers.index("      - name: Check out triggering revision")
    checkout_end = providers.index("      - uses: actions/setup-python@v6", checkout_start)
    checkout = providers[checkout_start:checkout_end]

    assert "fetch-depth: 1" in checkout
    assert "lfs: false" in checkout
    assert "sparse-checkout-cone-mode: true" in checkout
    assert (
        "sparse-checkout: |\n"
        "            configs\n"
        "            data/csv_clean\n"
        "            scripts\n"
        "            src\n"
    ) in checkout
    assert "fetch-depth: 0" not in checkout
    assert "lfs: true" not in checkout
    assert "filter:" not in checkout

    allowed_directories = ("configs/", "scripts/", "src/")
    for market in ("us", "cn"):
        contract = build_provider_cache_contract(
            repository_root=Path("."),
            market=market,
            start="2021-01-01",
            requested_cutoff="2026-08-21",
        )
        assert all(
            "/" not in path or path.startswith(allowed_directories)
            for path in contract["inputs"]
        ), f"{market} provider contract escaped its sparse checkout closure"


def test_formal_plan_job_checkout_only_plan_inputs() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    plan_start = workflow.index("\n  plan:\n")
    strategy_start = workflow.index("\n  strategy:\n", plan_start)
    plan = workflow[plan_start:strategy_start]
    checkout_start = plan.index("      - name: Check out triggering revision")
    checkout_end = plan.index("      - name: Download verified US provider", checkout_start)
    checkout = plan[checkout_start:checkout_end]

    assert "fetch-depth: 1" in checkout
    assert "lfs: false" in checkout
    assert "sparse-checkout-cone-mode: true" in checkout
    assert (
        "sparse-checkout: |\n"
        "            configs\n"
        "            data/research/formal_model_runs\n"
        "            data/research/strategy_signal_ledgers\n"
        "            scripts\n"
        "            src\n"
    ) in checkout
    assert "fetch-depth: 0" not in checkout
    assert "lfs: true" not in checkout
    assert "filter:" not in checkout

    active = load_active_strategy_catalog()
    for strategy in active.strategies:
        assert strategy.model_contract.startswith("configs/")
        assert Path(strategy.model_contract).is_file()
        assert strategy.signal_ledger.startswith("data/research/strategy_signal_ledgers/")
        assert Path(strategy.signal_ledger).is_dir()

    reader = FormalBundleReader.open(Path("."), relative_root=FORMAL_V2)
    for model_version_id in reader.records:
        reader.load(model_version_id)


def test_formal_refresh_is_bundle_v2_only() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
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
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    assert "plan:\n    needs: [prepare, providers]" in workflow
    assert "strategy:\n    needs: [prepare, plan]" in workflow
    assert "task: ${{ fromJson(needs.plan.outputs.task_matrix) }}" in workflow
    assert "if: needs.plan.outputs.refresh_required == 'true'" in workflow
    assert workflow.count("fail-fast: false") >= 2
    assert "uv run python scripts/run_formal_strategy_refresh.py" in workflow
    assert "pattern: formal-strategy-*-${{ github.run_id }}" in workflow
    download_start = workflow.index("      - name: Download all strategy results")
    download_end = workflow.index("      - name: Atomically fan in", download_start)
    assert (
        "if: needs.plan.outputs.refresh_required == 'true'"
        in workflow[download_start:download_end]
    )
    assert "run_formal_refresh_transaction.py assemble" in workflow
    assert '--candidate-preview-root "$CANDIDATE_PREVIEW_ROOT"' in workflow
    assert '--native-root "$CANDIDATE_PREVIEW_ROOT"' in workflow


def test_formal_refresh_yaml_contains_no_model_execution_recipe() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    strategy_start = workflow.index("\n  strategy:\n")
    publish_start = workflow.index("\n  publish:\n", strategy_start)
    strategy_block = workflow[strategy_start:publish_start]
    assert "scripts/refresh_qqq_v4_3_formal.py" not in strategy_block
    assert "scripts/refresh_ranker_formal.py cn" not in strategy_block
    assert "scripts/refresh_byd_v1_3_formal.py" not in strategy_block
    assert "scripts/run_formal_strategy_refresh.py" in strategy_block


def test_strategy_results_are_uploaded_after_failure_unless_cancelled() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    start = workflow.index("      - name: Upload bounded strategy receipt and evidence")
    end = workflow.index("\n\n  publish:", start)
    block = workflow[start:end]
    assert "if: ${{ !cancelled() }}" in block
    transaction = Path("scripts/run_formal_refresh_transaction.py").read_text(encoding="utf-8")
    assert 'FATAL_STATES = {"execution_failed"}' in transaction
    assert '"retained_strategy_ids"' in transaction


def test_run_scoped_artifacts_are_overwritable_for_failed_job_reruns() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    upload_contracts = (
        ("Transfer verified provider", 7),
        ("Upload failed provider diagnostics", 7),
        ("Upload immutable plan", 7),
        ("Upload bounded strategy receipt and evidence", 30),
        ("Upload bounded refresh evidence", 30),
    )
    assert workflow.count("uses: actions/upload-artifact@v6") == len(upload_contracts)
    assert "github.run_attempt" not in workflow
    for index, (name, retention_days) in enumerate(upload_contracts):
        start = workflow.index(f"      - name: {name}")
        next_start = workflow.find("\n      - name:", start + 1)
        block = workflow[start : next_start if next_start >= 0 else None]
        assert "uses: actions/upload-artifact@v6" in block, (index, name)
        assert "github.run_id" in block, (index, name)
        assert "overwrite: true" in block, (index, name)
        assert f"retention-days: {retention_days}" in block, (index, name)


def test_failed_provider_diagnostics_preserve_manifest_without_relaxing_gate() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Upload failed provider diagnostics")
    next_start = workflow.find("\n      - name:", start + 1)
    block = workflow[start : next_start if next_start >= 0 else None]

    assert "if: ${{ failure() }}" in block
    assert "selected_pool_price_refresh_manifest.json" in block
    assert "provider-${{ matrix.market }}-contract.json" in block
    assert "formal-provider-${{ matrix.market }}-${{ github.run_id }}" not in block


def test_publish_initial_checkout_excludes_cacheable_market_evidence() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    publish = workflow[workflow.index("\n  publish:\n") :]
    checkout_start = publish.index("      - name: Check out triggering revision")
    checkout_end = publish.index(
        "      - name: Resolve current Market Evidence tree",
        checkout_start,
    )
    checkout = publish[checkout_start:checkout_end]

    assert "fetch-depth: 1" in checkout
    assert "lfs: false" in checkout
    assert "sparse-checkout-cone-mode: true" in checkout
    assert (
        "sparse-checkout: |\n"
        "            configs\n"
        "            data/research/formal_model_runs\n"
        "            data/research/model_runs\n"
        "            data/research/model_data_bundle_v1\n"
        "            scripts\n"
        "            src\n"
    ) in checkout
    assert "fetch-depth: 0" not in checkout
    assert "lfs: true" not in checkout
    assert "filter:" not in checkout
    assert "data/research/market_evidence" not in checkout


def test_publish_market_evidence_cache_is_exact_and_fallback_safe() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    publish = workflow[workflow.index("\n  publish:\n") :]
    checkout = publish.index("      - name: Check out triggering revision")
    resolve = publish.index("      - name: Resolve current Market Evidence tree")
    restore = publish.index("      - name: Restore exact Market Evidence tree")
    verify = publish.index(
        "      - name: Materialize and verify current Market Evidence tree"
    )
    build = publish.index("      - name: Build shared governed Market Evidence")
    delta = publish.index("      - name: Classify canonical publication delta")
    save = publish.index("      - name: Save verified Market Evidence tree")
    hydrate = publish.index("      - name: Hydrate complete reviewed revision")
    assert checkout < resolve < restore < verify < build < delta < save < hydrate

    resolve_block = publish[resolve:restore]
    assert '${GITHUB_SHA}:data/research/market_evidence' in resolve_block
    assert 'git cat-file -t "$tree"' in resolve_block
    assert 'echo "oid=$tree" >> "$GITHUB_OUTPUT"' in resolve_block

    restore_block = publish[restore:verify]
    assert "continue-on-error: true" in restore_block
    assert "uses: actions/cache/restore@v6" in restore_block
    assert "restore-keys:" not in restore_block
    assert "formal-market-evidence-v1-${{ runner.os }}-" in restore_block
    assert "steps.market_evidence_tree.outputs.oid" in restore_block

    verify_block = publish[verify:publish.index("      - name: Download verified US provider")]
    for token in (
        'CACHE_HIT: ${{ steps.market_evidence_cache.outputs.cache-hit }}',
        'EXPECTED_TREE: ${{ steps.market_evidence_tree.outputs.oid }}',
        'GIT_INDEX_FILE="$index_path" git read-tree --empty',
        "git add -f --sparse --",
        'GIT_INDEX_FILE="$index_path" git write-tree',
        '${root_tree}:data/research/market_evidence',
        'test "$actual_tree" = "$EXPECTED_TREE"',
        'rm -rf data/research/market_evidence',
        "git sparse-checkout add data/research/market_evidence",
        "if [ \"$CACHE_HIT\" != \"true\" ] || ! verify_tree",
        'echo "source=$source" >> "$GITHUB_OUTPUT"',
    ):
        assert token in verify_block

    save_block = publish[save:hydrate]
    assert "success() && steps.market_evidence.outputs.source == 'git'" in save_block
    assert "continue-on-error: true" in save_block
    assert "uses: actions/cache/save@v6" in save_block
    assert "restore-keys:" not in save_block
    assert "steps.market_evidence_tree.outputs.oid" in save_block

def test_publish_hydrates_complete_revision_before_candidate_publication() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    publish = workflow[workflow.index("\n  publish:\n") :]
    delta = publish.index("      - name: Classify canonical publication delta")
    hydrate = publish.index("      - name: Hydrate complete reviewed revision")
    candidate_install = publish.index(
        "      - name: Install complete candidate and materialize read models"
    )
    setup_node = publish.index("      - uses: actions/setup-node@v6")
    validate = publish.index("      - name: Validate complete candidate publication")
    pull_request = publish.index("      - name: Open or update reviewed refresh PR")

    assert delta < hydrate < candidate_install < setup_node < validate < pull_request
    hydrate_end = publish.index("\n      - name:", hydrate + 1)
    block = publish[hydrate:hydrate_end]
    assert "if: steps.delta.outputs.publication_required == 'true'" in block
    assert "git fetch --unshallow --no-tags origin" in block
    assert "git fetch --no-tags origin" in block
    assert "+refs/heads/main:refs/remotes/origin/main" in block
    assert "git lfs install --local" in block
    assert "git sparse-checkout disable" in block
    assert "git lfs pull" in block
    assert (
        block.index("git lfs install --local")
        < block.index("git sparse-checkout disable")
        < block.index("git lfs pull")
    )
    assert 'test "$(git rev-parse --is-shallow-repository)" = "false"' in block
    assert 'git config --bool core.sparseCheckout || true' in block
    assert 'test -n "$(git merge-base HEAD origin/main)"' in block


def test_publish_validates_upstream_artifacts_before_installing_environments() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    publish_start = workflow.index("\n  publish:\n")
    publish = workflow[publish_start:]
    checkout = publish.index("      - name: Check out triggering revision")
    downloads = tuple(
        publish.index(f"      - name: {name}")
        for name in (
            "Download verified US provider",
            "Download verified CN provider",
            "Download immutable plan",
            "Download all strategy results",
        )
    )
    setup_python = publish.index("      - uses: actions/setup-python@v6")
    install = publish.index("      - name: Install locked publication Python environment")
    delta = publish.index("      - name: Classify canonical publication delta")
    hydrate = publish.index("      - name: Hydrate complete reviewed revision")
    setup_node = publish.index("      - uses: actions/setup-node@v6")
    frontend_install = publish.index(
        "      - name: Install locked frontend publication environment"
    )
    assert checkout < min(downloads)
    assert max(downloads) < setup_python < install
    assert install < delta < hydrate < setup_node < frontend_install


def test_semantic_no_change_skips_candidate_mutation_and_release() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    publish = workflow[workflow.index("\n  publish:\n") :]
    model_bundle = publish.index("      - name: Build shared Model Data Bundle")
    delta = publish.index("      - name: Classify canonical publication delta")
    install = publish.index(
        "      - name: Install complete candidate and materialize read models"
    )
    assert model_bundle < delta < install
    delta_block = publish[delta:install]
    assert "run_formal_refresh_transaction.py publication-delta" in delta_block
    assert "artifacts/formal-refresh/publication-delta-receipt.json" in delta_block
    for root in (
        "data/research/formal_model_runs",
        '"$CANDIDATE_V2_ROOT"',
        "data/research/model_runs",
        '"$CANDIDATE_PREVIEW_ROOT"',
        "data/research/market_evidence",
        '"$CANDIDATE_MARKET_EVIDENCE_ROOT"',
        "data/research/model_data_bundle_v1",
        '"$CANDIDATE_MODEL_DATA_ROOT"',
    ):
        assert root in delta_block

    gated_steps = (
        "Install complete candidate and materialize read models",
        "Install locked frontend publication environment",
        "Validate complete candidate publication",
        "Open or update reviewed refresh PR",
    )
    for name in gated_steps:
        start = publish.index(f"      - name: {name}")
        end = publish.find("\n      - name:", start + 1)
        block = publish[start : end if end >= 0 else None]
        assert "if: steps.delta.outputs.publication_required == 'true'" in block
    setup_node = publish.index("      - uses: actions/setup-node@v6")
    setup_node_end = publish.index("      - name: Install locked frontend", setup_node)
    assert (
        "if: steps.delta.outputs.publication_required == 'true'"
        in publish[setup_node:setup_node_end]
    )
    assert (
        "PUBLICATION_REQUIRED: "
        "${{ steps.effective_delta.outputs.publication_required }}" in publish
    )
    assert (
        "PUBLICATION_DELTA_STATUS: ${{ steps.effective_delta.outputs.status }}"
        in publish
    )
    assert "semantic_no_change" in publish


def test_publish_reconciles_candidate_against_latest_main_before_pr() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    publish = workflow[workflow.index("\n  publish:\n") :]
    pull_request = publish.index("      - name: Open or update reviewed refresh PR")
    effective = publish.index("      - name: Resolve effective publication delta")
    release = publish.index(
        "      - name: Wait for candidate checks, merge reviewed refresh, and verify Pages"
    )
    block = publish[pull_request:effective]

    assert pull_request < effective < release
    assert "git fetch origin main" in block
    assert "git reset --hard origin/main" in block
    assert 'git checkout -B "$REFRESH_BRANCH" origin/main' in block
    assert "publication-delta-latest-main-receipt.json" in block
    assert block.count("run_formal_refresh_transaction.py publication-delta") == 1
    assert 'if [ "$latest_publication_required" != "true" ]' in block
    assert 'test "$latest_delta_status" = "semantic_no_change"' in block
    assert 'echo "pr_number=" >> "$GITHUB_OUTPUT"' in block
    assert 'echo "candidate_sha=" >> "$GITHUB_OUTPUT"' in block
    assert 'test "$latest_delta_status" = "publication_required"' in block
    assert (
        "Latest-main delta requires publication but no canonical evidence bytes changed."
        in block
    )
    assert "git merge --no-edit origin/main" not in block
    assert block.index("git reset --hard origin/main") < block.index(
        'cp -a "$CANDIDATE_V2_ROOT" data/research/formal_model_runs'
    )

    effective_block = publish[effective:release]
    assert "LATEST_PUBLICATION_REQUIRED" in effective_block
    assert "LATEST_DELTA_STATUS" in effective_block
    assert 'LATEST_PUBLICATION_REQUIRED:-$INITIAL_PUBLICATION_REQUIRED' in effective_block
    assert 'LATEST_DELTA_STATUS:-$INITIAL_DELTA_STATUS' in effective_block
    assert 'echo "publication_required=$publication_required"' in effective_block
    assert 'echo "status=$delta_status"' in effective_block
    assert "publication-delta-latest-main-receipt.json" in publish


def test_publish_status_uses_the_transaction_outcome() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "id: transaction" in workflow
    assert "outcome=\"$(jq -er '.status' \"$REFRESH_RECEIPT\")\"" in workflow
    assert 'test "$outcome" = "candidate_ready_for_review"' in workflow
    assert 'echo "outcome=$outcome" >> "$GITHUB_OUTPUT"' in workflow
    assert '\\"$REFRESH_RECEIPT\\"' not in workflow
    assert "TRANSACTION_STATUS: ${{ steps.transaction.outputs.outcome }}" in workflow
    assert (
        "process.env.TRANSACTION_STATUS !== 'candidate_ready_for_review'" in workflow
    )


def test_cn_x1_2_duplicate_evidence_lives_in_maintained_adapter() -> None:
    runner = Path("scripts/run_formal_strategy_refresh.py").read_text(encoding="utf-8")
    assert "def _build_cn_x1_2_duplicate_ledgers(" in runner
    assert 'for suffix in ("a", "b")' in runner
    assert "scripts/build_cn_x1_2_prospective_ledger.py" in runner
    assert "--ledger-a" in runner
    assert "--ledger-b" in runner


def test_market_evidence_is_content_addressed_and_parallel() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    start = workflow.index("      - name: Build shared governed Market Evidence")
    end = workflow.index("      - name: Build shared Model Data Bundle")
    block = workflow[start:end]
    assert block.count("--reuse-root data/research/market_evidence") == 2
    assert 'us_pid="$!"' in block
    assert 'cn_pid="$!"' in block
    assert 'wait "$us_pid" || status=1' in block
    assert 'wait "$cn_pid" || status=1' in block


def test_formal_refresh_publishes_one_shared_model_data_bundle() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    assert workflow.count("scripts/data/build_model_data_bundle.py") == 1
    assert "data/research/model_data_bundle_v1" in workflow
    assert "cancel-in-progress: false" in workflow


def test_model_data_consumes_publication_identity_and_retains_raw_diagnostics() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Build shared Model Data Bundle")
    end = workflow.index("      - name: Classify canonical publication delta")
    block = workflow[start:end]
    assert block.count("selected_pool_price_publication_manifest.json") == 2
    assert "selected_pool_price_refresh_manifest.json" not in block
    assert "provider-us/artifacts/selected_pool_price_refresh_manifest.json" in workflow
    assert "provider-cn/artifacts/selected_pool_price_refresh_manifest.json" in workflow


def test_model_data_fetches_only_review_bound_cross_run_sources() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("      - name: Build shared Model Data Bundle")
    end = workflow.index("      - name: Classify canonical publication delta")
    block = workflow[start:end]

    assert "scripts/data/fetch_governed_model_data.py" in block
    assert "cn_alpha158_2026_08_31" in block
    assert "cn_events_2026_08_31" in block
    assert "GITHUB_TOKEN: ${{ github.token }}" in block
    assert "latest successful" not in block.lower()
    assert "gh run download" not in block
    assert "factors.qlib_alpha158.panel.cn.v1:factor_panel" in block
    assert "fundamentals.cn_selected_equities_v3:fundamental_coverage" in block
    assert "corporate_actions.cn_selected_equities_v3:corporate_action_coverage" in block
    assert block.count("governed-source-receipt.json") == 1
    assert "--source-receipt" in block
