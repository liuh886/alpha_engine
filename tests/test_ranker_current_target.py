from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.factors.ranker_snapshot import build_ranker_factor_snapshot
from src.factors.library import load_factor_library
from src.research.ranker_current_target import (
    CN_FACTOR_COLUMNS,
    RankerCurrentTargetError,
    _select_cn_sector_breadth,
    load_previous_state,
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


def test_live_ledger_supersedes_older_formal_position(tmp_path: Path) -> None:
    formal = tmp_path / "formal.json"
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _formal(formal, "2026-07-01", {"AAA": 1.0})
    (ledger / "latest.json").write_text(
        json.dumps(
            {
                "signal_date": "2026-07-15",
                "target_weights": {"BBB": 0.5, "CCC": 0.5},
            }
        ),
        encoding="utf-8",
    )
    date, weights = load_previous_state(formal_package=formal, ledger_dir=ledger)
    assert date == "2026-07-15"
    assert weights == {"BBB": 0.5, "CCC": 0.5}


def test_newer_formal_position_supersedes_stale_live_ledger(tmp_path: Path) -> None:
    formal = tmp_path / "formal.json"
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    _formal(formal, "2026-07-15", {"AAA": 1.0})
    (ledger / "latest.json").write_text(
        json.dumps(
            {
                "signal_date": "2026-07-01",
                "target_weights": {"BBB": 1.0},
            }
        ),
        encoding="utf-8",
    )
    date, weights = load_previous_state(formal_package=formal, ledger_dir=ledger)
    assert date == "2026-07-15"
    assert weights == {"AAA": 1.0}


def test_us_ranker_snapshot_uses_exact_canonical_group_order() -> None:
    library = load_factor_library(ROOT / "configs/factor_libraries/ohlcv.yaml")
    ids = [
        factor.factor_id
        for factor in library.factors_for_groups(["momentum_volatility_volume"])
    ]
    snapshot = build_ranker_factor_snapshot(
        model_family_id="us_ranker",
        signal_date="2026-08-07",
        latest_data_date="2026-08-07",
        factor_values={factor_id: float(index) for index, factor_id in enumerate(ids)},
        factor_references={},
        data_freshness_ok=True,
    )
    assert snapshot["groups"] == ["momentum_volatility_volume"]
    assert [row["factor_id"] for row in snapshot["factors"]] == ids
    assert snapshot["freshness"] == "current"


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
