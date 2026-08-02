from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from src.data.data_recipe import (
    DataRecipeError,
    data_recipe_status,
    prepare_data_recipe,
    run_research_recipe,
)


def _render(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha",
        description="Governed Alpha Engine data and research workflows.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current directory.",
    )
    groups = parser.add_subparsers(dest="group", required=True)

    data = groups.add_parser("data", help="Prepare and inspect governed datasets.")
    data_commands = data.add_subparsers(dest="data_command", required=True)

    prepare = data_commands.add_parser(
        "prepare",
        help="Build or reuse a governed dataset recipe.",
    )
    prepare.add_argument("recipe", choices=("qqq-rotation",))
    prepare.add_argument("--cutoff", default=None)
    prepare.add_argument("--refresh", action="store_true")
    prepare.add_argument(
        "--source-etf-bundle",
        type=Path,
        default=None,
        help="Reuse an already-built central ETF artifact instead of fetching it.",
    )

    status = data_commands.add_parser(
        "status",
        help="Verify the current cached dataset recipe and profile gate.",
    )
    status.add_argument("recipe", choices=("qqq-rotation",))
    status.add_argument("--cutoff", default=None)

    research = groups.add_parser("research", help="Run governed research workflows.")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    run = research_commands.add_parser(
        "run",
        help="Prepare governed data, enforce the profile gate, then run research.",
    )
    run.add_argument(
        "command",
        choices=("qqqi-vxn-v4.1", "qqqi-vxn-v4.2"),
    )
    run.add_argument("--recipe", default="qqq-rotation", choices=("qqq-rotation",))
    run.add_argument("--cutoff", default=None)
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--source-etf-bundle", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.group == "data" and args.data_command == "prepare":
            payload = prepare_data_recipe(
                args.recipe,
                root=root,
                cutoff=args.cutoff,
                refresh=args.refresh,
                source_etf_bundle=args.source_etf_bundle,
            )
        elif args.group == "data" and args.data_command == "status":
            payload = data_recipe_status(
                args.recipe,
                root=root,
                cutoff=args.cutoff,
            )
        elif args.group == "research" and args.research_command == "run":
            payload = run_research_recipe(
                args.command,
                recipe_id=args.recipe,
                root=root,
                cutoff=args.cutoff,
                refresh=args.refresh,
                source_etf_bundle=args.source_etf_bundle,
            )
        else:
            parser.error("unsupported command")
            return 2
    except DataRecipeError as exc:
        _render(
            {
                "status": "blocked",
                "reason": str(exc),
                "research_only": True,
                "trade_ready": False,
            }
        )
        return 2

    _render(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
