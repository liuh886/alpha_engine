"""Independent unadjusted 515180 audit-source retrieval."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd


def normalise_etf_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Accept the documented Eastmoney Chinese or Sina English schema."""

    chinese = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
    }
    english = {column: column for column in ("date", "open", "high", "low", "close", "volume")}
    if set(chinese).issubset(frame.columns):
        out = frame[list(chinese)].rename(columns=chinese).copy()
    elif set(english).issubset(frame.columns):
        out = frame[list(english)].copy()
    else:
        raise RuntimeError(
            "ETF history missing supported OHLCV schema: "
            + ", ".join(map(str, frame.columns))
        )
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="raise")
    return out.sort_values("date").drop_duplicates("date", keep="last")


def fetch_secondary_v2(
    start: str,
    cutoff: str,
    retries: int,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    import akshare as ak

    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max(1, retries) + 1):
        try:
            frame = ak.fund_etf_hist_em(
                symbol="515180",
                period="daily",
                start_date=start.replace("-", ""),
                end_date=cutoff.replace("-", ""),
                adjust="",
            )
            if frame is None or frame.empty:
                raise RuntimeError("empty Eastmoney ETF history")
            out = normalise_etf_history(frame)
            attempts.append(
                {
                    "provider": "akshare_eastmoney_unadjusted",
                    "attempt": attempt,
                    "status": "success",
                    "rows": int(len(out)),
                }
            )
            return out, {
                "provider": "akshare_eastmoney_unadjusted",
                "provider_symbol": "515180",
                "volume_semantics": "provider_reported_audit_only",
                "attempts": attempts,
            }
        except Exception as exc:
            attempts.append(
                {
                    "provider": "akshare_eastmoney_unadjusted",
                    "attempt": attempt,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            time.sleep(float(attempt))

    try:
        frame = ak.fund_etf_hist_sina(symbol="sh515180")
        if frame is None or frame.empty:
            raise RuntimeError("empty Sina ETF history")
        out = normalise_etf_history(frame)
        out = out.loc[
            out["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))
        ].copy()
        attempts.append(
            {
                "provider": "akshare_sina_unadjusted",
                "attempt": 1,
                "status": "success",
                "rows": int(len(out)),
            }
        )
        return out, {
            "provider": "akshare_sina_unadjusted",
            "provider_symbol": "sh515180",
            "volume_semantics": "provider_reported_lots_audit_only",
            "attempts": attempts,
        }
    except Exception as exc:
        attempts.append(
            {
                "provider": "akshare_sina_unadjusted",
                "attempt": 1,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return None, {
            "provider": "secondary_unavailable",
            "attempts": attempts,
            "status": "unavailable",
        }
