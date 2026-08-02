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


def test_failure_count_comes_from_journal_definition(monkeypatch, tmp_path):
    journal = ExperimentJournal(walk_forward_dir=str(tmp_path))
    monkeypatch.setattr(journal, "_get_factor_registry", lambda: _FactorRegistry())
    monkeypatch.setattr(journal, "_get_model_registry", lambda: _ModelRegistry())

    failures = journal.what_failed(market="us")

    assert len(failures) == 1
    assert failures[0]["name"] == "failed-validation"
