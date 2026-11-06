"""Audit split-scale contamination in US87 OHLCV before model search.

This is a read-only semantic check over the already hash-verified source.
A price jump is *suspected* split/scale contamination, not a certified
corporate action; repair requires independently sourced, versioned inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

from src.research.cloud_exchange import ExchangeError

SYMBOL_DIR = "data/research/market_evidence/us/symbols"
POOL_FILE = "configs/research_universes/us_selected_equities_v2.yaml"
# Large near-integer rescaling of adjusted daily close is not tradable alpha.
# Conservative >=3:1 threshold avoids mistaking ordinary volatile gains for splits.
SCALE_FACTORS = (3, 4, 5, 10)
FACTOR_TOLERANCE = 0.08


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit_symbol(symbol: str, bars: list[dict], start: str, end: str) -> list[dict]:
    """Scan consecutive source trading observations; do not synthesize returns."""
    events: list[dict] = []
    previous: dict | None = None
    previous_day = ""
    for row in bars:
        if not isinstance(row, dict):
            raise ExchangeError(f"{symbol}: invalid OHLCV bar")
        day = row.get("time")
        if not isinstance(day, str) or len(day) != 10 or day <= previous_day:
            raise ExchangeError(f"{symbol}: duplicate/unsorted source dates")
        previous_day = day
        try:
            values = [float(row[key]) for key in ("open", "high", "low", "close")]
            volume = float(row["volume"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ExchangeError(f"{symbol}: invalid OHLCV fields on {day}") from exc
        op, hi, lo, close = values
        if (not all(math.isfinite(v) and v > 0 for v in values) or
                not math.isfinite(volume) or volume < 0 or
                lo > hi or min(op, close) < lo * 0.9999 or
                max(op, close) > hi * 1.0001):
            raise ExchangeError(f"{symbol}: inconsistent OHLCV on {day}")
        if previous is not None and start <= day <= end:
            prev_close = float(previous["close"])
            ratio = close / prev_close
            factor = max(ratio, 1 / ratio)
            candidate = next((n for n in SCALE_FACTORS
                              if abs(factor / n - 1) <= FACTOR_TOLERANCE), None)
            if candidate is not None:
                events.append({
                    "symbol": symbol, "date": day,
                    "previous_date": previous["time"],
                    "previous_close": prev_close, "close": close,
                    "close_ratio": round(ratio, 6),
                    "suspected_scale_factor": candidate,
                    "direction": "up" if ratio > 1 else "down",
                    "code": "suspected_adjustment_scale_discontinuity",
                })
        previous = row
    if previous is None:
        raise ExchangeError(f"{symbol}: empty price history")
    return events


def audit_dataframe(frame: Any, *, symbol: str) -> list[dict]:
    """Reuse the same close-scale and OHLCV check on normalized provider CSV rows."""
    if frame.empty:
        raise ExchangeError(f"{symbol}: empty normalized price frame")
    rows = []
    for record in frame.to_dict(orient="records"):
        day = record["date"]
        date_string = day.date().isoformat() if hasattr(day, "date") else str(day)[:10]
        rows.append({
            "time": date_string,
            **{key: record[key] for key in ("open", "high", "low", "close", "volume")},
        })
    return _audit_symbol(symbol, rows, rows[0]["time"], rows[-1]["time"])


def audit_source(*, read_text: Callable[[str], str], symbols: list[str],
                 start_date: str, end_date: str, source_sha256: str | None = None) -> dict[str, Any]:
    """Call with a stable, explicitly selected archive or staged data root."""
    if (not isinstance(symbols, list) or len(symbols) != 87 or
            len(set(symbols)) != 87 or not start_date or end_date < start_date):
        raise ExchangeError("US87 price-integrity scope invalid")
    anomalies: list[dict] = []
    for symbol in [*symbols, "QQQ"]:
        if not symbol.replace("-", "").replace(".", "").isalnum():
            raise ExchangeError("invalid instrument identifier")
        doc = json.loads(read_text(f"{SYMBOL_DIR}/{symbol}.json"))
        if doc.get("symbol") != symbol or not isinstance(doc.get("bars"), list):
            raise ExchangeError(f"{symbol}: price source identity/shape mismatch")
        anomalies.extend(_audit_symbol(symbol, doc["bars"], start_date, end_date))
    return {
        "schema_version": "us87_price_integrity_v1",
        "status": "BLOCKED_PRICE_SCALE_INTEGRITY" if anomalies else "READY_PRICE_SCALE_SCREEN",
        "source_sha256": source_sha256,
        "start_date": start_date, "end_date": end_date,
        "candidate_count": len(symbols), "reference_symbols": ["QQQ"],
        "anomaly_count": len(anomalies), "anomalies": anomalies,
        "repair_policy": "replace source with independently verified adjusted OHLCV snapshot; never interpolate, infer split actions, or mutate original v5",
        "research_only": True, "trade_ready": False, "pit_certified": False,
        "price_semantics_certified": False,
    }


def audit_staged(root: Path, *, start_date: str, end_date: str,
                 symbols: list[str] | None = None) -> dict[str, Any]:
    import yaml
    from src.research.v5_isolated_staging import verify_stage

    receipt = verify_stage(root)
    if symbols is None:
        symbols = yaml.safe_load((root / POOL_FILE).read_text(encoding="utf-8"))["symbols"]
    report = audit_source(
        read_text=lambda path: (root / path).read_text(encoding="utf-8"),
        symbols=symbols, start_date=start_date, end_date=end_date,
        source_sha256=receipt["history_archive_sha256"])
    return report


def audit_archive(archive: Path, *, start_date: str, end_date: str) -> dict[str, Any]:
    import yaml

    if not archive.is_file() or archive.is_symlink():
        raise ExchangeError("missing or symlinked price archive")
    with zipfile.ZipFile(archive) as package:
        def read_text(path: str) -> str:
            return package.read("files/" + path).decode("utf-8")

        symbols = yaml.safe_load(read_text(POOL_FILE))["symbols"]
        return audit_source(read_text=read_text, symbols=symbols,
                            start_date=start_date, end_date=end_date,
                            source_sha256=_digest(archive))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--data-root", type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--report-file", type=Path)
    args = parser.parse_args(argv)
    try:
        report = (audit_archive(args.archive, start_date=args.start_date,
                                end_date=args.end_date) if args.archive else
                  audit_staged(args.data_root, start_date=args.start_date,
                               end_date=args.end_date))
        serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.report_file:
            with args.report_file.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        print(serialized)
        return 10 if report["anomaly_count"] else 0
    except (ExchangeError, OSError, ValueError, KeyError, TypeError,
            zipfile.BadZipFile) as exc:
        print(f"BLOCKED_PRICE_INTEGRITY_AUDIT: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
