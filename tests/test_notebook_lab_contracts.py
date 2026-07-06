from __future__ import annotations

import json
from pathlib import Path

import nbformat

import numpy as np
import pandas as pd

from src.research.daily_ranker import make_daily_rank_groups, make_daily_rank_target
from src.research.daily_ranker_model import (
    DailyRankerResult,
    fit_lgbm_daily_ranker,
    percentile_rank_to_gain,
    predict_lgbm_daily_ranker,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig
from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_research_api import sanitize_factor_name
from src.research.risk_controlled_momentum import (
    build_risk_controlled_momentum_grid,
    build_volatility_adjusted_momentum,
)
from src.research.ten_day_model_gates import evaluate_model_gates


def test_research_session_config_defaults_to_fixed_10d() -> None:
    cfg = ResearchSessionConfig(
        market="us",
        symbols=[f"S{i}" for i in range(20)],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-05",
    )
    assert cfg.holding_days == 10
    assert cfg.rebalance_days == 10
    assert cfg.topk == 15
    assert cfg.model_type == "lgbm_regressor"


def test_sanitize_factor_name_matches_training_notebook_convention() -> None:
    assert sanitize_factor_name("close/Ref(close,10)-1") == "close_d_Ref_close_10-1"


def test_model_gate_blocks_low_icir_and_large_drawdown() -> None:
    gate = evaluate_model_gates(
        {
            "icir": 0.12,
            "rank_ic": 0.03,
            "positive_ic_ratio": 0.60,
            "sharpe": 1.2,
            "max_drawdown": -0.30,
            "score_direction": {
                "top_minus_bottom_spread": 0.01,
                "recommendation": "keep_score",
            },
        }
    )
    assert gate["ready_for_trade_guidance"] is False
    assert gate["failed_gates"] == ["icir", "drawdown"]


def test_volatility_adjusted_momentum_marks_high_risk_score_missing() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01"]), ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    momentum = pd.DataFrame({"value": [0.04, 0.03, 0.02, 0.01]}, index=index)
    volatility = pd.DataFrame({"value": [0.10, 0.20, 0.30, 10.00]}, index=index)

    scores = build_volatility_adjusted_momentum(momentum, volatility, max_volatility_quantile=0.75)

    assert list(scores.columns) == ["score"]
    assert pd.isna(scores.loc[(pd.Timestamp("2025-01-01"), "D"), "score"])
    assert scores.attrs["provenance"] == "risk_controlled_momentum_score"


def test_risk_controlled_momentum_grid_builds_named_candidates() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01"]), ["A", "B", "C", "D"]],
        names=["datetime", "instrument"],
    )
    momentum = pd.DataFrame({"value": [0.04, 0.03, 0.02, 0.01]}, index=index)
    volatility = pd.DataFrame({"value": [0.10, 0.20, 0.30, 10.00]}, index=index)

    grid = build_risk_controlled_momentum_grid(momentum, volatility, volatility_quantiles=(0.5, 0.75))

    assert list(grid) == [
        "factor:risk_controlled_momentum_volq50",
        "factor:risk_controlled_momentum_volq75",
    ]
    assert all(list(frame.columns) == ["score"] for frame in grid.values())


def test_daily_ranker_builds_same_date_percentile_targets_and_groups() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    raw_returns = pd.DataFrame({"return": [0.1, 0.2, 0.3, -0.2, 0.0, 0.2]}, index=index)
    raw_returns.attrs["provenance"] = "raw_forward_return"
    raw_returns.attrs["horizon"] = 10

    rank_target = make_daily_rank_target(raw_returns)

    assert rank_target.attrs["provenance"] == "processed_daily_rank_target"
    assert rank_target.attrs["source"] == "raw_forward_return"
    assert rank_target.attrs["horizon"] == 10
    assert rank_target.loc[(pd.Timestamp("2025-01-01"), "C")] == 1.0
    assert make_daily_rank_groups(index) == [3, 3]


def test_percentile_rank_to_gain_builds_integer_ranker_labels() -> None:
    target = pd.Series([0.0, 0.2, 0.5, 0.99, 1.0], name="rank_target")
    target.attrs["provenance"] = "processed_daily_rank_target"

    gains = percentile_rank_to_gain(target, n_bins=5)

    assert gains.tolist() == [0, 1, 2, 4, 4]
    assert gains.attrs["provenance"] == "processed_daily_rank_gain_target"
    assert gains.attrs["source"] == "processed_daily_rank_target"
    assert gains.attrs["n_bins"] == 5


