"""Minimal Issue #966 Phase 1 definitions for volume/stat mechanism research.

The external QuantSkills repository is an idea/provenance source only. This
module contains independent Alpha Engine definitions and intentionally adds no
runtime, compatibility layer, or generated factor family.
"""

from __future__ import annotations

from src.factors.definition import FactorDefinition

NAMESPACE = "volume_stat_research"
SOURCE_REFERENCE = "docs/research/quantskills_volume_stat_alpha_review.md"


def load_volume_stat_research_definitions() -> list[FactorDefinition]:
    """Return only the genuinely new first-wave native research definition."""

    return [
        FactorDefinition.create(
            factor_id=f"{NAMESPACE}.signed_volume_balance_10d",
            factor_version="1.0",
            display_name="10-day signed volume balance",
            namespace=NAMESPACE,
            information_family="volume_flow",
            expression=(
                "Sum(Sign($close-Ref($close,1))*$volume,10)"
                "/(Mean($volume,10)+1e-12)"
            ),
            source_name="AlphaEngine independent volume/stat research",
            source_version="issue-966-phase1",
            source_reference=SOURCE_REFERENCE,
            required_fields=("close", "volume"),
            markets=("us", "cn"),
            minimum_lookback=11,
            availability_lag_sessions=0,
            adjustment_requirement="adjusted",
            status="unvalidated_formula",
        )
    ]
