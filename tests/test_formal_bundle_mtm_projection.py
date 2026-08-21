from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.sync_formal_bundle_v2 import sync
from src.artifacts.formal_bundle_reader import load_formal_run
from src.artifacts.formal_preview_builder import (
    build_preview_bundle,
    project_provisional_mtm_preview,
)
from src.artifacts.model_run_exporter import update_catalog
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.model_contract import load_performance_semantics

FRESHNESS = Path("data/research/formal_model_runs")
NATIVE = Path("data/research/model_runs")
MODEL_ID = "cn_x1_2"
US_MODEL_ID = "us_x1_3"


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
    retained_predecessor = preview / "cn_ranker" / "cn_x1_1"
    if retained_predecessor.exists():
        shutil.rmtree(retained_predecessor)
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


def test_preview_migrates_schema_less_performance_semantics_from_model_contract(
    tmp_path: Path,
) -> None:
    package = load_formal_run(Path.cwd(), US_MODEL_ID).refresh_state()
    package["schema_version"] = "1.0.0"
    package["record_type"] = "formal_model_backtest"
    package["publication_status"] = "accepted_formal_baseline"
    package["performance_semantics"].pop("schema_version", None)
    package_path = tmp_path / "us-refresh-state.json"
    _write(package_path, package)

    strategy = load_active_strategy_catalog().by_model_version_id[US_MODEL_ID]
    output = tmp_path / "preview"
    manifest_path = build_preview_bundle(package_path, strategy, output_root=output)
    manifest = _read(manifest_path)
    performance_decl = next(
        row for row in manifest["sections"] if row["section_id"] == "performance"
    )
    performance = _read(manifest_path.parent / performance_decl["path"])

    assert performance["performance_semantics"] == load_performance_semantics(strategy)


def test_us_mtm_preview_preserves_native_evidence_closure(tmp_path: Path) -> None:
    package = load_formal_run(Path.cwd(), US_MODEL_ID).refresh_state()
    package["schema_version"] = "1.0.0"
    package["record_type"] = "formal_model_backtest"
    package["publication_status"] = "accepted_formal_baseline"
    cutoff = package["evidence_cutoff"]
    package["backtest_id"] = f"{US_MODEL_ID}-through-{cutoff.replace('-', '_')}"
    latest = package["report"][-1]
    package["provisional_mtm"] = {
        "schema_version": "ranker_provisional_mtm_v1",
        "as_of": cutoff,
        "signal_date": latest["date"],
        "entry_date": latest["date"],
        "target_weights": {"TEST": 1.0},
        "source": "strategy_signal_ledger",
        "provider_identity_sha256": "a" * 64,
        "performance_row": {
            "date": cutoff,
            "holding_end_date": cutoff,
            "account": latest["account"],
            "bench_qqq": latest["bench_qqq"],
            "provisional_mtm": True,
            "settlement_status": "provisional_mtm",
            "mtm_as_of": cutoff,
            "research_only": True,
            "trade_ready": False,
        },
        "research_only": True,
        "trade_ready": False,
    }
    package_path = tmp_path / "us-refresh-state.json"
    _write(package_path, package)

    catalog = _read(NATIVE / "catalog.json")
    record = next(
        row for row in catalog["records"] if row["model_version_id"] == US_MODEL_ID
    )
    base_run = (NATIVE / record["manifest_path"]).parent
    strategy = load_active_strategy_catalog().by_model_version_id[US_MODEL_ID]
    manifest_path = project_provisional_mtm_preview(
        package_path,
        strategy,
        base_preview_run=base_run,
        output_root=tmp_path / "preview",
    )
    manifest = _read(manifest_path)
    sections = {row["section_id"]: row for row in manifest["sections"]}
    performance = _read(manifest_path.parent / sections["performance"]["path"])
    portfolio = _read(manifest_path.parent / sections["portfolio"]["path"])
    trades = _read(manifest_path.parent / sections["trades"]["path"])
    lineage = _read(manifest_path.parent / sections["lineage"]["path"])

    assert performance["report"][-1]["provisional_mtm"] is True
    assert portfolio["signals"]
    assert trades["records"]
    assert trades["analytics"]["quantity_available"] is False
    for field in (
        "builder_source_sha256",
        "factor_library_sha256",
        "universe_config_sha256",
        "classification_config_sha256",
    ):
        assert len(lineage[field]) == 64
    assert lineage["mtm_projection"]["provider_identity_sha256"] == "a" * 64
