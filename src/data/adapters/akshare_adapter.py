from __future__ import annotations

import hashlib
import socket
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.data.adapters.base import (
    DataFetchError,
    FetchRequest,
    FetchResult,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
    ProviderUnavailableError,
)
from src.data.provider_retry import RetryPolicy, call_with_retry

_INDEX_PROVIDER_SYMBOLS = {
    "000300": "sh000300",
    "399006": "sz399006",
}
# CN exchange-traded funds are not A-share equities. The stock endpoint
# (``stock_zh_a_hist``) does not serve them reliably, so ETF/fund codes route to
# the Eastmoney fund endpoint. Prefixes mirror the governed CN ETF classes:
# 15/16 are Shenzhen ETFs/LOFs, 51/56/58 are Shanghai ETFs (515180 is a 51).
_CN_ETF_PREFIXES = ("15", "16", "51", "56", "58")
_EASTMONEY_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}
_BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]
_FUND_SOURCE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_FUND_SOURCE_SCHEMA = "date,open,high,low,close,volume,amount"
# Bounded transport retry for the CN fund endpoint. The endpoint intermittently
# drops connections (RemoteDisconnected); three attempts with jittered
# exponential backoff are enough to absorb a transient reset without turning a
# real outage into a long stall. A Retry-After above 30 seconds is not honored:
# the adapter fails closed and the router can move to the independent Sina fund
# transport instead of sleeping through a provider quota window.
_FUND_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay_seconds=0.5,
    max_delay_seconds=8.0,
    max_honored_retry_after_seconds=30.0,
    jitter_ratio=0.25,
)
_TRANSIENT_EXCEPTION_NAMES = frozenset(
    {
        "ConnectionError",
        "ConnectTimeout",
        "ConnectionResetError",
        "MaxRetryError",
        "NewConnectionError",
        "ProtocolError",
        "ProxyError",
        "ReadTimeout",
        "ReadTimeoutError",
        "RemoteDisconnected",
        "Timeout",
        "TimeoutError",
    }
)
_NON_TRANSIENT_EXCEPTION_NAMES = frozenset(
    {
        "ContentDecodingError",
        "InvalidJSONError",
        "JSONDecodeError",
        "SSLError",
    }
)


