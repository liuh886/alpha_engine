from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.data.adapters.base import DataFetchError, FetchRequest, FetchResult

# Small provider rounding drift is tolerated only inside this narrow envelope.
# Material raw OHLC inconsistencies still fail closed.
OHLC_ROUNDING_REL_TOL = 5e-4
CN_ETF_PRICE_TICK = 1e-3
CN_ETF_PREFIXES = ("15", "16", "51", "56", "58")
FLOAT_COMPARISON_EPSILON = 1e-12


def _get_yahoo_ticker(ticker: str, region: str) -> str:
    ticker = str(ticker).upper()
    region = str(region or "").lower().strip()
    if region == "cn":
        if ticker.endswith(".SS") or ticker.endswith(".SZ"):
            return ticker
        if ticker == "000300":
            return "000300.SS"
        if ticker.startswith(("60", "68", "51", "56", "58")):
            return f"{ticker}.SS"
        if ticker.startswith(("00", "30", "15", "16")):
            return f"{ticker}.SZ"
        return f"{ticker}.SS"
    if region == "hk":
        clean = ticker.replace(".HK", "")
        if len(clean) == 5 and clean.startswith("0"):
            clean = clean[1:]
        return f"{clean}.HK"
    return ticker


def _ohlc_absolute_tolerance(symbol: str, market: str) -> float:
    """Return the exchange price-tick bound used for Yahoo envelope repair."""

    clean = str(symbol).upper().split(".", maxsplit=1)[0]
    if str(market).lower().strip() == "cn" and clean.startswith(CN_ETF_PREFIXES):
        return CN_ETF_PRICE_TICK
    return 0.0


