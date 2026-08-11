from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.run_active_research_experiments import validate_spec


def test_active_cross_sectional_spec_validates_without_execution() -> None:
    receipt = validate_spec(
        Path("configs/research_experiments/us_x1_2_calibrated_risk_control_v1.yaml").resolve()
    )

    assert receipt["status"] == "valid"
    assert receipt["models_executed"] is False
    assert receipt["providers_rebuilt"] is False


def test_validation_rejects_non_research_boundary(tmp_path: Path) -> None:
    source = Path(
        "configs/research_experiments/us_x1_2_calibrated_risk_control_v1.yaml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["trade_ready"] = True
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="research-only boundary"):
        validate_spec(path)
