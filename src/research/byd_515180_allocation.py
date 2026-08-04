"""Governed BYD/515180 core-dividend allocation research.

All executable evidence is restricted to the real ETF overlap. BYD signals are
computed from the immutable BYD canonical snapshot. ETF returns are consumed
only after its independent canonical quality gate passes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.etf_515180_canonical import CUTOFF as ETF_CUTOFF
from src.data.etf_515180_canonical import SCHEMA_VERSION as ETF_SCHEMA
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    build_v1_0_decision_position,
    load_canonical_snapshot,
)
from src.research.byd_v1_3_recovery_overlay import build_overlay_schedule

PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0

WINDOWS = {
    "development": ("2019-11-26", "2022-12-31"),
    "fixed_validation": ("2023-01-01", "2024-12-31"),
    "retrospective_2025_plus": ("2025-01-01", ETF_CUTOFF),
    "full_overlap": ("2019-11-26", ETF_CUTOFF),
}
PROMOTABLE = (
    "v1_dividend_75_25",
    "recovery_75_25",
    "recovery_50_50",
)


@dataclass(frozen=True)
class ETFResearchData:
    raw: pd.DataFrame
    adjusted: pd.DataFrame
    sessions: pd.DataFrame
    actions: pd.DataFrame
    manifest: dict[str, Any]


@dataclass(frozen=True)
class AllocationResult:
    name: str
    daily: pd.DataFrame
    trades: pd.DataFrame


def load_515180_canonical(root: str | Path) -> ETFResearchData:
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    exact = {
        "schema_version": ETF_SCHEMA,
        "symbol": "515180.SH",
        "cutoff": ETF_CUTOFF,
        "data_quality_status": "canonical_v1_pass",
        "cross_provider_stitching": False,
    }
    for key, expected in exact.items():
        if manifest.get(key) != expected:
            raise RuntimeError(
                f"515180 canonical contract mismatch for {key}: "
                f"{manifest.get(key)!r} != {expected!r}"
            )
    raw = pd.read_csv(root / "raw_ohlcv.csv", parse_dates=["date"])
    adjusted = pd.read_csv(root / "adjusted_ohlcv.csv", parse_dates=["date"])
    sessions = pd.read_csv(root / "session_audit.csv", parse_dates=["date"])
    actions = pd.read_csv(root / "corporate_actions.csv", parse_dates=["date"])
    if not {"date", "open_research_eligible"}.issubset(sessions.columns):
        raise RuntimeError("515180 session audit lacks open eligibility")
    sessions["open_research_eligible"] = sessions["open_research_eligible"].astype(bool)
    return ETFResearchData(
        raw=raw.sort_values("date").reset_index(drop=True),
        adjusted=adjusted.sort_values("date").reset_index(drop=True),
        sessions=sessions.sort_values("date").reset_index(drop=True),
        actions=actions.sort_values("date").reset_index(drop=True),
        manifest=manifest,
    )


def prepare_common_dataset(
    byd_root: str | Path,
    etf_root: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    byd = load_canonical_snapshot(byd_root)
    etf = load_515180_canonical(etf_root)
    byd_dataset = build_research_dataset(byd.adjusted, byd.sessions)
    byd_dataset.index = pd.to_datetime(byd_dataset.index).normalize()

    etf_adjusted = etf.adjusted.copy()
    etf_adjusted["date"] = pd.to_datetime(etf_adjusted["date"]).dt.normalize()
    etf_adjusted = etf_adjusted.set_index("date")
    etf_raw = etf.raw.copy()
    etf_raw["date"] = pd.to_datetime(etf_raw["date"]).dt.normalize()
    etf_raw = etf_raw.set_index("date")
    etf_sessions = etf.sessions.copy()
    etf_sessions["date"] = pd.to_datetime(etf_sessions["date"]).dt.normalize()
    etf_sessions = etf_sessions.set_index("date")

    common_index = byd_dataset.index.intersection(etf_adjusted.index)
    common_index = common_index[common_index <= pd.Timestamp(ETF_CUTOFF)]
    if len(common_index) < 1500:
        raise RuntimeError(f"insufficient BYD/515180 overlap: {len(common_index)}")

    common = byd_dataset.reindex(common_index).copy()
    for column in ("open", "high", "low", "close", "volume"):
        common[f"byd_{column}"] = common[column]
        common[f"etf_{column}"] = etf_adjusted.loc[common_index, column].astype(float)
        common[f"etf_raw_{column}"] = etf_raw.loc[common_index, column].astype(float)
    common["byd_open_eligible"] = common["open_research_eligible"].astype(bool)
    common["etf_open_eligible"] = etf_sessions.loc[
        common_index, "open_research_eligible"
    ].astype(bool)
    common["common_open_eligible"] = (
        common["byd_open_eligible"] & common["etf_open_eligible"]
    )
    common["byd_open_return"] = common["byd_open"].shift(-1) / common["byd_open"] - 1.0
    common["etf_open_return"] = common["etf_open"].shift(-1) / common["etf_open"] - 1.0

    actions = etf.actions.copy()
    actions["date"] = pd.to_datetime(actions["date"]).dt.normalize()
    dividend = actions.groupby("date")["dividend"].sum().reindex(common_index).fillna(0.0)
    common["etf_dividend_next"] = dividend.shift(-1).fillna(0.0)
    common["etf_raw_plus_cash_return"] = (
        common["etf_raw_open"].shift(-1) / common["etf_raw_open"] - 1.0
        + common["etf_dividend_next"] / common["etf_raw_open"]
    )
    common["etf_total_return_reconciliation_error"] = (
        common["etf_open_return"] - common["etf_raw_plus_cash_return"]
    )

    base_full = build_v1_0_decision_position(byd_dataset)
    overlay_full = build_overlay_schedule(byd_dataset, base_full)
    signals = pd.DataFrame(
        {
            "base_byd_weight": base_full.reindex(common_index),
            "recovery_byd_weight": overlay_full.final_decision_position.reindex(common_index),
            "recovery_active": overlay_full.overlay_active.reindex(common_index).fillna(False),
            "recovery_branch": overlay_full.overlay_branch.reindex(common_index).fillna(""),
        },
        index=common_index,
    )
    return common, signals, overlay_full.event_ledger


def build_decisions(common: pd.DataFrame, signals: pd.DataFrame) -> dict[str, pd.DataFrame]:
    index = common.index
    base = signals["base_byd_weight"].astype(float)
    recovery = signals["recovery_byd_weight"].astype(float)
    recovery_active = signals["recovery_active"].astype(bool)

    decisions: dict[str, pd.DataFrame] = {}

    def add(name: str, byd_weight: pd.Series | float, etf_weight: pd.Series | float) -> None:
        byd = pd.Series(byd_weight, index=index, dtype=float)
        etf = pd.Series(etf_weight, index=index, dtype=float)
        cash = 1.0 - byd - etf
        frame = pd.DataFrame(
            {"byd_weight": byd, "etf_weight": etf, "cash_weight": cash},
            index=index,
        )
        if (frame < -1e-12).any().any() or not np.allclose(frame.sum(axis=1), 1.0):
            raise AssertionError(f"{name} produced invalid portfolio weights")
        decisions[name] = frame

    add("byd100", 1.0, 0.0)
    add("etf100", 0.0, 1.0)
    add("fixed_75_25", 0.75, 0.25)
    add("byd_v1_cash", base, 0.0)
    add("v1_dividend_75_25", base, 1.0 - base)
    add("recovery_75_25", recovery, 1.0 - recovery)

    strong_defense = base.eq(0.75) & ~recovery_active
    strong_byd = pd.Series(np.where(strong_defense, 0.50, 1.0), index=index)
    add("recovery_50_50", strong_byd, 1.0 - strong_byd)

    binary_byd = pd.Series(np.where(recovery.eq(1.0), 1.0, 0.0), index=index)
    add("binary_100_0", binary_byd, 1.0 - binary_byd)
    return decisions


def execute_next_common_open(
    decision: pd.DataFrame,
    eligible: pd.Series,
) -> pd.DataFrame:
    if not decision.index.equals(eligible.index):
        raise ValueError("decision and common eligibility must align")
    current = decision.iloc[0].astype(float).copy()
    prior_decision = decision.iloc[0].astype(float).copy()
    rows: list[pd.Series] = []
    for i, (_, is_eligible) in enumerate(eligible.items()):
        if i > 0 and bool(is_eligible):
            current = prior_decision.copy()
        rows.append(current.copy())
        prior_decision = decision.iloc[i].astype(float).copy()
    executed = pd.DataFrame(rows, index=decision.index)
    executed.columns = [f"position_{column}" for column in decision.columns]
    return executed


def run_allocation(
    name: str,
    common: pd.DataFrame,
    decision: pd.DataFrame,
    *,
    cost_bps: float,
) -> AllocationResult:
    executed = execute_next_common_open(decision, common["common_open_eligible"])
    byd_weight = executed["position_byd_weight"]
    etf_weight = executed["position_etf_weight"]
    gross = byd_weight * common["byd_open_return"] + etf_weight * common["etf_open_return"]
    turnover = executed.diff().abs().sum(axis=1)
    turnover.iloc[0] = executed.iloc[0].abs().sum()
    cost = turnover * cost_bps / 10_000.0
    daily = pd.concat([decision.add_prefix("decision_"), executed], axis=1)
    daily["common_open_eligible"] = common["common_open_eligible"]
    daily["byd_return"] = common["byd_open_return"]
    daily["etf_return"] = common["etf_open_return"]
    daily["gross_return"] = gross
    daily["turnover_units"] = turnover
    daily["cost"] = cost
    daily["net_return"] = gross - cost
    daily = daily.iloc[:-1].copy()
    changes = executed.ne(executed.shift(1)).any(axis=1)
    trades = daily.loc[
        changes.reindex(daily.index).fillna(False),
        [
            "position_byd_weight",
            "position_etf_weight",
            "position_cash_weight",
            "turnover_units",
            "cost",
            "common_open_eligible",
        ],
    ].copy()
    trades.index.name = "date"
    return AllocationResult(name=name, daily=daily, trades=trades.reset_index())


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily["net_return"].dropna()
    years = len(returns) / 252.0
    wealth = (1.0 + returns).cumprod()
    total = float(wealth.iloc[-1] - 1.0)
    cagr = float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
    drawdown = wealth / wealth.cummax() - 1.0
    mdd = float(drawdown.min())
    volatility = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = float(returns.mean() / returns.std(ddof=0) * np.sqrt(252.0)) if returns.std(ddof=0) > 0 else 0.0
    calmar = float(cagr / abs(mdd)) if mdd < 0 else 0.0
    turnover = float(daily.loc[returns.index, "turnover_units"].sum())
    return {
        "sessions": float(len(returns)),
        "years": years,
        "total_return": total,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "calmar": calmar,
        "turnover_units": turnover,
        "round_trips_per_year": turnover / (2.0 * years),
        "mean_byd_weight": float(daily.loc[returns.index, "position_byd_weight"].mean()),
        "mean_etf_weight": float(daily.loc[returns.index, "position_etf_weight"].mean()),
    }


def window_metrics(result: AllocationResult, start: str, end: str) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty window {start} to {end}")
    return metrics(block)


def evaluation_table(results: dict[str, AllocationResult], cost_bps: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, result in results.items():
        for window, (start, end) in WINDOWS.items():
            rows.append(
                {"model": name, "cost_bps": cost_bps, "window": window, **window_metrics(result, start, end)}
            )
    return pd.DataFrame(rows)


def complementarity_diagnostics(common: pd.DataFrame, signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    close_returns = pd.DataFrame(
        {
            "byd": common["byd_close"].pct_change(),
            "etf": common["etf_close"].pct_change(),
        }
    )
    correlation_rows = [
        {"measure": "daily_return_correlation", "value": float(close_returns.corr().iloc[0, 1])},
        {
            "measure": "weekly_return_correlation",
            "value": float(
                pd.DataFrame(
                    {
                        "byd": common["byd_close"].resample("W-FRI").last().pct_change(),
                        "etf": common["etf_close"].resample("W-FRI").last().pct_change(),
                    }
                ).corr().iloc[0, 1]
            ),
        },
        {
            "measure": "20_session_return_correlation",
            "value": float(
                pd.DataFrame(
                    {
                        "byd": common["byd_close"].pct_change(20),
                        "etf": common["etf_close"].pct_change(20),
                    }
                ).corr().iloc[0, 1]
            ),
        },
        {
            "measure": "simultaneous_daily_loss_rate",
            "value": float(((close_returns["byd"] < 0) & (close_returns["etf"] < 0)).mean()),
        },
        {
            "measure": "median_60d_rolling_correlation",
            "value": float(close_returns["byd"].rolling(60).corr(close_returns["etf"]).median()),
        },
        {
            "measure": "p90_abs_total_return_reconciliation_error",
            "value": float(common["etf_total_return_reconciliation_error"].abs().dropna().quantile(0.90)),
        },
    ]

    states: dict[str, pd.Series] = {
        "all": pd.Series(True, index=common.index),
        "byd_bear": common["market_state"].eq("bear"),
        "byd_sideways": common["market_state"].eq("sideways"),
        "byd_bull": common["market_state"].eq("bull"),
        "byd_high_vol": common["vol_state"].eq("high"),
        "byd_deep_drawdown": common["drawdown_252"].le(-0.15),
        "recovery_active": signals["recovery_active"].astype(bool),
        "v1_defense": signals["base_byd_weight"].eq(0.75),
    }
    rows: list[dict[str, Any]] = []
    for state, mask in states.items():
        for horizon in (5, 10, 20):
            byd_forward = common["byd_open"].shift(-(horizon + 1)) / common["byd_open"].shift(-1) - 1.0
            etf_forward = common["etf_open"].shift(-(horizon + 1)) / common["etf_open"].shift(-1) - 1.0
            sample = pd.DataFrame({"byd": byd_forward, "etf": etf_forward}).loc[mask].dropna()
            rows.append(
                {
                    "state": state,
                    "horizon": horizon,
                    "samples": int(len(sample)),
                    "mean_byd_return": float(sample["byd"].mean()) if not sample.empty else np.nan,
                    "mean_etf_return": float(sample["etf"].mean()) if not sample.empty else np.nan,
                    "mean_byd_minus_etf": float((sample["byd"] - sample["etf"]).mean()) if not sample.empty else np.nan,
                    "etf_outperformance_rate": float((sample["etf"] > sample["byd"]).mean()) if not sample.empty else np.nan,
                }
            )
    return pd.DataFrame(correlation_rows), pd.DataFrame(rows)


def period_concentration(candidate: AllocationResult, baseline: AllocationResult) -> tuple[pd.DataFrame, float]:
    rows: list[dict[str, Any]] = []
    for window in ("development", "fixed_validation", "retrospective_2025_plus"):
        start, end = WINDOWS[window]
        candidate_return = window_metrics(candidate, start, end)["total_return"]
        baseline_return = window_metrics(baseline, start, end)["total_return"]
        relative = (1.0 + candidate_return) / (1.0 + baseline_return) - 1.0
        rows.append(
            {
                "window": window,
                "candidate_return": candidate_return,
                "baseline_return": baseline_return,
                "relative_return": relative,
                "positive_relative_return": max(relative, 0.0),
            }
        )
    table = pd.DataFrame(rows)
    total_positive = float(table["positive_relative_return"].sum())
    table["positive_relative_share"] = (
        table["positive_relative_return"] / total_positive if total_positive > 0 else 0.0
    )
    largest = float(table["positive_relative_share"].max()) if total_positive > 0 else 1.0
    return table, largest


def governed_decisions(
    results_20: dict[str, AllocationResult],
    results_40: dict[str, AllocationResult],
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    baseline20 = results_20["byd_v1_cash"]
    baseline40 = results_40["byd_v1_cash"]
    decisions: dict[str, Any] = {}
    concentration_tables: dict[str, pd.DataFrame] = {}
    full_start, full_end = WINDOWS["full_overlap"]
    val_start, val_end = WINDOWS["fixed_validation"]
    retro_start, retro_end = WINDOWS["retrospective_2025_plus"]
    baseline_full = window_metrics(baseline20, full_start, full_end)
    baseline_val = window_metrics(baseline20, val_start, val_end)
    baseline_retro = window_metrics(baseline20, retro_start, retro_end)
    baseline_full40 = window_metrics(baseline40, full_start, full_end)

    for name in PROMOTABLE:
        candidate = results_20[name]
        full = window_metrics(candidate, full_start, full_end)
        val = window_metrics(candidate, val_start, val_end)
        retro = window_metrics(candidate, retro_start, retro_end)
        full40 = window_metrics(results_40[name], full_start, full_end)
        concentration, largest = period_concentration(candidate, baseline20)
        concentration_tables[name] = concentration
        risk_gate = (
            full["max_drawdown"] >= baseline_full["max_drawdown"] + 0.03
            or full["calmar"] >= baseline_full["calmar"] + 0.03
        )
        gates = {
            "full_cagr_not_below_v1_cash": full["cagr"] >= baseline_full["cagr"],
            "risk_improvement": risk_gate,
            "validation_total_within_1pp": val["total_return"] >= baseline_val["total_return"] - 0.01,
            "retrospective_total_within_1pp": retro["total_return"] >= baseline_retro["total_return"] - 0.01,
            "stress_calmar_not_below_v1_cash": full40["calmar"] >= baseline_full40["calmar"],
            "round_trips_per_year_le_3": full["round_trips_per_year"] <= 3.0,
            "largest_positive_period_share_le_60pct": largest <= 0.60,
        }
        supported = all(gates.values())
        risk_improved = (
            full["max_drawdown"] > baseline_full["max_drawdown"] + 0.01
            or full["calmar"] > baseline_full["calmar"]
        )
        return_not_far_below = full["cagr"] >= baseline_full["cagr"] - 0.02
        decision = (
            "supported"
            if supported
            else "improved_but_not_outperforming"
            if risk_improved and return_not_far_below
            else "not_supported"
        )
        decisions[name] = {
            "decision": decision,
            "gates": gates,
            "largest_positive_period_share": largest,
            "full_20bps": full,
            "full_40bps": full40,
            "fixed_validation_20bps": val,
            "retrospective_2025_plus_20bps": retro,
        }
    decisions["governance"] = {
        "research_only": True,
        "trade_ready": False,
        "fresh_holdout": False,
        "binary_100_0_promotable": False,
        "primary_candidate": "v1_dividend_75_25",
    }
    return decisions, concentration_tables
