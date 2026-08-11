from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.research.byd_v1_3_low_vol_prospective import (
    CANDIDATE_MODEL_ID,
    CHAMPION_MODEL_ID,
    EVENT_MODEL_ID,
    HOLD_ELIGIBLE_SESSIONS,
    SOURCE_SCHEMA_VERSION,
    build_lifecycle,
    build_observations,
)


def _source_row(
    date: str,
    *,
    edge: bool = False,
    vol_state: str = "low",
    prospective: bool = True,
    common: bool = True,
    base: float = 0.75,
) -> dict[str, object]:
    etf = 1.0 - base
    target = {"byd_weight": base, "etf_weight": etf, "cash_weight": 0.0}
    return {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "signal_date": date,
        "observed_at_utc": f"{date}T12:00:00+00:00",
        "data_version": f"source-{date}",
        "common_open_eligible": common,
        "prospective_eligible": prospective,
        "champion": {"base_byd_weight": base},
        "detector": {
            "threshold": 0.026937,
            "drawdown252_x_rebound60": 0.03,
            "active": edge,
            "event_edge": edge,
        },
        "factors": {
            "market_state": "bear",
            "vol_state": vol_state,
            "mom_20": 0.0,
            "mom_60": 0.0,
            "drawdown_252": -0.2,
            "distance_from_low_60": 0.1,
        },
        "prices": {"byd_open": 100.0, "etf_open": 1.0},
        "targets": {
            CHAMPION_MODEL_ID: dict(target),
            EVENT_MODEL_ID: dict(target),
        },
    }


def test_prelaunch_seed_never_starts_lifecycle() -> None:
    rows = [_source_row("2026-08-10", edge=True, vol_state="low", prospective=False)]
    state = build_lifecycle(rows)
    assert not bool(state.iloc[0]["lifecycle_started"])
    assert not bool(state.iloc[0]["overlay_decision_active"])


def test_high_vol_edge_is_not_caught_up_later() -> None:
    rows = [
        _source_row("2026-08-10", prospective=False),
        _source_row("2026-08-11", edge=True, vol_state="high"),
        _source_row("2026-08-12", edge=False, vol_state="low"),
    ]
    state = build_lifecycle(rows)
    assert not bool(state.loc[pd.Timestamp("2026-08-11"), "lifecycle_started"])
    assert not bool(state.loc[pd.Timestamp("2026-08-12"), "lifecycle_started"])


def test_low_vol_edge_starts_and_detector_flicker_does_not_exit() -> None:
    rows = [
        _source_row("2026-08-10", prospective=False),
        _source_row("2026-08-11", edge=True, vol_state="low"),
        _source_row("2026-08-12", edge=False, vol_state="high"),
        _source_row("2026-08-13", edge=False, vol_state="high"),
    ]
    state = build_lifecycle(rows)
    assert bool(state.loc[pd.Timestamp("2026-08-11"), "lifecycle_started"])
    assert state.loc[pd.Timestamp("2026-08-11") :, "overlay_decision_active"].all()


def test_core_recovery_terminates_low_vol_lifecycle() -> None:
    rows = [
        _source_row("2026-08-10", prospective=False),
        _source_row("2026-08-11", edge=True, vol_state="low"),
        _source_row("2026-08-12"),
        _source_row("2026-08-13", base=1.0),
    ]
    state = build_lifecycle(rows)
    exit_row = state.loc[pd.Timestamp("2026-08-13")]
    assert not bool(exit_row["overlay_decision_active"])
    assert exit_row["termination_on_decision"] == "core_recovered"


def test_hold_counter_advances_only_on_common_eligible_opens() -> None:
    rows = [_source_row("2026-08-10", prospective=False)]
    rows.append(_source_row("2026-08-11", edge=True, vol_state="low"))
    for offset in range(2, HOLD_ELIGIBLE_SESSIONS + 5):
        date = (pd.Timestamp("2026-08-10") + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
        rows.append(_source_row(date, common=offset not in {5, 8}))
    state = build_lifecycle(rows)
    active = state["overlay_decision_active"].astype(bool)
    executed = 0
    for position in range(1, len(state)):
        if bool(active.iloc[position - 1]) and bool(rows[position]["common_open_eligible"]):
            executed += 1
    assert executed >= HOLD_ELIGIBLE_SESSIONS
    termination = state["termination_on_decision"].eq("max_hold")
    assert termination.any()


def test_build_observations_preserves_prelaunch_seed_and_source_hash(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    observations = source_root / "observations"
    observations.mkdir(parents=True)
    seed = _source_row("2026-08-10", edge=True, vol_state="high", prospective=False)
    (observations / "2026-08-10.json").write_text(
        json.dumps(seed, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    built = build_observations(source_store=source_root, existing_records=[])

    assert len(built) == 1
    row = built[0]
    assert "candidate_model_id" not in row
    assert row["prelaunch_seed"] is True
    assert row["prospective_eligible"] is False
    assert row["status"] == "prelaunch_seed"
    assert row["entry_confirmation"]["passed_on_edge"] is False
    assert row["targets"][CANDIDATE_MODEL_ID] == row["targets"][CHAMPION_MODEL_ID]
    assert len(row["source"]["recovery_event_observation_sha256"]) == 64


def test_new_observations_carry_explicit_candidate_identity(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    observations = source_root / "observations"
    observations.mkdir(parents=True)
    row = _source_row("2026-08-12", edge=False, vol_state="high", prospective=True)
    (observations / "2026-08-12.json").write_text(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    built = build_observations(source_store=source_root, existing_records=[])

    assert built[0]["candidate_model_id"] == CANDIDATE_MODEL_ID
