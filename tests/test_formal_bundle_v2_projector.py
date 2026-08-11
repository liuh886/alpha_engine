from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.artifacts.formal_bundle_v2_projector import (
    MODEL_MAP,
    project_formal_bundle_v2,
)
from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID as BYD_V13

SOURCE = Path("data/research/formal_backtests")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _section(root: Path, manifest: dict, section_id: str):
    row = next(value for value in manifest["sections"] if value["section_id"] == section_id)
    if row["availability_status"] != "available":
        return row, None
    payload = _read(root / row["path"])
    assert _sha(root / row["path"]) == row["sha256"]
    assert (root / row["path"]).stat().st_size == row["byte_size"]
    return row, payload


def test_migration_preserves_current_accepted_evidence(tmp_path: Path) -> None:
    output = tmp_path / "formal_model_runs"
    receipt = project_formal_bundle_v2(SOURCE, output)
    catalog = _read(output / "catalog.json")
    validate_catalog(catalog)
    assert catalog["channel"] == "formal"
    assert catalog["research_only"] is True
    assert catalog["trade_ready"] is False
    assert len(catalog["records"]) == 4
    assert receipt["status"] == "formal_v1_migrated_byte_preserving"

    v1_catalog = _read(SOURCE / "catalog.json")
    v1_paths = {
        row["model_id"]: SOURCE / row["path"]
        for row in v1_catalog["records"]
        if row["model_id"] in MODEL_MAP
    }
    assert set(v1_paths) == set(MODEL_MAP)
    for record in catalog["records"]:
        manifest_path = output / record["manifest_path"]
        manifest = _read(manifest_path)
        validate_manifest(manifest)
        assert manifest["publication_status"] == "accepted_formal_baseline"
        assert _sha(manifest_path) == record["manifest_sha256"]
        model_id = manifest["model_version_id"]
        source = _read(v1_paths[model_id])
        bundle_root = manifest_path.parent

        _, performance = _section(bundle_root, manifest, "performance")
        assert performance["report"] == source["report"]
        _, portfolio = _section(bundle_root, manifest, "portfolio")
        assert portfolio["positions"] == source["positions"]
        assert portfolio["portfolio_contract"] == source["portfolio_contract"]
        _, robustness = _section(bundle_root, manifest, "robustness")
        assert robustness["window_summary"] == source["window_summary"]
        _, lineage = _section(bundle_root, manifest, "lineage")
        assert lineage["source_package_sha256"] == _sha(v1_paths[model_id])
        assert lineage["historical_evidence_recomputed"] is False
        assert lineage["model_selection_reopened"] is False

        trades_row, trades = _section(bundle_root, manifest, "trades")
        attribution_row, attribution = _section(bundle_root, manifest, "attribution")
        if source["trades"]:
            assert trades_row["availability_status"] == "available"
            assert trades == source["trades"]
        else:
            assert trades_row["availability_status"] == "not_retained"
            assert trades is None
        if source["attribution"]:
            assert attribution_row["availability_status"] == "available"
            assert attribution == source["attribution"]
        else:
            assert attribution_row["availability_status"] == "not_retained"
            assert attribution is None


def test_migration_is_deterministic_and_does_not_synthesize_decisions(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    receipt_a = project_formal_bundle_v2(SOURCE, first)
    receipt_b = project_formal_bundle_v2(SOURCE, second)
    files_a = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    files_b = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert files_a == files_b
    assert all((first / path).read_bytes() == (second / path).read_bytes() for path in files_a)
    assert receipt_a == receipt_b

    catalog = _read(first / "catalog.json")
    for record in catalog["records"]:
        manifest = _read(first / record["manifest_path"])
        declarations = {row["section_id"]: row for row in manifest["sections"]}
        assert declarations["decision"]["availability_status"] == "not_retained"


def test_byd_v1_3_retained_benchmark_and_excess_metrics_are_projected(tmp_path: Path) -> None:
    output = tmp_path / "formal"
    project_formal_bundle_v2(SOURCE, output)
    catalog = _read(output / "catalog.json")
    byd = next(row for row in catalog["records"] if row["model_version_id"] == BYD_V13)
    manifest_path = output / byd["manifest_path"]
    manifest = _read(manifest_path)
    _, summary = _section(manifest_path.parent, manifest, "summary")
    metrics = {row["metric_id"]: row for row in summary["metrics"]}
    assert metrics["benchmark_return"]["availability_status"] == "available"
    assert metrics["excess_return"]["availability_status"] == "available"


def test_summary_aliases_without_recomputation(tmp_path: Path) -> None:
    output = tmp_path / "formal"
    project_formal_bundle_v2(SOURCE, output)
    catalog = _read(output / "catalog.json")
    for record in catalog["records"]:
        manifest_path = output / record["manifest_path"]
        manifest = _read(manifest_path)
        _, summary = _section(manifest_path.parent, manifest, "summary")
        assert summary["source_package_sha256"]
        for metric in summary["metrics"]:
            if metric["availability_status"] == "available":
                assert str(metric["estimator"]).startswith("retained_v1_label:")
                assert metric["unavailable_reason"] is None
            else:
                assert metric["value"] is None
                assert metric["unavailable_reason"]
        if manifest["model_kind"] == "rules_based_allocation":
            cross_sectional = {
                metric["metric_id"]: metric["availability_status"]
                for metric in summary["metrics"]
                if metric["metric_id"] in {"ic", "rank_ic", "icir"}
            }
            assert set(cross_sectional.values()) == {"not_applicable"}
