#!/usr/bin/env python3
"""Fetch exact reviewed Actions artifacts for the formal model-data bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.data.governed_actions_artifact import (
    GovernedActionsArtifactError,
    fetch_governed_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/data/formal_model_data_sources_v1.yaml"),
    )
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = fetch_governed_sources(
            registry_path=args.registry,
            source_ids=args.source,
            output_root=args.output_root,
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
    except (GovernedActionsArtifactError, OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
