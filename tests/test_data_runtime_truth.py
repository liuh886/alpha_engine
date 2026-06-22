from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.update_data as update_data
from src.assistant.data_snapshot_index import DataSnapshotIndex
from src.assistant.services.data_service import DataService
from src.data.snapshot import DataSnapshot


def _provider(root: Path, value: bytes = b"provider") -> Path:
    provider = root / "provider"
    (provider / "features" / "AAPL").mkdir(parents=True)
    (provider / "features" / "AAPL" / "close.day.bin").write_bytes(value)
    (provider / "calendars").mkdir()
    (provider / "calendars" / "day.txt").write_text("2026-06-19\n", encoding="utf-8")
    return provider


def test_snapshot_index_round_trips_exact_verified_manifest(tmp_path: Path):
    snapshot = DataSnapshot.create_snapshot(
        _provider(tmp_path),
        store=tmp_path / "store",
        universe={"us": ["AAPL"]},
        calendar={"frequency": "day", "latest_day": "2026-06-19"},
        source_policy={"us": ["yfinance"]},
        adjustment_policy={"mode": "forward"},
        quality_policy={"coverage": 1.0},
    )
    index = DataSnapshotIndex(db_path=tmp_path / "metadata.db")

    index.upsert_manifest(snapshot.manifest, dataset_key="watchlist")
    indexed = index.get_latest_manifest(dataset_key="watchlist", freq="day")

    assert indexed is not None
    assert indexed["snapshot_id"] == snapshot.snapshot_id
    assert indexed["manifest"] == snapshot.manifest.to_dict()
    assert indexed["authoritative"] == 1


class _MissingIndex:
    def get_latest_manifest(self, **_: object) -> None:
        return None


class _FailingIndex:
    def get_latest_manifest(self, **_: object) -> None:
        raise RuntimeError("index unavailable")


class _MissingQuality:
    def get_latest(self, **_: object) -> None:
        return None


def test_data_status_does_not_default_missing_state_to_ok(tmp_path: Path):
    service = DataService(project_root=tmp_path, python_exe="python")

    status = service.get_data_status(
        tmp_path / "missing-dashboard.json", _MissingIndex(), _MissingQuality()
    )

    assert status["snapshot_status"] == "unknown"
    assert status["quality_status"] == "unknown"
    assert status["status"] == "unknown"


def test_data_status_reports_index_exception_as_failed(tmp_path: Path):
    service = DataService(project_root=tmp_path, python_exe="python")

    status = service.get_data_status(
        tmp_path / "missing-dashboard.json", _FailingIndex(), _MissingQuality()
    )

    assert status["snapshot_status"] == "failed"
    assert status["status"] == "failed"


class _SnapshotIndex:
    def get_latest_manifest(self, **_: object) -> dict:
        return {"snapshot_id": "snapshot-a", "manifest": {"snapshot_id": "snapshot-a"}}


class _MismatchedQuality:
    def get_latest(self, **_: object) -> dict:
        return {
            "snapshot_id": "snapshot-b",
            "summary": {"ok": True, "warnings": []},
        }


def test_data_status_rejects_quality_for_another_snapshot(tmp_path: Path):
    service = DataService(project_root=tmp_path, python_exe="python")

    status = service.get_data_status(
        tmp_path / "missing-dashboard.json", _SnapshotIndex(), _MismatchedQuality()
    )

    assert status["snapshot_status"] == "ready"
    assert status["quality_status"] == "failed"
    assert status["status"] == "failed"
    assert "snapshot mismatch" in status["quality_error"]


def _complete_accounting():
    accounting = update_data.UpdateAccounting(
        configured={"us": ["AAPL", "MSFT"], "cn": ["SH600000"]}
    )
    accounting.add("excluded", "cn", "SH600000")
    accounting.add("reused", "cn", "SH600000")
    accounting.add("attempted", "us", "AAPL")
    accounting.add("updated", "us", "AAPL")
    accounting.add("attempted", "us", "MSFT")
    accounting.add("reused", "us", "MSFT")
    return accounting


def _quality_report() -> dict:
    return {
        "ok": True,
        "latest_calendar_day": "2026-06-19",
        "warnings": [],
        "markets": {
            "us": {
                "instruments": 2,
                "stale_instruments": 0,
                "csv_missing": 0,
                "csv_parse_errors": 0,
                "csv_stale": 0,
            },
            "cn": {
                "instruments": 1,
                "stale_instruments": 0,
                "csv_missing": 0,
                "csv_parse_errors": 0,
                "csv_stale": 0,
            },
        },
    }


