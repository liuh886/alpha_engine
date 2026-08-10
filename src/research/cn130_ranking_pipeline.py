"""Shared deterministic contracts for the CN130 ranking batch pipeline."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.cn130_cross_sectional_ranking import (
    attach_classification,
    fit_ranker,
    predict_ranker,
    transform_hierarchical_scores,
)

EXPERIMENT_ID = "cn130_cross_sectional_ranking_rotation_v1"
BENCHMARK = "000300"
SELECTION_WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("2024H1", "2024-01-01", "2024-06-30"),
    ("2024H2", "2024-07-01", "2024-12-31"),
    ("2025H1", "2025-01-01", "2025-06-30"),
    ("2025H2", "2025-07-01", "2025-12-31"),
)
FEATURE_FAMILIES: tuple[str, ...] = (
    "current_cn_ohlcv",
    "momentum_reversal",
    "volume_volatility",
    "governed_technical_extension",
)


@dataclass(frozen=True)
class WindowSpec:
    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    selection_eligible: bool


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def canonical_hash(payload: Any) -> str:
    import hashlib

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def risk_controls(metadata: dict[str, pd.DataFrame]) -> pd.DataFrame:
    output = (
        metadata["beta_60"]
        .join(metadata["realized_volatility_20"], how="outer")
        .join(metadata["trailing_amount_20"], how="outer")
    )
    output["log_trailing_amount_20"] = np.log(
        output["trailing_amount_20"].where(output["trailing_amount_20"] > 0.0)
    )
    return output[["beta_60", "realized_volatility_20", "log_trailing_amount_20"]]


def purged_training_dates(
    calendar: pd.DatetimeIndex,
    test_start: pd.Timestamp,
) -> pd.DatetimeIndex:
    location = int(calendar.get_indexer([test_start])[0])
    last_location = location - 11
    if last_location < 250:
        raise ValueError(f"insufficient purged training history before {test_start}")
    return calendar[: last_location + 1]


def eligible_test_dates(
    calendar: pd.DatetimeIndex,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    execution_delay: int = 1,
    horizon: int = 10,
) -> pd.DatetimeIndex:
    last_location = len(calendar) - (execution_delay + horizon) - 1
    eligible = calendar[: last_location + 1]
    return eligible[(eligible >= start) & (eligible <= end)]


def slice_dates(
    frame: pd.DataFrame,
    dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    mask = frame.index.get_level_values("datetime").isin(dates)
    return frame.loc[mask].copy()


def date_key(index: pd.MultiIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"datetime": index.get_level_values("datetime")},
        index=index,
    )


def sector_aggregate(
    features: pd.DataFrame,
    target: pd.DataFrame,
    classification: Mapping[str, Mapping[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = attach_classification(features.index, classification)
    joined = features.join(meta[["sector"]]).join(
        target.rename(columns={target.columns[0]: "target"})
    )
    groupers = [
        joined.index.get_level_values("datetime"),
        joined["sector"],
    ]
    sector_features = (
        joined[list(features.columns)]
        .groupby(
            groupers,
            sort=True,
        )
        .median()
    )
    sector_target = joined["target"].groupby(groupers, sort=True).median().to_frame("target_return")
    sector_features.index = sector_features.index.set_names(["datetime", "instrument"])
    sector_target.index = sector_target.index.set_names(["datetime", "instrument"])
    return sector_features.sort_index(), sector_target.sort_index()


def fit_predict_cell(
    *,
    ranking_id: str,
    train_features: pd.DataFrame,
    test_features: pd.DataFrame,
    train_target: pd.DataFrame,
    classification: Mapping[str, Mapping[str, str]],
    seed: int,
) -> pd.DataFrame:
    if ranking_id == "r4_two_stage_hierarchical_rank":
        sector_x, sector_y = sector_aggregate(
            train_features,
            train_target,
            classification,
        )
        sector_fit = fit_ranker(
            sector_x,
            sector_y,
            group_keys=date_key(sector_x.index),
            seed=seed,
        )
        placeholder = pd.DataFrame(
            0.0,
            index=test_features.index,
            columns=["target_return"],
        )
        sector_test_x, _ = sector_aggregate(
            test_features,
            placeholder,
            classification,
        )
        sector_scores = predict_ranker(sector_fit, sector_test_x)
        security_fit = fit_ranker(
            train_features,
            train_target,
            group_keys=date_key(train_features.index),
            seed=seed,
        )
        security_scores = predict_ranker(security_fit, test_features)
        return transform_hierarchical_scores(
            sector_scores,
            security_scores,
            classification=classification,
            sector_weight=0.35,
        )

    fit = fit_ranker(
        train_features,
        train_target,
        group_keys=date_key(train_features.index),
        seed=seed,
    )
    return predict_ranker(fit, test_features)


def target_mode(ranking_id: str) -> str:
    return {
        "r0_cn_x1_0_raw_return_rank": "raw",
        "r1_benchmark_relative_rank": "benchmark_relative",
        "r2_industry_relative_rank": "sector_relative",
        "r3_risk_residual_rank": "risk_residual_partial",
        "r4_two_stage_hierarchical_rank": "sector_relative",
    }[ranking_id]


def candidate_families(ranking_id: str) -> tuple[str, ...]:
    if ranking_id in {
        "r0_cn_x1_0_raw_return_rank",
        "r1_benchmark_relative_rank",
    }:
        return ("current_cn_ohlcv",)
    return FEATURE_FAMILIES


def label_rank_identity(
    first: pd.DataFrame,
    second: pd.DataFrame,
) -> dict[str, Any]:
    joined = (
        first.rename(columns={first.columns[0]: "first"})
        .join(
            second.rename(columns={second.columns[0]: "second"}),
            how="inner",
        )
        .dropna()
    )
    correlations: list[float] = []
    gains_equal = True
    for _, group in joined.groupby(level="datetime", sort=True):
        if len(group) < 2:
            continue
        first_rank = group["first"].rank(method="average", pct=True)
        second_rank = group["second"].rank(method="average", pct=True)
        correlations.append(float(first_rank.corr(second_rank, method="spearman")))
        first_gain = np.floor(first_rank.clip(0.0, 1.0) * 5).clip(0, 4).astype(int)
        second_gain = np.floor(second_rank.clip(0.0, 1.0) * 5).clip(0, 4).astype(int)
        gains_equal = gains_equal and bool((first_gain.to_numpy() == second_gain.to_numpy()).all())
    return {
        "n_dates": len(correlations),
        "minimum_daily_rank_correlation": min(correlations) if correlations else 0.0,
        "mean_daily_rank_correlation": float(np.mean(correlations)) if correlations else 0.0,
        "gain_labels_exactly_equal": gains_equal,
    }


def turnover(
    previous: Mapping[str, float],
    current: Mapping[str, float],
) -> float:
    previous_cash = 1.0 - sum(previous.values())
    current_cash = 1.0 - sum(current.values())
    names = set(previous) | set(current)
    return 0.5 * (
        sum(abs(current.get(name, 0.0) - previous.get(name, 0.0)) for name in names)
        + abs(current_cash - previous_cash)
    )
