"""Publish the user-authorized BYD v1.3 low-vol recovery model.

The publisher reconstructs the frozen V1.2 Champion first, applies exactly the
pre-registered low-vol recovery lifecycle, retains the complete daily trace,
and replaces V1.2 only in the formal allow-list. Historical V1.2 artifacts are
kept as immutable evidence. No fresh-holdout or trade-ready claim is made.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from scripts.byd_formal_publication_common import (
    BYD_SNAPSHOT_SHA256,
    ETF_ADJUSTED_SHA256,
    ETF_ARTIFACT_SHA256,
    allocation_action,
    write_json,
)
from src.research.byd_515180_allocation import WINDOWS, metrics, prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    CONVEX_POWER,
    FULL_INCREMENT_MOMENTUM,
    MAX_FINANCED_INCREMENT,
    build_decisions as build_v12_decisions,
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
from src.research.byd_v1_3_low_vol_recovery import (
    DISPLAY_NAME,
    HOLD_ELIGIBLE_SESSIONS,
    MODEL_ID,
    PUBLIC_MODEL_ID,
    RECOVERY_THRESHOLD,
    build_recovery_decision,
)

PACKAGE_NAME = f"{MODEL_ID}.json"
SUPERSEDED_MODEL_ID = V12_MODEL_ID
PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
EPS = 1e-12
EXPECTED = {
    "candidate_cagr": 0.37838108480564925,
    "champion_cagr": 0.35843544390055615,
    "candidate_sharpe": 0.9538094286223441,
    "candidate_max_drawdown": -0.4892927084747377,
    "relative_terminal_wealth": 0.09753521715046087,
    "turnover_units": 16.76311113908823,
    "max_period_positive_share": 0.5689759320440935,
}


class BYDV13FormalPromotionError(ValueError):
    """Raised when the frozen BYD v1.3 package cannot be reproduced exactly."""


def _wealth(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod()) if not clean.empty else 1.0


def _weights(row: pd.Series) -> dict[str, float]:
    return {
        "BYD": float(row["position_byd_weight"]),
        "515180.SH": float(row["position_etf_weight"]),
        "CASH": float(row["position_cash_weight"]),
    }


def _window_metrics(daily: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    result = metrics(block)
    returns = block["net_return"].dropna()
    result["turnover_units"] = float(block.loc[returns.index, "turnover_units"].sum())
    return result


def _relative_wealth(candidate: pd.DataFrame, champion: pd.DataFrame, start: str, end: str) -> float:
    c = _wealth(candidate.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"])
    b = _wealth(champion.loc[pd.Timestamp(start) : pd.Timestamp(end), "net_return"])
    return c / b - 1.0


def _period_attribution(candidate: pd.DataFrame, champion: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in ("development", "fixed_validation", "retrospective_2025_plus"):
        start, end = WINDOWS[window]
        rows.append(
            {
                "window": window,
                "relative_terminal_wealth": _relative_wealth(candidate, champion, start, end),
            }
        )
    positive_total = sum(max(float(row["relative_terminal_wealth"]), 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(float(row["relative_terminal_wealth"]), 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return rows


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


def _episode_attribution(
    candidate: pd.DataFrame,
    champion: pd.DataFrame,
    recovery_state: pd.DataFrame,
) -> list[dict[str, Any]]:
    table = _episodes(recovery_state["overlay_decision_active"].astype(bool))
    rows: list[dict[str, Any]] = []
    for episode in table.itertuples(index=False):
        relative = _wealth(candidate.loc[episode.start : episode.end, "net_return"]) / _wealth(
            champion.loc[episode.start : episode.end, "net_return"]
        ) - 1.0
        state_block = recovery_state.loc[episode.start : episode.end]
        termination = str(state_block.iloc[-1]["termination_on_decision"] or "")
        rows.append(
            {
                "episode_id": int(episode.episode_id),
                "start": pd.Timestamp(episode.start).strftime("%Y-%m-%d"),
                "end": pd.Timestamp(episode.end).strftime("%Y-%m-%d"),
                "sessions": int(episode.sessions),
                "relative_terminal_wealth": float(relative),
                "termination": termination or "core_or_sample_end",
            }
        )
    positive_total = sum(max(float(row["relative_terminal_wealth"]), 0.0) for row in rows)
    for row in rows:
        row["positive_contribution_share"] = (
            max(float(row["relative_terminal_wealth"]), 0.0) / positive_total
            if positive_total > 0.0
            else 0.0
        )
    return rows


def _verify_v12_formal_overlap(package: Mapping[str, Any], v12_daily: pd.DataFrame) -> None:
    rows = package.get("report")
    if not isinstance(rows, list) or not rows:
        raise BYDV13FormalPromotionError("accepted V1.2 package has no daily report")
    by_date = {
        str(row.get("date")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("date")
    }
    checked = 0
    for date, row in v12_daily.iterrows():
        key = pd.Timestamp(date).strftime("%Y-%m-%d")
        existing = by_date.get(key)
        if existing is None:
            continue
        expected = {
            "period_return": float(row["net_return"]),
            "weight_BYD": float(row["position_byd_weight"]),
            "weight_515180": float(row["position_etf_weight"]),
            "weight_cash": float(row["position_cash_weight"]),
        }
        for field, value in expected.items():
            if not math.isclose(float(existing[field]), value, rel_tol=1e-12, abs_tol=1e-12):
                raise BYDV13FormalPromotionError(
                    f"V1.2 formal predecessor drift on {key}: {field}"
                )
        checked += 1
    if checked < 1000:
        raise BYDV13FormalPromotionError(
            f"insufficient V1.2 formal overlap for promotion: {checked} rows"
        )


def _assert_expected(name: str, actual: float, *, tolerance: float = 1e-10) -> None:
    expected = float(EXPECTED[name])
    if not math.isclose(float(actual), expected, rel_tol=tolerance, abs_tol=tolerance):
        raise BYDV13FormalPromotionError(
            f"frozen #745 evidence drift: {name} expected {expected}, got {actual}"
        )


def _build_paths(
    byd_dir: Path,
    etf_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
    decisions, v12_state = build_v12_decisions(common, signals)
    champion_decision = decisions[V12_MODEL_ID]

    canonical = load_canonical_snapshot(byd_dir)
    research = build_research_dataset(canonical.adjusted, canonical.sessions)
    research.index = pd.to_datetime(research.index).tz_localize(None).normalize()
    factor = research["drawdown252_x_rebound60"].reindex(common.index).astype(float)
    vol_state = research["vol_state"].reindex(common.index).astype(str)
    base_target = signals["base_byd_weight"].astype(float)
    candidate_decision, recovery_state = build_recovery_decision(
        champion_decision,
        base_target,
        factor,
        vol_state,
        common["common_open_eligible"].astype(bool),
    )
    return common, champion_decision, candidate_decision, v12_state, recovery_state


def _scenario_paths(
    common: pd.DataFrame,
    champion_decision: pd.DataFrame,
    candidate_decision: pd.DataFrame,
    *,
    cost_bps: float,
    financing_rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    champion = run_financed_allocation(
        V12_MODEL_ID,
        common,
        champion_decision,
        cost_bps=cost_bps,
        annual_financing_rate=financing_rate,
    ).daily
    candidate = run_financed_allocation(
        MODEL_ID,
        common,
        candidate_decision,
        cost_bps=cost_bps,
        annual_financing_rate=financing_rate,
    ).daily
    if not champion.index.equals(candidate.index):
        raise BYDV13FormalPromotionError("V1.3 and V1.2 daily paths differ")
    return champion, candidate


def build_package(
    *,
    byd_dir: Path,
    etf_dir: Path,
    signal_ledger: Path,
    cutoff: str,
    generated_at: str,
    predecessor_package: Mapping[str, Any],
) -> dict[str, Any]:
    common, champion_decision, candidate_decision, v12_state, recovery_state = _build_paths(
        byd_dir, etf_dir
    )
    champion, candidate = _scenario_paths(
        common,
        champion_decision,
        candidate_decision,
        cost_bps=PRIMARY_COST_BPS,
        financing_rate=PRIMARY_FINANCING_RATE,
    )
    champion_stress, candidate_stress = _scenario_paths(
        common,
        champion_decision,
        candidate_decision,
        cost_bps=STRESS_COST_BPS,
        financing_rate=STRESS_FINANCING_RATE,
    )
    _verify_v12_formal_overlap(predecessor_package, champion)

    candidate_metrics = metrics(candidate)
    champion_metrics = metrics(champion)
    candidate_stress_metrics = metrics(candidate_stress)
    champion_stress_metrics = metrics(champion_stress)
    relative_terminal = _wealth(candidate["net_return"]) / _wealth(champion["net_return"]) - 1.0
    periods = _period_attribution(candidate, champion)
    episodes = _episode_attribution(candidate, champion, recovery_state)
    max_period_share = max(
        (float(row["positive_contribution_share"]) for row in periods), default=0.0
    )

    _assert_expected("candidate_cagr", candidate_metrics["cagr"])
    _assert_expected("champion_cagr", champion_metrics["cagr"])
    _assert_expected("candidate_sharpe", candidate_metrics["sharpe"])
    _assert_expected("candidate_max_drawdown", candidate_metrics["max_drawdown"])
    _assert_expected("relative_terminal_wealth", relative_terminal)
    _assert_expected("turnover_units", candidate_metrics["turnover_units"])
    _assert_expected("max_period_positive_share", max_period_share)

    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    account = 1.0
    benchmark = 1.0
    peak = 1.0
    previous = {"BYD": 0.0, "515180.SH": 0.0, "CASH": 1.0}
    contribution = {
        "BYD": {"gross": 0.0, "transaction_cost": 0.0, "financing_cost": 0.0},
        "515180.SH": {"gross": 0.0, "transaction_cost": 0.0, "financing_cost": 0.0},
        "CASH": {"gross": 0.0, "transaction_cost": 0.0, "financing_cost": 0.0},
    }

    for date, row in candidate.iterrows():
        key = pd.Timestamp(date).strftime("%Y-%m-%d")
        champion_row = champion.loc[date]
        state_row = v12_state.loc[date]
        recovery_row = recovery_state.loc[date]
        net = float(row["net_return"])
        benchmark_net = float(champion_row["net_return"])
        account *= 1.0 + net
        benchmark *= 1.0 + benchmark_net
        peak = max(peak, account)
        current = _weights(row)
        report.append(
            {
                "date": key,
                "account": account,
                "bench_byd_v1_2": benchmark,
                "period_return": net,
                "benchmark_return": benchmark_net,
                "relative_excess_return": (1.0 + net) / (1.0 + benchmark_net) - 1.0,
                "gross_return": float(row["gross_return"]),
                "transaction_cost": float(row["cost"]),
                "financing_cost": float(row["financing_cost"]),
                "turnover": float(row["turnover_units"]),
                "drawdown": account / peak - 1.0,
                "weight_BYD": current["BYD"],
                "weight_515180": current["515180.SH"],
                "weight_cash": current["CASH"],
                "base_BYD_weight": float(state_row["base_byd_weight"]),
                "trend_expansion_active": bool(state_row["trend_expansion_active"]),
                "momentum_20": float(state_row["mom_20"]),
                "momentum_scale": float(state_row["momentum_scale"]),
                "financed_increment": float(state_row["financed_increment"]),
                "recovery_detector": bool(recovery_row["detector"]),
                "recovery_event_edge": bool(recovery_row["event_edge"]),
                "low_vol_confirmed_edge": bool(recovery_row["low_vol_confirmed_edge"]),
                "recovery_lifecycle_active": bool(recovery_row["overlay_decision_active"]),
                "recovery_lifecycle_id": int(recovery_row["lifecycle_id"]),
                "recovery_remaining_eligible_sessions": int(
                    recovery_row["remaining_eligible_sessions_before_decision"]
                ),
                "common_open_eligible": bool(row["common_open_eligible"]),
                "trace_frequency": "daily_open_to_open",
            }
        )
        prices = {
            "BYD": float(common.loc[date, "byd_open"]),
            "515180.SH": float(common.loc[date, "etf_open"]),
            "CASH": 1.0,
        }
        for instrument, weight in current.items():
            if math.isclose(weight, 0.0, abs_tol=1e-15):
                continue
            positions.append(
                {
                    "date": key,
                    "instrument": instrument,
                    "weight": weight,
                    "price": prices[instrument],
                    "base_BYD_weight": float(state_row["base_byd_weight"]),
                    "market_state": str(state_row["market_state"]),
                    "vol_state": str(state_row["vol_state"]),
                    "recovery_lifecycle_active": bool(
                        recovery_row["overlay_decision_active"]
                    ),
                    "recovery_lifecycle_id": int(recovery_row["lifecycle_id"]),
                }
            )

        changes = {
            instrument: abs(current[instrument] - previous[instrument])
            for instrument in current
        }
        denominator = sum(changes.values())
        transaction_cost = float(row["cost"])
        for instrument in current:
            delta = current[instrument] - previous[instrument]
            allocated = (
                transaction_cost * changes[instrument] / denominator
                if denominator
                else 0.0
            )
            contribution[instrument]["transaction_cost"] += allocated
            if not math.isclose(delta, 0.0, abs_tol=1e-15):
                trades.append(
                    {
                        "date": key,
                        "instrument": instrument,
                        "action": allocation_action(previous[instrument], current[instrument]),
                        "previous_weight": previous[instrument],
                        "target_weight": current[instrument],
                        "weight_delta": delta,
                        "transaction_cost": allocated,
                        "reason": (
                            "low_vol_recovery_lifecycle"
                            if bool(recovery_row["overlay_decision_active"])
                            else "v1_2_core_or_convex_momentum"
                        ),
                        "common_open_eligible": bool(row["common_open_eligible"]),
                    }
                )
        contribution["BYD"]["gross"] += current["BYD"] * float(row["byd_return"])
        contribution["515180.SH"]["gross"] += current["515180.SH"] * float(
            row["etf_return"]
        )
        contribution["CASH"]["financing_cost"] += float(row["financing_cost"])
        previous = current

    attribution: list[dict[str, Any]] = []
    for instrument, values in contribution.items():
        total_cost = values["transaction_cost"] + values["financing_cost"]
        attribution.append(
            {
                "instrument": instrument,
                "name": instrument,
                "gross_contribution": values["gross"],
                "transaction_cost": values["transaction_cost"],
                "financing_cost": values["financing_cost"],
                "value": values["gross"] - total_cost,
                "semantics": "arithmetic daily contribution less allocated transaction and financing costs",
            }
        )

    window_summary: list[dict[str, Any]] = []
    for window, (start, end) in WINDOWS.items():
        window_summary.append(
            {
                "window": window,
                "start": start,
                "end": end,
                "candidate": _window_metrics(candidate, start, end),
                "benchmark_v1_2": _window_metrics(champion, start, end),
                "relative_terminal_wealth": _relative_wealth(candidate, champion, start, end),
            }
        )

    stress_relative = (
        (1.0 + candidate_stress_metrics["total_return"])
        / (1.0 + champion_stress_metrics["total_return"])
        - 1.0
    )
    actual_end = pd.Timestamp(candidate.index.max()).strftime("%Y-%m-%d")

    return {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": f"{MODEL_ID}-formal-user-authorized-2026-08-10",
        "model_id": MODEL_ID,
        "public_model_id": PUBLIC_MODEL_ID,
        "display_name": DISPLAY_NAME,
        "market": "cn",
        "benchmark": "BYD v1.2",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": cutoff,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "daily_open_to_open",
        "date_range": {
            "start": pd.Timestamp(candidate.index.min()).strftime("%Y-%m-%d"),
            "end": actual_end,
        },
        "metrics": {
            "Total Return": candidate_metrics["total_return"],
            "CAGR": candidate_metrics["cagr"],
            "Annualized Volatility": candidate_metrics["annual_volatility"],
            "Sharpe Ratio": candidate_metrics["sharpe"],
            "Max Drawdown": candidate_metrics["max_drawdown"],
            "Calmar Ratio": candidate_metrics["calmar"],
            "Turnover": candidate_metrics["turnover_units"],
            "Round Trips Per Year": candidate_metrics["round_trips_per_year"],
            "Benchmark V1.2 Return": champion_metrics["total_return"],
            "Benchmark V1.2 CAGR": champion_metrics["cagr"],
            "Incremental CAGR": candidate_metrics["cagr"] - champion_metrics["cagr"],
            "Relative Terminal Wealth vs V1.2": relative_terminal,
            "Stress 40bps Total Return": candidate_stress_metrics["total_return"],
            "Stress 40bps Benchmark V1.2 Return": champion_stress_metrics["total_return"],
            "Stress Relative Terminal Wealth vs V1.2": stress_relative,
            "Financed Sessions": int(candidate["borrowed_weight"].gt(0.0).sum()),
            "Completed Recovery Episodes": int(len(episodes)),
            "Low Vol Confirmed Event Edges": int(
                recovery_state["low_vol_confirmed_edge"].sum()
            ),
            "Maximum Positive Period Share": max_period_share,
            "Maximum Positive Episode Share": max(
                (float(row["positive_contribution_share"]) for row in episodes),
                default=0.0,
            ),
        },
        "portfolio_contract": {
            "symbols": ["BYD", "515180.SH", "CASH"],
            "signal_time": "session_close_t",
            "execution_time": "next_common_independently_confirmed_eligible_open_t_plus_1",
            "cost_bps": PRIMARY_COST_BPS,
            "stress_cost_bps": STRESS_COST_BPS,
            "primary_annual_financing_rate": PRIMARY_FINANCING_RATE,
            "stress_annual_financing_rate": STRESS_FINANCING_RATE,
            "v1_2_core_inherited": True,
            "convex_momentum_budget": {
                "full_increment_momentum": FULL_INCREMENT_MOMENTUM,
                "convex_power": CONVEX_POWER,
                "maximum_financed_increment": MAX_FINANCED_INCREMENT,
            },
            "recovery_lifecycle": {
                "factor": "drawdown252_x_rebound60",
                "detector_threshold": RECOVERY_THRESHOLD,
                "entry_confirmation_vol_state": "low",
                "same_edge_confirmation": True,
                "catch_up_after_high_vol_edge": False,
                "hold_common_open_eligible_sessions": HOLD_ELIGIBLE_SESSIONS,
                "detector_flicker_exit": False,
                "early_termination": "v1_2_core_returns_to_100pct_byd",
                "overlay": {"BYD": 1.0, "515180.SH": 0.0, "CASH": 0.0},
            },
        },
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution,
        "window_summary": window_summary,
        "period_attribution": periods,
        "episode_attribution": episodes,
        "operational_monitoring": {
            "status": "separate_runtime_signal_ledger",
            "ledger": signal_ledger.as_posix(),
            "runtime_state_embedded": False,
        },
        "freshness": {
            "status": "current",
            "required_cutoff": cutoff,
            "latest_completed_session": cutoff,
            "latest_realized_holding_end": actual_end,
            "model_selection_reopened": False,
            "monitoring_source": signal_ledger.as_posix(),
        },
        "evidence": {
            "source_research_issue": 744,
            "prospective_issue": 746,
            "promotion_issue": 752,
            "promotion_authority": "explicit_user_direction_2026_08_10",
            "historical_gate_result": "11_of_11_passed",
            "historical_evidence_consumed": True,
            "fresh_historical_holdout": False,
            "byd_snapshot_sha256": BYD_SNAPSHOT_SHA256,
            "etf_artifact_sha256": ETF_ARTIFACT_SHA256,
            "etf_adjusted_sha256": ETF_ADJUSTED_SHA256,
            "formal_config": "configs/models/byd_v1_3_recovery_event_low_vol_confirmation_v1.yaml",
            "implementation": "src/research/byd_v1_3_low_vol_recovery.py",
            "mechanism_evidence": "data/research/diagnostics/byd_recovery_event_low_vol_confirmation_v1_summary.json",
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_daily_open_to_open_path",
            "holdings": "retained_exact_daily_weights_including_financing",
            "trades": "retained_exact_weight_changes",
            "attribution": "derived_exact_from_retained_daily_components",
            "robustness": "primary_stress_period_and_recovery_episode_attribution",
            "signal_monitoring": "repository_persisted_identity_bound_ledger",
            "missing": [],
        },
        "interpretation_notes": [
            "User-directed accepted formal baseline; automatic promotion was not used.",
            "Historical evidence is consumed and no fresh historical holdout exists.",
            "The user explicitly authorized promotion before the prospective observation window completed.",
            "research_only=true and trade_ready=false remain hard boundaries.",
            "BYD v1.2 is retained as the exact predecessor benchmark in this package.",
        ],
    }


def promote(
    *,
    root: Path,
    byd_dir: Path,
    etf_dir: Path,
    signal_ledger: Path,
    generated_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    freshness = json.loads((root / "freshness.json").read_text(encoding="utf-8"))
    predecessor_path = root / f"{SUPERSEDED_MODEL_ID}.json"
    predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(freshness, dict):
        raise BYDV13FormalPromotionError("formal catalog or freshness root is invalid")
    if not isinstance(predecessor, dict):
        raise BYDV13FormalPromotionError("accepted V1.2 predecessor package is invalid")
    markets = freshness.get("markets")
    if not isinstance(markets, dict) or not markets.get("cn"):
        raise BYDV13FormalPromotionError("CN formal freshness cutoff is missing")
    cutoff = str(markets["cn"])

    package = build_package(
        byd_dir=byd_dir,
        etf_dir=etf_dir,
        signal_ledger=signal_ledger,
        cutoff=cutoff,
        generated_at=generated_at,
        predecessor_package=predecessor,
    )
    package_sha = write_json(root / PACKAGE_NAME, package)

    records = [
        dict(row)
        for row in catalog.get("records", [])
        if isinstance(row, dict)
        and row.get("model_id") not in {MODEL_ID, SUPERSEDED_MODEL_ID}
    ]
    records.append(
        {
            "display_name": DISPLAY_NAME,
            "display_order": 4,
            "model_id": MODEL_ID,
            "path": PACKAGE_NAME,
            "publication_status": "accepted_formal_baseline",
            "sha256": package_sha,
        }
    )
    records.sort(
        key=lambda row: (int(row.get("display_order", 999)), str(row.get("model_id")))
    )
    catalog["records"] = records
    catalog["published_at"] = generated_at
    catalog["research_only"] = True
    catalog["trade_ready"] = False
    write_json(root / "catalog.json", catalog)

    required = [
        str(value)
        for value in freshness.get("required_models", [])
        if str(value) not in {MODEL_ID, SUPERSEDED_MODEL_ID}
    ]
    required.append(MODEL_ID)
    freshness["required_models"] = required
    freshness["declared_at"] = generated_at
    freshness["research_only"] = True
    freshness["trade_ready"] = False
    write_json(root / "freshness.json", freshness)

    return {
        "schema_version": "1.0.0",
        "status": "accepted_formal_baseline_promoted",
        "model_id": MODEL_ID,
        "public_model_id": PUBLIC_MODEL_ID,
        "superseded_model_id": SUPERSEDED_MODEL_ID,
        "package_sha256": package_sha,
        "evidence_cutoff": cutoff,
        "historical_date_range_end": package["date_range"]["end"],
        "promotion_authority": "explicit_user_direction_2026_08_10",
        "historical_evidence_consumed": True,
        "fresh_historical_holdout": False,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("data/research/formal_backtests")
    )
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument(
        "--signal-ledger",
        type=Path,
        default=Path(
            "data/research/strategy_signal_ledgers/"
            "byd_v1_3_recovery_event_low_vol_confirmation_v1"
        ),
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = promote(
        root=args.root,
        byd_dir=args.byd_dir,
        etf_dir=args.etf_dir,
        signal_ledger=args.signal_ledger,
        generated_at=args.generated_at,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
