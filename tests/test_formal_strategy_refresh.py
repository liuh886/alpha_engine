from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts.run_formal_refresh_transaction import assemble_strategy_results
from scripts.run_formal_strategy_refresh import RECEIPT_SCHEMA
from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.governance.active_strategy_catalog import load_active_strategy_catalog

SOURCE = Path("data/research/formal_backtests")
NATIVE = Path("data/research/model_runs")
STRATEGIES = Path("configs/strategies/registry.json")


def _tasks() -> list[dict[str, object]]:
    active = load_active_strategy_catalog(STRATEGIES)
    return [
        {
            "strategy_id": strategy.strategy_id,
            "model_family_id": strategy.model_family_id,
            "model_version_id": strategy.model_version_id,
            "model_kind": strategy.model_kind,
            "market": strategy.market,
            "planned_provider_cutoff": "2026-08-12",
            "publication_input": (
                "native_bundle_v2"
                if strategy.model_version_id == "us_x1_3"
                else "governed_model_evidence"
            ),
            "formal_refresh_required": False,
            "mtm_refresh_required": False,
        }
        for strategy in active.strategies
    ]


def _receipt(task: dict[str, object], status: str) -> dict[str, object]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        **task,
        "execution_status": status,
        "research_only": True,
        "trade_ready": False,
    }


def _write_plan(path: Path, tasks: list[dict[str, object]]) -> None:
    write_object(
        path,
        {
            "schema_version": "formal_refresh_plan_v2",
            "generated_at": "2026-08-13T00:00:00Z",
            "tasks": tasks,
            "research_only": True,
            "trade_ready": False,
        },
    )


def _seed_current(tmp_path: Path) -> tuple[Path, Path]:
    current_formal = tmp_path / "current-formal"
    current_preview = tmp_path / "current-preview"
    shutil.copytree(SOURCE, current_formal)
    shutil.copytree(NATIVE, current_preview)
    return current_formal, current_preview


def _seed_results(root: Path, tasks: list[dict[str, object]], *, status: str) -> None:
    for task in tasks:
        result = root / str(task["strategy_id"])
        result.mkdir(parents=True)
        write_object(result / "receipt.json", _receipt(task, status))


def test_fan_in_accepts_complete_active_strategy_set(tmp_path: Path) -> None:
    tasks = _tasks()
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")
    current_formal, current_preview = _seed_current(tmp_path)
    candidate_preview = tmp_path / "candidate-preview"
    fan_in_path = tmp_path / "fan-in.json"

    fan_in = assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=results,
        current_root=current_formal,
        candidate_root=tmp_path / "candidate-formal",
        current_preview_root=current_preview,
        candidate_preview_root=candidate_preview,
        receipt_path=fan_in_path,
    )

    active = load_active_strategy_catalog(STRATEGIES)
    assert fan_in["status"] == "complete"
    assert fan_in["publication_contract"] == "active_preview_bundle_v2"
    assert fan_in["expected_strategy_ids"] == [row.strategy_id for row in active.strategies]
    assert fan_in["changed_strategy_ids"] == []
    assert sha256(candidate_preview / "catalog.json") == fan_in["preview_catalog_sha256"]

    catalog = load_object(candidate_preview / "catalog.json")
    validate_catalog(catalog)
    assert {row["model_version_id"] for row in catalog["records"]} == set(
        active.active_model_version_ids
    )
    assert load_object(fan_in_path)["publication_contract"] == "active_preview_bundle_v2"


def test_fan_in_fails_closed_on_missing_strategy_receipt(tmp_path: Path) -> None:
    tasks = _tasks()
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks[:-1], status="current_no_change")
    current_formal, current_preview = _seed_current(tmp_path)

    with pytest.raises(FormalRefreshError, match="membership mismatch"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=results,
            current_root=current_formal,
            candidate_root=tmp_path / "candidate-formal",
            current_preview_root=current_preview,
            candidate_preview_root=tmp_path / "candidate-preview",
            receipt_path=tmp_path / "fan-in.json",
        )


def test_fan_in_fails_closed_on_blocked_strategy(tmp_path: Path) -> None:
    tasks = _tasks()
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")
    blocked = results / str(tasks[0]["strategy_id"]) / "receipt.json"
    write_object(blocked, _receipt(tasks[0], "invalid_evidence"))
    current_formal, current_preview = _seed_current(tmp_path)

    with pytest.raises(FormalRefreshError, match="not publishable"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=results,
            current_root=current_formal,
            candidate_root=tmp_path / "candidate-formal",
            current_preview_root=current_preview,
            candidate_preview_root=tmp_path / "candidate-preview",
            receipt_path=tmp_path / "fan-in.json",
        )


def test_fan_in_installs_only_digest_bound_refreshed_governed_evidence(
    tmp_path: Path,
) -> None:
    tasks = _tasks()
    qqq = next(task for task in tasks if task["strategy_id"] == "qqq_rotation")
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")

    result = results / "qqq_rotation"
    package = result / "formal-package.json"
    shutil.copy2(SOURCE / "qqqi_qqq_tqqq_v4_3.json", package)
    receipt = _receipt(qqq, "refreshed")
    receipt["output_sha256"] = sha256(package)
    write_object(result / "receipt.json", receipt)

    current_formal, current_preview = _seed_current(tmp_path)
    candidate_formal = tmp_path / "candidate-formal"
    candidate_preview = tmp_path / "candidate-preview"

    fan_in = assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=results,
        current_root=current_formal,
        candidate_root=candidate_formal,
        current_preview_root=current_preview,
        candidate_preview_root=candidate_preview,
        receipt_path=tmp_path / "fan-in.json",
    )

    installed = candidate_formal / "qqqi_qqq_tqqq_v4_3.json"
    assert installed.read_bytes() == package.read_bytes()
    assert "qqq_rotation" in fan_in["changed_strategy_ids"]
    catalog = load_object(candidate_preview / "catalog.json")
    assert any(
        row["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
        for row in catalog["records"]
    )


def test_fan_in_rejects_unbound_refreshed_digest(tmp_path: Path) -> None:
    tasks = _tasks()
    qqq = next(task for task in tasks if task["strategy_id"] == "qqq_rotation")
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")

    result = results / "qqq_rotation"
    package = result / "formal-package.json"
    shutil.copy2(SOURCE / "qqqi_qqq_tqqq_v4_3.json", package)
    receipt = _receipt(qqq, "refreshed")
    receipt["output_sha256"] = "0" * 64
    write_object(result / "receipt.json", receipt)
    current_formal, current_preview = _seed_current(tmp_path)

    with pytest.raises(FormalRefreshError, match="digest mismatch"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=results,
            current_root=current_formal,
            candidate_root=tmp_path / "candidate-formal",
            current_preview_root=current_preview,
            candidate_preview_root=tmp_path / "candidate-preview",
            receipt_path=tmp_path / "fan-in.json",
        )
