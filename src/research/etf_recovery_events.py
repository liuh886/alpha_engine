"""Multi-stage recovery-event diagnostics for QQQ versus QQQI.

A single MA200 reclaim is a late and sparse definition of recovery. This module
separates recovery into earlier and later confirmation stages after a material
QQQ drawdown, while preserving the close-signal / next-open execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RecoveryStudyConfig:
    """Frozen diagnostic contract for one recovery-event study."""

    shock_threshold: float = 0.10
    shock_memory_sessions: int = 63
    ma_medium: int = 50
    breakout_windows: tuple[int, ...] = (5, 20)
    horizons: tuple[int, ...] = (5, 10, 20, 40)
    target_returns: tuple[float, ...] = (0.05, 0.10)

    def __post_init__(self) -> None:
        if not 0.0 < self.shock_threshold < 1.0:
            raise ValueError("shock_threshold must be in (0, 1)")
        if self.shock_memory_sessions <= 0:
            raise ValueError("shock_memory_sessions must be positive")
        if self.ma_medium <= 0:
            raise ValueError("ma_medium must be positive")
        if not self.breakout_windows or any(value <= 1 for value in self.breakout_windows):
            raise ValueError("breakout_windows must contain integers greater than one")
        if not self.horizons or any(value <= 0 for value in self.horizons):
            raise ValueError("horizons must contain positive integers")
        if tuple(sorted(set(self.horizons))) != self.horizons:
            raise ValueError("horizons must be unique and ascending")
        if not self.target_returns or any(value <= 0 for value in self.target_returns):
            raise ValueError("target_returns must contain positive values")


def recovery_config_from_mapping(payload: Mapping[str, Any]) -> RecoveryStudyConfig:
    """Build a typed config from the YAML-compatible recovery-study mapping."""

    return RecoveryStudyConfig(
        shock_threshold=float(payload.get("shock_threshold", 0.10)),
        shock_memory_sessions=int(payload.get("shock_memory_sessions", 63)),
        ma_medium=int(payload.get("ma_medium", 50)),
        breakout_windows=tuple(int(value) for value in payload.get("breakout_windows", [5, 20])),
        horizons=tuple(int(value) for value in payload.get("horizons", [5, 10, 20, 40])),
        target_returns=tuple(float(value) for value in payload.get("target_returns", [0.05, 0.10])),
    )


def _cross_above(close: pd.Series, reference: pd.Series) -> pd.Series:
    return close.gt(reference) & close.shift(1).le(reference.shift(1))


def build_recovery_event_frame(
    prepared: pd.DataFrame,
    config: RecoveryStudyConfig,
) -> pd.DataFrame:
    """Build shock episodes and one first trigger per stage and episode.

    A shock episode starts when QQQ's 252-session drawdown reaches the declared
    threshold. It remains active until ``shock_memory_sessions`` have passed
    without another threshold breach. Each trigger family contributes at most
    one event per episode, which avoids counting repeated whipsaws as independent
    recoveries.
    """

    required = {
        "qqq_close",
        "drawdown",
        "ma_short",
        "ma_long",
        "QQQI_next_open_return",
        "QQQ_next_open_return",
    }
    missing = sorted(required - set(prepared.columns))
    if missing:
        raise ValueError(f"prepared frame missing recovery columns: {missing}")
    frame = prepared.copy()
    close = pd.to_numeric(frame["qqq_close"], errors="coerce")
    drawdown = pd.to_numeric(frame["drawdown"], errors="coerce")

    frame["ma_medium_recovery"] = close.rolling(
        config.ma_medium, min_periods=config.ma_medium
    ).mean()
    for window in config.breakout_windows:
        frame[f"prior_high_{window}"] = (
            close.rolling(window, min_periods=window).max().shift(1)
        )

    shock_hit = drawdown.le(-config.shock_threshold).fillna(False)
    shock_active = (
        shock_hit.astype(int)
        .rolling(config.shock_memory_sessions, min_periods=1)
        .max()
        .gt(0)
    )
    episode_start = shock_active & ~shock_active.shift(1, fill_value=False)
    episode_number = episode_start.cumsum().astype("Int64")
    frame["shock_active"] = shock_active
    frame["shock_episode"] = episode_number.where(shock_active)

    events: dict[str, pd.Series] = {
        "ma20_reclaim": _cross_above(close, frame["ma_short"]),
        "ma50_reclaim": _cross_above(close, frame["ma_medium_recovery"]),
        "ma200_reclaim": _cross_above(close, frame["ma_long"]),
    }
    for window in config.breakout_windows:
        events[f"breakout_{window}d"] = _cross_above(close, frame[f"prior_high_{window}"])

    ordered_families = []
    if 5 in config.breakout_windows:
        ordered_families.append("breakout_5d")
    ordered_families.extend(["ma20_reclaim", "ma50_reclaim"])
    if 20 in config.breakout_windows:
        ordered_families.append("breakout_20d")
    ordered_families.append("ma200_reclaim")
    ordered_families.extend(
        family for family in events if family not in set(ordered_families)
    )

    rows: list[dict[str, Any]] = []
    max_horizon = max(config.horizons)
    active_episode_ids = [int(value) for value in frame["shock_episode"].dropna().unique()]
    for episode_id in active_episode_ids:
        episode_mask = frame["shock_episode"].eq(episode_id)
        episode_dates = frame.index[episode_mask]
        if episode_dates.empty:
            continue
        shock_start = episode_dates[0]
        shock_start_position = frame.index.get_loc(shock_start)
        for stage_order, family in enumerate(ordered_families):
            family_mask = events[family].fillna(False) & episode_mask
            matching_dates = frame.index[family_mask]
            if matching_dates.empty:
                continue
            event_date = matching_dates[0]
            event_position = frame.index.get_loc(event_date)
            window = frame.iloc[event_position + 1 : event_position + 1 + max_horizon]
            if window.empty:
                continue
            row: dict[str, Any] = {
                "shock_episode": episode_id,
                "shock_start_date": shock_start,
                "event_family": family,
                "stage_order": stage_order,
                "event_date": event_date,
                "entry_date": window.index[0],
                "sessions_from_shock_start": int(event_position - shock_start_position),
                "qqq_drawdown_at_event": float(drawdown.loc[event_date]),
            }
            for symbol in ("QQQI", "QQQ"):
                returns = pd.to_numeric(
                    window[f"{symbol}_next_open_return"], errors="coerce"
                ).dropna()
                path = (1.0 + returns).cumprod() - 1.0
                for horizon in config.horizons:
                    row[f"{symbol}_return_{horizon}d"] = (
                        float(path.iloc[horizon - 1]) if len(path) >= horizon else np.nan
                    )
                row[f"{symbol}_peak_return_{max_horizon}d"] = (
                    float(path.max()) if not path.empty else np.nan
                )
                row[f"{symbol}_max_adverse_{max_horizon}d"] = (
                    float(path.min()) if not path.empty else np.nan
                )
                for target in config.target_returns:
                    target_bps = int(round(target * 10_000))
                    hits = np.flatnonzero(path.to_numpy(dtype=float) >= target)
                    row[f"{symbol}_days_to_{target_bps}bps"] = (
                        int(hits[0] + 1) if len(hits) else np.nan
                    )
            for horizon in config.horizons:
                row[f"QQQ_minus_QQQI_{horizon}d"] = (
                    row[f"QQQ_return_{horizon}d"] - row[f"QQQI_return_{horizon}d"]
                )
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["shock_episode", "stage_order", "event_date"]
    ).reset_index(drop=True)


def summarize_recovery_returns(
    events: pd.DataFrame,
    config: RecoveryStudyConfig,
) -> pd.DataFrame:
    """Summarise forward-return advantage by trigger family and horizon."""

    if events.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for family, family_events in events.groupby("event_family", sort=False):
        for horizon in config.horizons:
            qqq_col = f"QQQ_return_{horizon}d"
            qqqi_col = f"QQQI_return_{horizon}d"
            diff_col = f"QQQ_minus_QQQI_{horizon}d"
            sample = family_events[[qqq_col, qqqi_col, diff_col]].dropna()
            rows.append(
                {
                    "event_family": family,
                    "horizon_sessions": horizon,
                    "events": int(len(sample)),
                    "median_sessions_from_shock_start": float(
                        family_events["sessions_from_shock_start"].median()
                    ),
                    "QQQ_mean_return": float(sample[qqq_col].mean()) if len(sample) else np.nan,
                    "QQQI_mean_return": float(sample[qqqi_col].mean()) if len(sample) else np.nan,
                    "QQQ_minus_QQQI_mean": float(sample[diff_col].mean()) if len(sample) else np.nan,
                    "QQQ_minus_QQQI_median": float(sample[diff_col].median()) if len(sample) else np.nan,
                    "QQQ_win_rate": float(sample[diff_col].gt(0).mean()) if len(sample) else np.nan,
                }
            )
    return pd.DataFrame(rows).set_index(["event_family", "horizon_sessions"])


def summarize_recovery_speed(
    events: pd.DataFrame,
    config: RecoveryStudyConfig,
) -> pd.DataFrame:
    """Summarise time-to-target and post-entry downside by trigger family."""

    if events.empty:
        return pd.DataFrame()
    max_horizon = max(config.horizons)
    rows: list[dict[str, Any]] = []
    for family, family_events in events.groupby("event_family", sort=False):
        for target in config.target_returns:
            target_bps = int(round(target * 10_000))
            qqq_days = pd.to_numeric(
                family_events[f"QQQ_days_to_{target_bps}bps"], errors="coerce"
            )
            qqqi_days = pd.to_numeric(
                family_events[f"QQQI_days_to_{target_bps}bps"], errors="coerce"
            )
            comparable = pd.DataFrame({"QQQ": qqq_days, "QQQI": qqqi_days}).dropna()
            rows.append(
                {
                    "event_family": family,
                    "target_return": target,
                    "events": int(len(family_events)),
                    "QQQ_hit_rate": float(qqq_days.notna().mean()),
                    "QQQI_hit_rate": float(qqqi_days.notna().mean()),
                    "QQQ_median_days": float(qqq_days.median()) if qqq_days.notna().any() else np.nan,
                    "QQQI_median_days": float(qqqi_days.median()) if qqqi_days.notna().any() else np.nan,
                    "QQQ_faster_rate_when_both_hit": (
                        float(comparable["QQQ"].lt(comparable["QQQI"]).mean())
                        if len(comparable)
                        else np.nan
                    ),
                    f"QQQ_median_max_adverse_{max_horizon}d": float(
                        family_events[f"QQQ_max_adverse_{max_horizon}d"].median()
                    ),
                    f"QQQI_median_max_adverse_{max_horizon}d": float(
                        family_events[f"QQQI_max_adverse_{max_horizon}d"].median()
                    ),
                }
            )
    return pd.DataFrame(rows).set_index(["event_family", "target_return"])
