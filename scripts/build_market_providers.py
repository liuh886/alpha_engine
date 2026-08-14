"""Build market-specific Qlib providers from the operational CSV source directory.

With an explicit ``cutoff`` each source is truncated to rows at or before that
date and the staged files -- serialized with LF line endings -- are the ones
bound into the provider calendar/features/instruments and the manifest
``source_csvs`` hashes. That makes an exact-cutoff provider identity
deterministic across platforms while leaving the historical no-cutoff build
path and identity untouched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from scripts.dump_bin import dump_all
from src.data.market_provider import (
    SUPPORTED_MARKETS,
    market_provider_path,
    normalize_provider_market,
    write_provider_manifest,
)
from src.data.symbol_identity import infer_data_market
from src.data.validation.schema import validate_market_data

DEFAULT_FIELDS = "open,high,low,close,volume,amount,factor"


def validate_cutoff(cutoff: str) -> pd.Timestamp:
    """Validate an explicit ISO ``YYYY-MM-DD`` cutoff and return it as midnight."""
    value = str(cutoff).strip()
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ValueError(f"cutoff must be a YYYY-MM-DD ISO date, got {cutoff!r}")
    try:
        return pd.Timestamp(date.fromisoformat(value))
    except ValueError:
        raise ValueError(f"cutoff must be a valid calendar date, got {cutoff!r}") from None


def source_csvs_for_market(csv_dir: str | Path, market: str) -> list[Path]:
    directory = Path(csv_dir).resolve()
    market_key = normalize_provider_market(market)
    return [
        path
        for path in sorted(directory.glob("*.csv"))
        if infer_data_market(path.stem) == market_key
    ]


def _preflight_source(source: Path, market_key: str, *, require_sorted: bool) -> None:
    """Fail closed unless one source CSV is clean for provider building.

    Validation runs on the full source regardless of cutoff so a truncated
    subset can never smuggle malformed bars into the provider.
    """

    symbol = source.stem
    try:
        source_df = pd.read_csv(source)
    except Exception as exc:
        raise ValueError(
            f"Cannot read source CSV {source.name} (symbol={symbol}, market={market_key}): {exc}"
        ) from exc

    if "date" not in source_df.columns:
        raise ValueError(
            f"Source CSV {source.name} "
            f"(symbol={symbol}, market={market_key}) "
            "is missing the required date column"
        )
    dates = pd.to_datetime(source_df["date"], errors="coerce")
    bad_dates = dates.isna()
    if bad_dates.any():
        raise ValueError(
            f"Source CSV {source.name} (symbol={symbol}, market={market_key}) "
            f"contains unparseable dates at indices "
            f"{source_df.index[bad_dates].tolist()}"
        )
    if dates.duplicated().any():
        raise ValueError(
            f"Source CSV {source.name} "
            f"(symbol={symbol}, market={market_key}) "
            "contains duplicate dates"
        )
    if require_sorted and not dates.is_monotonic_increasing:
        raise ValueError(
            f"Source CSV {source.name} "
            f"(symbol={symbol}, market={market_key}) "
            "contains dates that are not in ascending order"
        )

    validated = source_df.copy()
    validated["date"] = dates
    ok, _, errors = validate_market_data(validated, symbol)
    if not ok:
        raise ValueError(
            f"Source CSV {source.name} (symbol={symbol}, market={market_key}) "
            f"failed preflight validation: {'; '.join(errors)}"
        )


def _stage_cutoff_source(
    source: Path,
    stage: Path,
    cutoff: pd.Timestamp,
    market_key: str,
) -> Path:
    """Write a deterministic LF-truncated copy of one source at ``date <= cutoff``.

    Rows are filtered, never forward-filled or altered, so the staged file is
    exactly the source rows whose session falls at or before the cutoff.
    """

    symbol = source.stem
    source_df = pd.read_csv(source)
    dates = pd.to_datetime(source_df["date"], errors="coerce")
    keep = dates <= cutoff
    if not keep.any():
        raise ValueError(
            f"Source CSV {source.name} (symbol={symbol}, market={market_key}) "
            f"has no rows at or before cutoff {cutoff:%Y-%m-%d}"
        )
    destination = stage / source.name
    source_df.loc[keep].to_csv(
        destination,
        index=False,
        lineterminator="\n",
        encoding="utf-8",
    )
    return destination


def _verify_cutoff_provider(
    destination: Path,
    cutoff: pd.Timestamp,
    market_key: str,
) -> None:
    """Fail closed if any provider calendar session or instrument end date exceeds cutoff."""

    calendar_path = destination / "calendars" / "day.txt"
    if not calendar_path.is_file():
        raise ValueError(f"provider calendar is missing: {calendar_path}")
    for line in calendar_path.read_text(encoding="utf-8").splitlines():
        day = line.strip()
        if day and pd.Timestamp(day) > cutoff:
            raise ValueError(f"provider calendar session {day} is beyond cutoff {cutoff:%Y-%m-%d}")
    instrument_path = destination / "instruments" / f"{market_key}.txt"
    if not instrument_path.is_file():
        raise ValueError(f"provider instruments are missing: {instrument_path}")
    for line in instrument_path.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row:
            continue
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        if pd.Timestamp(parts[2]) > cutoff:
            raise ValueError(
                f"provider instrument {parts[0]} end date {parts[2]} "
                f"is beyond cutoff {cutoff:%Y-%m-%d}"
            )


def build_market_provider(
    *,
    csv_dir: str | Path,
    provider_dir: str | Path,
    market: str,
    include_fields: str = DEFAULT_FIELDS,
    cutoff: str | None = None,
) -> dict:
    """Build one provider using only CSVs inferred for the selected market.

    With ``cutoff`` set, sources are truncated to ``date <= cutoff`` and those
    staged files are the ones bound into the provider identity. With
    ``cutoff=None`` the historical behavior and identity are preserved.
    """

    source_dir = Path(csv_dir).resolve()
    destination = Path(provider_dir).resolve()
    market_key = normalize_provider_market(market)
    cutoff_ts = validate_cutoff(cutoff) if cutoff is not None else None
    source_files = source_csvs_for_market(source_dir, market_key)
    if not source_files:
        raise FileNotFoundError(f"no source CSVs found for market={market_key} under {source_dir}")

    # Preflight: validate every source CSV before touching the destination.
    for source in source_files:
        _preflight_source(source, market_key, require_sorted=cutoff_ts is not None)

    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"alpha-engine-{market_key}-") as temporary:
        stage = Path(temporary)
        staged_files: list[Path] = []
        for source in source_files:
            if cutoff_ts is not None:
                staged = _stage_cutoff_source(source, stage, cutoff_ts, market_key)
            else:
                staged = stage / source.name
                shutil.copy2(source, staged)
            staged_files.append(staged)
        dump_all(
            str(stage),
            str(destination),
            include_fields=include_fields,
            date_field_name="date",
            symbol_field_name="symbol",
            lf_newlines=cutoff_ts is not None,
        )
        if cutoff_ts is not None:
            _verify_cutoff_provider(destination, cutoff_ts, market_key)
        manifest_source_files = staged_files if cutoff_ts is not None else source_files
        manifest = write_provider_manifest(
            destination,
            market=market_key,
            source_csv_files=manifest_source_files,
            cutoff=cutoff,
        )
    return manifest


def build_market_providers(
    *,
    repository_root: str | Path = ".",
    csv_dir: str | Path | None = None,
    markets: Iterable[str] = SUPPORTED_MARKETS,
    include_fields: str = DEFAULT_FIELDS,
    cutoff: str | None = None,
) -> dict[str, dict]:
    root = Path(repository_root).resolve()
    source_dir = Path(csv_dir).resolve() if csv_dir else root / "data" / "csv_source"
    reports: dict[str, dict] = {}
    for market in markets:
        market_key = normalize_provider_market(market)
        source_files = source_csvs_for_market(source_dir, market_key)
        if not source_files:
            continue
        reports[market_key] = build_market_provider(
            csv_dir=source_dir,
            provider_dir=market_provider_path(root, market_key),
            market=market_key,
            include_fields=include_fields,
            cutoff=cutoff,
        )
    if not reports:
        raise RuntimeError("no market-specific providers were built")
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--csv-dir", type=Path, default=None)
    parser.add_argument(
        "--markets",
        nargs="+",
        choices=list(SUPPORTED_MARKETS),
        default=list(SUPPORTED_MARKETS),
    )
    parser.add_argument("--include-fields", default=DEFAULT_FIELDS)
    parser.add_argument("--cutoff", default=None)
    args = parser.parse_args()

    reports = build_market_providers(
        repository_root=args.root,
        csv_dir=args.csv_dir,
        markets=args.markets,
        include_fields=args.include_fields,
        cutoff=args.cutoff,
    )
    summary: dict[str, dict] = {}
    for market, report in reports.items():
        summary[market] = {
            "provider_identity_sha256": report["provider_identity_sha256"],
            "session_count": report["calendar"]["session_count"],
            "instrument_count": report["instruments"]["count"],
        }
        if "cutoff" in report:
            summary[market]["cutoff"] = report["cutoff"]
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
