#!/usr/bin/env python3
"""Add explicit signal/execution context to RSI-VIX SGOV episode evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

VARIANTS = (
    "vix_only_adaptive_sgov",
    "rsi_only_adaptive_sgov",
    "rsi_vix_adaptive_sgov",
)
SCOPES = ("actual", "qqq_proxy")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: pd.Timestamp | None) -> str | None:
    return value.date().isoformat() if value is not None else None


def _contextualize(scope_dir: Path, variant: str) -> None:
    daily_path = scope_dir / f"daily_{variant}.csv"
    episode_path = scope_dir / f"overlay_{variant}.csv"
    daily = pd.read_csv(daily_path, parse_dates=["date"]).set_index("date")
    episodes = pd.read_csv(episode_path)
    if episodes.empty:
        for column in (
            "activation_signal_date",
            "execution_date",
            "signal_rsi_14",
            "signal_vix_close",
            "release_signal_date",
            "release_execution_date",
            "release_signal_rsi_14",
            "release_signal_vix_close",
        ):
            episodes[column] = pd.Series(dtype="object")
        episodes.to_csv(episode_path, index=False)
        return

    index = daily.index
    rows: list[dict[str, object]] = []
    for record in episodes.to_dict(orient="records"):
        execution_date = pd.Timestamp(record["start_date"])
        end_execution_date = pd.Timestamp(record["end_date"])
        start_location = int(index.get_loc(execution_date))
        end_location = int(index.get_loc(end_execution_date))
        if start_location <= 0:
            raise ValueError(f"episode has no prior activation signal: {execution_date}")

        activation_signal_date = index[start_location - 1]
        release_signal_date: pd.Timestamp | None = None
        release_execution_date: pd.Timestamp | None = None
        release_rsi: float | None = None
        release_vix: float | None = None
        if end_location + 1 < len(index):
            release_signal_date = end_execution_date
            release_execution_date = index[end_location + 1]
            release_rsi = float(daily.loc[release_signal_date, "rsi_14"])
            release_vix = float(daily.loc[release_signal_date, "vix_close"])

        record.update(
            {
                "activation_signal_date": _iso(activation_signal_date),
                "execution_date": _iso(execution_date),
                "signal_rsi_14": float(
                    daily.loc[activation_signal_date, "rsi_14"]
                ),
                "signal_vix_close": float(
                    daily.loc[activation_signal_date, "vix_close"]
                ),
                "release_signal_date": _iso(release_signal_date),
                "release_execution_date": _iso(release_execution_date),
                "release_signal_rsi_14": release_rsi,
                "release_signal_vix_close": release_vix,
            }
        )
        rows.append(record)

    output = pd.DataFrame(rows)
    ordered = [
        "event_id",
        "activation_signal_date",
        "execution_date",
        "release_signal_date",
        "release_execution_date",
        "signal_rsi_14",
        "signal_vix_close",
        "release_signal_rsi_14",
        "release_signal_vix_close",
        *[
            column
            for column in output.columns
            if column
            not in {
                "event_id",
                "activation_signal_date",
                "execution_date",
                "release_signal_date",
                "release_execution_date",
                "signal_rsi_14",
                "signal_vix_close",
                "release_signal_rsi_14",
                "release_signal_vix_close",
            }
        ],
    ]
    output.loc[:, ordered].to_csv(episode_path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_rsi_vix_adaptive_sgov_v4_9_research"
        ),
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    for scope in SCOPES:
        for variant in VARIANTS:
            _contextualize(output / scope, variant)

    manifest_path = output / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"] = {
        str(path.relative_to(output)): _sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != manifest_path
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "finalized_scopes": list(SCOPES),
                "finalized_variants": list(VARIANTS),
                "manifest_sha256": _sha256(manifest_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
