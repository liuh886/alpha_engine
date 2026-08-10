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
    write_object,
)

RANKER_MTM_MODELS = (
    ("us_x1_1", "us"),
    ("cn_x1_1", "cn"),
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
    receipt = finalize_candidate_tree(
        args.current_root,
        args.candidate_root,
        target_cutoffs=cutoffs,
        generated_at=args.generated_at,
        receipt_path=args.receipt,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