def test_update_accounting_tracks_every_required_symbol_state():
    accounting = _complete_accounting()

    accounting.validate_for_publish(selected_markets={"us"})
    summary = accounting.to_dict()

    assert summary["configured"]["us"] == ["AAPL", "MSFT"]
    assert summary["attempted"]["us"] == ["AAPL", "MSFT"]
    assert summary["updated"]["us"] == ["AAPL"]
    assert summary["reused"]["us"] == ["MSFT"]
    assert summary["excluded"]["cn"] == ["SH600000"]
    assert summary["failed"]["us"] == []
    assert summary["stale"]["us"] == []


def test_update_accounting_rejects_zero_and_partial_updates():
    zero = update_data.UpdateAccounting(configured={"us": ["AAPL"]})
    zero.add("attempted", "us", "AAPL")
    zero.add("reused", "us", "AAPL")
    with pytest.raises(update_data.DataUpdateFailure, match="zero symbols updated"):
        zero.validate_for_publish(selected_markets={"us"})

    partial = update_data.UpdateAccounting(configured={"us": ["AAPL", "MSFT"]})
    partial.add("attempted", "us", "AAPL")
    partial.add("updated", "us", "AAPL")
    partial.add("attempted", "us", "MSFT")
    partial.add("failed", "us", "MSFT", reason="provider unavailable")
    with pytest.raises(update_data.DataUpdateFailure, match="partial update"):
        partial.validate_for_publish(selected_markets={"us"})


def test_publish_provider_snapshot_indexes_exact_manifest_and_marker(tmp_path: Path):
    provider = _provider(tmp_path)
    store = tmp_path / "store"
    db_path = tmp_path / "metadata.db"
    marker = tmp_path / "latest.json"
    accounting = _complete_accounting()

    snapshot = update_data.publish_provider_snapshot(
        provider_dir=provider,
        snapshot_store=store,
        marker_path=marker,
        db_path=db_path,
        dataset_key="watchlist",
        universe=accounting.configured,
        selected_markets={"us"},
        source_policy={"us": ["yfinance"], "cn": ["baostock"]},
        adjustment_policy={"mode": "forward"},
        quality_policy={"coverage": 1.0, "allow_stale": False},
        quality_report=_quality_report(),
        accounting=accounting,
    )

    latest = DataSnapshot.get_latest_snapshot(store=store)
    indexed = DataSnapshotIndex(db_path=db_path).get_latest_manifest(
        dataset_key="watchlist", freq="day"
    )
    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    assert latest is not None and latest.snapshot_id == snapshot.snapshot_id
    assert indexed is not None and indexed["manifest"] == snapshot.manifest.to_dict()
    assert marker_payload["manifest"] == snapshot.manifest.to_dict()


def test_index_persistence_failure_never_moves_latest(tmp_path: Path, monkeypatch):
    store = tmp_path / "store"
    old = DataSnapshot.create_snapshot(_provider(tmp_path / "old", b"old"), store=store)
    DataSnapshot.publish_snapshot(old.snapshot_id, store=store)

    class _BrokenSnapshotIndex:
        def __init__(self, **_: object):
            pass

        def upsert_manifest(self, *_: object, **__: object) -> None:
            raise OSError("index write failed")

    monkeypatch.setattr(update_data, "DataSnapshotIndex", _BrokenSnapshotIndex)
    accounting = _complete_accounting()
    with pytest.raises(OSError, match="index write failed"):
        update_data.publish_provider_snapshot(
            provider_dir=_provider(tmp_path / "new", b"new"),
            snapshot_store=store,
            marker_path=tmp_path / "latest.json",
            db_path=tmp_path / "metadata.db",
            dataset_key="watchlist",
            universe=accounting.configured,
            selected_markets={"us"},
            source_policy={"us": ["yfinance"], "cn": ["baostock"]},
            adjustment_policy={"mode": "forward"},
            quality_policy={"coverage": 1.0, "allow_stale": False},
            quality_report=_quality_report(),
            accounting=accounting,
        )

    assert DataSnapshot.get_latest_snapshot(store=store).snapshot_id == old.snapshot_id


def _write_market_csv(path: Path, close: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,open,high,low,close,volume,amount,factor\n"
        f"2026-06-19,{close},{close},{close},{close},100,1000,1\n",
        encoding="utf-8",
    )


