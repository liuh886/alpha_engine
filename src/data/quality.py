from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

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
    csv_missing: int
    csv_parse_errors: int
    csv_end_max: str | None
    csv_end_min: str | None
    csv_stale: int


def _parse_instruments_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        rows.append({"symbol": parts[0].strip(), "start": parts[1].strip(), "end": parts[2].strip()})
    return rows


def _safe_max(values: list[str]) -> str | None:
    values = [str(v) for v in values if str(v).strip()]
    return max(values) if values else None


def _safe_min(values: list[str]) -> str | None:
    values = [str(v) for v in values if str(v).strip()]
    return min(values) if values else None


def _read_csv_last_date(csv_path: Path) -> tuple[str | None, bool]:
    """
    Returns: (last_date_str, ok)
    """
    if not csv_path.exists():
        return None, False
    try:
        df = pd.read_csv(csv_path, usecols=["date"])
    except Exception:
        return None, False
    if df.empty or "date" not in df.columns:
        return None, False
    try:
        s = pd.to_datetime(df["date"], errors="coerce")
    except Exception:
        return None, False
    s = s.dropna()
    if s.empty:
        return None, False
    last = s.max()
    try:
        return pd.Timestamp(last).strftime("%Y-%m-%d"), True
    except Exception:
        return str(last), True


def compute_market_quality(
    *,
    market: str,
    provider_dir: Path,
    csv_dir: Path,
    latest_calendar_day: str,
    stale_sample_limit: int = 20,
) -> MarketQuality:
    market = str(market or "").strip().lower()
    inst_path = provider_dir / "instruments" / f"{market}.txt"
    inst_rows = _parse_instruments_file(inst_path)

    ends = [r.get("end") or "" for r in inst_rows]
    end_max = _safe_max(ends)
    end_min = _safe_min(ends)

    stale = []
    for r in inst_rows:
        end = str(r.get("end") or "").strip()
        sym = str(r.get("symbol") or "").strip()
        if not end or not sym:
            continue
        if end < str(latest_calendar_day):
            stale.append((end, sym))
    stale.sort(key=lambda x: x[0])
    stale_symbols = [sym for _, sym in stale[: int(stale_sample_limit)]]

    csv_missing = 0
    csv_parse_errors = 0
    csv_last_dates: list[str] = []
    csv_stale = 0
    for r in inst_rows:
        sym = str(r.get("symbol") or "").strip()
        if not sym:
            continue
        csv_path = csv_dir / f"{sym}.csv"
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
                csv_stale += 1

    return MarketQuality(
        market=market,
        instruments=len(inst_rows),
        instrument_end_max=end_max,
        instrument_end_min=end_min,
        stale_instruments=len(stale),
        stale_symbols_sample=stale_symbols,
        csv_missing=csv_missing,
        csv_parse_errors=csv_parse_errors,
        csv_end_max=_safe_max(csv_last_dates),
        csv_end_min=_safe_min(csv_last_dates),
        csv_stale=csv_stale,
    )


def generate_data_quality_summary(
    *,
    dataset_key: str,
    freq: str,
    provider_uri: str | Path,
    csv_dir: str | Path,
    markets: list[str] | None = None,
) -> dict:
    dataset_key = str(dataset_key or "").strip() or "watchlist"
    freq = str(freq or "").strip() or "day"
    provider_dir = Path(provider_uri)
    csv_dir = Path(csv_dir)
    markets = markets or ["cn", "us"]

    latest = read_latest_calendar_day(provider_dir, freq=freq)
    if not latest:
        return {
            "ok": False,
            "error": f"calendar not found under {provider_dir}/calendars/{freq}.txt",
            "dataset_key": dataset_key,
            "freq": freq,
            "provider_uri": str(provider_dir),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    snapshot_id = build_data_snapshot_id(dataset_key=dataset_key, freq=freq, latest_calendar_day=latest)

    per_market = {}
    for m in markets:
        try:
            q = compute_market_quality(
                market=m,
                provider_dir=provider_dir,
                csv_dir=csv_dir,
                latest_calendar_day=latest,
            )
            per_market[m] = {
                "market": q.market,
                "instruments": q.instruments,
                "instrument_end_max": q.instrument_end_max,
                "instrument_end_min": q.instrument_end_min,
                "stale_instruments": q.stale_instruments,
                "stale_symbols_sample": q.stale_symbols_sample,
                "csv_missing": q.csv_missing,
                "csv_parse_errors": q.csv_parse_errors,
                "csv_end_max": q.csv_end_max,
                "csv_end_min": q.csv_end_min,
                "csv_stale": q.csv_stale,
            }
        except Exception as e:
            per_market[m] = {"market": str(m), "error": str(e)}

    warnings = []
    for m, q in per_market.items():
        if isinstance(q, dict) and q.get("stale_instruments"):
            warnings.append(f"market={m}: {q.get('stale_instruments')} stale instruments (end < calendar latest)")
        if isinstance(q, dict) and q.get("csv_missing"):
            warnings.append(f"market={m}: {q.get('csv_missing')} csv files missing under {csv_dir}")
        if isinstance(q, dict) and q.get("csv_parse_errors"):
            warnings.append(f"market={m}: {q.get('csv_parse_errors')} csv parse errors")

    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "dataset_key": dataset_key,
        "freq": freq,
        "provider_uri": str(provider_dir),
        "csv_dir": str(csv_dir),
        "latest_calendar_day": latest,
        "markets": per_market,
        "warnings": warnings,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

