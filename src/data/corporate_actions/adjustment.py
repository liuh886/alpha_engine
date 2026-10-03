"""Deterministic adjusted-price reconstruction from raw OHLCV and daily factors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

_PRICE_COLUMNS = ("open", "high", "low", "close")

def reanchor_additive_qfq(
    bars: pd.DataFrame, *, symbol: str, cutoff: str,
    bridge_path: Path, repository_root: Path, frozen_source_sha256: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Translate a declared additive vendor basis using issuer events, never a fitted offset.

    The same translation applies to every input OHLC row: the frozen anchor
    is a research price basis, not a raw execution price or a cash ledger.
    The caller must still verify every frozen overlap and preserve its bytes.
    """
    encoded = bridge_path.read_bytes()
    bridge = json.loads(encoded)
    if (
        bridge.get("schema_version") != "additive_qfq_price_basis_bridge_v1"
        or bridge.get("provider") != "tencent_qfq_history"
        or bridge.get("research_only") is not True
        or bridge.get("trade_ready") is not False
        or bridge.get("frozen_source_sha256") != frozen_source_sha256
        or bridge.get("price_role") != "anchored_adjusted_research_prices_not_raw_execution"
    ):
        raise ValueError("invalid qfq price-basis bridge identity")
    anchor = pd.Timestamp(bridge["anchor_date"])
    if pd.Timestamp(cutoff) < anchor:
        raise ValueError("qfq cutoff precedes the frozen anchor")
    events = []
    for event in bridge["events"]:
        if event["symbol"] != symbol or not anchor < pd.Timestamp(event["ex_date"]) <= pd.Timestamp(cutoff):
            continue
        source = (repository_root / event["source_path"]).resolve()
        if not source.is_relative_to(repository_root.resolve()):
            raise ValueError("price-basis source escapes repository")
        amount = float(event["reference_cash_amount"])
        if (
            event["event_type"] != "cash_dividend_reference_adjustment"
            or pd.Timestamp(event["announced_at"]) > pd.Timestamp(event["ex_date"])
            or not np.isfinite(amount) or amount <= 0
            or abs(float(event["total_distributed_cash"]) / int(event["total_shares"]) - amount) > 1e-7
            or hashlib.sha256(source.read_bytes()).hexdigest() != event["source_sha256"]
        ):
            raise ValueError("unverified issuer cash-reference adjustment")
        events.append(event)
    offset = sum(float(event["reference_cash_amount"]) for event in events)
    result = bars.copy(deep=True)
    for column in _PRICE_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="raise") + offset
    return result, {
        "bridge_sha256": hashlib.sha256(encoded).hexdigest(),
        "anchor_date": bridge["anchor_date"], "price_role": bridge["price_role"],
        "reference_cash_offset": offset, "events": events,
        "research_only": True, "trade_ready": False,
    }

def rebuild_adjusted_ohlcv(
    raw_bars: pd.DataFrame,
    daily_factors: pd.DataFrame,
    *,
    cutoff: str | pd.Timestamp,
) -> pd.DataFrame:
    """Rebuild adjusted OHLCV using a factor anchor frozen at ``cutoff``.

    ``daily_factors`` must contain one positive factor for every raw-bar date.
    Prices are multiplied by ``factor / cutoff_factor`` and volume is multiplied
    by the inverse ratio. The input frames are never modified.
    """

    required_bars = {"date", *_PRICE_COLUMNS, "volume"}
    missing_bars = sorted(required_bars - set(raw_bars.columns))
    if missing_bars:
        raise ValueError(f"raw bars missing columns: {missing_bars}")
    if not {"date", "factor"} <= set(daily_factors.columns):
        raise ValueError("daily factors require date and factor columns")

    bars = raw_bars.copy(deep=True)
    factors = daily_factors.loc[:, ["date", "factor"]].copy(deep=True)
    bars["date"] = pd.to_datetime(bars["date"], errors="raise").dt.normalize()
    factors["date"] = pd.to_datetime(
        factors["date"],
        errors="raise",
    ).dt.normalize()
    if bars["date"].duplicated().any():
        raise ValueError("raw bars contain duplicate dates")
    if factors["date"].duplicated().any():
        raise ValueError("daily factors contain duplicate dates")

    factors["factor"] = pd.to_numeric(factors["factor"], errors="raise")
    finite_positive = np.isfinite(factors["factor"]) & (factors["factor"] > 0)
    if not finite_positive.all():
        raise ValueError("adjustment factors must be finite and positive")

    cutoff_date = pd.Timestamp(cutoff).normalize()
    cutoff_rows = factors.loc[factors["date"] == cutoff_date, "factor"]
    if len(cutoff_rows) != 1:
        raise ValueError("declared cutoff must have exactly one adjustment factor")
    cutoff_factor = float(cutoff_rows.iloc[0])

    merged = bars.merge(
        factors,
        on="date",
        how="left",
        validate="one_to_one",
    )
    if merged["factor"].isna().any():
        missing = merged.loc[merged["factor"].isna(), "date"].dt.strftime("%Y-%m-%d")
        raise ValueError(
            "missing adjustment factor for raw-bar dates: " + ", ".join(missing.tolist()[:10])
        )

    ratio = merged["factor"].astype(float) / cutoff_factor
    for column in _PRICE_COLUMNS:
        values = pd.to_numeric(merged[column], errors="raise")
        merged[column] = values * ratio
    volume = pd.to_numeric(merged["volume"], errors="raise")
    merged["volume"] = volume / ratio
    merged["adjustment_anchor_date"] = cutoff_date
    merged["adjustment_anchor_factor"] = cutoff_factor
    merged["price_role"] = "adjusted_feature_and_label"

    if not (
        (merged["low"] <= merged["open"])
        & (merged["low"] <= merged["close"])
        & (merged["high"] >= merged["open"])
        & (merged["high"] >= merged["close"])
    ).all():
        raise ValueError("rebuilt adjusted OHLC relationships are invalid")
    return merged.sort_values("date").reset_index(drop=True)
