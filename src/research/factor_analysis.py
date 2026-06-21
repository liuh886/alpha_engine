"""Factor IC (Information Coefficient) Analysis Engine.

Computes cross-sectional Pearson and Spearman IC for each Alpha158 factor,
aggregates statistics across time periods, and provides IC decay analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from src.common.logging import get_logger
from src.common.paths import ARTIFACTS_DIR

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FactorICResult:
    """IC statistics for a single factor."""

    factor_name: str
    ic: float  # Mean cross-sectional Pearson IC
    rank_ic: float  # Mean cross-sectional Spearman IC
    ic_std: float  # Std of IC across time periods
    ic_ir: float  # IC / ic_std (Information Ratio)
    positive_ic_ratio: float  # % of periods with positive IC
    t_stat: float  # t-statistic for H0: IC=0

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "ic": round(self.ic, 6),
            "rank_ic": round(self.rank_ic, 6),
            "ic_std": round(self.ic_std, 6),
            "ic_ir": round(self.ic_ir, 4),
            "positive_ic_ratio": round(self.positive_ic_ratio, 4),
            "t_stat": round(self.t_stat, 4),
        }


@dataclass
class FactorAnalysisReport:
    """Complete IC analysis report."""

    market: str
    date_range: tuple[str, str]
    forward_days: int
    n_periods: int
    factors: list[FactorICResult]
    top_factors: list[FactorICResult]  # Top 20 by |rank_ic|
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "date_range": list(self.date_range),
            "forward_days": self.forward_days,
            "n_periods": self.n_periods,
            "factors": [f.to_dict() for f in self.factors],
            "top_factors": [f.to_dict() for f in self.top_factors],
            "generated_at": self.generated_at,
        }


@dataclass
class DecayPoint:
    """IC value at a specific forward-return lag."""

    lag_days: int
    ic: float

    def to_dict(self) -> dict[str, Any]:
        return {"lag_days": self.lag_days, "ic": round(self.ic, 6)}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

_CACHE_DIR = ARTIFACTS_DIR / "factor_ic"


def _cache_path(market: str, start: str, end: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{market}_{start}_{end}.json"


def _load_cached(market: str, start: str, end: str) -> dict | None:
    path = _cache_path(market, start, end)
    if path.exists():
        try:
            import json

            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log.debug("Failed to read IC cache", path=str(path), exc_info=True)
    return None


def _save_cache(market: str, start: str, end: str, data: dict) -> None:
    import json

    path = _cache_path(market, start, end)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("IC cache saved", path=str(path))


# ---------------------------------------------------------------------------
# Factor loading from Qlib config
# ---------------------------------------------------------------------------


def _load_factor_names(market: str) -> list[str]:
    """Load factor expression list from the workflow YAML config."""
    from src.common.paths import CONFIG_DIR

    config_name = f"{market}_lgbm_workflow.yaml"
    config_file = CONFIG_DIR / config_name
    if not config_file.exists():
        # Fallback: try linear workflow
        config_name = f"{market}_workflow.yaml"
        config_file = CONFIG_DIR / config_name

    if not config_file.exists():
        raise FileNotFoundError(f"Workflow config not found for market={market}")

    with open(config_file) as f:
        config = yaml.safe_load(f)

    handler_cfg = (
        config.get("task", {})
        .get("dataset", {})
        .get("kwargs", {})
        .get("handler", {})
        .get("kwargs", {})
    )
    data_loader = handler_cfg.get("data_loader", {}).get("kwargs", {}).get("config", {})
    features = data_loader.get("feature", [])
    if not features:
        raise ValueError(f"No features found in {config_file}")
    return list(features)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _init_qlib(market: str) -> None:
    """Initialize Qlib with the appropriate market region."""
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    cfg = build_qlib_init_cfg(None, market=market)
    safe_qlib_init(cfg)


def _load_factor_data(
    market: str,
    features: list[str],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load factor values and forward returns using DataHandlerLP.

    Returns (factor_df, label_df) both indexed by (datetime, instrument).
    """
    from qlib.data.dataset.handler import DataHandlerLP

    label_expr = "Ref($close, -{}) / Ref($close, -1) - 1"

    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "instruments": market,
        "data_loader": {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": features,
                    "label": [label_expr],  # placeholder, we compute labels ourselves
                }
            },
        },
        "infer_processors": [
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
    }

    dh = DataHandlerLP(**handler_kwargs)
    factor_df = dh.fetch(col_set="feature")
    label_df = dh.fetch(col_set="label")

    return factor_df, label_df


