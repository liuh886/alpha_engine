from __future__ import annotations

import json

from src.research.cn_feature_quality import (
    build_cn_feature_quality_grid,
    cn_factor_baseline_expressions,
    cn_feature_grid_manifest,
    cn_ranker_calibrations,
    cn_ranker_feature_groups,
)


def test_cn_feature_groups_are_named_and_non_empty() -> None:
    groups = cn_ranker_feature_groups()

    assert groups
    assert len({group.name for group in groups}) == len(groups)
    for group in groups:
        assert group.name.startswith("cn_")
        assert len(group.expressions) >= 6


def test_cn_feature_groups_use_common_ohlcv_fields_only() -> None:
    allowed = {"$close", "$high", "$low", "$volume"}
    joined = "\n".join(expr for group in cn_ranker_feature_groups() for expr in group.expressions)

    assert "$open" not in joined
    assert "$amount" not in joined
    for token in ("$close", "$volume"):
        assert token in joined
    for raw_field in ("$close", "$high", "$low", "$volume"):
        if raw_field in joined:
            assert raw_field in allowed


def test_cn_calibrations_are_small_and_stable() -> None:
    calibrations = cn_ranker_calibrations()

    assert len(calibrations) == 2
    assert all(c.num_boost_round <= 100 for c in calibrations)
    assert all(c.min_data_in_leaf >= 10 for c in calibrations)


def test_cn_feature_quality_grid_has_unique_candidate_names() -> None:
    grid = build_cn_feature_quality_grid()
    names = [candidate.name for candidate in grid]

    assert len(grid) == len(cn_ranker_feature_groups()) * len(cn_ranker_calibrations())
    assert len(names) == len(set(names))
    assert all(name.startswith("lgbm:daily_ranker:cn_") for name in names)


def test_cn_factor_baselines_are_named_as_factors() -> None:
    baselines = cn_factor_baseline_expressions()

    assert baselines
    assert set(baselines) == {
        "factor:cn_momentum_10d",
        "factor:cn_reversal_5d",
        "factor:cn_volatility_10d",
        "factor:cn_volume_shock_10d",
    }
    assert all(name.startswith("factor:cn_") for name in baselines)
    assert all("$close" in expr or "$volume" in expr for expr in baselines.values())


def test_cn_feature_grid_manifest_is_json_serializable() -> None:
    manifest = cn_feature_grid_manifest(build_cn_feature_quality_grid())
    encoded = json.dumps(manifest)
    restored = json.loads(encoded)

    assert restored["schema_version"] == "1.0"
    assert restored["n_candidates"] == 8
    assert len(restored["candidates"]) == 8
    assert "factor_baselines" in restored
