"""Generic governed canonical construction for frozen CN ETF candidates.

This module intentionally does not replace the immutable 515180 implementation.
It provides the same audit-only secondary-source and open-eligibility contract
for the pre-registered 512890.SH and 511010.SH challengers in Issue #546.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.data.byd_canonical_bundle import (
    CanonicalBundle,
    build_canonical_bundle,
    dataframe_sha256,
)

SCHEMA_VERSION = "cn_etf_candidate_total_return_v1"
OPEN_RETURN_TOLERANCE = 0.01
MIN_ROWS = 1500
MIN_SECONDARY_COVERAGE = 0.97
MIN_OPEN_RETURN_CORRELATION = 0.995
MAX_P99_OPEN_RETURN_DIFFERENCE = 0.01
MIN_ELIGIBLE_OPEN_COVERAGE = 0.95


@dataclass(frozen=True)
class ETFSpec:
    symbol: str
    provider_symbol: str
    cutoff: str


@dataclass(frozen=True)
class ETFCanonicalQuality:
    passed: bool
    gates: dict[str, bool]


def _manifest_sha(manifest: dict[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_candidate_bundle(
    *,
    spec: ETFSpec,
    raw_primary: pd.DataFrame,
    provider_adjusted_close: pd.DataFrame,
    corporate_actions: pd.DataFrame,
    raw_secondary: pd.DataFrame | None,
    secondary_provider: str | None,
    provider_parameters: dict[str, Any],
) -> tuple[CanonicalBundle, ETFCanonicalQuality]:
    """Build one candidate without stitching or filling provider rows."""

    base = build_canonical_bundle(
        raw_primary=raw_primary,
        provider_adjusted_close=provider_adjusted_close,
        cutoff=spec.cutoff,
        primary_provider="yfinance_unadjusted_plus_adj_close",
        raw_secondary=raw_secondary,
        secondary_provider=secondary_provider,
        corporate_actions=corporate_actions,
        provider_parameters=provider_parameters,
    )

    sessions = base.session_audit.copy()
    comparison = base.provider_comparison.copy()
    if comparison.empty:
        sessions["secondary_open_return_difference"] = np.nan
        sessions["open_research_eligible"] = False
        secondary_coverage = 0.0
        p99_difference = None
    else:
        audit = comparison[["date", "absolute_return_difference"]].copy()
        sessions = sessions.merge(audit, on="date", how="left", validate="one_to_one")
        sessions = sessions.rename(
            columns={"absolute_return_difference": "secondary_open_return_difference"}
        )
        common = sessions["secondary_status"].eq("common")
        traded = sessions["session_status"].eq("traded")
        difference_ok = sessions["secondary_open_return_difference"].le(
            OPEN_RETURN_TOLERANCE
        ) | sessions["secondary_open_return_difference"].isna()
        sessions["open_research_eligible"] = common & traded & difference_ok
        secondary_coverage = float(common.mean())
        valid_diff = comparison["absolute_return_difference"].dropna()
        p99_difference = (
            float(valid_diff.quantile(0.99)) if not valid_diff.empty else None
        )

    manifest = dict(base.manifest)
    manifest.update(
        {
            "schema_version": SCHEMA_VERSION,
            "symbol": spec.symbol,
            "provider_symbol": spec.provider_symbol,
            "open_label_policy": (
                "entry_and_exit_open_must_be_primary_traded_secondary_confirmed_"
                "and_within_1pct_open_return_difference"
            ),
            "secondary_coverage": secondary_coverage,
            "p99_open_return_difference": p99_difference,
            "research_eligible_opens": int(
                sessions["open_research_eligible"].fillna(False).sum()
            ),
            "cash_dividend_semantics": (
                "corporate_actions_are_sealed_separately_from_adjusted_total_return_prices"
            ),
            "cross_provider_stitching": False,
            "data_quality_status": "pending",
        }
    )
    correlation = manifest.get("common_return_correlation")
    eligible_coverage = float(
        sessions["open_research_eligible"].fillna(False).mean()
    )
    gates = {
        "exact_cutoff": manifest["last_date"] == spec.cutoff,
        "minimum_history": int(manifest["rows"]) >= MIN_ROWS,
        "no_unexplained_factor_jumps": int(manifest["unexplained_factor_jumps"]) == 0,
        "secondary_coverage": secondary_coverage >= MIN_SECONDARY_COVERAGE,
        "open_return_correlation": (
            correlation is not None
            and np.isfinite(float(correlation))
            and float(correlation) >= MIN_OPEN_RETURN_CORRELATION
        ),
        "p99_open_return_difference": (
            p99_difference is not None
            and np.isfinite(p99_difference)
            and p99_difference <= MAX_P99_OPEN_RETURN_DIFFERENCE
        ),
        "eligible_open_coverage": eligible_coverage >= MIN_ELIGIBLE_OPEN_COVERAGE,
    }
    quality = ETFCanonicalQuality(passed=all(gates.values()), gates=gates)
    manifest["quality_gates"] = gates
    manifest["eligible_open_coverage"] = eligible_coverage
    manifest["data_quality_status"] = (
        "canonical_v1_pass" if quality.passed else "canonical_v1_blocked"
    )
    manifest["session_audit_sha256"] = dataframe_sha256(sessions)
    manifest["manifest_sha256"] = _manifest_sha(manifest)

    return (
        CanonicalBundle(
            raw_bars=base.raw_bars,
            adjustment_factors=base.adjustment_factors,
            adjusted_bars=base.adjusted_bars,
            corporate_actions=base.corporate_actions,
            session_audit=sessions,
            provider_comparison=base.provider_comparison,
            manifest=manifest,
        ),
        quality,
    )
