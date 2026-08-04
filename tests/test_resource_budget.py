from __future__ import annotations

from src.research.resource_budget import resolve_training_resource_budget


def test_training_budget_never_oversubscribes_available_cpus(monkeypatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 16)
    monkeypatch.delenv("ALPHA_ENGINE_WF_WORKERS", raising=False)
    monkeypatch.delenv("ALPHA_ENGINE_MODEL_THREADS", raising=False)

    budget = resolve_training_resource_budget(task_count=8)

    assert budget.split_workers in {1, 2}
    assert budget.threads_per_model <= (4 if budget.split_workers > 1 else 8)
    assert budget.split_workers * budget.threads_per_model <= 14


def test_training_budget_caps_explicit_oversubscription(monkeypatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 8)

    budget = resolve_training_resource_budget(
        task_count=3, split_workers=3, model_threads=20
    )

    assert budget.split_workers == 3
    assert budget.threads_per_model == 2
    assert budget.split_workers * budget.threads_per_model <= 6
