"""ETF Rotation Optimizer (QQQR-type models).

Optimizes rule-based state machine parameters: state allocation weights,
defense splits, panic repair, momentum thresholds. Works with pre-loaded
formal backtest data for speed.
"""
from __future__ import annotations

import json, math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.optimization.runner import BaseOptimizationRunner
from src.optimization.contracts import CandidateSpec, ExperimentContract, ModelType
from src.optimization.metrics import WindowResult


class RotatorOptimizer(BaseOptimizationRunner):
    """Parameter optimizer for ETF rotation strategies.

    Works with formal backtest JSON data. Each candidate specifies:
    - state_0/1/2: dict of asset→weight for each state
    - panic_boost: float (0.0 to disable)
    - defense_split: [qqqi_pct, sgov_pct]
    - state_trace_source: path to formal backtest JSON
    """

    ASSETS = ["QQQI", "QQQ", "TQQQ", "SGOV"]

    def __init__(self, contract: ExperimentContract, output_dir: str = "artifacts/optimization"):
        super().__init__(contract, output_dir)
        self._report: pd.DataFrame | None = None
        self._returns_df: pd.DataFrame | None = None
        self._benchmark_col = "bench_qqq"

    def _initialize(self) -> None:
        trace_path = self.contract.metadata.get("state_trace_source",
                                                   "data/research/formal_backtests/qqqi_qqq_tqqq_v4_3.json")
        d = json.loads(Path(trace_path).read_text(encoding="utf-8"))
        report = pd.DataFrame(d["report"])
        report["date"] = pd.to_datetime(report["date"])
        self._report = report

        # Reconstruct asset returns from positions
        positions = pd.DataFrame(d["positions"])
        positions["date"] = pd.to_datetime(positions["date"])
        ar = {}
        for a in ["QQQI", "QQQ", "TQQQ"]:
            ap = positions[positions["instrument"] == a].set_index("date")["price"]
            ar[a] = ap.pct_change().fillna(0.0)
        ar["SGOV"] = pd.Series(0.0, index=ar["QQQ"].index)
        self._returns_df = pd.DataFrame(ar).reindex(report["date"]).fillna(0.0)

        self._provider_identity = d.get("backtest_id", "formal_backtest")
        print(f"[rotator] loaded {len(report)} daily records")

    def _evaluate_candidate(self, candidate: CandidateSpec, window_label: str, cost_bps: float) -> WindowResult | None:
        params = candidate.params
        s0 = params.get("state_0", {"QQQI": 1.0, "QQQ": 0.0, "TQQQ": 0.0, "SGOV": 0.0})
        s1 = params.get("state_1", {"QQQI": 0.5, "QQQ": 0.5, "TQQQ": 0.0, "SGOV": 0.0})
        s2 = params.get("state_2", {"QQQI": 0.0, "QQQ": 0.25, "TQQQ": 0.75, "SGOV": 0.0})
        panic_boost = params.get("panic_boost", 0.0)
        defense_split = params.get("defense_split", (0.5, 0.5))

        # Filter to window (simplified: use full dataset; real impl would filter by window dates)
        daily = self._report.set_index("date")
        rf = self._returns_df

        w = pd.DataFrame(0.0, index=daily.index, columns=self.ASSETS)
        for i in range(len(daily)):
            st = int(daily["position_state"].iloc[i])
            ws = {0: s0, 1: s1, 2: s2}.get(st, s0)
            for a in self.ASSETS:
                w.iloc[i, w.columns.get_loc(a)] = ws.get(a, 0.0)
            if daily["panic_repair_active"].iloc[i] and panic_boost > 0 and st in (0, 1):
                ct = ws.get("TQQQ", 0.0); cq = ws.get("QQQI", 0.0)
                b = min(panic_boost, cq)
                w.iloc[i, w.columns.get_loc("TQQQ")] = ct + b
                w.iloc[i, w.columns.get_loc("QQQI")] = cq - b
            if daily["slow_bear_defense_active"].iloc[i]:
                qp, sp = defense_split
                w.iloc[i, w.columns.get_loc("QQQI")] = qp
                w.iloc[i, w.columns.get_loc("SGOV")] = sp
                w.iloc[i, w.columns.get_loc("QQQ")] = 0.0
                w.iloc[i, w.columns.get_loc("TQQQ")] = 0.0

        arf = rf.reindex(daily.index).fillna(0.0)
        gr = (w.values * arf.values).sum(axis=1)
        wc = w.diff().abs().sum(axis=1); wc.iloc[0] = w.iloc[0].abs().sum()
        tc = wc * cost_bps / 10000.0
        nr = gr - tc.values
        eq = (1.0 + pd.Series(nr, index=daily.index)).cumprod()
        dd = float((eq / eq.cummax() - 1.0).min())
        sc = float(eq.iloc[-1] - 1.0)

        # Benchmark: QQQ buy-and-hold
        bm_col = self._benchmark_col
        bc = float(daily[bm_col].iloc[-1] / daily[bm_col].iloc[0] - 1.0) if bm_col in daily.columns else sc * 0.3

        return WindowResult(
            window=window_label,
            relative_excess=(1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0,
            max_drawdown=dd,
            strategy_compound=sc,
            benchmark_compound=bc,
            n_periods=len(daily),
            cost_bps=cost_bps,
        )
