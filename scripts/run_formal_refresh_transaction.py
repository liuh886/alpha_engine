"""Plan, assemble, and finalize the catalog-driven formal refresh transaction."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from src.artifacts.formal_refresh import (
    FormalRefreshError,
    accepted_records,
    build_plan,
    common_provider_cutoff,
    finalize_candidate_tree,
    load_object,
    sha256,
    write_object,
)
from src.governance.active_strategy_catalog import (
    ActiveStrategyCatalogError,
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)

RANKER_MTM_MODELS = (("cn_x1_1", "cn"),)
TASK_RECEIPT_SCHEMA = "formal_strategy_refresh_receipt_v1"
PLAN_SCHEMA = "formal_refresh_plan_v2"
FAN_IN_SCHEMA = "formal_strategy_fan_in_v1"
SUCCESS_STATES = {"current_no_change", "refreshed"}


def _cutoffs(us_manifest: Path, cn_manifest: Path) -> dict[str, str]:
    return {
        "us": common_provider_cutoff(load_object(us_manifest), market="us"),
        "cn": common_provider_cutoff(load_object(cn_manifest), market="cn"),
    }


def _iso_date(value: object, *, label: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise FormalRefreshError(f"invalid {label}: {value!r}") from exc


def _latest_settled_performance_end(package: Mapping[str, object]) -> str:
    freshness = package.get("freshness")
    if isinstance(freshness, Mapping):
        realized = freshness.get("latest_realized_holding_end")
        if realized:
            return _iso_date(realized, label="latest_realized_holding_end")

    report = package.get("report")
    if not isinstance(report, list) or not report:
        raise FormalRefreshError("formal ranker report is missing")
    latest = report[-1]
    if not isinstance(latest, Mapping):
        raise FormalRefreshError("latest formal ranker report row is invalid")
    end = latest.get("holding_end_date") or latest.get("date")
    return _iso_date(end, label="latest settled performance end")


def _has_current_provisional_mtm(
    package: Mapping[str, object],
    *,
    cutoff: str,
) -> bool:
    provisional = package.get("provisional_mtm")
    if not isinstance(provisional, Mapping):
        return False
    row = provisional.get("performance_row")
    return bool(
        provisional.get("schema_version") == "ranker_provisional_mtm_v1"
        and provisional.get("as_of") == cutoff
        and provisional.get("research_only") is True
        and provisional.get("trade_ready") is False
        and isinstance(row, Mapping)
        and row.get("provisional_mtm") is True
        and row.get("settlement_status") == "provisional_mtm"
        and row.get("holding_end_date") == cutoff
    )


def _mtm_refresh_model_ids(
    formal_root: Path,
    *,
    cutoffs: Mapping[str, str],
) -> tuple[str, ...]:
    required: list[str] = []
    for model_id, market in RANKER_MTM_MODELS:
        package_path = formal_root / f"{model_id}.json"
        if not package_path.is_file():
            continue
        package = load_object(package_path)
        target = _iso_date(cutoffs[market], label=f"{market} MTM cutoff")
        settled_end = _latest_settled_performance_end(package)
        if settled_end > target:
            raise FormalRefreshError(
                f"settled performance exceeds target cutoff for {model_id}: "
                f"{settled_end} > {target}"
            )
        if settled_end < target and not _has_current_provisional_mtm(
            package,
            cutoff=target,
        ):
            required.append(model_id)
    return tuple(required)


def build_task_plan(
    *,
    formal_root: Path,
    formal_v2_catalog: Path,
    cutoffs: Mapping[str, str],
    generated_at: str,
) -> dict[str, Any]:
    """Build a side-effect-free active-strategy execution matrix."""

    active = load_active_strategy_catalog()
    formal_v2 = load_object(formal_v2_catalog)
    try:
        assert_formal_catalog_matches_active_strategies(formal_v2, active)
    except ActiveStrategyCatalogError as exc:
        raise FormalRefreshError(str(exc)) from exc

    formal_plan = build_plan(
        formal_root,
        target_cutoffs=cutoffs,
        generated_at=generated_at,
    )
    formal_ids = {record.model_id for record in formal_plan.models}
    stale_ids = set(formal_plan.stale_model_ids)
    mtm_ids = set(_mtm_refresh_model_ids(formal_root, cutoffs=cutoffs))

    tasks: list[dict[str, Any]] = []
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        tasks.append(
            {
                "strategy_id": strategy.strategy_id,
                "model_family_id": strategy.model_family_id,
                "model_version_id": model_id,
                "model_kind": strategy.model_kind,
                "market": strategy.market,
                "planned_provider_cutoff": str(cutoffs[strategy.market]),
                "publication_input": (
                    "formal_v1" if model_id in formal_ids else "native_bundle_v2"
                ),
                "formal_refresh_required": model_id in stale_ids,
                "mtm_refresh_required": model_id in mtm_ids,
            }
        )

    return {
        "schema_version": PLAN_SCHEMA,
        "generated_at": generated_at,
        "target_cutoffs": dict(sorted(cutoffs.items())),
        "active_strategy_ids": [row.strategy_id for row in active.strategies],
        "active_model_version_ids": list(active.active_model_version_ids),
        "formal_v1_model_ids": [record.model_id for record in formal_plan.models],
        "stale_model_ids": list(formal_plan.stale_model_ids),
        "mtm_refresh_model_ids": sorted(mtm_ids),
        "refresh_required": bool(stale_ids or mtm_ids),
        "tasks": tasks,
        "research_only": True,
        "trade_ready": False,
    }


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _validate_task_receipt(
    task: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    if receipt.get("schema_version") != TASK_RECEIPT_SCHEMA:
        raise FormalRefreshError(
            f"invalid strategy receipt schema for {task.get('strategy_id')}"
        )
    bindings = (
        "strategy_id",
        "model_family_id",
        "model_version_id",
        "model_kind",
        "market",
        "planned_provider_cutoff",
        "publication_input",
    )
    for field in bindings:
        if receipt.get(field) != task.get(field):
            raise FormalRefreshError(
                f"strategy receipt binding mismatch for {task.get('strategy_id')}: {field}"
            )
    if receipt.get("research_only") is not True or receipt.get("trade_ready") is not False:
        raise FormalRefreshError(
            f"strategy receipt research boundary changed: {task.get('strategy_id')}"
        )
    status = str(receipt.get("execution_status") or "")
    if status not in SUCCESS_STATES:
        raise FormalRefreshError(
            f"strategy task is not publishable: {task.get('strategy_id')}={status or 'missing'}"
        )


def assemble_strategy_results(
    *,
    plan_path: Path,
    strategy_results_root: Path,
    current_root: Path,
    candidate_root: Path,
    current_preview_root: Path,
    candidate_preview_root: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Atomically fan in all expected strategy receipts and candidate outputs."""

    plan = load_object(plan_path)
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise FormalRefreshError("unsupported formal refresh plan schema")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise FormalRefreshError("formal refresh plan has no active strategy tasks")

    expected = {
        str(task.get("strategy_id")): task
        for task in tasks
        if isinstance(task, Mapping) and task.get("strategy_id")
    }
    if len(expected) != len(tasks):
        raise FormalRefreshError("formal refresh plan contains duplicate strategy tasks")

    observed_dirs = {
        path.name
        for path in strategy_results_root.iterdir()
        if path.is_dir() and (path / "receipt.json").is_file()
    }
    if observed_dirs != set(expected):
        raise FormalRefreshError(
            "strategy result membership mismatch: "
            f"expected={sorted(expected)}, observed={sorted(observed_dirs)}"
        )

    _copy_tree(current_root, candidate_root)
    _copy_tree(current_preview_root, candidate_preview_root)

    receipts: list[dict[str, Any]] = []
    changed: list[str] = []
    for strategy_id, task in expected.items():
        result_root = strategy_results_root / strategy_id
        receipt = load_object(result_root / "receipt.json")
        _validate_task_receipt(task, receipt)
        status = str(receipt["execution_status"])
        publication_input = str(task["publication_input"])
        model_id = str(task["model_version_id"])

        if status == "refreshed":
            if publication_input == "formal_v1":
                package = result_root / "formal-package.json"
                if not package.is_file():
                    raise FormalRefreshError(
                        f"refreshed formal package is missing for {strategy_id}"
                    )
                expected_sha = str(receipt.get("output_sha256") or "")
                if not expected_sha or sha256(package) != expected_sha:
                    raise FormalRefreshError(
                        f"formal package digest mismatch for {strategy_id}"
                    )
                shutil.copy2(package, candidate_root / f"{model_id}.json")
            elif publication_input == "native_bundle_v2":
                preview = result_root / "model-runs"
                catalog = preview / "catalog.json"
                expected_sha = str(receipt.get("output_sha256") or "")
                if not catalog.is_file() or not expected_sha or sha256(catalog) != expected_sha:
                    raise FormalRefreshError(
                        f"native preview digest mismatch for {strategy_id}"
                    )
                _copy_tree(preview, candidate_preview_root)
            else:
                raise FormalRefreshError(
                    f"unsupported publication input for {strategy_id}: {publication_input}"
                )
            changed.append(strategy_id)
        receipts.append(dict(receipt))

    fan_in = {
        "schema_version": FAN_IN_SCHEMA,
        "status": "complete",
        "generated_at": plan.get("generated_at"),
        "expected_strategy_ids": list(expected),
        "changed_strategy_ids": changed,
        "receipts": receipts,
        "research_only": True,
        "trade_ready": False,
    }
    write_object(receipt_path, fan_in)
    return fan_in


