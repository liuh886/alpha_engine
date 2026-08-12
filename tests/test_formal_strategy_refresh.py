from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_formal_refresh_transaction import assemble_strategy_results
from scripts.run_formal_strategy_refresh import RECEIPT_SCHEMA
from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object


def _task(strategy_id: str, model_id: str, publication_input: str) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "model_family_id": f"{strategy_id}_family",
        "model_version_id": model_id,
        "model_kind": (
            "rules_based_allocation" if strategy_id == "qqq_rotation" else "cross_sectional_ranker"
        ),
        "market": "us",
        "planned_provider_cutoff": "2026-08-10",
        "publication_input": publication_input,
        "formal_refresh_required": publication_input == "formal_v1",
        "mtm_refresh_required": False,
    }


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
            "generated_at": "2026-08-12T00:00:00Z",
            "tasks": tasks,
            "research_only": True,
            "trade_ready": False,
        },
    )


def _seed_tree(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "marker.json").write_text(json.dumps({"current": True}), encoding="utf-8")


def test_fan_in_accepts_complete_current_strategy_set(tmp_path: Path) -> None:
    tasks = [
        _task("qqq_rotation", "qqqi_qqq_tqqq_v4_3", "formal_v1"),
        _task("us_x", "us_x1_2", "native_bundle_v2"),
    ]
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    for task in tasks:
        result = results / str(task["strategy_id"])
        result.mkdir(parents=True)
        write_object(result / "receipt.json", _receipt(task, "current_no_change"))

    current_formal = tmp_path / "current-formal"
    current_preview = tmp_path / "current-preview"
    _seed_tree(current_formal)
    _seed_tree(current_preview)
    fan_in_path = tmp_path / "fan-in.json"

    fan_in = assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=results,
        current_root=current_formal,
        candidate_root=tmp_path / "candidate-formal",
        current_preview_root=current_preview,
        candidate_preview_root=tmp_path / "candidate-preview",
        receipt_path=fan_in_path,
    )

    assert fan_in["status"] == "complete"
    assert fan_in["expected_strategy_ids"] == ["qqq_rotation", "us_x"]
    assert fan_in["changed_strategy_ids"] == []
    assert load_object(fan_in_path)["status"] == "complete"


def test_fan_in_fails_closed_on_missing_strategy_receipt(tmp_path: Path) -> None:
    tasks = [
        _task("qqq_rotation", "qqqi_qqq_tqqq_v4_3", "formal_v1"),
        _task("us_x", "us_x1_2", "native_bundle_v2"),
    ]
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    only = results / "qqq_rotation"
    only.mkdir(parents=True)
    write_object(only / "receipt.json", _receipt(tasks[0], "current_no_change"))
    current_formal = tmp_path / "current-formal"
    current_preview = tmp_path / "current-preview"
    _seed_tree(current_formal)
    _seed_tree(current_preview)

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
    task = _task("qqq_rotation", "qqqi_qqq_tqqq_v4_3", "formal_v1")
    plan = tmp_path / "plan.json"
    _write_plan(plan, [task])
    result = tmp_path / "results" / "qqq_rotation"
    result.mkdir(parents=True)
    write_object(result / "receipt.json", _receipt(task, "invalid_evidence"))
    current_formal = tmp_path / "current-formal"
    current_preview = tmp_path / "current-preview"
    _seed_tree(current_formal)
    _seed_tree(current_preview)

    with pytest.raises(FormalRefreshError, match="not publishable"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=tmp_path / "results",
            current_root=current_formal,
            candidate_root=tmp_path / "candidate-formal",
            current_preview_root=current_preview,
            candidate_preview_root=tmp_path / "candidate-preview",
            receipt_path=tmp_path / "fan-in.json",
        )


def test_fan_in_installs_only_digest_bound_refreshed_package(tmp_path: Path) -> None:
    task = _task("qqq_rotation", "qqqi_qqq_tqqq_v4_3", "formal_v1")
    plan = tmp_path / "plan.json"
    _write_plan(plan, [task])
    result = tmp_path / "results" / "qqq_rotation"
    result.mkdir(parents=True)
    package = result / "formal-package.json"
    package.write_text('{"candidate":true}\n', encoding="utf-8")
    receipt = _receipt(task, "refreshed")
    receipt["output_sha256"] = sha256(package)
    write_object(result / "receipt.json", receipt)
    current_formal = tmp_path / "current-formal"
    current_preview = tmp_path / "current-preview"
    _seed_tree(current_formal)
    _seed_tree(current_preview)
    candidate_formal = tmp_path / "candidate-formal"

    assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=tmp_path / "results",
        current_root=current_formal,
        candidate_root=candidate_formal,
        current_preview_root=current_preview,
        candidate_preview_root=tmp_path / "candidate-preview",
        receipt_path=tmp_path / "fan-in.json",
    )

    installed = candidate_formal / "qqqi_qqq_tqqq_v4_3.json"
    assert installed.read_bytes() == package.read_bytes()
