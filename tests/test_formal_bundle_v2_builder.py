from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.artifacts.formal_bundle_v2_builder import build_plan
from src.artifacts.model_run_bundle_v2 import validate_manifest
from src.artifacts.model_run_exporter import export_model_run
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID as BYD_V13

SOURCE = Path("data/research/formal_backtests")
STRATEGIES = Path("configs/strategies/registry.json")


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
    return row, payload


def test_source_backed_active_formals_export_without_recomputation(tmp_path: Path) -> None:
    active = load_active_strategy_catalog(STRATEGIES)
    source_catalog = _read(SOURCE / "catalog.json")
    source_ids = [row["model_id"] for row in source_catalog["records"]]
    assert source_ids == [
        "qqqi_qqq_tqqq_v4_3",
        "cn_x1_1",
        BYD_V13,
    ]

    for model_id in source_ids:
        strategy = active.by_model_version_id[model_id]
        source_path = SOURCE / f"{model_id}.json"
        source = _read(source_path)
        manifest_path = export_model_run(
            build_plan(source_path, strategy),
            output_root=tmp_path,
        )
        manifest = _read(manifest_path)
        validate_manifest(manifest)
        root = manifest_path.parent

        _, performance = _section(root, manifest, "performance")
        assert performance["report"] == source["report"]
        _, portfolio = _section(root, manifest, "portfolio")
        assert portfolio["positions"] == source["positions"]
        assert portfolio["portfolio_contract"] == source["portfolio_contract"]
        _, robustness = _section(root, manifest, "robustness")
        assert robustness["window_summary"] == source["window_summary"]
        _, lineage = _section(root, manifest, "lineage")
        assert lineage["source_contract"] == "formal_model_backtest_1_0_0"
        assert lineage["source_package_sha256"] == _sha(source_path)
        assert lineage["historical_evidence_recomputed"] is False
        assert lineage["model_selection_reopened"] is False
        assert "migration" not in json.dumps(lineage).lower()

        trades_row, trades = _section(root, manifest, "trades")
        if source["trades"]:
            assert trades_row["availability_status"] == "available"
            assert trades == source["trades"]
        else:
            assert trades_row["availability_status"] == "not_retained"
            assert trades is None

        decision = next(row for row in manifest["sections"] if row["section_id"] == "decision")
        assert decision["availability_status"] == "not_retained"


def test_builder_uses_retained_metric_labels_only(tmp_path: Path) -> None:
    active = load_active_strategy_catalog(STRATEGIES)
    for model_id in ("qqqi_qqq_tqqq_v4_3", "cn_x1_1", BYD_V13):
        manifest_path = export_model_run(
            build_plan(SOURCE / f"{model_id}.json", active.by_model_version_id[model_id]),
            output_root=tmp_path,
        )
        manifest = _read(manifest_path)
        _, summary = _section(manifest_path.parent, manifest, "summary")
        for metric in summary["metrics"]:
            if metric["availability_status"] == "available":
                assert str(metric["estimator"]).startswith("retained_formal_source:")
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


def test_byd_retained_benchmark_and_excess_metrics_are_available(tmp_path: Path) -> None:
    active = load_active_strategy_catalog(STRATEGIES)
    manifest_path = export_model_run(
        build_plan(SOURCE / f"{BYD_V13}.json", active.by_model_version_id[BYD_V13]),
        output_root=tmp_path,
    )
    manifest = _read(manifest_path)
    _, summary = _section(manifest_path.parent, manifest, "summary")
    metrics = {row["metric_id"]: row for row in summary["metrics"]}
    assert metrics["benchmark_return"]["availability_status"] == "available"
    assert metrics["excess_return"]["availability_status"] == "available"
