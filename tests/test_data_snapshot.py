"""Tests for src.data.snapshot — immutable, content-addressed DataSnapshot."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.snapshot import DataSnapshot
from src.data.snapshot_manifest import SnapshotManifest

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _write_sample_data(root: Path, *, variant: str = "alpha") -> Path:
    """Create a small data tree under *root* and return the directory."""
    d = root / "data_src"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.csv").write_text("date,close\n2026-01-01,100.0\n", encoding="utf-8")
    (d / "b.csv").write_text(f"date,close\n2026-01-02,{200 if variant == 'alpha' else 999}\n", encoding="utf-8")
    sub = d / "sub"
    sub.mkdir(exist_ok=True)
    (sub / "c.csv").write_text(f"metric\n{variant}\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# test: different content → different snapshot ID
# ---------------------------------------------------------------------------


def test_different_content_yields_different_snapshot_id(tmp_path: Path):
    data_a = _write_sample_data(tmp_path / "a", variant="alpha")
    data_b = _write_sample_data(tmp_path / "b", variant="beta")

    store = tmp_path / "store"
    snap_a = DataSnapshot.create_snapshot(data_a, store=store)
    snap_b = DataSnapshot.create_snapshot(data_b, store=store)

    assert snap_a.snapshot_id != snap_b.snapshot_id


# ---------------------------------------------------------------------------
# test: same content → same snapshot ID
# ---------------------------------------------------------------------------


def test_same_content_yields_same_snapshot_id(tmp_path: Path):
    data_a = _write_sample_data(tmp_path / "a", variant="same")
    data_b = _write_sample_data(tmp_path / "b", variant="same")

    store = tmp_path / "store"
    snap_a = DataSnapshot.create_snapshot(data_a, store=store)
    snap_b = DataSnapshot.create_snapshot(data_b, store=store)

    assert snap_a.snapshot_id == snap_b.snapshot_id


# ---------------------------------------------------------------------------
# test: historical snapshots remain accessible
# ---------------------------------------------------------------------------


def test_historical_snapshots_remain_accessible(tmp_path: Path):
    data_v1 = _write_sample_data(tmp_path / "v1", variant="v1")
    data_v2 = _write_sample_data(tmp_path / "v2", variant="v2")
    store = tmp_path / "store"

    snap_v1 = DataSnapshot.create_snapshot(data_v1, store=store)
    snap_v2 = DataSnapshot.create_snapshot(data_v2, store=store)

    # Publish v2 as latest
    DataSnapshot.publish_snapshot(snap_v2.snapshot_id, store=store)

    # v1 is still accessible by id
    resolved = DataSnapshot.resolve_snapshot(snap_v1.snapshot_id, store=store)
    assert resolved.snapshot_id == snap_v1.snapshot_id
    assert resolved.manifest.content_hash == snap_v1.manifest.content_hash

    # latest returns v2
    latest = DataSnapshot.get_latest_snapshot(store=store)
    assert latest is not None
    assert latest.snapshot_id == snap_v2.snapshot_id


# ---------------------------------------------------------------------------
# test: quality failure prevents publish
# ---------------------------------------------------------------------------


def test_quality_failure_prevents_publish(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="bad")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(data, store=store, quality_verdict="fail")

    with pytest.raises(ValueError, match="quality_verdict"):
        DataSnapshot.publish_snapshot(snap.snapshot_id, store=store)

    # latest should remain absent
    assert DataSnapshot.get_latest_snapshot(store=store) is None


# ---------------------------------------------------------------------------
# test: publish is atomic (latest pointer updated)
# ---------------------------------------------------------------------------


def test_publish_updates_latest_pointer(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="ok")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(data, store=store, quality_verdict="pass")
    DataSnapshot.publish_snapshot(snap.snapshot_id, store=store)

    latest = DataSnapshot.get_latest_snapshot(store=store)
    assert latest is not None
    assert latest.snapshot_id == snap.snapshot_id


# ---------------------------------------------------------------------------
# test: manifest round-trips through JSON
# ---------------------------------------------------------------------------


def test_manifest_json_round_trip(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="json")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(
        data, store=store,
        source_adapter="yfinance",
        universe="sp500",
        date_range={"start": "2025-01-01", "end": "2026-01-01"},
    )

    # Read manifest from disk and round-trip
    manifest_path = store / "snapshots" / snap.snapshot_id / "manifest.json"
    text = manifest_path.read_text(encoding="utf-8")
    rebuilt = SnapshotManifest.from_json(text)

    assert rebuilt.snapshot_id == snap.snapshot_id
    assert rebuilt.source_adapter == "yfinance"
    assert rebuilt.universe == "sp500"
    assert rebuilt.date_range["start"] == "2025-01-01"


# ---------------------------------------------------------------------------
# test: file checksums are computed correctly
# ---------------------------------------------------------------------------


def test_file_checksums_match_actual_files(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="cksum")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(data, store=store)

    for rel_path, expected_hash in snap.manifest.file_checksums.items():
        staged = snap.file_path(rel_path)
        assert staged.exists(), f"staged file missing: {rel_path}"
        # re-hash and compare
        h = __import__("hashlib").sha256(staged.read_bytes()).hexdigest()
        assert h == expected_hash, f"checksum mismatch for {rel_path}"


# ---------------------------------------------------------------------------
# test: resolve nonexistent snapshot raises
# ---------------------------------------------------------------------------


def test_resolve_nonexistent_raises(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError):
        DataSnapshot.resolve_snapshot("deadbeef01234567", store=store)


# ---------------------------------------------------------------------------
# test: get_latest returns None when nothing published
# ---------------------------------------------------------------------------


def test_get_latest_returns_none_when_empty(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)

    assert DataSnapshot.get_latest_snapshot(store=store) is None


# ---------------------------------------------------------------------------
# test: list_files returns sorted relative paths
# ---------------------------------------------------------------------------


def test_list_files_returns_sorted_paths(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="list")
    store = tmp_path / "store"

    snap = DataSnapshot.create_snapshot(data, store=store)
    files = snap.list_files()

    assert files == sorted(files)
    assert any("a.csv" in f for f in files)
    assert any("c.csv" in f for f in files)


def _identity_metadata() -> dict:
    return {
        "schema_version": "qlib-v2",
        "universe": {"us": ["AAPL"], "cn": ["SH600000"]},
        "calendar": {"frequency": "day", "name": "exchange", "timezone": "UTC"},
        "source_policy": {"us": ["yfinance"], "cn": ["baostock"]},
        "adjustment_policy": {"mode": "forward", "factor_field": "factor"},
        "quality_policy": {"coverage": 1.0, "allow_stale": False},
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schema_version", "qlib-v3"),
        ("universe", {"us": ["MSFT"], "cn": ["SH600000"]}),
        ("calendar", {"frequency": "day", "name": "weekday", "timezone": "UTC"}),
        ("source_policy", {"us": ["stooq"], "cn": ["baostock"]}),
        ("adjustment_policy", {"mode": "none", "factor_field": "factor"}),
        ("quality_policy", {"coverage": 0.99, "allow_stale": False}),
    ],
)
def test_policy_metadata_is_part_of_snapshot_identity(
    tmp_path: Path, field: str, replacement: object
):
    data = _write_sample_data(tmp_path / "src", variant="identity")
    metadata = _identity_metadata()

    first = DataSnapshot.create_snapshot(data, store=tmp_path / "store", **metadata)
    metadata[field] = replacement
    second = DataSnapshot.create_snapshot(data, store=tmp_path / "store", **metadata)

    assert len(first.snapshot_id) == 64
    assert first.snapshot_id != second.snapshot_id


def test_empty_snapshot_is_rejected(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ValueError, match="empty snapshot"):
        DataSnapshot.create_snapshot(empty, store=tmp_path / "store")


def test_resolve_rejects_tampered_data_file(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="tamper-bytes")
    store = tmp_path / "store"
    snapshot = DataSnapshot.create_snapshot(data, store=store, **_identity_metadata())
    snapshot.file_path("a.csv").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        DataSnapshot.resolve_snapshot(snapshot.snapshot_id, store=store)


def test_resolve_rejects_tampered_manifest_identity(tmp_path: Path):
    data = _write_sample_data(tmp_path / "src", variant="tamper-manifest")
    store = tmp_path / "store"
    snapshot = DataSnapshot.create_snapshot(data, store=store, **_identity_metadata())
    manifest_path = store / "snapshots" / snapshot.snapshot_id / "manifest.json"
    payload = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_policy"] = {"us": ["tampered"]}
    manifest_path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest identity mismatch"):
        DataSnapshot.resolve_snapshot(snapshot.snapshot_id, store=store)


def test_publish_verifies_snapshot_before_moving_latest(tmp_path: Path):
    store = tmp_path / "store"
    first_data = _write_sample_data(tmp_path / "first", variant="first")
    second_data = _write_sample_data(tmp_path / "second", variant="second")
    first = DataSnapshot.create_snapshot(first_data, store=store, **_identity_metadata())
    second = DataSnapshot.create_snapshot(second_data, store=store, **_identity_metadata())
    DataSnapshot.publish_snapshot(first.snapshot_id, store=store)
    second.file_path("b.csv").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        DataSnapshot.publish_snapshot(second.snapshot_id, store=store)

    assert DataSnapshot.get_latest_snapshot(store=store).snapshot_id == first.snapshot_id
