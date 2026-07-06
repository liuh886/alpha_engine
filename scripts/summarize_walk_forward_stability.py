"""Summarize fixed-ten-day walk-forward evidence JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.walk_forward_stability import summarize_walk_forward_reports


def _read_json_files(paths: list[Path]) -> list[dict[str, object]]:
    payloads = []
    for path in paths:
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="One or more run_10d_experiment evidence JSON files.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional output JSON path.")
    parser.add_argument("--min-windows", type=int, default=3)
    args = parser.parse_args()

    summary = summarize_walk_forward_reports(_read_json_files(args.paths), min_windows=args.min_windows)
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
