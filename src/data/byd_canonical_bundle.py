"""Canonical BYD daily-bar reconstruction from one raw source and explicit factors.

The canonical contract deliberately separates:

1. raw executable OHLCV;
2. a daily adjustment-factor series;
3. reconstructed adjusted OHLCV for features and labels;
4. corporate-action and cross-provider audit evidence.

No cross-provider row stitching is allowed. A secondary source is used only for
quality control and can never fill a primary-source gap.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.data.corporate_actions.adjustment import rebuild_adjusted_ohlcv

PRICE_COLUMNS = ("open", "high", "low", "close")
RAW_COLUMNS = ("date", *PRICE_COLUMNS, "volume")
MIN_PRICE_DECIMALS = 8


@dataclass(frozen=True)
class CanonicalBundle:
    raw_bars: pd.DataFrame
    adjustment_factors: pd.DataFrame
    adjusted_bars: pd.DataFrame
    corporate_actions: pd.DataFrame
    session_audit: pd.DataFrame
    provider_comparison: pd.DataFrame
    manifest: dict[str, Any]


def _normalise_frame(frame: pd.DataFrame, *, name: str) -> pd.DataFrame:
    missing = [column for column in RAW_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")
    out = frame.copy(deep=True)
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    if out["date"].duplicated().any():
        raise ValueError(f"{name} contains duplicate dates")
    for column in (*PRICE_COLUMNS, "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise").astype(float)
    if not np.isfinite(out[list(PRICE_COLUMNS)]).all().all():
        raise ValueError(f"{name} contains non-finite prices")
    if (out[list(PRICE_COLUMNS)] <= 0).any().any():
        raise ValueError(f"{name} contains non-positive prices")
    if (out["volume"] < 0).any():
        raise ValueError(f"{name} contains negative volume")
    envelope = (
        (out["low"] <= out["open"])
        & (out["low"] <= out["close"])
        & (out["high"] >= out["open"])
        & (out["high"] >= out["close"])
    )
    if not envelope.all():
        bad = out.loc[~envelope, "date"].dt.strftime("%Y-%m-%d").tolist()[:10]
        raise ValueError(f"{name} invalid OHLC envelope: {bad}")
    return out.sort_values("date").reset_index(drop=True)


def derive_adjustment_factors(
    raw_bars: pd.DataFrame,
    adjusted_close: pd.DataFrame,
    *,
    cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    """Derive a high-precision daily factor from raw and adjusted closes.

    The factor source must describe the same provider history as ``raw_bars``.
    This function does not combine price rows from different providers.
    """

    raw = _normalise_frame(raw_bars, name="raw_bars")
    if not {"date", "adjusted_close"} <= set(adjusted_close.columns):
        raise ValueError("adjusted_close requires date and adjusted_close columns")
    adjusted = adjusted_close.loc[:, ["date", "adjusted_close"]].copy()
    adjusted["date"] = pd.to_datetime(adjusted["date"], errors="raise").dt.normalize()
    adjusted["adjusted_close"] = pd.to_numeric(
        adjusted["adjusted_close"], errors="raise"
    ).astype(float)
    if adjusted["date"].duplicated().any():
        raise ValueError("adjusted_close contains duplicate dates")
    merged = raw[["date", "close"]].merge(
        adjusted, on="date", how="left", validate="one_to_one"
    )
    if merged["adjusted_close"].isna().any():
        missing = merged.loc[merged["adjusted_close"].isna(), "date"].dt.strftime(
            "%Y-%m-%d"
        )
        raise ValueError(
            "adjusted close missing for raw dates: " + ", ".join(missing.tolist()[:10])
        )
    factor = merged["adjusted_close"] / merged["close"]
    if not (np.isfinite(factor) & (factor > 0)).all():
        raise ValueError("derived adjustment factors must be finite and positive")
    cutoff_date = pd.Timestamp(cutoff).normalize()
    cutoff_rows = factor.loc[merged["date"] == cutoff_date]
    if len(cutoff_rows) != 1:
        raise ValueError("cutoff must be present exactly once in raw history")
    # The absolute scale of an adjustment factor is arbitrary. Anchor it to 1
    # at the frozen cutoff so identical inputs produce an immutable qfq series.
    anchored = factor / float(cutoff_rows.iloc[0])
    return pd.DataFrame(
        {
            "date": merged["date"],
            "factor": anchored.astype(float),
            "provider_adjusted_close": merged["adjusted_close"].astype(float),
        }
    )


def _normalise_actions(actions: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["date", "dividend", "stock_split", "event_source"]
    if actions is None or actions.empty:
        return pd.DataFrame(columns=columns)
    out = actions.copy(deep=True)
    if "date" not in out.columns:
        raise ValueError("corporate actions require date")
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for column in ("dividend", "stock_split"):
        if column not in out.columns:
            out[column] = 0.0
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    if "event_source" not in out.columns:
        out["event_source"] = "unknown"
    return out[columns].sort_values("date").reset_index(drop=True)


def audit_adjustment_events(
    factors: pd.DataFrame,
    actions: pd.DataFrame,
    *,
    jump_tolerance: float = 1e-8,
) -> pd.DataFrame:
    """Map each factor discontinuity to a declared action or flag it."""

    frame = factors[["date", "factor"]].copy()
    frame["factor_change"] = frame["factor"].pct_change().fillna(0.0)
    action_dates = set(pd.to_datetime(actions["date"]).dt.normalize())
    # Providers may place a dividend factor transition on the prior trading
    # session. Treat both the action date and immediately preceding factor row
    # as explainable candidates, but retain the exact mapping in evidence.
    previous_dates: set[pd.Timestamp] = set()
    for action_date in action_dates:
        prior = frame.loc[frame["date"] < action_date, "date"]
        if not prior.empty:
            previous_dates.add(pd.Timestamp(prior.iloc[-1]))
    explainable_dates = action_dates | previous_dates
    frame["factor_jump"] = frame["factor_change"].abs() > jump_tolerance
    frame["action_explained"] = frame["date"].isin(explainable_dates)
    frame["unexplained_jump"] = frame["factor_jump"] & ~frame["action_explained"]
    return frame


def compare_raw_providers(
    primary: pd.DataFrame,
    secondary: pd.DataFrame | None,
) -> pd.DataFrame:
    """Compare raw-return streams without substituting secondary rows."""

    left = _normalise_frame(primary, name="primary_raw")
    if secondary is None or secondary.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "primary_open_return",
                "secondary_open_return",
                "absolute_return_difference",
                "primary_volume",
                "secondary_volume",
            ]
        )
    right = _normalise_frame(secondary, name="secondary_raw")
    left = left.assign(primary_open_return=left["open"].pct_change())
    right = right.assign(secondary_open_return=right["open"].pct_change())
    merged = left[
        ["date", "primary_open_return", "volume"]
    ].rename(columns={"volume": "primary_volume"}).merge(
        right[["date", "secondary_open_return", "volume"]].rename(
            columns={"volume": "secondary_volume"}
        ),
        on="date",
        how="inner",
        validate="one_to_one",
    )
    merged["absolute_return_difference"] = (
        merged["primary_open_return"] - merged["secondary_open_return"]
    ).abs()
    return merged


def _session_audit(raw: pd.DataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    out = raw[["date", "volume"]].copy()
    out["session_status"] = np.where(out["volume"] > 0, "traded", "zero_volume")
    if not comparison.empty:
        common = set(comparison["date"])
        out["secondary_status"] = np.where(
            out["date"].isin(common), "common", "missing_in_secondary"
        )
    else:
        out["secondary_status"] = "secondary_unavailable"
    return out


def dataframe_sha256(frame: pd.DataFrame) -> str:
    normalised = frame.copy()
    for column in normalised.columns:
        if pd.api.types.is_datetime64_any_dtype(normalised[column]):
            normalised[column] = normalised[column].dt.strftime("%Y-%m-%d")
    payload = normalised.to_csv(index=False, float_format="%.12f", lineterminator="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_canonical_bundle(
    *,
    raw_primary: pd.DataFrame,
    provider_adjusted_close: pd.DataFrame,
    cutoff: str,
    primary_provider: str,
    raw_secondary: pd.DataFrame | None = None,
    secondary_provider: str | None = None,
    corporate_actions: pd.DataFrame | None = None,
    provider_parameters: dict[str, Any] | None = None,
) -> CanonicalBundle:
    raw = _normalise_frame(raw_primary, name="raw_primary")
    cutoff_date = pd.Timestamp(cutoff).normalize()
    raw = raw.loc[raw["date"] <= cutoff_date].copy().reset_index(drop=True)
    if raw.empty or raw["date"].iloc[-1] != cutoff_date:
        raise ValueError("primary raw history must end exactly on the declared cutoff")

    factors = derive_adjustment_factors(
        raw, provider_adjusted_close, cutoff=cutoff_date
    )
    adjusted = rebuild_adjusted_ohlcv(raw, factors, cutoff=cutoff_date)
    # Persist at high precision. This assertion prevents a two-decimal adjusted
    # history from becoming the model input even if the upstream source rounds.
    for column in PRICE_COLUMNS:
        adjusted[column] = adjusted[column].astype(float).round(MIN_PRICE_DECIMALS)
    actions = _normalise_actions(corporate_actions)
    event_audit = audit_adjustment_events(factors, actions)
    comparison = compare_raw_providers(raw, raw_secondary)
    sessions = _session_audit(raw, comparison)

    common_return_correlation = None
    mean_absolute_return_difference = None
    return_differences_over_1pct = None
    if not comparison.empty:
        valid = comparison.dropna(
            subset=["primary_open_return", "secondary_open_return"]
        )
        if not valid.empty:
            common_return_correlation = float(
                valid["primary_open_return"].corr(valid["secondary_open_return"])
            )
            mean_absolute_return_difference = float(
                valid["absolute_return_difference"].mean()
            )
            return_differences_over_1pct = int(
                (valid["absolute_return_difference"] > 0.01).sum()
            )

    manifest = {
        "schema_version": "byd_canonical_adjusted_ohlcv_v1",
        "symbol": "002594.SZ",
        "cutoff": cutoff_date.strftime("%Y-%m-%d"),
        "primary_provider": primary_provider,
        "secondary_provider": secondary_provider,
        "cross_provider_stitching": False,
        "price_roles": {
            "raw": "execution_and_event_accounting",
            "adjusted": "features_labels_and_total_return_research",
        },
        "factor_method": "provider_adjusted_close_divided_by_same_provider_raw_close_cutoff_anchored",
        "precision_decimals": MIN_PRICE_DECIMALS,
        "rows": int(len(raw)),
        "first_date": raw["date"].iloc[0].strftime("%Y-%m-%d"),
        "last_date": raw["date"].iloc[-1].strftime("%Y-%m-%d"),
        "raw_sha256": dataframe_sha256(raw),
        "factor_sha256": dataframe_sha256(factors),
        "adjusted_sha256": dataframe_sha256(adjusted),
        "actions_sha256": dataframe_sha256(actions),
        "unexplained_factor_jumps": int(event_audit["unexplained_jump"].sum()),
        "zero_volume_sessions": int((sessions["session_status"] == "zero_volume").sum()),
        "common_return_correlation": common_return_correlation,
        "mean_absolute_return_difference": mean_absolute_return_difference,
        "return_differences_over_1pct": return_differences_over_1pct,
        "provider_parameters": provider_parameters or {},
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return CanonicalBundle(
        raw_bars=raw,
        adjustment_factors=factors,
        adjusted_bars=adjusted,
        corporate_actions=actions,
        session_audit=sessions,
        provider_comparison=comparison,
        manifest=manifest,
    )
