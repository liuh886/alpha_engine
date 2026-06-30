"""Core strategy interfaces for notebook-friendly score generation."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pandas as pd


class ScoreGenerationError(RuntimeError):
    """Raised when model score generation fails."""


def load_model(model_path: str | Path) -> Any:
    """Load a serialized model from disk."""
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    with path.open("rb") as f:
        return pickle.load(f)


def generate_scores(model: Any, feature_df: pd.DataFrame) -> pd.Series:
    """Generate model scores while preserving the input index."""
    if feature_df.empty:
        return pd.Series(dtype=float, name="score", index=feature_df.index)

    try:
        if hasattr(model, "predict_proba"):
            values = model.predict_proba(feature_df)
            if len(values.shape) != 2 or values.shape[1] < 2:
                raise ScoreGenerationError("predict_proba() must return class probabilities")
            return pd.Series(values[:, 1], index=feature_df.index, name="score", dtype=float)

        if hasattr(model, "predict"):
            values = model.predict(feature_df)
            return pd.Series(values, index=feature_df.index, name="score", dtype=float)
    except ScoreGenerationError:
        raise
    except Exception as exc:
        raise ScoreGenerationError(f"Failed to generate scores: {exc}") from exc

    raise ScoreGenerationError(
        f"Unsupported model type: {type(model)!r}. Expected predict_proba() or predict()."
    )
