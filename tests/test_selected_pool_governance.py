from pathlib import Path

import yaml

from src.data.universe import get_selected_tickers
from src.research.selected_pool_guard import resolve_selected_pool


US_SELECTED = Path("configs/research_universes/us_selected_equities_v2.yaml")
CN_SELECTED = Path("configs/research_universes/cn_selected_equities_v2.yaml")
US_STRATEGY_POOL = Path("configs/pools/us_small_pool_v2.yaml")
REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
CIK_MAPPING = Path("configs/providers/us_small_pool_sec_cik_v2.yaml")
LIFECYCLE = Path("configs/data_quality/symbol_identity_and_lifecycle_v1.yaml")
US_SPEC = Path("configs/research_paradigms/us_structured_pool_hierarchical_rotation_v3.yaml")

US_APPROVED_REMOVALS = {
    "GOOG", "STX", "PAYX", "CHTR", "CMCSA", "WBD", "KHC", "KDP",
    "CCEP", "MDLZ", "MNST", "ROST", "AEP", "EXC", "XEL", "BABA",
    "BIDU", "CSGP", "TRI", "VRSK", "CTSH", "FTNT", "ZS", "WDAY",
    "TEAM", "ADBE", "MCHP", "NXPI", "TXN", "ADI", "MAR", "ABNB",
    "SBUX", "AMGN", "GILD", "ALNY", "INSM", "IDXX", "DXCM", "PYPL",
    "MSTR", "CSX", "ODFL", "PCAR", "FAST", "FER",
}
CN_APPROVED_REMOVALS = {
    "000656", "002157", "002607", "601933", "000002", "001979",
    "600048", "000069", "002146", "002271", "603833", "600000",
    "600016", "601398", "601939", "601988", "601288", "601328",
    "601658", "601818", "601998", "601169", "601229", "601009",
    "600919", "000166", "000776", "000783", "600958", "600999",
    "601066", "601211", "601377", "601688", "601788", "601878",
    "601881", "601901", "002673", "002736", "601319", "601336",
    "601628", "601601", "600104", "601238", "000625", "000800",
    "600741", "600170", "601186", "601390", "601618", "601668",
    "601800", "002074", "002129", "002120",
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _strategy_symbols(pool: dict) -> set[str]:
    return {
        str(symbol).upper()
        for basket in pool["baskets"].values()
        for symbol in basket["symbols"]
    }


def test_us_strategy_pool_fixes_entity_and_history_errors() -> None:
    pool = _load(US_STRATEGY_POOL)
    symbols = _strategy_symbols(pool)

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

    sndk = pool["forward_only_symbols"]["SNDK"]
    assert sndk["independent_history_start"] == "2025-02-24"
    assert sndk["eligible_for_historical_validation"] is False


def test_user_approved_selected_universes_are_active_and_exact() -> None:
    us = _load(US_SELECTED)
    cn = _load(CN_SELECTED)
    us_symbols = set(us["symbols"])
    cn_symbols = set(cn["symbols"])

    assert us["status"] == "active_selected_pool"
    assert cn["status"] == "active_selected_pool"
    assert len(us_symbols) == us["candidate_count"] == 87
    assert len(cn_symbols) == cn["candidate_count"] == 163
    assert "TIGO" in us_symbols
    assert "TYGO" in us_symbols
    assert US_APPROVED_REMOVALS.isdisjoint(us_symbols)
    assert CN_APPROVED_REMOVALS.isdisjoint(cn_symbols)
    assert {"600837", "601989"}.isdisjoint(cn_symbols)
    assert set(us["approved_removals"]) == US_APPROVED_REMOVALS
    assert set(cn["approved_removals"]) == CN_APPROVED_REMOVALS


def test_selected_pool_cik_mapping_is_exact_for_strategy_pool() -> None:
    pool = _load(US_STRATEGY_POOL)
    mapping = _load(CIK_MAPPING)

    assert mapping["pool_id"] == pool["pool_id"]
    assert set(mapping["symbols"]) == _strategy_symbols(pool)
    assert mapping["symbols"]["TYGO"] == "0001855447"
    assert mapping["symbols"]["WDC"] == "0000106040"
    assert "TIGO" not in mapping["symbols"]
    assert "SNDK" not in mapping["symbols"]


def test_future_runs_are_bound_to_user_approved_selected_universes() -> None:
    registry = _load(REGISTRY)
    us = registry["markets"]["us"]
    cn = registry["markets"]["cn"]
    spec = _load(US_SPEC)

    assert registry["policy"]["new_experiments_must_use_selected_pool"] is True
    assert registry["policy"]["new_backtests_must_use_selected_pool"] is True
    assert registry["policy"]["broad_universe_runs_are_legacy_or_diagnostic_only"] is True

    assert us["active_pool_id"] == "us_selected_equities_v2"
    assert us["pool_spec"] == str(US_SELECTED)
    assert us["active_strategy_pool_id"] == "us_small_pool_v2"
    assert us["new_authoritative_runs_allowed"] is True
    assert spec["pool_spec"] == us["active_strategy_pool_spec"]
    assert spec["pool_governance"]["allow_broad_universe_fallback"] is False

    assert cn["active_pool_id"] == "cn_selected_equities_v2"
    assert cn["pool_spec"] == str(CN_SELECTED)
    assert cn["new_authoritative_runs_allowed"] is True
    assert set(cn["mandatory_exclusions_after_terminal_date"]) == {"600837", "601989"}


def test_authoritative_guard_and_data_universe_resolve_both_markets() -> None:
    us = resolve_selected_pool("us")
    cn = resolve_selected_pool("cn")

    assert us.pool_id == "us_selected_equities_v2"
    assert us.pool_spec == US_SELECTED.resolve()
    assert cn.pool_id == "cn_selected_equities_v2"
    assert cn.pool_spec == CN_SELECTED.resolve()

    assert get_selected_tickers("us", Path(".")) == _load(US_SELECTED)["symbols"]
    assert get_selected_tickers("cn", Path(".")) == _load(CN_SELECTED)["symbols"]


def test_symbol_lifecycle_rules_fail_closed() -> None:
    lifecycle = _load(LIFECYCLE)["rules"]

    assert lifecycle["orphan_or_corrupt_files"]["ALBA"]["action"] == "delete_from_active_data"
    assert lifecycle["ticker_identity_conflicts"]["TIGO"]["retained_in_selected_universe"] is True
    assert lifecycle["ticker_identity_conflicts"]["TIGO"]["intended_symbol_for_tigo_energy"] == "TYGO"
    assert lifecycle["independent_listing_boundaries"]["TYGO"]["public_trading_start"] == "2023-05-24"
    assert lifecycle["independent_listing_boundaries"]["SNDK"]["authoritative_backtest_before_start_allowed"] is False
    assert lifecycle["terminal_listings"]["600837"]["active_universe_after_terminal_date_allowed"] is False
    assert lifecycle["terminal_listings"]["601989"]["active_universe_after_terminal_date_allowed"] is False


def test_approved_csv_files_are_removed_but_millicom_and_terminal_history_remain() -> None:
    for symbol in sorted(US_APPROVED_REMOVALS | CN_APPROVED_REMOVALS):
        assert not Path(f"data/csv_clean/{symbol}.csv").exists(), symbol

    assert Path("data/csv_clean/TIGO.csv").exists()
    assert Path("data/csv_clean/600837.csv").exists()
    assert Path("data/csv_clean/601989.csv").exists()
    assert not Path("data/csv_clean/ALBA.csv").exists()


def test_active_strategy_entrypoints_do_not_default_to_legacy_pool() -> None:
    snapshot_script = Path("scripts/build_us_pool_price_snapshot.py").read_text(encoding="utf-8")
    fundamental_script = Path("scripts/run_latest_us_fundamental_validation.py").read_text(encoding="utf-8")

    assert "us_small_pool_v2" in snapshot_script
    assert "selected_us_pool_price_snapshot" in snapshot_script
    assert "us_small_pool_v2" in fundamental_script
    assert "selected_us_fundamental_validation" in fundamental_script
    assert "us_small_pool_v1" not in snapshot_script
    assert "us_small_pool_v1" not in fundamental_script
