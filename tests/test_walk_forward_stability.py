from __future__ import annotations

import pandas as pd

from src.research.walk_forward_stability import slice_multiindex_dates, summarize_walk_forward_reports


def _candidate(
    name: str,
    *,
    icir: float,
    rank_ic: float,
    spread: float,
    drawdown: float,
    ready: bool = False,
) -> dict[str, object]:
    return {
        "candidate_name": name,
        "candidate_kind": "factor_baseline" if name.startswith("factor:") else "lgbm_lambdarank",
        "orientation": "original",
        "icir": icir,
        "rank_ic": rank_ic,
        "positive_ic_ratio": 0.60 if icir > 0 else 0.40,
        "sharpe": 1.0 if icir > 0 else -0.2,
        "max_drawdown": drawdown,
        "score_direction": {
            "top_minus_bottom_spread": spread,
            "recommendation": "keep_score" if ready else "hold_for_research",
        },
    }


def _report(*candidates: dict[str, object]) -> dict[str, object]:
    return {"comparison_report": {"candidates": list(candidates)}}


def test_slice_multiindex_dates_preserves_attrs() -> None:
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]), ["A", "B"]],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"value": range(len(index))}, index=index)
    frame.attrs["provenance"] = "raw_forward_return"

    sliced = slice_multiindex_dates(frame, "2025-01-02", "2025-01-03")

    assert sliced.index.get_level_values("datetime").min() == pd.Timestamp("2025-01-02")
    assert sliced.index.get_level_values("datetime").max() == pd.Timestamp("2025-01-03")
    assert sliced.attrs["provenance"] == "raw_forward_return"


def test_walk_forward_summary_rejects_single_window_promotion_as_unstable() -> None:
    summary = summarize_walk_forward_reports(
        [
            _report(
                _candidate(
                    "factor:historical_momentum_10d",
                    icir=0.45,
                    rank_ic=0.08,
                    spread=0.02,
                    drawdown=-0.10,
                    ready=True,
                )
            )
        ],
        min_windows=3,
    )

    row = summary["candidates"][0]
    assert row["candidate"] == "factor:historical_momentum_10d/factor_baseline/original"
    assert row["n_windows"] == 1
    assert row["ready_ratio"] == 1.0
    assert row["stable_research_candidate"] is False
    assert summary["best_candidate"] is None


def test_walk_forward_summary_promotes_only_stable_research_candidates() -> None:
    summary = summarize_walk_forward_reports(
        [
            _report(
                _candidate("lgbm:daily_ranker", icir=0.12, rank_ic=0.03, spread=0.010, drawdown=-0.12),
                _candidate("factor:historical_momentum_10d", icir=0.40, rank_ic=0.08, spread=0.020, drawdown=-0.10),
            ),
            _report(
                _candidate("lgbm:daily_ranker", icir=0.08, rank_ic=0.02, spread=0.007, drawdown=-0.15),
                _candidate("factor:historical_momentum_10d", icir=-0.20, rank_ic=-0.04, spread=-0.010, drawdown=-0.28),
            ),
            _report(
                _candidate("lgbm:daily_ranker", icir=0.10, rank_ic=0.025, spread=0.009, drawdown=-0.14),
                _candidate("factor:historical_momentum_10d", icir=0.35, rank_ic=0.07, spread=0.018, drawdown=-0.11),
            ),
        ],
        min_windows=3,
    )

    rows = {row["candidate"]: row for row in summary["candidates"]}
    ranker = rows["lgbm:daily_ranker/lgbm_lambdarank/original"]
    momentum = rows["factor:historical_momentum_10d/factor_baseline/original"]

    assert ranker["n_windows"] == 3
    assert ranker["positive_icir_ratio"] == 1.0
    assert ranker["positive_rank_ic_ratio"] == 1.0
    assert ranker["positive_spread_ratio"] == 1.0
    assert ranker["worst_drawdown"] >= -0.20
    assert ranker["stable_research_candidate"] is True

    assert momentum["positive_icir_ratio"] < 1.0
    assert momentum["worst_drawdown"] < -0.20
    assert momentum["stable_research_candidate"] is False
    assert summary["best_candidate"] == "lgbm:daily_ranker/lgbm_lambdarank/original"


def test_walk_forward_summary_requires_rank_ic_positive_in_most_windows() -> None:
    summary = summarize_walk_forward_reports(
        [
            _report(_candidate("lgbm:daily_ranker", icir=0.20, rank_ic=-0.01, spread=0.01, drawdown=-0.10)),
            _report(_candidate("lgbm:daily_ranker", icir=0.20, rank_ic=-0.01, spread=0.01, drawdown=-0.10)),
            _report(_candidate("lgbm:daily_ranker", icir=0.20, rank_ic=0.10, spread=0.01, drawdown=-0.10)),
        ],
        min_windows=3,
    )

    row = summary["candidates"][0]
    assert row["mean_rank_ic"] > 0.0
    assert row["positive_rank_ic_ratio"] == 1 / 3
    assert row["stable_research_candidate"] is False
    assert summary["best_candidate"] is None
