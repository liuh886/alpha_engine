from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.assistant.services.model_service as model_service_module
from src.assistant.services.model_service import ModelService


class FakeModelIndex:
    def __init__(self, version: dict, *, update_ok: bool = True) -> None:
        self.version = version
        self.update_ok = update_ok
        self.updated: list[tuple[str, str]] = []

    def get_version(self, version_id: str) -> dict:
        return self.version if version_id == self.version["id"] else {}

    def update_stage(self, version_id: str, stage: str) -> bool:
        self.updated.append((version_id, stage))
        return self.update_ok


def _eligible_entry(version_id: str, model_path: Path) -> dict:
    artifact_id = f"artifact-{version_id}"
    return {
        "id": version_id,
        "market": "us",
        "type": "LGBModel",
        "path": str(model_path),
        "created_at": "2026-06-20",
        "stage": "STAGING",
        "backtest": {
            "metrics": {
                "excess_return": 0.02,
                "information_ratio": 0.8,
                "max_drawdown": -0.08,
                "bench_max_drawdown": -0.1,
                "excess_return_with_cost": 0.01,
            }
        },
        "artifact_id": artifact_id,
        "walk_forward": {
            "model_id": version_id,
            "gate_passed": True,
        },
        "inference_gate": {"artifact_id": artifact_id, "passed": True},
        "reconstruction_gate": {
            "artifact_id": artifact_id,
            "passed": True,
            "status": "passed",
            "clean_process": True,
        },
    }


def test_recommended_gate_failure_returns_model_evidence(tmp_path, monkeypatch):
    version_id = "model_v_evidence_failure"
    monkeypatch.setattr(model_service_module, "MODELS_DIR", tmp_path / "models")
    model_index = FakeModelIndex(
        {
            "id": version_id,
            "market": "us",
            "metrics_json": json.dumps(
                {
                    "excess_return": -0.01,
                    "information_ratio": 0.7,
                    "max_drawdown": -0.1,
                    "bench_max_drawdown": -0.1,
                    "excess_return_with_cost": 0.02,
                    "walk_forward_validated": {"gate_passed": True},
                }
            ),
        }
    )
    service = ModelService(project_root=tmp_path, model_index=model_index)

    result = service.promote_model(version_id, stage="RECOMMENDED")

    assert result["ok"] is False
    assert result["gate_failures"]
    assert model_index.updated == []
    assert result["evidence"]["subject_type"] == "model"
    assert result["evidence"]["subject_id"] == version_id
    assert result["evidence"]["sources"][0]["name"] == "model_registry"


def test_non_recommended_promotion_does_not_force_evidence(tmp_path, monkeypatch):
    version_id = "model_v_staging"
    monkeypatch.setattr(model_service_module, "MODELS_DIR", tmp_path / "models")
    model_index = FakeModelIndex(
        {
            "id": version_id,
            "market": "us",
            "metrics_json": json.dumps({"excess_return": -0.01}),
        }
    )
    service = ModelService(project_root=tmp_path, model_index=model_index)

    result = service.promote_model(version_id, stage="STAGING")

    assert result == {"ok": True, "gate_failures": []}
    assert model_index.updated == [(version_id, "STAGING")]


def test_arbitrary_stage_cannot_bypass_promotion_gates(tmp_path, monkeypatch):
    version_id = "model_v_arbitrary_stage"
    monkeypatch.setattr(model_service_module, "MODELS_DIR", tmp_path / "models")
    model_index = FakeModelIndex(
        {
            "id": version_id,
            "market": "us",
            "metrics_json": json.dumps({"excess_return": -0.01}),
        }
    )
    service = ModelService(project_root=tmp_path, model_index=model_index)

    with pytest.raises(ValueError, match="Unknown model stage"):
        service.promote_model(version_id, stage="PRODUCTION_BUT_UNCHECKED")

    assert model_index.updated == []


def test_recommended_stage_fails_when_required_metrics_are_missing(tmp_path, monkeypatch):
    version_id = "model_v_missing_metrics"
    monkeypatch.setattr(model_service_module, "MODELS_DIR", tmp_path / "models")
    model_index = FakeModelIndex(
        {
            "id": version_id,
            "market": "us",
            "metrics_json": json.dumps({"excess_return": 0.02}),
            "payload": {
                "walk_forward": {
                    "model_id": version_id,
                    "gate_passed": True,
                },
                "inference_gate": {"artifact_id": version_id, "passed": True},
                "reconstruction_gate": {
                    "artifact_id": version_id,
                    "passed": True,
                    "clean_process": True,
                },
            },
        }
    )
    service = ModelService(project_root=tmp_path, model_index=model_index)

    result = service.promote_model(version_id, stage="RECOMMENDED")

    assert result["ok"] is False
    assert any("Missing required promotion metric" in reason for reason in result["gate_failures"])
    assert model_index.updated == []


