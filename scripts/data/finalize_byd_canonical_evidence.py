#!/usr/bin/env python3
"""Finalize BYD canonical evidence with economic factor-jump semantics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.data.byd_canonical_bundle import audit_adjustment_events, dataframe_sha256

FACTOR_JUMP_TOLERANCE = 1e-6


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = args.canonical_dir
    raw = pd.read_csv(root / "raw_ohlcv.csv", parse_dates=["date"])
    adjusted = pd.read_csv(root / "adjusted_ohlcv.csv", parse_dates=["date"])
    factors = pd.read_csv(root / "adjustment_factors.csv", parse_dates=["date"])
    actions = pd.read_csv(root / "corporate_actions.csv", parse_dates=["date"])
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    audit = audit_adjustment_events(
        factors,
        actions,
        jump_tolerance=FACTOR_JUMP_TOLERANCE,
    )
    audit.to_csv(
        root / "factor_event_audit.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )

    # Yahoo auto_adjust=False reports a raw/reference volume series already
    # normalized for its split history. Cash-dividend price factors must not
    # inversely scale volume. Preserve the primary provider's volume exactly.
    adjusted = adjusted.drop(columns=["volume"], errors="ignore").merge(
        raw[["date", "volume"]],
        on="date",
        how="left",
        validate="one_to_one",
    )
    if adjusted["volume"].isna().any():
        raise RuntimeError("adjusted rows missing primary raw volume")
    adjusted.to_csv(
        root / "adjusted_ohlcv.csv",
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )

    jumps = audit.loc[audit["factor_jump"]].copy()
    manifest.update(
        {
            "factor_jump_tolerance": FACTOR_JUMP_TOLERANCE,
            "factor_jump_count": int(len(jumps)),
            "unexplained_factor_jumps": int(jumps["unexplained_jump"].sum()),
            "volume_adjustment_method": "preserve_primary_provider_volume_no_cash_dividend_scaling",
            "raw_semantics": "provider_reported_ohlcv_auto_adjust_false; dividend_unadjusted; split_normalization_follows_provider_history",
            "adjusted_sha256": dataframe_sha256(adjusted),
            "factor_event_audit_sha256": dataframe_sha256(audit),
        }
    )
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    with (root / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\n## Finalized adjustment semantics\n\n")
        handle.write(
            f"- Economically material factor-jump tolerance: `{FACTOR_JUMP_TOLERANCE}`\n"
        )
        handle.write(f"- Material factor jumps: `{len(jumps)}`\n")
        handle.write(
            f"- Unexplained material factor jumps: `{manifest['unexplained_factor_jumps']}`\n"
        )
        handle.write(
            "- Adjusted volume preserves primary provider volume; cash-dividend price factors do not rescale volume.\n"
        )

    if manifest["unexplained_factor_jumps"] != 0:
        raise RuntimeError(
            f"unexplained material factor jumps: {manifest['unexplained_factor_jumps']}"
        )
    print(
        json.dumps(
            {
                "factor_jump_count": manifest["factor_jump_count"],
                "unexplained_factor_jumps": manifest["unexplained_factor_jumps"],
                "adjusted_sha256": manifest["adjusted_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
