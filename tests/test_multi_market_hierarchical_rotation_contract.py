from pathlib import Path

import yaml


US_SPEC_PATH = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2_draft.yaml"
)
CN_SPEC_PATH = Path("configs/research_paradigms/cn_small_pool_sector_rotation_v1_draft.yaml")
CN_POOL_PATH = Path("configs/pools/cn_small_pool_v1_draft.yaml")
EXPECTED_BASELINES = [
    "equal_weight_pool_buy_and_hold",
    "time_series_state_only",
    "hierarchical_cross_section_only",
    "hierarchical_cross_section_plus_state",
]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_us_and_cn_contracts_are_market_isolated() -> None:
    us = _load(US_SPEC_PATH)
    cn = _load(CN_SPEC_PATH)

    assert us["market"] == "us"
    assert cn["market"] == "cn"
    assert us["benchmark"] == "QQQ"
    assert cn["benchmark"] == "000300.SH"
    assert us["pool_spec"] != cn["pool_spec"]
    assert us["architecture"]["cross_market_ranking_allowed"] is False
    assert cn["architecture"]["cross_market_ranking_allowed"] is False
    assert us["benchmarking"]["baselines"] == EXPECTED_BASELINES
    assert cn["benchmarking"]["baselines"] == EXPECTED_BASELINES


def test_cn_pool_is_exchange_aware_unique_and_non_authoritative() -> None:
    pool = _load(CN_POOL_PATH)
    baskets = pool["baskets"]
    symbols = [symbol for basket in baskets.values() for symbol in basket["symbols"]]
    metadata = pool["symbol_metadata"]

    assert pool["market"] == "cn"
    assert pool["status"] == "draft_requires_user_freeze"
    assert pool["authoritative_for_performance"] is False
    assert pool["membership_mode"] == "versioned_predeclared_draft"
    assert pool["silent_exclusion_allowed"] is False
    assert len(symbols) == 21
    assert len(symbols) == len(set(symbols))
    assert set(symbols) == set(metadata)
    assert all(symbol.endswith((".SH", ".SZ")) for symbol in symbols)
    assert all(len(basket["symbols"]) >= 2 for basket in baskets.values())
    assert set(pool["references"]).isdisjoint(symbols)
    assert all(str(row["provider_symbol"]).isdigit() for row in metadata.values())
    assert all(str(row["display_name"]).strip() for row in metadata.values())


def test_cn_draft_contains_repeated_user_focus_names() -> None:
    metadata = _load(CN_POOL_PATH)["symbol_metadata"]
    names = {row["display_name"] for row in metadata.values()}

    assert {
        "澜起科技",
        "沪电股份",
        "金盘科技",
        "通富微电",
        "光迅科技",
        "佰维存储",
        "长芯博创",
        "比亚迪",
        "紫金矿业",
        "天赐材料",
        "中天科技",
        "英维克",
    }.issubset(names)


def test_cn_microstructure_and_freeze_boundary_are_explicit() -> None:
    pool = _load(CN_POOL_PATH)
    spec = _load(CN_SPEC_PATH)
    microstructure = spec["market_microstructure"]

    assert spec["authoritative_validation_allowed"] is False
    assert spec["pool_governance"]["pool_must_be_frozen_before_performance"] is True
    assert microstructure == {
        "price_limit_aware": True,
        "suspension_aware": True,
        "st_status_aware": True,
        "delisting_status_aware": True,
        "corporate_action_adjustment_required": True,
        "same_day_unavailable_information_prohibited": True,
        "missing_session_policy": (
            "preserve_suspension_and_fail_closed_for_new_entries"
        ),
    }
    assert pool["membership_governance"]["freeze_requires_explicit_user_review"] is True


def test_same_security_cross_section_is_frozen_for_both_markets() -> None:
    for path in (US_SPEC_PATH, CN_SPEC_PATH):
        spec = _load(path)
        selection = spec["security_selection"]
        components = selection["cross_section"]["components"]

        assert selection["state_is_absolute_filter_not_primary_rank"] is True
        assert set(components) == {
            "relative_momentum_63_vs_benchmark",
            "momentum_20",
            "drawdown_from_63d_high",
            "realized_volatility_20",
        }
        assert {row["weight"] for row in components.values()} == {0.25}
        assert sum(row["weight"] for row in components.values()) == 1.0
        assert components["realized_volatility_20"]["direction"] == "lower_is_better"
        assert not any(spec["parameter_search"].values())
        assert spec["evidence"]["independent_reserved"]["start"] == "2026-07-01"
