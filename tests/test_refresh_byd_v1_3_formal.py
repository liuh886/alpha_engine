from __future__ import annotations

import base64
import json
import tarfile
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from scripts.byd_formal_refresh_common import (
    BYDFormalRefreshError,
    extend_byd_input,
    preserve_verified_prefix,
)
from scripts.refresh_byd_v1_3_formal import refresh_byd_v1_3
from src.artifacts.formal_bundle_reader import load_formal_run
from src.research.byd_v1_2_recovery_state import (
    CANONICAL_EXTENDED_SCHEMA,
    file_sha256,
    load_canonical_snapshot,
    manifest_payload_sha256,
)
from src.research.byd_v1_3_low_vol_recovery import MODEL_ID


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _bundle_refresh_state(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    state = load_formal_run(Path.cwd(), MODEL_ID).refresh_state()
    state["schema_version"] = "1.0.0"
    state["record_type"] = "formal_model_backtest"
    state["publication_status"] = "accepted_formal_baseline"
    path = tmp_path / "current-byd.json"
    _write_json(path, state)
    return path, state


def test_byd_extension_normalizes_prospective_date_dtype(tmp_path: Path) -> None:
    base = tmp_path / "byd-base"
    shadow = tmp_path / "byd-shadow"
    output = tmp_path / "byd-output"
    base.mkdir()
    pd.DataFrame(
        [
            {
                "date": "2026-08-03",
                "open": 90.0,
                "high": 91.0,
                "low": 89.0,
                "close": 90.5,
                "volume": 1000.0,
            }
        ]
    ).to_csv(base / "adjusted_ohlcv.csv", index=False)
    pd.DataFrame([{"date": "2026-08-03", "open_research_eligible": True}]).to_csv(
        base / "session_audit.csv", index=False
    )
    _write_json(
        base / "manifest.json",
        {
            "schema_version": "test_v1",
            "adjusted_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "cutoff": "2026-08-03",
        },
    )
    _write_json(shadow / "manifest.json", {"last_signal_date": "2026-08-04"})
    _write_json(
        shadow / "observations" / "2026-08-04.json",
        {
            "signal_date": "2026-08-04",
            "open_research_eligible": True,
            "chain_linked_adjusted_ohlcv": {
                "open": 91.0,
                "high": 92.0,
                "low": 90.0,
                "close": 91.5,
                "volume": 1100.0,
            },
        },
    )

    manifest = extend_byd_input(
        base_dir=base,
        shadow_store=shadow,
        cutoff="2026-08-04",
        output_dir=output,
        validate_base=False,
    )

    adjusted = pd.read_csv(output / "adjusted_ohlcv.csv")
    sessions = pd.read_csv(output / "session_audit.csv")
    assert adjusted["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert sessions["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert manifest["cutoff"] == "2026-08-04"


def test_byd_production_archive_extends_under_verified_v2_contract(tmp_path: Path) -> None:
    base = tmp_path / "byd-base"
    output = tmp_path / "byd-output"
    base.mkdir()
    with tarfile.open("data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz") as archive:
        archive.extractall(base, filter="data")
    sealed_adjusted = (base / "adjusted_ohlcv.csv").read_bytes()
    sealed_sessions = (base / "session_audit.csv").read_bytes()

    manifest = extend_byd_input(
        base_dir=base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        cutoff="2026-08-10",
        output_dir=output,
    )
    loaded = load_canonical_snapshot(output)

    assert manifest["schema_version"] == CANONICAL_EXTENDED_SCHEMA
    assert loaded.manifest["cutoff"] == "2026-08-10"
    assert loaded.adjusted["date"].max() == pd.Timestamp("2026-08-10")
    assert (output / "adjusted_ohlcv.csv").read_bytes().startswith(sealed_adjusted)
    assert (output / "session_audit.csv").read_bytes().startswith(sealed_sessions)


def test_extended_loader_rejects_resealed_session_prefix_tampering(tmp_path: Path) -> None:
    base = tmp_path / "byd-base"
    output = tmp_path / "byd-output"
    base.mkdir()
    with tarfile.open("data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz") as archive:
        archive.extractall(base, filter="data")
    extend_byd_input(
        base_dir=base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        cutoff="2026-08-10",
        output_dir=output,
    )
    sessions = pd.read_csv(output / "session_audit.csv")
    sessions.loc[0, "open_research_eligible"] = False
    sessions.to_csv(output / "session_audit.csv", index=False)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_audit_sha256"] = file_sha256(output / "session_audit.csv")
    manifest["manifest_sha256"] = manifest_payload_sha256(manifest)
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="session history"):
        load_canonical_snapshot(output)


def test_prefix_preserves_accepted_float_representation() -> None:
    current = [{"date": "2026-01-07", "weight": 2.9820806175705164e-05}]
    replayed = [
        {"date": "2026-01-07", "weight": 2.9820806175705168e-05},
        {"date": "2026-01-08", "weight": 0.1},
    ]
    merged = preserve_verified_prefix("report", current, replayed)
    assert merged[0] == current[0]
    assert merged[1] == replayed[1]


def test_prefix_rejects_material_historical_drift() -> None:
    current = [{"date": "2026-01-07", "weight": 0.75}]
    replayed = [{"date": "2026-01-07", "weight": 0.70}]
    with pytest.raises(BYDFormalRefreshError, match="weight"):
        preserve_verified_prefix("positions", current, replayed)


def test_v1_3_formal_refresh_replays_bundle_v2_prefix_and_appends(tmp_path: Path) -> None:
    byd_base = tmp_path / "byd-base"
    etf_base = tmp_path / "etf-base"
    byd_base.mkdir()
    etf_base.mkdir()
    with tarfile.open("data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz") as archive:
        archive.extractall(byd_base, filter="data")
    encoded = Path("data/research/515180_canonical_v1_artifact.zip.b64").read_bytes()
    archive_path = tmp_path / "515180.zip"
    archive_path.write_bytes(base64.b64decode(encoded))
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(etf_base)

    current_package, current = _bundle_refresh_state(tmp_path)
    predecessor_package = Path(
        "data/research/historical_model_evidence/byd_v1_2_convex_momentum_budget_v1.json"
    )
    assert current["model_id"] == MODEL_ID
    cutoff = str(current["evidence_cutoff"])
    output = tmp_path / "byd-v1-3-formal.json"
    canonical_signal_ledger = Path(
        "data/research/strategy_signal_ledgers/"
        "byd_v1_3_recovery_event_low_vol_confirmation_v1"
    )
    result = refresh_byd_v1_3(
        current_package=current_package,
        predecessor_package=predecessor_package,
        base_byd_dir=byd_base,
        base_etf_dir=etf_base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        paired_store=Path("data/research/byd_515180_prospective"),
        signal_ledger=canonical_signal_ledger.resolve(),
        cutoff=cutoff,
        generated_at=f"{cutoff}T16:00:00Z",
        output=output,
    )

    package = json.loads(output.read_text(encoding="utf-8"))
    assert result["model_id"] == MODEL_ID
    assert result["appended_sessions"] >= 0
    assert package["evidence_cutoff"] == cutoff
    assert package["freshness"]["required_cutoff"] == cutoff
    assert package["freshness"]["latest_completed_session"] == cutoff
    assert package["freshness"]["model_selection_reopened"] is False
    assert package["freshness"]["monitoring_source"] == canonical_signal_ledger.as_posix()
    assert package["operational_monitoring"] == {
        "status": "separate_runtime_signal_ledger",
        "ledger": canonical_signal_ledger.as_posix(),
        "runtime_state_embedded": False,
    }
    assert package["evidence"]["refresh_adapter"] == "refresh_byd_v1_3_formal"
    assert package["research_only"] is True
    assert package["trade_ready"] is False
    assert package["report"][: len(current["report"])] == current["report"]
    assert package["positions"][: len(current["positions"])] == current["positions"]
    assert package["trades"][: len(current["trades"])] == current["trades"]
