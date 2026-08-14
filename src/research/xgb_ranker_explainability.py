"""Model-native current-decision explanations for governed XGBoost rankers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


class XGBRankerExplainabilityError(ValueError):
    """Raised when model-native contribution evidence cannot be reconciled."""


def _finite_required(value: object, *, label: str) -> float:
    result = float(value)
    if not np.isfinite(result):
        raise XGBRankerExplainabilityError(f"{label} must be finite")
    return result


def _finite_or_none(value: object) -> float | None:
    result = float(value)
    return result if np.isfinite(result) else None


def build_xgb_pred_contribs(
    *,
    model: Any,
    features: pd.DataFrame,
    scores: pd.DataFrame,
    column_to_factor_id: Mapping[str, str],
    instruments: Sequence[str],
    decision_role: str,
) -> dict[str, Any]:
    """Return canonical-factor TreeSHAP contributions for named current rows.

    XGBoost's native ``pred_contribs`` output is used directly; no SHAP package
    or surrogate explainer is introduced. Every row is reconciled back to the
    exact model score before publication. Missing source feature observations
    remain explicit JSON ``null`` values; model outputs must always be finite.
    """

    import xgboost as xgb

    requested = [str(value) for value in instruments]
    index_instruments = features.index.get_level_values("instrument").astype(str)
    selected = features.loc[index_instruments.isin(requested)].copy()
    if selected.empty:
        raise XGBRankerExplainabilityError("no feature rows for explanation instruments")
    selected_instruments = selected.index.get_level_values("instrument").astype(str)
    if set(selected_instruments) != set(requested):
        missing = sorted(set(requested) - set(selected_instruments))
        raise XGBRankerExplainabilityError(f"missing explanation rows for instruments: {missing}")
    columns = [str(column) for column in selected.columns]
    missing_columns = sorted(set(columns) - set(column_to_factor_id))
    if missing_columns:
        raise XGBRankerExplainabilityError(
            f"missing canonical factor mapping for columns: {missing_columns}"
        )
    matrix = xgb.DMatrix(selected.loc[:, columns])
    contributions = np.asarray(model.predict(matrix, pred_contribs=True), dtype=float)
    predictions = np.asarray(model.predict(matrix), dtype=float).reshape(-1)
    if contributions.shape != (len(selected), len(columns) + 1):
        raise XGBRankerExplainabilityError("unexpected XGBoost pred_contribs shape")
    if not np.isfinite(contributions).all() or not np.isfinite(predictions).all():
        raise XGBRankerExplainabilityError("XGBoost explanation outputs must be finite")
    reconciled = contributions.sum(axis=1)
    if not np.allclose(reconciled, predictions, rtol=1e-6, atol=1e-6):
        raise XGBRankerExplainabilityError(
            "XGBoost contributions do not reconcile to model predictions"
        )
    expected_scores = scores.reindex(selected.index)["score"].to_numpy(dtype=float)
    if not np.isfinite(expected_scores).all():
        raise XGBRankerExplainabilityError("published ranker scores must be finite")
    if not np.allclose(predictions, expected_scores, rtol=1e-6, atol=1e-6):
        raise XGBRankerExplainabilityError(
            "XGBoost explanation predictions do not match published ranker scores"
        )

    percentiles = features.loc[:, columns].rank(method="average", pct=True)
    rows: list[dict[str, Any]] = []
    for offset, index in enumerate(selected.index):
        instrument = str(index[1]) if isinstance(index, tuple) else str(index)
        feature_rows: list[dict[str, Any]] = []
        for column_index, column in enumerate(columns):
            contribution = _finite_required(
                contributions[offset, column_index],
                label=f"{instrument}.{column}.contribution",
            )
            feature_rows.append(
                {
                    "factor_id": str(column_to_factor_id[column]),
                    "value": _finite_or_none(selected.loc[index, column]),
                    "percentile": _finite_or_none(percentiles.loc[index, column]),
                    "contribution": contribution,
                }
            )
        positives = sorted(
            (row for row in feature_rows if row["contribution"] > 0.0),
            key=lambda row: (-float(row["contribution"]), str(row["factor_id"])),
        )[:3]
        negatives = sorted(
            (row for row in feature_rows if row["contribution"] < 0.0),
            key=lambda row: (float(row["contribution"]), str(row["factor_id"])),
        )[:3]
        rows.append(
            {
                "instrument": instrument,
                "decision_role": decision_role,
                "score": _finite_required(predictions[offset], label=f"{instrument}.score"),
                "bias": _finite_required(
                    contributions[offset, -1], label=f"{instrument}.bias"
                ),
                "top_positive": positives,
                "top_negative": negatives,
                "factor_contributions": sorted(
                    feature_rows, key=lambda row: str(row["factor_id"])
                ),
            }
        )
    rows.sort(key=lambda row: str(row["instrument"]))
    return {
        "method": "xgboost_pred_contribs",
        "score_reconciliation": "bias_plus_factor_contributions_equals_ranker_score",
        "decision_role": decision_role,
        "rows": rows,
    }


def attach_factor_contributions(
    snapshot: Mapping[str, Any],
    explanations: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach per-instrument model contributions to canonical factor rows."""

    output = dict(snapshot)
    factors = output.get("factors")
    rows = explanations.get("rows")
    if not isinstance(factors, list) or not isinstance(rows, list):
        raise XGBRankerExplainabilityError("invalid factor/explanation evidence shape")
    by_factor: dict[str, list[dict[str, Any]]] = {}
    for explanation in rows:
        if not isinstance(explanation, Mapping):
            continue
        instrument = str(explanation.get("instrument", ""))
        role = str(explanation.get("decision_role", ""))
        for contribution in explanation.get("factor_contributions", []):
            if not isinstance(contribution, Mapping):
                continue
            factor_id = str(contribution.get("factor_id", ""))
            by_factor.setdefault(factor_id, []).append(
                {
                    "instrument": instrument,
                    "decision_role": role,
                    "value": contribution.get("value"),
                    "percentile": contribution.get("percentile"),
                    "contribution": _finite_required(
                        contribution["contribution"],
                        label=f"{instrument}.{factor_id}.contribution",
                    ),
                }
            )
    enriched: list[dict[str, Any]] = []
    for raw in factors:
        row = dict(raw)
        factor_id = str(row.get("factor_id", ""))
        reference = dict(row.get("reference") or {})
        reference["model_contributions"] = sorted(
            by_factor.get(factor_id, []), key=lambda item: str(item["instrument"])
        )
        row["reference"] = reference
        enriched.append(row)
    output["factors"] = enriched
    return output