def test_canonical_return_expression_is_forward_looking() -> None:
    """The canonical 10D return expression must be forward-looking Ref($close, -10)."""
    assert CANONICAL_10D_RETURN_EXPR == "Ref($close, -10) / $close - 1"
    assert "Ref" in CANONICAL_10D_RETURN_EXPR
    assert "-10" in CANONICAL_10D_RETURN_EXPR


def test_notebook_07_contracts_evident_in_json_source() -> None:
    """Notebook 07 source must satisfy the 10D lab contract: provenance, horizon,
    expression, training-only ranker frame, test-only predict, raw returns used in
    experiment, and exact candidate names/output dir."""
    nb_path = Path(__file__).parent.parent / "notebooks" / "07_true_daily_ranker_lab.ipynb"
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    source = "\n".join("".join(c["source"]) for c in code_cells)

    # Sets provenance, horizon, expression from config
    assert 'attrs["provenance"] = "raw_forward_return"' in source
    assert 'attrs["horizon"] = 10' in source
    assert 'attrs["expression"]' in source

    # Calls prepare_ranker_frame on train-only frames
    assert "prepare_ranker_frame(features_train, returns_train)" in source

    # Predicts on test features
    assert "predict_lgbm_daily_ranker(ranker_result, features_test)" in source

    # Passes test raw returns into run_10d_experiment
    assert "run_10d_experiment" in source
    assert "returns_test" in source

    # Includes both exact candidate names and output dir
    assert "lgbm:daily_ranker" in source
    assert "factor:historical_momentum_10d" in source
    assert "output_dir=ROOT" in source

    # Qlib provider URI is root-anchored for portability (nbconvert cwd ≠ project root)
    assert "provider_uri_default=str(ROOT" in source

    # Notebook enforces at least 2 symbols for cross-sectional ranking
    assert "len(SYMBOLS) >= 2" in source

    # Notebook derives requested_topk from cfg or fallback and validates it's a positive integer
    assert "requested_topk" in source

    # Notebook clamps topk to at most len(SYMBOLS)-1 and passes it explicitly
    assert "topk=TOPK" in source

    # Notebook explicitly passes lgbm_lambdarank model_type (not relying on shared default)
    assert 'model_type="lgbm_lambdarank"' in source

    # ── OOS label-leakage purge contract ──
    # Notebook must purge final config.holding_days training dates before
    # prepare_ranker_frame so Ref($close, -10) labels do not peek into test period.
    assert "common_train_dates" in source, (
        "notebook 07 must compute common_train_dates for embargo purge"
    )
    assert "config.holding_days" in source, (
        "notebook 07 must reference config.holding_days for embargo width"
    )
    assert "purge_dates" in source, (
        "notebook 07 must compute purge_dates from final holding_days training dates"
    )
    assert "all_trading_dates" in source, (
        "notebook 07 must build all_trading_dates for embargo gap verification"
    )
    assert "trading_date_gap" in source, (
        "notebook 07 must compute trading_date_gap between latest training and first test date"
    )
    assert "purge_boundary not in purge_dates" in source, (
        "notebook 07 must assert purge boundary is not in purge set"
    )

    # prepare_ranker_frame must still be called on (purged) features_train, returns_train
    assert "prepare_ranker_frame(features_train, returns_train)" in source, (
        "prepare_ranker_frame must receive purged features_train and returns_train"
    )

    # After prepare_ranker_frame, notebook must directly assert X_rank/y_rank
    # datetime levels are disjoint from purge_dates (not just purge_boundary)
    assert ".isdisjoint(purge_dates)" in source, (
        "notebook 07 must directly assert X_rank/y_rank datetime levels exclude purged dates"
    )


