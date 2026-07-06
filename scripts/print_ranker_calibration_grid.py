"""Print the default ranker calibration grid manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.ranker_calibration_grid import build_ranker_calibration_grid, grid_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    manifest = grid_manifest(build_ranker_calibration_grid())
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
