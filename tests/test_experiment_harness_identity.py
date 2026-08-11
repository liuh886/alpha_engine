"""Tests for provider identity validation in experiment_harness."""
import pytest, tempfile, yaml
from pathlib import Path
from src.research.experiment_harness import load_experiment_contract


MINIMAL_CONFIG = {
    "experiment_id": "test",
    "runner": "cross_sectional_xgb_ranker_v1",
    "research_only": True,
    "trade_ready": False,
    "windows": {
        "candidate_selection": ["2024H1"],
        "consumed_reporting_only": [],
        "consumed_reporting_may_enter_selection": False,
    },
    "evaluation": {
        "baseline_candidate_id": "bl",
        "stress_cost_bps": 60,
        "decision": "test",
        "ranking": ["compounded_relative_excess"],
        "thresholds": {
            "min_window_relative_excess": 0.0,
            "min_worst_drawdown": -0.30,
            "min_stress_compounded_relative_excess": 0.0,
            "max_strongest_positive_window_share": 0.55,
            "min_mean_rank_ic_improvement": 0.0,
            "require_factor_baseline_dominance": False,
        },
    },
    "execution": {"base_cost_bps": 20, "cost_stress_bps": [20, 60]},
    "snapshot": {
        "provider_identity_sha256": "abc123",
        "cutoff": "2026-06-24",
    },
}


class TestProviderIdentityValidation:
    def test_valid_config_loads(self, tmp_path):
        path = tmp_path / "valid.yaml"
        path.write_text(yaml.dump(MINIMAL_CONFIG))
        contract = load_experiment_contract(str(path))
        assert contract.provider_identity_sha256 == "abc123"
        assert contract.cutoff == "2026-06-24"

    def test_missing_provider_identity_raises(self, tmp_path):
        cfg = {**MINIMAL_CONFIG, "snapshot": {"cutoff": "2026-06-24"}}
        path = tmp_path / "no_provider.yaml"
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="provider_identity_sha256 is required"):
            load_experiment_contract(str(path))

    def test_empty_provider_identity_raises(self, tmp_path):
        cfg = {**MINIMAL_CONFIG, "snapshot": {"provider_identity_sha256": "", "cutoff": "2026-06-24"}}
        path = tmp_path / "empty_provider.yaml"
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="provider_identity_sha256 is required"):
            load_experiment_contract(str(path))

    def test_missing_cutoff_raises(self, tmp_path):
        cfg = {**MINIMAL_CONFIG, "snapshot": {"provider_identity_sha256": "abc123"}}
        path = tmp_path / "no_cutoff.yaml"
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="cutoff is required"):
            load_experiment_contract(str(path))
