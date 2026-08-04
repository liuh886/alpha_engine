#!/usr/bin/env python3
"""Build 515180 canonical data with explicit provider-envelope evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.data.build_515180_canonical_bundle import (
    fetch_primary,
    parse_args,
    write_frame,
)
from scripts.data.fetch_515180_secondary_v2 import fetch_secondary_v2
from src.data.etf_515180_canonical import build_515180_bundle
from src.data.etf_515180_quality_v2 import apply_material_factor_quality

MAX_ENVELOPE_REPAIR_PCT = 0.002


def audit_and_repair_envelope(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Repair only small provider high/low envelope inconsistencies.

    Open, close and volume are immutable. High may only be raised and low may
    only be lowered to contain the provider open/close. Every change is sealed.
    """

    reference = raw.copy(deep=True)
    rows: list[dict[str, object]] = []
    repaired = raw.copy(deep=True)
    for index, row in reference.iterrows():
        required_high = max(float(row["open"]), float(row["close"]))
        required_low = min(float(row["open"]), float(row["close"]))
        high_gap = max(required_high - float(row["high"]), 0.0)
        low_gap = max(float(row["low"]) - required_low, 0.0)
        scale = max(abs(float(row["close"])), 1e-12)
        violation_pct = max(high_gap, low_gap) / scale
        if violation_pct <= 0.0:
            continue
        rows.append(
            {
                "date": pd.Timestamp(row["date"]),
                "provider_open": float(row["open"]),
                "provider_high": float(row["high"]),
                "provider_low": float(row["low"]),
                "provider_close": float(row["close"]),
                "high_gap": high_gap,
                "low_gap": low_gap,
                "violation_pct": violation_pct,
                "within_repair_tolerance": violation_pct <= MAX_ENVELOPE_REPAIR_PCT,
            }
        )
        if violation_pct > MAX_ENVELOPE_REPAIR_PCT:
            continue
        repaired.loc[index, "high"] = max(float(row["high"]), required_high)
        repaired.loc[index, "low"] = min(float(row["low"]), required_low)
    audit = pd.DataFrame(rows)
    blocked = (
        audit.loc[~audit["within_repair_tolerance"]]
        if not audit.empty
        else pd.DataFrame()
    )
    if not blocked.empty:
        dates = blocked["date"].dt.strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"provider OHLC envelope violations exceed tolerance: {dates}")
    return repaired, audit


def main() -> None:
    args = parse_args()
    output: Path = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    try:
        raw_reference, adjusted_close, actions, primary_meta = fetch_primary(
            args.start, args.cutoff
        )
        write_frame(output / "provider_reference_ohlcv.csv", raw_reference)
        raw, envelope_audit = audit_and_repair_envelope(raw_reference)
        write_frame(output / "provider_envelope_audit.csv", envelope_audit)
        secondary, secondary_meta = fetch_secondary_v2(
            args.start, args.cutoff, args.secondary_retries
        )
        bundle, quality = build_515180_bundle(
            raw_primary=raw,
            provider_adjusted_close=adjusted_close,
            corporate_actions=actions,
            raw_secondary=secondary,
            secondary_provider=(
                secondary_meta.get("provider") if secondary is not None else None
            ),
            provider_parameters={
                "primary": primary_meta,
                "secondary": secondary_meta,
                "envelope_policy": {
                    "max_repair_pct": MAX_ENVELOPE_REPAIR_PCT,
                    "open_close_volume_immutable": True,
                    "high_only_raised": True,
                    "low_only_lowered": True,
                    "repaired_rows": int(len(envelope_audit)),
                },
            },
            cutoff=args.cutoff,
        )
        bundle, quality = apply_material_factor_quality(bundle, quality)
        write_frame(output / "raw_ohlcv.csv", bundle.raw_bars)
        write_frame(output / "adjustment_factors.csv", bundle.adjustment_factors)
        write_frame(output / "adjusted_ohlcv.csv", bundle.adjusted_bars)
        write_frame(output / "corporate_actions.csv", bundle.corporate_actions)
        write_frame(output / "session_audit.csv", bundle.session_audit)
        write_frame(output / "provider_comparison.csv", bundle.provider_comparison)
        (output / "manifest.json").write_text(
            json.dumps(bundle.manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        report = [
            "# 515180.SH canonical ETF data",
            "",
            f"- Status: `{bundle.manifest['data_quality_status']}`",
            f"- Range: `{bundle.manifest['first_date']}` to `{bundle.manifest['last_date']}`",
            f"- Rows: `{bundle.manifest['rows']}`",
            f"- Adjusted SHA-256: `{bundle.manifest['adjusted_sha256']}`",
            f"- Manifest SHA-256: `{bundle.manifest['manifest_sha256']}`",
            f"- Provider envelope audit rows: `{len(envelope_audit)}`",
            f"- Material factor jumps: `{bundle.manifest['material_factor_jumps']}`",
            f"- Unexplained material jumps: `{bundle.manifest['unexplained_factor_jumps']}`",
            f"- Factor jump tolerance: `{bundle.manifest['factor_jump_tolerance']}`",
            f"- Secondary coverage: `{bundle.manifest['secondary_coverage']:.6f}`",
            f"- Open-return correlation: `{bundle.manifest['common_return_correlation']}`",
            f"- P99 open-return difference: `{bundle.manifest['p99_open_return_difference']}`",
            f"- Quality gates: `{json.dumps(quality.gates, ensure_ascii=False, sort_keys=True)}`",
            "",
            "Secondary data is audit-only. No rows are stitched or substituted.",
        ]
        (output / "report.md").write_text(
            "\n".join(report) + "\n", encoding="utf-8"
        )
        print(json.dumps(bundle.manifest, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        blocker = {
            "status": "data_blocked",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cutoff": args.cutoff,
        }
        (output / "data_blocked.json").write_text(
            json.dumps(blocker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    main()
