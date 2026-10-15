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
    inspect_source_retention,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/data/formal_model_data_sources_v1.yaml"),
    )
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--inspect", action="store_true", help="Read pinned source retention; no token, network or data refresh")
    args = parser.parse_args()
    if not args.inspect and (not args.source or args.output_root is None):
        parser.error("fetch requires --source and --output-root")
    try:
        if args.inspect:
            print(json.dumps(inspect_source_retention(args.registry, source_ids=args.source), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        receipt = fetch_governed_sources(
            registry_path=args.registry,
            source_ids=args.source,
            output_root=args.output_root,
            token=os.environ.get("GITHUB_TOKEN", ""),
            archive_ssh_key=os.environ.get("GOVERNED_SOURCE_ARCHIVE_SSH_KEY"),
        )
    except (GovernedActionsArtifactError, OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
