#!/usr/bin/env python3
"""Verify that GitHub Pages serves the expected formal Alpha Engine release."""

from __future__ import annotations

import argparse
import json

from src.artifacts.pages_release_verification import verify_with_retries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--attempts", type=int, default=24)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()

    receipt = verify_with_retries(
        base_url=args.base_url,
        expected_commit=args.expected_commit,
        attempts=args.attempts,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
