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
from src.artifacts.strategy_operations import (
    StrategyOperationsError,
    build_operations_payload,
    validate_operations_payload,
    write_operations_payload,
)
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    append_signal_evaluation,
    parse_optional_int,
)
from src.data.data_recipe import (
    DataRecipeError,
    data_recipe_catalog,
    data_recipe_status,
    prepare_data_recipe,
    run_research_recipe,
)
from src.governance.active_strategy_catalog import (
    DEFAULT_CATALOG_PATH as DEFAULT_STRATEGY_CATALOG,
    ActiveStrategyCatalogError,
    load_active_strategy_catalog,
)
from src.research.formal_model_replay import (
    BYD_REPLAY_ID,
    QQQ_REPLAY_ID,
    FormalModelReplayError,
    replay_formal_models,
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
        description="Governed Alpha Engine data, research and strategy operations.",
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

    replay = research_commands.add_parser(
        "replay",
        help="Exactly reproduce an accepted rules-based formal baseline locally.",
    )
    replay.add_argument(
        "model",
        choices=[QQQ_REPLAY_ID, BYD_REPLAY_ID, "all"],
        help="Accepted formal baseline to replay.",
    )
    replay.add_argument(
        "--refresh-data",
        action="store_true",
        help=(
            "Rebuild the governed QQQ exact-cutoff data recipe instead of reusing "
            "a verified local cache."
        ),
    )

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

    ops = groups.add_parser("ops", help="Record decisions and publish current strategy state.")
    ops_commands = ops.add_subparsers(dest="ops_command", required=True)

    record_decision = ops_commands.add_parser(
        "record-decision",
        help="Append one immutable active-strategy decision evaluation.",
    )
    record_decision.add_argument("--model-version-id", required=True)
    record_decision.add_argument("--signal-json", type=Path, required=True)
    record_decision.add_argument(
        "--strategy-catalog",
        type=Path,
        default=DEFAULT_STRATEGY_CATALOG,
    )
    record_decision.add_argument(
        "--ledger-root",
        type=Path,
        default=Path("data/research/strategy_signal_ledgers"),
    )
    record_decision.add_argument("--delivery-status", required=True)
    record_decision.add_argument("--github-issue-number", default="")
    record_decision.add_argument("--telegram-message-id", default="")
    record_decision.add_argument("--delivery-error", default="")
    record_decision.add_argument("--workflow-run-id", required=True)
    record_decision.add_argument("--commit-sha", required=True)
    record_decision.add_argument("--created-at-utc", required=True)

    build_ops = ops_commands.add_parser(
        "build",
        help="Materialize the current Strategy Console read model from formal identity and decisions.",
    )
    build_ops.add_argument(
        "--formal-catalog",
        type=Path,
        default=Path("data/research/formal_model_runs/catalog.json"),
    )
    build_ops.add_argument(
        "--strategy-catalog",
        type=Path,
        default=DEFAULT_STRATEGY_CATALOG,
    )
    build_ops.add_argument(
        "--ledger-root",
        type=Path,
        default=Path("data/research/strategy_signal_ledgers"),
    )
    build_ops.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/strategy_operations/snapshots.json"),
    )
    build_ops.add_argument("--generated-at", required=True)
    return parser


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    exit_code = 0

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
        elif args.group == "research" and args.research_command == "replay":
            payload = replay_formal_models(
                args.model,
                root=root,
                refresh_data=args.refresh_data,
            )
            if payload.get("decision") != "exact_replay":
                exit_code = 2
        elif args.group == "research" and args.research_command == "import-run":
            payload = import_local_run(
                args.source,
                root=root,
                publish=args.publish,
                set_primary=args.set_primary,
            )
        elif args.group == "research" and args.research_command == "rebuild-index":
            payload = rebuild_metadata_cache(
                root=root,
                db_path=_resolve(root, args.output),
            )
        elif args.group == "ops" and args.ops_command == "record-decision":
            strategy_catalog = _resolve(root, args.strategy_catalog)
            active = load_active_strategy_catalog(strategy_catalog)
            strategy = active.by_model_version_id.get(args.model_version_id)
            if strategy is None:
                raise ActiveStrategyCatalogError(
                    f"model is not an active strategy: {args.model_version_id}"
                )
            signal_path = _resolve(root, args.signal_json)
            signal = json.loads(signal_path.read_text(encoding="utf-8"))
            if not isinstance(signal, dict):
                raise StrategySignalLedgerError("signal JSON root must be an object")
            ledger_root = _resolve(root, args.ledger_root) / strategy.model_version_id
            record_path = append_signal_evaluation(
                ledger_root=ledger_root,
                model_version_id=strategy.model_version_id,
                signal=signal,
                delivery_status=args.delivery_status,
                github_issue_number=parse_optional_int(
                    args.github_issue_number,
                    label="github_issue_number",
                ),
                telegram_message_id=parse_optional_int(
                    args.telegram_message_id,
                    label="telegram_message_id",
                ),
                delivery_error=args.delivery_error or None,
                workflow_run_id=args.workflow_run_id,
                commit_sha=args.commit_sha,
                created_at_utc=args.created_at_utc,
            )
            payload = {
                "strategy_id": strategy.strategy_id,
                "model_version_id": strategy.model_version_id,
                "record_path": record_path.relative_to(root).as_posix(),
                "research_only": True,
                "trade_ready": False,
            }
        elif args.group == "ops" and args.ops_command == "build":
            output = _resolve(root, args.output)
            operations = build_operations_payload(
                formal_catalog=_resolve(root, args.formal_catalog),
                strategy_catalog=_resolve(root, args.strategy_catalog),
                ledger_root=_resolve(root, args.ledger_root),
                generated_at=args.generated_at,
            )
            validate_operations_payload(operations)
            changed = write_operations_payload(output, operations)
            payload = {
                "path": output.relative_to(root).as_posix(),
                "changed": changed,
                "strategy_count": len(operations["records"]),
                "research_only": True,
                "trade_ready": False,
            }
        else:
            parser.error("unsupported command")
            return 2
    except (
        DataRecipeError,
        FormalModelReplayError,
        RepositoryRunStoreError,
        RepositoryMetadataCacheError,
        ActiveStrategyCatalogError,
        StrategySignalLedgerError,
        StrategyOperationsError,
        OSError,
        json.JSONDecodeError,
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
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
