from __future__ import annotations

import json
from pathlib import Path

from src.data.provider_evidence import (
    build_universe_evidence,
    provider_attempts_evidence,
    read_effective_provider_universe,
)
from src.data.snapshot import DataSnapshot


def _write_provider(provider: Path) -> None:
    (provider / "calendars").mkdir(parents=True)
    (provider / "instruments").mkdir(parents=True)
    (provider / "features" / "aapl").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text(
        "2026-01-05\n2026-01-06\n",
        encoding="utf-8",
    )
    (provider / "instruments" / "us.txt").write_text(
        "AAPL\t2026-01-05\t2026-01-06\n",
        encoding="utf-8",
    )
    (provider / "features" / "aapl" / "close.day.bin").write_bytes(b"provider")


def test_partial_universe_evidence_separates_configured_and_effective(
    tmp_path: Path,
) -> None:
    provider = tmp_path / "provider"
    _write_provider(provider)

    effective = read_effective_provider_universe(provider, {"us"})
    evidence = build_universe_evidence(
        configured={"us": ["AAPL", "MSFT"]},
        effective=effective,
    )

    assert evidence["configured"]["us"] == ["AAPL", "MSFT"]
    assert evidence["effective"]["us"] == ["AAPL"]
    assert evidence["missing"]["us"] == ["MSFT"]
    assert evidence["extra"]["us"] == []
    assert len(evidence["configured_sha256"]) == 64
    assert len(evidence["effective_sha256"]) == 64
    assert evidence["configured_sha256"] != evidence["effective_sha256"]


def test_warning_snapshot_can_publish_without_claiming_full_coverage(
    tmp_path: Path,
) -> None:
    provider = tmp_path / "provider"
    store = tmp_path / "store"
    _write_provider(provider)
    universe = build_universe_evidence(
        configured={"us": ["AAPL", "MSFT"]},
        effective={"us": ["AAPL"]},
    )

    snapshot = DataSnapshot.create_snapshot(
        provider,
        store=store,
        universe=universe,
        quality_report={"warnings": ["partial provider"]},
        update_summary={"failed": {"us": ["MSFT"]}},
        quality_verdict="pass_with_warnings",
    )
    DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=store)

    latest = DataSnapshot.get_latest_snapshot(store=store)
    assert latest is not None
    assert latest.snapshot_id == snapshot.snapshot_id
    assert latest.manifest.quality_verdict == "pass_with_warnings"
    assert latest.manifest.universe["missing"]["us"] == ["MSFT"]


def test_provider_attempt_file_hash_is_bound_as_evidence(tmp_path: Path) -> None:
    path = tmp_path / "provider_attempts.json"
    path.write_text(
        json.dumps({"symbols": [{"symbol": "000300", "attempts": []}]}),
        encoding="utf-8",
    )

    evidence = provider_attempts_evidence(path)

    assert evidence["present"] is True
    assert evidence["path"] == str(path.resolve())
    assert len(evidence["sha256"]) == 64
