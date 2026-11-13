from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.artifacts.derived_formal_excess import (
    DEFAULT_ARTIFACT_PATH,
    FormalExcessDerivationError,
    derive_formal_benchmark_excess,
    write_derived_formal_excess,
)
from src.artifacts.formal_bundle_reader import FormalBundleReadError, load_formal_run

MODEL_VERSION_ID = "qqqi_qqq_tqqq_v4_3"
EXPECTED_OBSERVATIONS = 699
EXPECTED_STRATEGY_RETURN = 0.9094666652401326
EXPECTED_BENCHMARK_RETURN = 0.6323106782547736
EXPECTED_EXCESS = 0.16979364938155483


def _artifact() -> dict:
    return json.loads(Path(DEFAULT_ARTIFACT_PATH).read_text(encoding="utf-8"))


def test_committed_artifact_recomputes_exactly_from_governed_bundle() -> None:
    committed = _artifact()
    recomputed = derive_formal_benchmark_excess(Path.cwd(), MODEL_VERSION_ID)
    assert committed == recomputed


def test_excess_value_and_window_are_the_declared_same_basis_metrics() -> None:
    artifact = _artifact()
    assert artifact["evidence_type"] == "derived_formal_benchmark_excess"
    assert artifact["benchmark"]["declared_identity"] == "QQQ"
    assert artifact["benchmark"]["comparability_id"] == "qqq"
    assert artifact["window"]["declared_start"] == "2024-01-30"
    assert artifact["window"]["declared_end"] == "2026-11-10"
    assert artifact["window"]["observed_start"] == "2024-01-30"
    assert artifact["window"]["observed_end"] == "2026-11-10"
    assert artifact["window"]["observation_count"] == EXPECTED_OBSERVATIONS
    assert artifact["result"] == {
        "strategy_cumulative_return": EXPECTED_STRATEGY_RETURN,
        "benchmark_cumulative_return": EXPECTED_BENCHMARK_RETURN,
        "excess_return": EXPECTED_EXCESS,
    }
    assert artifact["result"]["excess_return"] == (
        1.0 + EXPECTED_STRATEGY_RETURN
    ) / (1.0 + EXPECTED_BENCHMARK_RETURN) - 1.0
    assert artifact["reconciliation"]["summary_sample_count"] == EXPECTED_OBSERVATIONS
    assert artifact["reconciliation"]["total_return_absolute_difference"] == 0.0
    assert artifact["reconciliation"]["benchmark_return_absolute_difference"] == 0.0
    assert artifact["reconciliation"]["summary_excess_return_availability"] == "not_retained"
    assert artifact["boundaries"] == {
        "research_only": True,
        "trade_ready": False,
        "descriptive_historical_metric": True,
        "pit_certified": False,
        "live_signal": False,
        "sealed_formal_evidence_rewritten": False,
        "formal_catalog_modified": False,
        "source_registry_pins_modified": False,
    }


def test_every_input_hash_matches_the_file_and_the_sealed_manifest() -> None:
    repository = Path.cwd().resolve()
    artifact = _artifact()
    run = load_formal_run(repository, MODEL_VERSION_ID)
    declared = {
        row["section_id"]: row for row in run.manifest["sections"] if row.get("path")
    }

    inputs = {row["role"]: row for row in artifact["inputs"]}
    assert set(inputs) == {
        "formal_manifest",
        "formal_summary",
        "formal_performance",
        "formal_lineage",
    }

    manifest_input = inputs.pop("formal_manifest")
    assert manifest_input["role"] == "formal_manifest"
    manifest_bytes = (repository / manifest_input["path"]).read_bytes()
    assert manifest_input["sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest_input["bytes"] == len(manifest_bytes)
    assert manifest_input["sha256"] == artifact["strategy"]["manifest_sha256"]

    for section_id, row in inputs.items():
        section = section_id.removeprefix("formal_")
        assert row["path"] == (
            run.manifest_path.parent / declared[section]["path"]
        ).relative_to(repository).as_posix()
        body = (repository / row["path"]).read_bytes()
        assert row["sha256"] == hashlib.sha256(body).hexdigest()
        assert row["sha256"] == declared[section]["sha256"]
        assert row["bytes"] == declared[section]["byte_size"] == len(body)

    catalog = json.loads(
        (repository / "data/research/formal_model_runs/catalog.json").read_text(
            encoding="utf-8"
        )
    )
    record = next(
        item for item in catalog["records"] if item["model_version_id"] == MODEL_VERSION_ID
    )
    assert artifact["strategy"]["bundle_id"] == record["bundle_id"]
    assert artifact["strategy"]["manifest_sha256"] == record["manifest_sha256"]
    assert artifact["strategy"]["run_id"] == record["run_id"]


def test_convention_matches_retained_comparison_bundle_excess() -> None:
    """The two comparison strategies prove the compound-relative convention."""

    for model_version_id in ("us_x1_3", "cn_27_v1_3"):
        run = load_formal_run(Path.cwd(), model_version_id)
        summary = run.section("summary")
        metrics = {
            row["metric_id"]: row
            for row in summary["metrics"]
            if row.get("availability_status") == "available"
        }
        total = metrics["total_return"]["value"]
        benchmark = metrics["benchmark_return"]["value"]
        retained_excess = metrics["excess_return"]["value"]
        assert retained_excess == (1.0 + total) / (1.0 + benchmark) - 1.0


def test_writer_refuses_to_touch_sealed_formal_run_directories(tmp_path: Path) -> None:
    with pytest.raises(FormalExcessDerivationError, match="sealed formal run"):
        write_derived_formal_excess(
            _artifact(),
            "data/research/formal_model_runs/derived.json",
            repository_root=Path.cwd(),
        )


def test_derivation_fails_closed_when_a_sealed_section_changes(tmp_path: Path) -> None:
    source_root = Path("data/research/formal_model_runs")
    catalog = json.loads((source_root / "catalog.json").read_text(encoding="utf-8"))
    record = next(
        item for item in catalog["records"] if item["model_version_id"] == MODEL_VERSION_ID
    )
    run_relative = Path(record["manifest_path"]).parent
    target_root = tmp_path / "formal"
    shutil.copytree(source_root / run_relative, target_root / run_relative)
    mini_catalog = {key: value for key, value in catalog.items() if key != "records"}
    mini_catalog["records"] = [record]
    (target_root / "catalog.json").write_text(
        json.dumps(mini_catalog), encoding="utf-8"
    )

    performance = target_root / run_relative / "performance.json"
    performance.write_bytes(performance.read_bytes() + b" ")

    with pytest.raises(FormalBundleReadError, match="section digest mismatch: performance"):
        derive_formal_benchmark_excess(
            tmp_path, MODEL_VERSION_ID, relative_root=Path("formal")
        )


def test_artifact_path_is_outside_the_sealed_formal_store() -> None:
    path = Path(DEFAULT_ARTIFACT_PATH).resolve()
    sealed = (Path.cwd() / "data/research/formal_model_runs").resolve()
    with pytest.raises(ValueError):
        path.relative_to(sealed)
