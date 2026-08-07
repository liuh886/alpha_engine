from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.byd_formal_publication_common import write_json
from scripts.promote_byd_v1_2_formal import _signal_monitoring
from scripts.sync_formal_bundle_v2 import FORMAL_MODEL_ADAPTERS, accepted_v1_models, sync
from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest

SOURCE = Path("data/research/formal_backtests")
BYD_V12 = "byd_v1_2_convex_momentum_budget_v1"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


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
    payload = _read(target)
    assert payload == {
        "episode_start": "2026-08-03T00:00:00",
        "count": 15,
        "relative_wealth": 0.0297,
    }


def test_live_signal_state_is_not_embedded_in_formal_package(tmp_path: Path) -> None:
    empty = tmp_path / "empty-ledger"
    populated = tmp_path / "populated-ledger"
    populated.mkdir()
    (populated / "latest.json").write_text(
        '{"model_id":"byd_v1_2_convex_momentum_budget_v1","fingerprint":"mutable"}\n',
        encoding="utf-8",
    )
    expected_empty = {
        "status": "separate_runtime_signal_ledger",
        "ledger": empty.as_posix(),
        "runtime_state_embedded": False,
    }
    expected_populated = {
        **expected_empty,
        "ledger": populated.as_posix(),
    }
    assert _signal_monitoring(empty) == expected_empty
    populated_monitoring = _signal_monitoring(populated)
    assert populated_monitoring == expected_populated
    assert set(populated_monitoring) == {
        "status",
        "ledger",
        "runtime_state_embedded",
    }
    assert "fingerprint" not in populated_monitoring
    assert "latest_signal_date" not in populated_monitoring
    assert "delivery_status" not in populated_monitoring


def test_current_formal_catalog_matches_supported_adapters() -> None:
    assert accepted_v1_models(SOURCE) == list(FORMAL_MODEL_ADAPTERS)
    assert list(FORMAL_MODEL_ADAPTERS) == [
        "qqqi_qqq_tqqq_v4_3",
        "us_x1_1",
        "cn_x1_1",
        BYD_V12,
    ]


def test_sync_projects_every_accepted_model_deterministically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    receipt_a = sync(SOURCE, first)
    receipt_b = sync(SOURCE, second)
    assert receipt_a == receipt_b

    files_a = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    files_b = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    assert files_a == files_b
    assert all((first / path).read_bytes() == (second / path).read_bytes() for path in files_a)

    catalog = _read(first / "catalog.json")
    validate_catalog(catalog)
    versions = {row["model_version_id"] for row in catalog["records"]}
    assert versions == set(FORMAL_MODEL_ADAPTERS)
    assert len(catalog["records"]) == len(FORMAL_MODEL_ADAPTERS)
    for row in catalog["records"]:
        manifest = _read(first / row["manifest_path"])
        validate_manifest(manifest)
        assert manifest["publication_status"] == "accepted_formal_baseline"
        assert manifest["research_only"] is True
        assert manifest["trade_ready"] is False

    source_freshness = _read(SOURCE / "freshness.json")
    projected_freshness = _read(first / "freshness.json")
    assert projected_freshness == source_freshness
    assert projected_freshness["cutoff_policy"] == "latest_completed_trading_session"
    assert receipt_a["source_freshness_sha256"] == receipt_a["formal_bundle_v2_freshness_sha256"]


def test_byd_v1_2_complete_ledgers_enter_bundle_v2(tmp_path: Path) -> None:
    output = tmp_path / "formal"
    sync(SOURCE, output)
    catalog = _read(output / "catalog.json")
    byd = next(
        row for row in catalog["records"]
        if row["model_version_id"] == BYD_V12
    )
    manifest_path = output / byd["manifest_path"]
    manifest = _read(manifest_path)
    assert manifest["model_version_id"] == BYD_V12
    sections = {row["section_id"]: row for row in manifest["sections"]}
    for section_id in ("performance", "portfolio", "trades", "attribution", "lineage"):
        assert sections[section_id]["availability_status"] == "available"
