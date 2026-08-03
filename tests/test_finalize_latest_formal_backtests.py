from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.finalize_latest_formal_backtests import (
    LatestFormalFinalizationError,
    finalize,
)

CURRENT_IDENTITY = "6614e26a4d7cc27dad4e1123ddcc1a73f0e753b7c115e86577a40ab195da2d09"
OLD_IDENTITY = "bf5fa1373a0b5ebfedcd90c2cf3c4748300efd2b25da0adfbfb1daab8c6405d8"


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
) -> tuple[Path, Path, Path]:
    generated = tmp_path / "generated"
    existing = tmp_path / "existing"
    run = tmp_path / "cn-run"
    generated.mkdir()
    existing.mkdir()
    historical_account = 1.2
    partial_returns = [-0.1, 0.05]
    final_account = historical_account
    for value in partial_returns:
        final_account *= 1.0 + value
    if bad_final:
        final_account += 0.01

    accepted_us_position = {
        "date": "2025-12-01",
        "instrument": "OLD_US",
        "weight": 1.0,
        "rank": 1,
        "window": "2025H2",
    }
    accepted_cn_position = {
        "date": "2026-06-01",
        "instrument": "OLD_CN",
        "weight": 1.0,
        "rank": 1,
        "window": "2026H1",
    }
    generated_cn_prefix = dict(accepted_cn_position)
    if rewrite_cn_prefix:
        generated_cn_prefix["instrument"] = "REWRITTEN_CN"

    accepted_us = {
        "positions": [accepted_us_position],
        "interpretation_notes": [],
    }
    accepted_cn = {
        "positions": [accepted_cn_position],
        "evidence": {
            "freshness_evidence": {
                "provider_identity_sha256": OLD_IDENTITY,
            }
        },
        "interpretation_notes": [],
    }
    us = {
        "positions": [
            dict(accepted_us_position),
            {
                "date": "2026-07-01",
                "instrument": "NEW_US",
                "weight": 1.0,
                "rank": 1,
                "window": "2026H2_partial",
            },
        ],
        "interpretation_notes": [],
    }
    cn = {
        "positions": [
            generated_cn_prefix,
            {
                "date": "2026-07-01",
                "instrument": "NEW_CN",
                "weight": 1.0,
                "rank": 1,
                "window": "2026H2_partial",
            },
        ],
        "report": [
            {"date": "2025-12-31", "account": 1.3},
            {"date": "2026-06-30", "account": historical_account},
            {"date": "2026-07-31", "account": final_account},
        ],
        "metrics": {"Max Drawdown": -0.05},
        "evidence": {
            "freshness_evidence": {
                "provider_identity_sha256": OLD_IDENTITY,
            }
        },
        "interpretation_notes": [],
    }
    _write(existing / "us_x1_1.json", accepted_us)
    _write(existing / "cn_x1_0.json", accepted_cn)
    us_digest = _write(generated / "us_x1_1.json", us)
    cn_digest = _write(generated / "cn_x1_0.json", cn)
    _write(
        generated / "catalog.json",
        {
            "records": [
                {"model_id": "us_x1_1", "path": "us_x1_1.json", "sha256": us_digest},
                {"model_id": "cn_x1_0", "path": "cn_x1_0.json", "sha256": cn_digest},
            ]
        },
    )
    _write(
        run / "walk_forward_windows.json",
        {"experiment_id": "cn_fixture"},
    )
    _write(
        run / "windows" / "cn_fixture_2026H2.json",
        {
            "backtest_traces": [
                {
                    "candidate_name": "xgb:daily_ranker:frozen",
                    "orientation": "original",
                    "points": [
                        {"signal_date": "2026-07-01", "net_period_return": -0.1},
                        {"signal_date": "2026-07-16", "net_period_return": 0.05},
                    ],
                }
            ]
        },
    )
    return generated, existing, run


def test_preserves_accepted_prefix_and_updates_only_extensions(tmp_path: Path) -> None:
    generated, existing, run = _fixture(tmp_path)
    result = finalize(
        generated,
        existing,
        run,
        cn_provider_identity=CURRENT_IDENTITY,
    )
    assert result["status"] == "finalized"
    assert result["accepted_position_prefix_lengths"] == {
        "us_x1_1": 1,
        "cn_x1_0": 1,
    }
    assert result["cn_provider_identity_sha256"] == CURRENT_IDENTITY
    assert result["superseded_cn_provider_identity_sha256"] == OLD_IDENTITY
    us = json.loads((generated / "us_x1_1.json").read_text(encoding="utf-8"))
    cn = json.loads((generated / "cn_x1_0.json").read_text(encoding="utf-8"))
    assert us["positions"][0]["rank"] == 1
    assert "rank" not in us["positions"][1]
    assert us["positions"][1]["rank_evidence"] == "not_retained"
    assert cn["positions"][0]["window"] == "2026H1"
    assert cn["positions"][0]["rank"] == 1
    assert "rank" not in cn["positions"][1]
    assert cn["positions"][1]["rank_evidence"] == "not_retained"
    assert cn["metrics"]["Max Drawdown"] == pytest.approx(-0.16923076923076918)
    freshness = cn["evidence"]["freshness_evidence"]
    assert freshness["provider_identity_sha256"] == CURRENT_IDENTITY
    assert freshness["superseded_provider_identity_sha256"] == OLD_IDENTITY
    assert freshness["provider_snapshot_revision_observed"] is True
    catalog = json.loads((generated / "catalog.json").read_text(encoding="utf-8"))
    for row in catalog["records"]:
        path = generated / row["path"]
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_rejects_non_reconciling_cn_path(tmp_path: Path) -> None:
    generated, existing, run = _fixture(tmp_path, bad_final=True)
    with pytest.raises(LatestFormalFinalizationError, match="does not reconcile"):
        finalize(
            generated,
            existing,
            run,
            cn_provider_identity=CURRENT_IDENTITY,
        )


def test_rejects_rewritten_accepted_position_prefix(tmp_path: Path) -> None:
    generated, existing, run = _fixture(tmp_path, rewrite_cn_prefix=True)
    with pytest.raises(LatestFormalFinalizationError, match="accepted position prefix"):
        finalize(
            generated,
            existing,
            run,
            cn_provider_identity=CURRENT_IDENTITY,
        )


def test_rejects_invalid_provider_identity(tmp_path: Path) -> None:
    generated, existing, run = _fixture(tmp_path)
    with pytest.raises(LatestFormalFinalizationError, match="invalid CN provider identity"):
        finalize(
            generated,
            existing,
            run,
            cn_provider_identity="not-a-digest",
        )
