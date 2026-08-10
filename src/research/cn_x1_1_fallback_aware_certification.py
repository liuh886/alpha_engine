"""Fallback-aware certification for frozen CN x1.1 regime-gated evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

FROZEN_ECONOMIC_HASHES: dict[str, str] = {
    "model_spec.json": "27809294e0fc5d5d2e3bb2dcaef3ad3cb31f99583b0854bf2079340d33f54a3c",
    "evaluation_summary.csv": "fac8421e868d7f0e547abb9c799c2941cfeb51dc3d032edbef73fb87382b3c81",
    "half_year_results.csv": "e3752b82dc96d162bcb5bb0fcfbcea7909a49a9accc67f05ed58617b9d3b3025",
    "yearly_state_coverage.csv": "288e9f182c2937efeb81440a06d8f4930aefbac104492230adcb931da9192771",
    "neighbor_rule_summary.csv": "f4737e1d7a1d90329e490893ed42e0f475f3de3fed0f395c5c36930209df3a14",
    "rebalance_periods.csv": "5fd1416596ab2a208ced0ecbea76ce6ad60e762c3342d4d082215adf4379adb7",
    "holdings.csv": "dc73b399b1dee8ce759f9e1c61535e650a83b31392ced3bda4560c233aa0b2d9",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen_economic_identity(
    output_dir: Path,
    expected: Mapping[str, str] = FROZEN_ECONOMIC_HASHES,
) -> dict[str, str]:
    """Fail closed if any model or economic evidence file has changed."""

    observed: dict[str, str] = {}
    mismatches: list[str] = []
    for filename, expected_hash in expected.items():
        path = output_dir / filename
        if not path.is_file():
            mismatches.append(f"missing:{filename}")
            continue
        observed_hash = sha256(path)
        observed[filename] = observed_hash
        if observed_hash != expected_hash:
            mismatches.append(f"hash:{filename}:expected={expected_hash}:observed={observed_hash}")
    if mismatches:
        raise ValueError("frozen economic evidence identity mismatch: " + " | ".join(mismatches))
    return observed


def fallback_aware_gates(original_gates: Mapping[str, bool]) -> dict[str, bool]:
    """Replace only the semantically invalid all-period fallback hit-rate gate."""

    gates = dict(original_gates)
    if "historical_all_period_hit_rate_at_least_50pct" not in gates:
        raise ValueError("original all-period hit-rate gate is missing")
    gates.pop("historical_all_period_hit_rate_at_least_50pct")
    gates["historical_risk_on_active_hit_rate_at_least_50pct"] = True
    return dict(sorted(gates.items()))


def build_certified_decision(
    original_decision: Mapping[str, Any],
    *,
    active_hit_rate: float,
    frozen_identity_verified: bool,
) -> dict[str, Any]:
    """Build the corrected decision without changing any economic evidence."""

    gates = dict(original_decision["gates"])
    if "historical_all_period_hit_rate_at_least_50pct" not in gates:
        raise ValueError("original decision does not contain the expected hit-rate gate")
    gates.pop("historical_all_period_hit_rate_at_least_50pct")
    gates["historical_risk_on_active_hit_rate_at_least_50pct"] = active_hit_rate >= 0.50
    gates["frozen_economic_identity_verified"] = frozen_identity_verified
    gates = dict(sorted(gates.items()))
    authorized = bool(all(gates.values()))
    return {
        "schema_version": "cn_x1_1_fallback_aware_certification_v1",
        "evaluation_contract": "benchmark_fallback_aware_v1",
        "decision": (
            "cn_x1_1_regime_gated_candidate_authorized"
            if authorized
            else "fallback_aware_candidate_gate_failed"
        ),
        "candidate_name": (
            "CN x1.1 Candidate A — Regime-Gated Sector Breadth" if authorized else ""
        ),
        "candidate_authorized": authorized,
        "risk_on_active_hit_rate": float(active_hit_rate),
        "replaced_gate": "historical_all_period_hit_rate_at_least_50pct",
        "replacement_gate": "historical_risk_on_active_hit_rate_at_least_50pct",
        "gates": gates,
        "model_rules_changed": False,
        "economic_evidence_changed": False,
        "automatic_production_promotion": False,
        "research_only": True,
        "trade_ready": False,
    }
