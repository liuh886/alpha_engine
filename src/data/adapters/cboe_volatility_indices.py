"""Cboe daily index-history adapter for QQQ volatility/tail-risk research.

Only official Cboe index-history CSV endpoints are supported. The adapter has
no alternate provider, no source splicing and no forward fill.
"""

from __future__ import annotations

import csv
import io
from urllib.request import Request, urlopen

import pandas as pd

SUPPORTED_INDICES = ("VIX9D", "VIX3M", "VVIX", "SKEW")
CBOE_HISTORY_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
)
_USER_AGENT = "Mozilla/5.0 AlphaEngine/1.0"


def parse_cboe_volatility_history(symbol: str, text: str) -> pd.DataFrame:
    """Parse one official Cboe daily-history CSV into a close-only frame."""
    normalized_symbol = str(symbol).strip().upper()
    if normalized_symbol not in SUPPORTED_INDICES:
        raise ValueError(f"unsupported Cboe index: {symbol}")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("Cboe CSV is missing a header")
    fields = {str(name).strip().upper(): str(name) for name in reader.fieldnames}
    if "DATE" not in fields:
        raise ValueError("Cboe CSV is missing DATE")
    value_field = fields.get("CLOSE") or fields.get(normalized_symbol)
    if value_field is None:
        raise ValueError(f"Cboe CSV has no CLOSE/{normalized_symbol} value column")

    rows: list[dict[str, object]] = []
    for raw in reader:
        date = pd.to_datetime(raw.get(fields["DATE"]), errors="coerce")
        value = pd.to_numeric(raw.get(value_field), errors="coerce")
        if pd.isna(date) or pd.isna(value):
            continue
        value_float = float(value)
        if value_float <= 0.0:
            raise ValueError(f"{normalized_symbol} contains a non-positive value")
        rows.append({"date": pd.Timestamp(date).normalize(), "close": value_float})

    if not rows:
        raise ValueError(f"{normalized_symbol} history contains no usable rows")
    frame = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError(f"{normalized_symbol} history contains duplicate dates")
    return frame.set_index("date")


def fetch_cboe_volatility_history(
    symbol: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout_seconds: float = 30.0,
) -> pd.DataFrame:
    """Fetch one official Cboe daily index history."""
    normalized_symbol = str(symbol).strip().upper()
    if normalized_symbol not in SUPPORTED_INDICES:
        raise ValueError(f"unsupported Cboe index: {symbol}")
    url = CBOE_HISTORY_URL.format(symbol=normalized_symbol)
    request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "text/csv,*/*"})
    with urlopen(request, timeout=timeout_seconds) as response:
        text = response.read().decode("utf-8-sig")
    frame = parse_cboe_volatility_history(normalized_symbol, text)
    if start_date is not None:
        frame = frame.loc[frame.index >= pd.Timestamp(start_date).normalize()].copy()
    if end_date is not None:
        frame = frame.loc[frame.index <= pd.Timestamp(end_date).normalize()].copy()
    if frame.empty:
        raise ValueError(f"{normalized_symbol} history is empty after clipping")
    return frame
