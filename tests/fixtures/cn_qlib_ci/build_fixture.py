"""Build a tiny deterministic CN Qlib dataset for CI integration tests.

The generated values are synthetic and have no research or investment meaning.
The directory layout and binary encoding follow Qlib's daily data format:

- calendars/day.txt
- instruments/all.txt
- features/<symbol>/<field>.day.bin

Each feature binary starts with one little-endian float32 calendar offset followed
by little-endian float32 observations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS: tuple[str, ...] = (
    "SH600001",
    "SH600002",
    "SH600003",
    "SH600004",
    "SH600005",
    "SH600006",
    "SZ000001",
    "SZ000002",
    "SZ000003",
    "SZ000004",
    "SZ000005",
    "SZ000006",
)
FIELDS: tuple[str, ...] = ("open", "close", "high", "low", "volume", "factor")
START_DATE = "2022-01-03"
END_DATE = "2024-12-31"


def _write_feature(path: Path, values: np.ndarray) -> None:
    payload = np.hstack(
        [
            np.asarray([0.0], dtype="<f4"),
            np.asarray(values, dtype="<f4"),
        ]
    )
    payload.astype("<f4").tofile(path)


def build_cn_qlib_fixture(target_dir: str | Path) -> Path:
    """Create and return a self-contained Qlib provider directory."""
    root = Path(target_dir).resolve()
    calendars_dir = root / "calendars"
    instruments_dir = root / "instruments"
    features_dir = root / "features"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)

    dates = pd.bdate_range(START_DATE, END_DATE)
    (calendars_dir / "day.txt").write_text(
        "\n".join(value.strftime("%Y-%m-%d") for value in dates) + "\n",
        encoding="utf-8",
    )
    (instruments_dir / "all.txt").write_text(
        "".join(
            f"{symbol}\t{dates[0]:%Y-%m-%d}\t{dates[-1]:%Y-%m-%d}\n"
            for symbol in SYMBOLS
        ),
        encoding="utf-8",
    )

    time_index = np.arange(len(dates), dtype=float)
    for symbol_index, symbol in enumerate(SYMBOLS):
        symbol_dir = features_dir / symbol.lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)

        drift = 0.0002 + (symbol_index - 5.5) * 0.000012
        cycle = 0.014 * np.sin(
            time_index / (9 + (symbol_index % 4)) + symbol_index * 0.41
        ) + 0.006 * np.cos(
            time_index / (21 + (symbol_index % 5)) + symbol_index
        )
        close = np.exp(np.log(8.0 + symbol_index * 0.75) + drift * time_index + cycle)
        open_ = close * (1.0 + 0.002 * np.sin(time_index / 5.0 + symbol_index))
        spread = 0.008 + 0.0015 * (
            1.0 + np.sin(time_index / 13.0 + symbol_index)
        )
        high = np.maximum(open_, close) * (1.0 + spread)
        low = np.minimum(open_, close) * (1.0 - spread)
        volume = (1_000_000 + 60_000 * symbol_index) * (
            1.0
            + 0.18 * np.sin(time_index / 7.0 + symbol_index * 0.2)
            + 0.08 * np.cos(time_index / 19.0 + symbol_index)
        )
        factor = np.ones_like(close)

        values = {
            "open": open_,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
            "factor": factor,
        }
        for field, field_values in values.items():
            _write_feature(symbol_dir / f"{field}.day.bin", field_values)

    manifest = {
        "schema_version": "1.0",
        "kind": "synthetic_cn_qlib_ci_fixture",
        "purpose": "CI smoke/integration only; no research or investment meaning",
        "start": dates[0].strftime("%Y-%m-%d"),
        "end": dates[-1].strftime("%Y-%m-%d"),
        "calendar_sessions": len(dates),
        "symbols": list(SYMBOLS),
        "fields": list(FIELDS),
    }
    (root / "fixture_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build_cn_qlib_fixture(args.output))


if __name__ == "__main__":
    main()
