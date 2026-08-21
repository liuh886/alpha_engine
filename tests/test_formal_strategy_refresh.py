from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import scripts.run_formal_strategy_refresh as runner
from scripts.run_formal_refresh_transaction import (
    _assert_declared_model_transition,
    assemble_strategy_results,
)
from scripts.run_formal_strategy_refresh import RECEIPT_SCHEMA
from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.artifacts.model_run_exporter import update_catalog
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import (
    load_active_strategy_runtime_capabilities,
)

NATIVE = Path("data/research/model_runs")
STRATEGIES = Path("configs/strategies/registry.json")


def _tasks() -> list[dict[str, object]]:
    active = load_active_strategy_catalog(STRATEGIES)
    runtime = load_active_strategy_runtime_capabilities(active=active)
    return [
        {
            "strategy_id": strategy.strategy_id,
            "model_family_id": strategy.model_family_id,
            "model_version_id": strategy.model_version_id,
            "model_kind": strategy.model_kind,
            "market": strategy.market,
            "planned_provider_cutoff": "2026-08-12",
            "publication_input": "native_bundle_v2",
            "formal_refresh_required": False,
            "mtm_refresh_required": False,
            "formal_refresh_capability_status": runtime[
                strategy.strategy_id
            ].formal_refresh.status,
            "formal_refresh_adapter_id": runtime[
                strategy.strategy_id
            ].formal_refresh.adapter_id,
            "formal_refresh_block_reason": runtime[
                strategy.strategy_id
            ].formal_refresh.reason,
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
            "schema_version": "formal_refresh_plan_v4",
            "generated_at": "2026-08-13T00:00:00Z",
            "tasks": tasks,
            "research_only": True,
            "trade_ready": False,
        },
    )


def _seed_results(root: Path, tasks: list[dict[str, object]], *, status: str) -> None:
    for task in tasks:
        result = root / str(task["strategy_id"])
        result.mkdir(parents=True)
        write_object(result / "receipt.json", _receipt(task, status))


def _single_model_preview(tmp_path: Path, model_id: str) -> Path:
    source_catalog = load_object(NATIVE / "catalog.json")
    record = next(row for row in source_catalog["records"] if row["model_version_id"] == model_id)
    root = tmp_path / f"preview-{model_id}"
    family = str(record["model_family_id"])
    shutil.copytree(NATIVE / family / model_id, root / family / model_id)
    manifests = sorted((root / family / model_id).rglob("manifest.json"))
    update_catalog(manifests, catalog_path=root / "catalog.json", channel="preview")
    return root


def _us_task(*, formal: bool, mtm: bool) -> dict[str, object]:
    return {
        "strategy_id": "us_x",
        "model_family_id": "us_ranker",
        "model_version_id": "us_x1_3",
        "model_kind": "cross_sectional_ranker",
        "market": "us",
        "planned_provider_cutoff": "2026-08-12",
        "publication_input": "native_bundle_v2",
        "formal_refresh_required": formal,
        "mtm_refresh_required": mtm,
        "formal_refresh_capability_status": "available",
        "formal_refresh_adapter_id": "us_x1_3_formal_refresh_v1",
        "formal_refresh_block_reason": None,
    }


def test_fan_in_accepts_complete_active_strategy_set(tmp_path: Path) -> None:
    tasks = _tasks()
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")
    current_preview = tmp_path / "current-preview"
    shutil.copytree(NATIVE, current_preview)
    candidate_preview = tmp_path / "candidate-preview"
    fan_in_path = tmp_path / "fan-in.json"

    fan_in = assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=results,
        current_preview_root=current_preview,
        candidate_preview_root=candidate_preview,
        receipt_path=fan_in_path,
    )

    active = load_active_strategy_catalog(STRATEGIES)
    assert fan_in["status"] == "complete"
    assert fan_in["publication_contract"] == "active_preview_bundle_v2"
    assert fan_in["expected_strategy_ids"] == [row.strategy_id for row in active.strategies]
    assert fan_in["changed_strategy_ids"] == []
    assert fan_in["retained_strategy_ids"] == []
    assert sha256(candidate_preview / "catalog.json") == fan_in["preview_catalog_sha256"]
    catalog = load_object(candidate_preview / "catalog.json")
    validate_catalog(catalog)
    observed = {row["model_version_id"] for row in catalog["records"]}
    expected = set(active.active_model_version_ids)
    if observed != expected:
        _assert_declared_model_transition(
            catalog["records"],
            active,
            error_message="preview transition mismatch",
            publication_status="ci_validated_preview",
        )


