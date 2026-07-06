from __future__ import annotations

import pandas as pd

from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR, ResearchSessionConfig


def test_ranker_grid_candidate_names_map_to_lambdarank_kind() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02"]), ["A", "B", "C"]],
        names=["datetime", "instrument"],
    )
    raw = pd.DataFrame({"return": [0.01, 0.02, 0.03, -0.01, 0.01, 0.04]}, index=index)
    raw.attrs["provenance"] = "raw_forward_return"
    raw.attrs["horizon"] = 10
    raw.attrs["expression"] = CANONICAL_10D_RETURN_EXPR
    score = pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.0, 0.1, 0.4]}, index=index)

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
    payload = run_10d_experiment(
        config=config,
        candidates={"lgbm:daily_ranker:momentum:gain5_round100_leaves31_leaf10_lr0.05": score},
        raw_returns=raw,
    )

    kinds = {candidate["candidate_kind"] for candidate in payload["comparison_report"]["candidates"]}
    names = {candidate["candidate_name"] for candidate in payload["comparison_report"]["candidates"]}
    assert kinds == {"lgbm_lambdarank"}
    assert names == {"lgbm:daily_ranker:momentum:gain5_round100_leaves31_leaf10_lr0.05"}
