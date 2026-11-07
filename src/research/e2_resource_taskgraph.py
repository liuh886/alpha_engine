"""Compile a conservative read-only E2 v2 DAG/capacity plan from a frozen batch.

Does not execute training or coalesce seeds; coordinator/worker implementation
is a later change with fresh runner and batch identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """Resource or immutable task-graph inputs were not acceptable."""


def _id(obj: dict) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_plan(batch: dict[str, Any], *, available_cpu_threads: int,
                 available_ram_gb: float, measured_worker_peak_ram_gb: float,
                 worker_threads: int = 2, max_workers: int = 4,
                 coordinator_reserve_ram_gb: float = 1.0) -> dict[str, Any]:
    """Allocate physical workers under explicit measured RAM and CPU budgets."""
    if (not isinstance(available_cpu_threads, int) or
            not isinstance(max_workers, int) or
            not isinstance(worker_threads, int) or
            min(available_cpu_threads, max_workers, worker_threads) < 1):
        raise PlanError("CPU worker/thread budgets must be positive integers")
    values = (available_ram_gb, measured_worker_peak_ram_gb, coordinator_reserve_ram_gb)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise PlanError("RAM inputs must be finite measured values")
    if available_ram_gb <= 0 or measured_worker_peak_ram_gb <= 0 or coordinator_reserve_ram_gb < 0:
        raise PlanError("RAM/reserve budget invalid")
    ram_slots = math.floor((available_ram_gb - coordinator_reserve_ram_gb) /
                           measured_worker_peak_ram_gb)
    workers = min(max_workers, available_cpu_threads // worker_threads, ram_slots)
    if workers < 1:
        raise PlanError("no safe worker slot under explicit CPU/RAM budget")
    trials = batch.get("trials")
    if (batch.get("research_only") is not True or batch.get("trade_ready") is not False or
            batch.get("holdout_evaluated") is not False or
            not isinstance(trials, list) or not trials or
            len(trials) != batch.get("trial_count")):
        raise PlanError("batch is not a frozen validation-only research plan")
    source = batch["data"]["history_archive_sha256"]
    runner = batch["runner_git_sha"]
    features: dict[str, dict[str, Any]] = {}
    by_feature: dict[str, list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for task in trials:
        trial_id = task["trial_id"]
        if trial_id in seen:
            raise PlanError("duplicate trial identity")
        seen.add(trial_id)
        study = task["study"]
        # The cache is a proposed immutable node, not a cache hit in this run.
        feature_inputs = {
            "source_history_sha256": source,
            "manifest_sha256": batch["data"]["v5_bundle_manifest_sha256"],
            "preprocessing_code_sha": runner,
            "fold_id": task["fold_id"],
            "pool_id": study["pool_id"],
            "symbols": study["symbols"],
            "price_mode": study["price_mode"],
            "train_start": study["train_start"],
            "train_end": study["train_end"],
            "test_start": study["test_start"],
            "test_end": study["test_end"],
            "as_of_cutoff": study["as_of_cutoff"],
            "feature_ids": study["features"],
            "feature_lookback_sessions": 20,
            "forward_label_horizon_sessions": 5,
        }
        feature_key = _id(feature_inputs)
        features[feature_key] = feature_inputs
        by_feature[feature_key].append({"trial_id": trial_id,
                                       "configuration_id": task["configuration_id"],
                                       "fold_id": task["fold_id"],
                                       "seed": task["seed"]})
    jobs: list[dict] = []
    for group_index, feature_key in enumerate(sorted(by_feature)):
        slot = group_index % workers
        for task in by_feature[feature_key]:
            jobs.append(task | {"feature_key": feature_key, "worker_slot": slot})
    if len(jobs) != len(trials):
        raise PlanError("planner lost a frozen task")
    return {
        "schema_version": "e2_resource_taskgraph_plan_v1",
        "execution_status": "DRY_RUN_NO_MODEL_EXECUTION",
        "original_batch_id": batch["batch_id"],
        "original_batch_run_id": batch["run_id"],
        "source_sha256": source, "runner_sha": runner,
        "planned_trials": len(jobs),
        "planned_feature_cache_nodes": len(features),
        "seed_deduplication": "DISABLED_REQUIRES_EFFECTIVE_DETERMINISM_PROOF",
        "cpu_threads_available": available_cpu_threads,
        "ram_gb_available": available_ram_gb,
        "ram_gb_measured_per_worker": measured_worker_peak_ram_gb,
        "ram_gb_coordinator_reserved": coordinator_reserve_ram_gb,
        "worker_threads": worker_threads, "workers": workers,
        "thread_budget_oversubscribed": False,
        "feature_nodes": [{"feature_key": k, "inputs": v,
                           "trial_references": len(by_feature[k])}
                          for k, v in sorted(features.items())],
        "tasks": jobs,
        "mutation_allowed": False, "holdout_evaluated": False,
        "trade_ready": False, "pit_certified": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-plan", type=Path, required=True)
    p.add_argument("--cpu-threads", type=int, required=True)
    p.add_argument("--ram-gb", type=float, required=True)
    p.add_argument("--measured-worker-peak-gb", type=float, required=True)
    p.add_argument("--worker-threads", type=int, default=2)
    p.add_argument("--max-workers", type=int, default=4)
    p.add_argument("--coordinator-reserve-gb", type=float, default=1.0)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    try:
        batch = json.loads(args.batch_plan.read_text(encoding="utf-8"))
        result = compile_plan(
            batch, available_cpu_threads=args.cpu_threads,
            available_ram_gb=args.ram_gb,
            measured_worker_peak_ram_gb=args.measured_worker_peak_gb,
            worker_threads=args.worker_threads, max_workers=args.max_workers,
            coordinator_reserve_ram_gb=args.coordinator_reserve_gb)
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as out:
                out.write(serialized)
        print(serialized)
        return 0
    except (OSError, KeyError, TypeError, ValueError, PlanError) as exc:
        print(f"BLOCKED_E2_RESOURCE_PLAN: {exc}")
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
