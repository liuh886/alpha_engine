from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

import src.research.v4_22_intraday_rank_pilot as core
from src.research.v4_22_intraday_rank_pilot_runtime import (
    run_intraday_rank_pilot_runtime,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_phase0_alignment(
    snapshot_dir: Path,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load and verify the outcome-free v4.21 Phase 0 input artifact."""

    specification = contract["frozen_phase0_snapshot"]
    required = specification["required_files"]
    alignment_path = snapshot_dir / "opening_alignment.csv"
    coverage_path = snapshot_dir / "intraday_source_coverage.csv"
    manifest_path = snapshot_dir / "manifest.json"
    missing = [
        str(path)
        for path in (alignment_path, coverage_path, manifest_path)
        if not path.exists()
    ]
    if missing:
        raise ValueError(f"frozen Phase 0 snapshot missing files: {missing}")
    hashes = {
        "opening_alignment.csv": _sha256(alignment_path),
        "intraday_source_coverage.csv": _sha256(coverage_path),
        "manifest.json": _sha256(manifest_path),
    }
    for name in ("opening_alignment.csv", "intraday_source_coverage.csv"):
        expected = str(required[name])
        if hashes[name] != expected:
            raise ValueError(
                f"frozen Phase 0 snapshot hash mismatch for {name}: "
                f"expected={expected}, actual={hashes[name]}"
            )
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("outcome_calculation_authorized") is not False:
        raise ValueError(
            "Phase 0 snapshot is not marked outcome-free"
        )
    if source_manifest.get("experiment_id") != specification["source_experiment"]:
        raise ValueError("Phase 0 snapshot experiment identity mismatch")
    source_files = source_manifest.get("files", {})
    for name in ("opening_alignment.csv", "intraday_source_coverage.csv"):
        if source_files.get(name) != hashes[name]:
            raise ValueError(
                f"Phase 0 source manifest does not authenticate {name}"
            )

    alignment = pd.read_csv(alignment_path)
    if "session_date" not in alignment.columns:
        raise ValueError("opening alignment is missing session_date")
    alignment["session_date"] = pd.to_datetime(
        alignment["session_date"], errors="raise"
    ).dt.tz_localize(None).dt.normalize()
    alignment = alignment.set_index("session_date").sort_index()
    if alignment.index.duplicated().any():
        raise ValueError("opening alignment contains duplicate sessions")
    if len(alignment) != int(specification["expected_alignment_rows"]):
        raise ValueError(
            "opening alignment row count mismatch: "
            f"expected={specification['expected_alignment_rows']}, actual={len(alignment)}"
        )
    usable = int(alignment["usable_session"].fillna(False).astype(bool).sum())
    if usable != int(specification["expected_usable_rows"]):
        raise ValueError(
            "opening alignment usable row count mismatch: "
            f"expected={specification['expected_usable_rows']}, actual={usable}"
        )
    coverage = pd.read_csv(coverage_path)
    if not coverage["admissible"].fillna(False).all():
        raise ValueError("Phase 0 snapshot contains inadmissible sources")
    audit = {
        "source_experiment": source_manifest["experiment_id"],
        "source_decision": source_manifest.get("decision"),
        "source_outcome_calculation_authorized": source_manifest.get(
            "outcome_calculation_authorized"
        ),
        "artifact_id": int(specification["artifact_id"]),
        "artifact_digest": str(specification["artifact_digest"]),
        "snapshot_dir": str(snapshot_dir),
        "file_hashes": hashes,
        "alignment_rows": int(len(alignment)),
        "usable_rows": usable,
        "first_session": alignment.index.min(),
        "last_session": alignment.index.max(),
        "vendor_rows_committed_to_repository": False,
    }
    return alignment, coverage, audit


def run_intraday_rank_pilot_from_alignment(
    alignment: pd.DataFrame,
    daily_bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> core.IntradayPilotResult:
    """Run the frozen pilot while substituting only the verified alignment input."""

    original = core.build_opening_alignment
    core.build_opening_alignment = lambda _bars, _contract: alignment.copy()
    try:
        return run_intraday_rank_pilot_runtime(
            {},
            daily_bars,
            baseline_daily,
            contract,
        )
    finally:
        core.build_opening_alignment = original
