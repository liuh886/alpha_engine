"""CNN Fear & Greed historical data adapter.

The primary research boundary starts on 2021-02-01, the period for which the
CNN historical endpoint is treated as authoritative. The adapter intentionally
has no alternate provider or archive fallback.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

import pandas as pd

CNN_FEAR_GREED_START = "2021-02-01"
CNN_FEAR_GREED_URL = (
    f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{CNN_FEAR_GREED_START}"
)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def parse_cnn_fear_greed(payload: dict[str, Any]) -> pd.DataFrame:
    """Parse CNN history into one deterministic latest-observation-per-day series."""
    historical = payload.get("fear_and_greed_historical")
    if not isinstance(historical, dict):
        raise ValueError("CNN payload missing fear_and_greed_historical")
    data = historical.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("CNN payload missing historical data rows")

    rows: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict) or "x" not in entry or "y" not in entry:
            raise ValueError("CNN historical row missing x/y")
        timestamp = pd.Timestamp(float(entry["x"]), unit="ms", tz="UTC")
        date = timestamp.tz_localize(None).normalize()
        score = float(entry["y"])
        if not 0.0 <= score <= 100.0:
            raise ValueError(f"CNN Fear & Greed score out of range: {score}")
        rows.append(
            {
                "date": date,
                "timestamp_utc": timestamp,
                "fear_greed_score": score,
                "fear_greed_rating": str(entry.get("rating") or ""),
            }
        )

    frame = pd.DataFrame(rows).sort_values(["date", "timestamp_utc"], kind="stable")
    frame = frame.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return frame.drop(columns=["timestamp_utc"]).set_index("date")


def fetch_cnn_fear_greed(
    *,
    end_date: str | None = None,
    timeout_seconds: float = 30.0,
) -> pd.DataFrame:
    """Fetch CNN history from the frozen authoritative start date."""
    request = Request(
        CNN_FEAR_GREED_URL,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.cnn.com",
            "Referer": "https://www.cnn.com/",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    frame = parse_cnn_fear_greed(payload)
    if end_date is not None:
        end = pd.Timestamp(end_date).normalize()
        frame = frame.loc[frame.index <= end].copy()
    if frame.empty:
        raise ValueError("CNN Fear & Greed history is empty after clipping")
    return frame
