"""Independent Sina ETF/fund history transport used as a bounded fallback.

The Eastmoney fund endpoint intermittently drops connections. This adapter is
only reached after :class:`AkShareAdapter` exhausts its bounded transport retry,
and it is deliberately narrow:

* prices are used exactly as the provider reports them (the endpoint has no
  adjustment parameter), and the raw basis is recorded in provenance;
* Sina reports volume in **shares** and amount in **CNY**. The governed CN ETF
  series (515180) is provider-reported **lots** (1 lot = 100 shares), so volume
  is normalized by dividing reported shares by 100. Amount stays
  provider-reported CNY. The payload unit is reconciled from
  ``amount / (volume * close)`` and must classify as ``shares_cny``; a payload
  that already reports lots (or 100-CNY units) fails closed rather than silently
  mixing bases;
* the refresh layer validates the normalized lots against the sealed governed
  overlap at a 0.001 relative tolerance, which is equivalent to requiring the
  raw Sina shares / governed lots ratio to be exactly 100:1.

The caller must preserve the governed history and append only strictly newer
sessions; the refresh enforces that boundary.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.data.adapters.akshare_adapter import is_cn_etf
from src.data.adapters.akshare_sina_adapter import _provider_symbol
from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]
_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")
_SOURCE_URL_TEMPLATE = (
    "https://finance.sina.com.cn/realstock/company/{provider_symbol}/"
    "hisdata_klc2/klc_kl.js"
)
_PRICE_BASIS = "provider_reported_raw"
_SINA_SHARES_PER_LOT = 100.0
_VOLUME_NORMALIZATION_FACTOR = 1.0 / _SINA_SHARES_PER_LOT
_VOLUME_BASIS = "lots_normalized_from_sina_shares_100_to_1"
_AMOUNT_BASIS = "CNY_vendor_reported"
# ``amount / (volume * close)`` is ~1.0 when volume is shares and amount is CNY,
# ~0.01 when volume is lots, and ~100 when amount is quoted in 100-CNY units.
_UNIT_BANDS = (
    ("shares_cny", 0.8, 1.25),
    ("lots_cny", 0.008, 0.0125),
    ("shares_per_100_cny", 80.0, 125.0),
)


def _content_hash(frame: pd.DataFrame) -> tuple[str, int]:
    payload = frame.copy()
    payload["date"] = pd.to_datetime(payload["date"]).dt.strftime("%Y-%m-%d")
    text = payload.to_csv(index=False, lineterminator="\n")
    encoded = text.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def _classify_volume_unit(median_ratio: float) -> str | None:
    for name, low, high in _UNIT_BANDS:
        if low <= median_ratio <= high:
            return name
    return None


def _normalize_sina_fund_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Validate a Sina ETF/fund payload and normalize shares to governed lots.

    Returns the canonical price frame with volume divided by 100 (shares ->
    lots) and provider-reported CNY amount, plus the unit reconciliation
    evidence used in provenance.
    """

    if frame is None or frame.empty:
        raise DataFetchError(f"empty Sina fund data for {symbol}")

    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DataFetchError(
            f"Sina fund payload missing columns for {symbol}: {missing}"
        )

    raw = frame[list(_REQUIRED_COLUMNS)].copy()
    raw_dates = raw["date"]
    # ``fund_etf_hist_sina`` returns ``datetime.date`` objects. Convert them to
    # ISO strings before parsing so pandas does not fall back to mixed-format
    # inference (and so malformed values fail closed rather than warn).
    date_inputs = raw_dates.map(
        lambda value: value.isoformat() if hasattr(value, "isoformat") else value
    )
    parsed_dates = pd.to_datetime(date_inputs, errors="coerce", format="mixed")
    if parsed_dates.isna().any():
        raise DataFetchError(f"Sina fund payload contains unparseable dates for {symbol}")
    raw["date"] = parsed_dates.dt.normalize()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")

    try:
        start_ts = pd.Timestamp(start).normalize()
        end_ts = (
            pd.Timestamp(end).normalize() if end else pd.Timestamp(raw["date"].max())
        )
    except (TypeError, ValueError) as exc:
        raise DataFetchError(
            f"invalid requested window for Sina fund {symbol}: {start}..{end}"
        ) from exc
    out = raw.loc[raw["date"].between(start_ts, end_ts, inclusive="both")].copy()
    if out.empty:
        raise DataFetchError(
            f"Sina fund payload has no bars for {symbol} from {start_ts.date()} "
            f"to {end_ts.date()}"
        )
    out = (
        out.sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if not out["date"].is_monotonic_increasing or out["date"].duplicated().any():
        raise DataFetchError(f"Sina fund dates are not ascending and unique for {symbol}")

    prices = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0.0).any():
        raise DataFetchError(
            f"Sina fund payload contains non-finite or non-positive OHLC for {symbol}"
        )
    tolerance = 1e-8
    if (out["high"] + tolerance < out[["open", "close"]].max(axis=1)).any():
        raise DataFetchError(f"Sina fund payload violates high >= open/close for {symbol}")
    if (out["low"] - tolerance > out[["open", "close"]].min(axis=1)).any():
        raise DataFetchError(f"Sina fund payload violates low <= open/close for {symbol}")

    implied = out["volume"] * out["close"]
    reconciled = (
        implied.notna()
        & (implied > 0.0)
        & out["amount"].notna()
        & (out["amount"] > 0.0)
    )
    if not reconciled.any():
        raise DataFetchError(
            f"Sina fund payload cannot reconcile volume and amount units for {symbol}"
        )
    ratios = out.loc[reconciled, "amount"] / implied.loc[reconciled]
    median_ratio = float(ratios.median())
    unit_basis = _classify_volume_unit(median_ratio)
    if unit_basis != "shares_cny":
        raise DataFetchError(
            "Sina fund payload is not on a reconcilable shares/CNY basis for "
            f"{symbol}: median amount/(volume*close)={median_ratio:.6g} "
            f"-> {unit_basis or 'unrecognized'}; refusing to normalize a "
            "non-share volume into the governed lot basis"
        )

    normalised = out.copy()
    # Sina reports shares; the governed CN ETF series is provider-reported lots
    # (1 lot = 100 shares). Amount is provider-reported CNY and is not rescaled.
    normalised["volume"] = out["volume"] / _SINA_SHARES_PER_LOT
    normalised["amount"] = out["amount"]
    normalised["factor"] = 1.0
    normalised = normalised[_BAR_COLUMNS]

    raw_date_type = next(
        (
            type(value).__name__
            for value in raw_dates.tolist()
            if value is not None and not (isinstance(value, float) and math.isnan(value))
        ),
        "unknown",
    )
    source_schema = ",".join(str(column) for column in frame.columns)
    content_hash, content_bytes = _content_hash(out)
    evidence = {
        "content_bytes": content_bytes,
        "content_hash": content_hash,
        "median_amount_over_volume_times_close": median_ratio,
        "reconciled_rows": int(reconciled.sum()),
        "sina_volume_unit": unit_basis,
        "sina_shares_per_lot": _SINA_SHARES_PER_LOT,
        "source_date_type": raw_date_type,
        "source_schema": source_schema,
        "volume_normalization_factor": _VOLUME_NORMALIZATION_FACTOR,
    }
    return normalised, evidence