def test_fan_in_fails_closed_on_missing_strategy_receipt(tmp_path: Path) -> None:
    tasks = _tasks()
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks[:-1], status="current_no_change")
    with pytest.raises(FormalRefreshError, match="membership mismatch"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=results,
            current_preview_root=NATIVE,
            candidate_preview_root=tmp_path / "candidate-preview",
            receipt_path=tmp_path / "fan-in.json",
        )


def test_fan_in_retains_current_preview_for_blocked_strategy(tmp_path: Path) -> None:
    tasks = _tasks()
    blocked_task = tasks[0]
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")
    blocked = results / str(blocked_task["strategy_id"]) / "receipt.json"
    write_object(blocked, _receipt(blocked_task, "invalid_evidence"))

    candidate = tmp_path / "candidate-preview"
    fan_in = assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=results,
        current_preview_root=NATIVE,
        candidate_preview_root=candidate,
        receipt_path=tmp_path / "fan-in.json",
    )

    assert fan_in["status"] == "degraded"
    assert fan_in["changed_strategy_ids"] == []
    assert fan_in["retained_strategy_ids"] == [blocked_task["strategy_id"]]
    assert sha256(candidate / "catalog.json") == fan_in["preview_catalog_sha256"]
    catalog = load_object(candidate / "catalog.json")
    validate_catalog(catalog)
    assert set(row["model_version_id"] for row in catalog["records"]) == set(
        load_active_strategy_catalog(STRATEGIES).active_model_version_ids
    )


def test_fan_in_records_execution_failure_and_refuses_candidate(tmp_path: Path) -> None:
    tasks = _tasks()
    failed_task = tasks[0]
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")
    failed = results / str(failed_task["strategy_id"]) / "receipt.json"
    write_object(failed, _receipt(failed_task, "execution_failed"))
    candidate = tmp_path / "candidate-preview"
    receipt_path = tmp_path / "fan-in.json"

    with pytest.raises(FormalRefreshError, match="fatal strategy execution failure"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=results,
            current_preview_root=NATIVE,
            candidate_preview_root=candidate,
            receipt_path=receipt_path,
        )

    fan_in = load_object(receipt_path)
    assert fan_in["status"] == "failed"
    assert fan_in["fatal_strategy_ids"] == [failed_task["strategy_id"]]
    assert not candidate.exists()


def test_fan_in_installs_only_digest_bound_refreshed_preview(tmp_path: Path) -> None:
    tasks = _tasks()
    qqq = next(task for task in tasks if task["strategy_id"] == "qqq_rotation")
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")

    result = results / "qqq_rotation"
    preview = _single_model_preview(tmp_path, str(qqq["model_version_id"]))
    shutil.copytree(preview, result / "model-runs")
    receipt = _receipt(qqq, "refreshed")
    receipt["output_sha256"] = sha256(result / "model-runs" / "catalog.json")
    write_object(result / "receipt.json", receipt)

    candidate_preview = tmp_path / "candidate-preview"
    fan_in = assemble_strategy_results(
        plan_path=plan,
        strategy_results_root=results,
        current_preview_root=NATIVE,
        candidate_preview_root=candidate_preview,
        receipt_path=tmp_path / "fan-in.json",
    )
    assert "qqq_rotation" in fan_in["changed_strategy_ids"]
    catalog = load_object(candidate_preview / "catalog.json")
    assert any(row["model_version_id"] == "qqqi_qqq_tqqq_v4_3" for row in catalog["records"])


def test_fan_in_rejects_unbound_refreshed_digest(tmp_path: Path) -> None:
    tasks = _tasks()
    qqq = next(task for task in tasks if task["strategy_id"] == "qqq_rotation")
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    _seed_results(results, tasks, status="current_no_change")
    result = results / "qqq_rotation"
    preview = _single_model_preview(tmp_path, str(qqq["model_version_id"]))
    shutil.copytree(preview, result / "model-runs")
    receipt = _receipt(qqq, "refreshed")
    receipt["output_sha256"] = "0" * 64
    write_object(result / "receipt.json", receipt)

    with pytest.raises(FormalRefreshError, match="digest mismatch"):
        assemble_strategy_results(
            plan_path=plan,
            strategy_results_root=results,
            current_preview_root=NATIVE,
            candidate_preview_root=tmp_path / "candidate-preview",
            receipt_path=tmp_path / "fan-in.json",
        )


