from __future__ import annotations

import base64
import json
import tarfile
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from scripts.refresh_allocation_formal import (
    AllocationRefreshError,
    _extend_byd_input,
    _extend_etf_input,
    _increment_qqq_attribution,
    _preserve_verified_byd_prefix,
    _qqq_metrics_from_report,
    _verify_qqq_decision_overlap,
    refresh_byd,
)
from src.research.byd_v1_2_recovery_state import (
    CANONICAL_EXTENDED_SCHEMA,
    file_sha256,
    load_canonical_snapshot,
    manifest_payload_sha256,
)


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "position_state": [1, 1],
            "decision_state": [1, 2],
            "position_label": ["attack", "attack"],
            "decision_reason": ["hold", "enter_leverage"],
            "executed_reason": ["enter_attack", "hold"],
            "weight_QQQI": [0.5, 0.5],
            "weight_QQQ": [0.5, 0.5],
            "weight_TQQQ": [0.0, 0.0],
            "QQQI_next_open_return": [0.01, 0.02],
            "QQQ_next_open_return": [0.02, 0.01],
            "TQQQ_next_open_return": [0.03, 0.02],
            "transaction_cost": [0.0, 0.001],
        },
        index=pd.to_datetime(["2026-07-30", "2026-07-31"]),
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


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
    pd.DataFrame(
        [{"date": "2026-08-03", "open_research_eligible": True}]
    ).to_csv(base / "session_audit.csv", index=False)
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

    manifest = _extend_byd_input(
        base_dir=base,
        shadow_store=shadow,
        cutoff="2026-08-04",
        output_dir=output,
        _validate_base=False,
    )

    adjusted = pd.read_csv(output / "adjusted_ohlcv.csv")
    sessions = pd.read_csv(output / "session_audit.csv")
    assert adjusted["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert sessions["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert manifest["cutoff"] == "2026-08-04"


def test_byd_production_archive_migrates_to_verified_append_only_v2(
    tmp_path: Path,
) -> None:
    base = tmp_path / "byd-base"
    output = tmp_path / "byd-output"
    base.mkdir()
    with tarfile.open(
        "data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz"
    ) as archive:
        archive.extractall(base, filter="data")
    sealed_adjusted = (base / "adjusted_ohlcv.csv").read_bytes()
    sealed_sessions = (base / "session_audit.csv").read_bytes()

    manifest = _extend_byd_input(
        base_dir=base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        cutoff="2026-08-07",
        output_dir=output,
    )
    loaded = load_canonical_snapshot(output)

    assert manifest["schema_version"] == CANONICAL_EXTENDED_SCHEMA
    assert loaded.manifest["cutoff"] == "2026-08-07"
    assert loaded.adjusted["date"].max() == pd.Timestamp("2026-08-07")
    assert (output / "adjusted_ohlcv.csv").read_bytes().startswith(sealed_adjusted)
    assert (output / "session_audit.csv").read_bytes().startswith(sealed_sessions)


def test_byd_extended_loader_rejects_payload_tampering(tmp_path: Path) -> None:
    base = tmp_path / "byd-base"
    output = tmp_path / "byd-output"
    base.mkdir()
    with tarfile.open(
        "data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz"
    ) as archive:
        archive.extractall(base, filter="data")
    _extend_byd_input(
        base_dir=base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        cutoff="2026-08-07",
        output_dir=output,
    )
    with (output / "adjusted_ohlcv.csv").open("a", encoding="utf-8") as handle:
        handle.write("2026-08-08,1,1,1,1,,,,,1\n")

    with pytest.raises(RuntimeError, match="adjusted_sha256"):
        load_canonical_snapshot(output)


def test_byd_extended_loader_rejects_resealed_session_prefix_tampering(
    tmp_path: Path,
) -> None:
    base = tmp_path / "byd-base"
    output = tmp_path / "byd-output"
    base.mkdir()
    with tarfile.open(
        "data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz"
    ) as archive:
        archive.extractall(base, filter="data")
    _extend_byd_input(
        base_dir=base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        cutoff="2026-08-07",
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


def test_byd_formal_refresh_replays_production_archives(tmp_path: Path) -> None:
    byd_base = tmp_path / "byd-base"
    etf_base = tmp_path / "etf-base"
    byd_base.mkdir()
    etf_base.mkdir()
    with tarfile.open(
        "data/research/byd_canonical_v1_snapshot.tar.xz", "r:xz"
    ) as archive:
        archive.extractall(byd_base, filter="data")
    encoded = Path(
        "data/research/515180_canonical_v1_artifact.zip.b64"
    ).read_bytes()
    archive_path = tmp_path / "515180.zip"
    archive_path.write_bytes(base64.b64decode(encoded))
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(etf_base)

    current_package = Path(
        "data/research/formal_backtests/"
        "byd_v1_2_convex_momentum_budget_v1.json"
    )
    current_cutoff = str(
        json.loads(current_package.read_text(encoding="utf-8"))["evidence_cutoff"]
    )
    output = tmp_path / "byd-formal.json"
    result = refresh_byd(
        current_package=current_package,
        base_byd_dir=byd_base,
        base_etf_dir=etf_base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        paired_store=Path("data/research/byd_515180_prospective"),
        signal_ledger=Path("data/research/byd_v1_2_signal_ledger"),
        cutoff="2026-08-07",
        generated_at="2026-08-09T00:00:00Z",
        output=output,
    )

    package = json.loads(output.read_text(encoding="utf-8"))
    expected_appended = current_cutoff < "2026-08-07"
    assert (result["appended_sessions"] > 0) is expected_appended
    assert package["evidence_cutoff"] == "2026-08-07"
    assert package["research_only"] is True
    assert package["trade_ready"] is False

    replay_output = tmp_path / "byd-formal-replay.json"
    replay = refresh_byd(
        current_package=output,
        base_byd_dir=byd_base,
        base_etf_dir=etf_base,
        shadow_store=Path("data/research/byd_prospective_shadow"),
        paired_store=Path("data/research/byd_515180_prospective"),
        signal_ledger=Path("data/research/byd_v1_2_signal_ledger"),
        cutoff="2026-08-07",
        generated_at="2026-08-09T00:00:00Z",
        output=replay_output,
    )
    assert replay["appended_sessions"] == 0


def test_byd_prefix_preserves_accepted_float_representation() -> None:
    current = [{"date": "2026-01-07", "weight": 2.9820806175705164e-05}]
    replayed = [{"date": "2026-01-07", "weight": 2.9820806175705168e-05}]
    replayed.append({"date": "2026-01-08", "weight": 0.1})

    merged = _preserve_verified_byd_prefix("report", current, replayed)

    assert merged[0] == current[0]
    assert merged[1] == replayed[1]


def test_byd_prefix_rejects_material_historical_drift() -> None:
    current = [{"date": "2026-01-07", "weight": 0.75}]
    replayed = [{"date": "2026-01-07", "weight": 0.70}]

    with pytest.raises(AllocationRefreshError, match="weight"):
        _preserve_verified_byd_prefix("positions", current, replayed)


def test_etf_extension_normalizes_all_prospective_date_dtypes(tmp_path: Path) -> None:
    base = tmp_path / "etf-base"
    paired = tmp_path / "paired"
    output = tmp_path / "etf-output"
    base.mkdir()
    base_row = {
        "date": "2026-08-03",
        "open": 1.40,
        "high": 1.42,
        "low": 1.39,
        "close": 1.41,
        "volume": 1000.0,
    }
    pd.DataFrame([base_row]).to_csv(base / "raw_ohlcv.csv", index=False)
    pd.DataFrame(
        [
            {
                **base_row,
                "factor": 1.0,
                "adjustment_anchor_date": "2026-08-03",
                "adjustment_anchor_factor": 1.0,
                "price_role": "adjusted_feature_and_label",
            }
        ]
    ).to_csv(base / "adjusted_ohlcv.csv", index=False)
    pd.DataFrame(
        [{"date": "2026-08-03", "open_research_eligible": True}]
    ).to_csv(base / "session_audit.csv", index=False)
    pd.DataFrame(
        [{"date": "2026-08-03", "dividend": 0.0, "stock_split": 0.0}]
    ).to_csv(base / "corporate_actions.csv", index=False)
    _write_json(base / "manifest.json", {"cutoff": "2026-08-03"})
    _write_json(paired / "manifest.json", {"last_signal_date": "2026-08-04"})
    _write_json(
        paired / "observations" / "2026-08-04.json",
        {
            "signal_date": "2026-08-04",
            "etf": {
                "open_research_eligible": True,
                "primary_raw_ohlcv": {
                    "open": 1.41,
                    "high": 1.43,
                    "low": 1.40,
                    "close": 1.42,
                    "volume": 1200.0,
                },
                "chain_linked_adjusted_ohlcv": {
                    "open": 1.41,
                    "high": 1.43,
                    "low": 1.40,
                    "close": 1.42,
                    "volume": 1200.0,
                },
                "company_actions": {"dividend": 0.01, "stock_split": 0.0},
            },
        },
    )

    manifest = _extend_etf_input(
        base_dir=base,
        paired_store=paired,
        cutoff="2026-08-04",
        output_dir=output,
    )

    for filename in (
        "raw_ohlcv.csv",
        "adjusted_ohlcv.csv",
        "session_audit.csv",
        "corporate_actions.csv",
    ):
        frame = pd.read_csv(output / filename)
        assert frame["date"].tolist() == ["2026-08-03", "2026-08-04"]
    assert manifest["cutoff"] == "2026-08-04"


def test_overlap_ignores_revised_economic_return_but_locks_decision_path() -> None:
    existing = {
        "2026-07-30": {
            "period_return": -0.99,
            "gross_return": -0.99,
            "transaction_cost": 0.25,
            "position_state": 1,
            "decision_state": 1,
            "position_label": "attack",
            "decision_reason": "hold",
            "executed_reason": "enter_attack",
            "weight_QQQI": 0.5,
            "weight_QQQ": 0.5,
            "weight_TQQQ": 0.0,
        }
    }
    _verify_qqq_decision_overlap(existing, _daily())


def test_overlap_fails_closed_when_frozen_decision_path_changes() -> None:
    existing = {
        "2026-07-30": {
            "position_state": 0,
            "decision_state": 1,
            "weight_QQQI": 1.0,
            "weight_QQQ": 0.0,
            "weight_TQQQ": 0.0,
        }
    }
    with pytest.raises(AllocationRefreshError, match="decision path changed"):
        _verify_qqq_decision_overlap(existing, _daily())


def test_overlap_requires_all_frozen_decision_dates_to_be_replayed() -> None:
    existing = {
        "2026-07-29": {"position_state": 1, "decision_state": 1},
    }
    with pytest.raises(AllocationRefreshError, match="missing 1 frozen decision dates"):
        _verify_qqq_decision_overlap(existing, _daily())


def test_metrics_are_recomputed_from_frozen_plus_appended_report() -> None:
    report = [
        {
            "date": "2026-07-29",
            "period_return": 0.01,
            "turnover": 0.0,
            "transaction_cost": 0.0,
        },
        {
            "date": "2026-07-30",
            "period_return": -0.005,
            "turnover": 1.0,
            "transaction_cost": 0.001,
        },
        {
            "date": "2026-07-31",
            "period_return": 0.02,
            "turnover": 0.0,
            "transaction_cost": 0.0,
        },
    ]
    metrics = _qqq_metrics_from_report(report, annual_risk_free_rate=0.0)
    assert metrics["Total Return"] == pytest.approx((1.01 * 0.995 * 1.02) - 1.0)
    assert metrics["Turnover"] == pytest.approx(1.0)
    assert metrics["Transaction Cost"] == pytest.approx(0.001)


def test_attribution_extends_only_new_sessions_from_frozen_values() -> None:
    existing = [
        {"instrument": "QQQI", "value": 0.10},
        {"instrument": "QQQ", "value": 0.20},
        {"instrument": "TQQQ", "value": 0.30},
    ]
    result = _increment_qqq_attribution(
        existing=existing,
        daily=_daily(),
        appended_dates={"2026-07-31"},
        previous_weights={"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0},
    )
    values = {row["instrument"]: row["value"] for row in result}
    assert values["QQQI"] == pytest.approx(0.11)
    assert values["QQQ"] == pytest.approx(0.205)
    assert values["TQQQ"] == pytest.approx(0.30)
