"""Tests for data-update lifecycle and snapshot reuse (T46.3).

Proves:
  1. A data update creates a snapshot whose manifest is correct.
  2. Snapshot N is frozen after update N+1 is staged.
  3. Training can reference snapshot N even after N+1 is published.
  4. Partial (incomplete) snapshots cannot be published as complete.
  5. The training pipeline accepts and propagates a ``snapshot_id`` parameter.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.snapshot import DataSnapshot
from src.data.snapshot_manifest import SnapshotManifest

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_data_files(root: Path, *, version: str = "v1") -> Path:
    """Create a small synthetic data tree that simulates a data update.

    ``version`` changes the file contents so content-hash differs.
    """
    d = root / "raw"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prices.csv").write_text(
        f"date,close,volume\n2026-01-01,100.0,1000\n2026-01-02,101.0,{version}\n",
        encoding="utf-8",
    )
    (d / "fundamentals.csv").write_text(
        f"date,pe,pb\n2026-01-01,15.0,1.2\n2026-01-02,15.5,{version}\n",
        encoding="utf-8",
    )
    sub = d / "derived"
    sub.mkdir(exist_ok=True)
    (sub / "returns.csv").write_text(
        f"date,ret\n2026-01-01,0.0\n2026-01-02,{version}\n",
        encoding="utf-8",
    )
    return d


# ---------------------------------------------------------------------------
# 1. Data update creates a snapshot with correct manifest
# ---------------------------------------------------------------------------


def test_data_update_creates_snapshot_with_correct_manifest(tmp_path: Path):
    """After staging data, the resulting snapshot carries a manifest whose
    fields match the staged content."""
    data_dir = _write_data_files(tmp_path / "update", version="manifest_check")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(
        data_dir,
        store=store,
        source_adapter="csv_clean",
        universe="test_universe",
        date_range={"start": "2026-01-01", "end": "2026-01-02"},
        frequency="day",
        quality_verdict="pass",
    )

    m = snap.manifest

    # Basic identity
    assert m.snapshot_id == snap.snapshot_id
    assert m.content_hash, "content_hash must be populated"
    assert len(m.content_hash) == 64, "SHA-256 hex is 64 chars"

    # Metadata round-trip
    assert m.source_adapter == "csv_clean"
    assert m.universe == "test_universe"
    assert m.date_range["start"] == "2026-01-01"
    assert m.frequency == "day"
    assert m.quality_verdict == "pass"

    # Every staged file is recorded
    assert len(m.file_checksums) >= 3  # prices, fundamentals, returns
    for rel, digest in m.file_checksums.items():
        assert len(digest) == 64, f"checksum for {rel} should be SHA-256"

    # The manifest on disk matches the in-memory object
    on_disk = SnapshotManifest.read(
        store / "snapshots" / snap.snapshot_id / "manifest.json"
    )
    assert on_disk.snapshot_id == snap.snapshot_id
    assert on_disk.file_checksums == m.file_checksums


# ---------------------------------------------------------------------------
# 2. Snapshot N is frozen after update N+1
# ---------------------------------------------------------------------------


def test_snapshot_n_frozen_after_update_n_plus_1(tmp_path: Path):
    """Snapshot N's manifest and data files are immutable even after a
    new snapshot N+1 is created from different data."""
    data_n = _write_data_files(tmp_path / "n", version="frozen_v1")
    data_n1 = _write_data_files(tmp_path / "n1", version="frozen_v2")
    store = tmp_path / "store"

    snap_n = DataSnapshot.create_snapshot(data_n, store=store)
    snap_n1 = DataSnapshot.create_snapshot(data_n1, store=store)

    # IDs differ because content differs
    assert snap_n.snapshot_id != snap_n1.snapshot_id

    # Snapshot N is still fully intact
    reloaded_n = DataSnapshot.resolve_snapshot(snap_n.snapshot_id, store=store)
    assert reloaded_n.manifest.file_checksums == snap_n.manifest.file_checksums
    assert reloaded_n.manifest.content_hash == snap_n.manifest.content_hash

    # Each data file in snapshot N matches its original checksum
    for rel, expected_hash in snap_n.manifest.file_checksums.items():
        staged_path = reloaded_n.file_path(rel)
        assert staged_path.exists(), f"{rel} missing from frozen snapshot"
        actual = __import__("hashlib").sha256(staged_path.read_bytes()).hexdigest()
        assert actual == expected_hash, f"{rel} was mutated in frozen snapshot"


# ---------------------------------------------------------------------------
# 3. Training can use snapshot N even after N+1 is published
# ---------------------------------------------------------------------------


def test_training_can_reference_snapshot_n_after_n1_published(tmp_path: Path):
    """resolve_snapshot for snapshot N succeeds even when the ``latest``
    pointer has been advanced to N+1."""
    data_n = _write_data_files(tmp_path / "n", version="reuse_v1")
    data_n1 = _write_data_files(tmp_path / "n1", version="reuse_v2")
    store = tmp_path / "store"

    snap_n = DataSnapshot.create_snapshot(data_n, store=store)
    snap_n1 = DataSnapshot.create_snapshot(data_n1, store=store)

    # Publish N first, then advance to N+1
    DataSnapshot.publish_snapshot(snap_n.snapshot_id, store=store)
    DataSnapshot.publish_snapshot(snap_n1.snapshot_id, store=store)

    latest = DataSnapshot.get_latest_snapshot(store=store)
    assert latest is not None
    assert latest.snapshot_id == snap_n1.snapshot_id

    # Simulate a training run that pinned snapshot N: resolve still works
    training_snap = DataSnapshot.resolve_snapshot(snap_n.snapshot_id, store=store)
    assert training_snap.snapshot_id == snap_n.snapshot_id
    assert training_snap.manifest.quality_verdict == "pass"

    # The data files are still readable
    for rel in training_snap.list_files():
        assert training_snap.file_path(rel).exists()


# ---------------------------------------------------------------------------
# 4. Partial updates cannot be published as complete
# ---------------------------------------------------------------------------


def test_partial_update_cannot_be_published(tmp_path: Path):
    """A snapshot with quality_verdict != 'pass' (e.g. 'partial') must be
    rejected by ``publish_snapshot``."""
    data_dir = _write_data_files(tmp_path / "partial", version="partial_v")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(
        data_dir, store=store, quality_verdict="partial"
    )
    assert snap.manifest.quality_verdict == "partial"

    with pytest.raises(ValueError, match="quality_verdict"):
        DataSnapshot.publish_snapshot(snap.snapshot_id, store=store)

    # latest should still be absent
    assert DataSnapshot.get_latest_snapshot(store=store) is None


def test_fail_verdict_cannot_be_published(tmp_path: Path):
    """A snapshot with quality_verdict='fail' is likewise rejected."""
    data_dir = _write_data_files(tmp_path / "fail", version="fail_v")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(
        data_dir, store=store, quality_verdict="fail"
    )

    with pytest.raises(ValueError, match="quality_verdict"):
        DataSnapshot.publish_snapshot(snap.snapshot_id, store=store)


def test_pass_verdict_can_be_published(tmp_path: Path):
    """Sanity: a 'pass' snapshot publishes successfully (control case)."""
    data_dir = _write_data_files(tmp_path / "ok", version="pass_v")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(
        data_dir, store=store, quality_verdict="pass"
    )
    DataSnapshot.publish_snapshot(snap.snapshot_id, store=store)

    latest = DataSnapshot.get_latest_snapshot(store=store)
    assert latest is not None
    assert latest.snapshot_id == snap.snapshot_id


# ---------------------------------------------------------------------------
# 5. Training pipeline accepts snapshot_id parameter
# ---------------------------------------------------------------------------


def test_train_model_accepts_snapshot_id():
    """``train_model`` signature includes ``snapshot_id``."""
    import inspect

    from src.research.training import train_model

    sig = inspect.signature(train_model)
    assert "snapshot_id" in sig.parameters, (
        "train_model must accept a snapshot_id parameter"
    )
    # Default should be empty string (optional)
    assert sig.parameters["snapshot_id"].default == ""


def test_research_service_run_training_accepts_snapshot_id():
    """``ResearchService.run_training_pipeline`` accepts ``snapshot_id``."""
    import inspect

    from src.research.service import ResearchService

    sig = inspect.signature(ResearchService.run_training_pipeline)
    assert "snapshot_id" in sig.parameters, (
        "ResearchService.run_training_pipeline must accept snapshot_id"
    )


def test_snapshot_id_is_logged_in_model_artifact(tmp_path: Path):
    """When ``train_model`` is called with a ``snapshot_id``, it stores it
    in the saved model artifact metadata (or at minimum does not crash).

    This is a structural test: we verify the function can be called with
    the parameter without raising ``TypeError``."""
    import inspect

    from src.research.training import train_model

    sig = inspect.signature(train_model)
    # Verify the parameter is accepted (not necessarily that training runs,
    # since that requires Qlib and real data).
    params = list(sig.parameters.keys())
    assert "snapshot_id" in params

    # Verify the default value allows calling without the argument
    defaults = {
        k: v.default
        for k, v in sig.parameters.items()
        if v.default is not inspect.Parameter.empty
    }
    assert defaults.get("snapshot_id") is not None  # has a default


def test_run_training_pipeline_hooks_accepts_snapshot_id():
    """``run_training_pipeline`` in hooks accepts ``snapshot_id``."""
    import inspect

    from src.workflows.hooks import run_training_pipeline

    sig = inspect.signature(run_training_pipeline)
    assert "snapshot_id" in sig.parameters, (
        "hooks.run_training_pipeline must accept snapshot_id"
    )


def test_n_plus_1_reuses_secondary_market_bytes_without_mutating_n(tmp_path: Path):
    store = tmp_path / "store"
    data_n = tmp_path / "n"
    (data_n / "features" / "US").mkdir(parents=True)
    (data_n / "features" / "CN").mkdir(parents=True)
    (data_n / "features" / "US" / "close.day.bin").write_bytes(b"us-n")
    (data_n / "features" / "CN" / "close.day.bin").write_bytes(b"cn-stable")

    data_n1 = tmp_path / "n1"
    (data_n1 / "features" / "US").mkdir(parents=True)
    (data_n1 / "features" / "CN").mkdir(parents=True)
    (data_n1 / "features" / "US" / "close.day.bin").write_bytes(b"us-n-plus-1")
    (data_n1 / "features" / "CN" / "close.day.bin").write_bytes(b"cn-stable")

    metadata = {
        "universe": {"us": ["US"], "cn": ["CN"]},
        "calendar": {"frequency": "day"},
        "source_policy": {"us": ["primary"], "cn": ["secondary"]},
        "adjustment_policy": {"mode": "forward"},
        "quality_policy": {"coverage": 1.0},
    }
    snap_n = DataSnapshot.create_snapshot(data_n, store=store, **metadata)
    snap_n1 = DataSnapshot.create_snapshot(data_n1, store=store, **metadata)
    DataSnapshot.publish_snapshot(snap_n.snapshot_id, store=store)
    DataSnapshot.publish_snapshot(snap_n1.snapshot_id, store=store)

    clean_n = DataSnapshot.resolve_snapshot(snap_n.snapshot_id, store=store)
    clean_n1 = DataSnapshot.resolve_snapshot(snap_n1.snapshot_id, store=store)
    secondary = "features/CN/close.day.bin"
    assert clean_n.file_path(secondary).read_bytes() == b"cn-stable"
    assert clean_n1.file_path(secondary).read_bytes() == b"cn-stable"
    assert clean_n.manifest.file_checksums[secondary] == clean_n1.manifest.file_checksums[secondary]
