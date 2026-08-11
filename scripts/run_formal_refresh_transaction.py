"""Plan and finalize a catalog-driven formal backtest refresh transaction."""

from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from scripts.ranker_provisional_mtm import attach_ranker_provisional_mtm
from src.artifacts.formal_refresh import (
    FormalRefreshError,
    build_plan,
    common_provider_cutoff,
    finalize_candidate_tree,
    load_object,
    sha256,
    write_object,
)
from src.research.qqq_authoritative_replay import (
    prepare_and_verify_active_rules_replay,
    verify_qqq_authoritative_replay,
)
from src.research.rules_formal_replay_gate import (
    verify_cn_current_allocation_replay,
    verify_cn_frozen_prefix,
)

RANKER_MTM_MODELS = (
    ("us_x1_1", "us"),
    ("cn_x1_1", "cn"),
)
QQQ_MODEL_ID = "qqqi_qqq_tqqq_v4_3"
CN_MODEL_ID = "cn_x1_1"
QQQ_BUNDLE_ROOT = Path("artifacts/formal-refresh/qqq-bundle")
CN_REPLAY_OUTPUT_ROOT = Path("artifacts/formal-refresh/cn-replay-ledger")
CN_LEDGER = Path(
    "artifacts/formal-refresh/cn-ledger-a/score_ledgers/"
    "2026H2_PARTIAL__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz"
)


def _cutoffs(us_manifest: Path, cn_manifest: Path) -> dict[str, str]:
    return {
        "us": common_provider_cutoff(load_object(us_manifest), market="us"),
        "cn": common_provider_cutoff(load_object(cn_manifest), market="cn"),
    }


def _provider_dir(manifest: Path, market: str) -> Path:
    return manifest.resolve().parent.parent / "data" / "providers" / market


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


def _attach_ranker_mtm(
    *,
    candidate_root: Path,
    us_provider_manifest: Path,
    cn_provider_manifest: Path,
    cutoffs: dict[str, str],
) -> None:
    repository_root = Path.cwd().resolve()
    rows = (
        (
            "us_x1_1",
            "us",
            us_provider_manifest,
        ),
        (
            "cn_x1_1",
            "cn",
            cn_provider_manifest,
        ),
    )
    for model_id, market, provider_manifest in rows:
        package_path = candidate_root / f"{model_id}.json"
        if not package_path.is_file():
            continue
        attach_ranker_provisional_mtm(
            package_path=package_path,
            provider_dir=_provider_dir(provider_manifest, market),
            ledger_dir=repository_root
            / "data"
            / "research"
            / "strategy_signal_ledgers"
            / model_id,
            cutoff=cutoffs[market],
            repository_root=repository_root,
        )


def _report_changed(current: Path, candidate: Path) -> bool:
    if not current.is_file() or not candidate.is_file():
        return False
    return load_object(current).get("report") != load_object(candidate).get("report")


