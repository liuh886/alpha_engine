from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.assistant.data_snapshot import build_data_snapshot_id, read_latest_calendar_day


@dataclass(frozen=True)
class MarketQuality:
    market: str
    instruments: int
    instrument_end_max: str | None
    instrument_end_min: str | None
    stale_instruments: int
    stale_symbols_sample: list[str]
    stale_details_sample: list[dict[str, Any]]
    csv_missing: int
    csv_parse_errors: int
    csv_end_max: str | None
    csv_end_min: str | None
    csv_stale: int
    csv_stale_symbols_sample: list[str]


def _parse_instruments_file(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rows.append(
            {
                "symbol": parts[0].strip(),
                "start": parts[1].strip(),
                "end": parts[2].strip(),
            }
        )
    return rows


def _safe_max(values: list[str]) -> str | None:
    values = [str(value) for value in values if str(value).strip()]
    return max(values) if values else None


def _safe_min(values: list[str]) -> str | None:
    values = [str(value) for value in values if str(value).strip()]
    return min(values) if values else None


def _read_csv_last_date(csv_path: Path) -> tuple[str | None, bool]:
    """Return the last valid date and whether the CSV could be parsed."""

    if not csv_path.exists():
        return None, False
    try:
        frame = pd.read_csv(csv_path, usecols=["date"])
    except Exception:
        return None, False
    if frame.empty or "date" not in frame.columns:
        return None, False
    series = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if series.empty:
        return None, False
    return pd.Timestamp(series.max()).strftime("%Y-%m-%d"), True


def _normalise_boundary(value: str | None, *, field_name: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return pd.Timestamp(value).normalize().strftime("%Y-%m-%d")
    except Exception as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _read_calendar_days(provider_dir: Path, *, freq: str) -> list[str]:
    path = provider_dir / "calendars" / f"{freq}.txt"
    if not path.exists():
        return []
    parsed = pd.to_datetime(
        [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ],
        errors="coerce",
    )
    return sorted(
        {
            pd.Timestamp(value).normalize().strftime("%Y-%m-%d")
            for value in parsed
            if not pd.isna(value)
        }
    )


def _lag_sessions(
    *, series_end: str, required_end: str, quality_calendar_days: list[str]
) -> int:
    return sum(series_end < day <= required_end for day in quality_calendar_days)


def _attempts_by_symbol(
    provider_attempts: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in provider_attempts or []:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            output[symbol] = row
    return output


def _classify_terminal_gap(
    *,
    symbol: str,
    benchmark_symbols: set[str],
    provider_attempt: dict[str, Any] | None,
) -> tuple[str, str, list[str]]:
    role = "benchmark" if symbol.upper() in benchmark_symbols else "equity"
    if provider_attempt is not None and not bool(provider_attempt.get("ok")):
        return (
            role,
            "provider_failure_with_retained_data",
            ["provider_failure"],
        )
    if role == "benchmark":
        return (
            role,
            "benchmark_or_market_calendar_divergence",
            ["benchmark_calendar_lag", "provider_delay"],
        )
    return (
        role,
        "unresolved_equity_terminal_gap",
        ["provider_failure", "suspension_or_non_trading_status"],
    )


def compute_market_quality(
    *,
    market: str,
    provider_dir: Path,
    csv_dir: Path,
    latest_calendar_day: str,
    freshness_mode: str = "current_snapshot",
    quality_calendar_days: list[str] | None = None,
    benchmark_symbols: set[str] | None = None,
    provider_attempts_by_symbol: dict[str, dict[str, Any]] | None = None,
    stale_sample_limit: int = 20,
) -> MarketQuality:
    market = str(market or "").strip().lower()
    inst_path = provider_dir / "instruments" / f"{market}.txt"
    inst_rows = _parse_instruments_file(inst_path)
    quality_calendar_days = quality_calendar_days or [str(latest_calendar_day)]
    benchmark_symbols = {str(value).upper() for value in (benchmark_symbols or set())}
    provider_attempts_by_symbol = provider_attempts_by_symbol or {}

    ends = [row.get("end") or "" for row in inst_rows]
    end_max = _safe_max(ends)
    end_min = _safe_min(ends)

    stale: list[tuple[str, str]] = []
    stale_details: list[dict[str, Any]] = []
    scope_classification = (
        "missing_declared_interval_terminal_coverage"
        if freshness_mode == "declared_interval"
        else "current_snapshot_lag"
    )
    for row in inst_rows:
        end = str(row.get("end") or "").strip()
        symbol = str(row.get("symbol") or "").strip().upper()
        if not end or not symbol or end >= str(latest_calendar_day):
            continue
        stale.append((end, symbol))
        role, cause, possible_causes = _classify_terminal_gap(
            symbol=symbol,
            benchmark_symbols=benchmark_symbols,
            provider_attempt=provider_attempts_by_symbol.get(symbol),
        )
        stale_details.append(
            {
                "symbol": symbol,
                "instrument_role": role,
                "series_end": end,
                "required_calendar_end": str(latest_calendar_day),
                "lag_sessions": _lag_sessions(
                    series_end=end,
                    required_end=str(latest_calendar_day),
                    quality_calendar_days=quality_calendar_days,
                ),
                "scope_classification": scope_classification,
                "cause_classification": cause,
                "possible_causes": possible_causes,
            }
        )
    stale.sort(key=lambda item: item[0])
    stale_details.sort(key=lambda item: (str(item["series_end"]), str(item["symbol"])))
    stale_symbols = [symbol for _, symbol in stale[: int(stale_sample_limit)]]

    csv_missing = 0
    csv_parse_errors = 0
    csv_last_dates: list[str] = []
    csv_stale_symbols: list[str] = []
    for row in inst_rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        csv_path = csv_dir / f"{symbol}.csv"
        last, ok = _read_csv_last_date(csv_path)
        if not csv_path.exists():
            csv_missing += 1
            continue
        if not ok:
            csv_parse_errors += 1
            continue
        if last:
            csv_last_dates.append(str(last))
            if str(last) < str(latest_calendar_day):
                csv_stale_symbols.append(symbol)

    return MarketQuality(
        market=market,
        instruments=len(inst_rows),
        instrument_end_max=end_max,
        instrument_end_min=end_min,
        stale_instruments=len(stale),
        stale_symbols_sample=stale_symbols,
        stale_details_sample=stale_details[: int(stale_sample_limit)],
        csv_missing=csv_missing,
        csv_parse_errors=csv_parse_errors,
        csv_end_max=_safe_max(csv_last_dates),
        csv_end_min=_safe_min(csv_last_dates),
        csv_stale=len(csv_stale_symbols),
        csv_stale_symbols_sample=csv_stale_symbols[: int(stale_sample_limit)],
    )


def generate_data_quality_summary(
    *,
    dataset_key: str,
    freq: str,
    provider_uri: str | Path,
    csv_dir: str | Path,
    markets: list[str] | None = None,
    requested_start: str | None = None,
    requested_end: str | None = None,
    benchmark_symbols: set[str] | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dataset_key = str(dataset_key or "").strip() or "watchlist"
    freq = str(freq or "").strip() or "day"
    provider_dir = Path(provider_uri)
    csv_dir = Path(csv_dir)
    markets = markets or ["cn", "us"]
    benchmark_symbols = {
        str(value).strip().upper() for value in (benchmark_symbols or set()) if str(value).strip()
    }
    attempts = _attempts_by_symbol(provider_attempts)

    try:
        requested_start = _normalise_boundary(
            requested_start, field_name="requested_start"
        )
        requested_end = _normalise_boundary(requested_end, field_name="requested_end")
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "dataset_key": dataset_key,
            "freq": freq,
            "provider_uri": str(provider_dir),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    if requested_start and requested_end and requested_end < requested_start:
        return {
            "ok": False,
            "error": "requested_end must be on or after requested_start",
            "dataset_key": dataset_key,
            "freq": freq,
            "provider_uri": str(provider_dir),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    provider_latest = read_latest_calendar_day(provider_dir, freq=freq)
    calendar_days = _read_calendar_days(provider_dir, freq=freq)
    if not provider_latest or not calendar_days:
        return {
            "ok": False,
            "error": f"calendar not found under {provider_dir}/calendars/{freq}.txt",
            "dataset_key": dataset_key,
            "freq": freq,
            "provider_uri": str(provider_dir),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    scoped_calendar = [
        day
        for day in calendar_days
        if (requested_start is None or day >= requested_start)
        and (requested_end is None or day <= requested_end)
    ]
    if not scoped_calendar:
        return {
            "ok": False,
            "error": "provider calendar has no sessions inside the requested interval",
            "dataset_key": dataset_key,
            "freq": freq,
            "provider_uri": str(provider_dir),
            "requested_start": requested_start,
            "requested_end": requested_end,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    freshness_mode = "declared_interval" if requested_end else "current_snapshot"
    quality_latest = scoped_calendar[-1]
    snapshot_id = build_data_snapshot_id(
        dataset_key=dataset_key,
        freq=freq,
        latest_calendar_day=provider_latest,
    )

    per_market: dict[str, dict[str, Any]] = {}
    for market in markets:
        try:
            quality = compute_market_quality(
                market=market,
                provider_dir=provider_dir,
                csv_dir=csv_dir,
                latest_calendar_day=quality_latest,
                freshness_mode=freshness_mode,
                quality_calendar_days=scoped_calendar,
                benchmark_symbols=benchmark_symbols,
                provider_attempts_by_symbol=attempts,
            )
            per_market[market] = {
                "market": quality.market,
                "instruments": quality.instruments,
                "instrument_end_max": quality.instrument_end_max,
                "instrument_end_min": quality.instrument_end_min,
                "stale_instruments": quality.stale_instruments,
                "stale_symbols_sample": quality.stale_symbols_sample,
                "stale_details_sample": quality.stale_details_sample,
                "csv_missing": quality.csv_missing,
                "csv_parse_errors": quality.csv_parse_errors,
                "csv_end_max": quality.csv_end_max,
                "csv_end_min": quality.csv_end_min,
                "csv_stale": quality.csv_stale,
                "csv_stale_symbols_sample": quality.csv_stale_symbols_sample,
            }
        except Exception as exc:
            per_market[market] = {"market": str(market), "error": str(exc)}

    warnings: list[str] = []
    for market, quality in per_market.items():
        if isinstance(quality, dict) and quality.get("stale_instruments"):
            label = (
                "missing declared interval terminal coverage"
                if freshness_mode == "declared_interval"
                else "stale instruments"
            )
            warnings.append(
                f"market={market}: {quality.get('stale_instruments')} {label} "
                f"(end < {quality_latest})"
            )
        if isinstance(quality, dict) and quality.get("csv_missing"):
            warnings.append(
                f"market={market}: {quality.get('csv_missing')} csv files missing under {csv_dir}"
            )
        if isinstance(quality, dict) and quality.get("csv_parse_errors"):
            warnings.append(
                f"market={market}: {quality.get('csv_parse_errors')} csv parse errors"
            )

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "dataset_key": dataset_key,
        "freq": freq,
        "provider_uri": str(provider_dir),
        "csv_dir": str(csv_dir),
        "latest_calendar_day": provider_latest,
        "freshness_scope": {
            "mode": freshness_mode,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "effective_calendar_start": scoped_calendar[0],
            "effective_calendar_end": quality_latest,
            "provider_calendar_latest": provider_latest,
            "calendar_session_count": len(scoped_calendar),
            "benchmark_symbols": sorted(benchmark_symbols),
        },
        "markets": per_market,
        "warnings": warnings,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
