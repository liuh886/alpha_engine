from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.run_active_research_experiments import active_specs, validate_spec

MISSION_PATH = Path(
    "configs/research_experiments/us_x1_2_calibrated_risk_control_v1.yaml"
).resolve()
FROZEN_PROVIDER_IDENTITY = (
    "66129d0727beb8d7b014966651f8b72c119f99195e33553d9781c9954ef267d8"
)


def test_superseded_us_x1_2_mission_is_not_active() -> None:
    payload = yaml.safe_load(MISSION_PATH.read_text(encoding="utf-8"))

    assert payload["active"] is False
    assert payload["status"] == "superseded"
    assert payload["snapshot"]["provider_identity_sha256"] == FROZEN_PROVIDER_IDENTITY
    assert MISSION_PATH not in active_specs()


def test_validation_rejects_terminal_active_mission(tmp_path: Path) -> None:
    payload = yaml.safe_load(MISSION_PATH.read_text(encoding="utf-8"))
    payload["active"] = True
    path = tmp_path / "invalid_terminal.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be active with terminal status"):
        validate_spec(path)


def test_validation_rejects_non_research_boundary(tmp_path: Path) -> None:
    payload = yaml.safe_load(MISSION_PATH.read_text(encoding="utf-8"))
    payload["active"] = True
    payload["status"] = "pre_registered"
    payload["trade_ready"] = True
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="research-only boundary"):
        validate_spec(path)
