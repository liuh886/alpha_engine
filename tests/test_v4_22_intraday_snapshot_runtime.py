from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.v4_22_intraday_snapshot_runtime import (
    load_frozen_phase0_alignment,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(tmp_path: Path, *, outcome_authorized: bool = False) -> tuple[Path, dict]:
    directory = tmp_path / "snapshot"
    directory.mkdir()
    alignment = pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2024-08-05", "2024-08-06"]),
            "QQQ_open": [100.0, 101.0],
            "usable_session": [True, False],
        }
    )
    coverage = pd.DataFrame(
        {
            "symbol": ["QQQ", "SPY", "TQQQ"],
            "admissible": [True, True, True],
        }
    )
    alignment_path = directory / "opening_alignment.csv"
    coverage_path = directory / "intraday_source_coverage.csv"
    alignment.to_csv(alignment_path, index=False)
    coverage.to_csv(coverage_path, index=False)
    manifest = {
        "experiment_id": "qqqi_state2_intraday_meta_label_v4_21_research",
        "decision": "intraday_phase0_failed_no_outcomes_authorized",
        "outcome_calculation_authorized": outcome_authorized,
        "files": {
            "opening_alignment.csv": _sha256(alignment_path),
            "intraday_source_coverage.csv": _sha256(coverage_path),
        },
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    contract = {
        "frozen_phase0_snapshot": {
            "source_experiment": manifest["experiment_id"],
            "artifact_id": 123,
            "artifact_digest": "sha256:test",
            "required_files": {
                "opening_alignment.csv": _sha256(alignment_path),
                "intraday_source_coverage.csv": _sha256(coverage_path),
                "manifest.json": None,
            },
            "expected_alignment_rows": 2,
            "expected_usable_rows": 1,
        }
    }
    return directory, contract


def test_load_frozen_snapshot_verifies_outcome_free_files(tmp_path):
    directory, contract = _snapshot(tmp_path)
    alignment, coverage, audit = load_frozen_phase0_alignment(
        directory, contract
    )
    assert len(alignment) == 2
    assert int(alignment["usable_session"].sum()) == 1
    assert coverage["admissible"].all()
    assert audit["source_outcome_calculation_authorized"] is False
    assert audit["artifact_id"] == 123
    assert audit["vendor_rows_committed_to_repository"] is False


def test_load_frozen_snapshot_rejects_tampered_alignment(tmp_path):
    directory, contract = _snapshot(tmp_path)
    with (directory / "opening_alignment.csv").open("a", encoding="utf-8") as handle:
        handle.write("2024-08-07,102.0,true\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_frozen_phase0_alignment(directory, contract)


def test_load_frozen_snapshot_requires_outcome_free_source(tmp_path):
    directory, contract = _snapshot(tmp_path, outcome_authorized=True)
    with pytest.raises(ValueError, match="not marked outcome-free"):
        load_frozen_phase0_alignment(directory, contract)


def test_load_frozen_snapshot_rejects_inadmissible_source(tmp_path):
    directory, contract = _snapshot(tmp_path)
    coverage_path = directory / "intraday_source_coverage.csv"
    coverage = pd.read_csv(coverage_path)
    coverage.loc[0, "admissible"] = False
    coverage.to_csv(coverage_path, index=False)
    contract["frozen_phase0_snapshot"]["required_files"][
        "intraday_source_coverage.csv"
    ] = _sha256(coverage_path)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["intraday_source_coverage.csv"] = _sha256(coverage_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="inadmissible sources"):
        load_frozen_phase0_alignment(directory, contract)
