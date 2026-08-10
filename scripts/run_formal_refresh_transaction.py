"""Plan and finalize a catalog-driven formal backtest refresh transaction."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from scripts.ranker_provisional_mtm import attach_ranker_provisional_mtm
from src.artifacts.formal_refresh import (
    build_plan,
    common_provider_cutoff,
    finalize_candidate_tree,
    load_object,
    write_object,
)


def _cutoffs(us_manifest: Path, cn_manifest: Path) -> dict[str, str]:
    return {
        "us": common_provider_cutoff(load_object(us_manifest), market="us"),
        "cn": common_provider_cutoff(load_object(cn_manifest), market="cn"),
    }


def _provider_dir(manifest: Path, market: str) -> Path:
    return manifest.resolve().parent.parent / "data" / "providers" / market


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
            ledger_dir=repository_root / "data" / "research" / "strategy_signal_ledgers" / model_id,
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
        write_object(args.output, plan.to_dict())
        if args.github_output:
            args.github_output.parent.mkdir(parents=True, exist_ok=True)
            with args.github_output.open("a", encoding="utf-8") as handle:
                handle.write(f"refresh_required={str(plan.refresh_required).lower()}\n")
                handle.write(f"us_cutoff={plan.target_cutoffs['us']}\n")
                handle.write(f"cn_cutoff={plan.target_cutoffs['cn']}\n")
                handle.write(
                    "stale_model_ids="
                    + json.dumps(list(plan.stale_model_ids), separators=(",", ":"))
                    + "\n"
                )
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
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
