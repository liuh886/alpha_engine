"""Deterministic CN130 cross-sectional ranking and rotation helpers.

The module deliberately reads the bound Qlib binary provider directly.  This keeps
research execution independent from Qlib runtime installation while preserving the
provider's calendar, adjusted OHLCV values, and instrument lifecycle semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


BASELINE_FEATURES: tuple[str, ...] = (
    "volume_ratio_10",
    "volume_ratio_20",
    "volume_ratio_5",
    "momentum_10",
    "momentum_20",
    "momentum_3",
    "momentum_5",
    "reversal_1",
    "reversal_3",
    "reversal_5",
    "intraday_range",
    "volatility_10",
    "volatility_20",
    "volatility_5",
)

EXTENDED_FEATURES: tuple[str, ...] = BASELINE_FEATURES + (
    "momentum_63",
    "price_to_ma20",
    "price_to_ma60",
    "bollinger_z20",
    "rsi_20",
    "drawdown_63",
    "volume_z20",
    "amount_ratio_20",
    "beta_60",
    "residual_momentum_20",
)


@dataclass(frozen=True)
class ProviderPanel:
    """Calendar-aligned market fields loaded from a Qlib binary provider."""

    calendar: pd.DatetimeIndex
    fields: dict[str, pd.DataFrame]
    lifecycle: pd.DataFrame


@dataclass(frozen=True)
class RankingFit:
    """Fitted ranker plus exact feature order and grouping contract."""

    model: Any
    feature_names: tuple[str, ...]
    seed: int
    group_key_names: tuple[str, ...]


def read_qlib_feature(path: Path, calendar_size: int) -> np.ndarray:
    """Read one Qlib ``*.day.bin`` vector into the global calendar coordinate."""

    raw = np.fromfile(path, dtype="<f4")
    if raw.size < 2:
        raise ValueError(f"invalid Qlib feature file: {path}")
    start = int(round(float(raw[0])))
    values = raw[1:].astype(float)
    if start < 0 or start + len(values) > calendar_size:
        raise ValueError(
            f"feature range outside calendar: {path} start={start} values={len(values)}"
        )
    output = np.full(calendar_size, np.nan, dtype=float)
    output[start : start + len(values)] = values
    return output


def _load_lifecycle(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        symbol, start, end = line.split("\t")[:3]
        rows.append(
            {
                "instrument": symbol.strip(),
                "start": pd.Timestamp(start),
                "end": pd.Timestamp(end),
            }
        )
    frame = pd.DataFrame(rows).set_index("instrument").sort_index()
    if frame.empty:
        raise ValueError(f"instrument lifecycle file is empty: {path}")
    return frame


def load_provider_panel(
    provider_dir: Path,
    symbols: Sequence[str],
    *,
    fields: Sequence[str] = ("open", "high", "low", "close", "volume", "amount"),
) -> ProviderPanel:
    """Load selected symbols and fields from a deterministic Qlib provider."""

    provider_dir = provider_dir.resolve()
    calendar_path = provider_dir / "calendars" / "day.txt"
    lifecycle_path = provider_dir / "instruments" / "cn.txt"
    calendar = pd.DatetimeIndex(
        pd.to_datetime(calendar_path.read_text(encoding="utf-8").splitlines()),
        name="datetime",
    )
    lifecycle = _load_lifecycle(lifecycle_path)
    missing_lifecycle = sorted(set(symbols) - set(lifecycle.index))
    if missing_lifecycle:
        raise ValueError(f"provider lifecycle missing symbols: {missing_lifecycle}")

    loaded: dict[str, pd.DataFrame] = {}
    for field in fields:
        columns: dict[str, np.ndarray] = {}
        for symbol in symbols:
            path = provider_dir / "features" / symbol.lower() / f"{field}.day.bin"
            if not path.is_file():
                raise FileNotFoundError(path)
            columns[symbol] = read_qlib_feature(path, len(calendar))
        loaded[field] = pd.DataFrame(columns, index=calendar, dtype=float)
    return ProviderPanel(calendar=calendar, fields=loaded, lifecycle=lifecycle.loc[list(symbols)])


def _safe_divide(numerator: pd.DataFrame, denominator: pd.DataFrame) -> pd.DataFrame:
    output = numerator / denominator.replace(0.0, np.nan)
    return output.replace([np.inf, -np.inf], np.nan)


def _rsi(close: pd.DataFrame, window: int) -> pd.DataFrame:
    delta = close.diff()
    gains = delta.clip(lower=0.0).rolling(window, min_periods=window).mean()
    losses = (-delta.clip(upper=0.0)).rolling(window, min_periods=window).mean()
    relative_strength = _safe_divide(gains, losses)
    return 100.0 - 100.0 / (1.0 + relative_strength)


def rolling_beta(
    stock_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    *,
    window: int = 60,
    minimum_observations: int = 40,
) -> pd.DataFrame:
    """Compute trailing market beta without using future observations."""

    variance = benchmark_returns.rolling(window, min_periods=minimum_observations).var()
    output: dict[str, pd.Series] = {}
    for symbol in stock_returns.columns:
        covariance = (
            stock_returns[symbol]
            .rolling(window, min_periods=minimum_observations)
            .cov(benchmark_returns)
        )
        output[symbol] = covariance / variance.replace(0.0, np.nan)
    return pd.DataFrame(output, index=stock_returns.index).replace([np.inf, -np.inf], np.nan)


def build_feature_matrices(
    panel: ProviderPanel,
    *,
    symbols: Sequence[str],
    benchmark: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Build baseline and governed technical feature families plus risk metadata."""

    close = panel.fields["close"].loc[:, list(symbols)]
    high = panel.fields["high"].loc[:, list(symbols)]
    low = panel.fields["low"].loc[:, list(symbols)]
    volume = panel.fields["volume"].loc[:, list(symbols)]
    amount = panel.fields["amount"].loc[:, list(symbols)]
    benchmark_close = panel.fields["close"][benchmark]

    daily_return = close.pct_change(fill_method=None)
    benchmark_return = benchmark_close.pct_change(fill_method=None)
    beta_60 = rolling_beta(daily_return, benchmark_return)

    feature_wide: dict[str, pd.DataFrame] = {
        "volume_ratio_10": _safe_divide(volume, volume.rolling(10).mean()) - 1.0,
        "volume_ratio_20": _safe_divide(volume, volume.rolling(20).mean()) - 1.0,
        "volume_ratio_5": _safe_divide(volume, volume.rolling(5).mean()) - 1.0,
        "momentum_10": _safe_divide(close, close.shift(10)) - 1.0,
        "momentum_20": _safe_divide(close, close.shift(20)) - 1.0,
        "momentum_3": _safe_divide(close, close.shift(3)) - 1.0,
        "momentum_5": _safe_divide(close, close.shift(5)) - 1.0,
        "reversal_1": _safe_divide(close.shift(1), close) - 1.0,
        "reversal_3": _safe_divide(close.shift(3), close) - 1.0,
        "reversal_5": _safe_divide(close.shift(5), close) - 1.0,
        "intraday_range": _safe_divide(high - low, close + 1e-12),
        "volatility_10": daily_return.rolling(10).std(),
        "volatility_20": daily_return.rolling(20).std(),
        "volatility_5": daily_return.rolling(5).std(),
        "momentum_63": _safe_divide(close, close.shift(63)) - 1.0,
        "price_to_ma20": _safe_divide(close, close.rolling(20).mean()) - 1.0,
        "price_to_ma60": _safe_divide(close, close.rolling(60).mean()) - 1.0,
        "bollinger_z20": _safe_divide(close - close.rolling(20).mean(), close.rolling(20).std()),
        "rsi_20": _rsi(close, 20) / 100.0,
        "drawdown_63": _safe_divide(close, close.rolling(63).max()) - 1.0,
        "volume_z20": _safe_divide(volume - volume.rolling(20).mean(), volume.rolling(20).std()),
        "amount_ratio_20": _safe_divide(amount, amount.rolling(20).mean()) - 1.0,
        "beta_60": beta_60,
    }
    benchmark_momentum_20 = benchmark_close / benchmark_close.shift(20) - 1.0
    feature_wide["residual_momentum_20"] = feature_wide["momentum_20"].sub(
        beta_60.mul(benchmark_momentum_20, axis=0)
    )

    def stack(names: Iterable[str]) -> pd.DataFrame:
        columns: list[pd.Series] = []
        for name in names:
            series = feature_wide[name].stack(future_stack=True)
            series.index = series.index.set_names(["datetime", "instrument"])
            series.name = name
            columns.append(series)
        return pd.concat(columns, axis=1).sort_index()

    families = {
        "current_cn_ohlcv": stack(BASELINE_FEATURES),
        "momentum_reversal": stack(
            (
                "momentum_3",
                "momentum_5",
                "momentum_10",
                "momentum_20",
                "reversal_1",
                "reversal_3",
                "reversal_5",
            )
        ),
        "volume_volatility": stack(
            (
                "volume_ratio_5",
                "volume_ratio_10",
                "volume_ratio_20",
                "intraday_range",
                "volatility_5",
                "volatility_10",
                "volatility_20",
            )
        ),
        "governed_technical_extension": stack(EXTENDED_FEATURES),
    }

    metadata = {
        "beta_60": stack(("beta_60",)),
        "realized_volatility_20": stack(("volatility_20",)).rename(
            columns={"volatility_20": "realized_volatility_20"}
        ),
        "trailing_amount_20": amount.rolling(20)
        .median()
        .stack(future_stack=True)
        .rename("trailing_amount_20")
        .to_frame(),
        "momentum_20": stack(("momentum_20",)),
        "price_to_ma50": (_safe_divide(close, close.rolling(50).mean()) - 1.0)
        .stack(future_stack=True)
        .rename("price_to_ma50")
        .to_frame(),
    }
    for frame in metadata.values():
        frame.index = frame.index.set_names(["datetime", "instrument"])
    return families, metadata


