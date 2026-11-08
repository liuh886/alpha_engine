"""Taskgraph is deterministic, bounded, non-mutating and never silently drops seeds."""
from __future__ import annotations

import copy

import pytest

from src.research.e2_resource_taskgraph import PlanError, compile_plan


def sample_batch():
    task = {
        "configuration_id": "xgb-p00", "fold_id": "fold_a",
        "study": {
            "pool_id": "us_selected_equities_v2", "symbols": "$US87",
            "price_mode": "anchored_adjusted",
            "train_start": "2025-06-05", "train_end": "2025-12-22",
            "test_start": "2026-01-02", "test_end": "2026-02-27",
            "as_of_cutoff": "2026-06-30",
            "features": ["return_5d", "return_20d"],
        },
    }
    a = copy.deepcopy(task)
    a.update(trial_id="xgb-a-s17", seed=17)
    b = copy.deepcopy(task)
    b.update(trial_id="xgb-a-s42", seed=42)
    c = copy.deepcopy(task)
    c.update(trial_id="xgb-a-risk-s17", seed=17)
    c["study"]["features"] = ["volatility_20d"]
    return {
        "batch_id": "v6-fixed-id", "run_id": "fixed-run", "runner_git_sha": "a" * 40,
        "trial_count": 3, "research_only": True,
        "trade_ready": False, "holdout_evaluated": False,
        "data": {"history_archive_sha256": "b" * 64,
                 "v5_bundle_manifest_sha256": "c" * 64},
        "trials": [a, b, c],
    }


def plan(**kwargs):
    return compile_plan(sample_batch(), available_cpu_threads=8,
                        available_ram_gb=16.0, measured_worker_peak_ram_gb=3.0,
                        **kwargs)


def test_resource_plan_reuses_feature_nodes_but_preserves_all_seeds():
    result = plan()
    assert result["workers"] == 4
    assert result["planned_trials"] == 3
    assert result["planned_feature_cache_nodes"] == 2
    assert result["seed_deduplication"].startswith("DISABLED")
    keys = {j["trial_id"]: j["feature_key"] for j in result["tasks"]}
    assert keys["xgb-a-s17"] == keys["xgb-a-s42"]
    assert keys["xgb-a-s17"] != keys["xgb-a-risk-s17"]
    assert result["execution_status"] == "DRY_RUN_NO_MODEL_EXECUTION"
    assert result == plan()  # stable deterministic compilation


def test_rejects_cpu_and_memory_oversubscription():
    with pytest.raises(PlanError, match="no safe worker"):
        compile_plan(sample_batch(), available_cpu_threads=2, worker_threads=4,
                     available_ram_gb=8, measured_worker_peak_ram_gb=2)
    with pytest.raises(PlanError, match="no safe worker"):
        compile_plan(sample_batch(), available_cpu_threads=8, worker_threads=2,
                     available_ram_gb=1.5, measured_worker_peak_ram_gb=1)


def test_rejects_duplicate_identity_and_unreviewed_batch():
    data = sample_batch()
    data["trials"][1]["trial_id"] = data["trials"][0]["trial_id"]
    with pytest.raises(PlanError, match="duplicate"):
        compile_plan(data, available_cpu_threads=4, available_ram_gb=12,
                     measured_worker_peak_ram_gb=2)
    data = sample_batch()
    data["holdout_evaluated"] = True
    with pytest.raises(PlanError, match="research plan"):
        compile_plan(data, available_cpu_threads=4, available_ram_gb=12,
                     measured_worker_peak_ram_gb=2)
