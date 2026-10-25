"""Sector ETF research admission. This does not register tradable instruments."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from .outcomes import PriceBar


@dataclass(frozen=True)
class SectorETFCandidate:
    symbol: str
    sector: str
    fund_inception: date
    exchange_listing: date | None
    reference_url: str
    verified_adjusted_total_return: bool = False
    liquidity_coverage_verified: bool = False
    pit_sector_mapping_verified: bool = False
    source_history_verified: bool = False


def audit_sector_etf(
    candidate: SectorETFCandidate,
    prices: Sequence[PriceBar],
    *,
    required_last_session: date,
    min_sessions: int = 250,
) -> dict[str, object]:
    """Never treat NAV, prelisting history, raw bars or unadjusted bars as qualified."""
    blockers: list[str] = []
    if not candidate.symbol or not candidate.sector or not candidate.reference_url:
        blockers.append("missing_instrument_identity")
    if candidate.exchange_listing is None:
        blockers.append("listing_date_unknown")
    elif candidate.exchange_listing < candidate.fund_inception:
        blockers.append("inconsistent_fund_lifecycle")
    if candidate.exchange_listing is not None and prices and prices[0].session < candidate.exchange_listing:
        blockers.append("pre_listing_prices_not_eligible")
    dates = [p.session for p in prices]
    if dates != sorted(set(dates)):
        blockers.append("duplicate_or_out_of_order_session")
    if len(dates) < min_sessions or not dates or dates[-1] < required_last_session:
        blockers.append("insufficient_verified_history")
    for ok, name in (
        (candidate.verified_adjusted_total_return, "adjusted_distribution_basis_not_verified"),
        (candidate.liquidity_coverage_verified, "liquidity_not_verified"),
        (candidate.pit_sector_mapping_verified, "pit_sector_mapping_not_verified"),
        (candidate.source_history_verified, "provider_history_not_verified"),
    ):
        if not ok:
            blockers.append(name)
    return {
        "symbol": candidate.symbol,
        "sector": candidate.sector,
        "status": "eligible_for_research" if not blockers else "blocked",
        "blockers": blockers,
        "observed_sessions": len(dates),
        "active_strategy_registration": False,
    }
