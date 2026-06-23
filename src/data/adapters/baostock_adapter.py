from __future__ import annotations

import socket
from contextlib import contextmanager
from dataclasses import dataclass

import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

BAOSTOCK_SOCKET_TIMEOUT_SECONDS = 10.0


class _FailClosedSocket(socket.socket):
    """Turn a clean peer disconnect into an error instead of a busy loop."""

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        data = super().recv(bufsize, flags)
        if not data:
            raise ConnectionError("baostock server closed the connection")
        return data


@contextmanager
def _baostock_socket_guard(timeout_seconds: float = BAOSTOCK_SOCKET_TIMEOUT_SECONDS):
    """Bound the third-party client's unbounded connect/recv implementation."""
    import baostock.common.contants as constants  # type: ignore
    import baostock.common.context as context  # type: ignore
    import baostock.util.socketutil as socketutil  # type: ignore

    original_connect = socketutil.SocketUtil.connect

    def guarded_connect(_instance) -> None:
        sock = _FailClosedSocket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_seconds)
        try:
            sock.connect((constants.BAOSTOCK_SERVER_IP, constants.BAOSTOCK_SERVER_PORT))
        except Exception as exc:
            sock.close()
            setattr(context, "default_socket", None)
            raise DataFetchError(f"baostock connection failed: {exc}") from exc
        setattr(context, "default_socket", sock)

    socketutil.SocketUtil.connect = guarded_connect
    try:
        yield
    finally:
        socketutil.SocketUtil.connect = original_connect
        sock = getattr(context, "default_socket", None)
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if hasattr(context, "default_socket"):
            delattr(context, "default_socket")


def _to_baostock_code(symbol: str) -> str:
    """
    Convert 6-digit A-share code into baostock code: sh.600519 / sz.000001
    """
    symbol = str(symbol or "").strip()
    if not symbol:
        return ""
    if symbol.lower().startswith(("sh.", "sz.")):
        return symbol.lower()
    if symbol.startswith(("60", "68", "51", "50", "52", "56", "58", "90")):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


@dataclass
class BaoStockAdapter:
    _name: str = "baostock"

    @property
    def name(self) -> str:
        return self._name

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if market != "cn":
            raise DataFetchError("baostock adapter currently supports market=cn only")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")
        end = str(req.end or "").strip() if req.end else ""

        try:
            import baostock as bs  # type: ignore
        except Exception as e:
            raise DataFetchError(f"baostock import failed: {e}") from e

        code = _to_baostock_code(symbol)
        if not code:
            raise DataFetchError("invalid symbol")

        with _baostock_socket_guard():
            lg = bs.login()
            if getattr(lg, "error_code", "0") != "0":
                raise DataFetchError(
                    f"baostock login failed: {getattr(lg, 'error_msg', '')}"
                )

            try:
                fields = "date,open,high,low,close,volume,amount"
                rs = bs.query_history_k_data_plus(
                    code,
                    fields,
                    start_date=start,
                    end_date=end or None,
                    frequency="d",
                    adjustflag="3",
                )
                if getattr(rs, "error_code", "0") != "0":
                    raise DataFetchError(
                        f"baostock query failed: {getattr(rs, 'error_msg', '')}"
                    )

                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                df = pd.DataFrame(rows, columns=rs.fields if hasattr(rs, "fields") else None)
            finally:
                try:
                    bs.logout()
                except Exception:
                    pass

        if df is None or df.empty:
            raise DataFetchError(f"empty data for {code}")

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        if df.empty:
            raise DataFetchError(f"empty data for {code}")

        df["factor"] = 1.0
        out = df[["date", "open", "high", "low", "close", "volume", "amount", "factor"]].copy()
        out = out.dropna(subset=["date", "open", "high", "low", "close"]).reset_index(drop=True)
        if out.empty:
            raise DataFetchError(f"empty usable bars for {code}")

        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
        )
