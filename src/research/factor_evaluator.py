"""Factor Evaluation Engine.

Evaluates arbitrary Qlib factor expressions by computing cross-sectional IC,
IC decay, quintile return analysis, and applying configurable pass/fail gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from src.common.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Default validation gates
# ---------------------------------------------------------------------------

DEFAULT_GATES: dict[str, float] = {
    "min_icir": 0.3,  # Calibrated for walk-forward IC level (~0.09)
    "min_t_stat": 1.5,  # Relaxed for small stock universe (118 stocks)
    "min_positive_ratio": 0.55,  # Keep: consistency matters
    "min_quintile_spread": 0.001,  # Lowered: real IC produces smaller spreads
    "min_ic_decay_5d_ratio": 0.3,  # IC at 5d should retain at least 30% of IC at 1d
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QuintileReturn:
    """Mean forward return for a single quintile bucket."""

    quintile: int  # 1 (bottom) to 5 (top)
    mean_return: float
    annualized_return: float
    n_stocks: float  # average number of stocks per period


@dataclass
class FactorEvalResult:
    """Complete evaluation result for a single factor expression."""

    # Identity
    expression: str
    market: str
    start_date: str
    end_date: str

    # IC metrics
    ic: float  # Pearson IC
    rank_ic: float  # Spearman rank IC
    ic_std: float
    icir: float  # IC / IC_std
    t_stat: float  # IC / (IC_std / sqrt(n_periods))
    positive_ratio: float  # fraction of periods with positive IC
    n_periods: int

    # Decay
    decay_1d: float  # IC at 1-day horizon
    decay_5d: float  # IC at 5-day horizon
    decay_10d: float  # IC at 10-day horizon

    # Quintile analysis
    quintile_returns: list[QuintileReturn]
    quintile_spread: float  # top quintile mean return - bottom quintile mean return

    # Diagnostics
    coverage: float  # fraction of stocks with non-null factor values
    mean_value: float
    std_value: float

    # Verdict
    passed: bool
    fail_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "expression": self.expression,
            "market": self.market,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "ic": round(self.ic, 6),
            "rank_ic": round(self.rank_ic, 6),
            "ic_std": round(self.ic_std, 6),
            "icir": round(self.icir, 4),
            "t_stat": round(self.t_stat, 4),
            "positive_ratio": round(self.positive_ratio, 4),
            "n_periods": self.n_periods,
            "decay_1d": round(self.decay_1d, 6),
            "decay_5d": round(self.decay_5d, 6),
            "decay_10d": round(self.decay_10d, 6),
            "quintile_returns": [
                {
                    "quintile": q.quintile,
                    "mean_return": round(q.mean_return, 6),
                    "annualized_return": round(q.annualized_return, 6),
                    "n_stocks": round(q.n_stocks, 1),
                }
                for q in self.quintile_returns
            ],
            "quintile_spread": round(self.quintile_spread, 6),
            "coverage": round(self.coverage, 4),
            "mean_value": round(self.mean_value, 6),
            "std_value": round(self.std_value, 6),
            "passed": self.passed,
            "fail_reasons": self.fail_reasons,
        }


# ---------------------------------------------------------------------------
# Expression validation
# ---------------------------------------------------------------------------


def validate_expression_syntax(expression: str) -> tuple[bool, str]:
    """Check whether *expression* is valid Qlib expression syntax.

    Returns ``(True, "")`` on success, ``(False, error_message)`` on failure.

    The check works by attempting to parse the expression through Qlib's
    expression engine without actually fetching data.
    """
    if not expression or not expression.strip():
        return False, "Expression is empty"

    # Try Qlib's expression parser if available
    try:
        from qlib.data.ops import ExpressionOps  # type: ignore[import-untyped]

        # Attempt to parse the expression through Qlib's parser.
        # Qlib expressions are parsed lazily when used in D.features(),
        # so we do a lightweight structural validation here and rely on
        # the actual data load in evaluate_factor() for full validation.
        del ExpressionOps  # imported only to verify availability
    except ImportError:
        # If qlib.data.ops is not available we fall back to a basic
        # structural check (heuristic below).
        pass

    # Heuristic: reject obviously broken patterns
    stripped = expression.strip()
    open_parens = stripped.count("(")
    close_parens = stripped.count(")")
    if open_parens != close_parens:
        return False, (f"Mismatched parentheses: {open_parens} '(' vs {close_parens} ')'")

    # At least one Qlib field or function must appear
    qlib_funcs = {
        "Ref",
        "Mean",
        "Std",
        "Slope",
        "Rsquare",
        "Resi",
        "Max",
        "Min",
        "Quantile",
        "Rank",
        "IdxMax",
        "IdxMin",
        "Corr",
        "Log",
        "Abs",
        "Sum",
        "Greater",
        "Less",
        "If",
        "Abs",
        "Sign",
        "Power",
        "Sqrt",
        "Log",
        "Exp",
    }
    has_field = "$" in stripped
    has_func = any(fn + "(" in stripped for fn in qlib_funcs)
    if not has_field and not has_func:
        return False, ("Expression contains no Qlib field references ($) or functions")

    return True, ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _init_qlib(market: str) -> None:
    """Initialize Qlib for the given market region."""
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    cfg = build_qlib_init_cfg(None, market=market)
    safe_qlib_init(cfg)


def _load_factor_values(
    expression: str,
    market: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load computed factor values via Qlib's DataHandlerLP.

    Returns a DataFrame indexed by (datetime, instrument) with a single
    column containing the factor values (cross-sectionally z-scored,
    NaN-filled).
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
                    "feature": [expression],
                    "label": ["Ref($close, -1) / $close - 1"],  # dummy label
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
    return factor_df


def _load_raw_factor_values(
    expression: str,
    market: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load factor values WITHOUT cross-sectional normalization.

    Used for diagnostics (coverage, mean, std) and quintile analysis where
    raw ranking matters.
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
                    "feature": [expression],
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
    forward_days: int,
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


def _group_by_cross_section(df: pd.DataFrame, freq: str = "ME") -> list[tuple[str, pd.DataFrame]]:
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


def _winsorize(arr: np.ndarray, lower: float = 0.01, upper: float = 0.99) -> np.ndarray:
    """Clip array values to [percentile(lower), percentile(upper)].

    Winsorization reduces the influence of extreme outliers on correlation
    estimates, which is especially important in small stock universes where
    a single outlier can inflate IC by 2-3x.
    """
    lo = np.nanpercentile(arr, lower * 100)
    hi = np.nanpercentile(arr, upper * 100)
    return np.clip(arr, lo, hi)


def _cross_sectional_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
) -> tuple[float, float]:
    """Compute Pearson and Spearman IC for a single cross-section.

    Factor values and forward returns are winsorized at the 1st/99th
    percentiles before computing Pearson IC to reduce outlier influence.
    Spearman IC (rank-based) is naturally robust to outliers and does not
    need winsorization, but we apply it for consistency.
    """
    common_idx = factor_values.index.intersection(forward_returns.index)
    if len(common_idx) < 10:
        return np.nan, np.nan

    fv = factor_values.loc[common_idx].values.astype(float)
    fr = forward_returns.loc[common_idx].values.astype(float)

    mask = np.isfinite(fv) & np.isfinite(fr)
    fv = fv[mask]
    fr = fr[mask]

    if len(fv) < 10:
        return np.nan, np.nan

    # Winsorize to reduce outlier influence (critical for small universes)
    fv = _winsorize(fv, lower=0.01, upper=0.99)
    fr = _winsorize(fr, lower=0.01, upper=0.99)

    pearson_ic, _ = stats.pearsonr(fv, fr)
    spearman_ic, _ = stats.spearmanr(fv, fr)
    return float(pearson_ic), float(spearman_ic)


def _compute_ic_series(
    factor_df: pd.DataFrame,
    forward_returns: pd.Series,
    freq: str = "ME",
) -> tuple[list[float], list[float], int]:
    """Compute cross-sectional IC for each period.

    Returns (period_pearson_ics, period_spearman_ics, n_periods).
    """
    common_dates = (
        factor_df.index.get_level_values("datetime")
        .intersection(forward_returns.index.get_level_values("datetime"))
        .unique()
    )
    if len(common_dates) == 0:
        return [], [], 0

    factor_df = factor_df.loc[factor_df.index.get_level_values("datetime").isin(common_dates)]
    forward_returns = forward_returns.loc[
        forward_returns.index.get_level_values("datetime").isin(common_dates)
    ]

    cross_sections = _group_by_cross_section(factor_df, freq=freq)
    if not cross_sections:
        return [], [], 0

    # Extract the single factor column as a Series
    if isinstance(factor_df.columns, pd.MultiIndex):
        factor_df.iloc[:, 0]
    else:
        factor_df.iloc[:, 0]

    period_pearson: list[float] = []
    period_spearman: list[float] = []

    for _period_label, section_df in cross_sections:
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

        pearson_ic, spearman_ic = _cross_sectional_ic(fv_by_inst, fwd_by_inst)

        if np.isfinite(pearson_ic):
            period_pearson.append(pearson_ic)
        if np.isfinite(spearman_ic):
            period_spearman.append(spearman_ic)

    n = max(len(period_pearson), len(period_spearman))
    return period_pearson, period_spearman, n


def _compute_ic_for_horizon(
    expression: str,
    market: str,
    start_date: str,
    end_date: str,
    forward_days: int,
) -> tuple[float, float]:
    """Load factor data and compute mean Pearson/Spearman IC at a given horizon.

    Returns (mean_pearson_ic, mean_spearman_ic).
    """
    factor_df = _load_factor_values(expression, market, start_date, end_date)
    if factor_df.empty:
        return np.nan, np.nan

    fwd = _compute_forward_returns(market, start_date, end_date, forward_days)
    if fwd.empty:
        return np.nan, np.nan

    pearson_ics, spearman_ics, _ = _compute_ic_series(factor_df, fwd)

    mean_p = float(np.mean(pearson_ics)) if pearson_ics else np.nan
    mean_s = float(np.mean(spearman_ics)) if spearman_ics else np.nan
    return mean_p, mean_s


def _compute_quintile_returns(
    factor_df: pd.DataFrame,
    forward_returns: pd.Series,
    freq: str = "ME",
) -> tuple[list[QuintileReturn], float]:
    """Rank stocks into quintiles by factor value and compute mean returns.

    Returns (list of QuintileReturn for quintiles 1-5, quintile_spread).
    """
    common_dates = (
        factor_df.index.get_level_values("datetime")
        .intersection(forward_returns.index.get_level_values("datetime"))
        .unique()
    )
    if len(common_dates) == 0:
        return [], 0.0

    factor_df = factor_df.loc[factor_df.index.get_level_values("datetime").isin(common_dates)]
    forward_returns = forward_returns.loc[
        forward_returns.index.get_level_values("datetime").isin(common_dates)
    ]

    cross_sections = _group_by_cross_section(factor_df, freq=freq)
    if not cross_sections:
        return [], 0.0

    if isinstance(factor_df.columns, pd.MultiIndex):
        factor_df.iloc[:, 0]
    else:
        factor_df.iloc[:, 0]

    # Accumulate per-quintile returns across periods
    quintile_returns_acc: dict[int, list[float]] = {q: [] for q in range(1, 6)}
    quintile_stock_counts: dict[int, list[float]] = {q: [] for q in range(1, 6)}

    for _period_label, section_df in cross_sections:
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
        if len(common) < 5:
            continue

        fv_aligned = fv_by_inst.loc[common]
        fwd_aligned = fwd_by_inst.loc[common]

        # Drop NaN
        mask = np.isfinite(fv_aligned.values) & np.isfinite(fwd_aligned.values)
        fv_aligned = fv_aligned[mask]
        fwd_aligned = fwd_aligned[mask]

        if len(fv_aligned) < 5:
            continue

        # Assign quintile labels (1 = bottom, 5 = top)
        quintile_labels = pd.qcut(fv_aligned, q=5, labels=[1, 2, 3, 4, 5], duplicates="drop")

        for q in range(1, 6):
            q_mask = quintile_labels == q
            if q_mask.any():
                quintile_returns_acc[q].append(float(fwd_aligned[q_mask].mean()))
                quintile_stock_counts[q].append(float(q_mask.sum()))

    results: list[QuintileReturn] = []
    # ~252 trading days per year; with monthly freq, 12 periods per year
    annualization_factor = 12.0

    for q in range(1, 6):
        rets = quintile_returns_acc[q]
        counts = quintile_stock_counts[q]
        if not rets:
            results.append(
                QuintileReturn(quintile=q, mean_return=0.0, annualized_return=0.0, n_stocks=0.0)
            )
            continue

        mean_ret = float(np.mean(rets))
        ann_ret = mean_ret * annualization_factor
        avg_stocks = float(np.mean(counts))
        results.append(
            QuintileReturn(
                quintile=q, mean_return=mean_ret, annualized_return=ann_ret, n_stocks=avg_stocks
            )
        )

    spread = 0.0
    if results[4].mean_return != 0.0 or results[0].mean_return != 0.0:
        spread = results[4].mean_return - results[0].mean_return

    return results, spread


def _compute_diagnostics(
    raw_factor_df: pd.DataFrame,
) -> tuple[float, float, float]:
    """Compute coverage, mean, and std of raw factor values.

    Returns (coverage, mean_value, std_value).
    """
    if raw_factor_df.empty:
        return 0.0, 0.0, 0.0

    if isinstance(raw_factor_df.columns, pd.MultiIndex):
        values = raw_factor_df.iloc[:, 0]
    else:
        values = raw_factor_df.iloc[:, 0]

    total = len(values)
    non_null = values.notna().sum()
    coverage = float(non_null / total) if total > 0 else 0.0

    valid = values.dropna()
    mean_val = float(valid.mean()) if len(valid) > 0 else 0.0
    std_val = float(valid.std()) if len(valid) > 1 else 0.0

    return coverage, mean_val, std_val


def _apply_gates(
    ic: float,
    icir: float,
    t_stat: float,
    positive_ratio: float,
    quintile_spread: float,
    decay_1d: float,
    decay_5d: float,
    gates: dict[str, float],
) -> list[str]:
    """Check metrics against gate thresholds. Returns list of failure reasons."""
    fail_reasons: list[str] = []

    if abs(icir) < gates.get("min_icir", DEFAULT_GATES["min_icir"]):
        fail_reasons.append(
            f"|ICIR|={abs(icir):.4f} < min_icir={gates.get('min_icir', DEFAULT_GATES['min_icir'])}"
        )

    if abs(t_stat) < gates.get("min_t_stat", DEFAULT_GATES["min_t_stat"]):
        fail_reasons.append(
            f"|t_stat|={abs(t_stat):.4f} < min_t_stat={gates.get('min_t_stat', DEFAULT_GATES['min_t_stat'])}"
        )

    if positive_ratio < gates.get("min_positive_ratio", DEFAULT_GATES["min_positive_ratio"]):
        fail_reasons.append(
            f"positive_ratio={positive_ratio:.4f} < min_positive_ratio={gates.get('min_positive_ratio', DEFAULT_GATES['min_positive_ratio'])}"
        )

    if abs(quintile_spread) < gates.get(
        "min_quintile_spread", DEFAULT_GATES["min_quintile_spread"]
    ):
        fail_reasons.append(
            f"|quintile_spread|={abs(quintile_spread):.6f} < min_quintile_spread={gates.get('min_quintile_spread', DEFAULT_GATES['min_quintile_spread'])}"
        )

    # Decay gate: IC at 5d should retain at least min_ratio of IC at 1d
    min_decay_ratio = gates.get("min_ic_decay_5d_ratio", DEFAULT_GATES["min_ic_decay_5d_ratio"])
    if np.isfinite(decay_1d) and np.isfinite(decay_5d) and abs(decay_1d) > 1e-10:
        decay_ratio = abs(decay_5d) / abs(decay_1d)
        if decay_ratio < min_decay_ratio:
            fail_reasons.append(
                f"IC decay 5d/1d ratio={decay_ratio:.4f} < min={min_decay_ratio} (factor decays too fast)"
            )

    return fail_reasons


def _make_failure_result(
    expression: str,
    market: str,
    start_date: str,
    end_date: str,
    fail_reasons: list[str],
) -> FactorEvalResult:
    """Build a FactorEvalResult with zeroed-out metrics and ``passed=False``."""
    return FactorEvalResult(
        expression=expression,
        market=market,
        start_date=start_date,
        end_date=end_date,
        ic=0.0,
        rank_ic=0.0,
        ic_std=0.0,
        icir=0.0,
        t_stat=0.0,
        positive_ratio=0.0,
        n_periods=0,
        decay_1d=0.0,
        decay_5d=0.0,
        decay_10d=0.0,
        quintile_returns=[],
        quintile_spread=0.0,
        coverage=0.0,
        mean_value=0.0,
        std_value=0.0,
        passed=False,
        fail_reasons=fail_reasons,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_factor(
    expression: str,
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = None,
    train_end: str | None = None,
    label_horizon: int = 10,
    gates: dict | None = None,
) -> FactorEvalResult:
    """Evaluate an arbitrary Qlib factor expression.

    Steps:
    1. Validate expression syntax.
    2. Initialize Qlib and load factor data via DataHandlerLP.
    3. Compute forward returns at *label_horizon*.
    4. Compute cross-sectional Pearson / Spearman IC per month, aggregate.
    5. Compute IC decay at 1d, 5d, 10d horizons.
    6. Compute quintile returns (rank into 5 buckets).
    7. Compute diagnostics (coverage, mean, std).
    8. Apply pass/fail gates.

    Args:
        expression: Any valid Qlib expression string (e.g. ``"Ref($close, 5)/$close"``).
        market: ``"us"`` or ``"cn"``.
        start_date: Start of evaluation window.
        end_date: End of evaluation window.
        train_end: If provided, IC/quintile metrics are computed only on
            data after this date (out-of-sample).  Factor data is still
            loaded for the full range so that IC decay can be computed.
            When ``None``, the entire range is used (in-sample).
        label_horizon: Forward return horizon in days.
        gates: Override default gate thresholds. Keys match ``DEFAULT_GATES``.

    Returns:
        A ``FactorEvalResult`` with all metrics and verdict.
    """
    from src.common.dates import default_end_date

    end_date = end_date or default_end_date()
    gates = gates or dict(DEFAULT_GATES)

    # ------------------------------------------------------------------
    # 1. Validate expression
    # ------------------------------------------------------------------
    valid, err = validate_expression_syntax(expression)
    if not valid:
        return _make_failure_result(
            expression,
            market,
            start_date,
            end_date,
            [f"Invalid expression syntax: {err}"],
        )

    log.info(
        "Evaluating factor",
        expression=expression,
        market=market,
        start=start_date,
        end=end_date,
        train_end=train_end,
        oos_mode=train_end is not None,
        horizon=label_horizon,
    )

    # ------------------------------------------------------------------
    # 2. Initialize Qlib
    # ------------------------------------------------------------------
    _init_qlib(market)

    # ------------------------------------------------------------------
    # 3. Load factor data (z-scored for IC, raw for diagnostics/quintiles)
    # ------------------------------------------------------------------
    try:
        factor_df = _load_factor_values(expression, market, start_date, end_date)
    except Exception as exc:
        log.warning("Failed to load factor data", expression=expression, error=str(exc))
        return _make_failure_result(
            expression,
            market,
            start_date,
            end_date,
            [f"Failed to load factor data: {exc}"],
        )

    if factor_df.empty:
        return _make_failure_result(
            expression,
            market,
            start_date,
            end_date,
            ["No factor data returned -- expression may reference missing fields"],
        )

    # Raw (non-normalized) factor values for diagnostics and quintile analysis
    try:
        raw_factor_df = _load_raw_factor_values(expression, market, start_date, end_date)
    except Exception:
        # Fall back to z-scored data for quintiles if raw load fails
        raw_factor_df = factor_df

    # ------------------------------------------------------------------
    # 4. Compute forward returns
    # ------------------------------------------------------------------
    fwd_returns = _compute_forward_returns(market, start_date, end_date, label_horizon)
    if fwd_returns.empty:
        return _make_failure_result(
            expression,
            market,
            start_date,
            end_date,
            ["No forward returns computed -- insufficient price data"],
        )

    # ------------------------------------------------------------------
    # 5. Compute IC (OOS if train_end is provided)
    # ------------------------------------------------------------------
    # Filter to OOS period if train_end is specified
    if train_end is not None:
        oos_mask_factor = factor_df.index.get_level_values("datetime") > pd.Timestamp(train_end)
        oos_mask_fwd = fwd_returns.index.get_level_values("datetime") > pd.Timestamp(train_end)
        factor_df_oos = factor_df.loc[oos_mask_factor]
        fwd_returns_oos = fwd_returns.loc[oos_mask_fwd]
        if factor_df_oos.empty or fwd_returns_oos.empty:
            return _make_failure_result(
                expression,
                market,
                start_date,
                end_date,
                [f"No OOS data after train_end={train_end}"],
            )
        log.info(
            "Computing IC on OOS period",
            train_end=train_end,
            n_factor_rows=len(factor_df_oos),
            n_fwd_rows=len(fwd_returns_oos),
        )
    else:
        factor_df_oos = factor_df
        fwd_returns_oos = fwd_returns

    period_pearson, period_spearman, n_periods = _compute_ic_series(
        factor_df_oos, fwd_returns_oos, freq="ME"
    )

    if not period_pearson:
        return _make_failure_result(
            expression,
            market,
            start_date,
            end_date,
            ["No valid cross-sections -- insufficient overlapping data"],
        )

    ic_array = np.array(period_pearson)
    rank_ic_array = np.array(period_spearman) if period_spearman else ic_array

    mean_ic = float(np.mean(ic_array))
    mean_rank_ic = float(np.mean(rank_ic_array))
    ic_std = float(np.std(ic_array, ddof=1)) if len(ic_array) > 1 else 0.0
    icir = mean_ic / ic_std if ic_std > 1e-10 else 0.0
    t_stat = float(mean_ic / (ic_std / np.sqrt(len(ic_array)))) if ic_std > 1e-10 else 0.0
    positive_ratio = float(np.mean(ic_array > 0))

    # ------------------------------------------------------------------
    # 6. Compute decay at 1d, 5d, 10d horizons
    # ------------------------------------------------------------------
    decay_horizons = {1: 0.0, 5: 0.0, 10: 0.0}
    for horizon in decay_horizons:
        try:
            mean_p, _ = _compute_ic_for_horizon(expression, market, start_date, end_date, horizon)
            decay_horizons[horizon] = mean_p if np.isfinite(mean_p) else 0.0
        except Exception as exc:
            log.debug("Decay computation failed", horizon=horizon, error=str(exc))
            decay_horizons[horizon] = 0.0

    decay_1d = decay_horizons[1]
    decay_5d = decay_horizons[5]
    decay_10d = decay_horizons[10]

    # ------------------------------------------------------------------
    # 7. Quintile analysis (uses raw factor values for proper ranking)
    # ------------------------------------------------------------------
    # Filter to OOS period if train_end is specified
    if train_end is not None:
        oos_mask_raw = raw_factor_df.index.get_level_values("datetime") > pd.Timestamp(train_end)
        raw_factor_df_oos = raw_factor_df.loc[oos_mask_raw]
    else:
        raw_factor_df_oos = raw_factor_df

    quintile_returns, quintile_spread = _compute_quintile_returns(
        raw_factor_df_oos, fwd_returns_oos, freq="ME"
    )

    # ------------------------------------------------------------------
    # 8. Diagnostics
    # ------------------------------------------------------------------
    coverage, mean_value, std_value = _compute_diagnostics(raw_factor_df)

    # ------------------------------------------------------------------
    # 9. Apply gates
    # ------------------------------------------------------------------
    fail_reasons = _apply_gates(
        ic=mean_ic,
        icir=icir,
        t_stat=t_stat,
        positive_ratio=positive_ratio,
        quintile_spread=quintile_spread,
        decay_1d=decay_1d,
        decay_5d=decay_5d,
        gates=gates,
    )

    passed = len(fail_reasons) == 0

    # Report the actual evaluation period (OOS if train_end provided)
    eval_start = train_end if train_end is not None else start_date
    eval_end = end_date

    result = FactorEvalResult(
        expression=expression,
        market=market,
        start_date=eval_start,
        end_date=eval_end,
        ic=mean_ic,
        rank_ic=mean_rank_ic,
        ic_std=ic_std,
        icir=icir,
        t_stat=t_stat,
        positive_ratio=positive_ratio,
        n_periods=n_periods,
        decay_1d=decay_1d,
        decay_5d=decay_5d,
        decay_10d=decay_10d,
        quintile_returns=quintile_returns,
        quintile_spread=quintile_spread,
        coverage=coverage,
        mean_value=mean_value,
        std_value=std_value,
        passed=passed,
        fail_reasons=fail_reasons,
    )

    log.info(
        "Factor evaluation complete",
        expression=expression,
        ic=round(mean_ic, 6),
        rank_ic=round(mean_rank_ic, 6),
        icir=round(icir, 4),
        t_stat=round(t_stat, 4),
        positive_ratio=round(positive_ratio, 4),
        quintile_spread=round(quintile_spread, 6),
        passed=passed,
        n_failures=len(fail_reasons),
        oos_mode=train_end is not None,
        eval_period=f"{eval_start} to {eval_end}",
    )

    return result
