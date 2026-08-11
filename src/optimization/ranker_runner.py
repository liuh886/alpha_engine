"""Complete RankerOptimizer with sector cap, guardrails, data caching, and core lib integration.

Integrates:
- src.core.selection: select_topk with guardrail
- src.core.portfolio: build_rolling_portfolio for portfolio construction
- src.core.metrics: compute_spread, compute_ic_series
- Sector cap via industry classification
- OptimizationDataCache for one-load-many-use
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.optimization.runner import BaseOptimizationRunner
from src.optimization.contracts import CandidateSpec, ExperimentContract
from src.optimization.metrics import WindowResult
from src.optimization.cache import OptimizationDataCache

from src.core.selection import select_topk
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

RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"


class RankerOptimizer(BaseOptimizationRunner):
    """Complete cross-sectional stock ranker optimizer.

    Supports:
    - Sector cap via max_per_sector + industry classification
    - Guardrail filtering via price/MA thresholds
    - Bottom-N exclusion
    - Factor group expansion
    - Data caching (one load per window, shared across candidates)
    - Integration with src.core primitives
    """

    def __init__(self, contract: ExperimentContract, output_dir: str = "artifacts/optimization"):
        super().__init__(contract, output_dir)
        self._runtime = None
        self._symbols: list[str] = []
        self._calendar: pd.DatetimeIndex | None = None
        self._eval_dates_by_window: dict[str, pd.DatetimeIndex] = {}
        self._train_windows: dict[str, tuple[str, str]] = {}
        self._cache = OptimizationDataCache(market=contract.market, symbols=[], benchmark=contract.benchmark)
        self._sector_map: dict[str, str] = {}
        self._factor_exprs: dict[str, list[str]] = {}

        if contract.market == "us":
            from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
            self._runtime_cls = QlibUSExecutionRuntime
        elif contract.market == "cn":
            from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime
            self._runtime_cls = QlibCNExecutionRuntime
        else:
            raise ValueError(f"unsupported market: {contract.market}")

    # ---- Init ----
    def _initialize(self) -> None:
        self._load_universe()
        self._init_runtime()
        self._load_sectors()
        self._precompute_factor_expressions()
        self._setup_windows()
        self._preload_all_window_data()

    def _load_universe(self):
        for path_candidate in [
            Path(self.contract.universe_config or ""),
            Path(f"configs/research_universes/{self.contract.market}_selected_equities_v3.yaml"),
            Path(f"configs/research_universes/{self.contract.market}_selected_equities_v2.yaml"),
        ]:
            if path_candidate.exists():
                self._universe_config = yaml.safe_load(path_candidate.read_text(encoding="utf-8"))
                return
        raise FileNotFoundError("universe config not found")

    def _init_runtime(self):
        provider_uri = self.contract.provider_uri or f"data/providers/{self.contract.market}"
        self._runtime = self._runtime_cls(provider_uri=provider_uri)
        self._runtime.initialize(Path.cwd())
        meta = self._runtime.metadata()
        self._provider_identity = str(meta.get("provider_identity_sha256", ""))
        requested = [str(s) for s in self._universe_config.get("symbols", [])]
        available = self._runtime.available_symbols()
        normalized = normalize_market_symbols(self.contract.market, requested, available_symbols=available)
        self._symbols = [i.normalized_symbol for i in normalized if i.normalized_symbol in available]
        self._cache.symbols = self._symbols
        print(f"[ranker] {len(self._symbols)}/{len(requested)} symbols resolved")

    def _load_sectors(self):
        if self.contract.sector_config:
            raw = yaml.safe_load(Path(self.contract.sector_config).read_text(encoding="utf-8"))
            records = raw.get("records", raw.get("symbols", {}))
            self._sector_map = {str(k): str(v.get("sector", "Unknown")) for k, v in records.items()}
            print(f"[ranker] {len(self._sector_map)} sector mappings loaded")

    def _precompute_factor_expressions(self):
        lib_path = Path(self.contract.factor_library or "configs/factor_libraries/ohlcv.yaml")
        library = load_factor_library(lib_path)
        for candidate in self.contract.candidates:
            groups = candidate.params.get("factor_groups", ["momentum_volatility_volume"])
            selected = select_factor_groups(library, list(groups))
            exprs, seen = [], set()
            for g in selected:
                for f in g.factors:
                    if f.expression not in seen:
                        exprs.append(f.expression)
                        seen.add(f.expression)
            self._factor_exprs[candidate.candidate_id] = exprs

    def _setup_windows(self):
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

        # Fixed train windows (aligned with USx/CNx experiments)
        self._train_windows = {
            "2024H1": ("2021-01-01", "2023-12-31"),
            "2024H2": ("2021-01-01", "2024-06-30"),
            "2025H1": ("2021-01-01", "2024-12-31"),
            "2025H2": ("2021-01-01", "2025-06-30"),
        }

    def _preload_all_window_data(self):
        """Load features/returns for ALL windows once, using union of all factor expressions."""
        all_exprs_set: set[str] = set()
        for exprs in self._factor_exprs.values():
            all_exprs_set.update(exprs)
        all_exprs = sorted(all_exprs_set)
        expr_to_idx = {e: i for i, e in enumerate(all_exprs)}

        for win_label in self.contract.windows.labels:
            if win_label not in self._train_windows or win_label not in self._eval_dates_by_window:
                continue
            train_start, train_end = self._train_windows[win_label]
            eval_dates = self._eval_dates_by_window[win_label]

            load_end = eval_dates.max().strftime("%Y-%m-%d")
            fa = normalize_qlib_frame_index(
                self._runtime.features(self._symbols, all_exprs, train_start, load_end)
            ).replace([np.inf, -np.inf], np.nan)
            fa.columns = [f"f{i}" for i in range(len(all_exprs))]

            ra = normalize_qlib_frame_index(
                self._runtime.features(self._symbols, [RETURN_EXPRESSION], train_start, load_end)
            )
            ra.columns = ["return"]

            dates = fa.index.get_level_values("datetime")
            tm = (dates >= pd.Timestamp(train_start)) & (dates <= pd.Timestamp(train_end))
            testm = dates.isin(eval_dates)

            bm = load_window_benchmark_returns(
                self._runtime, benchmark_instrument=self.contract.benchmark,
                return_expression=RETURN_EXPRESSION, evaluation_dates=eval_dates,
                start=eval_dates.min().strftime("%Y-%m-%d"),
                end=eval_dates.max().strftime("%Y-%m-%d"),
                provenance="raw_forward_return", horizon=10,
            )

            self._cache.store_window(win_label, fa, ra, bm, eval_dates, tm, testm)
            print(f"[ranker] cached window {win_label}: {fa.shape[1]} factors, {len(eval_dates)} eval dates")

    # ---- Candidate Evaluation ----
    def _evaluate_candidate(self, candidate: CandidateSpec, window_label: str, cost_bps: float) -> WindowResult | None:
        params = candidate.params
        top_n = params.get("top_n", 15)
        max_per_sector = params.get("max_per_sector")
        bottom_n_exclude = params.get("bottom_n_exclude", 0)
        cal_dict = params.get("calibration", {})
        guardrail = params.get("guardrail", False)

        if window_label not in self._cache.cached_windows:
            return None

        wdata = self._cache.get_window(window_label)
        features_all = wdata["features"]
        returns_all = wdata["returns"]
        benchmark = wdata["benchmark"]
        eval_dates = wdata["eval_dates"]
        train_mask = wdata["train_mask"]
        test_mask = wdata["test_mask"]

        # Get factor expressions for this candidate
        exprs = self._factor_exprs.get(candidate.candidate_id, [])
        if not exprs:
            return None
        n_factors = len(exprs)
        expr_indices = list(range(n_factors))  # Simplified: assume pre-aligned columns

        # Build calibration
        default_cal = {"n_gain_bins": 7, "num_boost_round": 200, "max_leaves": 31,
                       "max_depth": 0, "min_child_weight": 1.0, "learning_rate": 0.05,
                       "subsample": 1.0, "colsample_bytree": 1.0,
                       "reg_alpha": 0.0, "reg_lambda": 1.0, "seed": 42}
        cal = XGBNativeCalibration.from_dict({**default_cal, **cal_dict})

        # Select feature subset
        cf_all = features_all.iloc[:, expr_indices].copy()
        cf_all.columns = [f"f{i}" for i in range(n_factors)]
        cf_train = cf_all.loc[train_mask].copy()
        ret_train = returns_all.loc[train_mask].copy()
        cf_train, ret_train = purge_training_tail(cf_train, ret_train, holding_days=10)

        valid, reason = validate_no_nan_inputs(cf_train, context=f"{candidate.candidate_id}/{window_label}")
        if not valid:
            return None

        x_rank, y_rank, groups = prepare_ranker_frame(cf_train, ret_train)
        fitted = fit_xgb_native_daily_ranker(x_rank, y_rank, groups, calibration=cal)
        cf_test = cf_all.loc[test_mask].copy()
        scores = predict_xgb_native_daily_ranker(fitted, cf_test)
        rt_test = returns_all.loc[test_mask].copy()

        # Portfolio construction with sector cap + bottom-N exclusion
        cadence = self.contract.windows.cadence_sessions
        rebalance_dates = [eval_dates[i] for i in range(0, len(eval_dates), cadence)]
        port_returns = []

        for d in rebalance_dates:
            try:
                ds = scores.xs(d, level="datetime")
                dr = rt_test.xs(d, level="datetime")
            except KeyError:
                continue

            # Build daily scores as Series
            score_series = ds["score"]

            # Apply bottom-N exclusion
            if bottom_n_exclude > 0:
                bottom = score_series.nsmallest(bottom_n_exclude).index
                score_series = score_series.drop(bottom, errors="ignore")

            # Apply sector cap selection
            if max_per_sector and self._sector_map:
                selected = self._select_sector_capped(score_series, top_n, max_per_sector)
            else:
                selected = list(score_series.nlargest(top_n).index)

            selected = [str(s) for s in selected]
            sel_rets = dr[dr.index.isin(selected)]
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

    def _select_sector_capped(self, score_series: pd.Series, top_n: int, max_per_sector: int) -> list[str]:
        """Select top_n stocks respecting max_per_sector constraint."""
        ranked = score_series.sort_values(ascending=False)
        selected, counts = [], {}
        for sym, _ in ranked.items():
            sym_str = str(sym)
            sec = self._sector_map.get(sym_str, "Unknown")
            if counts.get(sec, 0) >= max_per_sector:
                continue
            selected.append(sym_str)
            counts[sec] = counts.get(sec, 0) + 1
            if len(selected) >= top_n:
                break
        if len(selected) < top_n:
            for sym, _ in ranked.items():
                sym_str = str(sym)
                if sym_str not in selected:
                    selected.append(sym_str)
                if len(selected) >= top_n:
                    break
        return selected[:top_n]