def test_build_provider_stage_contains_exact_configured_universe(tmp_path: Path):
    csv_stage = tmp_path / "csv"
    _write_market_csv(csv_stage / "AAPL.csv", 100)
    _write_market_csv(csv_stage / "SH600000.csv", 10)
    provider_stage = tmp_path / "provider"
    universe = {"us": ["AAPL"], "cn": ["SH600000"]}

    update_data.build_provider_stage(
        csv_stage=csv_stage,
        provider_stage=provider_stage,
        universe=universe,
    )

    assert (provider_stage / "features" / "AAPL" / "close.day.bin").exists()
    assert (provider_stage / "features" / "SH600000" / "close.day.bin").exists()
    assert (provider_stage / "instruments" / "us.txt").read_text().startswith("AAPL\t")
    assert (provider_stage / "instruments" / "cn.txt").read_text().startswith("SH600000\t")


def test_quality_persistence_failure_never_moves_latest(tmp_path: Path, monkeypatch):
    store = tmp_path / "store"
    old = DataSnapshot.create_snapshot(_provider(tmp_path / "old-quality", b"old"), store=store)
    DataSnapshot.publish_snapshot(old.snapshot_id, store=store)

    class _BrokenQualityIndex:
        def __init__(self, **_: object):
            pass

        def upsert(self, **_: object) -> None:
            raise OSError("quality write failed")

    monkeypatch.setattr(update_data, "DataQualityIndex", _BrokenQualityIndex)
    accounting = _complete_accounting()
    with pytest.raises(OSError, match="quality write failed"):
        update_data.publish_provider_snapshot(
            provider_dir=_provider(tmp_path / "new-quality", b"new"),
            snapshot_store=store,
            marker_path=tmp_path / "latest-quality.json",
            db_path=tmp_path / "quality.db",
            dataset_key="watchlist",
            universe=accounting.configured,
            selected_markets={"us"},
            source_policy={"us": ["yfinance"], "cn": ["baostock"]},
            adjustment_policy={"mode": "forward"},
            quality_policy={"coverage": 1.0, "allow_stale": False},
            quality_report=_quality_report(),
            accounting=accounting,
        )

    assert DataSnapshot.get_latest_snapshot(store=store).snapshot_id == old.snapshot_id


def test_cli_returns_nonzero_without_success_message_on_update_failure(monkeypatch, capsys):
    def _fail(_: object) -> None:
        raise update_data.DataUpdateFailure("zero symbols updated")

    monkeypatch.setattr(update_data, "run_data_update", _fail, raising=False)

    assert update_data.main([]) == 1
    output = capsys.readouterr().out
    assert "zero symbols updated" in output
    assert "Update Complete" not in output
    assert "published" not in output.lower()


def test_publish_provider_snapshot_resolves_to_actual_data_directory(tmp_path: Path):
    provider = _provider(tmp_path)
    store = tmp_path / "store"
    db_path = tmp_path / "metadata.db"
    marker = tmp_path / "latest.json"
    accounting = _complete_accounting()

    snapshot = update_data.publish_provider_snapshot(
        provider_dir=provider,
        snapshot_store=store,
        marker_path=marker,
        db_path=db_path,
        dataset_key="watchlist",
        universe=accounting.configured,
        selected_markets={"us"},
        source_policy={"us": ["yfinance"], "cn": ["baostock"]},
        adjustment_policy={"method": "none"},
        quality_policy={"max_stale_pct": 0.1, "max_csv_parse_errors": 0},
        quality_report=_quality_report(),
        accounting=accounting,
    )

    # provider_path must exist and contain the data files from the source.
    assert snapshot.provider_path.is_dir()
    assert (snapshot.provider_path / "features" / "AAPL" / "close.day.bin").exists()
    assert (snapshot.provider_path / "calendars" / "day.txt").exists()

    # Verify checksums via resolve (re-reads from disk and re-hashes).
    resolved = DataSnapshot.resolve_snapshot(snapshot.snapshot_id, store=store)
    assert resolved.provider_path == snapshot.provider_path


def test_publish_provider_snapshot_is_idempotent_for_identical_data(tmp_path: Path):
    provider = _provider(tmp_path)
    store = tmp_path / "store"
    db_path = tmp_path / "metadata.db"

    def _publish(accounting: update_data.UpdateAccounting) -> DataSnapshot:
        return update_data.publish_provider_snapshot(
            provider_dir=provider,
            snapshot_store=store,
            marker_path=tmp_path / "latest.json",
            db_path=db_path,
            dataset_key="watchlist",
            universe=accounting.configured,
            selected_markets={"us"},
            source_policy={"us": ["yfinance"], "cn": ["baostock"]},
            adjustment_policy={"method": "none"},
            quality_policy={"max_stale_pct": 0.1, "max_csv_parse_errors": 0},
            quality_report=_quality_report(),
            accounting=accounting,
        )

    snap_1 = _publish(_complete_accounting())
    snap_2 = _publish(_complete_accounting())

    assert snap_1.snapshot_id == snap_2.snapshot_id


