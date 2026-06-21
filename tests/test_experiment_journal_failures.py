import asyncio

from src.api.routers.factors import experiment_log_summary
from src.research import experiment_journal, factor_registry
from src.research.experiment_journal import ExperimentJournal


class _FactorRegistry:
    def list_factors(self, stage=None):
        factors = {
            "Proposed": [
                {"id": 1, "name": "not-run", "stage": "Proposed"},
                {"id": 2, "name": "failed-validation", "stage": "Proposed"},
            ],
            "Deprecated": [],
            "Retired": [],
        }
        return factors.get(stage, [])

    def get_validations(self, factor_id):
        if factor_id == 2:
            return [{"passed": False, "icir": 0.1, "t_stat": 0.5}]
        return []


class _ModelRegistry:
    def list_models(self, stage=None):
        return []


def test_unvalidated_proposals_are_not_reported_as_failed(monkeypatch, tmp_path):
    journal = ExperimentJournal(walk_forward_dir=str(tmp_path))
    monkeypatch.setattr(journal, "_get_factor_registry", lambda: _FactorRegistry())
    monkeypatch.setattr(journal, "_get_model_registry", lambda: _ModelRegistry())

    failures = journal.what_failed(market="us")

    assert [failure["name"] for failure in failures] == ["failed-validation"]


def test_experiment_summary_uses_the_same_failure_definition(monkeypatch):
    class Registry:
        def list_factors(self, stage=None):
            return [{"stage": "Active"}] if stage == "Active" else [{}, {}, {}]

    class Journal:
        def what_failed(self, market):
            return [{"reason": "failed"}, {"reason": "failed"}]

    monkeypatch.setattr(factor_registry, "FactorRegistry", Registry)
    monkeypatch.setattr(experiment_journal, "ExperimentJournal", Journal)

    response = asyncio.run(experiment_log_summary(market="us"))

    assert response["summary"]["failed_experiments"] == 2
