#!/usr/bin/env python3
"""Evaluate one pre-registered low-vol confirmation for the BYD recovery event.

Issue #744 changes exactly one thing relative to the frozen #739 event lifecycle:
a recovery detector edge may start a lifecycle only when ``vol_state == low`` on
that same decision date. Historical evidence is consumed and cannot authorize
promotion.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import scripts.evaluate_byd_recovery_event_lifecycle as base
from src.common.runtime_settings import PROJECT_ROOT
from src.research.byd_515180_allocation import WINDOWS, metrics, prepare_common_dataset
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
    STRESS_FINANCING_RATE,
    run_financed_allocation,
)

ISSUE = 744
CHALLENGER = "byd_v1_3_recovery_event_low_vol_confirmation_v1"
PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
EPS = 1e-12


def _low_vol_event_decision(
    champion_decision: pd.DataFrame,
    base_target: pd.Series,
    detector: pd.Series,
    eligible: pd.Series,
    vol_state: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    index = detector.index
    for value in (champion_decision, base_target, eligible, vol_state):
        if not value.index.equals(index):
            raise ValueError("low-vol event inputs must share one index")

    edge = detector & ~detector.shift(1, fill_value=False)
    confirmed_edge = edge & vol_state.eq("low")
    active = False
    remaining = 0
    lifecycle_id = 0
    rows: list[dict[str, Any]] = []

    for i, date in enumerate(index):
        termination = ""
        if active and float(base_target.iloc[i]) >= 1.0 - EPS:
            active = False
            remaining = 0
            termination = "core_recovered"

        started = False
        if (
            not active
            and bool(confirmed_edge.iloc[i])
            and np.isclose(float(base_target.iloc[i]), 0.75)
        ):
            active = True
            remaining = base.HOLD_ELIGIBLE_SESSIONS
            lifecycle_id += 1
            started = True

        overlay = active and np.isclose(float(base_target.iloc[i]), 0.75)
        rows.append(
            {
                "detector": bool(detector.iloc[i]),
                "event_edge": bool(edge.iloc[i]),
                "low_vol_confirmed_edge": bool(confirmed_edge.iloc[i]),
                "entry_vol_state": str(vol_state.iloc[i]),
                "lifecycle_started": started,
                "lifecycle_id": lifecycle_id if overlay else 0,
                "overlay_decision_active": overlay,
                "remaining_eligible_sessions_before_decision": remaining if overlay else 0,
                "termination_on_decision": termination,
            }
        )

        next_open_eligible = i + 1 < len(eligible) and bool(eligible.iloc[i + 1])
        if overlay and next_open_eligible:
            remaining -= 1
            if remaining <= 0:
                active = False
                remaining = 0
                rows[-1]["termination_on_decision"] = "max_hold"

    state = pd.DataFrame(rows, index=index)
    overlay = state["overlay_decision_active"].astype(bool)
    decision = champion_decision.copy(deep=True)
    decision.loc[overlay, "byd_weight"] = 1.0
    decision.loc[overlay, "etf_weight"] = 0.0
    decision.loc[overlay, "cash_weight"] = 0.0
    changed = decision.ne(champion_decision).any(axis=1)
    if not changed.equals(overlay):
        raise AssertionError("low-vol lifecycle changed outside its declared overlay")
    if (changed & base_target.ne(0.75)).any():
        raise AssertionError("low-vol lifecycle changed a non-defensive core state")
    if not np.allclose(decision.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("low-vol lifecycle weights do not sum to one")
    return decision, state


def _window_metrics(daily: pd.DataFrame, window: str) -> dict[str, float]:
    start, end = WINDOWS[window]
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    result = metrics(block)
    returns = block["net_return"].dropna()
    result["turnover_units"] = float(block.loc[returns.index, "turnover_units"].sum())
    return result


def _evaluate(
    common: pd.DataFrame,
    champion_decision: pd.DataFrame,
    frozen_event_decision: pd.DataFrame,
    candidate_decision: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    for scenario, cost_bps, financing_rate in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE),
    ):
        champion = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        frozen = run_financed_allocation(
            base.CHALLENGER,
            common,
            frozen_event_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        candidate = run_financed_allocation(
            CHALLENGER,
            common,
            candidate_decision,
            cost_bps=cost_bps,
            annual_financing_rate=financing_rate,
        )
        results[scenario] = {
            "champion": champion,
            "frozen_event": frozen,
            "candidate": candidate,
        }
        for window, (start, end) in WINDOWS.items():
            champion_metrics = _window_metrics(champion.daily, window)
            frozen_metrics = _window_metrics(frozen.daily, window)
            candidate_metrics = _window_metrics(candidate.daily, window)
            rows.append(
                {
                    "scenario": scenario,
                    "window": window,
                    "champion": champion_metrics,
                    "frozen_event": frozen_metrics,
                    "candidate": candidate_metrics,
                    "candidate_minus_champion": {
                        "cagr": candidate_metrics["cagr"] - champion_metrics["cagr"],
                        "sharpe": candidate_metrics["sharpe"] - champion_metrics["sharpe"],
                        "max_drawdown": candidate_metrics["max_drawdown"]
                        - champion_metrics["max_drawdown"],
                        "relative_terminal_wealth": base._relative_wealth(
                            candidate.daily, champion.daily, start, end
                        ),
                    },
                    "candidate_minus_frozen_event": {
                        "cagr": candidate_metrics["cagr"] - frozen_metrics["cagr"],
                        "sharpe": candidate_metrics["sharpe"] - frozen_metrics["sharpe"],
                        "relative_terminal_wealth": base._relative_wealth(
                            candidate.daily, frozen.daily, start, end
                        ),
                    },
                }
            )
    return rows, results


def _annual(
    champion: pd.DataFrame,
    frozen: pd.DataFrame,
    candidate: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in sorted(set(champion.index.year)):
        idx = champion.index[champion.index.year == year]
        rows.append(
            {
                "year": int(year),
                "candidate_vs_champion_relative_wealth": base._wealth(
                    candidate.loc[idx, "net_return"]
                )
                / base._wealth(champion.loc[idx, "net_return"])
                - 1.0,
                "candidate_vs_frozen_event_relative_wealth": base._wealth(
                    candidate.loc[idx, "net_return"]
                )
                / base._wealth(frozen.loc[idx, "net_return"])
                - 1.0,
            }
        )
    return rows


def _gates(
    evaluation: list[dict[str, Any]],
    period: list[dict[str, Any]],
    annual: list[dict[str, Any]],
    formal_exact: bool,
) -> dict[str, Any]:
    keyed = {(row["scenario"], row["window"]): row for row in evaluation}
    full = keyed[("primary", "full_overlap")]
    fixed = keyed[("primary", "fixed_validation")]
    recent = keyed[("primary", "retrospective_2025_plus")]
    stress_full = keyed[("stress", "full_overlap")]
    stress_recent = keyed[("stress", "retrospective_2025_plus")]
    y2026 = next(row for row in annual if row["year"] == 2026)
    max_period_share = max(
        (float(row["positive_contribution_share"]) for row in period),
        default=0.0,
    )
    candidate_turnover = float(full["candidate"]["turnover_units"])
    frozen_turnover = float(full["frozen_event"]["turnover_units"])
    gates = {
        "exact_v1_2_trace_reproduction": formal_exact,
        "full_cagr_delta_ge_minus_50bp": float(
            full["candidate_minus_champion"]["cagr"]
        )
        >= -0.005,
        "full_sharpe_delta_nonnegative": float(
            full["candidate_minus_champion"]["sharpe"]
        )
        >= 0.0,
        "mdd_deterioration_le_100bp": float(
            full["candidate_minus_champion"]["max_drawdown"]
        )
        >= -0.01,
        "fixed_validation_relative_wealth_nonnegative": float(
            fixed["candidate_minus_champion"]["relative_terminal_wealth"]
        )
        >= 0.0,
        "recent_relative_wealth_nonnegative": float(
            recent["candidate_minus_champion"]["relative_terminal_wealth"]
        )
        >= 0.0,
        "year_2026_relative_wealth_nonnegative": float(
            y2026["candidate_vs_champion_relative_wealth"]
        )
        >= 0.0,
        "stress_full_relative_wealth_nonnegative": float(
            stress_full["candidate_minus_champion"]["relative_terminal_wealth"]
        )
        >= 0.0,
        "stress_recent_relative_wealth_nonnegative": float(
            stress_recent["candidate_minus_champion"]["relative_terminal_wealth"]
        )
        >= 0.0,
        "turnover_le_frozen_event": candidate_turnover <= frozen_turnover + EPS,
        "period_positive_concentration_le_60pct": max_period_share <= 0.60 + EPS,
    }
    return {
        "gates": gates,
        "passed": int(sum(gates.values())),
        "total": len(gates),
        "all_pass": bool(all(gates.values())),
        "max_period_positive_contribution_share": max_period_share,
        "candidate_turnover_units": candidate_turnover,
        "frozen_event_turnover_units": frozen_turnover,
    }


def run() -> dict[str, Any]:
    spec = base._load_spec(base.SPEC)
    with tempfile.TemporaryDirectory(prefix="byd-recovery-low-vol-") as raw_root:
        root = Path(raw_root)
        byd_dir, etf_dir, data_identity = base._extract_inputs(spec, root)
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
        formal = base._load_formal(spec)
        performance_path, performance_sha = base._formal_section(
            formal,
            "performance",
            str(spec["baseline"]["performance_sha256"]),
        )
        formal_daily = base._formal_daily(performance_path, str(cutoff.date()))
        formal_trace = base._trace_reproduction(
            formal_daily, standard_results[V12_MODEL_ID].daily
        )
        if not formal_trace["exact"]:
            raise RuntimeError("low-vol experiment refuses a non-exact V1.2 Champion")

        decisions, _ = build_v12_decisions(common, signals)
        champion_decision = decisions[V12_MODEL_ID]
        champion_rebuilt = run_financed_allocation(
            V12_MODEL_ID,
            common,
            champion_decision,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        rebuilt_trace = base._trace_reproduction(formal_daily, champion_rebuilt.daily)
        if not rebuilt_trace["exact"]:
            raise RuntimeError("rebuilt V1.2 path does not match accepted formal trace")

        canonical = load_canonical_snapshot(byd_dir)
        full = build_research_dataset(canonical.adjusted, canonical.sessions)
        full.index = pd.to_datetime(full.index).normalize()
        factor = full["drawdown252_x_rebound60"].reindex(common.index).astype(float)
        vol_state = full["vol_state"].reindex(common.index).astype(str)
        base_target = signals["base_byd_weight"].astype(float)
        detector = base._build_detector(base_target, factor)
        frozen_event_decision, frozen_state = base._event_lifecycle_decision(
            champion_decision,
            base_target,
            detector,
            common["common_open_eligible"].astype(bool),
        )
        candidate_decision, candidate_state = _low_vol_event_decision(
            champion_decision,
            base_target,
            detector,
            common["common_open_eligible"].astype(bool),
            vol_state,
        )
        evaluation, scenario_results = _evaluate(
            common,
            champion_decision,
            frozen_event_decision,
            candidate_decision,
        )
        primary = scenario_results["primary"]
        champion_daily = primary["champion"].daily
        frozen_daily = primary["frozen_event"].daily
        candidate_daily = primary["candidate"].daily
        period = base._period_attribution(champion_daily, candidate_daily)
        episodes = base._episode_attribution(champion_daily, candidate_daily, base_target)
        annual = _annual(champion_daily, frozen_daily, candidate_daily)
        gates = _gates(
            evaluation,
            period,
            annual,
            bool(formal_trace["exact"] and rebuilt_trace["exact"]),
        )

    return {
        "schema_version": "1.0",
        "issue": ISSUE,
        "challenger": CHALLENGER,
        "research_only": True,
        "fresh_holdout": False,
        "historical_evidence_consumed": True,
        "automatic_promotion_allowed": False,
        "prospective_confirmation_required": True,
        "frozen_contract": {
            "detector_threshold": base.RECOVERY_THRESHOLD,
            "entry": "false_to_true_detector_edge AND vol_state == low on the same decision date",
            "missed_high_vol_edge_catch_up": False,
            "hold_common_open_eligible_sessions": base.HOLD_ELIGIBLE_SESSIONS,
            "overlay": "75% BYD + 25% 515180 -> 100% BYD",
            "early_termination": "unchanged V1.2 core returns to 100%",
            "detector_flicker_exit": False,
            "retrigger_requires_new_edge": True,
        },
        "baseline": {
            "model_id": V12_MODEL_ID,
            "bundle_id": formal.bundle_id,
            "performance_sha256": performance_sha,
            "formal_trace_reproduction": formal_trace,
            "rebuilt_trace_reproduction": rebuilt_trace,
        },
        "data_identity": data_identity,
        "evaluation": evaluation,
        "annual_attribution": annual,
        "period_attribution": period,
        "episode_attribution": episodes,
        "lifecycle_counts": {
            "detector_edges": int(candidate_state["event_edge"].sum()),
            "low_vol_confirmed_edges": int(
                candidate_state["low_vol_confirmed_edge"].sum()
            ),
            "candidate_lifecycle_starts": int(
                candidate_state["lifecycle_started"].sum()
            ),
            "frozen_event_lifecycle_starts": int(
                frozen_state["lifecycle_started"].sum()
            ),
        },
        "gates": gates,
        "decision": "prospective_shadow_worthy" if gates["all_pass"] else "not_supported",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "artifacts/research/byd_recovery_event_low_vol_confirmation_v1.json",
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
