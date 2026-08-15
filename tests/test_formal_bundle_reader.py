from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.artifacts.formal_bundle_reader import (
    FormalBundleReadError,
    FormalBundleReader,
    load_formal_run,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog


def test_every_active_formal_run_is_readable_from_bundle_v2() -> None:
    active = load_active_strategy_catalog()
    for strategy in active.strategies:
        run = load_formal_run(Path.cwd(), strategy.model_version_id)
        assert run.model_version_id == strategy.model_version_id
        assert run.manifest["publication_channel"] == "formal"
        assert run.manifest["publication_status"] == "accepted_formal_baseline"
        assert run.manifest["research_only"] is True
        assert run.manifest["trade_ready"] is False
        assert "formal_backtests" not in run.identity["manifest_path"]
        trace = run.replay_trace()
        assert trace["report"]
        assert trace["positions"]
        assert isinstance(trace["trades"], list)
        assert trace["portfolio_contract"]


def test_active_bundle_reader_exposes_digest_bound_identity() -> None:
    run = load_formal_run(Path.cwd(), "byd_v1_3_recovery_event_low_vol_confirmation_v1")
    identity = run.identity
    assert identity["bundle_id"] == run.manifest["bundle_id"]
    assert identity["evidence_cutoff"] == run.manifest["evidence_cutoff"]
    assert len(identity["manifest_sha256"]) == 64
    assert identity["manifest_path"].startswith("data/research/formal_model_runs/")


def test_catalog_scoped_reader_reuses_one_validated_run() -> None:
    reader = FormalBundleReader.open(Path.cwd())
    first = reader.load("us_x1_3")
    second = reader.load("us_x1_3")

    assert first is second
    assert set(reader.records) == set(load_active_strategy_catalog().active_model_version_ids)


def test_catalog_scoped_reader_enforces_section_byte_size(tmp_path: Path) -> None:
    source = Path("data/research/formal_model_runs")
    target = tmp_path / "formal"
    shutil.copytree(source, target)
    catalog_path = target / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    record = next(row for row in catalog["records"] if row["model_version_id"] == "us_x1_3")
    manifest_path = target / record["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    section = next(row for row in manifest["sections"] if row["section_id"] == "portfolio")
    section_path = manifest_path.parent / section["path"]
    section_path.write_bytes(section_path.read_bytes() + b" ")

    reader = FormalBundleReader.open(tmp_path, relative_root=Path("formal"))
    with pytest.raises(FormalBundleReadError, match="section digest mismatch: portfolio"):
        reader.load("us_x1_3")
