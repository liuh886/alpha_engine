#!/usr/bin/env python3
"""Select the smallest passing Issue #966 Phase-6 US feature subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.us_issue966_minimal_set import (
    select_minimal_feature_set,
    write_minimal_feature_set_decision,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--stage-b", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--redundancy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    decision = select_minimal_feature_set(
        args.spec,
        args.stage_b,
        args.observations,
        args.redundancy,
    )
    write_minimal_feature_set_decision(decision, args.output)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
