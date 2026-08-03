from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.finalize_latest_formal_backtests import LatestFormalFinalizationError, finalize

CURRENT_IDENTITY = "6614e26a4d7cc27dad4e1123ddcc1a73f0e753b7c115e86577a40ab195da2d09"
US_IDENTITY = "5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95"
OLD_IDENTITY = "bf5fa1373a0b5ebfedcd90c2cf3c4748300efd2b25da0adfbfb1daab8c6405d8"
US_TRACE = "a" * 64
CN_TRACE = "b" * 64
HEAD_SHA = "1" * 40
ARTIFACT_DIGEST = "sha256:" + "2" * 64


def _write(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(encoded, encoding="utf-8")
    return hashlib.sha256(encoded.encode()).hexdigest()


def _fixture(
    tmp_path: Path,
    *,
    bad_final: bool = False,
    rewrite_cn_prefix: bool = False,
    bad_source_trace: bool = False,
) -> tuple[Path, Path, Path, Path]:
    generated = tmp_path / "generated"
    existing = tmp_path / "existing"
    run = tmp_path / "cn-run"
    source_path = tmp_path / "freshness_source.json"
    generated.mkdir()
    existing.mkdir()
    historical_account = 1.2
    final_account = historical_account * 0.9 * 1.05
    if bad_final:
        final_account += 0.01

    accepted_us_position = {
        "date": "2025-12-01", "instrument": "OLD_US", "weight": 1.0,
        "rank": 1, "window": "2025H2",
    }
    accepted_cn_position = {
        "date": "2026-06-01", "instrument": "OLD_CN", "weight": 1.0,
        "rank": 1, "window": "2026H1",
    }
    generated_cn_prefix = dict(accepted_cn_position)
    if rewrite_cn_prefix:
        generated_cn_prefix["instrument"] = "REWRITTEN_CN"

    _write(existing / "us_x1_1.json", {"positions": [accepted_us_position]})
    _write(
        existing / "cn_x1_0.json",
        {"positions": [accepted_cn_position], "evidence": {"freshness_evidence": {
            "provider_identity_sha256": OLD_IDENTITY,
        }}},
    )
    us = {
        "model_id": "us_x1_1", "evidence_cutoff": "2026-07-31",
        "generated_at": "2026-08-03T03:55:00Z",
        "positions": [dict(accepted_us_position), {
            "date": "2026-07-01", "instrument": "NEW_US", "weight": 1.0,
            "rank": 1, "window": "2026H2_partial",
        }],
        "evidence": {"freshness_evidence": {
            "provider_identity_sha256": US_IDENTITY,
            "trace_sha256": {"2026H1": US_TRACE, "2026H2": US_TRACE},
        }},
        "interpretation_notes": [],
    }
    cn = {
        "model_id": "cn_x1_0", "evidence_cutoff": "2026-07-31",
        "generated_at": "2026-08-03T03:55:00Z",
        "positions": [generated_cn_prefix, {
            "date": "2026-07-01", "instrument": "NEW_CN", "weight": 1.0,
            "rank": 1, "window": "2026H2_partial",
        }],
        "report": [
            {"date": "2025-12-31", "account": 1.3},
            {"date": "2026-06-30", "account": historical_account},
            {"date": "2026-07-31", "account": final_account},
        ],
        "metrics": {"Max Drawdown": -0.05},
        "evidence": {"freshness_evidence": {
            "provider_identity_sha256": OLD_IDENTITY,
            "trace_sha256": {"2026H2": CN_TRACE},
        }},
        "interpretation_notes": [],
    }
    us_digest = _write(generated / "us_x1_1.json", us)
    cn_digest = _write(generated / "cn_x1_0.json", cn)
    _write(generated / "catalog.json", {"records": [
        {"model_id": "us_x1_1", "path": "us_x1_1.json", "sha256": us_digest},
        {"model_id": "cn_x1_0", "path": "cn_x1_0.json", "sha256": cn_digest},
    ]})
    _write(run / "walk_forward_windows.json", {"experiment_id": "cn_fixture"})
    _write(run / "windows/cn_fixture_2026H2.json", {"backtest_traces": [{
        "candidate_name": "xgb:daily_ranker:frozen", "orientation": "original",
        "points": [
            {"signal_date": "2026-07-01", "net_period_return": -0.1},
            {"signal_date": "2026-07-16", "net_period_return": 0.05},
        ],
    }]})
    _write(source_path, {
        "schema_version": "1.0.0",
        "status": "accepted_reproducible_freshness_evidence",
        "cutoff": "2026-07-31", "generated_at": "2026-08-03T03:55:00Z",
        "workflow_run_id": 123, "workflow_head_sha": HEAD_SHA,
        "artifact_id": 456, "artifact_name": "freshness-evidence",
        "artifact_digest": ARTIFACT_DIGEST,
        "models": {
            "us_x1_1": {"provider_identity_sha256": US_IDENTITY, "trace_sha256": {
                "2026H1": "c" * 64 if bad_source_trace else US_TRACE,
                "2026H2": US_TRACE,
            }},
            "cn_x1_0": {"provider_identity_sha256": CURRENT_IDENTITY, "trace_sha256": {
                "2026H2": CN_TRACE,
            }},
        },
        "research_only": True, "trade_ready": False,
    })
    return generated, existing, run, source_path


def _finalize(paths: tuple[Path, Path, Path, Path], identity: str = CURRENT_IDENTITY):
    generated, existing, run, source = paths
    return finalize(generated, existing, run, source, cn_provider_identity=identity)


def test_preserves_prefix_and_binds_immutable_source(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = _finalize(paths)
    generated = paths[0]
    assert result["status"] == "finalized"
    assert result["accepted_position_prefix_lengths"] == {"us_x1_1": 1, "cn_x1_0": 1}
    assert result["freshness_source"]["artifact_id"] == 456
    us = json.loads((generated / "us_x1_1.json").read_text())
    cn = json.loads((generated / "cn_x1_0.json").read_text())
    assert us["positions"][0]["rank"] == 1 and "rank" not in us["positions"][1]
    assert cn["positions"][0]["rank"] == 1 and "rank" not in cn["positions"][1]
    assert cn["metrics"]["Max Drawdown"] == pytest.approx(-0.16923076923076918)
    for package in (us, cn):
        freshness = package["evidence"]["freshness_evidence"]
        assert freshness["workflow_run_id"] == "123"
        assert freshness["workflow_head_sha"] == HEAD_SHA
        assert freshness["artifact_id"] == 456
        assert freshness["artifact_digest"] == ARTIFACT_DIGEST
    cn_freshness = cn["evidence"]["freshness_evidence"]
    assert cn_freshness["provider_identity_sha256"] == CURRENT_IDENTITY
    assert cn_freshness["superseded_provider_identity_sha256"] == OLD_IDENTITY
    catalog = json.loads((generated / "catalog.json").read_text())
    for row in catalog["records"]:
        assert row["sha256"] == hashlib.sha256((generated / row["path"]).read_bytes()).hexdigest()


def test_rejects_non_reconciling_cn_path(tmp_path: Path) -> None:
    with pytest.raises(LatestFormalFinalizationError, match="does not reconcile"):
        _finalize(_fixture(tmp_path, bad_final=True))


def test_rejects_rewritten_accepted_position_prefix(tmp_path: Path) -> None:
    with pytest.raises(LatestFormalFinalizationError, match="accepted position prefix"):
        _finalize(_fixture(tmp_path, rewrite_cn_prefix=True))


def test_rejects_invalid_provider_identity(tmp_path: Path) -> None:
    with pytest.raises(LatestFormalFinalizationError, match="invalid CN provider identity"):
        _finalize(_fixture(tmp_path), identity="not-a-digest")


def test_rejects_freshness_source_trace_mismatch(tmp_path: Path) -> None:
    with pytest.raises(LatestFormalFinalizationError, match="trace/source mismatch"):
        _finalize(_fixture(tmp_path, bad_source_trace=True))