def test_publish_provider_snapshot_different_data_yields_different_id(tmp_path: Path):
    store = tmp_path / "store"

    provider_a = _provider(tmp_path / "a", value=b"alpha-data")
    provider_b = _provider(tmp_path / "b", value=b"beta-data")

    # Quality report matching the 1-symbol universe used here.
    qr = {
        "ok": True,
        "latest_calendar_day": "2026-06-19",
        "warnings": [],
        "markets": {
            "us": {
                "instruments": 1,
                "stale_instruments": 0,
                "csv_missing": 0,
                "csv_parse_errors": 0,
                "csv_stale": 0,
            },
        },
    }
    acct = update_data.UpdateAccounting(configured={"us": ["AAPL"]})
    acct.add("attempted", "us", "AAPL")
    acct.add("updated", "us", "AAPL")

    def _publish(provider: Path, label: str) -> DataSnapshot:
        db = tmp_path / f"db_{label}.db"
        return update_data.publish_provider_snapshot(
            provider_dir=provider,
            snapshot_store=store,
            marker_path=tmp_path / f"latest_{label}.json",
            db_path=db,
            dataset_key="watchlist",
            universe={"us": ["AAPL"]},
            selected_markets={"us"},
            source_policy={"us": ["yfinance"]},
            adjustment_policy={"method": "none"},
            quality_policy={"max_stale_pct": 0.1, "max_csv_parse_errors": 0},
            quality_report=qr,
            accounting=acct,
        )

    snap_a = _publish(provider_a, "a")
    snap_b = _publish(provider_b, "b")

    assert snap_a.snapshot_id != snap_b.snapshot_id


def test_validate_for_publish_raises_when_symbols_unaccounted():
    accounting = update_data.UpdateAccounting(configured={"us": ["AAPL", "MSFT", "GOOG"]})
    accounting.add("attempted", "us", "AAPL")
    accounting.add("updated", "us", "AAPL")
    accounting.add("attempted", "us", "MSFT")
    accounting.add("updated", "us", "MSFT")
    # GOOG is configured but never attempted -- completely unaccounted.

    with pytest.raises(update_data.DataUpdateFailure, match="partial update"):
        accounting.validate_for_publish(selected_markets={"us"})


def test_partial_missing_below_threshold_warns_without_strict():
    # 2 out of 100 missing -> 2% missing_pct, count = 2.
    # threshold = 5%, count = 20
    configured = {"us": [f"SYM{i}" for i in range(100)]}
    accounting = update_data.UpdateAccounting(configured=configured)
    for i in range(100):
        accounting.add("attempted", "us", f"SYM{i}")
        if i < 98:
            accounting.add("updated", "us", f"SYM{i}")
        else:
            accounting.add("failed", "us", f"SYM{i}")

    # Should not raise, should return warnings
    warnings = accounting.validate_for_publish(
        selected_markets={"us"},
        strict=False,
        max_missing_pct=0.05,
        max_missing_count=20,
    )
    assert len(warnings) > 0
    assert "Partial update accepted" in warnings[0]


def test_partial_missing_below_threshold_fails_with_strict():
    # 2 out of 100 missing, exactly the same as above
    configured = {"us": [f"SYM{i}" for i in range(100)]}
    accounting = update_data.UpdateAccounting(configured=configured)
    for i in range(100):
        accounting.add("attempted", "us", f"SYM{i}")
        if i < 98:
            accounting.add("updated", "us", f"SYM{i}")
        else:
            accounting.add("failed", "us", f"SYM{i}")

    # strict=True should raise DataUpdateFailure unconditionally
    with pytest.raises(update_data.DataUpdateFailure, match="partial update failed.*strict=True"):
        accounting.validate_for_publish(
            selected_markets={"us"},
            strict=True,
            max_missing_pct=0.05,
            max_missing_count=20,
        )


def test_partial_missing_above_count_threshold_fails():
    # 25 missing out of 1000 -> 2.5% missing_pct, count = 25.
    # threshold = 5%, count = 20. Fails because 25 > 20.
    configured = {"us": [f"SYM{i}" for i in range(1000)]}
    accounting = update_data.UpdateAccounting(configured=configured)
    for i in range(1000):
        accounting.add("attempted", "us", f"SYM{i}")
        if i < 975:
            accounting.add("updated", "us", f"SYM{i}")
        else:
            accounting.add("failed", "us", f"SYM{i}")

    with pytest.raises(update_data.DataUpdateFailure, match="partial update failed.*max_count=20"):
        accounting.validate_for_publish(
            selected_markets={"us"},
            strict=False,
            max_missing_pct=0.05,
            max_missing_count=20,
        )
