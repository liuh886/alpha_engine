from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.data.adapters.base import DataFetchError
from src.data.adapters.polygon_intraday_adapter import (
    PolygonIntradayAdapter,
    PolygonIntradayRequest,
)


@dataclass(frozen=True)
class IntradayPreflightResult:
    bars: dict[str, pd.DataFrame]
    source_coverage: pd.DataFrame
    opening_alignment: pd.DataFrame
    state2_population: pd.DataFrame
    gate: dict[str, Any]


def fetch_intraday_bars(
    contract: Mapping[str, Any],
    *,
    adapter: PolygonIntradayAdapter | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    specification = contract["intraday_data"]
    resolved = adapter or PolygonIntradayAdapter()
    bars: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []
    inter_symbol_delay = float(
        specification.get("inter_symbol_delay_seconds", 0.0)
    )
    for position, raw_symbol in enumerate(specification["symbols"]):
        symbol = str(raw_symbol).upper()
        if position > 0 and inter_symbol_delay > 0.0:
            time.sleep(inter_symbol_delay)
        try:
            result = resolved.fetch_aggregate_bars(
                PolygonIntradayRequest(
                    symbol=symbol,
                    market="us",
                    start=str(specification["start_date"]),
                    end=str(specification["end_date"]),
                    multiplier=int(specification["multiplier"]),
                    timespan=str(specification["timespan"]),
                    adjusted=bool(specification["adjusted"]),
                    regular_session_only=bool(
                        specification["regular_session_only"]
                    ),
                    maximum_results=int(specification["maximum_results"]),
                    max_pages=int(specification.get("max_pages", 10)),
                    request_delay_seconds=float(
                        specification.get("request_delay_seconds", 0.0)
                    ),
                )
            )
            frame = result.df.copy()
            bars[symbol] = frame
            metadata = dict(frame.attrs.get("provider_metadata", {}))
            pagination_complete = bool(
                metadata.get("pagination_completed", False)
            )
            require_complete = bool(
                specification.get("require_complete_pagination", True)
            )
            rows.append(
                {
                    "symbol": symbol,
                    "provider": result.provider,
                    "provider_symbol": result.provider_symbol,
                    "identity_source": metadata.get("identity_source"),
                    "first_timestamp_utc": frame["timestamp_utc"].min(),
                    "last_timestamp_utc": frame["timestamp_utc"].max(),
                    "first_session": frame["session_date"].min(),
                    "last_session": frame["session_date"].max(),
                    "rows": int(len(frame)),
                    "sessions": int(frame["session_date"].nunique()),
                    "raw_results_count": metadata.get("raw_results_count"),
                    "pages": metadata.get("pages"),
                    "pagination_used": metadata.get("pagination_used"),
                    "pagination_completed": pagination_complete,
                    "duplicate_timestamps": bool(
                        frame["timestamp_utc"].duplicated().any()
                    ),
                    "positive_finite_ohlcv": bool(
                        np.isfinite(
                            frame[["open", "high", "low", "close", "volume"]]
                            .to_numpy(dtype=float)
                        ).all()
                        and frame[["open", "high", "low", "close", "volume"]]
                        .gt(0.0)
                        .all()
                        .all()
                    ),
                    "fetch_error": None,
                    "admissible": pagination_complete or not require_complete,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "symbol": symbol,
                    "provider": "polygon_intraday",
                    "provider_symbol": symbol,
                    "identity_source": None,
                    "first_timestamp_utc": None,
                    "last_timestamp_utc": None,
                    "first_session": None,
                    "last_session": None,
                    "rows": 0,
                    "sessions": 0,
                    "raw_results_count": None,
                    "pages": None,
                    "pagination_used": None,
                    "pagination_completed": False,
                    "duplicate_timestamps": None,
                    "positive_finite_ohlcv": False,
                    "fetch_error": f"{type(exc).__name__}: {exc}",
                    "admissible": False,
                }
            )
    return bars, pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


def _opening_table(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    local_minutes = (
        frame["timestamp_et"].dt.hour * 60
        + frame["timestamp_et"].dt.minute
    )
    opening = frame.loc[local_minutes.eq(9 * 60 + 30)].copy()
    if opening["session_date"].duplicated().any():
        raise DataFetchError(f"duplicate opening bars for {symbol}")
    closing = (
        frame.sort_values("timestamp_et")
        .groupby("session_date", as_index=False)
        .tail(1)
        .set_index("session_date")["close"]
        .rename("regular_close")
    )
    opening = opening.set_index("session_date").sort_index()
    opening[f"{symbol}_open"] = opening["open"]
    opening[f"{symbol}_opening_close"] = opening["close"]
    opening[f"{symbol}_opening_high"] = opening["high"]
    opening[f"{symbol}_opening_low"] = opening["low"]
    opening[f"{symbol}_opening_volume"] = opening["volume"]
    opening[f"{symbol}_regular_close"] = closing.reindex(opening.index)
    opening[f"{symbol}_previous_regular_close"] = closing.shift(1).reindex(
        opening.index
    )
    opening[f"{symbol}_next_open"] = opening[f"{symbol}_open"].shift(-1)
    columns = [
        f"{symbol}_open",
        f"{symbol}_opening_close",
        f"{symbol}_opening_high",
        f"{symbol}_opening_low",
        f"{symbol}_opening_volume",
        f"{symbol}_regular_close",
        f"{symbol}_previous_regular_close",
        f"{symbol}_next_open",
    ]
    return opening[columns]


def build_opening_alignment(
    bars: Mapping[str, pd.DataFrame],
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    required = [
        str(value).upper() for value in contract["intraday_data"]["symbols"]
    ]
    missing = [symbol for symbol in required if symbol not in bars]
    if missing:
        return pd.DataFrame()
    tables = [_opening_table(bars[symbol], symbol) for symbol in required]
    aligned = tables[0]
    for table in tables[1:]:
        aligned = aligned.join(table, how="outer")
    aligned.index = pd.DatetimeIndex(aligned.index).tz_localize(None).normalize()
    aligned.index.name = "session_date"
    aligned = aligned.sort_index()
    for symbol in required:
        aligned[f"{symbol}_opening_present"] = aligned[
            f"{symbol}_open"
        ].notna()
        aligned[f"{symbol}_next_open_present"] = aligned[
            f"{symbol}_next_open"
        ].notna()
    aligned["all_openings_present"] = aligned[
        [f"{symbol}_opening_present" for symbol in required]
    ].all(axis=1)
    aligned["all_next_opens_present"] = aligned[
        [f"{symbol}_next_open_present" for symbol in required]
    ].all(axis=1)
    aligned["usable_session"] = (
        aligned["all_openings_present"] & aligned["all_next_opens_present"]
    )
    return aligned


def _state2_rows(
    baseline: pd.DataFrame,
    alignment: pd.DataFrame,
    *,
    sample: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    if alignment.empty:
        return pd.DataFrame()
    index = baseline.index.intersection(alignment.index)
    index = index[
        (index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))
    ]
    state = baseline["position_state"].reindex(index)
    usable = alignment["usable_session"].reindex(index).fillna(False)
    selected = index[state.eq(2) & usable]
    if len(selected) == 0:
        return pd.DataFrame()
    output = pd.DataFrame(
        {
            "session_date": selected,
            "sample": sample,
            "position_state": 2,
            "weight_QQQI": baseline["weight_QQQI"].reindex(selected).to_numpy(),
            "weight_QQQ": baseline["weight_QQQ"].reindex(selected).to_numpy(),
            "weight_TQQQ": baseline["weight_TQQQ"].reindex(selected).to_numpy(),
            "baseline_net_return": baseline["net_return"].reindex(selected).to_numpy(),
            "opening_and_next_open_usable": True,
        }
    )
    return output


def audit_phase0(
    bars: Mapping[str, pd.DataFrame],
    source_coverage: pd.DataFrame,
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> IntradayPreflightResult:
    alignment = build_opening_alignment(bars, contract)
    phase = contract["phase_0"]
    development = _state2_rows(
        proxy_baseline_daily,
        alignment,
        sample="development_proxy",
        start=str(phase["development_start"]),
        end=str(phase["development_end"]),
    )
    quarantine = _state2_rows(
        actual_baseline_daily,
        alignment,
        sample="quarantine_actual",
        start=str(phase["quarantine_start"]),
        end=str(contract["intraday_data"]["end_date"]),
    )
    population = (
        pd.concat(
            [frame for frame in (development, quarantine) if not frame.empty],
            ignore_index=True,
        )
        if (not development.empty or not quarantine.empty)
        else pd.DataFrame()
    )

    required_symbols = [
        str(value).upper() for value in contract["intraday_data"]["symbols"]
    ]
    sources_admissible = bool(
        len(source_coverage) == len(required_symbols)
        and source_coverage["admissible"].fillna(False).all()
    )
    pagination_complete = bool(
        len(source_coverage) == len(required_symbols)
        and source_coverage["pagination_completed"].fillna(False).all()
    )
    development_start = pd.Timestamp(phase["development_start"])
    development_end = pd.Timestamp(phase["development_end"])
    development_alignment = (
        alignment.loc[
            (alignment.index >= development_start)
            & (alignment.index <= development_end)
        ]
        if not alignment.empty
        else pd.DataFrame()
    )
    missing_rate = (
        float(1.0 - development_alignment["all_openings_present"].mean())
        if not development_alignment.empty
        else 1.0
    )
    complete_years = 0
    if not development_alignment.empty:
        for _, year_frame in development_alignment.groupby(
            development_alignment.index.year
        ):
            if len(year_frame) >= 200 and float(
                year_frame["all_openings_present"].mean()
            ) >= 1.0 - float(phase["maximum_missing_opening_bar_rate"]):
                complete_years += 1
    state2_weights_valid = True
    if not population.empty:
        state2_weights_valid = bool(
            np.allclose(population["weight_QQQI"], 0.0)
            and np.allclose(population["weight_QQQ"], 0.25)
            and np.allclose(population["weight_TQQQ"], 0.75)
        )
    checks = {
        "sources_admissible": sources_admissible,
        "complete_pagination": pagination_complete,
        "opening_bar_missing_rate": missing_rate
        <= float(phase["maximum_missing_opening_bar_rate"]),
        "complete_development_years": complete_years
        >= int(phase["minimum_complete_development_years"]),
        "development_state2_sessions": len(development)
        >= int(phase["minimum_development_state2_sessions"]),
        "quarantine_state2_sessions": len(quarantine)
        >= int(phase["minimum_quarantine_state2_sessions"]),
        "state2_weights_match_contract": state2_weights_valid,
        "next_open_available": bool(
            not alignment.empty
            and alignment.loc[
                alignment["all_openings_present"], "all_next_opens_present"
            ].mean()
            >= 1.0 - float(phase["maximum_missing_opening_bar_rate"])
        ),
    }
    gate = {
        "checks": checks,
        "metrics": {
            "opening_bar_missing_rate": missing_rate,
            "complete_development_years": int(complete_years),
            "development_state2_sessions": int(len(development)),
            "quarantine_state2_sessions": int(len(quarantine)),
            "aligned_sessions": int(len(alignment)),
            "usable_aligned_sessions": int(
                alignment["usable_session"].sum()
            )
            if not alignment.empty
            else 0,
            "total_pages": int(
                pd.to_numeric(source_coverage["pages"], errors="coerce")
                .fillna(0)
                .sum()
            )
            if not source_coverage.empty
            else 0,
        },
        "passed": bool(all(checks.values())),
    }
    return IntradayPreflightResult(
        bars=dict(bars),
        source_coverage=source_coverage,
        opening_alignment=alignment,
        state2_population=population,
        gate=gate,
    )