def _verify_rules_replay_gates(
    *,
    current_root: Path,
    candidate_root: Path,
    cn_provider_manifest: Path,
) -> dict[str, object]:
    repository_root = Path.cwd().resolve()
    receipts: dict[str, object] = {}

    qqq_current = current_root / f"{QQQ_MODEL_ID}.json"
    qqq_candidate = candidate_root / f"{QQQ_MODEL_ID}.json"
    qqq_bundle_manifest = QQQ_BUNDLE_ROOT / "bundle_manifest.json"
    qqq_changed = (
        qqq_current.is_file()
        and qqq_candidate.is_file()
        and sha256(qqq_current) != sha256(qqq_candidate)
    )
    if qqq_changed or qqq_bundle_manifest.is_file():
        if not qqq_bundle_manifest.is_file():
            raise FormalRefreshError(
                "QQQ formal candidate changed without the professional governed ETF bundle"
            )
        receipts[QQQ_MODEL_ID] = verify_qqq_authoritative_replay(
            repository_root,
            package_path=qqq_candidate,
            bundle_dir=QQQ_BUNDLE_ROOT,
        )

    cn_current = current_root / f"{CN_MODEL_ID}.json"
    cn_candidate = candidate_root / f"{CN_MODEL_ID}.json"
    if cn_candidate.is_file():
        candidate_package = load_object(cn_candidate)
        frozen = verify_cn_frozen_prefix(repository_root, candidate_package)
        ledger = (repository_root / CN_LEDGER).resolve()
        settled_changed = _report_changed(cn_current, cn_candidate)
        if ledger.is_file():
            receipts[CN_MODEL_ID] = verify_cn_current_allocation_replay(
                repository_root,
                package_path=cn_candidate,
                provider_dir=_provider_dir(cn_provider_manifest, "cn"),
                ledger_path=ledger,
            )
        elif settled_changed:
            raise FormalRefreshError(
                "CN settled formal trace changed without the governed current R0 score ledger"
            )
        else:
            receipts[CN_MODEL_ID] = {
                "schema_version": "1.0",
                "model_id": CN_MODEL_ID,
                "decision": "exact_replay",
                "frozen_prefix": frozen,
                "current_allocation": "not_required_no_settled_trace_change",
                "research_only": True,
                "trade_ready": False,
                "promotion_authorized": False,
            }

    return {
        "schema_version": "rules_formal_replay_gates_v1",
        "status": "exact_replay",
        "models": receipts,
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--formal-root", type=Path, required=True)
    plan_parser.add_argument("--us-provider-manifest", type=Path, required=True)
    plan_parser.add_argument("--cn-provider-manifest", type=Path, required=True)
    plan_parser.add_argument("--generated-at", required=True)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--github-output", type=Path)

    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--current-root", type=Path, required=True)
    initialize.add_argument("--candidate-root", type=Path, required=True)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--current-root", type=Path, required=True)
    finalize.add_argument("--candidate-root", type=Path, required=True)
    finalize.add_argument("--us-provider-manifest", type=Path, required=True)
    finalize.add_argument("--cn-provider-manifest", type=Path, required=True)
    finalize.add_argument("--generated-at", required=True)
    finalize.add_argument("--receipt", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "initialize":
        if args.candidate_root.exists():
            shutil.rmtree(args.candidate_root)
        shutil.copytree(args.current_root, args.candidate_root)
        return

    cutoffs = _cutoffs(args.us_provider_manifest, args.cn_provider_manifest)
    if args.command == "plan":
        active_rules_replay = prepare_and_verify_active_rules_replay(
            Path.cwd(),
            formal_root=args.formal_root,
            cn_provider_dir=_provider_dir(args.cn_provider_manifest, "cn"),
            qqq_bundle_dir=QQQ_BUNDLE_ROOT,
            cn_replay_output_dir=CN_REPLAY_OUTPUT_ROOT,
        )
        plan = build_plan(
            args.formal_root,
            target_cutoffs=cutoffs,
            generated_at=args.generated_at,
        )
        mtm_refresh_model_ids = _mtm_refresh_model_ids(
            args.formal_root,
            cutoffs=cutoffs,
        )
        refresh_required = plan.refresh_required or bool(mtm_refresh_model_ids)
        plan_payload = plan.to_dict()
        plan_payload["active_rules_replay"] = active_rules_replay
        plan_payload["mtm_refresh_model_ids"] = list(mtm_refresh_model_ids)
        plan_payload["refresh_required"] = refresh_required
        write_object(args.output, plan_payload)
        if args.github_output:
            args.github_output.parent.mkdir(parents=True, exist_ok=True)
            with args.github_output.open("a", encoding="utf-8") as handle:
                handle.write(f"refresh_required={str(refresh_required).lower()}\n")
                handle.write(f"us_cutoff={plan.target_cutoffs['us']}\n")
                handle.write(f"cn_cutoff={plan.target_cutoffs['cn']}\n")
                handle.write(
                    "stale_model_ids="
                    + json.dumps(list(plan.stale_model_ids), separators=(",", ":"))
                    + "\n"
                )
                handle.write(
                    "mtm_refresh_model_ids="
                    + json.dumps(list(mtm_refresh_model_ids), separators=(",", ":"))
                    + "\n"
                )
        print(json.dumps(plan_payload, indent=2, sort_keys=True))
        return

    _attach_ranker_mtm(
        candidate_root=args.candidate_root,
        us_provider_manifest=args.us_provider_manifest,
        cn_provider_manifest=args.cn_provider_manifest,
        cutoffs=cutoffs,
    )
    replay_gates = _verify_rules_replay_gates(
        current_root=args.current_root,
        candidate_root=args.candidate_root,
        cn_provider_manifest=args.cn_provider_manifest,
    )
    receipt = finalize_candidate_tree(
        args.current_root,
        args.candidate_root,
        target_cutoffs=cutoffs,
        generated_at=args.generated_at,
        receipt_path=args.receipt,
    )
    receipt["rules_formal_replay_gates"] = replay_gates
    write_object(args.receipt, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
