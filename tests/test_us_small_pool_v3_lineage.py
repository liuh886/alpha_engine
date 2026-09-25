from __future__ import annotations

from pathlib import Path

import yaml

POOL = Path("configs/pools/us_small_pool_v3.yaml")
SEC_CONTRACT = Path("configs/providers/sec_companyfacts_fundamentals_v3.yaml")
CIK_MAPPING = Path("configs/providers/us_small_pool_sec_cik_v3.yaml")
FACTOR_CONTRACT = Path("configs/factors/us_fundamental_acceleration_v3.yaml")
MULTIFACTOR_CONTRACT = Path("configs/factors/us_low_turnover_multifactor_v2.yaml")
ROTATION_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v4.yaml"
)
CUTOVER_CONTRACT = Path("configs/operations/prospective_shadow_cutover_v2.yaml")


def _load(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _pool_symbols(pool: dict) -> set[str]:
    return {
        str(symbol).upper()
        for basket in pool["baskets"].values()
        for symbol in basket["symbols"]
    }


def test_v3_pool_replaces_every_annual_only_foreign_symbol() -> None:
    pool = _load(POOL)

    assert pool["pool_id"] == "us_small_pool_v3"
    assert pool["parent_pool_id"] == "us_small_pool_v2"
    symbols = _pool_symbols(pool)
    assert len(symbols) == 23
    removed = {
        str(correction["removed_symbol"])
        for correction in pool["corrections_from_parent"]
        if "removed_symbol" in correction
    }
    added = {
        str(correction["added_symbol"])
        for correction in pool["corrections_from_parent"]
        if "added_symbol" in correction
    }
    assert removed == {"TSM", "POET", "NOK", "NBIS", "IREN", "PDD", "JD"}
    assert added <= symbols
    assert not (removed & symbols)


def test_v3_lineage_contracts_pin_the_v3_pool() -> None:
    assert (
        _load(SEC_CONTRACT)["pool_spec"] == "configs/pools/us_small_pool_v3.yaml"
    )
    assert (
        _load(FACTOR_CONTRACT)["pool_spec"] == "configs/pools/us_small_pool_v3.yaml"
    )
    assert (
        _load(MULTIFACTOR_CONTRACT)["pool_spec"]
        == "configs/pools/us_small_pool_v3.yaml"
    )
    assert _load(ROTATION_SPEC)["pool_spec"] == "configs/pools/us_small_pool_v3.yaml"
    cutover = _load(CUTOVER_CONTRACT)["markets"]["us"]
    assert cutover["pool_id"] == "us_small_pool_v3"
    assert cutover["rotation_spec"].endswith(
        "us_structured_pool_hierarchical_rotation_v4.yaml"
    )


def test_v3_cik_mapping_covers_exactly_the_v3_pool() -> None:
    pool = _load(POOL)
    mapping = _load(CIK_MAPPING)

    assert mapping["pool_id"] == "us_small_pool_v3"
    assert set(mapping["symbols"]) == _pool_symbols(pool)
    for cik in mapping["symbols"].values():
        assert len(str(cik)) == 10 and str(cik).isdigit()


def test_daily_decision_defaults_point_at_the_v3_lineage() -> None:
    script = Path("scripts/run_latest_us_low_turnover_decision.py").read_text(
        encoding="utf-8"
    )
    for expected in (
        "us_small_pool_v3.yaml",
        "sec_companyfacts_fundamentals_v3.yaml",
        "us_fundamental_acceleration_v3.yaml",
        "us_structured_pool_hierarchical_rotation_v4.yaml",
        "us_low_turnover_multifactor_v2.yaml",
        "prospective_shadow_cutover_v2.yaml",
    ):
        assert expected in script
