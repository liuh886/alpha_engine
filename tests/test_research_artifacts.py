"""Tests for research artifact safety and completeness."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.research.research_artifacts import (
    ARTIFACT_PATH_KEYS,
    ResearchRunPaths,
    build_frontend_payload,
    build_research_run_paths,
    build_research_signals_payload,
    validate_artifact_completeness,
    write_frontend_payload,
    write_json,
    write_run_status,
    write_top_bottom_signals_csv,
)


def test_paths_list_only_existing_files_by_default(tmp_path: Path) -> None:
    paths = ResearchRunPaths(tmp_path / "run")
    paths.ensure_dir()
    write_json(paths.experiment_spec, {"x": 1})
    assert paths.artifact_paths() == {
        "experiment_spec": str(paths.experiment_spec)
    }
    assert set(paths.artifact_paths(existing_only=False)) == set(ARTIFACT_PATH_KEYS)


def test_output_dir_contract(tmp_path: Path) -> None:
    paths = build_research_run_paths(None, "exp", output_dir=tmp_path)
    assert paths.run_dir == tmp_path / "exp"


def test_status_extra_cannot_override_reserved_fields(tmp_path: Path) -> None:
    paths = ResearchRunPaths(tmp_path)
    with pytest.raises(ValueError, match="reserved status fields"):
        write_run_status(
            paths,
            experiment_id="exp",
            status="prepared",
            extra={"trade_ready": True},
        )


def test_status_is_research_only_and_defaults_not_ready(tmp_path: Path) -> None:
    paths = ResearchRunPaths(tmp_path)
    payload = write_run_status(
        paths,
        experiment_id="exp",
        status="prepared",
        extra={"n_candidates": 8},
    )
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["n_candidates"] == 8


def test_frontend_trade_ready_derives_from_decision_only() -> None:
    not_ready = build_frontend_payload(
        "exp", market="cn", benchmark="000300"
    )
    ready = build_frontend_payload(
        "exp",
        market="cn",
        benchmark="000300",
        decision={"status": "trade_guidance_candidate", "trade_ready": True},
    )
    assert not_ready["trade_ready"] is False
    assert ready["trade_ready"] is True
    assert ready["decision_status"] == "trade_guidance_candidate"


def test_signal_rows_cannot_override_decision_readiness() -> None:
    rows = build_research_signals_payload(
        [
            {
                "symbol": "000001",
                "side": "top",
                "trade_ready": True,
            }
        ],
        market="cn",
        experiment_id="exp",
        decision=None,
    )
    assert rows[0]["trade_ready"] is False
    assert rows[0]["research_only"] is True


def test_invalid_signal_side_fails_closed() -> None:
    with pytest.raises(ValueError, match="side must be"):
        build_research_signals_payload([{"symbol": "x", "side": "buy"}])


def test_csv_uses_canonical_columns(tmp_path: Path) -> None:
    paths = ResearchRunPaths(tmp_path)
    write_top_bottom_signals_csv(
        paths,
        [{"symbol": "000001", "side": "top", "rank": 1, "score": 0.2}],
        market="cn",
        experiment_id="exp",
    )
    with paths.top_bottom_signals_csv.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["side"] == "top"
    assert row["research_only"] == "True"
    assert row["trade_ready"] == "False"


def test_artifact_profile_fails_closed_when_incomplete(tmp_path: Path) -> None:
    paths = ResearchRunPaths(tmp_path)
    paths.ensure_dir()
    with pytest.raises(ValueError, match="Missing required artifacts"):
        validate_artifact_completeness(paths, profile="research_run_v1")


def test_artifact_profile_passes_when_complete(tmp_path: Path) -> None:
    paths = ResearchRunPaths(tmp_path)
    write_json(paths.experiment_spec, {})
    write_json(paths.run_status, {})
    write_json(paths.factor_manifest, {})
    write_json(paths.candidate_manifest, {})
    write_json(paths.signals_latest, {"signals": []})
    write_top_bottom_signals_csv(paths, [])
    write_frontend_payload(
        paths,
        build_frontend_payload("exp", market="cn", benchmark="000300"),
    )
    result = validate_artifact_completeness(paths, profile="research_run_v1")
    assert result["complete"] is True
    assert json.loads(paths.frontend_payload.read_text())["trade_ready"] is False
