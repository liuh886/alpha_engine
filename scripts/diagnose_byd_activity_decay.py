#!/usr/bin/env python3
"""Diagnose whether BYD post-2024 inactivity is healthy persistence or under-response.

This is a diagnostic-only companion to Issue #729. It reuses the frozen BYD
v1.3 Research Loop mission solely for immutable input and formal-baseline
identity, then decomposes the maintained V1.2/V1.3 paths without changing any
model parameter, threshold, execution rule, cost assumption, or promotion gate.
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
    BASELINE as V11_MODEL_ID,
    CANDIDATE as V12_MODEL_ID,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    RULES as EXPANSION_RULES,
)
from src.research.byd_v1_3_candidate import (
    build_v13_signals,
    run_v13_candidate,
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
PRIMARY_COST_BPS = 20.0
EPS = 1e-9


def _wealth(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod()) if not clean.empty else 1.0


def _episode_table(mask: pd.Series) -> pd.DataFrame:
    active = mask.fillna(False).astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    ids = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in active.groupby(ids):
        if pd.isna(raw_id):
            continue
        index = block.index
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": index.min(),
                "end": index.max(),
                "sessions": int(len(index)),
            }
        )
    return pd.DataFrame(rows)


def _period_key(index: pd.DatetimeIndex, frequency: str) -> pd.Index:
    if frequency == "year":
        return pd.Index(index.year.astype(str), name="period")
    if frequency == "quarter":
        return pd.Index(index.to_period("Q").astype(str), name="period")
    raise ValueError(f"unsupported frequency: {frequency}")


def _period_for_stamp(stamp: pd.Timestamp, frequency: str) -> str:
    if frequency == "year":
        return str(stamp.year)
    return str(stamp.to_period("Q"))


def _period_return(daily: pd.DataFrame, index: pd.DatetimeIndex) -> float:
    selected = daily.reindex(index)["net_return"]
    return _wealth(selected) - 1.0


def _buy_hold_return(series: pd.Series, index: pd.DatetimeIndex) -> float:
    return _wealth(series.reindex(index)) - 1.0


def _relative_wealth(
    challenger: pd.DataFrame,
    champion: pd.DataFrame,
    index: pd.DatetimeIndex,
) -> float:
    return (
        _wealth(challenger.reindex(index)["net_return"])
        / _wealth(champion.reindex(index)["net_return"])
        - 1.0
    )


def _near_miss_expansion(common: pd.DataFrame, base: pd.Series) -> dict[str, pd.Series]:
    conditions = {
        "base_100": base.eq(EXPANSION_RULES["entry_base_byd_weight"]),
        "market_bull": common["market_state"].eq(EXPANSION_RULES["entry_market_state"]),
        "vol_low": common["vol_state"].eq(EXPANSION_RULES["entry_vol_state"]),
        "mom20_positive": common["mom_20"].gt(EXPANSION_RULES["entry_mom_20_floor"]),
        "mom60_positive": common["mom_60"].gt(EXPANSION_RULES["entry_mom_60_floor"]),
        "drawdown_above_floor": common["drawdown_252"].gt(
            EXPANSION_RULES["entry_drawdown_252_floor"]
        ),
    }
    output: dict[str, pd.Series] = {}
    for name, condition in conditions.items():
        others = pd.Series(True, index=common.index)
        for other_name, other_condition in conditions.items():
            if other_name != name:
                others &= other_condition
        output[name] = others & ~condition
    return output


def _summary_by_period(
    *,
    frequency: str,
    common: pd.DataFrame,
    v12_base: pd.Series,
    v13_signals: pd.DataFrame,
    v12_daily: pd.DataFrame,
    v11_daily: pd.DataFrame,
    v13_daily: pd.DataFrame,
    v12_diag: pd.DataFrame,
    v13_diag: pd.DataFrame,
) -> list[dict[str, Any]]:
    base_risk_on = v12_base.ge(0.999)
    v12_base_transition = base_risk_on.ne(base_risk_on.shift(1)).fillna(False)
    v13_risk_on = v13_signals["base_risk_on"].gt(0.5)
    v13_base_transition = v13_risk_on.ne(v13_risk_on.shift(1)).fillna(False)

    v12_expansion = v12_daily["borrowed_weight"].gt(EPS)
    v13_expansion = v13_daily["borrowed_weight"].gt(EPS)
    bear_defense = v13_signals["is_bear"] & ~v13_risk_on

    v12_expansion_episodes = _episode_table(v12_expansion)
    v13_expansion_episodes = _episode_table(v13_expansion)
    bear_episodes = _episode_table(bear_defense)

    entry_trend = common["close"].gt(common["sma_120"])
    entry_mom = common["mom_20"].gt(0.0)
    exit_trend = common["close"].lt(common["sma_120"])
    exit_mom = common["mom_60"].lt(0.0)
    raw_entry = entry_trend & entry_mom
    raw_exit = exit_trend & exit_mom
    entry_trend_only = entry_trend & ~entry_mom
    entry_momentum_only = ~entry_trend & entry_mom
    exit_trend_only = exit_trend & ~exit_mom
    exit_momentum_only = ~exit_trend & exit_mom

    prior_v13_risk_on = v13_risk_on.shift(1, fill_value=False)
    blocked_min_hold_exit = raw_exit & prior_v13_risk_on & v13_risk_on

    expansion_near_miss = _near_miss_expansion(common, v12_base)
    base_unchanged = ~v12_base_transition

    turnover = v12_daily["turnover_units"].fillna(0.0)
    turnover_buckets = {
        "micro_lt_0_02": turnover.gt(EPS) & turnover.lt(0.02),
        "small_0_02_0_10": turnover.ge(0.02) & turnover.lt(0.10),
        "medium_0_10_0_25": turnover.ge(0.10) & turnover.lt(0.25),
        "major_ge_0_25": turnover.ge(0.25),
    }

    v12_byd_contribution = (
        v12_daily["position_byd_weight"] * v12_daily["byd_return"]
    )
    v12_etf_contribution = (
        v12_daily["position_etf_weight"] * v12_daily["etf_return"]
    )
    defensive = v12_base.eq(0.75)
    defensive_alt_return = (
        0.75 * common["byd_open_return"] + 0.25 * common["etf_open_return"]
    )
    defensive_opportunity_cost = (
        common["byd_open_return"] - defensive_alt_return
    ).where(defensive, 0.0)

    period_keys = _period_key(common.index, frequency)
    rows: list[dict[str, Any]] = []
    for period in sorted(period_keys.unique()):
        mask = period_keys == period
        index = common.index[mask]
        if len(index) == 0:
            continue

        abs_move = common.loc[index, "byd_open_return"].abs().sum()
        unchanged_abs_move = common.loc[
            index.intersection(base_unchanged.index[base_unchanged]), "byd_open_return"
        ].abs().sum()

        def episode_stats(table: pd.DataFrame) -> tuple[int, float, int]:
            if table.empty:
                return 0, 0.0, 0
            selected = table.loc[
                table["start"].map(lambda stamp: _period_for_stamp(stamp, frequency))
                == period
            ]
            if selected.empty:
                return 0, 0.0, 0
            return (
                int(len(selected)),
                float(selected["sessions"].median()),
                int(selected["sessions"].max()),
            )

        v12_ep_count, v12_ep_median, v12_ep_max = episode_stats(v12_expansion_episodes)
        v13_ep_count, v13_ep_median, v13_ep_max = episode_stats(v13_expansion_episodes)
        bear_ep_count, bear_ep_median, bear_ep_max = episode_stats(bear_episodes)

        v12_period_daily = v12_daily.reindex(index)
        row: dict[str, Any] = {
            "period": str(period),
            "sessions": int(len(index)),
            "v12_base_transitions": int(v12_base_transition.reindex(index).fillna(False).sum()),
            "v13_base_transitions": int(v13_base_transition.reindex(index).fillna(False).sum()),
            "v12_expansion_episodes": v12_ep_count,
            "v12_expansion_median_sessions": v12_ep_median,
            "v12_expansion_max_sessions": v12_ep_max,
            "v13_expansion_episodes": v13_ep_count,
            "v13_expansion_median_sessions": v13_ep_median,
            "v13_expansion_max_sessions": v13_ep_max,
            "v13_bear_defense_episodes": bear_ep_count,
            "v13_bear_defense_median_sessions": bear_ep_median,
            "v13_bear_defense_max_sessions": bear_ep_max,
            "v12_financed_sessions": int(v12_expansion.reindex(index).fillna(False).sum()),
            "v13_financed_sessions": int(v13_expansion.reindex(index).fillna(False).sum()),
            "share_v12_base_75": float(v12_base.reindex(index).eq(0.75).mean()),
            "share_v12_base_100": float(v12_base.reindex(index).ge(0.999).mean()),
            "share_v12_executed_gt_100": float(
                v12_period_daily["position_byd_weight"].gt(1.0 + EPS).mean()
            ),
            "raw_base_entry_hits": int(raw_entry.reindex(index).fillna(False).sum()),
            "raw_base_exit_hits": int(raw_exit.reindex(index).fillna(False).sum()),
            "entry_near_miss_trend_only": int(
                entry_trend_only.reindex(index).fillna(False).sum()
            ),
            "entry_near_miss_momentum_only": int(
                entry_momentum_only.reindex(index).fillna(False).sum()
            ),
            "exit_near_miss_trend_only": int(
                exit_trend_only.reindex(index).fillna(False).sum()
            ),
            "exit_near_miss_momentum_only": int(
                exit_momentum_only.reindex(index).fillna(False).sum()
            ),
            "v13_min_hold_blocked_exit_hits": int(
                blocked_min_hold_exit.reindex(index).fillna(False).sum()
            ),
            "raw_expansion_entry_hits": int(
                v12_diag["entry"].reindex(index).fillna(False).sum()
            ),
            "raw_expansion_exit_hits": int(
                v12_diag["exit"].reindex(index).fillna(False).sum()
            ),
            "common_open_eligibility_share": float(
                common.loc[index, "common_open_eligible"].mean()
            ),
            "v12_strategy_return": _period_return(v12_daily, index),
            "v13_strategy_return": _period_return(v13_daily, index),
            "byd_buy_hold_return": _buy_hold_return(common["byd_open_return"], index),
            "etf_buy_hold_return": _buy_hold_return(common["etf_open_return"], index),
            "v13_vs_v12_relative_wealth": _relative_wealth(v13_daily, v12_daily, index),
            "v12_vs_v11_expansion_relative_wealth": _relative_wealth(
                v12_daily, v11_daily, index
            ),
            "v12_byd_arithmetic_contribution": float(
                v12_byd_contribution.reindex(index).fillna(0.0).sum()
            ),
            "v12_etf_arithmetic_contribution": float(
                v12_etf_contribution.reindex(index).fillna(0.0).sum()
            ),
            "defensive_state_arithmetic_opportunity_cost": float(
                defensive_opportunity_cost.reindex(index).fillna(0.0).sum()
            ),
            "absolute_byd_move_sum": float(abs_move),
            "unchanged_base_state_absolute_move_share": (
                float(unchanged_abs_move / abs_move) if abs_move > 0.0 else 0.0
            ),
        }
        for name, bucket in turnover_buckets.items():
            row[f"turnover_events_{name}"] = int(
                bucket.reindex(index).fillna(False).sum()
            )
        for name, near_miss in expansion_near_miss.items():
            row[f"expansion_entry_near_miss_{name}"] = int(
                near_miss.reindex(index).fillna(False).sum()
            )
        rows.append(row)
    return rows


def _post_2024_diagnosis(annual: list[dict[str, Any]]) -> dict[str, Any]:
    by_year = {row["period"]: row for row in annual}
    pre = [row for year, row in by_year.items() if year <= "2024"]
    post = [row for year, row in by_year.items() if year >= "2025"]

    def per_252(rows: list[dict[str, Any]], key: str) -> float:
        sessions = sum(float(row["sessions"]) for row in rows)
        total = sum(float(row[key]) for row in rows)
        return total / sessions * 252.0 if sessions else 0.0

    pre_transitions = per_252(pre, "v12_base_transitions")
    post_transitions = per_252(post, "v12_base_transitions")
    pre_entry_hits = per_252(pre, "raw_base_entry_hits")
    post_entry_hits = per_252(post, "raw_base_entry_hits")
    pre_expansion_hits = per_252(pre, "raw_expansion_entry_hits")
    post_expansion_hits = per_252(post, "raw_expansion_entry_hits")
    post_eligibility = float(
        np.average(
            [row["common_open_eligibility_share"] for row in post],
            weights=[row["sessions"] for row in post],
        )
    ) if post else 0.0
    post_unchanged_move_share = float(
        np.average(
            [row["unchanged_base_state_absolute_move_share"] for row in post],
            weights=[row["absolute_byd_move_sum"] for row in post],
        )
    ) if post and sum(row["absolute_byd_move_sum"] for row in post) > 0 else 0.0

    causes: list[str] = []
    if post_eligibility < 0.98:
        causes.append("D_execution_or_data_suppression")
    if post_entry_hits < pre_entry_hits * 0.70 or post_expansion_hits < pre_expansion_hits * 0.70:
        causes.append("B_trigger_scarcity")
    if post_transitions < pre_transitions * 0.70 and post_unchanged_move_share >= 0.80:
        causes.append("C_state_model_under_response")
    if not causes or (
        post_transitions >= pre_transitions * 0.70 and post_unchanged_move_share < 0.80
    ):
        causes.append("A_healthy_persistence")

    return {
        "pre_2025_v12_base_transitions_per_252": pre_transitions,
        "post_2024_v12_base_transitions_per_252": post_transitions,
        "pre_2025_raw_base_entry_hits_per_252": pre_entry_hits,
        "post_2024_raw_base_entry_hits_per_252": post_entry_hits,
        "pre_2025_raw_expansion_entry_hits_per_252": pre_expansion_hits,
        "post_2024_raw_expansion_entry_hits_per_252": post_expansion_hits,
        "post_2024_common_open_eligibility_share": post_eligibility,
        "post_2024_unchanged_base_state_absolute_move_share": post_unchanged_move_share,
        "classified_causes": causes,
    }


def run() -> dict[str, Any]:
    spec = _load_spec(SPEC)
    with tempfile.TemporaryDirectory(prefix="byd-activity-") as raw_root:
        root = Path(raw_root)
        byd_dir, etf_dir, data_identity = _extract_inputs(spec, root)
        common, v12_signals, _ = prepare_common_dataset(byd_dir, etf_dir)
        cutoff = pd.Timestamp(str(spec["data"]["historical_cutoff"]))
        common = common.loc[:cutoff].copy()
        v12_signals = v12_signals.reindex(common.index)

        v12_results, v12_diag = run_v12_candidates(
            common,
            v12_signals,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        v12_daily = v12_results[V12_MODEL_ID].daily
        v11_daily = v12_results[V11_MODEL_ID].daily

        canonical = load_canonical_snapshot(byd_dir)
        full_byd = build_research_dataset(canonical.adjusted, canonical.sessions)
        full_byd.index = pd.to_datetime(full_byd.index).normalize()
        v13_signals = build_v13_signals(full_byd, target_index=common.index)
        v13_result, v13_diag = run_v13_candidate(
            common,
            v13_signals,
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
        trace = _trace_reproduction(formal_daily, v12_daily)
        if not trace["exact"]:
            raise RuntimeError("BYD activity diagnostic refuses non-exact V1.2 baseline")

        annual = _summary_by_period(
            frequency="year",
            common=common,
            v12_base=v12_signals["base_byd_weight"],
            v13_signals=v13_signals,
            v12_daily=v12_daily,
            v11_daily=v11_daily,
            v13_daily=v13_result.daily,
            v12_diag=v12_diag,
            v13_diag=v13_diag,
        )
        quarterly = _summary_by_period(
            frequency="quarter",
            common=common,
            v12_base=v12_signals["base_byd_weight"],
            v13_signals=v13_signals,
            v12_daily=v12_daily,
            v11_daily=v11_daily,
            v13_daily=v13_result.daily,
            v12_diag=v12_diag,
            v13_diag=v13_diag,
        )

    return {
        "schema_version": "1.0",
        "issue": 729,
        "diagnostic": "byd_post_2024_activity_decay_and_opportunity_coverage",
        "research_only": True,
        "parameter_changes": False,
        "historical_evidence_consumed": True,
        "baseline": {
            "model_id": V12_MODEL_ID,
            "bundle_id": formal.bundle_id,
            "performance_sha256": performance_sha,
            "trace_reproduction": trace,
        },
        "data_identity": data_identity,
        "turnover_bucket_contract": {
            "micro_lt_0_02": "0 < turnover_units < 0.02",
            "small_0_02_0_10": "0.02 <= turnover_units < 0.10",
            "medium_0_10_0_25": "0.10 <= turnover_units < 0.25",
            "major_ge_0_25": "turnover_units >= 0.25",
        },
        "activity_by_year": annual,
        "activity_by_quarter": quarterly,
        "opportunity_coverage": _post_2024_diagnosis(annual),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts/research/byd_post_2024_activity_diagnostic.json",
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
