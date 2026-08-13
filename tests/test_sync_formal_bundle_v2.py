from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.byd_formal_publication_common import write_json
from scripts.sync_formal_bundle_v2 import sync
from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle
from src.artifacts.formal_preview_builder import build_preview_bundle
from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest
from src.artifacts.model_run_exporter import update_catalog
from src.artifacts.us_x1_3_formal import MODEL_ID as US_X1_3
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID as BYD_V13

SOURCE = Path("data/research/formal_backtests")
NATIVE = Path("data/research/model_runs")
STRATEGIES = Path("configs/strategies/registry.json")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _active_preview_root(tmp_path: Path) -> Path:
    root = tmp_path / "preview"
    shutil.copytree(NATIVE, root)
    active = load_active_strategy_catalog(STRATEGIES)
    for strategy in active.strategies:
        if strategy.model_version_id == US_X1_3:
            continue
        build_preview_bundle(
            SOURCE / f"{strategy.model_version_id}.json",
            strategy,
            output_root=root,
        )
    manifests = sorted(root.rglob("manifest.json"))
    update_catalog(manifests, catalog_path=root / "catalog.json", channel="preview")
    return root


def test_formal_json_serializes_timestamps_and_numpy_scalars(tmp_path: Path) -> None:
    target = tmp_path / "evidence.json"
    digest = write_json(
        target,
        {
            "episode_start": pd.Timestamp("2026-08-03"),
            "count": np.int64(15),
            "relative_wealth": np.float64(0.0297),
        },
    )
    assert len(digest) == 64
    assert _read(target) == {
        "episode_start": "2026-08-03T00:00:00",
        "count": 15,
        "relative_wealth": 0.0297,
    }


def test_live_signal_state_is_not_embedded_in_governed_byd_evidence() -> None:
    package = _read(SOURCE / f"{BYD_V13}.json")
    monitoring = package["operational_monitoring"]
    assert monitoring == {
        "status": "separate_runtime_signal_ledger",
        "ledger": (
            "data/research/strategy_signal_ledgers/"
            "byd_v1_3_recovery_event_low_vol_confirmation_v1"
        ),
        "runtime_state_embedded": False,
    }
    assert "fingerprint" not in monitoring
    assert "latest_signal_date" not in monitoring
    assert "delivery_status" not in monitoring


def test_active_preview_catalog_is_exact_active_strategy_set(tmp_path: Path) -> None:
    active = load_active_strategy_catalog(STRATEGIES)
    preview = _active_preview_root(tmp_path)
    catalog = _read(preview / "catalog.json")
    validate_catalog(catalog)

    assert catalog["channel"] == "preview"
    preview_ids = {row["model_version_id"] for row in catalog["records"]}
    assert preview_ids == set(active.active_model_version_ids)
    assert preview_ids == {
        "qqqi_qqq_tqqq_v4_3",
        US_X1_3,
        "cn_x1_1",
        BYD_V13,
    }
    assert "us_x1_2" not in preview_ids

    for row in catalog["records"]:
        manifest = _read(preview / row["manifest_path"])
        validate_manifest(manifest)
        assert manifest["publication_channel"] == "preview"
        assert manifest["publication_status"] == "ci_validated_preview"
        if row["model_version_id"] != US_X1_3:
            lineage = _read((preview / row["manifest_path"]).parent / "lineage.json")
            assert lineage["publication_origin"] == "governed_model_evidence"
            assert "source_contract" not in lineage
            assert "source_path" not in lineage
            assert "formal_model_backtest_1_0_0" not in json.dumps(lineage)


