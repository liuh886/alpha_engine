#!/usr/bin/env python3
"""Diagnose current governed evidence and five-strategy operating health."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


def diagnose(repository_root: Path, *, generated_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read and verify existing evidence; keep health rules in SystemHealth."""
    from src.artifacts.formal_bundle_reader import FormalBundleReader
    from src.artifacts.strategy_operations import build_operations_payload, validate_operations_payload
    from src.artifacts.system_health import build_system_health, validate_system_health

    root = repository_root.resolve()
    formal_root = root / "data/research/formal_model_runs"
    reader = FormalBundleReader.open(root)
    for model_version_id in reader.records:
        reader.load(model_version_id)

    operations = build_operations_payload(
        formal_catalog=formal_root / "catalog.json",
        strategy_catalog=root / "configs/strategies/registry.json",
        ledger_root=root / "data/research/strategy_signal_ledgers",
        repository_root=root,
        generated_at=generated_at,
    )
    validate_operations_payload(operations)
    health = build_system_health(
        repository_root=root,
        formal_catalog=formal_root / "catalog.json",
        formal_freshness=formal_root / "freshness.json",
        operations=operations,
        model_data_readiness=root / "data/research/model_data_bundle_v1/model-data-readiness.json",
        generated_at=generated_at,
    )
    validate_system_health(health)
    return health, operations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    generated_at = datetime.now(timezone.utc).isoformat()
    print("=== Alpha Engine Operating Health ===")
    print(f"Python: {sys.version.split()[0]} ({sys.platform})")
    print(f"Observed at: {generated_at}")
    try:
        health, operations = diagnose(args.root, generated_at=generated_at)
    except (OSError, ValueError, ImportError) as exc:
        print(f"[FAILURE] Governed health could not be verified: {exc}")
        if isinstance(exc, ImportError):
            print("Restore locked dependencies with: uv sync --frozen --extra dev")
        return 1

    print("[OK] Formal catalog, manifests and available section bytes verified.")
    print(f"Core operating state: {health['state']}")
    by_model = {row["model_version_id"]: row for row in operations["records"]}
    for row in health["strategies"]:
        print(
            f"  {row['model_version_id']}: {row['state']} | "
            f"provider={row['provider_cutoff']} formal={row['formal_cutoff']} "
            f"factor={row['factor_cutoff']} decision={row['last_signal_evaluation']}"
        )
        issues = [f"{stage}={state}" for stage, state in row["stages"].items()
                  if state not in {"current", "not_applicable"}]
        if issues:
            print(f"    Affected stages: {', '.join(issues)}")
            reason = by_model[row["model_version_id"]].get("decision_reason")
            if reason:
                print(f"    Decision evidence: {reason}")

    training = health["model_data"]
    print(
        f"Research training profiles: {training['state']} | "
        f"cutoff={training['evidence_cutoff']} | "
        f"blocked_profiles={training['summary']['blocked_training_profile_count']}"
    )
    print("  Scope: research_training_profiles; details: data/research/model_data_bundle_v1/model-data-readiness.json")
    print("Research only: true | Trade ready: false")
    if health["state"] == "current":
        print("[SUCCESS] Current operating evidence verified.")
        return 0
    print("[FAILURE] Resolve the affected evidence stages through their existing governed workflows.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
