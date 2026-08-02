from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.check_repository_model_runs import (
    RepositoryModelRunError,
    validate_repository_model_runs,
)

ROOT = Path(__file__).resolve().parents[1]


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
