from pathlib import Path

import pytest
import yaml

from scripts.run_selected_pool_ranker_retest import run
from src.research.multi_market_readiness import load_market_watchlist
from src.research.paradigm import load_research_paradigm_spec


OLD_US_SPEC = Path(
    "configs/research_paradigms/us_10d_lgbm_xgb_ranker_comparison.yaml"
)
US_SPEC = Path(
    "configs/research_paradigms/us_10d_selected_pool_ranker_retest_v1.yaml"
)
CN_SPEC = Path(
    "configs/research_paradigms/cn_10d_selected_pool_ranker_retest_v1.yaml"
)
US_POOL = Path("configs/research_universes/us_selected_equities_v2.yaml")
CN_POOL = Path("configs/research_universes/cn_selected_equities_v3.yaml")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_us_retest_changes_only_the_selected_opportunity_set() -> None:
    old = _load(OLD_US_SPEC)
    new = _load(US_SPEC)

    assert new["universe"]["source"] == str(US_POOL)
    assert new["universe"]["universe_id"] == "us_selected_equities_v2"
    assert new["universe"]["exact_pool_candidate_count"] == 87
    assert new["universe"]["min_symbols"] == old["universe"]["min_symbols"] == 30
    assert new["universe"]["alignment_mode"] == old["universe"]["alignment_mode"] == "auto"
    assert new["universe"]["listing_policy"] == (
        "no_prelisting_fill_coverage_qualified_static_members"
    )

    assert new["factor_library"] == old["factor_library"]
    assert new["candidate_grid"] == old["candidate_grid"]
    assert new["strategy"] == old["strategy"]
    assert new["walk_forward"] == old["walk_forward"]
    assert new["evaluation"] == old["evaluation"]


def test_cn_retest_uses_one_frozen_ranker_calibration() -> None:
    spec = _load(CN_SPEC)
    ranker = spec["candidate_grid"]["ranker"]

    assert spec["universe"]["source"] == str(CN_POOL)
    assert spec["universe"]["universe_id"] == "cn_selected_equities_v3"
    assert spec["universe"]["exact_pool_candidate_count"] == 130
    assert spec["universe"]["min_symbols"] == 30
    assert spec["universe"]["alignment_mode"] == "auto"
    assert spec["universe"]["listing_policy"] == (
        "no_prelisting_fill_coverage_qualified_static_members"
    )
    assert spec["factor_library"]["groups"] == ["cn_balanced_ohlcv"]
    assert ranker["model_families"] == ["lgbm", "xgb"]
    assert ranker["calibrations"] == [
        {
            "n_gain_bins": 5,
            "num_boost_round": 100,
            "num_leaves": 31,
            "min_data_in_leaf": 10,
            "learning_rate": 0.05,
        }
    ]


def test_selected_pools_are_exact_and_references_are_separate() -> None:
    us = _load(US_POOL)
    cn = _load(CN_POOL)

    assert len(us["symbols"]) == us["candidate_count"] == 87
    assert len(cn["symbols"]) == cn["candidate_count"] == 130
    assert len(set(us["symbols"])) == 87
    assert len(set(cn["symbols"])) == 130
    assert "QQQ" not in us["symbols"]
    assert "000300" not in cn["symbols"]


def test_governed_selected_pool_schema_loads_exact_symbols() -> None:
    assert load_market_watchlist("us", watchlist_path=US_POOL) == _load(US_POOL)[
        "symbols"
    ]
    assert load_market_watchlist("cn", watchlist_path=CN_POOL) == _load(CN_POOL)[
        "symbols"
    ]


def test_governed_selected_pool_schema_fails_on_wrong_market() -> None:
    with pytest.raises(ValueError, match="market mismatch"):
        load_market_watchlist("us", watchlist_path=CN_POOL)


def test_governed_selected_pool_schema_fails_on_count_drift(tmp_path: Path) -> None:
    malformed = _load(CN_POOL)
    malformed["candidate_count"] = 129
    path = tmp_path / "malformed.yaml"
    path.write_text(yaml.safe_dump(malformed), encoding="utf-8")

    with pytest.raises(ValueError, match="candidate_count mismatch"):
        load_market_watchlist("cn", watchlist_path=path)


def test_retest_specs_pass_the_canonical_parser() -> None:
    us = load_research_paradigm_spec(US_SPEC)
    cn = load_research_paradigm_spec(CN_SPEC)

    assert us.experiment_id == "us_10d_selected_pool_ranker_retest_v1"
    assert cn.experiment_id == "cn_10d_selected_pool_ranker_retest_v1"
    assert us.strategy["research_only"] is True
    assert cn.strategy["research_only"] is True


def test_us_run_fails_closed_without_exact_refreshed_provider() -> None:
    payload = run(Path.cwd(), markets=("us",))
    market = payload["markets"]["us"]

    assert payload["overall_status"] == "selected_pool_ranker_data_blocked"
    assert market["status"] == "selected_pool_ranker_data_blocked"
    assert "provider" in market["reason"].lower()
