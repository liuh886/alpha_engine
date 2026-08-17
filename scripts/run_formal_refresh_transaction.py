"""Plan and fan in the catalog-driven formal refresh transaction on Bundle v2 only."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from src.artifacts.formal_bundle_reader import FormalBundleReadError, FormalBundleReader
from src.artifacts.formal_refresh import (
    FormalRefreshError,
    load_object,
    market_provider_cutoff,
    next_weekday_refresh_deadline,
    sha256,
    write_object,
)
from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.artifacts.model_run_exporter import update_catalog
from src.artifacts.strategy_signal_ledger import read_latest_evaluation
from src.governance.active_strategy_catalog import (
    ActiveStrategyCatalogError,
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)
from src.governance.strategy_runtime_capabilities import (
    RANKER_FORMAL_REFRESH_ADAPTERS,
    load_active_strategy_runtime_capabilities,
)

TASK_RECEIPT_SCHEMA = "formal_strategy_refresh_receipt_v2"
PLAN_SCHEMA = "formal_refresh_plan_v4"
FAN_IN_SCHEMA = "formal_strategy_fan_in_v2"
REFRESH_RECEIPT_SCHEMA = "formal_refresh_receipt_v2"
SUCCESS_STATES = {"current_no_change", "refreshed"}
RETAIN_CURRENT_STATES = {
    "data_blocked",
    "execution_failed",
    "invalid_evidence",
    "runtime_blocked",
}


def _assert_declared_model_transition(
    rows: object,
    active: Any,
    *,
    error_message: str,
    cause: Exception | None = None,
    publication_status: str | None = None,
) -> None:
    if not isinstance(rows, list):
        raise FormalRefreshError(error_message) from cause
    observed = {
        str(row.get("model_version_id") or "")
        for row in rows
        if isinstance(row, Mapping)
    }
    expected = set(active.active_model_version_ids)
    missing = expected - observed
    extra = observed - expected
    if not missing or len(missing) != len(extra):
        raise FormalRefreshError(error_message) from cause
    by_model = active.by_model_version_id
    unmatched_extra = set(extra)
    for successor in sorted(missing):
        strategy = by_model.get(successor)
        config_path = Path("configs/models") / f"{successor}.yaml"
        if strategy is None or not config_path.is_file():
            raise FormalRefreshError(error_message) from cause
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        lineage = config.get("lineage") if isinstance(config, Mapping) else None
        predecessor = (
            str(lineage.get("supersedes") or "") if isinstance(lineage, Mapping) else ""
        )
        predecessor_row = next(
            (
                row
                for row in rows
                if isinstance(row, Mapping)
                and row.get("model_version_id") == predecessor
            ),
            None,
        )
        if (
            predecessor not in unmatched_extra
            or not isinstance(predecessor_row, Mapping)
            or predecessor_row.get("model_family_id") != strategy.model_family_id
            or predecessor_row.get("model_kind") != strategy.model_kind
            or predecessor_row.get("publication_status")
            != (publication_status or strategy.formal_status)
        ):
            raise FormalRefreshError(error_message) from cause
        unmatched_extra.remove(predecessor)
    if unmatched_extra:
        raise FormalRefreshError(error_message) from cause


def _assert_formal_catalog_or_declared_transition(
    formal_v2: Mapping[str, object], active: Any
) -> None:
    try:
        assert_formal_catalog_matches_active_strategies(formal_v2, active)
        return
    except ActiveStrategyCatalogError as original:
        _assert_declared_model_transition(
            formal_v2.get("records"),
            active,
            error_message=str(original),
            cause=original,
        )


def _cutoffs(us_manifest: Path, cn_manifest: Path) -> dict[str, str]:
    return {
        "us": market_provider_cutoff(load_object(us_manifest), market="us"),
        "cn": market_provider_cutoff(load_object(cn_manifest), market="cn"),
    }


def _iso_date(value: object, *, label: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise FormalRefreshError(f"invalid {label}: {value!r}") from exc


def _latest_settled_performance_end(performance: Mapping[str, Any]) -> str:
    report = performance.get("report")
    if not isinstance(report, list) or not report:
        raise FormalRefreshError("formal ranker performance report is missing")
    ends: list[str] = []
    for row in report:
        if not isinstance(row, Mapping) or row.get("provisional_mtm") is True:
            continue
        value = row.get("holding_end_date") or row.get("date")
        if value:
            ends.append(_iso_date(value, label="latest settled performance end"))
    if not ends:
        raise FormalRefreshError("formal ranker has no settled performance row")
    return max(ends)


def _latest_formal_signal_date(portfolio: Mapping[str, Any]) -> str:
    positions = portfolio.get("positions")
    if not isinstance(positions, list) or not positions:
        raise FormalRefreshError("formal ranker portfolio has no positions")
    dates = [
        _iso_date(row.get("date"), label="formal ranker signal date")
        for row in positions
        if isinstance(row, Mapping) and row.get("date")
    ]
    if not dates:
        raise FormalRefreshError("formal ranker portfolio has no signal date")
    return max(dates)


def _latest_ledger_signal_date(ledger_root: Path, model_id: str) -> str:
    record = read_latest_evaluation(
        ledger_root / model_id,
        model_version_id=model_id,
    )
    if record is None:
        raise FormalRefreshError(f"canonical ranker signal ledger is missing: {model_id}")
    signal = record.get("signal")
    if not isinstance(signal, Mapping):
        raise FormalRefreshError(f"canonical ranker signal payload is missing: {model_id}")
    value = signal.get("signal_date") or record.get("signal_date")
    return _iso_date(value, label=f"{model_id} ledger signal date")


def _has_current_provisional_mtm(
    performance: Mapping[str, Any], *, cutoff: str, signal_date: str
) -> bool:
    report = performance.get("report")
    if not isinstance(report, list):
        return False
    return any(
        isinstance(row, Mapping)
        and row.get("provisional_mtm") is True
        and row.get("settlement_status") == "provisional_mtm"
        and str(row.get("holding_end_date") or "") == cutoff
        and str(row.get("signal_date") or "") == signal_date
        for row in report
    )


def _ranker_refresh_requirements(
    *,
    model_id: str,
    target: str,
    formal_signal_date: str,
    ledger_signal_date: str,
    performance: Mapping[str, Any],
) -> tuple[bool, bool]:
    target_date = _iso_date(target, label=f"{model_id} target cutoff")
    formal_date = _iso_date(formal_signal_date, label=f"{model_id} formal signal date")
    ledger_date = _iso_date(ledger_signal_date, label=f"{model_id} ledger signal date")
    if ledger_date < formal_date:
        raise FormalRefreshError(
            f"formal ranker state is ahead of canonical ledger for {model_id}: "
            f"formal={formal_date} ledger={ledger_date}"
        )
    if ledger_date > target_date:
        raise FormalRefreshError(
            f"canonical ranker signal exceeds provider cutoff for {model_id}: "
            f"ledger={ledger_date} target={target_date}"
        )

    settled_end = _latest_settled_performance_end(performance)
    if settled_end > target_date:
        raise FormalRefreshError(
            f"settled performance exceeds target cutoff for {model_id}: "
            f"{settled_end} > {target_date}"
        )

    settled_refresh_required = ledger_date > formal_date
    mtm_refresh_required = target_date > ledger_date and not _has_current_provisional_mtm(
        performance,
        cutoff=target_date,
        signal_date=ledger_date,
    )
    return settled_refresh_required, mtm_refresh_required


def build_task_plan(
    *,
    formal_v2_root: Path,
    cutoffs: Mapping[str, str],
    generated_at: str,
) -> dict[str, Any]:
    active = load_active_strategy_catalog()
    repository = Path.cwd().resolve()
    try:
        relative_root = formal_v2_root.resolve().relative_to(repository)
        reader = FormalBundleReader.open(repository, relative_root=relative_root)
    except (ValueError, FormalBundleReadError) as exc:
        raise FormalRefreshError(str(exc)) from exc
    formal_v2 = reader.catalog
    _assert_formal_catalog_or_declared_transition(formal_v2, active)
    records = reader.records
    runtime = load_active_strategy_runtime_capabilities(active=active)
    ranker_strategies = [
        strategy
        for strategy in active.strategies
        if runtime[strategy.strategy_id].formal_refresh.adapter_id
        in RANKER_FORMAL_REFRESH_ADAPTERS
    ]
    ranker_model_ids = {strategy.model_version_id for strategy in ranker_strategies}

    stale_ids: set[str] = set()
    mtm_ids: set[str] = set()
    planned_cutoffs: dict[str, str] = {}
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        record = records.get(model_id)
        market_target = _iso_date(
            cutoffs[strategy.market], label=f"{strategy.market} target cutoff"
        )
        if record is None:
            planned_cutoffs[model_id] = market_target
            stale_ids.add(model_id)
            continue
        accepted = _iso_date(
            record.get("evidence_cutoff"), label=f"{model_id} formal cutoff"
        )
        # Accepted evidence is immutable. A transient provider regression never
        # asks a model to move backwards and never aborts unrelated strategies.
        planned_cutoffs[model_id] = max(market_target, accepted)
        if model_id not in ranker_model_ids and accepted < market_target:
            stale_ids.add(model_id)

    for strategy in ranker_strategies:
        model_id = strategy.model_version_id
        record = records.get(model_id)
        if record is None:
            continue
        try:
            run = reader.load(model_id)
            performance = run.section("performance")
            portfolio = run.section("portfolio")
        except FormalBundleReadError as exc:
            raise FormalRefreshError(str(exc)) from exc
        if not isinstance(performance, Mapping) or not isinstance(portfolio, Mapping):
            raise FormalRefreshError(f"formal ranker sections are invalid: {model_id}")
        formal_signal = _latest_formal_signal_date(portfolio)
        ledger_signal = _latest_ledger_signal_date(
            Path(strategy.signal_ledger).parent,
            model_id,
        )
        # A sealed decision is canonical state. If provider freshness temporarily
        # trails it, plan the model at least through that decision and let the
        # model task prove or block its own data coverage; never abort other models.
        target = max(planned_cutoffs[model_id], ledger_signal)
        planned_cutoffs[model_id] = target
        settled_required, mtm_required = _ranker_refresh_requirements(
            model_id=model_id,
            target=target,
            formal_signal_date=formal_signal,
            ledger_signal_date=ledger_signal,
            performance=performance,
        )
        if settled_required:
            stale_ids.add(model_id)
        if mtm_required:
            mtm_ids.add(model_id)

    tasks: list[dict[str, Any]] = []
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        capability = runtime[strategy.strategy_id].formal_refresh
        tasks.append(
            {
                "strategy_id": strategy.strategy_id,
                "model_family_id": strategy.model_family_id,
                "model_version_id": model_id,
                "model_kind": strategy.model_kind,
                "market": strategy.market,
                "planned_provider_cutoff": planned_cutoffs[model_id],
                "publication_input": "native_bundle_v2",
                "formal_refresh_required": model_id in stale_ids,
                "mtm_refresh_required": model_id in mtm_ids,
                "formal_refresh_capability_status": capability.status,
                "formal_refresh_adapter_id": capability.adapter_id,
                "formal_refresh_block_reason": capability.reason,
            }
        )

    blocked_ids = sorted(
        str(task["model_version_id"])
        for task in tasks
        if (task["formal_refresh_required"] or task["mtm_refresh_required"])
        and task["formal_refresh_capability_status"] == "blocked"
    )

    return {
        "schema_version": PLAN_SCHEMA,
        "generated_at": generated_at,
        "target_cutoffs": dict(sorted(cutoffs.items())),
        "active_strategy_ids": [row.strategy_id for row in active.strategies],
        "active_model_version_ids": list(active.active_model_version_ids),
        "stale_model_ids": sorted(stale_ids),
        "mtm_refresh_model_ids": sorted(mtm_ids),
        "blocked_model_ids": blocked_ids,
        "refresh_required": bool(stale_ids or mtm_ids),
        "tasks": tasks,
        "research_only": True,
        "trade_ready": False,
    }


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _validate_task_receipt(task: Mapping[str, Any], receipt: Mapping[str, Any]) -> str:
    if receipt.get("schema_version") != TASK_RECEIPT_SCHEMA:
        raise FormalRefreshError(
            f"invalid strategy receipt schema for {task.get('strategy_id')}"
        )
    for field in (
        "strategy_id",
        "model_family_id",
        "model_version_id",
        "model_kind",
        "market",
        "planned_provider_cutoff",
        "publication_input",
        "formal_refresh_capability_status",
        "formal_refresh_adapter_id",
        "formal_refresh_block_reason",
    ):
        if receipt.get(field) != task.get(field):
            raise FormalRefreshError(
                f"strategy receipt binding mismatch for {task.get('strategy_id')}: {field}"
            )
    if receipt.get("research_only") is not True or receipt.get("trade_ready") is not False:
        raise FormalRefreshError(
            f"strategy receipt research boundary changed: {task.get('strategy_id')}"
        )
    status = str(receipt.get("execution_status") or "")
    if status not in SUCCESS_STATES | RETAIN_CURRENT_STATES:
        raise FormalRefreshError(
            f"unsupported strategy task result: {task.get('strategy_id')}={status or 'missing'}"
        )
    return status


def _install_preview(source_root: Path, target_root: Path, *, model_id: str) -> None:
    catalog = load_object(source_root / "catalog.json")
    validate_catalog(catalog)
    if catalog.get("channel") != "preview":
        raise FormalRefreshError("strategy output must be a preview Bundle v2 catalog")
    rows = catalog.get("records")
    if not isinstance(rows, list) or len(rows) != 1:
        raise FormalRefreshError("strategy output must contain exactly one preview run")
    row = rows[0]
    if not isinstance(row, Mapping) or row.get("model_version_id") != model_id:
        raise FormalRefreshError(f"strategy preview identity mismatch: {model_id}")
    manifest = source_root / str(row.get("manifest_path") or "")
    if not manifest.is_file() or sha256(manifest) != row.get("manifest_sha256"):
        raise FormalRefreshError(f"strategy preview manifest digest mismatch: {model_id}")
    family = str(row.get("model_family_id") or "")
    source_model_root = source_root / family / model_id
    target_model_root = target_root / family / model_id
    _copy_tree(source_model_root, target_model_root)


def _seal_preview_catalog(candidate_preview_root: Path) -> dict[str, Any]:
    active = load_active_strategy_catalog()
    discovered = sorted(candidate_preview_root.rglob("manifest.json"))
    if not discovered:
        raise FormalRefreshError("active preview fan-in produced no Bundle v2 manifests")

    manifests_by_model: dict[str, list[Path]] = {}
    for manifest_path in discovered:
        manifest = load_object(manifest_path)
        model_id = str(manifest.get("model_version_id") or "")
        manifests_by_model.setdefault(model_id, []).append(manifest_path)

    manifests: list[Path] = []
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        candidates = manifests_by_model.get(model_id, [])
        if not candidates:
            config_path = Path("configs/models") / f"{model_id}.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            lineage = config.get("lineage") if isinstance(config, Mapping) else None
            predecessor = (
                str(lineage.get("supersedes") or "")
                if isinstance(lineage, Mapping)
                else ""
            )
            candidates = manifests_by_model.get(predecessor, [])
        if len(candidates) != 1:
            raise FormalRefreshError(
                "active preview fan-in must resolve exactly one run for "
                f"{model_id}: observed={len(candidates)}"
            )
        manifests.append(candidates[0])

    catalog = update_catalog(
        manifests,
        catalog_path=candidate_preview_root / "catalog.json",
        channel="preview",
    )
    observed = [
        str(row.get("model_version_id") or "")
        for row in catalog.get("records", [])
        if isinstance(row, Mapping)
    ]
    if len(observed) != len(set(observed)):
        raise FormalRefreshError("active preview fan-in contains multiple runs for one model")
    if set(observed) != set(active.active_model_version_ids):
        message = (
            "active preview fan-in must contain exactly the active model set: "
            f"expected={sorted(active.active_model_version_ids)}, observed={sorted(observed)}"
        )
        _assert_declared_model_transition(
            catalog.get("records"),
            active,
            error_message=message,
            publication_status="ci_validated_preview",
        )
    return catalog


def assemble_strategy_results(
    *,
    plan_path: Path,
    strategy_results_root: Path,
    current_preview_root: Path,
    candidate_preview_root: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    plan = load_object(plan_path)
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise FormalRefreshError("unsupported formal refresh plan schema")
    raw_tasks = plan.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise FormalRefreshError("formal refresh plan has no active strategy tasks")
    tasks = [dict(task) for task in raw_tasks if isinstance(task, Mapping)]
    if len(tasks) != len(raw_tasks):
        raise FormalRefreshError("formal refresh plan contains invalid strategy tasks")
    expected = {str(task["strategy_id"]): task for task in tasks}
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

    _copy_tree(current_preview_root, candidate_preview_root)
    receipts: list[dict[str, Any]] = []
    changed: list[str] = []
    retained: list[str] = []
    for strategy_id, task in expected.items():
        result_root = strategy_results_root / strategy_id
        receipt = load_object(result_root / "receipt.json")
        status = _validate_task_receipt(task, receipt)
        if status == "refreshed":
            preview = result_root / "model-runs"
            catalog_path = preview / "catalog.json"
            expected_sha = str(receipt.get("output_sha256") or "")
            if (
                not catalog_path.is_file()
                or not expected_sha
                or sha256(catalog_path) != expected_sha
            ):
                raise FormalRefreshError(f"preview digest mismatch for {strategy_id}")
            _install_preview(
                preview,
                candidate_preview_root,
                model_id=str(task["model_version_id"]),
            )
            changed.append(strategy_id)
        elif status in RETAIN_CURRENT_STATES:
            retained.append(strategy_id)
        receipts.append(dict(receipt))

    _seal_preview_catalog(candidate_preview_root)
    fan_in = {
        "schema_version": FAN_IN_SCHEMA,
        "status": "complete",
        "generated_at": plan.get("generated_at"),
        "expected_strategy_ids": list(expected),
        "changed_strategy_ids": changed,
        "retained_strategy_ids": retained,
        "publication_contract": "active_preview_bundle_v2",
        "preview_catalog_sha256": sha256(candidate_preview_root / "catalog.json"),
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
        or receipt.get("publication_contract") != "active_preview_bundle_v2"
        or receipt.get("research_only") is not True
        or receipt.get("trade_ready") is not False
    ):
        raise FormalRefreshError("strategy fan-in receipt is invalid")
    return receipt


def finalize_refresh(
    *,
    us_provider_manifest: Path,
    cn_provider_manifest: Path,
    generated_at: str,
    fan_in_receipt: Path,
    freshness_output: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    cutoffs = _cutoffs(us_provider_manifest, cn_provider_manifest)
    active = load_active_strategy_catalog()
    fan_in = _validate_fan_in(fan_in_receipt)
    rankers = [
        row.model_version_id
        for row in active.strategies
        if row.model_kind == "cross_sectional_ranker"
    ]
    freshness = {
        "schema_version": "1.0.0",
        "cutoff_policy": "governed_benchmark_market_session",
        "declared_at": generated_at,
        "markets": dict(sorted(cutoffs.items())),
        "next_session_close_utc": {
            market: next_weekday_refresh_deadline(cutoff, market=market)
            for market, cutoff in sorted(cutoffs.items())
        },
        "required_models": list(active.active_model_version_ids),
        "date_range_end_required_models": rankers,
        "freshness_receipt_required_models": rankers,
        "research_only": True,
        "trade_ready": False,
    }
    write_object(freshness_output, freshness)
    receipt = {
        "schema_version": REFRESH_RECEIPT_SCHEMA,
        "status": "candidate_ready_for_review",
        "generated_at": generated_at,
        "target_cutoffs": dict(sorted(cutoffs.items())),
        "active_strategy_ids": [row.strategy_id for row in active.strategies],
        "active_model_version_ids": list(active.active_model_version_ids),
        "retained_strategy_ids": list(fan_in.get("retained_strategy_ids") or []),
        "publication_contract": "active_preview_bundle_v2",
        "preview_catalog_sha256": fan_in["preview_catalog_sha256"],
        "strategy_fan_in_sha256": sha256(fan_in_receipt),
        "freshness_sha256": sha256(freshness_output),
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_object(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--formal-v2-root", type=Path, required=True)
    plan_parser.add_argument("--us-provider-manifest", type=Path, required=True)
    plan_parser.add_argument("--cn-provider-manifest", type=Path, required=True)
    plan_parser.add_argument("--generated-at", required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--github-output", type=Path)

    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--plan", type=Path, required=True)
    assemble.add_argument("--strategy-results-root", type=Path, required=True)
    assemble.add_argument("--current-preview-root", type=Path, required=True)
    assemble.add_argument("--candidate-preview-root", type=Path, required=True)
    assemble.add_argument("--receipt", type=Path, required=True)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--us-provider-manifest", type=Path, required=True)
    finalize.add_argument("--cn-provider-manifest", type=Path, required=True)
    finalize.add_argument("--generated-at", required=True)
    finalize.add_argument("--fan-in-receipt", type=Path, required=True)
    finalize.add_argument("--freshness-output", type=Path, required=True)
    finalize.add_argument("--receipt", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "assemble":
        result = assemble_strategy_results(
            plan_path=args.plan,
            strategy_results_root=args.strategy_results_root,
            current_preview_root=args.current_preview_root,
            candidate_preview_root=args.candidate_preview_root,
            receipt_path=args.receipt,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "plan":
        cutoffs = _cutoffs(args.us_provider_manifest, args.cn_provider_manifest)
        plan = build_task_plan(
            formal_v2_root=args.formal_v2_root,
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

    result = finalize_refresh(
        us_provider_manifest=args.us_provider_manifest,
        cn_provider_manifest=args.cn_provider_manifest,
        generated_at=args.generated_at,
        fan_in_receipt=args.fan_in_receipt,
        freshness_output=args.freshness_output,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
