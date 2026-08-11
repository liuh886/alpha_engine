"""Tests for src.optimization.contracts and src.optimization.receipts."""
import json, tempfile
from pathlib import Path

from src.optimization.contracts import (
    CandidateSpec, CostStructure, ExperimentContract, ModelType, WindowSpec,
)
from src.optimization.receipts import experiment_identity, write_receipt


class TestContracts:
    def test_baseline_lookup(self):
        candidates = (
            CandidateSpec("bl", "baseline"),
            CandidateSpec("ch1", "challenger"),
        )
        c = ExperimentContract("test", ModelType.RANKER, "us", "QQQ",
            CostStructure(20.0), WindowSpec(("2024H1",)), candidates, "bl")
        assert c.baseline.candidate_id == "bl"
        assert len(c.challengers) == 1

    def test_baseline_not_found(self):
        import pytest
        c = ExperimentContract("test", ModelType.RANKER, "us", "QQQ",
            CostStructure(20.0), WindowSpec(("2024H1",)), (), "missing")
        with pytest.raises(ValueError, match="not found"):
            _ = c.baseline

    def test_cost_stress_defaults(self):
        cs = CostStructure(20.0)
        assert cs.stress_cost_bps == (40.0, 60.0)

    def test_experiment_identity_stable(self):
        candidates = (CandidateSpec("bl", "baseline"), CandidateSpec("ch", "challenger"))
        c = ExperimentContract("test", ModelType.RANKER, "us", "QQQ",
            CostStructure(20.0), WindowSpec(("2024H1",)), candidates, "bl")
        id1 = experiment_identity(c)
        id2 = experiment_identity(c)
        assert id1 == id2  # Deterministic


class TestReceipts:
    def test_write_and_read(self):
        results = [{"candidate": "bl", "exc20": 0.15, "dd": -0.05}]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_receipt(tmp, "test_exp", results, provider_identity="abc123")
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["experiment_id"] == "test_exp"
            assert data["provider_identity"] == "abc123"
            assert len(data["results"]) == 1
            assert "generated_at" in data