def test_us_daily_mtm_fast_path_never_runs_historical_preview_builder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path.resolve()
    provider_root = root / "provider-root"
    formal_root = root / "formal"
    current_preview = root / "preview"
    result_root = root / "result"
    provider_root.mkdir()
    formal_root.mkdir()
    current_preview.mkdir()
    result_root.mkdir()

    def fail_if_historical_builder_runs(*_args, **_kwargs) -> None:
        raise AssertionError("historical builder must not run on MTM-only refresh")

    monkeypatch.setattr(runner, "_run", fail_if_historical_builder_runs)
    monkeypatch.setattr(runner, "_current_preview_bundle_id", lambda *_args: "current-bundle")

    def materialize(*, target: Path, **_kwargs):
        payload = {
            "model_id": "us_x1_3",
            "evidence_cutoff": "2026-08-11",
            "freshness": {"status": "current"},
            "report": [{"date": "2026-07-16", "holding_end_date": "2026-07-30"}],
            "positions": [{"date": "2026-07-30", "instrument": "A", "weight": 1.0}],
        }
        write_object(target, payload)
        return payload

    def attach(*, package_path: Path, cutoff: str, **_kwargs):
        payload = load_object(package_path)
        payload["evidence_cutoff"] = cutoff
        payload["freshness"] = {
            "status": "current",
            "latest_mtm_date": cutoff,
        }
        write_object(package_path, payload)
        return {"as_of": cutoff}

    monkeypatch.setattr(runner, "_materialize_refresh_state", materialize)
    monkeypatch.setattr(runner, "attach_ranker_provisional_mtm", attach)
    monkeypatch.setattr(
        runner,
        "_seal_preview",
        lambda **_kwargs: ("catalog-sha", "candidate-bundle"),
    )

    receipt = runner._run_us(
        root=root,
        task=_us_task(formal=False, mtm=True),
        provider_root=provider_root,
        formal_v2_root=formal_root,
        current_preview_root=current_preview,
        result_root=result_root,
        generated_at="2026-08-12T23:00:00Z",
    )

    assert receipt["execution_status"] == "refreshed"
    assert receipt["candidate_evidence_cutoff"] == "2026-08-12"
    assert receipt["performance_observation_end"] == "2026-08-12"
    assert receipt["replay_verdict"] == "ledger_mtm_projection_no_historical_rebuild"


def test_strategy_refresh_runtime_has_no_cn_x1_1_predecessor_adapter() -> None:
    assert not hasattr(runner, "_run_cn")
    assert not hasattr(runner, "_run_cn_duplicate_ledgers")
    source = Path("scripts/run_formal_strategy_refresh.py").read_text(encoding="utf-8")
    assert "cn_x1_1" not in source


def test_task_rejects_runtime_adapter_identity_drift(tmp_path: Path) -> None:
    task = next(row for row in _tasks() if row["strategy_id"] == "us_x")
    task["formal_refresh_adapter_id"] = "unregistered_formal_refresh_v1"
    plan = tmp_path / "plan.json"
    _write_plan(plan, [task])

    with pytest.raises(ValueError, match="formal_refresh_adapter_id"):
        runner._task(plan, "us_x")


def test_required_cn_x1_2_refresh_dispatches_exact_maintained_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    task = next(row for row in _tasks() if row["strategy_id"] == "cn_x")
    task["formal_refresh_required"] = True
    observed = {}

    def run_cn_x1_2(**kwargs):
        observed.update(kwargs)
        return {"execution_status": "refreshed", "model_id": "cn_x1_2"}

    monkeypatch.setattr(runner, "_run_cn_x1_2", run_cn_x1_2)
    receipt = runner.execute_strategy(
        root=tmp_path,
        task=task,
        provider_root=tmp_path,
        formal_v2_root=tmp_path,
        current_preview_root=tmp_path,
        result_root=tmp_path,
        generated_at="2026-08-15T00:00:00Z",
    )

    assert receipt == {"execution_status": "refreshed", "model_id": "cn_x1_2"}
    assert observed["task"] is task
    assert observed["generated_at"] == "2026-08-15T00:00:00Z"
