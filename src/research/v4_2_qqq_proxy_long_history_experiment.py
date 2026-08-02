"""QQQ proxy long-history evidence for the frozen v4.2 recovery precursor.

The proxy replaces QQQI adjusted bars with an exact copy of QQQ adjusted bars.
It is used only to expand the number of observable recovery-precursor events.
The actual QQQI sample remains authoritative for product-specific economics.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.v4_2_sgov_precursor_50_experiment import (
    BOLD_KEY,
    PRIOR_KEY,
    run_precursor_50_comparison,
)


def alias_qqqi_to_qqq(
    bars: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Return a copied bar mapping with QQQI mechanically aliased to QQQ."""

    if "QQQ" not in bars:
        raise ValueError("QQQ bars are required for the QQQI proxy")
    proxied = {symbol: frame.copy() for symbol, frame in bars.items()}
    proxied["QQQI"] = bars["QQQ"].copy()
    if not proxied["QQQI"].equals(proxied["QQQ"]):
        raise AssertionError("QQQI proxy must exactly equal QQQ bars")
    return proxied


def _normalise_event_dates(table: pd.DataFrame) -> pd.DataFrame:
    result = table.copy()
    for column in ("start_date", "end_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column])
    return result


def overlap_event_concordance(
    actual_events: pd.DataFrame,
    proxy_events: pd.DataFrame,
) -> pd.DataFrame:
    """Match actual and proxy marginal events and compare their directions."""

    actual = _normalise_event_dates(actual_events)
    proxy = _normalise_event_dates(proxy_events)
    columns = ["start_date", "end_date", "sessions", "event_relative_return"]
    if actual.empty:
        return pd.DataFrame(
            columns=[
                "start_date",
                "end_date",
                "sessions_actual",
                "sessions_proxy",
                "actual_marginal_return",
                "proxy_marginal_return",
                "direction_match",
            ]
        )
    missing_actual = sorted(set(columns) - set(actual.columns))
    missing_proxy = sorted(set(columns) - set(proxy.columns))
    if missing_actual or missing_proxy:
        raise ValueError(
            f"event tables missing columns: actual={missing_actual}, proxy={missing_proxy}"
        )
    merged = actual[columns].merge(
        proxy[columns],
        on=["start_date", "end_date"],
        how="left",
        suffixes=("_actual", "_proxy"),
        validate="one_to_one",
    )
    merged = merged.rename(
        columns={
            "event_relative_return_actual": "actual_marginal_return",
            "event_relative_return_proxy": "proxy_marginal_return",
        }
    )
    merged["direction_match"] = (
        np.sign(merged["actual_marginal_return"])
        == np.sign(merged["proxy_marginal_return"])
    ) & merged["proxy_marginal_return"].notna()
    return merged


def _long_sample_support_gate(
    actual_diagnostics: Mapping[str, Any],
    proxy_diagnostics: Mapping[str, Any],
    actual_events: pd.DataFrame,
    proxy_events: pd.DataFrame,
    concordance: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]
    proxy_shadow = proxy_diagnostics["shadow_gate"]
    proxy_metrics = proxy_shadow["metrics"]
    actual_count = int(len(actual_events))
    proxy_count = int(len(proxy_events))
    matched = int(concordance["proxy_marginal_return"].notna().sum())
    sign_concordance = (
        float(concordance["direction_match"].mean()) if len(concordance) else 0.0
    )
    actual_start = pd.Timestamp(actual_diagnostics["common_sample_start"])
    proxy_start = pd.Timestamp(proxy_diagnostics["common_sample_start"])

    metrics = {
        "actual_qqqi_precursor_event_count": actual_count,
        "qqq_proxy_precursor_event_count": proxy_count,
        "additional_proxy_events": proxy_count - actual_count,
        "matched_actual_events_in_overlap": matched,
        "overlap_event_sign_concordance": sign_concordance,
        "actual_sample_start": actual_start.date().isoformat(),
        "proxy_sample_start": proxy_start.date().isoformat(),
        "long_sample_full_cagr_delta_50_vs_25_pp": float(
            proxy_metrics["full_sample_cagr_delta_vs_25_pp"]
        ),
        "long_sample_early_cagr_delta_50_vs_25_pp": float(
            proxy_metrics["early_segment_cagr_delta_vs_25_pp"]
        ),
        "long_sample_late_cagr_delta_50_vs_25_pp": float(
            proxy_metrics["late_segment_cagr_delta_vs_25_pp"]
        ),
        "long_sample_marginal_event_positive_rate": float(
            proxy_metrics["marginal_event_positive_rate_vs_25"]
        ),
        "long_sample_largest_event_benefit_share": float(
            proxy_metrics["largest_marginal_event_benefit_share"]
        ),
    }
    checks = {
        "minimum_long_sample_precursor_events": proxy_count
        >= int(thresholds["minimum_long_sample_precursor_events"]),
        "minimum_additional_events": proxy_count - actual_count
        >= int(thresholds["minimum_additional_events_vs_actual_qqqi_sample"]),
        "all_actual_events_matched": (
            matched == actual_count
            if bool(thresholds["require_all_actual_events_matched_in_overlap"])
            else True
        ),
        "overlap_event_sign_concordance": sign_concordance
        >= float(thresholds["overlap_event_sign_concordance_min"]),
        "proxy_sample_starts_earlier": (
            proxy_start < actual_start
            if bool(thresholds["require_proxy_sample_start_before_actual_sample_start"])
            else True
        ),
        "full_cagr_delta_50_vs_25": (
            metrics["long_sample_full_cagr_delta_50_vs_25_pp"] >= 0.0
            if bool(
                thresholds[
                    "require_long_sample_50_vs_25_full_cagr_delta_nonnegative"
                ]
            )
            else True
        ),
        "early_cagr_delta_50_vs_25": (
            metrics["long_sample_early_cagr_delta_50_vs_25_pp"] >= 0.0
            if bool(
                thresholds[
                    "require_long_sample_50_vs_25_early_cagr_delta_nonnegative"
                ]
            )
            else True
        ),
        "late_cagr_delta_50_vs_25": (
            metrics["long_sample_late_cagr_delta_50_vs_25_pp"] >= 0.0
            if bool(
                thresholds[
                    "require_long_sample_50_vs_25_late_cagr_delta_nonnegative"
                ]
            )
            else True
        ),
        "marginal_event_positive_rate": metrics[
            "long_sample_marginal_event_positive_rate"
        ]
        >= float(thresholds["minimum_long_sample_marginal_event_positive_rate"]),
        "event_concentration": metrics["long_sample_largest_event_benefit_share"]
        <= float(thresholds["maximum_long_sample_largest_event_share"]),
    }
    return {
        "structural_support_for_50_percent_hypothesis": bool(all(checks.values())),
        "actionable_model_authorized": False,
        "direct_promotion_authorized": False,
        "checks": checks,
        "metrics": metrics,
    }


def run_qqq_proxy_long_history_comparison(
    bars: Mapping[str, pd.DataFrame],
    baseline_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    prior_release_contract: Mapping[str, Any],
    bold_contract: Mapping[str, Any],
    proxy_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Run actual QQQI and long-history QQQ-proxy comparisons side by side."""

    (
        actual_headline,
        actual_results,
        actual_chronological,
        actual_episodes,
        actual_events_vs_static,
        actual_marginal_events,
        actual_diagnostics,
    ) = run_precursor_50_comparison(
        bars,
        baseline_contract,
        sgov_contract,
        attribution_contract,
        prior_release_contract,
        bold_contract,
    )

    proxy_bars = alias_qqqi_to_qqq(bars)
    (
        proxy_headline,
        proxy_results,
        proxy_chronological,
        proxy_episodes,
        proxy_events_vs_static,
        proxy_marginal_events,
        proxy_diagnostics,
    ) = run_precursor_50_comparison(
        proxy_bars,
        baseline_contract,
        sgov_contract,
        attribution_contract,
        prior_release_contract,
        bold_contract,
    )

    concordance = overlap_event_concordance(
        actual_marginal_events,
        proxy_marginal_events,
    )
    support_gate = _long_sample_support_gate(
        actual_diagnostics,
        proxy_diagnostics,
        actual_marginal_events,
        proxy_marginal_events,
        concordance,
        proxy_contract,
    )
    if not proxy_results[BOLD_KEY].daily["precursor_active"].astype(bool).equals(
        proxy_results[PRIOR_KEY].daily["precursor_active"].astype(bool)
    ):
        raise AssertionError("QQQ proxy changed 25% versus 50% precursor dates")

    return {
        "actual_headline": actual_headline,
        "actual_results": actual_results,
        "actual_chronological": actual_chronological,
        "actual_episodes": actual_episodes,
        "actual_events_vs_static": actual_events_vs_static,
        "actual_marginal_events": actual_marginal_events,
        "actual_diagnostics": actual_diagnostics,
        "proxy_headline": proxy_headline,
        "proxy_results": proxy_results,
        "proxy_chronological": proxy_chronological,
        "proxy_episodes": proxy_episodes,
        "proxy_events_vs_static": proxy_events_vs_static,
        "proxy_marginal_events": proxy_marginal_events,
        "proxy_diagnostics": proxy_diagnostics,
        "overlap_concordance": concordance,
        "support_gate": support_gate,
        "proxy_definition": {
            "target_symbol": "QQQI",
            "source_symbol": "QQQ",
            "method": "exact_adjusted_bar_alias",
            "product_specific_claim_authorized": False,
        },
    }