def _compute_forward_returns(
    market: str,
    start_date: str,
    end_date: str,
    forward_days: int,
) -> pd.Series:
    """Compute forward N-day returns for all stocks as a Series.

    Returns a Series indexed by (datetime, instrument) with forward returns.
    """
    from qlib.data import D

    instruments = D.instruments(market)
    all_instruments = D.list_instruments(instruments, as_list=True)

    # Get close prices with enough buffer for forward returns
    close_fields = ["$close"]
    close_df = D.features(
        all_instruments,
        close_fields,
        start_time=start_date,
        end_time=end_date,
    )
    close_df.columns = ["close"]

    if close_df.empty:
        return pd.Series(dtype=float)

    # Pivot to (datetime x instrument) matrix
    if isinstance(close_df.index, pd.MultiIndex):
        pivot = close_df["close"].unstack(level="instrument")
    else:
        return pd.Series(dtype=float)

    # Compute forward returns: close(t+N) / close(t) - 1
    fwd_ret = pivot.shift(-forward_days) / pivot - 1

    # Melt back to Series with MultiIndex
    fwd_series = fwd_ret.stack()
    fwd_series.index.names = ["datetime", "instrument"]
    fwd_series.name = "forward_return"
    return fwd_series.dropna()


def _group_by_cross_section(df: pd.DataFrame, freq: str = "ME") -> list[tuple[str, pd.DataFrame]]:
    """Group a (datetime, instrument) DataFrame by time periods."""
    if not isinstance(df.index, pd.MultiIndex):
        return []

    df.index.get_level_values("datetime")
    grouped = df.groupby(pd.Grouper(level="datetime", freq=freq))
    result = []
    for period_key, group_df in grouped:
        if group_df.empty:
            continue
        label = str(period_key)[:10]
        result.append((label, group_df))
    return result


def _cross_sectional_ic(
    factor_values: pd.Series, forward_returns: pd.Series
) -> tuple[float, float]:
    """Compute Pearson and Spearman IC for a single cross-section."""
    # Align indices
    common_idx = factor_values.index.intersection(forward_returns.index)
    if len(common_idx) < 10:
        return np.nan, np.nan

    fv = factor_values.loc[common_idx].values.astype(float)
    fr = forward_returns.loc[common_idx].values.astype(float)

    # Drop NaN pairs
    mask = np.isfinite(fv) & np.isfinite(fr)
    fv = fv[mask]
    fr = fr[mask]

    if len(fv) < 10:
        return np.nan, np.nan

    pearson_ic, _ = stats.pearsonr(fv, fr)
    spearman_ic, _ = stats.spearmanr(fv, fr)
    return float(pearson_ic), float(spearman_ic)


