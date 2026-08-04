#!/usr/bin/env python3
"""Seal the final BYD canonical manifest after all data-quality stages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = args.canonical_dir
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    quality = manifest.get("secondary_quality")
    if not isinstance(quality, dict) or quality.get("quality_pass") is not True:
        raise RuntimeError("cannot seal manifest without a passing secondary audit")
    if manifest.get("unexplained_factor_jumps") != 0:
        raise RuntimeError("cannot seal manifest with unexplained factor jumps")
    if manifest.get("cross_provider_stitching") is not False:
        raise RuntimeError("cannot seal manifest when provider stitching is enabled")

    # Replace preliminary first-attempt metrics with the selected independent
    # provider's final metrics. This avoids carrying stale trial values into the
    # immutable data identity.
    manifest["common_return_correlation"] = quality["open_return_correlation"]
    manifest["close_return_correlation"] = quality["close_return_correlation"]
    manifest["mean_absolute_return_difference"] = quality[
        "mean_open_return_difference"
    ]
    manifest["return_differences_over_1pct"] = quality[
        "open_level_differences_over_1pct"
    ]
    manifest["common_return_rows"] = quality["common_rows"]
    manifest["data_quality_status"] = "canonical_v1_pass"
    manifest["trade_ready"] = False
    manifest["model_promotion_allowed"] = False
    manifest["manifest_sha256"] = ""
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(payload).hexdigest()
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with (root / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("\n## Sealed canonical status\n\n")
        handle.write("- Data quality status: `canonical_v1_pass`\n")
        handle.write(f"- Manifest SHA-256: `{manifest['manifest_sha256']}`\n")
        handle.write("- Model promotion remains disabled; this bundle only establishes the research data base.\n")
    print(
        json.dumps(
            {
                "data_quality_status": manifest["data_quality_status"],
                "manifest_sha256": manifest["manifest_sha256"],
                "secondary_provider": manifest["secondary_provider"],
                "quarantined_open_rows": manifest["quarantined_open_rows"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