def _validate_fan_in(path: Path) -> dict[str, Any]:
    receipt = load_object(path)
    if (
        receipt.get("schema_version") != FAN_IN_SCHEMA
        or receipt.get("status") != "complete"
        or receipt.get("research_only") is not True
        or receipt.get("trade_ready") is not False
    ):
        raise FormalRefreshError("strategy fan-in receipt is invalid")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--formal-root", type=Path, required=True)
    plan_parser.add_argument("--formal-v2-catalog", type=Path, required=True)
    plan_parser.add_argument("--us-provider-manifest", type=Path, required=True)
    plan_parser.add_argument("--cn-provider-manifest", type=Path, required=True)
    plan_parser.add_argument("--generated-at", required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--github-output", type=Path)

    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--plan", type=Path, required=True)
    assemble.add_argument("--strategy-results-root", type=Path, required=True)
    assemble.add_argument("--current-root", type=Path, required=True)
    assemble.add_argument("--candidate-root", type=Path, required=True)
    assemble.add_argument("--current-preview-root", type=Path, required=True)
    assemble.add_argument("--candidate-preview-root", type=Path, required=True)
    assemble.add_argument("--receipt", type=Path, required=True)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--current-root", type=Path, required=True)
    finalize.add_argument("--candidate-root", type=Path, required=True)
    finalize.add_argument("--us-provider-manifest", type=Path, required=True)
    finalize.add_argument("--cn-provider-manifest", type=Path, required=True)
    finalize.add_argument("--generated-at", required=True)
    finalize.add_argument("--fan-in-receipt", type=Path, required=True)
    finalize.add_argument("--receipt", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "assemble":
        result = assemble_strategy_results(
            plan_path=args.plan,
            strategy_results_root=args.strategy_results_root,
            current_root=args.current_root,
            candidate_root=args.candidate_root,
            current_preview_root=args.current_preview_root,
            candidate_preview_root=args.candidate_preview_root,
            receipt_path=args.receipt,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    cutoffs = _cutoffs(args.us_provider_manifest, args.cn_provider_manifest)
    if args.command == "plan":
        plan = build_task_plan(
            formal_root=args.formal_root,
            formal_v2_catalog=args.formal_v2_catalog,
            cutoffs=cutoffs,
            generated_at=args.generated_at,
        )
        write_object(args.output, plan)
        if args.github_output:
            args.github_output.parent.mkdir(parents=True, exist_ok=True)
            with args.github_output.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"refresh_required={str(bool(plan['refresh_required'])).lower()}\n"
                )
                handle.write(f"us_cutoff={plan['target_cutoffs']['us']}\n")
                handle.write(f"cn_cutoff={plan['target_cutoffs']['cn']}\n")
                handle.write(
                    "task_matrix="
                    + json.dumps(plan["tasks"], separators=(",", ":"))
                    + "\n"
                )
        print(json.dumps(plan, indent=2, sort_keys=True))
        return

    fan_in = _validate_fan_in(args.fan_in_receipt)
    receipt = finalize_candidate_tree(
        args.current_root,
        args.candidate_root,
        target_cutoffs=cutoffs,
        generated_at=args.generated_at,
        receipt_path=args.receipt,
    )
    receipt["strategy_fan_in_sha256"] = sha256(args.fan_in_receipt)
    receipt["active_strategy_ids"] = fan_in["expected_strategy_ids"]
    write_object(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
