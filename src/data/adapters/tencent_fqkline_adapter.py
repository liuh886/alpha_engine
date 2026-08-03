from __future__ import annotations

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


@dataclass
class TencentFqKlineAdapter:
    """Fetch overlap and completed qfq daily rows from Tencent Finance."""

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
        if start not in dates or end not in dates:
            raise DataFetchError(
                f"Tencent fqkline must contain exact overlap/current dates for "
                f"{provider_symbol}: requested={start},{end} available={sorted(dates)}"
            )
        frame = frame.loc[frame["date"].astype(str).isin({start, end})].copy()
        if len(frame) != 2:
            raise DataFetchError(
                f"Tencent fqkline overlap/current rows are not unique: {provider_symbol}"
            )
        for row in frame.to_dict(orient="records"):
            prices = [float(row[key]) for key in ("open", "high", "low", "close")]
            if min(prices) <= 0:
                raise DataFetchError(f"Tencent fqkline contains non-positive price: {provider_symbol}")
            if float(row["high"]) < max(float(row["open"]), float(row["close"])):
                raise DataFetchError(f"Tencent fqkline violates high envelope: {provider_symbol}")
            if float(row["low"]) > min(float(row["open"]), float(row["close"])):
                raise DataFetchError(f"Tencent fqkline violates low envelope: {provider_symbol}")
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=end,
            df=frame[_BAR_COLUMNS],
            provider_symbol=provider_symbol,
        )
