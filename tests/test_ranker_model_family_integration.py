"""Focused integration tests for model_family in the ranker candidate path.

Covers: legacy default identity, two-family unique identities/manifest,
invalid family rejection, and dispatch uses true ranker adapters with
identical inputs/groups.
"""

from __future__ import annotations

from unittest import mock

import numpy as np
import pandas as pd
import pytest

from src.research.daily_ranker_model import (
    DailyRankerResult,
    fit_lgbm_daily_ranker,
    fit_xgb_daily_ranker,
    predict_lgbm_daily_ranker,
    predict_xgb_daily_ranker,
)
from src.research.paradigm import (
    ResearchParadigmSpec,
    build_ranker_candidates_from_spec,
    validate_research_paradigm_spec,
)
from src.research.qlib_execution_common import (
    fit_ranker_scores,
    materialize_ranker_candidates,
)
from src.research.ranker_calibration_grid import (
    VALID_MODEL_FAMILIES,
    RankerCalibration,
    RankerFeatureGroup,
    RankerGridCandidate,
    build_ranker_calibration_grid,
    grid_manifest,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_index(
    dates: list[str],
    instruments: list[str],
) -> pd.MultiIndex:
    return pd.MultiIndex.from_product(
        [pd.to_datetime(dates), instruments],
        names=["datetime", "instrument"],
    )


def _features(index: pd.MultiIndex, n_cols: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        rng.normal(size=(len(index), n_cols)),
        index=index,
        columns=[f"f{i}" for i in range(n_cols)],
    )


def _returns(index: pd.MultiIndex) -> pd.DataFrame:
    rng = np.random.default_rng(99)
    vals = rng.normal(loc=0.001, scale=0.02, size=len(index))
    returns = pd.DataFrame(vals, index=index, columns=["return"])
    returns.attrs["provenance"] = "raw_forward_return"
    returns.attrs["horizon"] = 10
    returns.attrs["expression"] = "Ref($close, -10) / $close - 1"
    return returns


# ---------------------------------------------------------------------------
# legacy default identity
# ---------------------------------------------------------------------------


def test_candidate_defaults_to_lgbm() -> None:
    """Every existing identity is unchanged — default model_family is 'lgbm'."""
    group = RankerFeatureGroup("momentum", ("a", "b"))
    cal = RankerCalibration(5, 100, 31, 10)
    candidate = RankerGridCandidate(group, cal)
    assert candidate.model_family == "lgbm"
    assert candidate.name.startswith("lgbm:daily_ranker:")


def test_grid_defaults_to_lgbm_only() -> None:
    """build_ranker_calibration_grid without model_families gives lgbm only."""
    groups = [RankerFeatureGroup("g", ("x",))]
    cals = [RankerCalibration(3, 50, 15, 5)]
    candidates = build_ranker_calibration_grid(groups, cals)
    assert len(candidates) == 1
    assert candidates[0].model_family == "lgbm"
    assert candidates[0].name == "lgbm:daily_ranker:g:gain3_round50_leaves15_leaf5_lr0.05"


def test_existing_to_dict_includes_model_family() -> None:
    """to_dict() carries model_family so effective contracts round-trip."""
    candidate = RankerGridCandidate(
        RankerFeatureGroup("m", ("a",)),
        RankerCalibration(5, 100, 31, 10),
    )
    d = candidate.to_dict()
    assert d["model_family"] == "lgbm"
    assert d["name"] == candidate.name


# ---------------------------------------------------------------------------
# two-family unique identities / manifest
# ---------------------------------------------------------------------------


def test_lgbm_and_xgb_produce_distinct_names() -> None:
    """Same feature group + calibration yields different names per model family."""
    group = RankerFeatureGroup("mv", ("a", "b"))
    cal = RankerCalibration(5, 100, 31, 10)
    lgbm = RankerGridCandidate(group, cal, model_family="lgbm")
    xgb = RankerGridCandidate(group, cal, model_family="xgb")
    assert lgbm.name == "lgbm:daily_ranker:mv:gain5_round100_leaves31_leaf10_lr0.05"
    assert xgb.name == "xgb:daily_ranker:mv:gain5_round100_leaves31_leaf10_lr0.05"
    assert lgbm.name != xgb.name


def test_two_family_grid_manifest_is_unique() -> None:
    """grid_manifest must accept distinct model_family candidates."""
    group = RankerFeatureGroup("mv", ("a", "b"))
    cal = RankerCalibration(5, 100, 31, 10)
    candidates = build_ranker_calibration_grid(
        [group], [cal], model_families=("lgbm", "xgb")
    )
    assert len(candidates) == 2
    manifest = grid_manifest(candidates)
    assert manifest["n_candidates"] == 2
    names = [c["name"] for c in manifest["candidates"]]
    assert len(names) == len(set(names))


def test_two_family_candidate_names_are_unique() -> None:
    """Same group/cal with two families yields two unique-named candidates."""
    group = RankerFeatureGroup("g", ("x",))
    cal = RankerCalibration(3, 50, 15, 5)
    candidates = build_ranker_calibration_grid(
        [group], [cal], model_families=("lgbm", "xgb")
    )
    names = [c.name for c in candidates]
    assert names == [
        "lgbm:daily_ranker:g:gain3_round50_leaves15_leaf5_lr0.05",
        "xgb:daily_ranker:g:gain3_round50_leaves15_leaf5_lr0.05",
    ]


# ---------------------------------------------------------------------------
# invalid family rejection
# ---------------------------------------------------------------------------


def test_invalid_model_family_raises() -> None:
    """RankerGridCandidate rejects model families outside the allowlist."""
    group = RankerFeatureGroup("g", ("x",))
    cal = RankerCalibration(5, 100, 31, 10)
    with pytest.raises(ValueError, match="model_family must be one of"):
        RankerGridCandidate(group, cal, model_family="catboost")


def test_build_grid_rejects_invalid_family() -> None:
    """build_ranker_calibration_grid rejects invalid model_families entries."""
    with pytest.raises(ValueError, match="model_families must be a subset"):
        build_ranker_calibration_grid(
            model_families=("lgbm", "catboost"),
        )


def test_spec_validation_rejects_invalid_model_families() -> None:
    """Paradigm spec validation rejects unknown model_families."""
    spec_dict = {
        "schema_version": "1.1",
        "experiment_id": "test_reject",
        "market": "us",
        "benchmark": "QQQ",
        "universe": {
            "source": "configs/research_universes/us_curated_equities_v1.yaml",
            "market_key": "us",
            "min_symbols": 30,
            "alignment_mode": "strict",
        },
        "factor_library": {
            "source": "configs/factor_libraries/ohlcv.yaml",
            "groups": ["momentum"],
        },
        "candidate_grid": {
            "ranker": {
                "model_families": ["lgbm", "catboost"],
                "calibrations": [
                    {
                        "n_gain_bins": 5,
                        "num_boost_round": 100,
                        "num_leaves": 31,
                        "min_data_in_leaf": 10,
                    }
                ],
            },
            "factor_baselines": ["ohlcv.momentum.ret_10d"],
        },
        "strategy": {
            "horizon_days": 10,
            "holding_days": 10,
            "rebalance_days": 10,
            "top_n": 15,
            "bottom_n": 15,
            "return_expression": "Ref($close, -10) / $close - 1",
            "return_provenance": "raw_forward_return",
            "research_only": True,
        },
        "walk_forward": {
            "requested_train_start": "2021-01-01",
            "test_end": "2026-06-18",
            "first_test_year": 2024,
            "last_test_year": 2026,
            "min_windows": 3,
            "train_embargo_sessions": 10,
            "partial_window_policy": "complete_windows_only",
        },
        "evaluation": {
            "benchmark_mode": "reference_only",
            "metrics": [
                "mean_icir",
                "mean_rank_ic",
                "mean_spread",
                "worst_drawdown",
                "ready_ratio",
                "positive_icir_ratio",
                "positive_spread_ratio",
            ],
            "gate_profile": "ten_day_model_gates_v1",
        },
        "outputs": {"artifact_profile": "research_run_v1"},
    }
    spec = ResearchParadigmSpec.from_dict(spec_dict, spec_path="")
    with pytest.raises(ValueError, match="model_families contains invalid"):
        validate_research_paradigm_spec(spec)


# ---------------------------------------------------------------------------
# materialization preserves model_family
# ---------------------------------------------------------------------------


def test_materialize_preserves_model_family() -> None:
    """materialize_ranker_candidates round-trips model_family from raw dicts."""
    from src.research.spec_bound_execution import SpecBoundExecutionPlan

    raw_candidate = {
        "name": "xgb:daily_ranker:mv:gain5_round100_leaves31_leaf10_lr0.05",
        "model_family": "xgb",
        "feature_group": {"name": "mv", "expressions": ["a", "b"]},
        "calibration": {
            "n_gain_bins": 5,
            "num_boost_round": 100,
            "num_leaves": 31,
            "min_data_in_leaf": 10,
            "learning_rate": 0.05,
        },
    }
    # Minimal plan stub
    plan = mock.Mock(spec=SpecBoundExecutionPlan)
    plan.candidates = [raw_candidate]
    materialized = materialize_ranker_candidates(plan)
    assert len(materialized) == 1
    assert materialized[0].model_family == "xgb"
    assert materialized[0].name == raw_candidate["name"]


def test_materialize_defaults_to_lgbm() -> None:
    """materialize_ranker_candidates defaults model_family to 'lgbm' when absent."""
    raw_candidate = {
        "name": "lgbm:daily_ranker:mv:gain5_round100_leaves31_leaf10_lr0.05",
        "feature_group": {"name": "mv", "expressions": ["a", "b"]},
        "calibration": {
            "n_gain_bins": 5,
            "num_boost_round": 100,
            "num_leaves": 31,
            "min_data_in_leaf": 10,
            "learning_rate": 0.05,
        },
    }
    plan = mock.Mock()
    plan.candidates = [raw_candidate]
    materialized = materialize_ranker_candidates(plan)
    assert len(materialized) == 1
    assert materialized[0].model_family == "lgbm"


# ---------------------------------------------------------------------------
# dispatch uses true ranker adapters with identical inputs/groups
# ---------------------------------------------------------------------------


def test_fit_ranker_scores_dispatches_to_lgbm() -> None:
    """lgbm model_family calls fit_lgbm_daily_ranker with calibration params."""
    index = _make_index(["2026-01-02", "2026-01-05", "2026-01-08"], ["A", "B", "C", "D"])
    feat = _features(index, n_cols=2)
    ret = _returns(index)
    candidate = RankerGridCandidate(
        RankerFeatureGroup("mv", ("f0", "f1")),
        RankerCalibration(5, 20, 31, 10),
        model_family="lgbm",
    )
    expr_cols = {"f0": "f0", "f1": "f1"}

    with mock.patch(
        "src.research.qlib_execution_common.fit_lgbm_daily_ranker",
        wraps=fit_lgbm_daily_ranker,
    ) as mock_fit, mock.patch(
        "src.research.qlib_execution_common.predict_lgbm_daily_ranker",
        wraps=predict_lgbm_daily_ranker,
    ) as mock_predict:
        scores = fit_ranker_scores(candidate, feat, ret, feat, expr_cols)
        mock_fit.assert_called_once()
        mock_predict.assert_called_once()
        assert scores.columns.tolist() == ["score"]
        assert scores.attrs["model_type"] == "lgbm_lambdarank"


def test_fit_ranker_scores_dispatches_to_xgb() -> None:
    """xgb model_family calls fit_xgb_daily_ranker with params=None."""
    index = _make_index(["2026-01-02", "2026-01-05", "2026-01-08"], ["A", "B", "C", "D"])
    feat = _features(index, n_cols=2)
    ret = _returns(index)
    candidate = RankerGridCandidate(
        RankerFeatureGroup("mv", ("f0", "f1")),
        RankerCalibration(5, 20, 31, 10),
        model_family="xgb",
    )
    expr_cols = {"f0": "f0", "f1": "f1"}

    with mock.patch(
        "src.research.qlib_execution_common.fit_xgb_daily_ranker",
        wraps=fit_xgb_daily_ranker,
    ) as mock_fit, mock.patch(
        "src.research.qlib_execution_common.predict_xgb_daily_ranker",
        wraps=predict_xgb_daily_ranker,
    ) as mock_predict:
        scores = fit_ranker_scores(candidate, feat, ret, feat, expr_cols)
        mock_fit.assert_called_once()
        mock_predict.assert_called_once()
        assert scores.columns.tolist() == ["score"]
        assert scores.attrs["model_type"] == "xgb_rank_ndcg"


def test_lgbm_and_xgb_receive_identical_inputs_and_groups() -> None:
    """Both adapters get the same processed rank target, groups, feature columns,
    n_gain_bins, and num_boost_round."""
    index = _make_index(
        ["2026-01-02", "2026-01-05", "2026-01-08", "2026-01-12"],
        ["A", "B", "C", "D", "E", "F", "G", "H"],
    )
    feat = _features(index, n_cols=2)
    ret = _returns(index)
    expr_cols = {"f0": "f0", "f1": "f1"}

    lgbm_calls: list[dict] = []
    xgb_calls: list[dict] = []

    def _capture_lgbm(features, rank_target, groups, *, n_gain_bins, params, num_boost_round):
        lgbm_calls.append({
            "n_rows": len(features),
            "n_cols": features.shape[1],
            "groups": list(groups),
            "n_gain_bins": n_gain_bins,
            "num_boost_round": num_boost_round,
        })
        return DailyRankerResult(model=None, feature_names=[], groups=list(groups), n_gain_bins=n_gain_bins)

    def _capture_xgb(features, rank_target, groups, *, n_gain_bins, params, num_boost_round):
        xgb_calls.append({
            "n_rows": len(features),
            "n_cols": features.shape[1],
            "groups": list(groups),
            "n_gain_bins": n_gain_bins,
            "num_boost_round": num_boost_round,
        })
        return DailyRankerResult(model=None, feature_names=[], groups=list(groups), n_gain_bins=n_gain_bins)

    lgbm_candidate = RankerGridCandidate(
        RankerFeatureGroup("mv", ("f0", "f1")),
        RankerCalibration(5, 100, 31, 10),
        model_family="lgbm",
    )
    xgb_candidate = RankerGridCandidate(
        RankerFeatureGroup("mv", ("f0", "f1")),
        RankerCalibration(5, 100, 31, 10),
        model_family="xgb",
    )

    with mock.patch(
        "src.research.qlib_execution_common.fit_lgbm_daily_ranker",
        side_effect=_capture_lgbm,
    ), mock.patch(
        "src.research.qlib_execution_common.predict_lgbm_daily_ranker",
        return_value=pd.DataFrame({"score": [0.5] * len(index)}, index=index),
    ), mock.patch(
        "src.research.qlib_execution_common.fit_xgb_daily_ranker",
        side_effect=_capture_xgb,
    ), mock.patch(
        "src.research.qlib_execution_common.predict_xgb_daily_ranker",
        return_value=pd.DataFrame({"score": [0.5] * len(index)}, index=index),
    ):
        fit_ranker_scores(lgbm_candidate, feat, ret, feat, expr_cols)
        fit_ranker_scores(xgb_candidate, feat, ret, feat, expr_cols)

    assert len(lgbm_calls) == 1
    assert len(xgb_calls) == 1

    # Same processed daily rank target / groups / feature columns
    assert lgbm_calls[0]["n_rows"] == xgb_calls[0]["n_rows"]
    assert lgbm_calls[0]["n_cols"] == xgb_calls[0]["n_cols"]
    assert lgbm_calls[0]["groups"] == xgb_calls[0]["groups"]

    # Same n_gain_bins and num_boost_round
    assert lgbm_calls[0]["n_gain_bins"] == xgb_calls[0]["n_gain_bins"] == 5
    assert lgbm_calls[0]["num_boost_round"] == xgb_calls[0]["num_boost_round"] == 100


def test_xgb_dispatch_passes_params_none() -> None:
    """XGB fitting must NOT translate LightGBM-specific params."""
    index = _make_index(["2026-01-02", "2026-01-05"], ["A", "B", "C", "D"])
    feat = _features(index, n_cols=2)
    ret = _returns(index)
    candidate = RankerGridCandidate(
        RankerFeatureGroup("mv", ("f0", "f1")),
        RankerCalibration(5, 20, 31, 10),
        model_family="xgb",
    )
    expr_cols = {"f0": "f0", "f1": "f1"}

    with mock.patch(
        "src.research.qlib_execution_common.fit_xgb_daily_ranker",
        wraps=fit_xgb_daily_ranker,
    ) as mock_fit:
        fit_ranker_scores(candidate, feat, ret, feat, expr_cols)
        _, kwargs = mock_fit.call_args
        assert kwargs["params"] is None


# ---------------------------------------------------------------------------
# VALID_MODEL_FAMILIES is the allowlist
# ---------------------------------------------------------------------------


def test_valid_model_families_is_lgbm_xgb() -> None:
    """Only 'lgbm' and 'xgb' are allowed model families."""
    assert VALID_MODEL_FAMILIES == ("lgbm", "xgb")