def _reconcile_ohlc_rounding(
    frame: pd.DataFrame,
    *,
    relative_tolerance: float = OHLC_ROUNDING_REL_TOL,
    absolute_tolerance: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Correct bounded provider-adjustment OHLC envelope drift with evidence."""

    result = frame.copy()
    required_high = result[["open", "close", "low"]].max(axis=1)
    required_low = result[["open", "close", "high"]].min(axis=1)
    high_gap = (required_high - result["high"]).clip(lower=0.0)
    low_gap = (result["low"] - required_low).clip(lower=0.0)
    high_scale = (
        pd.concat([required_high.abs(), result["high"].abs()], axis=1)
        .max(axis=1)
        .clip(lower=1.0)
    )
    low_scale = (
        pd.concat([required_low.abs(), result["low"].abs()], axis=1)
        .max(axis=1)
        .clip(lower=1.0)
    )
    high_relative = high_gap / high_scale
    low_relative = low_gap / low_scale
    max_relative = float(max(high_relative.max(), low_relative.max()))
    max_absolute = float(max(high_gap.max(), low_gap.max()))
    high_mask = high_gap > 0.0
    low_mask = low_gap > 0.0
    corrected_mask = high_mask | low_mask
    material_high = (
        high_mask
        & (high_relative > relative_tolerance)
        & (high_gap - absolute_tolerance > FLOAT_COMPARISON_EPSILON)
    )
    material_low = (
        low_mask
        & (low_relative > relative_tolerance)
        & (low_gap - absolute_tolerance > FLOAT_COMPARISON_EPSILON)
    )
    evidence = {
        "relative_tolerance": relative_tolerance,
        "absolute_tolerance": absolute_tolerance,
        "corrected_rows": int(corrected_mask.sum()),
        "corrected_high_rows": int(high_mask.sum()),
        "corrected_low_rows": int(low_mask.sum()),
        "max_relative_violation": max_relative,
        "max_absolute_violation": max_absolute,
    }
    if material_high.any() or material_low.any():
        raise DataFetchError(
            "material Yahoo OHLC envelope violation: "
            f"max_relative={max_relative:.12g} "
            f"> tolerance={relative_tolerance:.12g}; "
            f"max_absolute={max_absolute:.12g} "
            f"> tolerance={absolute_tolerance:.12g}"
        )
    result.loc[high_mask, "high"] = required_high.loc[high_mask]
    result.loc[low_mask, "low"] = required_low.loc[low_mask]
    result.attrs["ohlc_rounding_reconciliation"] = evidence
    return result, evidence


def _process_yfinance_df(
    df: pd.DataFrame,
    *,
    absolute_tolerance: float = 0.0,
) -> pd.DataFrame:
    """Normalize raw Yahoo bars and apply one uniform adjustment ratio.

    yfinance's maintained ``auto_adjust`` algorithm multiplies raw Open/High/Low
    by ``Adj Close / Close`` and uses Adj Close as Close. Perform that operation
    explicitly from un-repaired provider bars so Alpha Engine remains the sole
    authority for deterministic OHLC reconciliation and envelope validation.
    """

    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    if isinstance(result.columns, pd.MultiIndex):
        try:
            result.columns = result.columns.get_level_values(0)
        except Exception:
            pass
    result = result.reset_index()
    result.columns = [str(column).lower() for column in result.columns]
    required = ["date", "open", "high", "low", "close", "adj close", "volume"]
    if any(column not in result.columns for column in required):
        return pd.DataFrame()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "adj close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(
        subset=["date", "open", "high", "low", "close", "adj close"]
    ).copy()

    raw = result[["date", "open", "high", "low", "close", "volume"]].copy()
    raw, raw_evidence = _reconcile_ohlc_rounding(
        raw,
        absolute_tolerance=absolute_tolerance,
    )
    result.loc[:, ["open", "high", "low", "close", "volume"]] = raw[
        ["open", "high", "low", "close", "volume"]
    ].to_numpy()

    close = result["close"].to_numpy(dtype=float)
    adjusted_close = result["adj close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = adjusted_close / close
    if (
        not np.isfinite(ratio).all()
        or (close <= 0.0).any()
        or (adjusted_close <= 0.0).any()
        or (ratio <= 0.0).any()
    ):
        raise DataFetchError("Yahoo adjustment ratio is non-finite or non-positive")

    result["open"] = result["open"] * ratio
    result["high"] = result["high"] * ratio
    result["low"] = result["low"] * ratio
    result["close"] = result["adj close"]
    result["amount"] = result["close"] * result["volume"]
    result["factor"] = 1.0
    out = (
        result[["date", "open", "high", "low", "close", "volume", "amount", "factor"]]
        .sort_values("date")
        .reset_index(drop=True)
    )
    reconciled, adjusted_evidence = _reconcile_ohlc_rounding(
        out,
        absolute_tolerance=absolute_tolerance,
    )
    adjusted_evidence["adjustment_method"] = "uniform_adj_close_ratio"
    adjusted_evidence["adjustment_ratio_min"] = float(np.min(ratio))
    adjusted_evidence["adjustment_ratio_max"] = float(np.max(ratio))
    adjusted_evidence["raw_reconciliation"] = raw_evidence
    reconciled.attrs["ohlc_rounding_reconciliation"] = adjusted_evidence
    return reconciled


def _normalise_boundary(value: object, *, field_name: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(value).normalize()
    except Exception as exc:
        raise DataFetchError(f"invalid {field_name}: {value!r}") from exc


def _exclusive_provider_end(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    requested_end = _normalise_boundary(value, field_name="end")
    return (requested_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def _clip_to_request(frame: pd.DataFrame, *, start: str, end: str | None) -> pd.DataFrame:
    if frame.empty:
        return frame
    start_ts = _normalise_boundary(start, field_name="start")
    end_ts = _normalise_boundary(end, field_name="end") if end else None
    if end_ts is not None and end_ts < start_ts:
        raise DataFetchError("end must be on or after start")
    evidence = frame.attrs.get("ohlc_rounding_reconciliation")
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    dates = dates.dt.normalize()
    mask = dates >= start_ts
    if end_ts is not None:
        mask &= dates <= end_ts
    clipped = frame.loc[mask].copy()
    clipped["date"] = dates.loc[mask]
    clipped = clipped.sort_values("date").reset_index(drop=True)
    if evidence is not None:
        clipped.attrs["ohlc_rounding_reconciliation"] = evidence
    return clipped


@dataclass
class YFinanceAdapter:
    _name: str = "yfinance"

    @property
    def name(self) -> str:
        return self._name

    def provider_symbol(self, req: FetchRequest) -> str:
        return _get_yahoo_ticker(req.symbol, req.market)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        try:
            import yfinance as yf
        except Exception as exc:
            raise DataFetchError(f"yfinance import failed: {exc}") from exc
        symbol = str(req.symbol or "").strip()
        if not symbol:
            raise DataFetchError("symbol is required")
        market = str(req.market or "").strip().lower()
        if not market:
            raise DataFetchError("market is required")
        start = str(req.start or "").strip()
        if not start:
            raise DataFetchError("start is required")
        start_ts = _normalise_boundary(start, field_name="start")
        end_ts = _normalise_boundary(req.end, field_name="end") if req.end else None
        if end_ts is not None and end_ts < start_ts:
            raise DataFetchError("end must be on or after start")
        provider_end = _exclusive_provider_end(req.end)
        yf_ticker = self.provider_symbol(req)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*Timestamp.utcnow is deprecated.*")
                df = yf.download(
                    yf_ticker,
                    start=start,
                    end=provider_end,
                    progress=False,
                    auto_adjust=False,
                    repair=False,
                    threads=False,
                )
        except Exception as exc:
            raise DataFetchError(f"yfinance download failed for {yf_ticker}: {exc}") from exc
        out = _clip_to_request(
            _process_yfinance_df(
                df,
                absolute_tolerance=_ohlc_absolute_tolerance(symbol, market),
            ),
            start=start,
            end=req.end,
        )
        if out.empty:
            raise DataFetchError(f"empty data for {yf_ticker}")
        from src.data.validation.schema import validate_market_data

        valid, _, errors = validate_market_data(out, symbol)
        if not valid:
            raise DataFetchError(
                f"yfinance schema validation failed for {yf_ticker}: {'; '.join(errors)}"
            )
        return FetchResult(
            provider=self.name,
            symbol=symbol,
            market=market,
            start=start,
            end=req.end,
            df=out,
            provider_symbol=yf_ticker,
        )
