from __future__ import annotations

from src.research.ranker_calibration_grid import (
    build_ranker_calibration_grid,
    default_ranker_calibrations,
    default_ranker_feature_groups,
    grid_manifest,
)


def test_default_ranker_feature_groups_are_compact_and_named() -> None:
    groups = default_ranker_feature_groups()

    assert [group.name for group in groups] == [
        "momentum",
        "momentum_volatility",
        "momentum_volatility_volume",
        "risk_controlled_momentum",
    ]
    assert all(group.expressions for group in groups)
    assert len(groups[-1].expressions) > len(groups[0].expressions)


def test_default_ranker_calibrations_cover_gain_and_complexity_grid() -> None:
    calibrations = default_ranker_calibrations()

    assert [item.n_gain_bins for item in calibrations] == [3, 5, 7, 10]
    assert {item.num_boost_round for item in calibrations} == {100, 200}
    assert all(item.params()["min_data_in_leaf"] == item.min_data_in_leaf for item in calibrations)
    assert all(item.params()["learning_rate"] == item.learning_rate for item in calibrations)


def test_ranker_calibration_grid_builds_unique_lgbm_candidates() -> None:
    candidates = build_ranker_calibration_grid()
    names = [candidate.name for candidate in candidates]

    assert len(candidates) == 16
    assert len(names) == len(set(names))
    assert all(name.startswith("lgbm:daily_ranker:") for name in names)
    assert any(":risk_controlled_momentum:" in name for name in names)


def test_grid_manifest_is_serializable_and_rejects_duplicate_names() -> None:
    candidates = build_ranker_calibration_grid()
    manifest = grid_manifest(candidates)

    assert manifest["schema_version"] == "1.0"
    assert manifest["n_candidates"] == 16
    assert len(manifest["candidates"]) == 16
    assert manifest["candidates"][0]["feature_group"]["expressions"]
    assert manifest["candidates"][0]["calibration"]["name"]
