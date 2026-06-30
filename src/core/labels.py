"""Winner-bucket label generation."""

from __future__ import annotations

import math

import pandas as pd

EXCESS_RETURN_COL = "future_10d_excess_return"
RANK_COL = "rank_pct"


def _label_col_name(top_pct: float) -> str:
    return f"label_top{int(top_pct * 100)}pct"


def _validate_top_pct(top_pct: tuple[float, ...]) -> None:
    if not top_pct:
        raise ValueError("top_pct must contain at least one threshold")
    invalid = [threshold for threshold in top_pct if threshold <= 0 or threshold > 1]
    if invalid:
        raise ValueError(f"top_pct thresholds must be in (0, 1], got {invalid}")


def compute_excess_return(
    stock_returns: pd.DataFrame,
    bench_returns: pd.Series,
) -> pd.DataFrame:
    common_dates = stock_returns.index.intersection(bench_returns.index)
    stocks = stock_returns.loc[common_dates].rename_axis(index="date", columns="ticker")
    bench = bench_returns.loc[common_dates].rename("bench_return").rename_axis("date")

    long = stocks.reset_index().melt(
        id_vars=["date"],
        var_name="ticker",
        value_name="stock_return",
    )
    long = long.merge(bench.reset_index(), on="date", how="left")
    long[EXCESS_RETURN_COL] = long["stock_return"] - long["bench_return"]
    return long


def add_cross_sectional_rank(
    df: pd.DataFrame,
    excess_col: str = EXCESS_RETURN_COL,
) -> pd.DataFrame:
    df = df.copy()
    df[RANK_COL] = df.groupby("date")[excess_col].rank(pct=True, ascending=True)
    return df


def add_bucket_labels(
    df: pd.DataFrame,
    top_pct: tuple[float, ...] = (0.20, 0.10, 0.05),
    excess_col: str = EXCESS_RETURN_COL,
) -> pd.DataFrame:
    _validate_top_pct(top_pct)
    if "date" not in df.columns or "ticker" not in df.columns:
        raise ValueError("df must contain 'date' and 'ticker' columns")
    if excess_col not in df.columns:
        raise ValueError(f"df must contain '{excess_col}' column")

    labeled = df.copy()
    labeled["__row_id"] = range(len(labeled))

    for threshold in top_pct:
        labeled[_label_col_name(threshold)] = 0

    for _, group in labeled.groupby("date", sort=False):
        valid = group[group[excess_col].notna()].copy()
        if valid.empty:
            continue

        valid["__ticker_sort"] = valid["ticker"].astype(str)
        sorted_valid = valid.sort_values(
            by=[excess_col, "__ticker_sort"],
            ascending=[False, True],
            kind="mergesort",
        )

        valid_count = len(sorted_valid)
        for threshold in top_pct:
            top_n = math.ceil(valid_count * threshold)
            selected_row_ids = set(sorted_valid.head(top_n)["__row_id"])
            selected = labeled["__row_id"].isin(selected_row_ids)
            labeled.loc[selected, _label_col_name(threshold)] = 1

    return labeled.drop(columns="__row_id")


def build_excess_return_labels(
    stock_returns: pd.DataFrame,
    bench_returns: pd.Series,
    top_pct: tuple[float, ...] = (0.20, 0.10, 0.05),
) -> pd.DataFrame:
    df = compute_excess_return(stock_returns, bench_returns)
    df = add_cross_sectional_rank(df)
    df = add_bucket_labels(df, top_pct=top_pct)
    return df