def test_sync_promotes_active_preview_set_deterministically(tmp_path: Path) -> None:
    preview = _active_preview_root(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    receipt_a = sync(SOURCE, first, native_root=preview, strategy_catalog=STRATEGIES)
    receipt_b = sync(SOURCE, second, native_root=preview, strategy_catalog=STRATEGIES)
    assert receipt_a == receipt_b

    files_a = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    files_b = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert files_a == files_b
    assert all((first / path).read_bytes() == (second / path).read_bytes() for path in files_a)

    catalog = _read(first / "catalog.json")
    validate_catalog(catalog)
    versions = {row["model_version_id"] for row in catalog["records"]}
    assert versions == set(receipt_a["active_model_version_ids"])
    assert versions == {
        "qqqi_qqq_tqqq_v4_3",
        US_X1_3,
        "cn_x1_1",
        BYD_V13,
    }
    assert receipt_a["status"] == "active_formal_bundle_v2_built"
    assert receipt_a["publication_input"] == "active_preview_bundle_v2"
    assert receipt_a["native_promoted_model_ids"] == list(
        load_active_strategy_catalog(STRATEGIES).active_model_version_ids
    )
    assert "source_built_model_ids" not in receipt_a
    assert "source_catalog_sha256" not in receipt_a
    assert "migration_receipt" not in receipt_a

    for row in catalog["records"]:
        run_dir = (first / row["manifest_path"]).parent
        manifest = _read(run_dir / "manifest.json")
        validate_manifest(manifest)
        assert manifest["publication_channel"] == "formal"
        assert manifest["publication_status"] == "accepted_formal_baseline"
        assert manifest["research_only"] is True
        assert manifest["trade_ready"] is False
        validate_formal_evidence_bundle(run_dir)
        if row["model_version_id"] != US_X1_3:
            lineage = _read(run_dir / "lineage.json")
            assert lineage["publication_origin"] == "governed_model_evidence"
            assert "source_contract" not in lineage
            assert "source_path" not in lineage

    freshness = _read(first / "freshness.json")
    assert freshness["required_models"] == list(
        load_active_strategy_catalog(STRATEGIES).active_model_version_ids
    )
    assert freshness["date_range_end_required_models"] == [US_X1_3, "cn_x1_1"]
    assert freshness["freshness_receipt_required_models"] == [US_X1_3, "cn_x1_1"]


def test_sync_fails_closed_when_preview_catalog_is_incomplete(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete"
    shutil.copytree(NATIVE, incomplete)
    output = tmp_path / "formal"

    try:
        sync(SOURCE, output, native_root=incomplete, strategy_catalog=STRATEGIES)
    except ValueError as exc:
        assert "must exactly match" in str(exc)
    else:
        raise AssertionError("incomplete active preview catalog was accepted")


def test_native_us_x1_3_formal_boundary_is_explicit(tmp_path: Path) -> None:
    preview = _active_preview_root(tmp_path)
    output = tmp_path / "formal"
    receipt = sync(SOURCE, output, native_root=preview, strategy_catalog=STRATEGIES)
    assert US_X1_3 in receipt["native_promoted_model_ids"]

    catalog = _read(output / "catalog.json")
    record = next(row for row in catalog["records"] if row["model_version_id"] == US_X1_3)
    run_dir = (output / record["manifest_path"]).parent
    summary = _read(run_dir / "summary.json")
    diagnostics = _read(run_dir / "diagnostics.json")
    lineage = _read(run_dir / "lineage.json")

    assert summary["baseline_status"] == "accepted_formal_baseline"
    assert summary["formal_acceptance_status"] == "accepted_by_explicit_user_direction"
    assert summary["trade_readiness_status"] == "prospective_gate_pending"
    assert summary["evidence_completeness"]["missing"] == []
    assert diagnostics["evidence_completeness"]["missing"] == []
    assert lineage["formal_baseline_superseded"] == "us_x1_2"
    assert lineage["prospective_gate_scope"] == "trade_readiness_only"
    assert lineage["prospective_gate_status"] == "pending"
    assert summary["research_only"] is True
    assert summary["trade_ready"] is False
    validate_formal_evidence_bundle(run_dir)


def test_byd_v1_3_complete_ledgers_enter_native_formal_bundle(tmp_path: Path) -> None:
    preview = _active_preview_root(tmp_path)
    output = tmp_path / "formal"
    sync(SOURCE, output, native_root=preview, strategy_catalog=STRATEGIES)
    catalog = _read(output / "catalog.json")
    byd = next(row for row in catalog["records"] if row["model_version_id"] == BYD_V13)
    manifest = _read(output / byd["manifest_path"])
    assert manifest["model_version_id"] == BYD_V13
    sections = {row["section_id"]: row for row in manifest["sections"]}
    for section_id in ("performance", "portfolio", "trades", "attribution", "lineage"):
        assert sections[section_id]["availability_status"] == "available"
    validate_formal_evidence_bundle((output / byd["manifest_path"]).parent)
