import pytest

from src.assistant.services.training_service import TrainingService


def test_training_service_create_job():
    service = TrainingService(project_root=".", python_exe="python")

    # 1. Test success
    payload = {"market": "us", "tag": "LGBM_v1", "model_type": "lgbm"}
    job = service.create_job_from_payload(payload)
    assert job["type"] == "train"
    assert job["market"] == "us"
    assert job["tag"] == "LGBM_v1"
    assert "src.orchestrator" in job["commands"][0]
    assert "--market us" in " ".join(job["commands"][0])

    # 2. Test missing market
    with pytest.raises(ValueError, match="market is required"):
        service.create_job_from_payload({"tag": "no_market"})

    # 3. Test missing tag
    with pytest.raises(ValueError, match="tag is required"):
        service.create_job_from_payload({"market": "us"})
