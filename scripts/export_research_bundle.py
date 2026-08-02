from __future__ import annotations

import argparse
from pathlib import Path

from src.artifacts.research_bundle import BundleBuildError, build_research_bundle, verify_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a versioned Alpha Engine research bundle.")
    parser.add_argument("--source", default="artifacts/site", help="Static export source directory")
    parser.add_argument("--output", default="artifacts/research-bundle", help="Bundle output directory")
    parser.add_argument("--title", default="Alpha Engine Research Bundle")
    args = parser.parse_args()

    try:
        manifest = build_research_bundle(Path(args.source), Path(args.output), title=args.title)
        verified = verify_bundle(Path(args.output))
    except BundleBuildError as exc:
        parser.error(str(exc))
        return 2

    print(f"bundle_id={manifest['bundle_id']}")
    print(f"artifacts={len(verified)}")
    print(f"output={Path(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
