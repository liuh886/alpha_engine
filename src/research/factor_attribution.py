"""Factor Return Attribution Engine.

Attributes portfolio returns to a set of factors using a cross-sectional
factor model. For each period t:

    R_portfolio(t) = sum_i(beta_i * F_i(t)) + epsilon(t)

Where F_i(t) is the quintile-spread return for factor i, beta_i is the
OLS-estimated exposure (loading), and epsilon is the unexplained residual.

Attribution metrics:
- Return contribution: beta_i * mean(F_i)
- Risk contribution:   beta_i^2 * var(F_i) / var(R_portfolio)
- Attribution R^2:     how well the factor model explains portfolio returns
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from src.common.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FactorContribution:
    """Attribution result for a single factor."""

    factor_name: str
    factor_expression: str
    factor_ic: float  # this factor's IC
    factor_return: float  # quintile spread * factor exposure
    return_contribution_pct: float  # % of total return attributable to this factor
    risk_contribution_pct: float  # % of total variance attributable to this factor
    exposure: float  # average factor loading (z-scored exposure)

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "factor_expression": self.factor_expression,
            "factor_ic": round(self.factor_ic, 6),
            "factor_return": round(self.factor_return, 6),
            "return_contribution_pct": round(self.return_contribution_pct, 4),
            "risk_contribution_pct": round(self.risk_contribution_pct, 4),
            "exposure": round(self.exposure, 6),
        }


@dataclass
class AttributionReport:
    """Complete factor attribution report for a strategy."""

    strategy_name: str
    market: str
    period: str  # "2021-01-01 to 2025-12-31"
    total_return: float  # strategy total return
    benchmark_return: float  # benchmark total return
    excess_return: float  # alpha
    factor_contributions: list[FactorContribution]
    unexplained_return: float  # residual (total - sum of factor contributions)
    factor_coverage: float  # % of return explained by factors
    attribution_confidence: float  # R^2 of the factor model

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "market": self.market,
            "period": self.period,
            "total_return": round(self.total_return, 6),
            "benchmark_return": round(self.benchmark_return, 6),
            "excess_return": round(self.excess_return, 6),
            "factor_contributions": [fc.to_dict() for fc in self.factor_contributions],
            "unexplained_return": round(self.unexplained_return, 6),
            "factor_coverage": round(self.factor_coverage, 4),
            "attribution_confidence": round(self.attribution_confidence, 4),
        }


@dataclass
class TimeVaryingAttribution:
    """Summary of how factor contributions change across rolling windows."""

    windows: list[AttributionReport]
    factor_trends: dict[str, list[float]]  # factor_name -> [contrib_t1, contrib_t2, ...]
    window_labels: list[str]  # ["2021-01 to 2022-01", "2021-04 to 2022-04", ...]

    def to_dict(self) -> dict:
        return {
            "windows": [w.to_dict() for w in self.windows],
            "factor_trends": {
                k: [round(v, 6) for v in vals]
                for k, vals in self.factor_trends.items()
            },
            "window_labels": self.window_labels,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _init_qlib(market: str) -> None:
    """Initialize Qlib for the given market region."""
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    cfg = build_qlib_init_cfg(None, market=market)
    safe_qlib_init(cfg)


def _load_factor_values(
    expressions: list[str],
    market: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load computed factor values via Qlib's DataHandlerLP.

    Returns a DataFrame indexed by (datetime, instrument) with one column
    per factor expression. Values are cross-sectionally z-scored and NaN-filled.
    """
    # Use raw loading then z-score manually to avoid CSZScoreNorm column issues
    raw_df = _load_raw_factor_values(expressions, market, start_date, end_date)
    # Cross-sectional z-score
    zscored = raw_df.groupby("datetime", group_keys=False).apply(
        lambda x: (x - x.mean()) / (x.std() + 1e-8)
    )
    return zscored.fillna(0.0)


