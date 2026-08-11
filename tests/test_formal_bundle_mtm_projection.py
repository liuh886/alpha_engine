from __future__ import annotations

import json
from pathlib import Path

from scripts.sync_formal_bundle_v2 import sync


SOURCE = Path("data/research/formal_backtests")
NATIVE = Path("data/research/model_runs")


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_legacy_cn_mtm_appends_without_mutating_settled_report_or_native_us(
    tmp_path: Path,
) -> None:
    """Legacy MTM stays on retained v1 models; native US x1.2 bypasses that projector."""

    source_cn = _read(SOURCE / "cn_x1_1.json")
    settled_report = source_cn["report"]
    provisional = source_cn["provisional_mtm"]["performance_row"]

    output = tmp_path / "formal-v2"
    receipt = sync(SOURCE, output, NATIVE)
    catalog = _read(output / "catalog.json")
    records = catalog["records"]

    cn_record = next(row for row in records if row["model_version_id"] == "cn_x1_1")
    cn_run = (output / cn_record["manifest_path"]).parent
    performance = _read(cn_run / "performance.json")
    projected_report = performance["report"]

    assert source_cn["report"] == settled_report
    assert projected_report[:-1] == settled_report
    assert projected_report[-1] == provisional
    assert performance["provisional_mtm_projected"] is True
    assert performance["source_fields"] == [
        "report",
        "provisional_mtm.performance_row",
    ]

    model_ids = {row["model_version_id"] for row in records}
    assert "us_x1_1" not in model_ids
    assert "us_x1_2" in model_ids
    assert receipt["superseded_formal_model_ids"] == ["us_x1_1"]
    assert "us_x1_1" in receipt["migration_receipt"]["provisional_mtm_models"]
    assert "cn_x1_1" in receipt["migration_receipt"]["provisional_mtm_models"]

    us_record = next(row for row in records if row["model_version_id"] == "us_x1_2")
    us_run = (output / us_record["manifest_path"]).parent
    us_performance = _read(us_run / "performance.json")
    assert us_performance.get("provisional_mtm_projected") is not True
