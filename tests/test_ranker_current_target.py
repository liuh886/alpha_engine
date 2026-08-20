from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.artifacts.strategy_signal_ledger import seal_signal_decision
from src.factors.library import load_factor_library
from src.factors.ranker_snapshot import build_ranker_factor_snapshot
from src.factors.strategy_snapshot import StrategyFactorSnapshotError
from src.research.ranker_current_target import (
    RankerCurrentTargetError,
    _select_cn_sector_breadth,
    load_previous_state,
    merge_governed_market_sessions,
    next_due_session,
)

ROOT = Path(__file__).resolve().parents[1]


def _formal(path: Path, date: str, weights: dict[str, float]) -> None:
    path.write_text(
        json.dumps(
            {
                "positions": [
                    {"date": date, "instrument": symbol, "weight": weight}
                    for symbol, weight in weights.items()
                ]
            }
        ),
        encoding="utf-8",
    )


def _live_ledger(ledger: Path, date: str, weights: dict[str, float]) -> None:
    factor_evidence = build_ranker_factor_snapshot(
        model_family_id="us_ranker",
        signal_date=date,
        latest_data_date=date,
        factor_values={"ohlcv.momentum.ret_3d": 0.0},
        factor_references={},
        data_freshness_ok=True,
    )
    signal = {
        "model_family_id": "us_ranker",
        "research_only": True,
        "trade_ready": False,
        "should_alert": True,
        "fingerprint": f"test-{date}",
        "signal_date": date,
        "latest_data_date": date,
        "data_freshness_ok": True,
        "factor_evidence": factor_evidence,
        "factor_freshness_ok": True,
        "current_weights": {},
        "target_weights": weights,
        "turnover_units": 1.0,
        "estimated_transaction_cost": 0.0,
        "reason_code": "test_ranker_state",
    }
    seal_signal_decision(
        ledger_root=ledger,
        model_version_id=ledger.name,
        signal=signal,
        workflow_run_id="test-run",
        commit_sha="a" * 40,
        created_at_utc=f"{date}T00:00:00Z",
    )


def test_next_due_session_is_exactly_ten_provider_sessions_after_anchor() -> None:
    sessions = pd.bdate_range("2026-07-01", periods=20)
    assert next_due_session(anchor="2026-07-01", sessions=sessions) == "2026-07-15"
    assert next_due_session(anchor="2026-07-15", sessions=sessions) is None


def test_next_due_session_fails_if_anchor_is_not_provider_session() -> None:
    with pytest.raises(RankerCurrentTargetError, match="not uniquely present"):
        next_due_session(
            anchor="2026-07-04",
            sessions=pd.bdate_range("2026-07-01", periods=20),
        )


def test_governed_sessions_extend_audited_history_with_live_benchmark(tmp_path: Path) -> None:
    evidence = tmp_path / "benchmark.json"
    evidence.write_text(
        json.dumps(
            {
                "bars": [
                    {"time": str(day.date()), "close": 1.0}
                    for day in pd.bdate_range("2026-07-29", periods=9)
                ]
            }
        ),
        encoding="utf-8",
    )
    sessions = merge_governed_market_sessions(
        evidence_path=evidence,
        live_sessions=pd.DatetimeIndex(["2026-08-11"]),
        as_of="2026-08-11",
    )
    assert sessions[0] == pd.Timestamp("2026-07-29")
    assert sessions[-1] == pd.Timestamp("2026-08-11")
    assert next_due_session(anchor="2026-07-29", sessions=sessions) is None


def test_live_ledger_supersedes_older_same_model_formal_position(tmp_path: Path) -> None:
    formal = tmp_path / "formal.json"
    ledger = tmp_path / "test_model"
    _formal(formal, "2026-07-01", {"AAA": 1.0})
    _live_ledger(ledger, "2026-07-15", {"BBB": 0.5, "CCC": 0.5})
    date, weights = load_previous_state(formal_package=formal, ledger_dir=ledger)
    assert date == "2026-07-15"
    assert weights == {"BBB": 0.5, "CCC": 0.5}


