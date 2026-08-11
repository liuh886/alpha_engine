"""Single-Stock Timer Optimizer (BYD-type models).

Optimizes timing rules, allocation weights, and convex momentum budget
parameters for single-equity tactical allocation strategies.
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.optimization.runner import BaseOptimizationRunner
from src.optimization.contracts import CandidateSpec, ExperimentContract
from src.optimization.metrics import WindowResult


class TimerOptimizer(BaseOptimizationRunner):
    """Parameter optimizer for single-stock timing strategies.

    Each candidate specifies:
    - defense_byd_pct: BYD weight in defense (0.0 = full ETF)
    - offense_byd_pct: BYD weight in offense (1.0 = full BYD)
    - expansion_max: maximum BYD weight in expansion
    - convex_power: exponent for momentum scaling
    - full_increment_momentum: momentum level for full increment
    - max_financed_increment: maximum margin increment
    - mom_entry_threshold: momentum must exceed this to enter offense
    - mom_exit_threshold: momentum below this triggers defense
    - backtest_source: path to formal backtest JSON
    - primary_asset: ticker of the primary asset (default "BYD")
    - defensive_asset: ticker of the defensive asset (default "515180")
    """

    def __init__(self, contract: ExperimentContract, output_dir: str = "artifacts/optimization"):
        super().__init__(contract, output_dir)
        self._report: pd.DataFrame | None = None
        self._returns_df: pd.DataFrame | None = None

    def _initialize(self) -> None:
        trace_path = self.contract.metadata.get("backtest_source",
                                                   "data/research/formal_backtests/byd_v1_2_convex_momentum_budget_v1.json")
        d = json.loads(Path(trace_path).read_text(encoding="utf-8"))
        report = pd.DataFrame(d["report"])
        report["date"] = pd.to_datetime(report["date"])
        self._report = report

        # Reconstruct asset returns from positions
        positions = pd.DataFrame(d["positions"])
        positions["date"] = pd.to_datetime(positions["date"])
        primary = self.contract.metadata.get("primary_asset", "BYD")
        defensive = self.contract.metadata.get("defensive_asset", "515180")
        pp = positions[positions["instrument"] == primary].set_index("date")["price"]
        dp = positions[positions["instrument"].isin([defensive, "515180.SH"])].set_index("date")["price"]
        if dp.empty:
            dp = positions[positions["instrument"] == "515180.SH"].set_index("date")["price"]

        pr = pp.pct_change().fillna(0.0)
        dr = dp.pct_change().fillna(0.0)
        self._returns_df = pd.DataFrame({primary: pr, defensive: dr}).reindex(report["date"]).fillna(0.0)
        self._primary = primary
        self._defensive = defensive
        self._provider_identity = d.get("backtest_id", "formal_backtest")
        print(f"[timer] loaded {len(report)} daily records ({primary} + {defensive})")

    @staticmethod
    def _mom_scale(m20: float, fi: float, cp: float, mf: float) -> tuple[float, float]:
        if m20 <= 0:
            return 0.0, 0.0
        s = min(1.0, m20 / fi) ** cp
        return s, s * mf

    def _evaluate_candidate(self, candidate: CandidateSpec, window_label: str, cost_bps: float) -> WindowResult | None:
        params = candidate.params
        def_byd = params.get("defense_byd_pct", 0.0)
        off_byd = params.get("offense_byd_pct", 1.0)
        exp_max = params.get("expansion_max", 1.125)
        cp = params.get("convex_power", 4.0)
        fi = params.get("full_increment_momentum", 0.15)
        mf = params.get("max_financed_increment", 0.125)
        mom_entry = params.get("mom_entry_threshold", 0.0)
        mom_exit = params.get("mom_exit_threshold", 0.0)

        daily = self._report.set_index("date")
        rf = self._returns_df
        primary = self._primary
        defensive = self._defensive

        w_primary, w_defensive, w_cash = [], [], []
        for i in range(len(daily)):
            m20 = float(daily["momentum_20"].iloc[i])
            s, inc = self._mom_scale(max(0.0, m20), fi, cp, mf)

            if m20 > mom_entry:
                tb = min(off_byd + inc, exp_max)
                w_primary.append(tb)
                w_defensive.append(0.0)
                w_cash.append(1.0 - tb)
            elif m20 <= mom_exit:
                w_primary.append(def_byd)
                w_defensive.append(1.0 - def_byd)
                w_cash.append(0.0)
            else:
                w_primary.append(def_byd)
                w_defensive.append(1.0 - def_byd)
                w_cash.append(0.0)

        ar = rf.reindex(daily.index).fillna(0.0)
        gr = np.array(w_primary) * ar[primary].values + np.array(w_defensive) * ar[defensive].values

        # Transaction costs
        wp = pd.Series(w_primary)
        wd = pd.Series(w_defensive)
        wch = abs(wp.diff().fillna(0)) + abs(wd.diff().fillna(0))
        wch.iloc[0] = abs(wp.iloc[0]) + abs(wd.iloc[0])
        tc = wch * cost_bps / 10000.0

        # Financing cost for margin
        fin = np.maximum(np.array(w_primary) - 1.0, 0.0)
        fcost = fin * 0.06 / 252.0

        nr = gr - tc.values - fcost
        eq = (1.0 + pd.Series(nr, index=daily.index)).cumprod()
        dd = float((eq / eq.cummax() - 1.0).min())
        sc = float(eq.iloc[-1] - 1.0)
        bc = float(daily["benchmark_return"].iloc[-1])

        return WindowResult(
            window=window_label,
            relative_excess=(1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0,
            max_drawdown=dd,
            strategy_compound=sc,
            benchmark_compound=bc,
            n_periods=len(daily),
            cost_bps=cost_bps,
        )
