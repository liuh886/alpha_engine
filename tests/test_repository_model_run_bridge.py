from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from scripts.check_repository_model_runs import (
    RepositoryModelRunError,
    validate_repository_model_runs,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-model-run-bridge.yml"
BRIDGE_RUNTIME_PATHS = {
    ".github/workflows/repository-model-run-bridge.yml",
    "scripts/check_repository_model_runs.py",
    "scripts/export_static_site_data.py",
    "src/artifacts/repository_metadata_cache.py",
    "src/artifacts/repository_research_store.py",
    "src/cli/main.py",
    "tests/test_repository_metadata_cache.py",
    "tests/test_repository_model_run_bridge.py",
    "tests/test_repository_research_store.py",
}


def _bridge_trigger_paths() -> tuple[set[str], set[str]]:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    return (
        set(triggers["pull_request"]["paths"]),
        set(triggers["push"]["paths"]),
    )


def test_named_models_bind_to_immutable_repository_runs() -> None:
    result = validate_repository_model_runs(ROOT)

    assert result["status"] == "repository_model_run_bridge_valid"
    assert result["model_count"] == 3
    assert result["published_run_count"] == 3
    assert {item["model_id"] for item in result["models"]} == {
        "us_x1_1",
        "us_x1_0",
        "cn_x1_0",
    }
    assert all(
        item["curve_status"]
        == "unavailable_source_artifact_did_not_retain_trace"
        for item in result["models"]
    )


def test_bridge_trigger_matches_repository_catalog_allow_list() -> None:
    pull_paths, push_paths = _bridge_trigger_paths()
    catalog = json.loads(
        (ROOT / "data" / "research" / "catalog.json").read_text(encoding="utf-8")
    )

    assert pull_paths == push_paths
    assert "data/research/**" not in pull_paths
    assert "configs/models/*.yaml" not in pull_paths
    assert BRIDGE_RUNTIME_PATHS <= pull_paths
    assert "data/research/catalog.json" in pull_paths
    assert "data/research/model_data_bundle_v1/**" in pull_paths

    for entry in catalog["published_models"]:
        source = str(entry["source"])
        assert source in pull_paths
        model = yaml.safe_load((ROOT / source).read_text(encoding="utf-8"))
        report = str((model.get("evidence_identity") or {}).get("result_report") or "")
        if report:
            assert report in pull_paths

    for entry in catalog["published_runs"]:
        source = str(entry["source"])
        assert f"{source}/**" in pull_paths


def test_historical_runs_do_not_fabricate_equity_curves() -> None:
    catalog = json.loads(
        (ROOT / "data" / "research" / "catalog.json").read_text(encoding="utf-8")
    )
    for entry in catalog["published_runs"]:
        run_dir = ROOT / entry["source"]
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert not (run_dir / "equity_curve.json").exists()
        curve = run["evidence_completeness"]["equity_curve"]
        assert curve["status"] == "unavailable_source_artifact_did_not_retain_trace"
        assert "No curve was inferred or reconstructed" in curve["reason"]


def test_validator_rejects_unacknowledged_missing_curve(tmp_path: Path) -> None:
    source = ROOT / "data" / "research"
    copied = tmp_path / "data" / "research"
    copied.mkdir(parents=True)
    shutil.copytree(source / "runs", copied / "runs")
    shutil.copy2(source / "catalog.json", copied / "catalog.json")
    (tmp_path / "configs" / "models").mkdir(parents=True)
    for name in ("us_x1_1.yaml", "us_x1_0.yaml", "cn_x1_0.yaml"):
        shutil.copy2(
            ROOT / "configs" / "models" / name,
            tmp_path / "configs" / "models" / name,
        )

    run_path = copied / "runs" / "us_x1_1-evidence-30737322468" / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["evidence_completeness"]["equity_curve"]["status"] = "unknown"
    run_path.write_text(json.dumps(run, separators=(",", ":")) + "\n", encoding="utf-8")

    inventory_path = run_path.parent / "inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    content = run_path.read_bytes()
    for record in inventory["files"]:
        if record["path"] == "run.json":
            record["byte_size"] = len(content)
            record["sha256"] = hashlib.sha256(content).hexdigest()
    inventory_path.write_text(
        json.dumps(inventory, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RepositoryModelRunError, match="missing curve is not explicitly governed"):
        validate_repository_model_runs(tmp_path)
