"""Run the frozen ranker transfer test on the selected US and CN pools.

Pool membership remains exact and immutable. Runtime coverage follows the
historical frozen contract: no pre-listing data are fabricated, coverage-
qualified members are retained, and every dropped symbol is reported. A market
is complete when its exact promoted provider exists and the execution adapter
finishes a passed multi-window result. A rejected promotion decision is valid
negative evidence, not a data or execution failure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import yaml

from scripts.run_cn_feature_quality_validation import run as run_cn_validation
from scripts.run_us_feature_quality_validation import run as run_us_validation
from src.research.paradigm import load_research_paradigm_spec
from src.research.selected_pool_guard import resolve_selected_pool

US_SPEC = Path(
    "configs/research_paradigms/us_10d_selected_pool_ranker_retest_v1.yaml"
)
CN_SPEC = Path(
    "configs/research_paradigms/cn_10d_selected_pool_ranker_retest_v1.yaml"
)
REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
LISTING_POLICY = "no_prelisting_fill_coverage_qualified_static_members"
CANDIDATE_PROMOTION_STATUSES = {
    "research_candidate",
    "stronger_research_candidate",
    "trade_guidance_candidate",
}

Runner = Callable[..., dict[str, Any]]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML contract must be a mapping: {path}")
    return payload


def _preflight(root: Path, market: str, spec_path: Path) -> dict[str, Any]:
    binding = resolve_selected_pool(
        market,
        registry_path=root / REGISTRY,
        authoritative=True,
        require_data_ready=True,
    )
    absolute_spec = root / spec_path
    spec = load_research_paradigm_spec(absolute_spec)
    declared_pool = (root / str(spec.universe["source"])).resolve()
    if declared_pool != binding.pool_spec:
        raise ValueError(
            "selected-pool retest spec does not use the active selected pool: "
            f"declared={declared_pool}, active={binding.pool_spec}"
        )

    pool = _load_yaml(binding.pool_spec)
    symbols = [str(value).upper() for value in pool.get("symbols", [])]
    expected_count = int(pool.get("candidate_count", 0))
    if len(symbols) != expected_count or len(symbols) != len(set(symbols)):
        raise ValueError("selected-pool membership count or uniqueness mismatch")
    if int(spec.universe.get("exact_pool_candidate_count", 0)) != expected_count:
        raise ValueError(
            "retest exact_pool_candidate_count must equal selected-pool membership"
        )
    min_symbols = int(spec.universe.get("min_symbols", 0))
    top_n = int(spec.strategy.get("top_n", 0))
    bottom_n = int(spec.strategy.get("bottom_n", 0))
    if min_symbols <= max(top_n, bottom_n) or min_symbols > expected_count:
        raise ValueError(
            "retest min_symbols must exceed Top/Bottom N and not exceed pool count"
        )
    if spec.universe.get("alignment_mode") != "auto":
        raise ValueError(
            "selected-pool transfer test must preserve frozen auto alignment"
        )
    if spec.universe.get("listing_policy") != LISTING_POLICY:
        raise ValueError("selected-pool listing policy is not fail-closed")
    if spec.benchmark.upper() in set(symbols):
        raise ValueError("benchmark must remain outside the candidate cross-section")

    return {
        "market": market,
        "pool_id": binding.pool_id,
        "candidate_count": expected_count,
        "runtime_min_symbols": min_symbols,
        "spec": str(spec_path),
        "benchmark": spec.benchmark,
    }


def _completed_evidence_status(result: dict[str, Any]) -> tuple[str, str]:
    """Classify a passed execution by its canonical promotion decision."""

    promotion = result.get("promotion_decision")
    if not isinstance(promotion, dict):
        return (
            "selected_pool_ranker_data_blocked",
            "passed execution has no canonical promotion_decision",
        )
    promotion_status = str(promotion.get("status", "")).strip().lower()
    rationale = str(promotion.get("rationale", "")).strip()
    if promotion_status == "rejected":
        return (
            "selected_pool_ranker_not_supported",
            rationale or "no candidate satisfied the frozen promotion gates",
        )
    if promotion_status in CANDIDATE_PROMOTION_STATUSES:
        return (
            "selected_pool_ranker_research_candidate",
            rationale or f"promotion_status={promotion_status}",
        )
    return (
        "selected_pool_ranker_data_blocked",
        rationale or f"unsupported promotion_status={promotion_status or 'missing'}",
    )


def _run_market(
    root: Path,
    *,
    market: str,
    spec_path: Path,
    runner: Runner,
    output_dir: Path,
    provider_uri: Path | None,
) -> dict[str, Any]:
    try:
        preflight = _preflight(root, market, spec_path)
    except (FileNotFoundError, ValueError) as exc:
        return {
            "market": market,
            "status": "selected_pool_ranker_data_blocked",
            "reason": f"{type(exc).__name__}: {exc}",
        }

    if provider_uri is None:
        return {
            **preflight,
            "status": "selected_pool_ranker_data_blocked",
            "reason": "exact refreshed provider URI is required",
        }

    try:
        result = runner(
            root,
            spec_path=spec_path,
            output_dir=output_dir,
            provider_uri=provider_uri,
        )
    except Exception as exc:  # the market runner writes its own failure artifact
        return {
            **preflight,
            "status": "selected_pool_ranker_data_blocked",
            "reason": f"{type(exc).__name__}: {exc}",
        }

    execution_status = str(result.get("status", "")).strip().lower()
    if execution_status != "passed":
        runtime_metadata = result.get("runtime_metadata")
        reason = (
            runtime_metadata.get("skip_reason")
            if isinstance(runtime_metadata, dict)
            else None
        )
        return {
            **preflight,
            "status": "selected_pool_ranker_data_blocked",
            "reason": str(reason or f"execution_status={execution_status or 'missing'}"),
            "result": result,
        }

    verdict, reason = _completed_evidence_status(result)
    return {
        **preflight,
        "status": verdict,
        "evidence_completed": verdict != "selected_pool_ranker_data_blocked",
        "reason": reason,
        "result": result,
    }


def run(
    root: Path,
    *,
    markets: tuple[str, ...] = ("us", "cn"),
    output_dir: Path = Path("artifacts/evidence/selected_pool_ranker_retest"),
    us_provider_uri: Path | None = None,
    cn_provider_uri: Path | None = None,
) -> dict[str, Any]:
    """Run one or both frozen selected-pool comparisons."""

    normalized_root = root.resolve()
    selected = tuple(dict.fromkeys(str(value).lower() for value in markets))
    invalid = sorted(set(selected) - {"us", "cn"})
    if invalid:
        raise ValueError(f"unsupported markets: {invalid}")

    configurations: dict[str, tuple[Path, Runner, Path | None]] = {
        "us": (US_SPEC, run_us_validation, us_provider_uri),
        "cn": (CN_SPEC, run_cn_validation, cn_provider_uri),
    }
    results: dict[str, Any] = {}
    for market in selected:
        spec_path, runner, provider_uri = configurations[market]
        results[market] = _run_market(
            normalized_root,
            market=market,
            spec_path=spec_path,
            runner=runner,
            output_dir=output_dir,
            provider_uri=provider_uri,
        )

    statuses = {payload["status"] for payload in results.values()}
    overall = (
        "selected_pool_ranker_data_blocked"
        if "selected_pool_ranker_data_blocked" in statuses
        else "evidence_run_completed"
    )
    return {
        "experiment_family": "selected_pool_ranker_retest_v1",
        "research_only": True,
        "trade_ready": False,
        "overall_status": overall,
        "markets": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--market",
        choices=("us", "cn", "both"),
        default="both",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/selected_pool_ranker_retest"),
    )
    parser.add_argument("--us-provider-uri", type=Path, default=None)
    parser.add_argument("--cn-provider-uri", type=Path, default=None)
    args = parser.parse_args()

    markets = ("us", "cn") if args.market == "both" else (args.market,)
    payload = run(
        args.root,
        markets=markets,
        output_dir=args.output_dir,
        us_provider_uri=args.us_provider_uri,
        cn_provider_uri=args.cn_provider_uri,
    )
    print(json.dumps(payload, indent=2, default=str))
    if payload["overall_status"] != "evidence_run_completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
