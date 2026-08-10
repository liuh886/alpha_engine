"""Frozen BYD defensive-sleeve convergence screen for Issue #546."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.cn_etf_candidate_canonical import SCHEMA_VERSION as CANDIDATE_SCHEMA
from src.research.byd_515180_allocation import (
    ETFResearchData,
    load_515180_canonical,
    metrics,
)
from src.research.byd_515180_execution import run_allocation
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    build_v1_0_decision_position,
    load_canonical_snapshot,
)

PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
OVERLAP_START = "2019-11-26"
CUTOFF = "2026-08-03"
WINDOWS = {
    "development": (OVERLAP_START, "2022-12-31"),
    "fixed_validation": ("2023-01-01", "2024-12-31"),
    "retrospective_2025_plus": ("2025-01-01", CUTOFF),
    "full_overlap": (OVERLAP_START, CUTOFF),
}
CANDIDATES = ("515180.SH", "512890.SH", "511010.SH")
CHALLENGERS = ("512890.SH", "511010.SH")


@dataclass(frozen=True)
class ScreenInputs:
    byd_dir: Path
    etf_dirs: dict[str, Path]


def load_candidate_canonical(root: Path, symbol: str) -> ETFResearchData:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "schema_version": CANDIDATE_SCHEMA,
        "symbol": symbol,
        "cutoff": CUTOFF,
        "data_quality_status": "canonical_v1_pass",
        "cross_provider_stitching": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(
                f"{symbol} canonical contract mismatch for {key}: "
                f"{manifest.get(key)!r} != {value!r}"
            )
    raw = pd.read_csv(root / "raw_ohlcv.csv", parse_dates=["date"])
    adjusted = pd.read_csv(root / "adjusted_ohlcv.csv", parse_dates=["date"])
    sessions = pd.read_csv(root / "session_audit.csv", parse_dates=["date"])
    actions = pd.read_csv(root / "corporate_actions.csv", parse_dates=["date"])
    sessions["open_research_eligible"] = sessions["open_research_eligible"].astype(bool)
    return ETFResearchData(
        raw=raw.sort_values("date").reset_index(drop=True),
        adjusted=adjusted.sort_values("date").reset_index(drop=True),
        sessions=sessions.sort_values("date").reset_index(drop=True),
        actions=actions.sort_values("date").reset_index(drop=True),
        manifest=manifest,
    )


def load_inputs(
    inputs: ScreenInputs,
) -> tuple[pd.DataFrame, dict[str, ETFResearchData], dict[str, dict[str, Any]]]:
    byd = load_canonical_snapshot(inputs.byd_dir)
    byd_dataset = build_research_dataset(byd.adjusted, byd.sessions)
    byd_dataset.index = pd.to_datetime(byd_dataset.index).normalize()

    etfs: dict[str, ETFResearchData] = {
        "515180.SH": load_515180_canonical(inputs.etf_dirs["515180.SH"])
    }
    blocked: dict[str, dict[str, Any]] = {}
    for symbol in CHALLENGERS:
        root = inputs.etf_dirs[symbol]
        manifest_path = root / "manifest.json"
        blocker_path = root / "data_blocked.json"
        if manifest_path.exists():
            etfs[symbol] = load_candidate_canonical(root, symbol)
        elif blocker_path.exists():
            blocker = json.loads(blocker_path.read_text(encoding="utf-8"))
            if blocker.get("symbol") != symbol or blocker.get("status") != "data_blocked":
                raise RuntimeError(f"invalid immutable blocker for {symbol}")
            blocked[symbol] = blocker
        else:
            raise RuntimeError(f"{symbol} has neither canonical manifest nor blocker")
    return byd_dataset, etfs, blocked


def prepare_master_dataset(
    byd_dataset: pd.DataFrame,
    etfs: dict[str, ETFResearchData],
) -> tuple[pd.DataFrame, pd.Series]:
    index = byd_dataset.index
    for etf in etfs.values():
        etf_index = pd.to_datetime(etf.adjusted["date"]).dt.normalize()
        index = index.intersection(pd.Index(etf_index))
    index = index[(index >= pd.Timestamp(OVERLAP_START)) & (index <= pd.Timestamp(CUTOFF))]
    if len(index) < 1500:
        raise RuntimeError(f"insufficient common candidate overlap: {len(index)}")

    master = pd.DataFrame(index=index)
    master["byd_open"] = byd_dataset.loc[index, "open"].astype(float)
    master["byd_close"] = byd_dataset.loc[index, "close"].astype(float)
    master["byd_open_return"] = master["byd_open"].shift(-1) / master["byd_open"] - 1.0
    master["byd_open_eligible"] = byd_dataset.loc[index, "open_research_eligible"].astype(bool)
    master["market_state"] = byd_dataset.loc[index, "market_state"].astype(str)
    master["vol_state"] = byd_dataset.loc[index, "vol_state"].astype(str)

    eligibility = master["byd_open_eligible"].copy()
    for symbol, etf in etfs.items():
        key = symbol.split(".")[0]
        adjusted = etf.adjusted.copy()
        adjusted["date"] = pd.to_datetime(adjusted["date"]).dt.normalize()
        adjusted = adjusted.set_index("date")
        sessions = etf.sessions.copy()
        sessions["date"] = pd.to_datetime(sessions["date"]).dt.normalize()
        sessions = sessions.set_index("date")
        master[f"{key}_open"] = adjusted.loc[index, "open"].astype(float)
        master[f"{key}_close"] = adjusted.loc[index, "close"].astype(float)
        master[f"{key}_open_return"] = master[f"{key}_open"].shift(-1) / master[f"{key}_open"] - 1.0
        master[f"{key}_open_eligible"] = sessions.loc[index, "open_research_eligible"].astype(bool)
        eligibility &= master[f"{key}_open_eligible"]
    master["common_open_eligible"] = eligibility

    base = build_v1_0_decision_position(byd_dataset).reindex(index).astype(float)
    if base.isna().any():
        raise RuntimeError("BYD V1.0 decision missing inside frozen overlap")
    return master, base


def _decision(base: pd.Series, *, use_etf: bool) -> pd.DataFrame:
    etf = 1.0 - base if use_etf else pd.Series(0.0, index=base.index)
    return pd.DataFrame(
        {
            "byd_weight": base,
            "etf_weight": etf,
            "cash_weight": 1.0 - base - etf,
        },
        index=base.index,
    )


def _view(master: pd.DataFrame, symbol: str) -> pd.DataFrame:
    key = symbol.split(".")[0]
    return pd.DataFrame(
        {
            "byd_open_return": master["byd_open_return"],
            "etf_open_return": master[f"{key}_open_return"],
            "common_open_eligible": master["common_open_eligible"],
        },
        index=master.index,
    )


def _window_metrics(daily: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    block = daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise RuntimeError(f"empty evaluation window: {start} to {end}")
    return metrics(block)


def run_screen(
    inputs: ScreenInputs,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    byd_dataset, etfs, blocked = load_inputs(inputs)
    available = tuple(symbol for symbol in CANDIDATES if symbol in etfs)
    master, base = prepare_master_dataset(byd_dataset, etfs)
    cash_decision = _decision(base, use_etf=False)
    candidate_decision = _decision(base, use_etf=True)

    results: dict[tuple[str, float], Any] = {}
    cash_view = _view(master, "515180.SH")
    for cost in (PRIMARY_COST_BPS, STRESS_COST_BPS):
        results[("cash", cost)] = run_allocation("cash", cash_view, cash_decision, cost_bps=cost)
        for symbol in available:
            results[(symbol, cost)] = run_allocation(
                symbol,
                _view(master, symbol),
                candidate_decision,
                cost_bps=cost,
            )

    rows: list[dict[str, Any]] = []
    for (name, cost), result in results.items():
        for window, (start, end) in WINDOWS.items():
            rows.append(
                {
                    "candidate": name,
                    "cost_bps": cost,
                    "window": window,
                    **_window_metrics(result.daily, start, end),
                }
            )
    evaluation = pd.DataFrame(rows)

    period_rows: list[dict[str, Any]] = []
    for symbol in available:
        positive_total = 0.0
        symbol_rows: list[dict[str, Any]] = []
        for window in ("development", "fixed_validation", "retrospective_2025_plus"):
            start, end = WINDOWS[window]
            candidate_metric = _window_metrics(
                results[(symbol, PRIMARY_COST_BPS)].daily, start, end
            )
            cash_metric = _window_metrics(results[("cash", PRIMARY_COST_BPS)].daily, start, end)
            delta = candidate_metric["total_return"] - cash_metric["total_return"]
            positive_total += max(delta, 0.0)
            symbol_rows.append(
                {
                    "candidate": symbol,
                    "window": window,
                    "candidate_total_return": candidate_metric["total_return"],
                    "cash_total_return": cash_metric["total_return"],
                    "incremental_total_return": delta,
                }
            )
        for row in symbol_rows:
            row["positive_contribution_share"] = (
                max(float(row["incremental_total_return"]), 0.0) / positive_total
                if positive_total > 0
                else 1.0
            )
            period_rows.append(row)
    periods = pd.DataFrame(period_rows)

    correlation_rows: list[dict[str, Any]] = []
    byd_return = master["byd_close"].pct_change()
    for symbol in available:
        key = symbol.split(".")[0]
        etf_return = master[f"{key}_close"].pct_change()
        correlation_rows.append(
            {
                "candidate": symbol,
                "daily_return_correlation": float(byd_return.corr(etf_return)),
                "median_60d_rolling_correlation": float(
                    byd_return.rolling(60).corr(etf_return).median()
                ),
                "simultaneous_daily_loss_rate": float(((byd_return < 0) & (etf_return < 0)).mean()),
            }
        )
    correlations = pd.DataFrame(correlation_rows)

    full20 = evaluation.loc[
        (evaluation["window"] == "full_overlap") & (evaluation["cost_bps"] == PRIMARY_COST_BPS)
    ].set_index("candidate")
    full40 = evaluation.loc[
        (evaluation["window"] == "full_overlap") & (evaluation["cost_bps"] == STRESS_COST_BPS)
    ].set_index("candidate")
    cash20 = full20.loc["cash"]
    cash40 = full40.loc["cash"]
    reference20 = full20.loc["515180.SH"]
    reference40 = full40.loc["515180.SH"]

    gate_matrix: dict[str, dict[str, Any]] = {
        symbol: {
            "data_status": "blocked",
            "blocker": blocker,
            "cash_gates": {},
            "cash_qualified": False,
            "challenge_gates": {},
            "challenge_qualified": False,
        }
        for symbol, blocker in blocked.items()
    }
    qualified_challengers: list[str] = []
    for symbol in available:
        current20 = full20.loc[symbol]
        current40 = full40.loc[symbol]
        symbol_periods = periods.loc[periods["candidate"] == symbol]
        cash_gates = {
            "cagr_delta_at_least_50bp": (float(current20["cagr"] - cash20["cagr"]) >= 0.005),
            "calmar_not_below_cash": float(current20["calmar"]) >= float(cash20["calmar"]),
            "drawdown_not_worse_by_more_than_1pp": (
                float(current20["max_drawdown"] - cash20["max_drawdown"]) >= -0.01
            ),
            "stress_total_increment_nonnegative": (
                float(current40["total_return"] - cash40["total_return"]) >= 0.0
            ),
            "all_three_periods_positive": bool(
                (symbol_periods["incremental_total_return"] > 0).all()
            ),
            "max_period_share_at_most_60pct": (
                float(symbol_periods["positive_contribution_share"].max()) <= 0.60
            ),
            "round_trips_at_most_3": float(current20["round_trips_per_year"]) <= 3.0,
        }
        cash_qualified = all(cash_gates.values())
        challenge_gates: dict[str, bool] = {}
        challenge_qualified = False
        if symbol in CHALLENGERS and cash_qualified:
            calmar_path = (
                float(current20["calmar"] - reference20["calmar"]) >= 0.02
                and float(current20["cagr"] - reference20["cagr"]) >= -0.005
            )
            drawdown_path = (
                float(current20["max_drawdown"] - reference20["max_drawdown"]) >= 0.02
                and float(current20["cagr"] - reference20["cagr"]) >= -0.005
            )
            challenge_gates = {
                "stress_total_not_below_515180": (
                    float(current40["total_return"]) >= float(reference40["total_return"])
                ),
                "calmar_or_drawdown_path": calmar_path or drawdown_path,
            }
            challenge_qualified = all(challenge_gates.values())
            if challenge_qualified:
                qualified_challengers.append(symbol)
        gate_matrix[symbol] = {
            "data_status": "canonical_pass",
            "cash_gates": cash_gates,
            "cash_qualified": cash_qualified,
            "challenge_gates": challenge_gates,
            "challenge_qualified": challenge_qualified,
        }

    reference_qualified = bool(gate_matrix["515180.SH"]["cash_qualified"])
    if not reference_qualified:
        decision = "structural_conflict_515180_failed_recalculation"
        selected = None
    elif not qualified_challengers:
        decision = "retain_515180_as_only_prospective_etf"
        selected = None
    else:
        ranked = sorted(
            qualified_challengers,
            key=lambda symbol: (
                float(full20.loc[symbol, "calmar"]),
                float(full40.loc[symbol, "total_return"]),
                -float(
                    periods.loc[
                        periods["candidate"] == symbol,
                        "positive_contribution_share",
                    ].max()
                ),
            ),
            reverse=True,
        )
        selected = ranked[0]
        decision = "add_single_historical_challenger_to_prospective_parallel"

    summary = {
        "schema_version": "byd_defensive_sleeve_screen_v1",
        "issue": 546,
        "overlap_start": OVERLAP_START,
        "cutoff": CUTOFF,
        "common_sessions": int(len(master)),
        "common_eligible_opens": int(master["common_open_eligible"].sum()),
        "frozen_candidates": list(CANDIDATES),
        "available_candidates": list(available),
        "blocked_candidates": blocked,
        "challengers": list(CHALLENGERS),
        "gate_matrix": gate_matrix,
        "governed_decision": decision,
        "selected_challenger": selected,
        "research_only": True,
        "trade_ready": False,
        "fresh_holdout": False,
    }
    return evaluation, periods, correlations, summary