def _to_yyyymmdd(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    return value.replace("-", "")


def _normalize_index_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Normalize unadjusted index OHLCV without inventing turnover amount."""
    required = ("date", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DataFetchError(f"akshare index payload missing columns for {symbol}: {missing}")

    out = frame[list(required)].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    out = out.loc[out["date"].between(start_ts, end_ts, inclusive="both")].copy()
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable index bars for {symbol}")

    # The selected AKShare index endpoint exposes volume but not turnover
    # amount. Its volume is already an index-specific provider quantity, so it
    # is retained and explicitly separated from equity share volume.
    out["amount"] = np.nan
    out["factor"] = 1.0
    return out[_BAR_COLUMNS]


def is_cn_etf(symbol: str) -> bool:
    """Return whether ``symbol`` is a CN ETF/fund rather than an A-share stock."""

    return str(symbol or "").strip().upper().startswith(_CN_ETF_PREFIXES)


# Backwards-compatible private alias for in-module callers/tests.
_is_cn_etf = is_cn_etf


def _normalize_eastmoney_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str,
    label: str,
) -> pd.DataFrame:
    """Normalize an Eastmoney daily payload with the governed QFQ contract.

    Both the stock and fund endpoints expose the same Chinese schema and report
    volume in lots (手). The canonical Alpha Engine unit is shares and turnover
    is already CNY. Bars are sorted, deduplicated, windowed, and rejected when
    OHLC is non-finite or non-positive; no fill or interpolation is applied.
    """

    if frame is None or frame.empty:
        raise DataFetchError(f"empty {label} data for {symbol}")

    missing = [column for column in _EASTMONEY_COLUMN_MAP if column not in frame.columns]
    if missing:
        raise DataFetchError(
            f"akshare {label} payload missing columns for {symbol}: {missing}"
        )

    out = frame[list(_EASTMONEY_COLUMN_MAP)].rename(columns=_EASTMONEY_COLUMN_MAP).copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    # AKShare/Eastmoney reports volume in lots (手); the canonical unit is shares.
    out["volume"] = out["volume"] * 100.0

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    out = out.loc[out["date"].between(start_ts, end_ts, inclusive="both")].copy()
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise DataFetchError(f"empty usable {label} bars for {symbol}")

    prices = out[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise DataFetchError(
            f"akshare {label} payload contains non-finite or non-positive OHLC "
            f"for {symbol}"
        )

    out["factor"] = 1.0
    return out[_BAR_COLUMNS]


def _frame_content_hash(frame: pd.DataFrame) -> tuple[str, int]:
    """Return a deterministic content hash and byte length for provenance."""

    payload = frame.copy()
    payload["date"] = pd.to_datetime(payload["date"]).dt.strftime("%Y-%m-%d")
    text = payload.to_csv(index=False, lineterminator="\n")
    encoded = text.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def _retry_after_seconds(headers: Any) -> float | None:
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After")
    except Exception:
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0.0 else None


def _translate_fund_transport_error(exc: BaseException) -> BaseException:
    """Map requests/urllib transport failures to retryable provider errors.

    Schema and payload-decoding failures are deliberately returned unchanged so
    ``call_with_retry`` fails immediately instead of masking a data defect with
    another attempt or a different vendor.
    """

    if isinstance(exc, ProviderTransientError):
        return exc
    name = type(exc).__name__
    if name in _NON_TRANSIENT_EXCEPTION_NAMES:
        return exc
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = _retry_after_seconds(exc.headers)
        if exc.code == 429:
            return ProviderRateLimitError(
                f"Eastmoney fund endpoint rate limited: HTTP {exc.code}",
                retry_after_seconds=retry_after,
            )
        if 500 <= int(exc.code) < 600:
            return ProviderUnavailableError(
                f"Eastmoney fund endpoint upstream error: HTTP {exc.code}",
                retry_after_seconds=retry_after,
            )
        return exc

    # requests wraps HTTP status details in ``response`` and raises
    # HTTPError; urllib3 raises ProtocolError/ReadTimeoutError. Classify by
    # name and status, never by message text.
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is None:
        status = getattr(response, "status", None)
    if status is not None:
        headers = getattr(response, "headers", None)
        retry_after = _retry_after_seconds(headers)
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            status_code = 0
        if status_code == 429:
            return ProviderRateLimitError(
                f"Eastmoney fund endpoint rate limited: HTTP {status_code}",
                retry_after_seconds=retry_after,
            )
        if 500 <= status_code < 600:
            return ProviderUnavailableError(
                f"Eastmoney fund endpoint upstream error: HTTP {status_code}",
                retry_after_seconds=retry_after,
            )
        if 400 <= status_code < 500:
            return exc

    if isinstance(exc, (TimeoutError, socket.timeout)) or name in {
        "Timeout",
        "TimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
    }:
        return ProviderTimeoutError(f"Eastmoney fund endpoint timed out: {exc}")
    if isinstance(exc, ConnectionError) or name in _TRANSIENT_EXCEPTION_NAMES:
        return ProviderUnavailableError(f"Eastmoney fund endpoint network failure: {exc}")
    module = type(exc).__module__ or ""
    if module.startswith(("urllib3", "http.client")):
        # Unknown low-level transport failure: treat as transient. Payload and
        # schema exceptions are excluded above by name. Unrecognized requests
        # exceptions (for example configuration errors) are left unchanged and
        # therefore not retried.
        return ProviderUnavailableError(f"Eastmoney fund endpoint transport failure: {exc}")
    return exc


def _fund_provenance(
    frame: pd.DataFrame,
    *,
    provider_symbol: str,
    start: str,
    end: str | None,
    retry_evidence: dict[str, Any],
    source_schema: str,
    content_hash: str,
    content_bytes: int,
) -> dict[str, Any]:
    return {
        "amount_basis": "CNY",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "first_date": pd.Timestamp(frame["date"].min()).strftime("%Y-%m-%d"),
        "last_date": pd.Timestamp(frame["date"].max()).strftime("%Y-%m-%d"),
        "price_basis": "qfq_adjusted",
        "provider": "akshare",
        "provider_symbol": provider_symbol,
        "requested_end": str(end) if end else None,
        "requested_start": str(start),
        "research_only": True,
        "response_bytes": int(content_bytes),
        "response_sha256": content_hash,
        "retry_attempts": int(retry_evidence.get("retry_attempts", 1)),
        "retry_history": list(retry_evidence.get("retry_history", [])),
        "retry_outcome": str(retry_evidence.get("retry_outcome", "succeeded")),
        "retry_policy": dict(retry_evidence.get("retry_policy", {})),
        "rows": int(len(frame)),
        "source_date_format": "provider_date_string",
        "source_schema": source_schema,
        "source_url": _FUND_SOURCE_URL,
        "terms_caveat": (
            "Eastmoney fund endpoint reports volume in lots; the adapter converts "
            "lots to canonical shares. Amount is provider-reported CNY."
        ),
        "trade_ready": False,
        "volume_basis": "shares",
    }


@dataclass
class AkShareAdapter:
    _name: str = "akshare"
    # Injectable for tests; production uses the bounded fund-endpoint policy.
    fund_retry_policy: RetryPolicy | None = field(default=None)

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if market != "cn":
            raise DataFetchError("akshare adapter currently supports market=cn only")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")

        try:
            import akshare as ak  # type: ignore
        except Exception as exc:
            raise DataFetchError(f"akshare import failed: {exc}") from exc

        beg = _to_yyyymmdd(start)
        end = _to_yyyymmdd(str(req.end)) if req.end else "20500101"
        if not beg:
            raise DataFetchError("invalid start date")

        provider_symbol = symbol
        provenance: dict[str, Any] | None = None
        try:
            if symbol in _INDEX_PROVIDER_SYMBOLS:
                provider_symbol = _INDEX_PROVIDER_SYMBOLS[symbol]
                frame = ak.stock_zh_index_daily(symbol=provider_symbol)
                out = _normalize_index_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                )
            elif _is_cn_etf(symbol):
                # CN ETFs are not served reliably by the A-share stock endpoint.
                # Route them to the Eastmoney fund endpoint with the same
                # forward-adjusted contract used for stocks. The request is
                # wrapped in a bounded transport retry; schema/data failures are
                # never retried.
                retry_evidence: dict[str, Any] = {}
                policy = self.fund_retry_policy or _FUND_RETRY_POLICY

                def _fetch_fund() -> pd.DataFrame:
                    try:
                        return ak.fund_etf_hist_em(
                            symbol=symbol,
                            period="daily",
                            start_date=beg,
                            end_date=end,
                            adjust="qfq",
                        )
                    except Exception as exc:  # noqa: BLE001 - provider boundary
                        translated = _translate_fund_transport_error(exc)
                        if translated is exc:
                            raise
                        raise translated from exc

                try:
                    outcome = call_with_retry(
                        _fetch_fund,
                        policy=policy,
                        evidence=retry_evidence,
                        label=f"Eastmoney fund endpoint {symbol}",
                    )
                except Exception as exc:  # noqa: BLE001 - preserve typed failure
                    if retry_evidence:
                        raise DataFetchError(
                            "akshare fund endpoint failed for "
                            f"{symbol} after "
                            f"{retry_evidence.get('retry_attempts', '?')} attempt(s) "
                            f"({retry_evidence.get('retry_outcome', 'unknown')}): {exc}"
                        ) from exc
                    raise
                frame = outcome.value
                out = _normalize_eastmoney_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                    label="fund",
                )
                content_hash, content_bytes = _frame_content_hash(out)
                provenance = _fund_provenance(
                    out,
                    provider_symbol=provider_symbol,
                    start=start,
                    end=req.end,
                    retry_evidence=retry_evidence,
                    source_schema=_FUND_SOURCE_SCHEMA,
                    content_hash=content_hash,
                    content_bytes=content_bytes,
                )
            else:
                frame = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=beg,
                    end_date=end,
                    adjust="qfq",
                )
                out = _normalize_eastmoney_frame(
                    frame,
                    symbol=symbol,
                    start=beg,
                    end=end,
                    label="stock",
                )
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(f"akshare fetch failed for {provider_symbol}: {exc}") from exc

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
            provider_symbol=provider_symbol,
            provenance=provenance,
        )
