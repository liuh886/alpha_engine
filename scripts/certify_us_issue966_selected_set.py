#!/usr/bin/env python3
"""Certify the selected Issue #966 US feature set and its one skew control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.us_issue966_selected_certification import certify_selected_feature_set


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    receipt = certify_selected_feature_set(
        args.spec,
        args.decision,
        args.observations,
        output_path=args.output,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
