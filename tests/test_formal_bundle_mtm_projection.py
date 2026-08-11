from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from scripts.sync_formal_bundle_v2 import sync


SOURCE = Path("data/research/formal_backtests")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bundle_v2_appends_provisional_mtm_without_mutating_settled_report(
    tmp_path: Path,
) -> None:
    source = tmp_path / "formal-v1"
    shutil.copytree(SOURCE, source)
    package_path = source / "cn_x1_1.json"
    package = _read(package_path)
    settled_count = len(package["report"])
    cutoff = package["evidence_cutoff"]
    latest = package["report"][-1]
    package["provisional_mtm"] = {
        "schema_version": "ranker_provisional_mtm_v1",
        "as_of": cutoff,
        "signal_date": latest["holding_end_date"],
        "entry_date": latest["holding_end_date"],
        "target_weights": {"TEST": 1.0},
        "source": "governed_current_target",
        "performance_row": {
            "date": latest["holding_end_date"],
            "holding_end_date": cutoff,
            "account": latest["account"],
            "bench_hs300": latest["bench_hs300"],
            "provisional_mtm": True,
            "settlement_status": "provisional_mtm",
            "mtm_as_of": cutoff,
            "research_only": True,
            "trade_ready": False,
        },
        "research_only": True,
        "trade_ready": False,
    }
    _write(package_path, package)

    catalog_path = source / "catalog.json"
    catalog = _read(catalog_path)
    for row in catalog["records"]:
        if row["model_id"] == "cn_x1_1":
            row["sha256"] = _sha(package_path)
    _write(catalog_path, catalog)

    output = tmp_path / "formal-v2"
    sync(source, output)

    projected_catalog = _read(output / "catalog.json")
    cn = next(
        row for row in projected_catalog["records"]
        if row["model_version_id"] == "cn_x1_1"
    )
    manifest = _read(output / cn["manifest_path"])
    performance_decl = next(
        row for row in manifest["sections"] if row["section_id"] == "performance"
    )
    performance = _read((output / cn["manifest_path"]).parent / performance_decl["path"])

    assert len(package["report"]) == settled_count
    assert len(performance["report"]) == settled_count + 1
    assert performance["report"][-1]["provisional_mtm"] is True
    assert performance["report"][-1]["holding_end_date"] == cutoff
    assert performance["provisional_mtm_projected"] is True
    assert performance["source_fields"] == [
        "report",
        "provisional_mtm.performance_row",
    ]
