from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

import scripts.run_ranker_current_target as ranker_command
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import load_active_strategy_runtime_capabilities
from src.research.cn_x1_2_current_target import MODEL_ID as CN_MODEL_ID
from src.research.cn_x1_2_prospective import FROZEN_TRAIN_END

ROOT = Path(__file__).resolve().parents[1]


def _benchmark_evidence(
    root: Path,
    *,
    market: str,
    benchmark: str,
    dates: list[str],
    cutoff: str | None = None,
) -> Path:
    market_root = root / market
    evidence = market_root / "symbols" / f"{benchmark}.json"
    evidence.parent.mkdir(parents=True)
    provider_sha = "a" * 64
    payload = {
        "bars": [{"time": date, "close": 1.0} for date in dates],
        "cutoff": cutoff or dates[-1],
        "evidence_type": "security_market_evidence",
        "instrument_id": f"{market}:{benchmark}",
        "market": market,
        "provider_manifest_sha256": provider_sha,
        "research_only": True,
        "schema_version": "1.1",
        "source_csv_sha256": "b" * 64,
        "start": dates[0],
        "symbol": benchmark,
        "trade_ready": False,
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    catalog = {
        "benchmark": benchmark,
        "cutoff": cutoff or dates[-1],
        "evidence_type": "market_evidence_catalog",
        "input_identity_sha256": "c" * 64,
        "market": market,
        "provider_identity_sha256": "d" * 64,
        "provider_manifest_sha256": provider_sha,
        "research_only": True,
        "schema_version": "1.1",
        "symbols": [
            {
                "cutoff": cutoff or dates[-1],
                "instrument_id": f"{market}:{benchmark}",
                "path": f"symbols/{benchmark}.json",
                "sha256": evidence_sha,
                "symbol": benchmark,
            }
        ],
        "trade_ready": False,
    }
    (market_root / "catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )
    return evidence


def test_both_active_rankers_have_exact_current_target_adapters() -> None:
    active = load_active_strategy_catalog(ROOT / "configs/strategies/registry.json")
    capabilities = load_active_strategy_runtime_capabilities(
        repository_root=ROOT,
        active=active,
    )
    assert capabilities["us_x"].current_target.adapter_id == "us_x1_3_current_target_v1"
    assert capabilities["cn_x"].current_target.adapter_id == "cn_x1_2_current_target_v1"


def test_cn_x1_2_current_target_keeps_frozen_training_boundary() -> None:
    config = yaml.safe_load((ROOT / "configs/models/cn_x1_2.yaml").read_text(encoding="utf-8"))
    assert CN_MODEL_ID == "cn_x1_2"
    assert FROZEN_TRAIN_END == "2026-06-30"
    assert (
        config["formal_publication"]["current_target_activation"]
        == "maintained_cn_x1_2_current_target_v1"
    )
    assert "blocked_pending" not in (ROOT / "configs/models/cn_x1_2.yaml").read_text(
        encoding="utf-8"
    )


def test_ranker_workflow_has_no_delivery_transport() -> None:
    workflow = (ROOT / ".github/workflows/ranker-10d-current-target.yml").read_text(
        encoding="utf-8"
    )
    assert "scripts/run_ranker_current_target.py" in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "api.telegram.org" not in workflow
    assert "gh issue create" not in workflow
    assert "run_us_x1_3_current_target.py" not in workflow


def test_due_calendar_extends_governed_identity_with_exact_exchange_sessions(
    tmp_path: Path,
) -> None:
    evidence = _benchmark_evidence(
        tmp_path,
        market="us",
        benchmark="QQQ",
        dates=["2026-08-28", "2026-08-31"],
    )

    sessions, provider = ranker_command._resolve_market_sessions(
        evidence_path=evidence,
        market="us",
        benchmark="QQQ",
        as_of="2026-09-02",
    )

    assert sessions.tolist() == [
        pd.Timestamp("2026-08-28"),
        pd.Timestamp("2026-08-31"),
        pd.Timestamp("2026-09-01"),
        pd.Timestamp("2026-09-02"),
    ]
    assert "exchange_calendars@" in provider
    assert ":XNYS+governed_market_evidence_identity" in provider


@pytest.mark.parametrize(
    ("market", "benchmark", "dates", "as_of", "calendar_id"),
    [
        ("us", "QQQ", ["2026-09-03", "2026-09-04"], "2026-09-07", "XNYS"),
        ("cn", "000300", ["2026-09-29", "2026-09-30"], "2026-10-07", "XSHG"),
    ],
)
def test_due_calendar_handles_weekday_exchange_holidays_without_market_data(
    tmp_path: Path,
    market: str,
    benchmark: str,
    dates: list[str],
    as_of: str,
    calendar_id: str,
) -> None:
    evidence = _benchmark_evidence(
        tmp_path,
        market=market,
        benchmark=benchmark,
        dates=dates,
    )

    sessions, provider = ranker_command._resolve_market_sessions(
        evidence_path=evidence,
        market=market,
        benchmark=benchmark,
        as_of=as_of,
    )

    assert sessions.max() == pd.Timestamp(dates[-1])
    assert calendar_id in provider


def test_due_calendar_rejects_wrong_market_catalog_identity(tmp_path: Path) -> None:
    evidence = _benchmark_evidence(
        tmp_path,
        market="us",
        benchmark="QQQ",
        dates=["2026-08-28", "2026-08-31"],
    )
    catalog_path = evidence.parent.parent / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["market"] = "cn"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(
        ranker_command.RankerCurrentTargetCommandError,
        match="catalog identity mismatch",
    ):
        ranker_command._resolve_market_sessions(
            evidence_path=evidence,
            market="us",
            benchmark="QQQ",
            as_of="2026-08-31",
        )


def test_due_calendar_rejects_evidence_cutoff_after_last_bar(tmp_path: Path) -> None:
    evidence = _benchmark_evidence(
        tmp_path,
        market="us",
        benchmark="QQQ",
        dates=["2026-08-28"],
        cutoff="2026-08-31",
    )

    with pytest.raises(
        ranker_command.RankerCurrentTargetCommandError,
        match="cutoff mismatch",
    ):
        ranker_command._resolve_market_sessions(
            evidence_path=evidence,
            market="us",
            benchmark="QQQ",
            as_of="2026-08-31",
        )


def test_due_calendar_has_no_live_market_data_dependency() -> None:
    source = (ROOT / "scripts/run_ranker_current_target.py").read_text(encoding="utf-8")

    assert "build_hardened_router" not in source
    assert "_live_sessions" not in source
