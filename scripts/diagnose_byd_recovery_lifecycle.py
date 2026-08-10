#!/usr/bin/env python3
"""Diagnose the lifecycle failure of the frozen BYD recovery satellite.

Issue #736 is diagnostic only. It preserves the Phase 2 recovery state and
pointwise allocation mapping exactly, reproduces the accepted V1.2 Champion,
and explains executed recovery episodes without changing any model rule.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.byd_515180_allocation import prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    build_decisions as build_v12_decisions,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    run_financed_allocation,
)
from src.research.rules_based_allocation_experiment_runner import (
    _extract_inputs,
    _formal_daily,
    _formal_section,
    _load_formal,
    _load_spec,
    _trace_reproduction,
)

SPEC = PROJECT_ROOT / "configs/research_experiments/byd_v1_3_min_hold_bear_defense_certification_v1.yaml"
RECOVERY_THRESHOLD = 0.026937
PRIMARY_COST_BPS = 20.0
EPS = 1e-12
FORWARD_HORIZONS = (1, 3, 5, 10, 20)


def _wealth(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod()) if not clean.empty else 1.0


def _episodes(mask: pd.Series) -> pd.DataFrame:
    active = mask.fillna(False).astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    ids = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in active.groupby(ids):
        if pd.isna(raw_id):
            continue
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
            }
        )
    return pd.DataFrame(rows)


def _build_frozen_challenger(
    champion_decision: pd.DataFrame,
    base: pd.Series,
    factor: pd.Series,
) -> tuple[pd.DataFrame, pd.Series]:
    state = base.eq(0.75) & factor.ge(RECOVERY_THRESHOLD)
    challenger = champion_decision.copy(deep=True)
    challenger.loc[state, "byd_weight"] = 1.0
    challenger.loc[state, "etf_weight"] = 0.0
    challenger.loc[state, "cash_weight"] = 0.0
    changed = challenger.ne(champion_decision).any(axis=1)
    if not changed.equals(state.astype(bool)):
        raise AssertionError("lifecycle diagnostic drifted from frozen recovery state")
    if (changed & base.ne(0.75)).any():
        raise AssertionError("recovery state changed a non-defensive V1.2 core state")
    return challenger, state.astype(bool)


def _relative_open_return(
    common: pd.DataFrame,
    start_pos: int,
    end_pos: int,
) -> float | None:
    if end_pos < 0 or end_pos >= len(common) or start_pos < 0:
        return None
    start = common.index[start_pos]
    end = common.index[end_pos]
    if not bool(common.loc[start, "common_open_eligible"]):
        return None
    if not bool(common.loc[end, "common_open_eligible"]):
        return None
    byd_growth = float(common.loc[end, "byd_open"] / common.loc[start, "byd_open"])
    etf_growth = float(common.loc[end, "etf_open"] / common.loc[start, "etf_open"])
    return byd_growth / etf_growth - 1.0


def _forward_path(common: pd.DataFrame, start_pos: int) -> dict[str, Any]:
    forward: dict[str, float | None] = {}
    for horizon in FORWARD_HORIZONS:
        forward[str(horizon)] = _relative_open_return(common, start_pos, start_pos + horizon)

    path: list[tuple[int, float]] = []
    for horizon in range(1, 21):
        value = _relative_open_return(common, start_pos, start_pos + horizon)
        if value is not None:
            path.append((horizon, value))
    if not path:
        return {
            "forward_relative_returns": forward,
            "relative_mfe_20": None,
            "relative_mae_20": None,
            "time_to_mfe_sessions": None,
            "time_to_mae_sessions": None,
        }
    mfe_h, mfe = max(path, key=lambda item: item[1])
    mae_h, mae = min(path, key=lambda item: item[1])
    return {
        "forward_relative_returns": forward,
        "relative_mfe_20": float(mfe),
        "relative_mae_20": float(mae),
        "time_to_mfe_sessions": int(mfe_h),
        "time_to_mae_sessions": int(mae_h),
    }


def _source_signal_episode(
    common_index: pd.DatetimeIndex,
    signal_episodes: pd.DataFrame,
    executed_start: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp, int, pd.Timestamp]:
    start_pos = common_index.get_loc(executed_start)
    if not isinstance(start_pos, int) or start_pos <= 0:
        raise RuntimeError("executed recovery episode has no preceding decision session")
    source_date = common_index[start_pos - 1]
    matches = signal_episodes.loc[
        (signal_episodes["start"] <= source_date) & (signal_episodes["end"] >= source_date)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"cannot bind executed recovery at {executed_start.date()} to one signal episode"
        )
    row = matches.iloc[0]
    return (
        pd.Timestamp(row["start"]),
        pd.Timestamp(row["end"]),
        int(row["sessions"]),
        pd.Timestamp(source_date),
    )


def _classify_episode(row: dict[str, Any]) -> str:
    forward = row["forward_relative_returns"]
    r10 = forward.get("10")
    r20 = forward.get("20")
    prior5 = row["prior_5_session_relative_return"]
    mfe = row["relative_mfe_20"]
    mae = row["relative_mae_20"]
    exit_relative = row["relative_return_at_executed_exit"]
    time_to_mfe = row["time_to_mfe_sessions"]

    if row["core_100_within_3_sessions"]:
        return "E_core_overlap_redundancy"
    if (
        prior5 is not None
        and mfe is not None
        and r10 is not None
        and prior5 > 0.0
        and prior5 > max(mfe, 0.03)
        and r10 <= 0.0
    ):
        return "A_late_entry"
    if r10 is not None and r20 is not None and r10 <= 0.0 and r20 <= 0.0:
        return "B_false_recovery"
    if (
        mfe is not None
        and exit_relative is not None
        and time_to_mfe is not None
        and mfe >= 0.02
        and time_to_mfe < row["executed_sessions"]
        and exit_relative <= mfe * 0.5
    ):
        return "C_stale_persistence_late_exit"
    if (
        mae is not None
        and mae <= -0.05
        and ((r10 is not None and r10 > 0.0) or (r20 is not None and r20 > 0.0))
    ):
        return "D_oversized_rerisk_risk_asymmetry"
    return "useful_or_unclassified"


def _period_name(stamp: pd.Timestamp) -> str:
    if stamp < pd.Timestamp("2023-01-01"):
        return "development"
    if stamp < pd.Timestamp("2025-01-01"):
        return "fixed_validation"
    return "retrospective_2025_plus"


def _episode_ledger(
    *,
    common: pd.DataFrame,
    base: pd.Series,
    factor: pd.Series,
    recovery_state: pd.Series,
    champion_daily: pd.DataFrame,
    challenger_daily: pd.DataFrame,
) -> list[dict[str, Any]]:
    signal_episodes = _episodes(recovery_state)
    executed_delta = challenger_daily["position_byd_weight"].gt(
        champion_daily["position_byd_weight"] + EPS
    )
    executed_episodes = _episodes(executed_delta)
    rows: list[dict[str, Any]] = []

    for episode in executed_episodes.itertuples(index=False):
        executed_start = pd.Timestamp(episode.start)
        executed_end = pd.Timestamp(episode.end)
        start_pos = common.index.get_loc(executed_start)
        end_pos = common.index.get_loc(executed_end)
        if not isinstance(start_pos, int) or not isinstance(end_pos, int):
            raise RuntimeError("recovery episode index lookup is ambiguous")

        signal_start, signal_end, signal_sessions, source_date = _source_signal_episode(
            common.index, signal_episodes, executed_start
        )
        signal_start_pos = common.index.get_loc(signal_start)
        if not isinstance(signal_start_pos, int):
            raise RuntimeError("signal start index lookup is ambiguous")

        path = _forward_path(common, start_pos)
        prior5 = _relative_open_return(common, start_pos - 5, start_pos)
        exit_pos = min(end_pos + 1, len(common) - 1)
        exit_relative = _relative_open_return(common, start_pos, exit_pos)

        next_three = base.iloc[start_pos : min(start_pos + 4, len(base))]
        core_100_within_3 = bool(next_three.eq(1.0).any())
        core_first_100: str | None = None
        next_twenty = base.iloc[start_pos : min(start_pos + 21, len(base))]
        core_hits = next_twenty.loc[next_twenty.eq(1.0)]
        if not core_hits.empty:
            core_first_100 = pd.Timestamp(core_hits.index[0]).strftime("%Y-%m-%d")

        c_returns = challenger_daily.loc[executed_start:executed_end, "net_return"]
        b_returns = champion_daily.loc[executed_start:executed_end, "net_return"]
        episode_relative_wealth = _wealth(c_returns) / _wealth(b_returns) - 1.0

        row: dict[str, Any] = {
            "episode_id": int(episode.episode_id),
            "period": _period_name(executed_start),
            "year": int(executed_start.year),
            "signal_start": signal_start.strftime("%Y-%m-%d"),
            "signal_end": signal_end.strftime("%Y-%m-%d"),
            "signal_sessions": signal_sessions,
            "source_decision_date": source_date.strftime("%Y-%m-%d"),
            "first_executable_date": executed_start.strftime("%Y-%m-%d"),
            "executed_end": executed_end.strftime("%Y-%m-%d"),
            "executed_sessions": int(episode.sessions),
            "signal_to_execution_common_sessions": int(start_pos - signal_start_pos),
            "prior_5_session_relative_return": prior5,
            "relative_return_at_executed_exit": exit_relative,
            "actual_episode_relative_wealth": float(episode_relative_wealth),
            "core_100_within_3_sessions": core_100_within_3,
            "core_first_100_within_20_date": core_first_100,
            "entry_market_state": str(common.iloc[start_pos]["market_state"]),
            "entry_vol_state": str(common.iloc[start_pos]["vol_state"]),
            "entry_drawdown_252": float(common.iloc[start_pos]["drawdown_252"]),
            "entry_momentum_accel_20_60": float(common.iloc[start_pos]["momentum_accel_20_60"]),
            "entry_recovery_factor": float(factor.iloc[start_pos]),
            **path,
        }
        mfe_h = row["time_to_mfe_sessions"]
        row["factor_persisted_past_mfe"] = bool(
            mfe_h is not None and int(mfe_h) < int(episode.sessions)
        )
        row["primary_mechanism"] = _classify_episode(row)
        rows.append(row)
    return rows


def _aggregate(ledger: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    values = sorted({row[key] for row in ledger})
    output: list[dict[str, Any]] = []
    for value in values:
        subset = [row for row in ledger if row[key] == value]
        mechanisms: dict[str, int] = {}
        mechanism_relative_wealth_sum: dict[str, float] = {}
        for row in subset:
            mechanism = str(row["primary_mechanism"])
            mechanisms[mechanism] = mechanisms.get(mechanism, 0) + 1
            mechanism_relative_wealth_sum[mechanism] = (
                mechanism_relative_wealth_sum.get(mechanism, 0.0)
                + float(row["actual_episode_relative_wealth"])
            )
        output.append(
            {
                key: value,
                "episodes": len(subset),
                "executed_sessions": int(sum(int(row["executed_sessions"]) for row in subset)),
                "episode_relative_wealth_sum": float(
                    sum(float(row["actual_episode_relative_wealth"]) for row in subset)
                ),
                "mechanism_counts": mechanisms,
                "mechanism_relative_wealth_sum": mechanism_relative_wealth_sum,
            }
        )
    return output


def _dominant_negative_mechanism(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    negative: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in ledger:
        value = float(row["actual_episode_relative_wealth"])
        if value >= 0.0:
            continue
        mechanism = str(row["primary_mechanism"])
        negative[mechanism] = negative.get(mechanism, 0.0) + value
        counts[mechanism] = counts.get(mechanism, 0) + 1
    if not negative:
        return {"mechanism": None, "negative_relative_wealth_sum": 0.0, "episodes": 0}
    dominant = min(negative, key=negative.get)
    return {
        "mechanism": dominant,
        "negative_relative_wealth_sum": float(negative[dominant]),
        "episodes": int(counts[dominant]),
        "all_negative_mechanism_sums": negative,
    }


def run() -> dict[str, Any]:
    spec = _load_spec(SPEC)
    with tempfile.TemporaryDirectory(prefix="byd-recovery-lifecycle-") as raw_root:
        root = Path(raw_root)
        byd_dir, etf_dir, data_identity = _extract_inputs(spec, root)
        common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
        cutoff = pd.Timestamp(str(spec["data"]["historical_cutoff"]))
        common = common.loc[:cutoff].copy()
        signals = signals.reindex(common.index)

        standard_results, _ = run_v12_candidates(
            common,
            signals,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        formal = _load_formal(spec)
        performance_path, performance_sha = _formal_section(
            formal,
            "performance",
            str(spec["baseline"]["performance_sha256"]),
        )
        formal_daily = _formal_daily(performance_path, str(cutoff.date()))
        formal_trace = _trace_reproduction(
            formal_daily, standard_results[V12_MODEL_ID].daily
        )
        if not formal_trace["exact"]:
            raise RuntimeError("lifecycle diagnostic refuses a non-exact V1.2 Champion")

        decisions, _ = build_v12_decisions(common, signals)
        champion_decision = decisions[V12_MODEL_ID]
        champion = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        rebuilt_trace = _trace_reproduction(formal_daily, champion.daily)
        if not rebuilt_trace["exact"]:
            raise RuntimeError("rebuilt V1.2 path does not match accepted formal trace")

        canonical = load_canonical_snapshot(byd_dir)
        full = build_research_dataset(canonical.adjusted, canonical.sessions)
        full.index = pd.to_datetime(full.index).normalize()
        factor = full["drawdown252_x_rebound60"].reindex(common.index).astype(float)
        base = signals["base_byd_weight"].astype(float)
        challenger_decision, recovery_state = _build_frozen_challenger(
            champion_decision, base, factor
        )
        challenger = run_financed_allocation(
            "byd_recovery_satellite_drawdown252_rebound60_v1",
            common,
            challenger_decision,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )

        ledger = _episode_ledger(
            common=common,
            base=base,
            factor=factor,
            recovery_state=recovery_state,
            champion_daily=champion.daily,
            challenger_daily=challenger.daily,
        )

    by_year = _aggregate(ledger, "year")
    by_period = _aggregate(ledger, "period")
    year_sessions = {int(row["year"]): int(row["executed_sessions"]) for row in by_year}
    expected = {2022: 47, 2025: 0, 2026: 20}
    for year, sessions in expected.items():
        actual = year_sessions.get(year, 0)
        if actual != sessions:
            raise RuntimeError(
                f"Phase 2 lifecycle tie-out failed for {year}: {actual} != {sessions}"
            )

    return {
        "schema_version": "1.0",
        "issue": 736,
        "diagnostic": "byd_recovery_lifecycle_v1",
        "research_only": True,
        "historical_evidence_consumed": True,
        "parameter_changes": False,
        "candidate_construction": False,
        "frozen_state": {
            "threshold": RECOVERY_THRESHOLD,
            "expression": "base_byd_weight == 0.75 and drawdown252_x_rebound60 >= 0.026937",
            "allocation_mapping": "75% BYD + 25% 515180 -> 100% BYD while decision state is true",
        },
        "classification_contract": {
            "priority": [
                "E_core_overlap_redundancy",
                "A_late_entry",
                "B_false_recovery",
                "C_stale_persistence_late_exit",
                "D_oversized_rerisk_risk_asymmetry",
                "useful_or_unclassified",
            ],
            "core_overlap_sessions": 3,
            "stale_mfe_floor": 0.02,
            "stale_giveback_fraction": 0.50,
            "risk_asymmetry_mae_ceiling": -0.05,
        },
        "baseline": {
            "model_id": V12_MODEL_ID,
            "bundle_id": formal.bundle_id,
            "performance_sha256": performance_sha,
            "formal_trace_reproduction": formal_trace,
            "rebuilt_trace_reproduction": rebuilt_trace,
        },
        "data_identity": data_identity,
        "episodes": ledger,
        "summary_by_year": by_year,
        "summary_by_period": by_period,
        "dominant_negative_mechanism": _dominant_negative_mechanism(ledger),
        "phase2_session_tieout": {
            "expected": expected,
            "actual": {year: year_sessions.get(year, 0) for year in expected},
            "exact": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts/research/byd_recovery_lifecycle_v1.json",
    )
    args = parser.parse_args()
    payload = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
