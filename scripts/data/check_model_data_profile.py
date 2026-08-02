#!/usr/bin/env python3
"""Fail closed unless a model-data training profile is ready and hash-valid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.model_data_bundle import ModelDataBundleError
from src.data.model_data_profile import check_profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--expected-pool-id", default=None)
    parser.add_argument("--maximum-evidence-cutoff", default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        result = check_profile(
            args.bundle_root,
            args.profile,
            expected_pool_id=args.expected_pool_id,
            maximum_evidence_cutoff=args.maximum_evidence_cutoff,
        )
    except ModelDataBundleError as exc:
        print(
            json.dumps(
                {
                    "profile_id": args.profile,
                    "status": "blocked",
                    "reason": str(exc),
                    "research_only": True,
                    "trade_ready": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    rendered = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