def _provenance(
    *,
    provider_symbol: str,
    start: str,
    end: str | None,
    frame: pd.DataFrame,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    median_ratio = float(evidence["median_amount_over_volume_times_close"])
    caveat = (
        "Sina ETF/fund history is used only after the Eastmoney fund endpoint "
        "exhausts its bounded retry. Prices are provider-reported raw (the "
        "endpoint has no adjustment parameter). Sina reports volume in shares "
        f"and amount in CNY; reconciling amount/(volume*close) over "
        f"{evidence['reconciled_rows']} rows gives a median of "
        f"{median_ratio:.6f} -> {evidence['sina_volume_unit']}. Volume is "
        f"normalized by dividing reported shares by "
        f"{int(evidence['sina_shares_per_lot'])} to the governed CN ETF lot basis "
        "(raw shares / governed lots = 100:1); amount remains provider-reported "
        "CNY. The refresh validates the normalized lots against the sealed "
        "governed overlap at 0.001 relative tolerance and fails closed on drift."
    )
    return {
        "amount_basis": _AMOUNT_BASIS,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "first_date": pd.Timestamp(frame["date"].min()).strftime("%Y-%m-%d"),
        "last_date": pd.Timestamp(frame["date"].max()).strftime("%Y-%m-%d"),
        "median_amount_over_volume_times_close": median_ratio,
        "price_basis": _PRICE_BASIS,
        "provider": "akshare_sina_fund",
        "provider_symbol": provider_symbol,
        "reconciled_rows": int(evidence["reconciled_rows"]),
        "requested_end": str(end) if end else None,
        "requested_start": str(start),
        "research_only": True,
        "response_bytes": int(evidence["content_bytes"]),
        "response_sha256": str(evidence["content_hash"]),
        "rows": int(len(frame)),
        "sina_shares_per_lot": evidence["sina_shares_per_lot"],
        "sina_volume_unit": evidence["sina_volume_unit"],
        "source_date_format": evidence["source_date_type"],
        "source_schema": evidence["source_schema"],
        "source_url": _SOURCE_URL_TEMPLATE.format(provider_symbol=provider_symbol),
        "terms_caveat": caveat,
        "trade_ready": False,
        "volume_basis": _VOLUME_BASIS,
        "volume_normalization_factor": evidence["volume_normalization_factor"],
    }


@dataclass
class AkShareSinaFundAdapter:
    """Sina ETF/fund fallback with an explicit withheld volume basis."""

    min_interval_seconds: float = 0.75
    _name: str = "akshare_sina_fund"
    _last_request_at: float = field(default=0.0, init=False, repr=False)

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _provider_symbol(req.symbol)

    def _pace(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip().upper()
        market = str(req.market or "").strip().lower()
        start = str(req.start or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        if market != "cn":
            raise DataFetchError("akshare_sina_fund currently supports market=cn only")
        if not start:
            raise DataFetchError("start is required")
        if not is_cn_etf(symbol):
            # Cheap fail-fast for non-ETF symbols in the shared CN chain; no
            # network call is made and the router continues to the next source.
            raise DataFetchError(
                f"akshare_sina_fund supports CN ETFs/funds only: {symbol}"
            )

        try:
            import akshare as ak  # type: ignore
        except Exception as exc:
            raise DataFetchError(f"akshare import failed: {exc}") from exc

        provider_symbol = self.provider_symbol(req)
        self._pace()
        try:
            frame = ak.fund_etf_hist_sina(symbol=provider_symbol)
        except Exception as exc:
            raise DataFetchError(
                f"akshare Sina fund fetch failed for {provider_symbol}: {exc}"
            ) from exc

        normalised, evidence = _normalize_sina_fund_frame(
            frame,
            symbol=symbol,
            start=start,
            end=req.end,
        )
        provenance = _provenance(
            provider_symbol=provider_symbol,
            start=start,
            end=req.end,
            frame=normalised,
            evidence=evidence,
        )
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=normalised,
            provider_symbol=provider_symbol,
            provenance=provenance,
        )


__all__ = [
    "AkShareSinaFundAdapter",
    "_normalize_sina_fund_frame",
]
