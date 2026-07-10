"""Run a structured 10D research paradigm from a YAML spec.

Usage::

    # Dry-run (Qlib-free — validates config, writes manifests, frontend payload)
    python scripts/run_research_paradigm.py --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml --dry-run

    # Execute the existing CN runner and normalize artifacts
    python scripts/run_research_paradigm.py --spec configs/research_paradigms/cn_10d_csi300_baseline.yaml --execute-existing-runner

    # Custom output directory
    python scripts/run_research_paradigm.py --spec configs/research_paradigms/us_10d_qqq_baseline.yaml --dry-run --output-dir /custom/path

Exactly one execution mode (--dry-run or --execute-existing-runner) must be
specified.  The script fails closed if neither or both are given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _resolve_root(args: argparse.Namespace) -> Path:
    if args.root:
        return Path(args.root).resolve()
    # Default: resolve from the spec file's grandparent or cwd
    if args.spec:
        spec_path = Path(args.spec).resolve()
        # Walk up to find project root (directory containing configs/ and src/)
        for parent in spec_path.parents:
            if (parent / "configs").is_dir() and (parent / "src").is_dir():
                return parent
    return Path.cwd()


def _resolve_execution_mode(args: argparse.Namespace) -> str | None:
    """Determine execution mode from the market in the spec.

    When ``--execute-existing-runner`` is set, looks at the spec's
    market to dispatch: ``cn`` → ``cn`` runner, ``us`` → unsupported
    (fails closed).
    """
    if not args.execute_existing_runner:
        return None
    # Quick peek at the market to dispatch
    import yaml

    spec_path = Path(args.spec).resolve()
    with open(spec_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    market = str(data.get("market", "")).lower()
    if market == "cn":
        return "cn"
    raise ValueError(
        f"--execute-existing-runner does not yet support market '{market}'. "
        f"Only 'cn' (via the #91 CN feature-quality runner) is supported."
    )


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Path to research paradigm YAML spec (required)",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Project root directory (auto-detected from spec location if omitted)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override artifacts output directory (default: <root>/artifacts/research_runs/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Qlib-free dry run — validate config, write manifests and frontend payload only",
    )
    parser.add_argument(
        "--execute-existing-runner",
        action="store_true",
        default=False,
        help="Execute the existing CN #91 runner and normalize artifacts",
    )
    parser.add_argument(
        "--help-execution-modes",
        action="store_true",
        default=False,
        help="Print detailed execution mode help and exit",
    )

    args = parser.parse_args(argv)

    if args.help_execution_modes:
        print(__doc__)
        return {"status": "help_printed"}

    # Exactly one execution mode must be explicit
    if args.dry_run and args.execute_existing_runner:
        print(
            "ERROR: Exactly one execution mode must be specified. "
            "Use --dry-run OR --execute-existing-runner, not both.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.dry_run and not args.execute_existing_runner:
        print(
            "ERROR: No execution mode specified. "
            "Use --dry-run for Qlib-free config validation, "
            "or --execute-existing-runner for execution.",
            file=sys.stderr,
        )
        sys.exit(1)

    root = _resolve_root(args)

    # Load spec
    from src.research.paradigm import ResearchParadigmSpec, run_research_paradigm

    spec = ResearchParadigmSpec.from_yaml(args.spec)

    execution_mode = _resolve_execution_mode(args)

    result = run_research_paradigm(
        spec,
        root=root,
        dry_run=args.dry_run,
        execution_mode=execution_mode,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