def forward_returns(close: pd.DataFrame, *, horizon: int, delay: int = 0) -> pd.DataFrame:
    """Return close-to-close forward returns with an optional execution delay."""

    entry = close.shift(-delay)
    exit_price = close.shift(-(delay + horizon))
    return _safe_divide(exit_price, entry) - 1.0


def stack_return_frame(frame: pd.DataFrame, name: str = "forward_return") -> pd.DataFrame:
    series = frame.stack(future_stack=True)
    series.index = series.index.set_names(["datetime", "instrument"])
    return series.rename(name).to_frame().sort_index()


def attach_classification(
    index: pd.MultiIndex,
    classification: Mapping[str, Mapping[str, str]],
) -> pd.DataFrame:
    instruments = index.get_level_values("instrument")
    rows = [classification[str(symbol)] for symbol in instruments]
    return pd.DataFrame(rows, index=index)[["entity", "sector", "industry"]]


def make_label(
    raw_returns: pd.DataFrame,
    *,
    mode: str,
    benchmark_returns: pd.Series,
    classification: Mapping[str, Mapping[str, str]],
    risk_controls: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construct one preregistered ranking label without altering pool membership."""

    if raw_returns.shape[1] != 1:
        raise ValueError("raw_returns must have one column")
    values = raw_returns.iloc[:, 0].astype(float).rename("raw_forward_return")
    dates = values.index.get_level_values("datetime")
    benchmark_aligned = pd.Series(
        benchmark_returns.reindex(dates).to_numpy(), index=values.index, dtype=float
    )
    if mode == "raw":
        target = values
    elif mode == "benchmark_relative":
        target = values - benchmark_aligned
    elif mode == "sector_relative":
        meta = attach_classification(values.index, classification)
        temp = pd.DataFrame({"value": values, "sector": meta["sector"]}, index=values.index)
        medians = temp.groupby([temp.index.get_level_values("datetime"), "sector"], sort=False)[
            "value"
        ].transform("median")
        target = values - medians.to_numpy()
    elif mode == "risk_residual_partial":
        if risk_controls is None:
            raise ValueError("risk_controls required for risk residual label")
        target = _cross_sectional_risk_residual(
            values,
            classification=classification,
            risk_controls=risk_controls,
        )
    else:
        raise ValueError(f"unsupported label mode: {mode}")
    return target.rename("target_return").to_frame()


def _cross_sectional_risk_residual(
    values: pd.Series,
    *,
    classification: Mapping[str, Mapping[str, str]],
    risk_controls: pd.DataFrame,
) -> pd.Series:
    """Residualize returns on sector, beta, volatility, and liquidity proxy.

    The bound provider has no point-in-time shares or market capitalization.
    Therefore this is an explicitly ineligible partial diagnostic, not R3 proper.
    """

    aligned = values.rename("return").to_frame().join(risk_controls, how="left")
    meta = attach_classification(aligned.index, classification)
    aligned = aligned.join(meta[["sector"]])
    residual = pd.Series(np.nan, index=aligned.index, dtype=float, name="target_return")
    numeric = ["beta_60", "realized_volatility_20", "log_trailing_amount_20"]
    for _, group in aligned.groupby(level="datetime", sort=True):
        valid = group[["return", *numeric, "sector"]].dropna()
        if len(valid) < 30:
            continue
        sector_dummies = pd.get_dummies(valid["sector"], drop_first=True, dtype=float)
        x_numeric = valid[numeric].astype(float)
        x_numeric = (x_numeric - x_numeric.mean()) / x_numeric.std(ddof=0).replace(0.0, 1.0)
        design = np.column_stack(
            [np.ones(len(valid)), x_numeric.to_numpy(), sector_dummies.to_numpy()]
        )
        y = valid["return"].to_numpy(dtype=float)
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual.loc[valid.index] = y - design @ coefficients
    return residual


def _finite_aligned(
    features: pd.DataFrame,
    target: pd.DataFrame,
    *,
    minimum_group_size: int,
    group_keys: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    common = features.index.intersection(target.index).intersection(group_keys.index)
    x = features.loc[common].replace([np.inf, -np.inf], np.nan)
    y = target.loc[common].iloc[:, 0].replace([np.inf, -np.inf], np.nan)
    keys = group_keys.loc[common]
    valid = x.notna().all(axis=1) & y.notna() & keys.notna().all(axis=1)
    x, y, keys = x.loc[valid], y.loc[valid], keys.loc[valid]
    sizes = keys.groupby([keys[column] for column in keys.columns], sort=True).size()
    valid_groups = sizes[sizes >= minimum_group_size].index
    if len(keys.columns) == 1:
        mask = keys.iloc[:, 0].isin(valid_groups)
    else:
        key_index = pd.MultiIndex.from_frame(keys)
        mask = key_index.isin(valid_groups)
    x, y, keys = x.loc[mask], y.loc[mask], keys.loc[mask]
    sort_frame = keys.copy()
    sort_columns = [f"__group_{index}" for index in range(len(keys.columns))]
    sort_frame.columns = sort_columns
    sort_frame["__instrument"] = x.index.get_level_values("instrument").astype(str)
    ordering = sort_frame.sort_values([*sort_columns, "__instrument"], kind="mergesort").index
    return x.loc[ordering], y.loc[ordering], keys.loc[ordering]


def fit_ranker(
    features: pd.DataFrame,
    target: pd.DataFrame,
    *,
    group_keys: pd.DataFrame,
    seed: int = 42,
    num_boost_round: int = 100,
) -> RankingFit:
    """Fit the frozen XGBoost rank:ndcg baseline on explicit query groups."""

    import xgboost as xgb

    x, y, keys = _finite_aligned(
        features,
        target,
        minimum_group_size=2,
        group_keys=group_keys,
    )
    if x.empty:
        raise ValueError("no finite ranker rows")
    percentiles = y.groupby([keys[column] for column in keys.columns], sort=False).rank(
        method="average", pct=True
    )
    gains = np.floor(percentiles.clip(0.0, 1.0) * 5).clip(0, 4).astype(int)
    sizes = keys.groupby([keys[column] for column in keys.columns], sort=True).size().tolist()
    matrix = xgb.DMatrix(x, label=gains.to_numpy())
    matrix.set_group(sizes)
    model = xgb.train(
        {
            "objective": "rank:ndcg",
            "tree_method": "hist",
            "grow_policy": "lossguide",
            "max_leaves": 31,
            "max_depth": 0,
            "learning_rate": 0.05,
            "seed": seed,
            "nthread": 5,
            "verbosity": 0,
        },
        matrix,
        num_boost_round=num_boost_round,
    )
    return RankingFit(
        model=model,
        feature_names=tuple(str(column) for column in x.columns),
        seed=seed,
        group_key_names=tuple(str(column) for column in keys.columns),
    )


def predict_ranker(fit: RankingFit, features: pd.DataFrame) -> pd.DataFrame:
    import xgboost as xgb

    x = features.loc[:, list(fit.feature_names)].replace([np.inf, -np.inf], np.nan)
    valid = x.notna().all(axis=1)
    output = pd.Series(np.nan, index=x.index, dtype=float, name="score")
    if valid.any():
        output.loc[valid] = fit.model.predict(xgb.DMatrix(x.loc[valid]))
    return output.to_frame()


def rank_metrics(
    scores: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    classification: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, float | int], pd.DataFrame]:
    """Calculate daily rank evidence and top-minus-bottom economic spread."""

    joined = scores.rename(columns={scores.columns[0]: "score"}).join(
        raw_returns.rename(columns={raw_returns.columns[0]: "forward_return"}),
        how="inner",
    )
    joined = joined.replace([np.inf, -np.inf], np.nan).dropna()
    meta = attach_classification(joined.index, classification)
    joined = joined.join(meta[["sector", "industry"]])
    daily_rows: list[dict[str, Any]] = []
    for date, group in joined.groupby(level="datetime", sort=True):
        if len(group) < 20:
            continue
        rank_ic = group["score"].corr(group["forward_return"], method="spearman")
        ic = group["score"].corr(group["forward_return"], method="pearson")
        ordered = group.sort_values(["score"], ascending=False, kind="mergesort")
        bucket = max(1, len(ordered) // 5)
        top_return = float(ordered.head(bucket)["forward_return"].mean())
        bottom_return = float(ordered.tail(bucket)["forward_return"].mean())
        daily_rows.append(
            {
                "datetime": pd.Timestamp(date),
                "n": int(len(group)),
                "ic": float(ic) if pd.notna(ic) else np.nan,
                "rank_ic": float(rank_ic) if pd.notna(rank_ic) else np.nan,
                "top_return": top_return,
                "bottom_return": bottom_return,
                "top_bottom_spread": top_return - bottom_return,
            }
        )
    daily = pd.DataFrame(daily_rows)
    rank_values = daily["rank_ic"].dropna()
    spread_values = daily["top_bottom_spread"].dropna()
    rank_mean = float(rank_values.mean()) if not rank_values.empty else 0.0
    rank_std = float(rank_values.std(ddof=1)) if len(rank_values) > 1 else 0.0
    metrics: dict[str, float | int] = {
        "n_dates": int(len(daily)),
        "mean_ic": float(daily["ic"].mean()) if not daily.empty else 0.0,
        "mean_rank_ic": rank_mean,
        "rank_icir": rank_mean / rank_std if rank_std > 0.0 else 0.0,
        "positive_rank_ic_ratio": float((rank_values > 0.0).mean())
        if not rank_values.empty
        else 0.0,
        "mean_top_bottom_spread": float(spread_values.mean()) if not spread_values.empty else 0.0,
        "positive_spread_ratio": float((spread_values > 0.0).mean())
        if not spread_values.empty
        else 0.0,
    }
    return metrics, daily


def transform_hierarchical_scores(
    sector_scores: pd.DataFrame,
    security_scores: pd.DataFrame,
    *,
    classification: Mapping[str, Mapping[str, str]],
    sector_weight: float = 0.35,
) -> pd.DataFrame:
    """Combine sector and within-sector percentiles using frozen 35/65 weights."""

    security = security_scores.rename(columns={security_scores.columns[0]: "security_score"})
    meta = attach_classification(security.index, classification)
    security = security.join(meta[["sector"]])
    output = pd.Series(np.nan, index=security.index, dtype=float, name="score")
    sector_lookup = sector_scores.rename(columns={sector_scores.columns[0]: "sector_score"})
    for date, group in security.groupby(level="datetime", sort=True):
        sector_day = sector_lookup.xs(date, level="datetime").copy()
        sector_pct = sector_day["sector_score"].rank(method="average", pct=True)
        day = group.copy()
        within = day.groupby("sector")["security_score"].rank(method="average", pct=True)
        sector_component = day["sector"].map(sector_pct)
        output.loc[day.index] = sector_weight * sector_component.to_numpy(dtype=float) + (
            1.0 - sector_weight
        ) * within.to_numpy(dtype=float)
    return output.to_frame()


def score_stability(
    scores: pd.DataFrame,
    *,
    top_k: int = 15,
    rebalance_every: int = 10,
) -> dict[str, float | int]:
    """Measure adjacent-date rank persistence and rebalance Top-K overlap."""

    wide = scores.iloc[:, 0].unstack("instrument").sort_index()
    adjacent: list[float] = []
    for previous, current in zip(wide.index[:-1], wide.index[1:]):
        pair = pd.concat([wide.loc[previous], wide.loc[current]], axis=1).dropna()
        if len(pair) >= 20:
            value = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
            if pd.notna(value):
                adjacent.append(float(value))
    dates = list(wide.index[::rebalance_every])
    overlaps: list[float] = []
    prior: set[str] | None = None
    for date in dates:
        current = set(wide.loc[date].dropna().nlargest(top_k).index.astype(str))
        if prior is not None and len(current) == top_k and len(prior) == top_k:
            overlaps.append(len(current & prior) / top_k)
        prior = current
    return {
        "adjacent_rank_correlation": float(np.mean(adjacent)) if adjacent else 0.0,
        "rebalance_topk_overlap": float(np.mean(overlaps)) if overlaps else 0.0,
        "n_adjacent_pairs": len(adjacent),
        "n_rebalance_transitions": len(overlaps),
    }


def max_drawdown(period_returns: Sequence[float]) -> float:
    wealth = np.cumprod(1.0 + np.asarray(period_returns, dtype=float))
    if wealth.size == 0:
        return 0.0
    peak = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peak - 1.0))


def compound(period_returns: Sequence[float]) -> float:
    return float(np.prod(1.0 + np.asarray(period_returns, dtype=float)) - 1.0)


def bootstrap_mean_rank_ic(
    daily_metrics: pd.DataFrame,
    *,
    seed: int = 42,
    block_size: int = 10,
    repetitions: int = 500,
) -> dict[str, float | int]:
    values = daily_metrics["rank_ic"].dropna().to_numpy(dtype=float)
    if values.size == 0:
        return {"repetitions": repetitions, "mean": 0.0, "p05": 0.0, "p95": 0.0}
    rng = np.random.default_rng(seed)
    means: list[float] = []
    n_blocks = int(np.ceil(len(values) / block_size))
    starts = np.arange(max(1, len(values) - block_size + 1))
    for _ in range(repetitions):
        sampled: list[float] = []
        for start in rng.choice(starts, size=n_blocks, replace=True):
            sampled.extend(values[start : start + block_size])
        means.append(float(np.mean(sampled[: len(values)])))
    return {
        "repetitions": repetitions,
        "mean": float(np.mean(means)),
        "p05": float(np.quantile(means, 0.05)),
        "p95": float(np.quantile(means, 0.95)),
    }