def test_formal_state_ahead_of_existing_same_model_ledger_fails_closed(tmp_path: Path) -> None:
    formal = tmp_path / "formal.json"
    ledger = tmp_path / "test_model"
    _formal(formal, "2026-07-15", {"AAA": 1.0})
    _live_ledger(ledger, "2026-07-01", {"BBB": 1.0})
    with pytest.raises(RankerCurrentTargetError, match="formal ranker state is ahead"):
        load_previous_state(formal_package=formal, ledger_dir=ledger)


def test_ranker_snapshot_preserves_explicit_model_factor_order() -> None:
    library = load_factor_library(ROOT / "configs/factor_libraries/ohlcv.yaml")
    ids = [
        factor.factor_id
        for factor in library.factors_for_groups(["momentum_volatility_volume"])
    ]
    ids = list(reversed(ids))
    snapshot = build_ranker_factor_snapshot(
        model_family_id="us_ranker",
        signal_date="2026-08-07",
        latest_data_date="2026-08-07",
        factor_values={factor_id: float(index) for index, factor_id in enumerate(ids)},
        factor_references={},
        data_freshness_ok=True,
    )
    assert snapshot["groups"] == []
    assert [row["factor_id"] for row in snapshot["factors"]] == ids
    assert snapshot["freshness"] == "current"


def test_ranker_snapshot_resolves_multi_library_factor_contract() -> None:
    snapshot = build_ranker_factor_snapshot(
        model_family_id="cn_ranker",
        signal_date="2026-08-07",
        latest_data_date="2026-08-07",
        factor_values={
            "ohlcv.momentum.ret_3d": 0.1,
            "qlib_alpha158.cntd30": 0.2,
            "qlib_alpha158.cord5": 0.3,
            "qlib_alpha158.imin30": 0.4,
        },
        factor_references={},
        data_freshness_ok=True,
        library_sources=[
            "configs/factor_libraries/ohlcv.yaml",
            "src/factors/sets/qlib_alpha158.py",
        ],
    )

    assert [row["factor_id"] for row in snapshot["factors"]] == [
        "ohlcv.momentum.ret_3d",
        "qlib_alpha158.cntd30",
        "qlib_alpha158.cord5",
        "qlib_alpha158.imin30",
    ]
    assert snapshot["catalog_id"] == "alpha_engine_ohlcv+qlib_alpha158"
    assert len(snapshot["catalog_implementation_hash"]) == 64
    assert len(snapshot["source_sha256"]) == 64


def test_ranker_snapshot_multi_library_rejects_unknown_factor() -> None:
    with pytest.raises(StrategyFactorSnapshotError, match="unknown canonical factor ids"):
        build_ranker_factor_snapshot(
            model_family_id="cn_ranker",
            signal_date="2026-08-07",
            latest_data_date="2026-08-07",
            factor_values={"ohlcv.momentum.ret_3d": 0.1, "missing.factor": 0.2},
            factor_references={},
            data_freshness_ok=True,
            library_sources=[
                "configs/factor_libraries/ohlcv.yaml",
                "src/factors/sets/qlib_alpha158.py",
            ],
        )


def test_ranker_snapshot_accepts_new_canonical_factors_without_family_map() -> None:
    library = load_factor_library(ROOT / "configs/factor_libraries/ohlcv.yaml")
    ids = [
        factor.factor_id
        for factor in library.factors_for_groups(["us_short_reversal_liquidity"])
    ]
    snapshot = build_ranker_factor_snapshot(
        model_family_id="us_ranker",
        signal_date="2026-08-07",
        latest_data_date="2026-08-07",
        factor_values={factor_id: float(index) for index, factor_id in enumerate(ids)},
        factor_references={},
        data_freshness_ok=True,
    )
    assert snapshot["groups"] == []
    assert [row["factor_id"] for row in snapshot["factors"]] == ids


def test_cn_sector_breadth_selects_one_name_from_top_four_sectors() -> None:
    day = pd.DataFrame(
        {
            "instrument": ["A1", "A2", "B1", "B2", "C1", "D1", "E1"],
            "sector": ["A", "A", "B", "B", "C", "D", "E"],
            "score": [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 1.0],
        }
    )
    chosen = _select_cn_sector_breadth(day, sectors=4, names_per_sector=1)
    assert len(chosen) == 4
    assert chosen.groupby("sector").size().max() == 1
    assert set(chosen["instrument"]) == {"A1", "B1", "C1", "D1"}