def test_same_market_walk_forward_file_is_not_model_evidence(tmp_path, monkeypatch):
    version_id = "model_v_without_bound_wf"
    monkeypatch.setattr(model_service_module, "MODELS_DIR", tmp_path / "models")
    wf_dir = tmp_path / "artifacts" / "walk_forward"
    wf_dir.mkdir(parents=True)
    (wf_dir / "us_latest.json").write_text(
        json.dumps({"gate_passed": True, "mean_ic": 0.2}),
        encoding="utf-8",
    )
    model_index = FakeModelIndex(
        {
            "id": version_id,
            "market": "us",
            "metrics_json": json.dumps(
                {
                    "excess_return": 0.02,
                    "information_ratio": 0.8,
                    "max_drawdown": -0.08,
                    "bench_max_drawdown": -0.1,
                    "excess_return_with_cost": 0.01,
                }
            ),
            "payload": {
                "inference_gate": {"artifact_id": version_id, "passed": True},
                "reconstruction_gate": {
                    "artifact_id": version_id,
                    "passed": True,
                    "clean_process": True,
                },
            },
        }
    )
    service = ModelService(project_root=tmp_path, model_index=model_index)

    failures = service._check_promotion_gates(version_id)

    assert any("Walk-forward validation not performed" in reason for reason in failures)


def test_model_details_use_frozen_artifact_config(tmp_path, monkeypatch):
    version_id = "model_v_frozen_config"
    monkeypatch.setattr(model_service_module, "MODELS_DIR", tmp_path / "models")
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "us_lgbm_workflow.yaml").write_text(
        "task:\n  model:\n    kwargs:\n      max_depth: 99\n",
        encoding="utf-8",
    )
    frozen = {"task": {"model": {"kwargs": {"max_depth": 6}}}}
    model_index = FakeModelIndex(
        {
            "id": version_id,
            "market": "us",
            "payload": {"artifact_id": "artifact-1", "artifact_config": frozen},
        }
    )
    service = ModelService(project_root=tmp_path, model_index=model_index)

    details = service.get_model_details(version_id)

    assert details["config"]["resolved"] == frozen
    assert "max_depth: 6" in details["config"]["content"]
    assert "max_depth: 99" not in details["config"]["content"]


def test_promotion_rolls_back_registry_and_alias_when_audit_fails(tmp_path, monkeypatch):
    from src.assistant.model_registry_index import ModelRegistryIndex

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model_path = models_dir / "candidate.pkl"
    model_path.write_bytes(b"candidate")
    monkeypatch.setattr(model_service_module, "MODELS_DIR", models_dir)
    index = ModelRegistryIndex(db_path=tmp_path / "artifacts" / "metadata.db")
    entry = _eligible_entry("model-atomic-rollback", model_path)
    index.upsert_entry(entry)
    service = ModelService(project_root=tmp_path, model_index=index)
    monkeypatch.setattr(
        service._gov,
        "log_run_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    result = service.promote_model(entry["id"], stage="RECOMMENDED")

    assert result["ok"] is False
    assert index.get_version(entry["id"])["stage"] == "STAGING"
    assert not (models_dir / "recommended_us_model.pkl").exists()


def test_successful_promotion_updates_alias_registry_and_audit(tmp_path, monkeypatch):
    from src.assistant.model_registry_index import ModelRegistryIndex

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    model_path = models_dir / "candidate.pkl"
    model_path.write_bytes(b"candidate")
    monkeypatch.setattr(model_service_module, "MODELS_DIR", models_dir)
    index = ModelRegistryIndex(db_path=tmp_path / "artifacts" / "metadata.db")
    entry = _eligible_entry("model-atomic-success", model_path)
    index.upsert_entry(entry)
    service = ModelService(project_root=tmp_path, model_index=index)

    result = service.promote_model(entry["id"], stage="RECOMMENDED")

    assert result["ok"] is True
    assert index.get_version(entry["id"])["stage"] == "RECOMMENDED"
    assert (models_dir / "recommended_us_model.pkl").read_bytes() == b"candidate"
    audit = service._gov.query_history(limit=1)[0]
    assert audit["action"] == "Model Promotion"
    assert audit["details"]["model_id"] == entry["id"]
    assert audit["details"]["stage"] == "RECOMMENDED"
