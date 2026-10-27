from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from src.governance.active_strategy_catalog import (
    DEFAULT_CATALOG_PATH as DEFAULT_STRATEGY_CATALOG,
    ActiveStrategyCatalogError,
)
from src.research.formal_replay_contract import REPLAY_IDS


def _render(payload: dict[str, Any] | str) -> None:
    if isinstance(payload, str):
        print(payload)
        return
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

    slice_cmd = data_commands.add_parser(
        "slice",
        help="Extract a parameterized research data slice and immutable receipt.",
    )
    slice_cmd.add_argument(
        "--market",
        required=True,
        choices=["cn", "us"],
        help="Market identifier (cn or us).",
    )
    slice_cmd.add_argument(
        "--pool",
        required=True,
        help="Governed candidate pool id (e.g. cn_selected_equities_v3).",
    )
    slice_cmd.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated symbols list (e.g. 000001,000338).",
    )
    slice_cmd.add_argument(
        "--start",
        required=True,
        help="Start date YYYY-MM-DD.",
    )
    slice_cmd.add_argument(
        "--end",
        required=True,
        help="End date YYYY-MM-DD.",
    )
    slice_cmd.add_argument(
        "--cutoff",
        required=True,
        help="Point-in-time as-of cutoff date YYYY-MM-DD.",
    )
    slice_cmd.add_argument(
        "--price-mode",
        default="anchored_adjusted",
        choices=["raw", "anchored_adjusted"],
        help="Price adjustment mode.",
    )
    slice_cmd.add_argument(
        "--fields",
        default="open,high,low,close,volume",
        help="Comma-separated required field list.",
    )
    slice_cmd.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path for receipt JSON.",
    )
    slice_cmd.add_argument(
        "--data-output",
        type=Path,
        default=None,
        help="Optional output path to export the sliced dataset as CSV.",
    )

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
        choices=[*REPLAY_IDS, "all"],
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

    study = research_commands.add_parser(
        "study", help="Discover, run and compare local research hypotheses."
    )
    study_actions = study.add_subparsers(dest="study_action", required=True)
    study_actions.add_parser("list", help="List the supported research-study template.")
    study_init = study_actions.add_parser("init", help="Write an editable research-study specification.")
    study_init.add_argument("--output", required=True, type=Path)
    study_run = study_actions.add_parser("run", help="Run a frozen study and retain its receipt.")
    study_run.add_argument("--spec", type=Path, help="Optional JSON study spec; defaults to built-in.")
    study_run.add_argument("--output", type=Path, help="Optional immutable receipt output path.")
    study_compare = study_actions.add_parser(
        "compare", help="Compare two completed receipts on identical frozen data."
    )
    study_compare.add_argument("left", type=Path)
    study_compare.add_argument("right", type=Path)

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

    acceptance = ops_commands.add_parser("acceptance", help="Summarize retained operating observations without refresh or training")
    acceptance.add_argument("--input-root", type=Path, required=True)
    acceptance.add_argument("--declarations", type=Path)
    acceptance.add_argument("--output", type=Path)
    acceptance.add_argument("--through", help="Completed cutoff YYYY-MM-DD; defaults to current completed market sessions")
    acceptance.add_argument("--collect-repository", help="Collect the latest completed formal attempt and prepare an unapproved review packet")
    acceptance.add_argument("--archive-repository", help="Retain the compact collected packet using the existing private archive key")

    build_ops = ops_commands.add_parser(
        "build",
        help="Materialize Strategy Operations and the system-health read model.",
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

    publish_ops = ops_commands.add_parser(
        "publish",
        help="Publish the generated Strategy Operations read model through GitHub OIDC.",
    )
    publish_ops.add_argument(
        "--input",
        type=Path,
        default=Path("data/research/strategy_operations/snapshots.json"),
    )

    personal = groups.add_parser(
        "personal",
        help="Audit and interface with personal investment holdings (read-only, zero privacy leak).",
    )
    personal_commands = personal.add_subparsers(dest="personal_command", required=True)
    audit = personal_commands.add_parser(
        "audit",
        help="Scan personal investment notes, check data readiness, without reading private finances.",
    )
    audit.add_argument(
        "--dir",
        type=Path,
        default=Path("D:/Documents/zhihaol/200_Area/Investment/Pool"),
        help="Path to personal investment pool directory.",
    )
    audit.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (table for human-readable markdown, json for structured data).",
    )
    audit.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write the output report.",
    )

    return parser


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    exit_code = 0
    errors: tuple[type[Exception], ...] = (
        OSError, json.JSONDecodeError, ActiveStrategyCatalogError,
    )

    try:
        if args.group == "data" and args.data_command == "list":
            from src.data.data_recipe_catalog import DataRecipeError, data_recipe_catalog

            errors += (DataRecipeError,)
            payload = data_recipe_catalog(root)
        elif args.group == "data" and args.data_command == "prepare":
            from src.data.data_recipe import DataRecipeError, prepare_data_recipe

            errors += (DataRecipeError,)
            payload = prepare_data_recipe(
                args.recipe,
                root=root,
                cutoff=args.cutoff,
                refresh=args.refresh,
                source_etf_bundle=args.source_etf_bundle,
            )
        elif args.group == "data" and args.data_command == "status":
            from src.data.data_recipe import DataRecipeError, data_recipe_status

            errors += (DataRecipeError,)
            payload = data_recipe_status(
                args.recipe,
                root=root,
                cutoff=args.cutoff,
            )
        elif args.group == "data" and args.data_command == "slice":
            from src.data.research_slice import (
                DataSliceRequest,
                ResearchDataSliceError,
                get_research_data_slice,
            )

            errors += (ResearchDataSliceError,)
            req = DataSliceRequest.from_dict({
                "market": args.market,
                "pool_id": args.pool,
                "symbols": args.symbols,
                "start_date": args.start,
                "end_date": args.end,
                "as_of_cutoff": args.cutoff,
                "price_mode": args.price_mode,
                "required_fields": args.fields,
            })
            res = get_research_data_slice(req, root=root)
            payload = res.receipt
            if args.output is not None:
                out_path = _resolve(root, args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            if args.data_output is not None and res.is_ready and res.data is not None:
                data_out_path = _resolve(root, args.data_output)
                data_out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_out_path = data_out_path.with_name(f".{data_out_path.name}.tmp")
                try:
                    res.data.to_csv(tmp_out_path, index=False)
                    tmp_out_path.replace(data_out_path)
                except Exception:
                    if tmp_out_path.is_file():
                        tmp_out_path.unlink()
                    raise
            if payload.get("status") == "blocked":
                exit_code = 10
        elif args.group == "research" and args.research_command == "run":
            from src.data.data_recipe import DataRecipeError, run_research_recipe

            errors += (DataRecipeError,)
            payload = run_research_recipe(
                args.command,
                recipe_id=args.recipe,
                root=root,
                cutoff=args.cutoff,
                refresh=args.refresh,
                source_etf_bundle=args.source_etf_bundle,
            )
        elif args.group == "research" and args.research_command == "replay":
            from src.research.formal_model_replay import FormalModelReplayError, replay_formal_models

            errors += (FormalModelReplayError,)
            payload = replay_formal_models(
                args.model,
                root=root,
                refresh_data=args.refresh_data,
            )
            if payload.get("decision") != "exact_replay":
                exit_code = 2
        elif args.group == "research" and args.research_command == "study":
            from src.research.study_workspace import (
                ResearchStudyError,
                compare_studies,
                initialize_study,
                run_study,
                study_catalog,
            )

            errors += (ResearchStudyError,)
            if args.study_action == "list":
                payload = study_catalog(root)
            elif args.study_action == "init":
                payload = initialize_study(_resolve(root, args.output))
            elif args.study_action == "run":
                payload = run_study(
                    _resolve(root, args.spec) if args.spec is not None else None,
                    root,
                    output=_resolve(root, args.output) if args.output is not None else None,
                )
                if payload["status"] == "blocked":
                    exit_code = 10
            elif args.study_action == "compare":
                payload = compare_studies(
                    _resolve(root, args.left), _resolve(root, args.right)
                )
            else:
                parser.error("unsupported study action")
                return 2
        elif args.group == "research" and args.research_command == "import-run":
            from src.artifacts.repository_run_store import RepositoryRunStoreError, import_local_run

            errors += (RepositoryRunStoreError,)
            payload = import_local_run(
                args.source,
                root=root,
                publish=args.publish,
                set_primary=args.set_primary,
            )
        elif args.group == "research" and args.research_command == "rebuild-index":
            from src.artifacts.repository_metadata_cache import RepositoryMetadataCacheError, rebuild_metadata_cache

            errors += (RepositoryMetadataCacheError,)
            payload = rebuild_metadata_cache(
                root=root,
                db_path=_resolve(root, args.output),
            )
        elif args.group == "ops" and args.ops_command == "record-decision":
            from src.governance.active_strategy_catalog import (
                load_active_strategy_catalog,
            )
            from src.artifacts.strategy_signal_ledger import (
                StrategySignalLedgerError, append_signal_evaluation, parse_optional_int,
            )

            errors += (ActiveStrategyCatalogError, StrategySignalLedgerError)
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
        elif args.group == "ops" and args.ops_command == "acceptance":
            from datetime import datetime, timezone
            import zipfile
            from src.artifacts.operating_acceptance import build_acceptance_report, collect_operating_review

            errors += (ValueError, zipfile.BadZipFile)
            readiness = None
            if args.archive_repository and not args.collect_repository:
                raise ValueError("private retention requires --collect-repository")
            if args.collect_repository:
                readiness = collect_operating_review(args.collect_repository, input_root=_resolve(root, args.input_root), repository_root=root, now_utc=datetime.now(timezone.utc), archive_repository=args.archive_repository)
            payload = build_acceptance_report(_resolve(root, args.input_root), declarations=_resolve(root, args.declarations) if args.declarations else None, through=args.through)
            if readiness is not None:
                payload["latest_attempt_readiness"] = readiness
            if args.output:
                target = _resolve(root, args.output)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        elif args.group == "ops" and args.ops_command == "build":
            from src.artifacts.strategy_operations import (
                StrategyOperationsError, build_operations_payload,
                validate_operations_payload, write_operations_payload,
            )
            from src.artifacts.system_health import (
                SystemHealthError, build_system_health, validate_system_health,
                write_system_health,
            )

            errors += (StrategyOperationsError, SystemHealthError)
            output = _resolve(root, args.output)
            formal_catalog = _resolve(root, args.formal_catalog)
            operations = build_operations_payload(
                formal_catalog=formal_catalog,
                strategy_catalog=_resolve(root, args.strategy_catalog),
                ledger_root=_resolve(root, args.ledger_root),
                generated_at=args.generated_at,
            )
            validate_operations_payload(operations)
            changed = write_operations_payload(output, operations)

            health_output = output.parent / "system-health.json"
            health = build_system_health(
                repository_root=root,
                formal_catalog=formal_catalog,
                formal_freshness=formal_catalog.parent / "freshness.json",
                operations=operations,
                model_data_readiness=root
                / "data/research/model_data_bundle_v1/model-data-readiness.json",
                generated_at=args.generated_at,
            )
            validate_system_health(health)
            health_changed = write_system_health(health_output, health)
            payload = {
                "path": output.relative_to(root).as_posix(),
                "changed": changed,
                "strategy_count": len(operations["records"]),
                "system_health_path": health_output.relative_to(root).as_posix(),
                "system_health_changed": health_changed,
                "system_health_state": health["state"],
                "research_only": True,
                "trade_ready": False,
            }
        elif args.group == "ops" and args.ops_command == "publish":
            from src.artifacts.strategy_operations_runtime import StrategyOperationsRuntimeError, publish_strategy_operations

            errors += (StrategyOperationsRuntimeError,)
            payload = publish_strategy_operations(_resolve(root, args.input))
        elif args.group == "personal" and args.personal_command == "audit":
            from src.research.personal_lens import PersonalLensError, scan_personal_investment_pool

            errors += (PersonalLensError,)
            report = scan_personal_investment_pool(pool_dir=args.dir, root=root)

            if args.format == "table":
                payload = (
                    f"{report.table_markdown}\n\n---\n"
                    f"**汇总统计**：已扫描 {report.total_scanned} 个标的 | 🟢 数据已就绪: {report.ready_count} | "
                    f"⚠️ 缺失切片: {report.missing_evidence_count} | 💵 现金储备: {report.cash_count} | "
                    f"🌐 跨市场: {report.other_market_count}\n"
                    f"*(治理铁律：research_only=true，零个人资金与账户隐私读取)*"
                )
            else:
                payload = report.to_dict()

            if args.output is not None:
                out_path = _resolve(root, args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_content = (
                    payload
                    if isinstance(payload, str)
                    else json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
                )
                out_path.write_text(out_content, encoding="utf-8")
        else:
            parser.error("unsupported command")
            return 2
    except errors as exc:
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
