from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.sync_formal_bundle_v2 import sync
from src.artifacts.formal_bundle_reader import load_formal_run
from src.artifacts.formal_preview_builder import build_preview_bundle
from src.artifacts.model_run_exporter import update_catalog
from src.governance.active_strategy_catalog import load_active_strategy_catalog

FRESHNESS = Path("data/research/formal_model_runs")
NATIVE = Path("data/research/model_runs")
MODEL_ID = "cn_x1_1"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_bundle_v2_appends_provisional_mtm_without_mutating_settled_report(
    tmp_path: Path,
) -> None:
    package = load_formal_run(Path.cwd(), MODEL_ID).refresh_state()
    package["schema_version"] = "1.0.0"
    package["record_type"] = "formal_model_backtest"
    package["publication_status"] = "accepted_formal_baseline"
    settled_count = len(package["report"])
    cutoff = package["evidence_cutoff"]
    latest = package["report"][-1]
    latest_date = latest["date"]
    package["provisional_mtm"] = {
        "schema_version": "ranker_provisional_mtm_v1",
        "as_of": cutoff,
        "signal_date": latest_date,
        "entry_date": latest_date,
        "target_weights": {"TEST": 1.0},
        "source": "governed_current_target",
        "performance_row": {
            "date": latest_date,
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
    package_path = tmp_path / "cn-refresh-state.json"
    _write(package_path, package)

    preview = tmp_path / "active-preview"
    shutil.copytree(NATIVE, preview)
    shutil.rmtree(preview / "cn_ranker" / MODEL_ID)
    strategy = load_active_strategy_catalog().by_model_version_id[MODEL_ID]
    build_preview_bundle(package_path, strategy, output_root=preview)
    update_catalog(
        sorted(preview.rglob("manifest.json")),
        catalog_path=preview / "catalog.json",
        channel="preview",
    )

    output = tmp_path / "formal-v2"
    sync(FRESHNESS, output, native_root=preview)

    projected_catalog = _read(output / "catalog.json")
    cn = next(
        row for row in projected_catalog["records"]
        if row["model_version_id"] == MODEL_ID
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
