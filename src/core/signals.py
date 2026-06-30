"""Signal generation — pure functions.

All functions are stateless and side-effect-free so they can be called
directly from notebooks for interactive validation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any


def generate_scores(
    model: Any,
    feature_df: pd.DataFrame,
    sanitize_columns: bool = True,
) -> pd.Series:
    """Generate a score Series from a fitted LightGBM (or sklearn-compatible) model.

    Parameters
    ----------
    model:
        Any object with a ``.predict(X)`` method.
    feature_df:
        DataFrame of features.  Index can be anything (datetime, MultiIndex, etc.).
        NaN / Inf values are replaced with 0 before prediction.
    sanitize_columns:
        If True, column names are sanitised to match the naming used in
        ``end_to_end_training_pipeline.ipynb`` (``$`` → ``D``, etc.).

    Returns
    -------
    pd.Series
        Score for each row, same index as ``feature_df``.

    Examples
    --------
    >>> scores = generate_scores(booster, feature_df.loc["2026-06-01"])
    >>> scores.sort_values(ascending=False).head(10)
    """
    df = feature_df.copy()

    if sanitize_columns:
        def _sanitize(c: str) -> str:
            return (
                str(c)
                .replace("$", "D")
                .replace("/", "_d_")
                .replace("(", "L")
                .replace(")", "R")
                .replace(",", "_")
                .replace(" ", "_")
                .replace("-", "neg")
                .replace("+", "plus")
            )
        df.columns = [_sanitize(c) for c in df.columns]

    X = df.fillna(0.0).replace([np.inf, -np.inf], 0.0)
    preds = model.predict(X.values)
    return pd.Series(preds, index=feature_df.index, name="score")


def generate_scores_panel(
    model: Any,
    feature_panel: pd.DataFrame,
    date_level: int = 0,
    sanitize_columns: bool = True,
) -> pd.DataFrame:
    """Apply ``generate_scores`` cross-sectionally to a full panel DataFrame.

    Parameters
    ----------
    feature_panel:
        MultiIndex DataFrame with (datetime, instrument) or (instrument, datetime)
        as index levels.  Specify which level holds dates via ``date_level``.

    Returns
    -------
    pd.DataFrame
        Columns: ["score"], same MultiIndex as input.

    Examples
    --------
    >>> score_panel = generate_scores_panel(booster, X_test)
    >>> score_panel.xs("2026-06-01", level=0).sort_values("score", ascending=False)
    """
    scores = generate_scores(model, feature_panel, sanitize_columns=sanitize_columns)
    return scores.to_frame("score")
