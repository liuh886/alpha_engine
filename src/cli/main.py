from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from src.artifacts.repository_metadata_cache import (
    RepositoryMetadataCacheError,
    rebuild_metadata_cache,
)
from src.artifacts.repository_run_store import (
    RepositoryRunStoreError,
    import_local_run,
)
from src.data.data_recipe import (
    DataRecipeError,
    data_recipe_catalog,
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

    data_commands.add_parser(
        "list",
        help="List recipes and research commands declared by the recipe registry.",
    )

    prepare = data_commands.add_parser(
        "prepare",
        help="Build or reuse a governed dataset recipe.",
    )
    prepare.add_argument("recipe")
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
    status.add_argument("recipe")
    status.add_argument("--cutoff", default=None)

    research = groups.add_parser("research", help="Run governed research workflows.")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    run = research_commands.add_parser(
        "run",
        help="Prepare governed data, enforce the profile gate, then run research.",
    )
    run.add_argument("command")
    run.add_argument("--recipe", default="qqq-rotation")
    run.add_argument("--cutoff", default=None)
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--source-etf-bundle", type=Path, default=None)

    import_run = research_commands.add_parser(
        "import-run",
        help="Validate a local training/backtest run and copy it into data/research/runs.",
    )
    import_run.add_argument("source", type=Path)
    import_run.add_argument(
        "--publish",
        action="store_true",
        help="Add the imported run to data/research/catalog.json for bundle publication.",
    )
    import_run.add_argument(
        "--set-primary",
        action="store_true",
        help="Attach the run as the published model's primary frontend backtest.",
    )

    rebuild_index = research_commands.add_parser(
        "rebuild-index",
        help="Rebuild the disposable local metadata.db from data/research.",
    )
    rebuild_index.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/metadata/metadata.db"),
        help="SQLite cache path relative to the repository root unless absolute.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.group == "data" and args.data_command == "list":
            payload = data_recipe_catalog(root)
        elif args.group == "data" and args.data_command == "prepare":
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
        elif args.group == "research" and args.research_command == "import-run":
            payload = import_local_run(
                args.source,
                root=root,
                publish=args.publish,
                set_primary=args.set_primary,
            )
        elif args.group == "research" and args.research_command == "rebuild-index":
            output = args.output
            if not output.is_absolute():
                output = root / output
            payload = rebuild_metadata_cache(root=root, db_path=output)
        else:
            parser.error("unsupported command")
            return 2
    except (
        DataRecipeError,
        RepositoryRunStoreError,
        RepositoryMetadataCacheError,
    ) as exc:
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
