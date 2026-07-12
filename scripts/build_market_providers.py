"""Build market-specific Qlib providers from the operational CSV source directory."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

from scripts.dump_bin import dump_all
from src.data.market_provider import (
    SUPPORTED_MARKETS,
    market_provider_path,
    normalize_provider_market,
    write_provider_manifest,
)
from src.data.symbol_identity import infer_data_market

DEFAULT_FIELDS = "open,high,low,close,volume,amount,factor"


def source_csvs_for_market(csv_dir: str | Path, market: str) -> list[Path]:
    directory = Path(csv_dir).resolve()
    market_key = normalize_provider_market(market)
    return [
        path
        for path in sorted(directory.glob("*.csv"))
        if infer_data_market(path.stem) == market_key
    ]


def build_market_provider(
    *,
    csv_dir: str | Path,
    provider_dir: str | Path,
    market: str,
    include_fields: str = DEFAULT_FIELDS,
) -> dict:
    """Build one provider using only CSVs inferred for the selected market."""

    source_dir = Path(csv_dir).resolve()
    destination = Path(provider_dir).resolve()
    market_key = normalize_provider_market(market)
    source_files = source_csvs_for_market(source_dir, market_key)
    if not source_files:
        raise FileNotFoundError(
            f"no source CSVs found for market={market_key} under {source_dir}"
        )

    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"alpha-engine-{market_key}-") as temporary:
        stage = Path(temporary)
        for source in source_files:
            shutil.copy2(source, stage / source.name)
        dump_all(
            str(stage),
            str(destination),
            include_fields=include_fields,
            date_field_name="date",
            symbol_field_name="symbol",
        )

    manifest = write_provider_manifest(
        destination,
        market=market_key,
        source_csv_files=source_files,
    )
    return manifest


def build_market_providers(
    *,
    repository_root: str | Path = ".",
    csv_dir: str | Path | None = None,
    markets: Iterable[str] = SUPPORTED_MARKETS,
    include_fields: str = DEFAULT_FIELDS,
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
    args = parser.parse_args()

    reports = build_market_providers(
        repository_root=args.root,
        csv_dir=args.csv_dir,
        markets=args.markets,
        include_fields=args.include_fields,
    )
    summary = {
        market: {
            "provider_identity_sha256": report["provider_identity_sha256"],
            "session_count": report["calendar"]["session_count"],
            "instrument_count": report["instruments"]["count"],
        }
        for market, report in reports.items()
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
