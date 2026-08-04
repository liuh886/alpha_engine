"""Canonical VWAP construction and source-role evidence for Alpha158."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


class CanonicalVwapError(ValueError):
    """Raised when reported turnover cannot support a canonical adjusted VWAP."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CanonicalVwapError(f"{label} bars missing columns: {missing}")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None)
    numeric = ["open", "high", "low", "close", "volume"]
    if "amount" in out.columns:
        numeric.append("amount")
    for column in numeric:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if out["date"].isna().any():
        raise CanonicalVwapError(f"{label} bars contain unparseable dates")
    out = out.sort_values("date").reset_index(drop=True)
    if out["date"].duplicated().any():
        raise CanonicalVwapError(f"{label} bars contain duplicate dates")
    if out.empty:
        raise CanonicalVwapError(f"{label} bars are empty")
    return out


def derive_adjusted_vwap(
    raw_frame: pd.DataFrame,
    adjusted_frame: pd.DataFrame,
    *,
    symbol: str,
    amount_is_reported: bool,
    volume_unit: str,
    amount_unit: str,
    envelope_tolerance: float = 1e-6,
    price_tick_size: float = 0.01,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Align raw/qfq bars and derive adjusted VWAP from reported turnover.

    Raw VWAP is reported turnover divided by reported share volume. It is moved
    to the adjusted-price basis by the same-day qfq/raw close ratio. Synthetic
    turnover and mismatched raw/adjusted volume are rejected.
    """

    if amount_is_reported is not True:
        raise CanonicalVwapError(
            f"{symbol}: synthetic or undeclared turnover cannot support canonical VWAP"
        )
    if volume_unit != "shares" or amount_unit != "CNY":
        raise CanonicalVwapError(
            f"{symbol}: canonical units must be shares and CNY, got "
            f"volume={volume_unit}, amount={amount_unit}"
        )
    if not np.isfinite(price_tick_size) or price_tick_size <= 0:
        raise CanonicalVwapError(f"{symbol}: price_tick_size must be positive")
    raw = _normalise(raw_frame, label=f"{symbol} raw")
    adjusted = _normalise(adjusted_frame, label=f"{symbol} adjusted")
    if "amount" not in raw.columns:
        raise CanonicalVwapError(f"{symbol}: raw bars do not contain reported amount")

    raw_columns = raw[["date", "close", "volume", "amount"]].rename(
        columns={
            "close": "raw_close",
            "volume": "raw_volume",
            "amount": "raw_amount",
        }
    )
    adjusted_columns = adjusted[
        ["date", "open", "high", "low", "close", "volume"]
    ].rename(columns={"volume": "adjusted_volume"})
    merged = adjusted_columns.merge(raw_columns, on="date", how="inner", validate="one_to_one")
    if len(merged) != len(raw) or len(merged) != len(adjusted):
        raise CanonicalVwapError(
            f"{symbol}: raw and adjusted calendars must match exactly: "
            f"raw={len(raw)}, adjusted={len(adjusted)}, overlap={len(merged)}"
        )

    required_numeric = [
        "open",
        "high",
        "low",
        "close",
        "adjusted_volume",
        "raw_close",
        "raw_volume",
        "raw_amount",
    ]
    if merged[required_numeric].isna().any().any():
        raise CanonicalVwapError(f"{symbol}: paired bars contain missing numeric values")
    if (merged[["open", "high", "low", "close", "raw_close"]] <= 0).any().any():
        raise CanonicalVwapError(f"{symbol}: paired prices must be positive")
    if (merged[["raw_volume", "raw_amount"]] <= 0).any().any():
        raise CanonicalVwapError(f"{symbol}: reported volume and amount must be positive")
    if not np.allclose(
        merged["adjusted_volume"],
        merged["raw_volume"],
        rtol=0.0,
        atol=0.0,
        equal_nan=False,
    ):
        raise CanonicalVwapError(
            f"{symbol}: raw and adjusted share volume differ; source pairing is invalid"
        )

    adjustment_ratio = merged["close"] / merged["raw_close"]
    raw_vwap = merged["raw_amount"] / merged["raw_volume"]
    adjusted_vwap = raw_vwap * adjustment_ratio
    if not np.isfinite(adjustment_ratio).all() or (adjustment_ratio <= 0).any():
        raise CanonicalVwapError(f"{symbol}: adjustment ratio is invalid")
    if not np.isfinite(adjusted_vwap).all() or (adjusted_vwap <= 0).any():
        raise CanonicalVwapError(f"{symbol}: adjusted VWAP is invalid")

    relative_tolerance = np.maximum(
        merged["close"].abs() * envelope_tolerance, 1e-8
    )
    below_distance = (merged["low"] - adjusted_vwap).clip(lower=0.0)
    above_distance = (adjusted_vwap - merged["high"]).clip(lower=0.0)
    envelope_distance = np.maximum(below_distance, above_distance)
    strict_violations = envelope_distance > relative_tolerance
    # Sina publishes adjusted OHLC to two decimals while turnover and volume retain
    # materially higher precision. Half a tick is the maximum nearest-tick error.
    rounding_tolerance = np.maximum(relative_tolerance, price_tick_size / 2.0)
    below = adjusted_vwap < (merged["low"] - rounding_tolerance)
    above = adjusted_vwap > (merged["high"] + rounding_tolerance)
    envelope_violations = int((below | above).sum())
    if envelope_violations:
        max_distance = float(envelope_distance[below | above].max())
        raise CanonicalVwapError(
            f"{symbol}: adjusted VWAP violates adjusted OHLC envelope on "
            f"{envelope_violations} sessions; max_distance={max_distance:.8f}, "
            f"half_tick={price_tick_size / 2.0:.8f}"
        )

    result = merged[["date", "open", "high", "low", "close"]].copy()
    result["vwap"] = adjusted_vwap
    result["volume"] = merged["raw_volume"]
    result["amount"] = merged["raw_amount"]
    result["factor"] = adjustment_ratio
    diagnostics = {
        "symbol": symbol,
        "rows": int(len(result)),
        "first_date": result["date"].min().date().isoformat(),
        "last_date": result["date"].max().date().isoformat(),
        "vwap_semantics": "reported_turnover_divided_by_reported_volume",
        "raw_vwap_basis": "reported_CNY_turnover/reported_share_volume",
        "adjustment_method": "same_source_qfq_close/raw_close_ratio",
        "volume_unit": "shares",
        "amount_unit": "CNY",
        "amount_is_reported": True,
        "raw_adjusted_volume_exact_match": True,
        "envelope_violations": 0,
        "rounded_envelope_tolerance_sessions": int(strict_violations.sum()),
        "max_envelope_rounding_distance": float(envelope_distance.max()),
        "price_tick_size": float(price_tick_size),
        "maximum_rounding_tolerance": float(price_tick_size / 2.0),
        "adjustment_ratio_min": float(adjustment_ratio.min()),
        "adjustment_ratio_max": float(adjustment_ratio.max()),
        "research_only": True,
        "trade_ready": False,
    }
    return result, diagnostics


def write_source_role_manifest(
    provider_dir: str | Path,
    *,
    provider_manifest: Mapping[str, Any],
    provider_manifest_path: str | Path,
    source_providers: list[str],
    market: str,
    vwap_ready: bool,
    blocker: str | None = None,
) -> dict[str, Any]:
    provider = Path(provider_dir).resolve()
    manifest_path = Path(provider_manifest_path).resolve()
    if not manifest_path.is_file():
        raise CanonicalVwapError(f"provider manifest is missing: {manifest_path}")
    payload = {
        "schema_version": "1.0",
        "market": market,
        "role": "canonical" if vwap_ready else "blocked",
        "canonical_training_eligible": bool(vwap_ready),
        "validation_only": False,
        "source_providers": source_providers,
        "provider_manifest_path": str(manifest_path),
        "provider_manifest_sha256": _sha256(manifest_path),
        "provider_identity_sha256": provider_manifest.get("provider_identity_sha256"),
        "field_semantics": {
            "open": "same_source_qfq_adjusted",
            "high": "same_source_qfq_adjusted",
            "low": "same_source_qfq_adjusted",
            "close": "same_source_qfq_adjusted",
            "vwap": (
                "reported_turnover_divided_by_reported_volume"
                if vwap_ready
                else "unavailable"
            ),
            "volume": "reported_shares_unadjusted",
            "amount": "reported_CNY_turnover_unadjusted",
            "factor": "same_source_qfq_close/raw_close_ratio",
        },
        "vwap_ready": bool(vwap_ready),
        "blocker": blocker,
        "research_only": True,
        "trade_ready": False,
    }
    path = provider / "source_role_manifest.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