def compute_factor_ic(
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "latest",
    factors: list[str] | None = None,
    forward_days: int = 10,
    freq: str = "ME",
    use_cache: bool = True,
) -> FactorAnalysisReport:
    """Compute Information Coefficient for each Alpha158 factor.

    Steps:
    1. Initialize Qlib with market data
    2. Load factor values using DataHandlerLP
    3. Compute forward N-day returns as label
    4. For each time period (monthly cross-sections):
       - Compute Pearson correlation(factor, forward_return) across all stocks
       - Compute Spearman rank correlation
    5. Aggregate: mean, std, IR, t-stat, positive ratio
    6. Rank by |rank_ic| and select top 20
    """
    import qlib

    # Init Qlib FIRST — must be before any qlib.data.D usage
    _init_qlib(market)

    # Resolve end_date
    if end_date == "latest" or not end_date:
        calendar = qlib.data.D.calendar()
        end_date = str(pd.Timestamp(calendar[-1]).strftime("%Y-%m-%d"))

    # Check cache
    if use_cache:
        cached = _load_cached(market, start_date, end_date)
        if cached:
            log.info("Returning cached IC report", market=market)
            # Reconstruct from cache
            factors_list = [FactorICResult(**f) for f in cached.get("factors", [])]
            top_list = [FactorICResult(**f) for f in cached.get("top_factors", [])]
            return FactorAnalysisReport(
                market=cached["market"],
                date_range=tuple(cached["date_range"]),
                forward_days=cached["forward_days"],
                n_periods=cached["n_periods"],
                factors=factors_list,
                top_factors=top_list,
                generated_at=cached["generated_at"],
            )

    # Qlib already initialized above — load factor names
    if factors is None:
        factors = _load_factor_names(market)

    log.info(
        "Computing factor IC",
        market=market,
        n_factors=len(factors),
        start=start_date,
        end=end_date,
        forward_days=forward_days,
    )

    # Load factor data via DataHandlerLP
    from qlib.data.dataset.handler import DataHandlerLP

    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "instruments": market,
        "data_loader": {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": factors,
                    "label": ["Ref($close, -1) / $close - 1"],  # dummy
                }
            },
        },
        "infer_processors": [
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
    }

    dh = DataHandlerLP(**handler_kwargs)
    factor_df = dh.fetch(col_set="feature")

    if factor_df.empty:
        log.warning("No factor data returned")
        return FactorAnalysisReport(
            market=market,
            date_range=(start_date, end_date),
            forward_days=forward_days,
            n_periods=0,
            factors=[],
            top_factors=[],
            generated_at=datetime.now().isoformat(),
        )

    # Compute forward returns
    fwd_returns = _compute_forward_returns(market, start_date, end_date, forward_days)

    if fwd_returns.empty:
        log.warning("No forward returns computed")
        return FactorAnalysisReport(
            market=market,
            date_range=(start_date, end_date),
            forward_days=forward_days,
            n_periods=0,
            factors=[],
            top_factors=[],
            generated_at=datetime.now().isoformat(),
        )

    # Align factor data with forward returns
    common_dates = (
        factor_df.index.get_level_values("datetime")
        .intersection(fwd_returns.index.get_level_values("datetime"))
        .unique()
    )
    if len(common_dates) == 0:
        log.warning("No overlapping dates between factor data and forward returns")
        return FactorAnalysisReport(
            market=market,
            date_range=(start_date, end_date),
            forward_days=forward_days,
            n_periods=0,
            factors=[],
            top_factors=[],
            generated_at=datetime.now().isoformat(),
        )

    factor_df = factor_df.loc[factor_df.index.get_level_values("datetime").isin(common_dates)]
    fwd_returns = fwd_returns.loc[fwd_returns.index.get_level_values("datetime").isin(common_dates)]

    # Group by cross-section periods
    cross_sections = _group_by_cross_section(factor_df, freq=freq)
    if not cross_sections:
        log.warning("No cross-sections formed")
        return FactorAnalysisReport(
            market=market,
            date_range=(start_date, end_date),
            forward_days=forward_days,
            n_periods=0,
            factors=[],
            top_factors=[],
            generated_at=datetime.now().isoformat(),
        )

    # Get factor column names
    if isinstance(factor_df.columns, pd.MultiIndex):
        factor_cols = [c[0] for c in factor_df.columns]
    else:
        factor_cols = list(factor_df.columns)

    # Compute IC for each factor across cross-sections
    factor_results: list[FactorICResult] = []

    for col_idx, factor_name in enumerate(factor_cols):
        period_ics: list[float] = []
        period_rank_ics: list[float] = []

        for period_label, section_df in cross_sections:
            # Get factor values for this cross-section
            if isinstance(section_df.columns, pd.MultiIndex):
                fv = section_df.iloc[:, col_idx]
            else:
                fv = section_df[factor_name]

            # Get corresponding forward returns
            section_dates = section_df.index.get_level_values("datetime").unique()
            section_fwd = fwd_returns.loc[
                fwd_returns.index.get_level_values("datetime").isin(section_dates)
            ]

            # Flatten both to instrument-level for this cross-section
            # Take the mean across dates in the period for each instrument
            fv_by_inst = fv.groupby(level="instrument").mean()
            fwd_by_inst = section_fwd.groupby(level="instrument").mean()

            pearson_ic, spearman_ic = _cross_sectional_ic(fv_by_inst, fwd_by_inst)

            if np.isfinite(pearson_ic):
                period_ics.append(pearson_ic)
            if np.isfinite(spearman_ic):
                period_rank_ics.append(spearman_ic)

        if not period_ics:
            continue

        ic_array = np.array(period_ics)
        rank_ic_array = np.array(period_rank_ics)

        mean_ic = float(np.mean(ic_array))
        mean_rank_ic = float(np.mean(rank_ic_array))
        ic_std = float(np.std(ic_array, ddof=1)) if len(ic_array) > 1 else 0.0
        ic_ir = mean_ic / ic_std if ic_std > 1e-10 else 0.0
        pos_ratio = float(np.mean(ic_array > 0))
        t_stat = float(mean_ic / (ic_std / np.sqrt(len(ic_array)))) if ic_std > 1e-10 else 0.0

        factor_results.append(
            FactorICResult(
                factor_name=factor_name,
                ic=mean_ic,
                rank_ic=mean_rank_ic,
                ic_std=ic_std,
                ic_ir=ic_ir,
                positive_ic_ratio=pos_ratio,
                t_stat=t_stat,
            )
        )

    # Sort by |rank_ic| descending for top factors
    sorted_by_abs = sorted(factor_results, key=lambda f: abs(f.rank_ic), reverse=True)
    top_factors = sorted_by_abs[:20]

    report = FactorAnalysisReport(
        market=market,
        date_range=(start_date, end_date),
        forward_days=forward_days,
        n_periods=len(cross_sections),
        factors=sorted_by_abs,
        top_factors=top_factors,
        generated_at=datetime.now().isoformat(),
    )

    # Cache
    if use_cache:
        _save_cache(market, start_date, end_date, report.to_dict())

    log.info(
        "Factor IC computation complete",
        market=market,
        n_factors=len(factor_results),
        n_periods=len(cross_sections),
    )

    return report