def test_fit_lgbm_daily_ranker_trains_true_lambdarank() -> None:
    """fit_lgbm_daily_ranker must produce a DailyRankerResult with LambdaRank objective."""

    n_per_date = 5
    n_dates = 4
    dates = pd.to_datetime(["2025-01-0%d" % (d + 1) for d in range(n_dates)])
    index = pd.MultiIndex.from_product([dates, [f"S{i}" for i in range(n_per_date)]], names=["datetime", "instrument"])
    index = index.sort_values()

    np.random.seed(42)
    features = pd.DataFrame(
        {f"f{i}": np.random.randn(n_per_date * n_dates) for i in range(3)},
        index=index,
    )
    rank_target = pd.Series(np.random.rand(n_per_date * n_dates), index=index, name="rank_target")
    rank_target.attrs["provenance"] = "processed_daily_rank_target"
    groups = [n_per_date] * n_dates

    result = fit_lgbm_daily_ranker(features, rank_target, groups, n_gain_bins=5, num_boost_round=10)

    assert isinstance(result, DailyRankerResult)
    assert result.model is not None
    assert result.n_gain_bins == 5
    assert result.feature_names == ["f0", "f1", "f2"]
    assert result.groups == groups
    assert result.model.params["objective"] == "lambdarank"


def test_predict_lgbm_daily_ranker_produces_oos_scores() -> None:
    """predict_lgbm_daily_ranker must return a single-column 'score' frame with provenance."""

    n_per_date = 5
    n_dates = 3
    dates = pd.to_datetime(["2025-01-0%d" % (d + 1) for d in range(n_dates)])
    index = pd.MultiIndex.from_product([dates, [f"S{i}" for i in range(n_per_date)]], names=["datetime", "instrument"])
    index = index.sort_values()

    np.random.seed(42)
    features = pd.DataFrame({"f0": np.random.randn(n_per_date * n_dates)}, index=index)
    rank_target = pd.Series(np.random.rand(n_per_date * n_dates), index=index, name="rank_target")
    rank_target.attrs["provenance"] = "processed_daily_rank_target"
    groups = [n_per_date] * n_dates

    result = fit_lgbm_daily_ranker(features, rank_target, groups, n_gain_bins=5, num_boost_round=10)
    scores = predict_lgbm_daily_ranker(result, features)

    assert list(scores.columns) == ["score"]
    assert len(scores) == n_per_date * n_dates
    assert scores.attrs["provenance"] == "out_of_sample_daily_ranker_prediction"
    assert scores.attrs["model_type"] == "lgbm_lambdarank"
    assert scores.attrs["n_gain_bins"] == 5


def test_notebook_07_candidate_names_include_lgbm_daily_ranker_and_baseline() -> None:
    """Notebook 07 candidates: lgbm:daily_ranker→lgbm_lambdarank, factor:*→factor_baseline."""
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    raw = pd.DataFrame({"return": [0.01] * 6}, index=index)
    raw.attrs["provenance"] = "raw_forward_return"
    raw.attrs["horizon"] = 10
    raw.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    ranker = pd.DataFrame({"score": [0.1] * 6}, index=index)
    ranker.attrs["provenance"] = "out_of_sample_daily_ranker_prediction"
    baseline = pd.DataFrame({"score": [0.05] * 6}, index=index)
    baseline.attrs["provenance"] = "factor_baseline"

    config = ResearchSessionConfig(
        market="us",
        symbols=["A", "B", "C"],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-02",
        experiment_id="us_true_daily_ranker_lab",
        topk=2,
    )

    experiment = run_10d_experiment(
        config=config,
        candidates={
            "lgbm:daily_ranker": ranker,
            "factor:historical_momentum_10d": baseline,
        },
        raw_returns=raw,
    )

    candidates = experiment["comparison_report"]["candidates"]
    candidate_kinds = {c["candidate_kind"] for c in candidates}
    assert "lgbm_lambdarank" in candidate_kinds, "lgbm:daily_ranker must map to lgbm_lambdarank kind"
    assert "factor_baseline" in candidate_kinds, "factor:historical_momentum_10d must map to factor_baseline kind"

    # Exact candidate_name must be populated from dict keys (both orientations)
    candidate_names = {c["candidate_name"] for c in candidates}
    assert "lgbm:daily_ranker" in candidate_names, (
        "lgbm:daily_ranker must appear via candidate_name field"
    )
    assert "factor:historical_momentum_10d" in candidate_names, (
        "factor:historical_momentum_10d must appear via candidate_name field"
    )

    # Backward compat: name also embedded in strength_rationale
    rationales = [c["strength_rationale"] for c in candidates]
    assert any("lgbm:daily_ranker:" in r for r in rationales), (
        "exact candidate name lgbm:daily_ranker must appear in report via strength_rationale"
    )
    assert any("factor:historical_momentum_10d:" in r for r in rationales), (
        "exact candidate name factor:historical_momentum_10d must appear in report via strength_rationale"
    )
    assert experiment["comparison_report"]["summary"]["n_candidates"] >= 2


