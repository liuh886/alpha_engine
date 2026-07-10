"""Prepare a validated structured 10D research contract.

This command is intentionally Qlib-free and contract-only. It validates the
selected market/universe/factor/candidate/evaluation settings and writes the
standard preparation artifacts. It does not train a model or dispatch an
existing runner.

Usage:
    python scripts/run_research_paradigm.py \
      --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml \
      --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _resolve_root(spec_path: str, explicit_root: str | None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    resolved_spec = Path(spec_path).resolve()
    for parent in resolved_spec.parents:
        if (parent / "configs").is_dir() and (parent / "src").is_dir():
            return parent
    return Path.cwd()


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="Path to paradigm YAML")
    parser.add_argument("--root", default=None, help="Repository root")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional parent directory for prepared run artifacts",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and materialize the contract without Qlib or training",
    )
    args = parser.parse_args(argv)

    if not args.dry_run:
        print(
            "ERROR: --dry-run is required. Spec-bound model execution is not "
            "implemented in this PR.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    root = _resolve_root(args.spec, args.root)

    from src.research.paradigm import (
        load_research_paradigm_spec,
        run_research_paradigm,
    )

    spec = load_research_paradigm_spec(args.spec)
    result = run_research_paradigm(
        spec,
        root=root,
        dry_run=True,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
