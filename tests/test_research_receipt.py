from __future__ import annotations

import json
from pathlib import Path

from src.research.research_receipt import (
    build_factor_lineage,
    finalize_research_receipt,
    write_research_receipt,
)


US_MISSION = Path(
    "configs/research_experiments/us_x1_2_risk_controlled_momentum_v1.yaml"
)


def test_us_mission_records_declared_aliases_and_effective_factors() -> None:
    lineage = build_factor_lineage(US_MISSION)

    assert lineage is not None
    assert lineage["source"] == "configs/factor_libraries/us_ohlcv.yaml"
    assert len(lineage["source_sha256"]) == 64
    assert lineage["identity"]["scheme"] == "qlib_expression_text_v1"

    baseline = lineage["candidates"]["baseline_7factor"]
    challenger = lineage["candidates"]["risk_controlled_9factor"]

    assert baseline["declared_factor_count"] == 7
    assert baseline["effective_factor_count"] == 7
    assert challenger["declared_factor_count"] == 14
    assert challenger["effective_factor_count"] == 9

    ret10 = next(
        item
        for item in challenger["effective_factors"]
        if item["expression"] == "$close/Ref($close,10)-1"
    )
    assert ret10["declared_factor_ids"] == [
        "us:momentum:ret_10d@momentum_volatility_volume",
        "us:momentum:ret_10d@risk_controlled_momentum",
    ]
    assert ret10["canonical_expression_id"].startswith("qlib-expression:")
    assert len(ret10["canonical_expression_sha256"]) == 64


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
        US_MISSION,
        {"experiment_id": "us_x1_2_risk_controlled_momentum_v1", "status": "completed"},
        output_dir=tmp_path,
    )

    stored = json.loads((tmp_path / "research_receipt.json").read_text(encoding="utf-8"))
    assert stored == final
    assert stored["factor_lineage"]["candidates"]["risk_controlled_9factor"][
        "effective_factor_count"
    ] == 9