def test_lgbm_daily_ranker_and_regressor_map_to_distinct_kinds() -> None:
    """lgbm:daily_ranker maps to lgbm_lambdarank, lgbm:regressor maps to lgbm_regressor."""
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    raw = pd.DataFrame({"return": [0.01] * 6}, index=index)
    raw.attrs["provenance"] = "raw_forward_return"
    raw.attrs["horizon"] = 10
    raw.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    score = pd.DataFrame({"score": [0.1] * 6}, index=index)

    config = ResearchSessionConfig(
        market="us",
        symbols=["A", "B", "C"],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-02",
        topk=2,
    )

    experiment = run_10d_experiment(
        config=config,
        candidates={
            "lgbm:daily_ranker": score,
            "lgbm:regressor": score,
        },
        raw_returns=raw,
    )

    candidate_kinds = {
        c["candidate_name"]: c["candidate_kind"]
        for c in experiment["comparison_report"]["candidates"]
    }
    assert candidate_kinds.get("lgbm:daily_ranker") == "lgbm_lambdarank", (
        f"lgbm:daily_ranker must map to lgbm_lambdarank, got {candidate_kinds.get('lgbm:daily_ranker')}"
    )
    assert candidate_kinds.get("lgbm:regressor") == "lgbm_regressor", (
        f"lgbm:regressor must map to lgbm_regressor, got {candidate_kinds.get('lgbm:regressor')}"
    )


def test_run_10d_experiment_output_dir_writes_evidence_json() -> None:
    """run_10d_experiment with output_dir must write evidence JSON under the output path."""
    import tempfile

    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    raw = pd.DataFrame({"return": [0.01] * 6}, index=index)
    raw.attrs["provenance"] = "raw_forward_return"
    raw.attrs["horizon"] = 10
    raw.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    ranker = pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}, index=index)
    ranker.attrs["provenance"] = "out_of_sample_daily_ranker_prediction"

    config = ResearchSessionConfig(
        market="us",
        symbols=["A", "B", "C"],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-02",
        experiment_id="us_test_output_dir",
        topk=2,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "notebook_10d_lab"
        experiment = run_10d_experiment(
            config=config,
            candidates={"lgbm:daily_ranker": ranker},
            raw_returns=raw,
            output_dir=output_dir,
        )

        assert "artifact_path" in experiment
        artifact = Path(experiment["artifact_path"])
        assert artifact.exists()
        assert artifact.suffix == ".json"
        content = json.loads(artifact.read_text(encoding="utf-8"))
        assert content["schema_version"] == "1.0"
        assert "comparison_report" in content


def test_notebook_07_passes_nbformat_validation() -> None:
    """Notebook 07 must be valid nbformat v4 — all code cells have outputs, execution_count, etc."""
    nb_path = Path(__file__).parent.parent / "notebooks" / "07_true_daily_ranker_lab.ipynb"
    nb = nbformat.read(nb_path, as_version=4)
    # Raises NotebookValidationError on any schema violation
    nbformat.validate(nb)


def test_ci_workflow_includes_notebook_07_execution() -> None:
    """The online-validation CI workflow must run notebook 07 alongside 00/01/end_to_end/06."""
    ci_path = Path(__file__).parent.parent / ".github" / "workflows" / "online-validation.yml"
    source = ci_path.read_text(encoding="utf-8")

    # Existing entries must remain
    assert "notebooks/00_data_download_and_sync.ipynb" in source
    assert "notebooks/01_factor_research.ipynb" in source
    assert "notebooks/end_to_end_training_pipeline.ipynb" in source
    assert "notebooks/06_risk_controlled_momentum_grid.ipynb" in source

    # Notebook 07 execution must be present
    assert "07_true_daily_ranker_lab" in source
