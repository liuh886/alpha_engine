"""Unified Data Foundation — shared data layer for offline optimization and online execution.

Single source of truth for:
- Provider data loading with identity verification
- Factor expression resolution via canonical factor library
- Feature/return caching with window awareness
- Forward-walking support for online agents
- Sector classification loading

Used by both:
- src/optimization/ (offline parameter search)
- src/execution/ (online signal generation)
- Any agent doing model evaluation

Design principle: same code path for backtest and live — no divergence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.factor_library import load_factor_library, select_factor_groups
from src.optimization.factor_library import FactorLibrary, get_factor_library
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import (
    load_window_benchmark_returns,
    normalize_qlib_frame_index,
)
from src.research.window_policy import (
    WindowSamplingPlan,
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)

RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"


@dataclass
class DataFoundation:
    """Universal data layer — offline optimization AND online execution.

    Usage:
        foundation = DataFoundation(market="us", provider_uri="data/providers/us")
        foundation.initialize()

        # Get factor expressions for any candidate
        exprs = foundation.factor_expressions(["momentum_volatility_volume"])

        # Load window data (cached after first load)
        wdata = foundation.load_window("2024H1", exprs)

        # Online: forward-walk with latest available data
        latest = foundation.load_forward_window(exprs, lookback_sessions=500)

        # Sector classification
        sector_map = foundation.sector_map
    """

    market: str
    benchmark: str = "QQQ"
    provider_uri: str | None = None
    factor_library_path: str = "configs/factor_libraries/ohlcv.yaml"
    universe_config_path: str | None = None
    sector_config_path: str | None = None
    return_expression: str = RETURN_EXPRESSION
    horizon_sessions: int = 10

    # Runtime state
    _initialized: bool = field(default=False, repr=False)
    _runtime: Any = field(default=None, repr=False)
    _symbols: list[str] = field(default_factory=list, repr=False)
    _provider_identity: str = field(default="", repr=False)
    _sector_map: dict[str, str] = field(default_factory=dict, repr=False)
    _universe_config: dict[str, Any] = field(default_factory=dict, repr=False)
    _factor_library: Any = field(default=None, repr=False)
    _unified_factor_library: FactorLibrary | None = field(default=None, repr=False)

    # Feature caches: (window_label, expr_tuple_hash) → DataFrame
    _feature_cache: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)
    _return_cache: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)
    _benchmark_cache: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)

    # Window plan
    _window_plan: WindowSamplingPlan | None = field(default=None, repr=False)
    _eval_dates_by_window: dict[str, pd.DatetimeIndex] = field(default_factory=dict, repr=False)
    _train_windows: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)

    def initialize(self) -> None:
        """Initialize runtime, load metadata, set up window plan."""
        if self._initialized:
            return

        self._init_runtime()
        self._load_universe()
        self._load_sectors()
        self._load_factor_library()
        self._setup_windows()
        self._initialized = True

    # ---- Initialization steps ----

    def _init_runtime(self):
        provider = Path(self.provider_uri or f"data/providers/{self.market}")
        if self.market == "us":
            from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
            self._runtime = QlibUSExecutionRuntime(provider_uri=str(provider))
        elif self.market == "cn":
            from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime
            self._runtime = QlibCNExecutionRuntime(provider_uri=str(provider))
        else:
            raise ValueError(f"unsupported market: {self.market}")
        self._runtime.initialize(Path.cwd())
        meta = self._runtime.metadata()
        self._provider_identity = str(meta.get("provider_identity_sha256", ""))

    def _load_universe(self):
        paths = [
            Path(self.universe_config_path or ""),
            Path(f"configs/research_universes/{self.market}_selected_equities_v3.yaml"),
            Path(f"configs/research_universes/{self.market}_selected_equities_v2.yaml"),
        ]
        for p in paths:
            if p.is_file() and p.exists():
                self._universe_config = yaml.safe_load(p.read_text(encoding="utf-8"))
                break
        if not self._universe_config:
            raise FileNotFoundError("universe config not found")

        requested = [str(s) for s in self._universe_config.get("symbols", [])]
        available = self._runtime.available_symbols()
        normalized = normalize_market_symbols(self.market, requested, available_symbols=available)
        self._symbols = [i.normalized_symbol for i in normalized if i.normalized_symbol in available]

    def _load_sectors(self):
        paths = [
            Path(self.sector_config_path or ""),
            Path(f"configs/research_classifications/{self.market}87_sector_industry_v1.yaml"),
            Path(f"configs/research_classifications/{self.market}130_sector_industry_v1.yaml"),
        ]
        for p in paths:
            if p.is_file() and p.exists():
                raw = yaml.safe_load(p.read_text(encoding="utf-8"))
                records = raw.get("records", raw.get("symbols", {}))
                self._sector_map = {str(k): str(v.get("sector", "Unknown")) for k, v in records.items()}
                break

    def _load_factor_library(self):
        self._factor_library = load_factor_library(Path(self.factor_library_path))
        # Also load the unified factor library
        self._unified_factor_library = get_factor_library()

    def _setup_windows(self):
        cal = self._runtime.calendar("2021-01-01", "2026-12-31")
        avail_end = min(pd.Timestamp("2026-06-30"), cal.max()).strftime("%Y-%m-%d")
        self._window_plan = build_window_sampling_plan(
            cal, "2021-01-01", avail_end,
            first_test_year=2024, last_test_year=2026,
            min_complete_windows=3,
            partial_window_policy="allow_horizon_contained_partial_final_window",
            min_partial_window_eligible_sessions=10,
            horizon_sessions=self.horizon_sessions,
            cadence_sessions=self.horizon_sessions,
        )
        self._eval_dates_by_window = horizon_eligible_dates_by_window(self._window_plan, cal)
        self._train_windows = {
            "2024H1": ("2021-01-01", "2023-12-31"),
            "2024H2": ("2021-01-01", "2024-06-30"),
            "2025H1": ("2021-01-01", "2024-12-31"),
            "2025H2": ("2021-01-01", "2025-06-30"),
            "2026H1": ("2021-01-01", "2025-12-31"),
        }

    # ---- Public API ----

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    @property
    def provider_identity(self) -> str:
        return self._provider_identity

    @property
    def factor_library(self) -> FactorLibrary | None:
        """Unified factor library — all factors from all sources."""
        return self._unified_factor_library

    @property
    def sector_map(self) -> dict[str, str]:
        return dict(self._sector_map)

    @property
    def available_windows(self) -> list[str]:
        return sorted(self._eval_dates_by_window.keys())

    def factor_expressions(self, group_names: list[str]) -> list[str]:
        """Resolve factor group names to Qlib expressions."""
        selected = select_factor_groups(self._factor_library, group_names)
        exprs, seen = [], set()
        for g in selected:
            for f in g.factors:
                if f.expression not in seen:
                    exprs.append(f.expression)
                    seen.add(f.expression)
        return exprs

    def factor_metadata(self, group_names: list[str]) -> list[dict[str, str]]:
        """Get factor metadata for a set of groups."""
        selected = select_factor_groups(self._factor_library, group_names)
        result = []
        for g in selected:
            for f in g.factors:
                result.append({
                    "factor_id": f.factor_id,
                    "display_name": f.display_name,
                    "expression": f.expression,
                    "information_family": f.information_family,
                    "factor_version": f.factor_version,
                })
        return result

    def load_window(
        self,
        window_label: str,
        expressions: list[str],
        *,
        force_reload: bool = False,
    ) -> dict[str, Any]:
        """Load features, returns, and benchmark for a complete window.

        Cached after first load. Set force_reload=True for forward walking.
        """
        cache_key = f"{window_label}:{hash(tuple(expressions))}"
        if not force_reload and cache_key in self._feature_cache:
            return {
                "features": self._feature_cache[cache_key],
                "returns": self._return_cache.get(cache_key),
                "benchmark": self._benchmark_cache.get(cache_key),
                "eval_dates": self._eval_dates_by_window.get(window_label),
                "train_start": self._train_windows.get(window_label, ("", ""))[0],
                "train_end": self._train_windows.get(window_label, ("", ""))[1],
                "symbols": self._symbols,
            }

        train = self._train_windows.get(window_label)
        eval_dates = self._eval_dates_by_window.get(window_label)
        if train is None or eval_dates is None:
            raise ValueError(f"unknown window: {window_label}")

        train_start, train_end = train
        load_end = eval_dates.max().strftime("%Y-%m-%d")

        features = normalize_qlib_frame_index(
            self._runtime.features(self._symbols, expressions, train_start, load_end)
        ).replace([np.inf, -np.inf], np.nan)
        features.columns = [f"feature_{i}" for i in range(len(expressions))]

        returns = normalize_qlib_frame_index(
            self._runtime.features(self._symbols, [self.return_expression], train_start, load_end)
        )
        returns.columns = ["return"]

        benchmark = load_window_benchmark_returns(
            self._runtime,
            benchmark_instrument=self.benchmark,
            return_expression=self.return_expression,
            evaluation_dates=eval_dates,
            start=eval_dates.min().strftime("%Y-%m-%d"),
            end=eval_dates.max().strftime("%Y-%m-%d"),
            provenance="raw_forward_return",
            horizon=self.horizon_sessions,
        )

        self._feature_cache[cache_key] = features
        self._return_cache[cache_key] = returns
        self._benchmark_cache[cache_key] = benchmark

        return {
            "features": features,
            "returns": returns,
            "benchmark": benchmark,
            "eval_dates": eval_dates,
            "train_start": train_start,
            "train_end": train_end,
            "symbols": self._symbols,
        }

    def load_forward_window(
        self,
        expressions: list[str],
        *,
        lookback_sessions: int = 500,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Load latest data for online forward walking.

        Used by live signal generation agents. Always forces reload to
        capture the most recent market data.
        """
        cal = self._runtime.calendar("2021-01-01", "2026-12-31")
        if end_date:
            end_ts = pd.Timestamp(end_date)
            start_ts = cal[cal <= end_ts][-lookback_sessions:].min()
        else:
            end_ts = cal.max()
            start_ts = cal[-lookback_sessions:].min()

        features = normalize_qlib_frame_index(
            self._runtime.features(
                self._symbols, expressions,
                start_ts.strftime("%Y-%m-%d"),
                end_ts.strftime("%Y-%m-%d"),
            )
        ).replace([np.inf, -np.inf], np.nan)
        features.columns = [f"feature_{i}" for i in range(len(expressions))]

        returns = normalize_qlib_frame_index(
            self._runtime.features(
                self._symbols, [self.return_expression],
                start_ts.strftime("%Y-%m-%d"),
                end_ts.strftime("%Y-%m-%d"),
            )
        )
        returns.columns = ["return"]

        return {
            "features": features,
            "returns": returns,
            "symbols": self._symbols,
            "start_date": start_ts.strftime("%Y-%m-%d"),
            "end_date": end_ts.strftime("%Y-%m-%d"),
            "n_sessions": len(cal[(cal >= start_ts) & (cal <= end_ts)]),
        }

    def train_test_split(
        self,
        window_label: str,
        features: pd.DataFrame,
        returns: pd.DataFrame,
    ) -> dict[str, Any]:
        """Split cached window data into train/test sets."""
        train = self._train_windows.get(window_label)
        eval_dates = self._eval_dates_by_window.get(window_label)
        if train is None or eval_dates is None:
            raise ValueError(f"unknown window: {window_label}")

        train_start, train_end = train
        dates = features.index.get_level_values("datetime")
        train_mask = (dates >= pd.Timestamp(train_start)) & (dates <= pd.Timestamp(train_end))
        test_mask = dates.isin(eval_dates)

        return {
            "features_train": features.loc[train_mask].copy(),
            "returns_train": returns.loc[train_mask].copy(),
            "features_test": features.loc[test_mask].copy(),
            "returns_test": returns.loc[test_mask].copy(),
            "train_mask": train_mask,
            "test_mask": test_mask,
            "eval_dates": eval_dates,
        }

    def clear_cache(self) -> None:
        """Clear all cached data (e.g., for forward walking with fresh data)."""
        self._feature_cache.clear()
        self._return_cache.clear()
        self._benchmark_cache.clear()

    def cache_stats(self) -> dict[str, int]:
        return {
            "cached_windows": len(self._feature_cache),
            "total_expressions_cached": sum(
                len(df.columns) for df in self._feature_cache.values()
            ),
        }
