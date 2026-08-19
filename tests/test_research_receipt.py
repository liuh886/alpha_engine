from __future__ import annotations

import json
from pathlib import Path

from src.research.research_receipt import (
    build_factor_lineage,
    finalize_research_receipt,
    write_research_receipt,
)


FACTOR_MISSION = Path("tests/fixtures/research_experiments/alpha158_runner_v1.yaml")


def test_factor_mission_records_canonical_factor_identities() -> None:
    lineage = build_factor_lineage(FACTOR_MISSION)

    assert lineage is not None
    assert lineage["schema_version"] == "2.0"
    assert lineage["source"] == "src/factors/sets/qlib_alpha158.py"
    assert len(lineage["source_sha256"]) == 64
    assert lineage["catalog_id"] == "qlib_alpha158"

    baseline = lineage["candidates"]["alpha158_baseline"]
    challenger = lineage["candidates"]["alpha158_challenger"]

    assert baseline["factor_count"] == 158
    assert challenger["factor_count"] == 158
    assert len(challenger["factor_ids"]) == len(set(challenger["factor_ids"]))
    assert all(len(item["implementation_hash"]) == 64 for item in challenger["factors"])


def test_mission_without_factor_library_does_not_invent_factor_lineage(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "allocation.yaml"
    spec.write_text(
        "experiment_id: allocation_test\nrunner: rules_based_allocation_v1\n",
        encoding="utf-8",
    )

    receipt = finalize_research_receipt(
        spec,
        {"experiment_id": "allocation_test", "status": "completed"},
    )

    assert "factor_lineage" not in receipt


def test_write_research_receipt_persists_finalized_payload(tmp_path: Path) -> None:
    final = write_research_receipt(
        FACTOR_MISSION,
        {"experiment_id": "alpha158_runner_fixture_v1", "status": "completed"},
        output_dir=tmp_path,
    )

    stored = json.loads((tmp_path / "research_receipt.json").read_text(encoding="utf-8"))
    assert stored == final
    assert stored["factor_lineage"]["candidates"]["alpha158_challenger"][
        "factor_count"
    ] == 158
