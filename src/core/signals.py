"""Core strategy interfaces for notebook-friendly score generation."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pandas as pd


class ScoreGenerationError(RuntimeError):
    """Raised when model score generation fails."""



def load_model(model_path: str | Path) -> Any:
    """Load a serialized sklearn/lightgbm model from disk.

    Parameters
    ----------
    model_path:
        Path to pickle model artifact.
    """
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    with path.open("rb") as f:
        return pickle.load(f)



def generate_scores(model: Any, feature_df: pd.DataFrame) -> pd.Series:
    """Generate per-instrument scores from a fitted model.

    This function is notebook-friendly and intentionally side-effect free.
    It supports regressors via ``predict`` and classifiers via ``predict_proba``
    as a fallback for legacy models.
    """
    if feature_df.empty:
        return pd.Series(dtype=float, name="score")

    if isinstance(feature_df.index, pd.MultiIndex):
        score_index = feature_df.index
    else:
        score_index = feature_df.index

    try:
        if hasattr(model, "predict"):
            values = model.predict(feature_df.values)
            scores = pd.Series(values, index=score_index, name="score", dtype=float)
            return scores
        if hasattr(model, "predict_proba"):
            values = model.predict_proba(feature_df.values)[:, 1]
            scores = pd.Series(values, index=score_index, name="score", dtype=float)
            return scores
    except Exception as exc:
        raise ScoreGenerationError(f"Failed to generate scores: {exc}") from exc

    raise ScoreGenerationError(
        f"Unsupported model type: {type(model)!r}. Expected predict() or predict_proba()."
    )
