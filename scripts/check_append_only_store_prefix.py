#!/usr/bin/env python3
"""Verify that a reproduced prospective store preserves accepted history."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.artifacts.append_only_store import validate_append_only_store_prefix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    validate_append_only_store_prefix(args.current, args.candidate)
    print("Append-only prospective store prefix is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
