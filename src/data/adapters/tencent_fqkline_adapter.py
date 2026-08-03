from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.data.adapters.akshare_sina_adapter import _provider_symbol
from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MARKET_FINAL_TIME = time(15, 5)
_QUOTE_PATTERN = re.compile(r'^v_[^=]+="(?P<payload>.*)";?$')


def _completed_session_guard(cutoff: str, *, now: datetime | None = None) -> None:
    observed = now.astimezone(_SHANGHAI) if now is not None else datetime.now(_SHANGHAI)
    if observed.date().isoformat() == cutoff and observed.time() < _MARKET_FINAL_TIME:
        raise DataFetchError(
            f"Tencent daily bar cannot be accepted before {_MARKET_FINAL_TIME.isoformat()} "
            f"Asia/Shanghai for {cutoff}"
        )


def _parse_rows(payload: object, provider_symbol: str) -> list[list[object]]:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise DataFetchError(f"Tencent fqkline response is invalid for {provider_symbol}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise DataFetchError(f"Tencent fqkline data is missing for {provider_symbol}")
    instrument = data.get(provider_symbol)
    if not isinstance(instrument, dict):
        raise DataFetchError(f"Tencent fqkline instrument is missing: {provider_symbol}")
    rows = instrument.get("qfqday") or instrument.get("day")
    if not isinstance(rows, list):
        raise DataFetchError(f"Tencent fqkline rows are missing: {provider_symbol}")
    return [row for row in rows if isinstance(row, list)]


def _fetch_rows(provider_symbol: str, start: str, end: str) -> pd.DataFrame:
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{provider_symbol},day,{start},{end},10,qfq"}
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "alpha-engine-research/1.0"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise DataFetchError(
            f"Tencent fqkline request failed for {provider_symbol}: {exc}"
        ) from exc
    records: list[dict[str, object]] = []
    for row in _parse_rows(payload, provider_symbol):
        if len(row) < 6:
            raise DataFetchError(f"Tencent fqkline row is incomplete: {provider_symbol}")
        try:
            records.append(
                {
                    "date": str(row[0]),
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                    "amount": float("nan"),
                    "factor": 1.0,
                }
            )
        except (TypeError, ValueError) as exc:
            raise DataFetchError(
                f"Tencent fqkline row contains invalid values: {provider_symbol}"
            ) from exc
    frame = pd.DataFrame(records, columns=_BAR_COLUMNS)
    if frame.empty:
        raise DataFetchError(f"Tencent fqkline returned no rows: {provider_symbol}")
    return frame


def _fetch_completed_quote(provider_symbol: str, cutoff: str) -> dict[str, float | str]:
    url = f"https://qt.gtimg.cn/q={provider_symbol}"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "alpha-engine-research/1.0"},
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        raise DataFetchError(
            f"Tencent quote request failed for {provider_symbol}: {exc}"
        ) from exc
    text = response.content.decode("gbk", errors="replace").strip()
    match = _QUOTE_PATTERN.match(text)
    if not match:
        raise DataFetchError(f"invalid Tencent quote envelope for {provider_symbol}")
    fields = match.group("payload").split("~")
    if len(fields) < 38:
        raise DataFetchError(
            f"incomplete Tencent quote for {provider_symbol}: field_count={len(fields)}"
        )
    stamp = fields[30].strip()
    if len(stamp) < 14 or stamp[:8] != cutoff.replace("-", "") or stamp[8:14] < "150000":
        raise DataFetchError(
            f"Tencent quote is not a completed {cutoff} session for {provider_symbol}: "
            f"timestamp={stamp!r}"
        )
    try:
        result: dict[str, float | str] = {
            "date": cutoff,
            "close": float(fields[3]),
            "previous_close": float(fields[4]),
            "open": float(fields[5]),
            "volume": float(fields[6]),
            "high": float(fields[33]),
            "low": float(fields[34]),
            "amount": float(fields[37]),
            "timestamp": stamp,
        }
    except (TypeError, ValueError, IndexError) as exc:
        raise DataFetchError(f"invalid Tencent quote values for {provider_symbol}") from exc
    prices = [float(result[key]) for key in ("open", "high", "low", "close", "previous_close")]
    if min(prices) <= 0:
        raise DataFetchError(f"Tencent quote contains non-positive price: {provider_symbol}")
    if float(result["high"]) < max(float(result["open"]), float(result["close"])):
        raise DataFetchError(f"Tencent quote violates high envelope: {provider_symbol}")
    if float(result["low"]) > min(float(result["open"]), float(result["close"])):
        raise DataFetchError(f"Tencent quote violates low envelope: {provider_symbol}")
    return result


def _append_quote_on_qfq_scale(
    frame: pd.DataFrame,
    *,
    provider_symbol: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    overlap = frame.loc[frame["date"].astype(str) == start]
    if len(overlap) != 1:
        raise DataFetchError(f"Tencent qfq overlap is not unique: {provider_symbol}")
    quote = _fetch_completed_quote(provider_symbol, end)
    previous_close = float(quote["previous_close"])
    qfq_close = float(overlap.iloc[0]["close"])
    ratio = qfq_close / previous_close
    if not 0 < ratio < 1000:
        raise DataFetchError(f"Tencent quote/qfq scale is invalid: {provider_symbol}")
    current = {
        "date": end,
        "open": float(quote["open"]) * ratio,
        "high": float(quote["high"]) * ratio,
        "low": float(quote["low"]) * ratio,
        "close": float(quote["close"]) * ratio,
        "volume": float(quote["volume"]),
        "amount": float(quote["amount"]),
        "factor": 1.0,
    }
    return pd.concat([overlap[_BAR_COLUMNS], pd.DataFrame([current])], ignore_index=True)


@dataclass
class TencentFqKlineAdapter:
    """Fetch qfq overlap and a completed current daily row from Tencent Finance."""

    _name: str = "tencent_fqkline"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip().upper()
        market = str(req.market or "").strip().lower()
        start = str(req.start or "").strip()
        end = str(req.end or "").strip()
        if not symbol or market != "cn" or not start or not end:
            raise DataFetchError("Tencent fqkline requires CN symbol, start and end")
        _completed_session_guard(end)
        provider_symbol = _provider_symbol(symbol)
        frame = _fetch_rows(provider_symbol, start, end)
        dates = set(frame["date"].astype(str))
        if start not in dates:
            raise DataFetchError(
                f"Tencent fqkline must contain overlap date for {provider_symbol}: "
                f"requested={start} available={sorted(dates)}"
            )
        if end not in dates:
            frame = _append_quote_on_qfq_scale(
                frame,
                provider_symbol=provider_symbol,
                start=start,
                end=end,
            )
        else:
            frame = frame.loc[frame["date"].astype(str).isin({start, end})].copy()
        if len(frame) != 2 or set(frame["date"].astype(str)) != {start, end}:
            raise DataFetchError(
                f"Tencent overlap/current rows are not exact: {provider_symbol}"
            )
        for row in frame.to_dict(orient="records"):
            prices = [float(row[key]) for key in ("open", "high", "low", "close")]
            if min(prices) <= 0:
                raise DataFetchError(f"Tencent rows contain non-positive price: {provider_symbol}")
            if float(row["high"]) < max(float(row["open"]), float(row["close"])):
                raise DataFetchError(f"Tencent rows violate high envelope: {provider_symbol}")
            if float(row["low"]) > min(float(row["open"]), float(row["close"])):
                raise DataFetchError(f"Tencent rows violate low envelope: {provider_symbol}")
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=end,
            df=frame[_BAR_COLUMNS],
            provider_symbol=provider_symbol,
        )
