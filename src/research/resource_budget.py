"""Hardware-aware resource budgets for research model training."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingResourceBudget:
    """Bounded concurrency settings with enough provenance for run manifests."""

    logical_cpus: int
    physical_cpus: int | None
    available_memory_gb: float | None
    split_workers: int
    threads_per_model: int


def _positive_override(explicit: int | None, environment_name: str) -> int | None:
    value = explicit
    if value is None:
        raw = os.getenv(environment_name)
        if raw:
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"{environment_name} must be a positive integer") from exc
    if value is not None and value < 1:
        raise ValueError(f"{environment_name} must be a positive integer")
    return value


def resolve_training_resource_budget(
    *,
    task_count: int,
    split_workers: int | None = None,
    model_threads: int | None = None,
) -> TrainingResourceBudget:
    """Resolve a conservative, non-oversubscribed LightGBM training budget."""
    logical = max(1, os.cpu_count() or 1)
    physical: int | None = None
    memory_gb: float | None = None
    try:
        import psutil

        physical = psutil.cpu_count(logical=False)
        memory_gb = psutil.virtual_memory().available / (1024**3)
    except (ImportError, OSError):
        pass

    requested_workers = _positive_override(split_workers, "ALPHA_ENGINE_WF_WORKERS")
    requested_threads = _positive_override(model_threads, "ALPHA_ENGINE_MODEL_THREADS")

    if requested_workers is None:
        cpu_worker_limit = max(1, logical // 4)
        memory_worker_limit = (
            max(1, int(max(0.0, memory_gb - 4.0) // 4.0)) if memory_gb is not None else 1
        )
        workers = min(2, cpu_worker_limit, memory_worker_limit)
    else:
        workers = requested_workers
    workers = min(max(1, task_count), workers)

    usable_cpus = max(1, logical - 2) if logical > 4 else logical
    safe_thread_cap = 4 if workers > 1 else 8
    auto_threads = max(1, min(safe_thread_cap, usable_cpus // workers))
    threads = requested_threads or auto_threads
    if workers * threads > usable_cpus:
        threads = max(1, usable_cpus // workers)

    return TrainingResourceBudget(
        logical_cpus=logical,
        physical_cpus=physical,
        available_memory_gb=memory_gb,
        split_workers=workers,
        threads_per_model=threads,
    )
