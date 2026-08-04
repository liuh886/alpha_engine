#!/usr/bin/env python3
"""Run exploratory BYD factor discovery on a canonical adjusted bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.byd_factor_discovery_v2 import PERIODS, discover_factors


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _report(result, manifest: dict[str, object]) -> str:
    shortlist = result.shortlist.copy()
    columns = [
        "factor",
        "orientation",
        "period_sign_consistency",
        "median_oriented_ic",
        "worst_oriented_ic",
        "mean_abs_ic",
        "stability_score",
    ]
    table = (
        shortlist[columns].head(25).to_markdown(index=False, floatfmt=".4f")
        if not shortlist.empty
        else "No factor passed the frozen exploratory shortlist gates."
    )
    return "\n".join(
        [
            "# BYD canonical factor discovery v2",
            "",
            "> Exploratory only. The 2025+ period has already been observed and is not an untouched promotion holdout.",
            "",
            "## Data identity",
            "",
            f"- Canonical schema: `{manifest.get('schema_version')}`",
            f"- Cutoff: `{manifest.get('cutoff')}`",
            f"- Adjusted SHA-256: `{manifest.get('adjusted_sha256')}`",
            f"- Cross-provider stitching: `{manifest.get('cross_provider_stitching')}`",
            "",
            "## Evaluation periods",
            "",
            f"`{json.dumps(PERIODS, ensure_ascii=False)}`",
            "",
            "## Stable factor shortlist",
            "",
            table,
            "",
            "## Interpretation rules",
            "",
            "- A positive orientation means a larger factor value is associated with a higher future 10-session open-to-open return.",
            "- A negative orientation means the economic factor should be inverted before use.",
            "- Shortlisting requires sign consistency in at least four of five periods, median oriented IC >= 0.02, and worst-period oriented IC >= -0.01.",
            "- This report discovers hypotheses; it does not define a tradable model or reuse the old holdout as fresh evidence.",
        ]
    ) + "\n"


def main() -> None:
    args = _parse_args()
    canonical = args.canonical_dir
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((canonical / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("cross_provider_stitching") is not False:
        raise RuntimeError("canonical bundle permits cross-provider stitching")
    adjusted = pd.read_csv(canonical / "adjusted_ohlcv.csv")
    result = discover_factors(adjusted)
    result.diagnostics.to_csv(
        output / "factor_diagnostics.csv", index=False, float_format="%.12f"
    )
    result.shortlist.to_csv(
        output / "factor_shortlist.csv", index=False, float_format="%.12f"
    )
    result.correlation.to_csv(
        output / "factor_correlation.csv", float_format="%.12f"
    )
    result.dataset.reset_index().to_csv(
        output / "factor_dataset.csv", index=False, float_format="%.12f"
    )
    summary = {
        "status": "exploratory_factor_discovery_complete",
        "trade_ready": False,
        "canonical_adjusted_sha256": manifest.get("adjusted_sha256"),
        "factor_count": int(len(result.diagnostics)),
        "shortlist_count": int(len(result.shortlist)),
        "top_factors": result.shortlist["factor"].head(20).tolist(),
        "periods": PERIODS,
        "fresh_holdout_available": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output / "report.md").write_text(_report(result, manifest), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