def compute_factor_decay(
    market: str = "us",
    factor_name: str = "",
    max_lag: int = 20,
    start_date: str = "2021-01-01",
    end_date: str = "latest",
) -> list[DecayPoint]:
    """Compute IC at different forward-return horizons (1d, 2d, ..., max_lag days).

    Returns list of DecayPoint with (lag_days, mean_ic).
    """
    if not factor_name:
        return []

    import qlib

    # Init Qlib FIRST
    _init_qlib(market)

    # Resolve end_date
    if end_date == "latest" or not end_date:
        calendar = qlib.data.D.calendar()
        end_date = str(pd.Timestamp(calendar[-1]).strftime("%Y-%m-%d"))

    log.info(
        "Computing factor decay",
        factor=factor_name,
        max_lag=max_lag,
        market=market,
    )

    # Load single factor via DataHandlerLP
    from qlib.data.dataset.handler import DataHandlerLP

    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "instruments": market,
        "data_loader": {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": [factor_name],
                    "label": ["Ref($close, -1) / $close - 1"],
                }
            },
        },
        "infer_processors": [
            {"class": "CSZScoreNorm", "kwargs": {"fields_group": "feature"}},
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
    }

    dh = DataHandlerLP(**handler_kwargs)
    factor_df = dh.fetch(col_set="feature")

    if factor_df.empty:
        return []

    # Get factor values as Series
    if isinstance(factor_df.columns, pd.MultiIndex):
        fv = factor_df.iloc[:, 0]
    else:
        fv = factor_df.iloc[:, 0]

    # For each lag, compute forward returns and IC
    results: list[DecayPoint] = []
    for lag in range(1, max_lag + 1):
        fwd = _compute_forward_returns(market, start_date, end_date, lag)
        if fwd.empty:
            continue

        # Align
        common_dates = (
            fv.index.get_level_values("datetime")
            .intersection(fwd.index.get_level_values("datetime"))
            .unique()
        )
        if len(common_dates) == 0:
            continue

        fv_aligned = fv.loc[fv.index.get_level_values("datetime").isin(common_dates)]
        fwd_aligned = fwd.loc[fwd.index.get_level_values("datetime").isin(common_dates)]

        # Monthly cross-sections
        sections_fv = _group_by_cross_section(fv_aligned.to_frame("fv"), freq="ME")

        period_ics: list[float] = []
        for period_label, section_df in sections_fv:
            fv_section = section_df["fv"]
            section_dates = section_df.index.get_level_values("datetime").unique()
            fwd_section = fwd_aligned.loc[
                fwd_aligned.index.get_level_values("datetime").isin(section_dates)
            ]

            fv_by_inst = fv_section.groupby(level="instrument").mean()
            fwd_by_inst = fwd_section.groupby(level="instrument").mean()

            pearson_ic, _ = _cross_sectional_ic(fv_by_inst, fwd_by_inst)
            if np.isfinite(pearson_ic):
                period_ics.append(pearson_ic)

        if period_ics:
            results.append(DecayPoint(lag_days=lag, ic=float(np.mean(period_ics))))

    return results
