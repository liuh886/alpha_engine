"""Concrete ranker optimizer — cross-sectional stock ranking (USx, CNx).

Demonstrates how to implement a model-type-specific runner using the
base optimization infrastructure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.optimization.runner import BaseOptimizationRunner
from src.optimization.contracts import CandidateSpec, ExperimentContract
from src.optimization.metrics import WindowResult

# These imports are project-specific and would be replaced by the agent's own
# model training code:
from src.research.daily_ranker import prepare_ranker_frame
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import load_window_benchmark_returns, normalize_qlib_frame_index
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.window_policy import build_window_sampling_plan, horizon_eligible_dates_by_window
from src.research.xgb_native_calibration import (
    XGBNativeCalibration, fit_xgb_native_daily_ranker, predict_xgb_native_daily_ranker,
)


class RankerOptimizer(BaseOptimizationRunner):
    """Cross-sectional stock ranker optimizer.

    Handles USx and CNx model types. Each candidate specifies:
    - factor_groups: list of factor group names
    - calibration: XGBNativeCalibration dict
    - top_n: number of stocks to select
    - max_per_sector: sector cap (None = no cap)
    """

    def __init__(self, contract: ExperimentContract, output_dir: str = "artifacts/optimization"):
        super().__init__(contract, output_dir)
        self._runtime = None
        self._symbols: list[str] = []
        self._calendar: pd.DatetimeIndex | None = None
        self._eval_dates_by_window: dict[str, pd.DatetimeIndex] = {}
        self._universe_config: dict[str, Any] = {}

        # Select runtime based on market
        if contract.market == "us":
            from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
            self._runtime_cls = QlibUSExecutionRuntime
        elif contract.market == "cn":
            from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime
            self._runtime_cls = QlibCNExecutionRuntime
        else:
            raise ValueError(f"unsupported market: {contract.market}")

    def _initialize(self) -> None:
        # Load universe
        universe_path = Path(self.contract.universe_config or f"configs/research_universes/{self.contract.market}_selected_equities_v2.yaml")
        if not universe_path.exists():
            universe_path = Path(f"configs/research_universes/{self.contract.market}_selected_equities_v3.yaml")
        self._universe_config = yaml.safe_load(universe_path.read_text(encoding="utf-8"))

        # Init runtime
        provider_uri = self.contract.provider_uri or f"data/providers/{self.contract.market}"
        self._runtime = self._runtime_cls(provider_uri=provider_uri)
        self._runtime.initialize(Path.cwd())
        meta = self._runtime.metadata()
        self._provider_identity = str(meta.get("provider_identity_sha256", ""))

        # Resolve symbols
        requested = [str(s) for s in self._universe_config.get("symbols", [])]
        available = self._runtime.available_symbols()
        normalized = normalize_market_symbols(self.contract.market, requested, available_symbols=available)
        self._symbols = [item.normalized_symbol for item in normalized
                        if item.normalized_symbol in available]
        print(f"[ranker] {len(self._symbols)} symbols resolved")

        # Set up window plan
        ws = self.contract.windows
        self._calendar = self._runtime.calendar(ws.train_start, f"{ws.last_test_year}-12-31")
        avail_end = min(pd.Timestamp(f"{ws.last_test_year}-12-31"), self._calendar.max()).strftime("%Y-%m-%d")
        wp = build_window_sampling_plan(
            self._calendar, ws.train_start, avail_end,
            first_test_year=ws.first_test_year, last_test_year=ws.last_test_year,
            min_complete_windows=ws.min_complete_windows,
            partial_window_policy=ws.partial_window_policy,
            min_partial_window_eligible_sessions=None,
            horizon_sessions=ws.horizon_sessions, cadence_sessions=ws.cadence_sessions,
        )
        self._eval_dates_by_window = horizon_eligible_dates_by_window(wp, self._calendar)

    def _evaluate_candidate(self, candidate: CandidateSpec, window_label: str, cost_bps: float) -> WindowResult | None:
        params = candidate.params
        factor_groups = params.get("factor_groups", ["momentum_volatility_volume"])
        cal_dict = params.get("calibration", {})
        top_n = params.get("top_n", 15)
        max_per_sector = params.get("max_per_sector")

        # Get factor expressions
        factor_lib_path = Path(self.contract.factor_library or "configs/factor_libraries/ohlcv.yaml")
        library = load_factor_library(factor_lib_path)
        selected = select_factor_groups(library, list(factor_groups))
        expressions: list[str] = []
        seen: set[str] = set()
        for g in selected:
            for f in g.factors:
                if f.expression not in seen:
                    expressions.append(f.expression)
                    seen.add(f.expression)

        # Get window info
        wp = self._eval_dates_by_window
        if window_label not in wp:
            return None
        eval_dates = wp[window_label]

        # Find window boundaries
        ws = self.contract.windows
        windows_list = list(wp.keys() if hasattr(wp, 'keys') else [])
        # We need the train boundaries — reconstruct from window plan
        # Simplified: use fixed train windows
        train_windows = {
            "2024H1": ("2021-01-01", "2023-12-31"),
            "2024H2": ("2021-01-01", "2024-06-30"),
            "2025H1": ("2021-01-01", "2024-12-31"),
            "2025H2": ("2021-01-01", "2025-06-30"),
        }
        if window_label not in train_windows:
            return None
        train_start, train_end = train_windows[window_label]

        # Load features and returns
        return_expr = "Ref($close, -10) / $close - 1"
        benchmark = self.contract.benchmark

        try:
            features = normalize_qlib_frame_index(
                self._runtime.features(self._symbols, expressions, train_start, self._eval_dates_by_window[window_label].max().strftime("%Y-%m-%d"))
            ).replace([np.inf, -np.inf], np.nan)
            features.columns = [f"feature_{i}" for i in range(len(expressions))]

            returns = normalize_qlib_frame_index(
                self._runtime.features(self._symbols, [return_expr], train_start, self._eval_dates_by_window[window_label].max().strftime("%Y-%m-%d"))
            )
            returns.columns = ["return"]
        except Exception as e:
            print(f"[ranker] data error for {candidate.candidate_id}/{window_label}: {e}")
            return None

        dates = features.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(train_start)) & (dates <= pd.Timestamp(train_end))
        test_mask = dates.isin(eval_dates)

        ft_train = features.loc[train_mask].copy()
        rt_train = returns.loc[train_mask].copy()
        ft_train, rt_train = purge_training_tail(ft_train, rt_train, holding_days=10)

        valid, reason = validate_no_nan_inputs(ft_train, context=f"{candidate.candidate_id}/{window_label}")
        if not valid:
            print(f"[ranker] NaN in {candidate.candidate_id}/{window_label}: {reason}")
            return None

        # Build calibration
        default_cal = {"n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
                       "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
                       "subsample": 1.0, "colsample_bytree": 1.0,
                       "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
        cal = XGBNativeCalibration.from_dict({**default_cal, **cal_dict})

        x_rank, y_rank, groups = prepare_ranker_frame(ft_train, rt_train)
        fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups, calibration=cal)

        ft_test = features.loc[test_mask].copy()
        scores = predict_xgb_native_daily_ranker(fitted, ft_test)
        rt_test = returns.loc[test_mask].copy()

        # Load benchmark
        bm = load_window_benchmark_returns(
            self._runtime, benchmark_instrument=benchmark, return_expression=return_expr,
            evaluation_dates=eval_dates,
            start=eval_dates.min().strftime("%Y-%m-%d"),
            end=eval_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return", horizon=10,
        )

        # Simple portfolio evaluation (Top-K equal weight)
        rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), self.contract.windows.cadence_sessions)]
        port_returns = []
        for d in rebalance_dates:
            try:
                ds = scores.xs(d, level="datetime")
                dr = rt_test.xs(d, level="datetime")
            except KeyError:
                continue
            ranked = ds.sort_values("score", ascending=False)
            selected = [str(s) for s in ranked.index[:top_n]]
            sel_rets = dr[dr.index.isin(selected)]
            if len(sel_rets) == 0:
                continue
            cf = 1.0 - (cost_bps / 10000.0) / self.contract.windows.cadence_sessions
            port_returns.append(float(sel_rets["return"].mean()) * cf)

        if not port_returns:
            return None

        pr_series = pd.Series(port_returns, index=pd.DatetimeIndex([rebalance_dates[i] for i in range(len(port_returns))]))
        common = pr_series.index.intersection(bm.index)
        if len(common) == 0:
            return None
        pa = pr_series[common]
        ba = bm.loc[common, "return"]

        sc = float(np.prod(1.0 + pa) - 1.0)
        bc = float(np.prod(1.0 + ba) - 1.0)
        cum = (1.0 + pa).cumprod()
        dd = float(((cum - cum.cummax()) / cum.cummax()).min())

        return WindowResult(
            window=window_label,
            relative_excess=(1.0 + sc) / (1.0 + bc) - 1.0,
            max_drawdown=dd,
            strategy_compound=sc,
            benchmark_compound=bc,
            n_periods=len(pa),
            positive_periods=int((pa > 0).sum()),
            cost_bps=cost_bps,
        )
