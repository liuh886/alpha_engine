"""Complete RankerOptimizer using shared DataFoundation.

Integrates with DataFoundation for both offline optimization and online forward walking.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.optimization.runner import BaseOptimizationRunner
from src.optimization.contracts import CandidateSpec, ExperimentContract
from src.optimization.metrics import WindowResult
from src.optimization.foundation import DataFoundation
from src.research.daily_ranker import prepare_ranker_frame
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.xgb_native_calibration import (
    XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker,
)

RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"

TRAIN_WINDOWS = {
    "2024H1": ("2021-01-01", "2023-12-31"),
    "2024H2": ("2021-01-01", "2024-06-30"),
    "2025H1": ("2021-01-01", "2024-12-31"),
    "2025H2": ("2021-01-01", "2025-06-30"),
    "2026H1": ("2021-01-01", "2025-12-31"),
}


class RankerOptimizer(BaseOptimizationRunner):
    """Cross-sectional stock ranker optimizer using shared DataFoundation."""

    def __init__(self, contract: ExperimentContract, output_dir: str = "artifacts/optimization"):
        super().__init__(contract, output_dir)
        self._foundation: DataFoundation | None = None

    def _initialize(self) -> None:
        self._foundation = DataFoundation(
            market=self.contract.market,
            benchmark=self.contract.benchmark,
            provider_uri=self.contract.provider_uri,
            factor_library_path=self.contract.factor_library or "configs/factor_libraries/ohlcv.yaml",
            sector_config_path=self.contract.sector_config,
            universe_config_path=self.contract.universe_config,
            horizon_sessions=self.contract.windows.horizon_sessions,
        )
        self._foundation.initialize()
        self._provider_identity = self._foundation.provider_identity
        print(f"[ranker] {len(self._foundation.symbols)} symbols, "
              f"{len(self._foundation.sector_map)} sectors, "
              f"provider={self._provider_identity[:16]}...")

    def _evaluate_candidate(self, candidate: CandidateSpec, window_label: str, cost_bps: float) -> WindowResult | None:
        params = candidate.params
        top_n = params.get("top_n", 15)
        max_per_sector = params.get("max_per_sector")
        bottom_n_exclude = params.get("bottom_n_exclude", 0)
        cal_dict = params.get("calibration", {})
        factor_groups = params.get("factor_groups", ["momentum_volatility_volume"])

        # Get factor expressions via DataFoundation
        exprs = self._foundation.factor_expressions(list(factor_groups))
        if not exprs:
            return None

        # Load window data (cached by DataFoundation)
        wdata = self._foundation.load_window(window_label, exprs)
        features = wdata["features"]
        returns = wdata["returns"]
        benchmark = wdata["benchmark"]
        eval_dates = wdata["eval_dates"]

        # Train/test split
        train_start = TRAIN_WINDOWS.get(window_label, (wdata["train_start"], wdata["train_end"]))[0]
        train_end = TRAIN_WINDOWS.get(window_label, (wdata["train_start"], wdata["train_end"]))[1]

        dates = features.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(train_start)) & (dates <= pd.Timestamp(train_end))
        test_mask = dates.isin(eval_dates)

        ft = features.loc[train_mask].copy()
        rt = returns.loc[train_mask].copy()
        ft, rt = purge_training_tail(ft, rt, holding_days=self.contract.windows.horizon_sessions)
        valid, reason = validate_no_nan_inputs(ft, context=f"{candidate.candidate_id}/{window_label}")
        if not valid:
            return None

        # Build calibration
        default_cal = {"n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
                       "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
                       "subsample": 1.0, "colsample_bytree": 1.0,
                       "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
        cal = XGBNativeCalibration.from_dict({**default_cal, **cal_dict})

        x_rank, y_rank, groups = prepare_ranker_frame(ft, rt)
        fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups, calibration=cal)
        ft_test = features.loc[test_mask].copy()
        scores = predict_xgb_native_daily_ranker(fitted, ft_test)
        rt_test = returns.loc[test_mask].copy()

        # Portfolio construction
        cadence = self.contract.windows.cadence_sessions
        rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
        port_returns = []
        sector_map = self._foundation.sector_map

        for d in rebalance_dates:
            try:
                ds = scores.xs(d, level="datetime")
                dr = rt_test.xs(d, level="datetime")
            except KeyError:
                continue

            score_series = ds["score"]
            if bottom_n_exclude > 0:
                bottom = score_series.nsmallest(bottom_n_exclude).index
                score_series = score_series.drop(bottom, errors="ignore")

            if max_per_sector and sector_map:
                selected = self._select_sector_capped(score_series, top_n, max_per_sector, sector_map)
            else:
                selected = list(score_series.nlargest(top_n).index)

            sel_rets = dr[dr.index.isin([str(s) for s in selected])]
            if len(sel_rets) == 0:
                continue
            cf = 1.0 - (cost_bps / 10000.0) / cadence
            port_returns.append(float(sel_rets["return"].mean()) * cf)

        if not port_returns:
            return None

        pr_series = pd.Series(port_returns, index=pd.DatetimeIndex(
            [rebalance_dates[i] for i in range(len(port_returns))]))
        common = pr_series.index.intersection(benchmark.index)
        if len(common) == 0:
            return None
        pa = pr_series[common]
        ba = benchmark.loc[common, "return"]

        sc = float(np.prod(1.0 + pa) - 1.0)
        bc = float(np.prod(1.0 + ba) - 1.0)
        cum = (1.0 + pa).cumprod()
        dd = float(((cum - cum.cummax()) / cum.cummax()).min())

        return WindowResult(
            window=window_label,
            relative_excess=(1.0 + sc) / (1.0 + bc) - 1.0 if bc > -1 else 0.0,
            max_drawdown=dd,
            strategy_compound=sc,
            benchmark_compound=bc,
            n_periods=len(pa),
            positive_periods=int((pa > 0).sum()),
            cost_bps=cost_bps,
        )

    @staticmethod
    def _select_sector_capped(score_series, top_n, max_per_sector, sector_map):
        ranked = score_series.sort_values(ascending=False)
        selected, counts = [], {}
        for sym, _ in ranked.items():
            sym_str = str(sym)
            sec = sector_map.get(sym_str, "Unknown")
            if counts.get(sec, 0) >= max_per_sector:
                continue
            selected.append(sym_str)
            counts[sec] = counts.get(sec, 0) + 1
            if len(selected) >= top_n:
                break
        if len(selected) < top_n:
            for sym, _ in ranked.items():
                if str(sym) not in selected:
                    selected.append(str(sym))
                if len(selected) >= top_n:
                    break
        return selected[:top_n]
