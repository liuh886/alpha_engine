"""Governed listing-lifecycle eligibility consumed by model selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.data.listing_lifecycle import (
    ListingLifecycleError,
    eligible_symbols,
    ineligible_symbols,
    load_terminal_listings,
)

ROOT = Path(__file__).resolve().parents[1]


def _registry(root: Path, body: str) -> Path:
    path = root / "configs" / "data_quality" / "symbol_identity_and_lifecycle_v1.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_real_registry_excludes_ea_after_suspension() -> None:
    # EA terminated 2026-08-04; suspension effective 2026-08-05.
    ineligible = ineligible_symbols(
        ROOT, market="us", as_of="2026-09-11", symbols=["EA", "AAPL"]
    )
    assert set(ineligible) == {"EA"}
    assert ineligible["EA"].terminal_date == "2026-08-04"
    assert ineligible["EA"].suspension_effective_date == "2026-08-05"


def test_real_registry_allows_ea_on_its_terminal_date() -> None:
    ineligible = ineligible_symbols(
        ROOT, market="us", as_of="2026-08-04", symbols=["EA"]
    )
    assert ineligible == {}


def test_real_registry_is_market_isolated() -> None:
    assert ineligible_symbols(ROOT, market="cn", as_of="2026-09-11", symbols=["EA"]) == {}
    cn = ineligible_symbols(
        ROOT, market="cn", as_of="2026-09-11", symbols=["600837", "601989", "000001"]
    )
    assert set(cn) == {"600837", "601989"}


def test_eligible_symbols_preserves_order_and_drops_terminal() -> None:
    assert eligible_symbols(ROOT, market="us", as_of="2026-09-11", symbols=["AAPL", "EA", "MSFT"]) == [
        "AAPL",
        "MSFT",
    ]


def test_missing_registry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ListingLifecycleError):
        load_terminal_listings(tmp_path, market="us")


def test_unsupported_active_universe_flag_is_not_excluded(tmp_path: Path) -> None:
    _registry(
        tmp_path,
        """
registry_id: symbol_identity_and_lifecycle_v1
rules:
  terminal_listings:
    ZZZ:
      market: us
      terminal_date: "2026-01-02"
      active_universe_after_terminal_date_allowed: true
      reason: not enforced
""",
    )
    assert ineligible_symbols(tmp_path, market="us", as_of="2026-09-11", symbols=["ZZZ"]) == {}


def test_missing_terminal_date_fails_closed(tmp_path: Path) -> None:
    _registry(
        tmp_path,
        """
registry_id: symbol_identity_and_lifecycle_v1
rules:
  terminal_listings:
    ZZZ:
      market: us
      active_universe_after_terminal_date_allowed: false
""",
    )
    with pytest.raises(ListingLifecycleError):
        load_terminal_listings(tmp_path, market="us")


def test_invalid_registry_identity_fails_closed(tmp_path: Path) -> None:
    _registry(tmp_path, "registry_id: something_else\nrules: {terminal_listings: {}}\n")
    with pytest.raises(ListingLifecycleError):
        load_terminal_listings(tmp_path, market="us")
