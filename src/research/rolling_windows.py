"""Rolling train/test window helpers for fixed-ten-day research."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RollingResearchWindow:
    """One rolling research window with separate train and OOS test dates."""

    label: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
        }


def purge_training_tail(
    features_train: pd.DataFrame,
    returns_train: pd.DataFrame,
    *,
    holding_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove labels whose forward horizon would cross into the OOS window."""

    common_dates = sorted(
        set(features_train.index.get_level_values("datetime"))
        & set(returns_train.index.get_level_values("datetime"))
    )
    if len(common_dates) <= holding_days:
        raise ValueError("not enough training dates for holding-period embargo")
    purge_dates = set(common_dates[-holding_days:])
    keep_features = ~features_train.index.get_level_values("datetime").isin(purge_dates)
    keep_returns = ~returns_train.index.get_level_values("datetime").isin(purge_dates)
    purged_features = features_train.loc[keep_features].copy()
    purged_returns = returns_train.loc[keep_returns].copy()
    purged_returns.attrs.update(returns_train.attrs)
    return purged_features, purged_returns


def half_year_rolling_windows(
    *,
    start_year: int = 2021,
    first_test_year: int = 2024,
    last_test_year: int = 2026,
) -> list[RollingResearchWindow]:
    """Build simple half-year OOS windows with expanding training history."""

    if first_test_year <= start_year:
        raise ValueError("first_test_year must be > start_year")
    if last_test_year < first_test_year:
        raise ValueError("last_test_year must be >= first_test_year")

    windows: list[RollingResearchWindow] = []
    for year in range(first_test_year, last_test_year + 1):
        halves = [
            (f"{year}H1", f"{year}-01-01", f"{year}-06-30"),
            (f"{year}H2", f"{year}-07-01", f"{year}-12-31"),
        ]
        for label, test_start, test_end in halves:
            train_end = (pd.Timestamp(test_start) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            windows.append(
                RollingResearchWindow(
                    label=label,
                    train_start=f"{start_year}-01-01",
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
    return windows


def filter_windows_by_available_range(
    windows: list[RollingResearchWindow],
    *,
    available_start: str,
    available_end: str,
) -> list[RollingResearchWindow]:
    """Keep only windows fully covered by the available data range."""

    start = pd.Timestamp(available_start)
    end = pd.Timestamp(available_end)
    kept = []
    for window in windows:
        if pd.Timestamp(window.train_start) >= start and pd.Timestamp(window.test_end) <= end:
            kept.append(window)
    return kept