def _load_factor_values_old(
    expressions: list[str],
    market: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Legacy loader with DataHandlerLP (kept for reference)."""
    from qlib.data.dataset.handler import DataHandlerLP

    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "instruments": market,
        "data_loader": {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": expressions,
                    "label": ["Ref($close, -1) / $close - 1"],  # dummy label
                }
            },
        },
        "infer_processors": [
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
    }

    dh = DataHandlerLP(**handler_kwargs)
    factor_df = dh.fetch(col_set="feature")
    # Manual cross-sectional z-score (avoid CSZScoreNorm column mismatch issue)
    factor_df = factor_df.groupby("datetime", group_keys=False).apply(
        lambda x: (x - x.mean()) / (x.std() + 1e-8)
    )
    factor_df = factor_df.fillna(0.0)
    return factor_df


def _load_raw_factor_values(
    expressions: list[str],
    market: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load factor values WITHOUT cross-sectional normalization.

    Used for quintile analysis where raw ranking matters.
    """
    from qlib.data.dataset.handler import DataHandlerLP

    handler_kwargs = {
        "start_time": start_date,
        "end_time": end_date,
        "instruments": market,
        "data_loader": {
            "class": "QlibDataLoader",
            "kwargs": {
                "config": {
                    "feature": expressions,
                    "label": ["Ref($close, -1) / $close - 1"],  # dummy label
                }
            },
        },
        "infer_processors": [
            {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
        ],
        "learn_processors": [{"class": "DropnaLabel"}],
    }

    dh = DataHandlerLP(**handler_kwargs)
    factor_df = dh.fetch(col_set="feature")
    return factor_df


def _compute_forward_returns(
    market: str,
    start_date: str,
    end_date: str,
    forward_days: int = 10,
) -> pd.Series:
    """Compute forward N-day returns for all stocks.

    Returns a Series indexed by (datetime, instrument).
    """
    from qlib.data import D

    instruments = D.instruments(market)
    all_instruments = D.list_instruments(instruments, as_list=True)

    close_df = D.features(
        all_instruments,
        ["$close"],
        start_time=start_date,
        end_time=end_date,
    )
    close_df.columns = ["close"]

    if close_df.empty:
        return pd.Series(dtype=float)

    if isinstance(close_df.index, pd.MultiIndex):
        pivot = close_df["close"].unstack(level="instrument")
    else:
        return pd.Series(dtype=float)

    # forward return: close(t+N) / close(t) - 1
    fwd_ret = pivot.shift(-forward_days) / pivot - 1

    fwd_series = fwd_ret.stack()
    fwd_series.index.names = ["datetime", "instrument"]
    fwd_series.name = "forward_return"
    return fwd_series.dropna()


def _group_by_cross_section(
    df: pd.DataFrame, freq: str = "ME"
) -> list[tuple[str, pd.DataFrame]]:
    """Group a (datetime, instrument) DataFrame by calendar periods."""
    if not isinstance(df.index, pd.MultiIndex):
        return []

    grouped = df.groupby(pd.Grouper(level="datetime", freq=freq))
    result = []
    for period_key, group_df in grouped:
        if group_df.empty:
            continue
        label = str(period_key)[:10]
        result.append((label, group_df))
    return result


def _cross_sectional_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
) -> float:
    """Compute Pearson IC for a single cross-section. Returns NaN if insufficient data."""
    common_idx = factor_values.index.intersection(forward_returns.index)
    if len(common_idx) < 10:
        return np.nan

    fv = factor_values.loc[common_idx].values.astype(float)
    fr = forward_returns.loc[common_idx].values.astype(float)

    mask = np.isfinite(fv) & np.isfinite(fr)
    fv = fv[mask]
    fr = fr[mask]

    if len(fv) < 10:
        return np.nan

    pearson_ic, _ = stats.pearsonr(fv, fr)
    return float(pearson_ic)


def _compute_quintile_spread_series(
    raw_factor_series: pd.Series,
    forward_returns: pd.Series,
    cross_sections: list[tuple[str, pd.DataFrame]],
) -> pd.Series:
    """Compute the quintile-spread return time series for a single factor.

    For each cross-section period: rank stocks into quintiles by raw factor
    value, compute mean return of top quintile minus bottom quintile.

    Returns a Series indexed by period label (date string).
    """
    spread_series: dict[str, float] = {}

    for period_label, section_df in cross_sections:
        # Extract the factor values for this cross-section
        if isinstance(section_df.columns, pd.MultiIndex):
            fv = section_df.iloc[:, 0]
        else:
            fv = section_df.iloc[:, 0]

        section_dates = section_df.index.get_level_values("datetime").unique()
        section_fwd = forward_returns.loc[
            forward_returns.index.get_level_values("datetime").isin(section_dates)
        ]

        fv_by_inst = fv.groupby(level="instrument").mean()
        fwd_by_inst = section_fwd.groupby(level="instrument").mean()

        common = fv_by_inst.index.intersection(fwd_by_inst.index)
        if len(common) < 10:
            continue

        fv_aligned = fv_by_inst.loc[common]
        fwd_aligned = fwd_by_inst.loc[common]

        # Drop NaN
        mask = np.isfinite(fv_aligned.values) & np.isfinite(fwd_aligned.values)
        fv_aligned = fv_aligned[mask]
        fwd_aligned = fwd_aligned[mask]

        if len(fv_aligned) < 10:
            continue

        try:
            quintile_labels = pd.qcut(
                fv_aligned, q=5, labels=[1, 2, 3, 4, 5], duplicates="drop"
            )
        except ValueError:
            continue

        q5_mask = quintile_labels == 5
        q1_mask = quintile_labels == 1

        if q5_mask.any() and q1_mask.any():
            spread = float(fwd_aligned[q5_mask].mean() - fwd_aligned[q1_mask].mean())
            spread_series[period_label] = spread

    return pd.Series(spread_series, dtype=float)


def _compute_portfolio_returns(
    market: str,
    start_date: str,
    end_date: str,
) -> pd.Series:
    """Compute equal-weighted portfolio returns (market benchmark).

    Returns a Series indexed by datetime with daily portfolio returns.
    """
    from qlib.data import D

    instruments = D.instruments(market)
    all_instruments = D.list_instruments(instruments, as_list=True)

    close_df = D.features(
        all_instruments,
        ["$close"],
        start_time=start_date,
        end_time=end_date,
    )
    close_df.columns = ["close"]

    if close_df.empty:
        return pd.Series(dtype=float)

    if isinstance(close_df.index, pd.MultiIndex):
        pivot = close_df["close"].unstack(level="instrument")
    else:
        return pd.Series(dtype=float)

    # Daily returns for each stock
    daily_returns = pivot.pct_change()

    # Equal-weighted portfolio return
    portfolio_returns = daily_returns.mean(axis=1)
    portfolio_returns.name = "portfolio_return"
    return portfolio_returns.dropna()


def _estimate_factor_model(
    portfolio_returns_monthly: pd.Series,
    factor_spread_df: pd.DataFrame,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Estimate the factor model via OLS: R_p = X * beta + epsilon.

    Args:
        portfolio_returns_monthly: Monthly portfolio returns, indexed by period label.
        factor_spread_df: DataFrame with factor quintile-spread returns per period,
            columns are factor names, rows are period labels.

    Returns:
        (betas, r_squared, residuals)
    """
    # Align on common periods
    common_periods = portfolio_returns_monthly.index.intersection(factor_spread_df.index)
    if len(common_periods) < 3:
        n_factors = factor_spread_df.shape[1]
        return np.zeros(n_factors), 0.0, np.array([])

    y = portfolio_returns_monthly.loc[common_periods].values.astype(float)
    X = factor_spread_df.loc[common_periods].values.astype(float)

    # Drop rows with NaN in either y or any X column
    mask = np.isfinite(y)
    for col_idx in range(X.shape[1]):
        mask &= np.isfinite(X[:, col_idx])

    y = y[mask]
    X = X[mask]

    if len(y) < 3 or X.shape[1] == 0:
        n_factors = factor_spread_df.shape[1]
        return np.zeros(n_factors), 0.0, np.array([])

    # OLS: beta = (X'X)^{-1} X'y
    # Add intercept column
    n_obs = len(y)
    X_with_intercept = np.column_stack([np.ones(n_obs), X])

    try:
        beta_full, residuals_sum, rank, sv = np.linalg.lstsq(
            X_with_intercept, y, rcond=None
        )
    except np.linalg.LinAlgError:
        n_factors = factor_spread_df.shape[1]
        return np.zeros(n_factors), 0.0, np.array([])

    intercept = beta_full[0]
    betas = beta_full[1:]

    # Predicted values and residuals
    y_pred = X_with_intercept @ beta_full
    residuals = y - y_pred

    # R^2
    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-15 else 0.0

    return betas, float(r_squared), residuals


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def attribute_returns(
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    strategy_config: str | None = None,
    factor_ids: list[int] | None = None,
) -> AttributionReport:
    """Attribute portfolio returns to a set of factors.

    Uses a cross-sectional factor model estimated via OLS:

        R_portfolio(t) = sum_i(beta_i * F_i(t)) + epsilon(t)

    Where F_i(t) is the quintile-spread return for factor i at time t,
    beta_i is the OLS-estimated exposure (loading), and epsilon is the
    residual.

    Args:
        market: ``"us"`` or ``"cn"``.
        start_date: Start of attribution window.
        end_date: End of attribution window.
        strategy_config: Path to strategy YAML config (reserved for future use).
        factor_ids: Specific factor IDs to attribute. If ``None``, uses all
            Active factors from the FactorRegistry.

    Returns:
        An ``AttributionReport`` with per-factor contributions.
    """
    from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

    log.info(
        "Starting factor attribution",
        market=market,
        start=start_date,
        end=end_date,
        factor_ids=factor_ids,
    )

    # ------------------------------------------------------------------
    # 1. Load factor metadata from registry
    # ------------------------------------------------------------------
    registry = FactorRegistry()

    if factor_ids is not None:
        factors_meta = []
        for fid in factor_ids:
            f = registry.get_factor(fid)
            if f is None:
                log.warning("Factor id not found, skipping", factor_id=fid)
                continue
            factors_meta.append(f)
    else:
        factors_meta = registry.list_factors(stage=STAGE_ACTIVE)

    if not factors_meta:
        log.warning("No factors found for attribution")
        return AttributionReport(
            strategy_name=strategy_config or "default",
            market=market,
            period=f"{start_date} to {end_date}",
            total_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            factor_contributions=[],
            unexplained_return=0.0,
            factor_coverage=0.0,
            attribution_confidence=0.0,
        )

    factor_names = [f["name"] for f in factors_meta]
    factor_expressions = [f["expression"] for f in factors_meta]

    log.info("Factors loaded for attribution", n_factors=len(factors_meta), names=factor_names)

    # ------------------------------------------------------------------
    # 2. Initialize Qlib and load data
    # ------------------------------------------------------------------
    _init_qlib(market)

    # Load z-scored factor values (for IC and exposure computation)
    try:
        factor_df = _load_factor_values(factor_expressions, market, start_date, end_date)
    except Exception as exc:
        log.error("Failed to load factor values", error=str(exc))
        raise

    if factor_df.empty:
        log.warning("No factor data returned")
        return AttributionReport(
            strategy_name=strategy_config or "default",
            market=market,
            period=f"{start_date} to {end_date}",
            total_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            factor_contributions=[],
            unexplained_return=0.0,
            factor_coverage=0.0,
            attribution_confidence=0.0,
        )

    # Load raw factor values (for quintile ranking)
    try:
        raw_factor_df = _load_raw_factor_values(
            factor_expressions, market, start_date, end_date
        )
    except Exception:
        raw_factor_df = factor_df

    # Compute forward returns
    fwd_returns = _compute_forward_returns(market, start_date, end_date, forward_days=10)
    if fwd_returns.empty:
        log.warning("No forward returns computed")

    # ------------------------------------------------------------------
    # 3. Compute per-factor IC and quintile-spread return series
    # ------------------------------------------------------------------
    # Group by monthly cross-sections
    cross_sections_raw = _group_by_cross_section(raw_factor_df, freq="ME")
    cross_sections_z = _group_by_cross_section(factor_df, freq="ME")

    # Get column mapping
    if isinstance(raw_factor_df.columns, pd.MultiIndex):
        raw_cols = [c[0] for c in raw_factor_df.columns]
    else:
        raw_cols = list(raw_factor_df.columns)

    if isinstance(factor_df.columns, pd.MultiIndex):
        z_cols = [c[0] for c in factor_df.columns]
    else:
        z_cols = list(factor_df.columns)

    # Build per-factor quintile-spread return series
    factor_spread_dict: dict[str, pd.Series] = {}
    factor_ic_dict: dict[str, float] = {}

    for col_idx, (factor_name, expression) in enumerate(
        zip(factor_names, factor_expressions)
    ):
        # --- Quintile-spread return series ---
        if col_idx < len(raw_cols):
            # Extract single-factor raw data
            if isinstance(raw_factor_df.columns, pd.MultiIndex):
                single_raw = raw_factor_df.iloc[:, [col_idx]]
            else:
                single_raw = raw_factor_df[[raw_cols[col_idx]]]

            single_raw_cross_sections = _group_by_cross_section(single_raw, freq="ME")

            spread_ts = _compute_quintile_spread_series(
                single_raw.iloc[:, 0] if single_raw.shape[1] == 1 else single_raw.iloc[:, 0],
                fwd_returns,
                single_raw_cross_sections,
            )
            factor_spread_dict[factor_name] = spread_ts
        else:
            factor_spread_dict[factor_name] = pd.Series(dtype=float)

        # --- Factor IC ---
        if col_idx < len(z_cols) and not fwd_returns.empty:
            period_ics: list[float] = []
            for period_label, section_df in cross_sections_z:
                if isinstance(section_df.columns, pd.MultiIndex):
                    fv = section_df.iloc[:, col_idx]
                else:
                    fv = section_df[z_cols[col_idx]]

                section_dates = section_df.index.get_level_values("datetime").unique()
                section_fwd = fwd_returns.loc[
                    fwd_returns.index.get_level_values("datetime").isin(section_dates)
                ]

                fv_by_inst = fv.groupby(level="instrument").mean()
                fwd_by_inst = section_fwd.groupby(level="instrument").mean()

                ic = _cross_sectional_ic(fv_by_inst, fwd_by_inst)
                if np.isfinite(ic):
                    period_ics.append(ic)

            factor_ic_dict[factor_name] = (
                float(np.mean(period_ics)) if period_ics else 0.0
            )
        else:
            factor_ic_dict[factor_name] = 0.0

    # ------------------------------------------------------------------
    # 4. Build the factor-spread DataFrame and portfolio return series
    # ------------------------------------------------------------------
    factor_spread_df = pd.DataFrame(factor_spread_dict)

    # Drop factors with no data
    valid_factors = [
        name for name in factor_names if name in factor_spread_df.columns
        and factor_spread_df[name].notna().any()
    ]
    if not valid_factors:
        log.warning("No factors have valid quintile-spread data")
        return AttributionReport(
            strategy_name=strategy_config or "default",
            market=market,
            period=f"{start_date} to {end_date}",
            total_return=0.0,
            benchmark_return=0.0,
            excess_return=0.0,
            factor_contributions=[],
            unexplained_return=0.0,
            factor_coverage=0.0,
            attribution_confidence=0.0,
        )

    factor_spread_df = factor_spread_df[valid_factors]

    # Compute monthly portfolio returns
    portfolio_daily = _compute_portfolio_returns(market, start_date, end_date)
    if portfolio_daily.empty:
        log.warning("No portfolio returns computed")
        # Fall back: use equal-weighted average of factor spreads as proxy
        portfolio_monthly = factor_spread_df.mean(axis=1)
    else:
        portfolio_monthly = portfolio_daily.resample("ME").apply(
            lambda x: (1 + x).prod() - 1
        )
        # Align index to match period labels from cross-sections
        portfolio_monthly.index = portfolio_monthly.index.strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # 5. Estimate factor model via OLS
    # ------------------------------------------------------------------
    betas, r_squared, residuals = _estimate_factor_model(
        portfolio_monthly, factor_spread_df
    )

    # ------------------------------------------------------------------
    # 6. Compute attribution metrics
    # ------------------------------------------------------------------
    total_return = float(portfolio_monthly.sum()) if not portfolio_monthly.empty else 0.0
    benchmark_return = 0.0  # equal-weighted market is both portfolio and benchmark proxy
    excess_return = total_return - benchmark_return

    # Factor return contributions: beta_i * mean(F_i)
    factor_mean_returns = factor_spread_df.mean()
    factor_contributions_raw = betas * factor_mean_returns.values

    # Sum of explained return
    sum_explained = float(np.sum(factor_contributions_raw))

    # Risk contributions: beta_i^2 * var(F_i) / var(R_portfolio)
    factor_variances = factor_spread_df.var()
    portfolio_variance = float(portfolio_monthly.var()) if portfolio_monthly.shape[0] > 1 else 1e-15

    if portfolio_variance < 1e-15:
        risk_contributions_raw = np.zeros(len(valid_factors))
    else:
        risk_contributions_raw = (betas**2 * factor_variances.values) / portfolio_variance

    # Normalize risk contributions to sum to 100% (if non-zero)
    total_risk_raw = float(np.sum(risk_contributions_raw))
    if total_risk_raw > 1e-15:
        risk_contributions_pct = (risk_contributions_raw / total_risk_raw) * 100.0
    else:
        risk_contributions_pct = np.zeros(len(valid_factors))

    # Return contributions as percentage of total return
    if abs(total_return) > 1e-15:
        return_contributions_pct = (factor_contributions_raw / total_return) * 100.0
    else:
        return_contributions_pct = np.zeros(len(valid_factors))

    # Factor coverage: what % of total return is explained
    factor_coverage = (
        abs(sum_explained) / abs(total_return) * 100.0
        if abs(total_return) > 1e-15
        else 0.0
    )
    factor_coverage = min(factor_coverage, 100.0)

    unexplained_return = total_return - sum_explained

    # ------------------------------------------------------------------
    # 7. Build FactorContribution objects
    # ------------------------------------------------------------------
    factor_meta_by_name = {f["name"]: f for f in factors_meta}
    contributions: list[FactorContribution] = []

    for i, fname in enumerate(valid_factors):
        meta = factor_meta_by_name.get(fname, {})
        contributions.append(
            FactorContribution(
                factor_name=fname,
                factor_expression=meta.get("expression", ""),
                factor_ic=factor_ic_dict.get(fname, 0.0),
                factor_return=float(factor_contributions_raw[i]),
                return_contribution_pct=float(return_contributions_pct[i]),
                risk_contribution_pct=float(risk_contributions_pct[i]),
                exposure=float(betas[i]),
            )
        )

    # Sort by absolute return contribution descending
    contributions.sort(key=lambda c: abs(c.factor_return), reverse=True)

    report = AttributionReport(
        strategy_name=strategy_config or "default",
        market=market,
        period=f"{start_date} to {end_date}",
        total_return=total_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        factor_contributions=contributions,
        unexplained_return=unexplained_return,
        factor_coverage=factor_coverage,
        attribution_confidence=r_squared,
    )

    log.info(
        "Factor attribution complete",
        market=market,
        n_factors=len(contributions),
        total_return=round(total_return, 6),
        r_squared=round(r_squared, 4),
        factor_coverage=round(factor_coverage, 2),
    )

    return report


def attribute_returns_rolling(
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    factor_ids: list[int] | None = None,
    window_months: int = 12,
    step_months: int = 3,
) -> TimeVaryingAttribution:
    """Compute attribution over rolling windows.

    Generates a sequence of overlapping windows of length *window_months*,
    stepping forward by *step_months*, and runs ``attribute_returns`` on each
    window.  Returns a :class:`TimeVaryingAttribution` that bundles the
    per-window reports together with a factor-trend summary showing how each
    factor's return contribution evolves over time.

    Args:
        market: ``"us"`` or ``"cn"``.
        start_date: Start of the first window.
        end_date: End of the last window.
        factor_ids: Specific factor IDs to attribute.  ``None`` uses all
            Active factors from the FactorRegistry.
        window_months: Length of each attribution window in months.
        step_months: Step size between consecutive windows in months.

    Returns:
        A :class:`TimeVaryingAttribution` containing per-window reports,
        factor contribution trends, and human-readable window labels.
    """
    import calendar

    def _add_months(dt: datetime, months: int) -> datetime:
        """Add *months* calendar months to *dt*, clamping the day to the
        last valid day of the target month."""
        total_months = dt.year * 12 + dt.month - 1 + months
        new_year, new_month = divmod(total_months, 12)
        new_month += 1
        max_day = calendar.monthrange(new_year, new_month)[1]
        return dt.replace(year=new_year, month=new_month, day=min(dt.day, max_day))

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # Generate rolling window boundaries
    windows: list[AttributionReport] = []
    window_labels: list[str] = []
    window_starts: list[datetime] = []

    current_start = start_dt
    while True:
        window_end = _add_months(current_start, window_months)
        if window_end > end_dt:
            break
        window_starts.append(current_start)
        current_start = _add_months(current_start, step_months)

    if not window_starts:
        log.warning(
            "No rolling windows fit within the requested date range",
            start_date=start_date,
            end_date=end_date,
            window_months=window_months,
        )
        return TimeVaryingAttribution(
            windows=[],
            factor_trends={},
            window_labels=[],
        )

    log.info(
        "Starting rolling attribution",
        market=market,
        n_windows=len(window_starts),
        window_months=window_months,
        step_months=step_months,
    )

    for ws in window_starts:
        we = _add_months(ws, window_months)
        ws_str = ws.strftime("%Y-%m-%d")
        we_str = we.strftime("%Y-%m-%d")
        label = f"{ws_str} to {we_str}"

        log.info("Computing attribution for window", window=label)
        try:
            report = attribute_returns(
                market=market,
                start_date=ws_str,
                end_date=we_str,
                factor_ids=factor_ids,
            )
            windows.append(report)
            window_labels.append(label)
        except Exception as exc:
            log.error("Attribution failed for window", window=label, error=str(exc))
            # Append an empty report placeholder so indices stay aligned
            windows.append(
                AttributionReport(
                    strategy_name="default",
                    market=market,
                    period=label,
                    total_return=0.0,
                    benchmark_return=0.0,
                    excess_return=0.0,
                    factor_contributions=[],
                    unexplained_return=0.0,
                    factor_coverage=0.0,
                    attribution_confidence=0.0,
                )
            )
            window_labels.append(label)

    # Build factor trends: collect each factor's return_contribution_pct across windows
    # Discover all factor names that appeared in any window
    all_factor_names: set[str] = set()
    for report in windows:
        for fc in report.factor_contributions:
            all_factor_names.add(fc.factor_name)

    factor_trends: dict[str, list[float]] = {name: [] for name in sorted(all_factor_names)}
    for report in windows:
        contrib_by_name = {fc.factor_name: fc.return_contribution_pct for fc in report.factor_contributions}
        for name in factor_trends:
            factor_trends[name].append(contrib_by_name.get(name, 0.0))

    result = TimeVaryingAttribution(
        windows=windows,
        factor_trends=factor_trends,
        window_labels=window_labels,
    )

    log.info(
        "Rolling attribution complete",
        n_windows=len(windows),
        n_factors=len(factor_trends),
    )

    return result
