from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pandas as pd
import pytest

import scripts.run_ranker_current_target as ranker_runner
from src.artifacts.strategy_signal_ledger import seal_signal_decision
from src.factors.library import load_factor_library
from src.factors.ranker_snapshot import build_ranker_factor_snapshot
from src.research.ranker_current_target import (
    CN_FACTOR_COLUMNS,
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


def test_governed_sessions_fill_short_live_provider_window(tmp_path: Path) -> None:
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


def test_cn_due_uses_governed_calendar_without_yahoo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "data/research/market_evidence/cn/symbols/000300.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps({"bars": [{"time": "2026-08-12", "close": 1.0}]}),
        encoding="utf-8",
    )
    formal = tmp_path / "portfolio.json"
    formal.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(ranker_runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        ranker_runner,
        "_formal_portfolio",
        lambda _formal_root, _model_version_id: formal,
    )
    monkeypatch.setattr(
        ranker_runner,
        "load_previous_state",
        lambda **_kwargs: ("2026-08-12", {"000300": 1.0}),
    )
    monkeypatch.setattr(
        ranker_runner,
        "completed_market_date",
        lambda _market, _as_of: "2026-08-13",
    )

    class UnexpectedYahooAdapter:
        def __init__(self) -> None:
            raise AssertionError("CN due resolution must not instantiate Yahoo")

    monkeypatch.setattr(ranker_runner, "YFinanceAdapter", UnexpectedYahooAdapter)
    output = tmp_path / "due.json"
    args = Namespace(
        market="cn",
        formal_root=tmp_path,
        ledger_dir=tmp_path / "ledger",
        as_of="2026-08-14",
        output=output,
    )

    assert ranker_runner._due(args) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["due"] is False
    assert payload["signal_date"] is None
    assert payload["calendar_provider"] == (
        "completed_session_gate+governed_market_evidence"
    )


def test_live_ledger_supersedes_older_formal_position(tmp_path: Path) -> None:
    formal = tmp_path / "formal.json"
    ledger = tmp_path / "ledger"
    _formal(formal, "2026-07-01", {"AAA": 1.0})
    _live_ledger(
        ledger,
        "2026-07-15",
        {"BBB": 0.5, "CCC": 0.5},
    )
    date, weights = load_previous_state(formal_package=formal, ledger_dir=ledger)
    assert date == "2026-07-15"
    assert weights == {"BBB": 0.5, "CCC": 0.5}


def test_newer_formal_position_supersedes_stale_live_ledger(tmp_path: Path) -> None:
    formal = tmp_path / "formal.json"
    ledger = tmp_path / "ledger"
    _formal(formal, "2026-07-15", {"AAA": 1.0})
    _live_ledger(ledger, "2026-07-01", {"BBB": 1.0})
    date, weights = load_previous_state(formal_package=formal, ledger_dir=ledger)
    assert date == "2026-07-15"
    assert weights == {"AAA": 1.0}


def test_us_ranker_snapshot_preserves_explicit_model_factor_order() -> None:
    library = load_factor_library(ROOT / "configs/factor_libraries/ohlcv.yaml")
    ids = [
        factor.factor_id for factor in library.factors_for_groups(["momentum_volatility_volume"])
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


def test_us_ranker_snapshot_accepts_new_canonical_factors_without_family_map() -> None:
    library = load_factor_library(ROOT / "configs/factor_libraries/ohlcv.yaml")
    ids = [
        factor.factor_id for factor in library.factors_for_groups(["us_short_reversal_liquidity"])
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


def test_cn_factor_mapping_matches_canonical_group() -> None:
    library = load_factor_library(ROOT / "configs/factor_libraries/ohlcv.yaml")
    ids = [factor.factor_id for factor in library.factors_for_groups(["cn_balanced_ohlcv"])]
    assert list(CN_FACTOR_COLUMNS) == ids


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
