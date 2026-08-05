from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import promote_byd_dividend_sleeve_formal as module


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def test_monitoring_requires_exact_observation_after_historical_cutoff(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prospective"
    write_json(
        root / "manifest.json",
        {
            "schema_version": "byd_515180_prospective_v1",
            "append_only": True,
            "observation_sha256": {"2026-08-04": "0" * 64},
            "last_signal_date": "2026-08-04",
        },
    )
    with pytest.raises(module.FormalPromotionError, match="exact paired observation"):
        module._monitoring(root, "2026-08-05")


def test_monitoring_binds_exact_observation_sha(tmp_path: Path) -> None:
    root = tmp_path / "prospective"
    observation = {
        "signal_date": "2026-08-05",
        "prospective_eligible": False,
        "common_open_eligible": False,
        "status": "prospective_paired_open_quarantined",
        "targets": {
            "v1_dividend_75_25": {
                "byd_weight": 0.75,
                "etf_weight": 0.25,
                "cash_weight": 0.0,
            }
        },
    }
    observation_path = root / "observations" / "2026-08-05.json"
    write_json(observation_path, observation)
    digest = hashlib.sha256(observation_path.read_bytes()).hexdigest()
    write_json(
        root / "manifest.json",
        {
            "schema_version": "byd_515180_prospective_v1",
            "append_only": True,
            "observation_sha256": {"2026-08-05": digest},
            "last_signal_date": "2026-08-05",
            "completed_defense_episode_count": 0,
        },
    )

    result = module._monitoring(root, "2026-08-05")

    assert result["status"] == "post_promotion_prospective_monitoring"
    assert result["latest_signal_date"] == "2026-08-05"
    assert result["latest_observation_sha256"] == digest
    assert result["latest_target_weights"] == {
        "byd_weight": 0.75,
        "etf_weight": 0.25,
        "cash_weight": 0.0,
    }


def test_promote_adds_formal_allow_list_without_weakening_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "formal"
    write_json(
        root / "catalog.json",
        {
            "schema_version": "1.0.0",
            "publication_policy": "formal_named_baselines_only",
            "records": [
                {
                    "display_name": "CN x1.0",
                    "display_order": 3,
                    "model_id": "cn_x1_0",
                    "path": "cn_x1_0.json",
                    "publication_status": "accepted_formal_baseline",
                    "sha256": "a" * 64,
                }
            ],
            "research_only": True,
            "trade_ready": False,
        },
    )
    write_json(
        root / "freshness.json",
        {
            "schema_version": "1.0.0",
            "cutoff_policy": "latest_completed_trading_session",
            "markets": {"cn": "2026-08-03"},
            "next_session_close_utc": {"cn": "2026-08-04T07:00:00Z"},
            "required_models": ["cn_x1_0"],
            "freshness_receipt_required_models": ["cn_x1_0"],
            "date_range_end_required_models": ["cn_x1_0"],
            "research_only": True,
            "trade_ready": False,
        },
    )

    package = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "model_id": module.MODEL_ID,
        "display_name": module.DISPLAY_NAME,
        "market": "cn",
        "publication_status": "accepted_formal_baseline",
        "evidence_cutoff": "2026-08-03",
        "date_range": {"start": "2019-11-26", "end": "2026-08-02"},
        "operational_monitoring": {"latest_signal_date": None},
        "report": [{"date": "2019-11-26", "account": 1.0}],
        "evidence_completeness": {"status": "complete"},
        "research_only": True,
        "trade_ready": False,
    }
    monkeypatch.setattr(module, "build_package", lambda **_: package)

    receipt = module.promote(
        root=root,
        byd_dir=tmp_path / "byd",
        etf_dir=tmp_path / "etf",
        prospective_root=tmp_path / "prospective",
        generated_at="2026-08-05T13:30:00Z",
    )

    catalog = json.loads((root / "catalog.json").read_text())
    freshness = json.loads((root / "freshness.json").read_text())
    promoted = json.loads((root / module.PACKAGE_NAME).read_text())

    assert receipt["status"] == "accepted_formal_baseline_promoted"
    assert [row["model_id"] for row in catalog["records"]] == [
        "cn_x1_0",
        module.MODEL_ID,
    ]
    assert module.MODEL_ID in freshness["required_models"]
    assert module.MODEL_ID not in freshness["date_range_end_required_models"]
    assert promoted["research_only"] is True
    assert promoted["trade_ready"] is False


def test_formal_identity_is_versioned_and_user_directed() -> None:
    assert module.MODEL_ID == "byd_dividend_sleeve_v1_0"
    assert module.DISPLAY_NAME == "BYD Dividend Sleeve V1.0"
    assert module.PRIMARY_COST_BPS == 20.0
    assert module.STRESS_COST_BPS == 40.0
