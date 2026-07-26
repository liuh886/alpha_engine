"""Build an isolated US provider with best-effort NDX history backfill.

The operational provider is treated as immutable.  This command copies its
hash-pinned source CSVs into a distinct data root, fetches only official NDX
snapshot symbols missing from that provider, and then builds a new Qlib
provider with explicit lineage.

Renamed/recycled symbols require an allow-listed identity mapping.  In
particular, ``FB`` is sourced from the existing ``META`` history and clipped
before the first semiannual snapshot that uses ``META``.  The current Yahoo
``FB`` instrument is unrelated and is never downloaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.build_market_providers import build_market_provider
from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.market_provider import load_provider_manifest, market_provider_path
from src.research.ndx_window_start_universe import (
    DEFAULT_SNAPSHOT_PATH,
    NdxWindowStartSnapshot,
    load_snapshot,
)

DEFAULT_START = "2021-04-05"
DEFAULT_END = "2026-06-24"
ALLOWED_IDENTITY_ALIASES = {"FB": "META"}
REQUIRED_BAR_COLUMNS = ("date", "open", "high", "low", "close", "volume")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _provider_symbols(provider_dir: Path) -> set[str]:
    instrument_file = provider_dir / "instruments" / "us.txt"
    if not instrument_file.is_file():
        raise FileNotFoundError(f"US instrument file not found: {instrument_file}")
    return {
        line.split("\t", 1)[0].strip().upper()
        for line in instrument_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _required_symbols(snapshot: NdxWindowStartSnapshot) -> set[str]:
    return {
        symbol
        for entry in snapshot.snapshot_dates
        for symbol in entry.symbols
    }


def _alias_end_date(
    snapshot: NdxWindowStartSnapshot,
    *,
    target_symbol: str,
    source_symbol: str,
    requested_end: str,
) -> str:
    """End an alias immediately before snapshots switch to its new ticker."""

    target = target_symbol.upper()
    source = source_symbol.upper()
    target_dates = sorted(
        pd.Timestamp(entry.date)
        for entry in snapshot.snapshot_dates
        if target in entry.symbols
    )
    if not target_dates:
        raise ValueError(f"alias target is absent from NDX snapshots: {target}")

    first_source_after_target = min(
        (
            pd.Timestamp(entry.date)
            for entry in snapshot.snapshot_dates
            if pd.Timestamp(entry.date) > target_dates[-1] and source in entry.symbols
        ),
        default=None,
    )
    requested = pd.Timestamp(requested_end)
    if first_source_after_target is None:
        return requested.strftime("%Y-%m-%d")
    return min(requested, first_source_after_target - pd.Timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )


def _required_first_date(
    snapshot: NdxWindowStartSnapshot,
    symbol: str,
    requested_start: str,
) -> pd.Timestamp:
    first_snapshot = min(
        pd.Timestamp(entry.date)
        for entry in snapshot.snapshot_dates
        if symbol.upper() in entry.symbols
    )
    return max(first_snapshot, pd.Timestamp(requested_start))


def _clean_bars(frame: pd.DataFrame, *, start: str, end: str) -> pd.DataFrame:
    missing = [column for column in REQUIRED_BAR_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"downloaded bars missing required columns: {missing}")

    clean = frame.copy()
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.tz_localize(None)
    clean = clean.dropna(subset=list(REQUIRED_BAR_COLUMNS))
    clean = clean.loc[
        (clean["date"] >= pd.Timestamp(start))
        & (clean["date"] <= pd.Timestamp(end))
    ]
    clean = clean.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    if clean.empty:
        raise ValueError("no complete daily bars remain after clipping")
    if "amount" not in clean.columns:
        clean["amount"] = clean["close"] * clean["volume"]
    if "factor" not in clean.columns:
        clean["factor"] = 1.0
    return clean[
        ["date", "open", "high", "low", "close", "volume", "amount", "factor"]
    ].reset_index(drop=True)


def _assert_usable_from_first_membership(
    frame: pd.DataFrame,
    *,
    snapshot: NdxWindowStartSnapshot,
    symbol: str,
    requested_start: str,
) -> None:
    required = _required_first_date(snapshot, symbol, requested_start)
    first = pd.Timestamp(frame["date"].min())
    if first > required:
        raise ValueError(
            f"{symbol} history starts after first required membership date: "
            f"first={first.date()} required={required.date()}"
        )


def _validate_isolated_roots(base_data_root: Path, output_data_root: Path) -> None:
    base = base_data_root.resolve()
    output = output_data_root.resolve()
    if base == output:
        raise ValueError("output data root must differ from the base data root")
    if len(output.parts) < 3:
        raise ValueError(f"refusing unsafe shallow output data root: {output}")
    if market_provider_path(base, "us") == market_provider_path(output, "us"):
        raise ValueError("output provider must differ from the operational provider")


def _seed_pinned_sources(
    *,
    base_data_root: Path,
    output_csv_dir: Path,
    base_manifest: dict[str, Any],
) -> int:
    source_dir = base_data_root / "data" / "csv_source"
    output_csv_dir.mkdir(parents=True, exist_ok=False)
    entries = base_manifest.get("source_csvs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("base provider manifest has no source_csvs")

    for entry in entries:
        name = str(entry.get("name", "")).strip()
        expected_hash = str(entry.get("sha256", "")).strip()
        source = source_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"hash-pinned source CSV not found: {source}")
        actual_hash = _sha256_file(source)
        if actual_hash != expected_hash:
            raise ValueError(
                f"source CSV hash mismatch for {name}: "
                f"expected={expected_hash} actual={actual_hash}"
            )
        shutil.copy2(source, output_csv_dir / name)
    return len(entries)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, date_format="%Y-%m-%d")


def build_ndx_window_start_provider(
    *,
    base_data_root: str | Path,
    output_data_root: str | Path,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT_PATH,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    overwrite: bool = False,
) -> dict[str, Any]:
    base_root = Path(base_data_root).resolve()
    output_root = Path(output_data_root).resolve()
    _validate_isolated_roots(base_root, output_root)

    snapshot = load_snapshot(snapshot_path)
    base_provider = market_provider_path(base_root, "us")
    base_manifest = load_provider_manifest(
        base_provider,
        expected_market="us",
        verify_files=True,
    )
    base_symbols = _provider_symbols(base_provider)
    missing_symbols = sorted(_required_symbols(snapshot) - base_symbols)

    output_data_dir = output_root / "data"
    if output_data_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"output data directory already exists (use --overwrite): {output_data_dir}"
            )
        if output_root not in output_data_dir.resolve().parents:
            raise ValueError(f"unsafe output data directory: {output_data_dir}")
        shutil.rmtree(output_data_dir)

    output_csv_dir = output_data_dir / "csv_source"
    seeded_count = _seed_pinned_sources(
        base_data_root=base_root,
        output_csv_dir=output_csv_dir,
        base_manifest=base_manifest,
    )

    adapter = YFinanceAdapter()
    downloaded: list[dict[str, Any]] = []
    aliased: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []

    for symbol in missing_symbols:
        alias_source = ALLOWED_IDENTITY_ALIASES.get(symbol)
        try:
            if alias_source:
                alias_source_path = output_csv_dir / f"{alias_source}.csv"
                if not alias_source_path.is_file():
                    raise FileNotFoundError(
                        f"alias source CSV not found: {alias_source_path}"
                    )
                alias_end = _alias_end_date(
                    snapshot,
                    target_symbol=symbol,
                    source_symbol=alias_source,
                    requested_end=end,
                )
                source_frame = pd.read_csv(alias_source_path)
                frame = _clean_bars(source_frame, start=start, end=alias_end)
                source_kind = "pinned_base_alias"
            else:
                result = adapter.fetch_daily_bars(
                    FetchRequest(
                        symbol=symbol,
                        market="us",
                        start=start,
                        end=end,
                    )
                )
                frame = _clean_bars(result.df, start=start, end=end)
                source_kind = result.provider

            _assert_usable_from_first_membership(
                frame,
                snapshot=snapshot,
                symbol=symbol,
                requested_start=start,
            )
            _write_csv(frame, output_csv_dir / f"{symbol}.csv")
            record = {
                "symbol": symbol,
                "source": source_kind,
                "source_symbol": alias_source or symbol,
                "first_date": frame["date"].min().strftime("%Y-%m-%d"),
                "last_date": frame["date"].max().strftime("%Y-%m-%d"),
                "rows": int(len(frame)),
            }
            if alias_source:
                aliased.append(record)
            else:
                downloaded.append(record)
        except (DataFetchError, FileNotFoundError, ValueError) as exc:
            unavailable.append(
                {
                    "symbol": symbol,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    output_provider = market_provider_path(output_root, "us")
    output_manifest = build_market_provider(
        csv_dir=output_csv_dir,
        provider_dir=output_provider,
        market="us",
    )
    output_symbols = _provider_symbols(output_provider)

    coverage = {}
    for entry in snapshot.snapshot_dates:
        requested = set(entry.symbols)
        retained = sorted(requested & output_symbols)
        missing = sorted(requested - output_symbols)
        coverage[entry.date] = {
            "n_requested": len(requested),
            "n_retained": len(retained),
            "coverage_ratio": round(len(retained) / len(requested), 4),
            "missing": missing,
            "complete": not missing,
        }

    lineage = {
        "schema_version": "1.0",
        "evidence_type": "ndx_window_start_provider_backfill",
        "research_only": True,
        "base_provider_identity_sha256": base_manifest["provider_identity_sha256"],
        "output_provider_identity_sha256": output_manifest["provider_identity_sha256"],
        "snapshot_path": str(Path(snapshot_path).resolve()),
        "snapshot_membership_hashes": {
            entry.date: entry.sha256_membership_hash
            for entry in snapshot.snapshot_dates
        },
        "requested_start": start,
        "requested_end": end,
        "price_adjustment": "yfinance_auto_adjust_true",
        "seeded_source_csvs": seeded_count,
        "missing_from_base_provider": missing_symbols,
        "downloaded": downloaded,
        "aliased": aliased,
        "unavailable": unavailable,
        "membership_coverage": coverage,
        "policies": {
            "operational_provider_mutated": False,
            "recycled_symbols_downloaded_directly": False,
            "identity_aliases_allowlisted": ALLOWED_IDENTITY_ALIASES,
            "unavailable_symbols_fail_closed": True,
        },
    }
    lineage_path = output_data_dir / "provider_backfill_lineage.json"
    lineage_path.write_text(
        json.dumps(lineage, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "output_data_root": str(output_root),
        "provider_uri": str(output_provider),
        "provider_identity_sha256": output_manifest["provider_identity_sha256"],
        "lineage_path": str(lineage_path),
        "downloaded_count": len(downloaded),
        "aliased_count": len(aliased),
        "unavailable_count": len(unavailable),
        "lineage": lineage,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-data-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-data-root", type=Path, required=True)
    parser.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = build_ndx_window_start_provider(
        base_data_root=args.base_data_root,
        output_data_root=args.output_data_root,
        snapshot_path=args.snapshot_path,
        start=args.start,
        end=args.end,
        overwrite=args.overwrite,
    )
    summary = {
        key: result[key]
        for key in (
            "output_data_root",
            "provider_uri",
            "provider_identity_sha256",
            "lineage_path",
            "downloaded_count",
            "aliased_count",
            "unavailable_count",
        )
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
