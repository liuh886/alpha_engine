from pathlib import Path

import pytest
import yaml

from src.research.selected_pool_guard import resolve_selected_pool


US_POOL = Path("configs/pools/us_small_pool_v2.yaml")
REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
CIK_MAPPING = Path("configs/providers/us_small_pool_sec_cik_v2.yaml")
LIFECYCLE = Path("configs/data_quality/symbol_identity_and_lifecycle_v1.yaml")
US_SPEC = Path("configs/research_paradigms/us_structured_pool_hierarchical_rotation_v3.yaml")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _candidate_symbols(pool: dict) -> set[str]:
    return {
        str(symbol).upper()
        for basket in pool["baskets"].values()
        for symbol in basket["symbols"]
    }


def test_us_selected_pool_fixes_entity_and_history_errors() -> None:
    pool = _load(US_POOL)
    symbols = _candidate_symbols(pool)

    assert pool["pool_id"] == "us_small_pool_v2"
    assert pool["parent_pool_id"] == "us_small_pool_v1"
    assert pool["status"] == "active_selected_pool"
    assert len(symbols) == 23
    assert "TYGO" in symbols
    assert "TIGO" not in symbols
    assert "WDC" in symbols
    assert "SNDK" not in symbols

    tygo = pool["symbol_history_constraints"]["TYGO"]
    assert tygo["public_trading_start"] == "2023-05-24"
    assert tygo["pre_start_policy"] == "unavailable_not_backfilled"
    assert tygo["eligible_after_start_only"] is True

    sndk = pool["forward_only_symbols"]["SNDK"]
    assert sndk["independent_history_start"] == "2025-02-24"
    assert sndk["pre_start_policy"] == "unavailable_not_backfilled"
    assert sndk["eligible_for_historical_validation"] is False
    assert sndk["eligible_for_prospective_shadow"] is True


def test_selected_pool_cik_mapping_is_exact() -> None:
    pool = _load(US_POOL)
    mapping = _load(CIK_MAPPING)

    assert mapping["pool_id"] == pool["pool_id"]
    assert set(mapping["symbols"]) == _candidate_symbols(pool)
    assert mapping["symbols"]["TYGO"] == "0001855447"
    assert mapping["symbols"]["WDC"] == "0000106040"
    assert "TIGO" not in mapping["symbols"]
    assert "SNDK" not in mapping["symbols"]


def test_future_runs_are_bound_to_selected_pool_registry() -> None:
    registry = _load(REGISTRY)
    us = registry["markets"]["us"]
    cn = registry["markets"]["cn"]
    spec = _load(US_SPEC)

    assert registry["policy"]["new_experiments_must_use_selected_pool"] is True
    assert registry["policy"]["new_backtests_must_use_selected_pool"] is True
    assert registry["policy"]["broad_universe_runs_are_legacy_or_diagnostic_only"] is True
    assert us["active_pool_id"] == "us_small_pool_v2"
    assert us["new_authoritative_runs_allowed"] is True
    assert spec["pool_spec"] == us["pool_spec"]
    assert spec["pool_governance"]["allow_broad_universe_fallback"] is False

    assert cn["status"] == "pending_user_selection"
    assert cn["new_authoritative_runs_allowed"] is False
    assert set(cn["mandatory_exclusions_after_terminal_date"]) == {"600837", "601989"}


def test_authoritative_guard_allows_us_and_blocks_cn() -> None:
    us = resolve_selected_pool("us")
    assert us.pool_id == "us_small_pool_v2"
    assert us.pool_spec == US_POOL.resolve()

    with pytest.raises(ValueError, match="authoritative cn run blocked"):
        resolve_selected_pool("cn")


def test_symbol_lifecycle_rules_fail_closed() -> None:
    lifecycle = _load(LIFECYCLE)["rules"]

    assert lifecycle["orphan_or_corrupt_files"]["ALBA"]["action"] == "delete_from_active_data"
    assert lifecycle["ticker_identity_conflicts"]["TIGO"]["intended_symbol_for_tigo_energy"] == "TYGO"
    assert lifecycle["independent_listing_boundaries"]["TYGO"]["public_trading_start"] == "2023-05-24"
    assert lifecycle["independent_listing_boundaries"]["TYGO"]["authoritative_backtest_before_start_allowed"] is False
    assert lifecycle["independent_listing_boundaries"]["SNDK"]["authoritative_backtest_before_start_allowed"] is False
    assert lifecycle["terminal_listings"]["600837"]["active_universe_after_terminal_date_allowed"] is False
    assert lifecycle["terminal_listings"]["601989"]["active_universe_after_terminal_date_allowed"] is False
    assert not Path("data/csv_clean/ALBA.csv").exists()


def test_active_entrypoints_do_not_default_to_legacy_pool() -> None:
    snapshot_script = Path("scripts/build_us_pool_price_snapshot.py").read_text(encoding="utf-8")
    fundamental_script = Path("scripts/run_latest_us_fundamental_validation.py").read_text(encoding="utf-8")

    assert "us_small_pool_v2" in snapshot_script
    assert "selected_us_pool_price_snapshot" in snapshot_script
    assert "us_small_pool_v2" in fundamental_script
    assert "selected_us_fundamental_validation" in fundamental_script
    assert "us_small_pool_v1" not in snapshot_script
    assert "us_small_pool_v1" not in fundamental_script
