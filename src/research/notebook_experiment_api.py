"""Notebook-callable fixed-10D experiment API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.research.notebook_lab_contracts import ResearchSessionConfig
from src.research.signal_discovery import (
    CandidateKind,
    CandidateStatus,
    ComparisonReport,
    PROMOTION_THRESHOLDS,
    ScoreOrientation,
    evaluate_candidate,
)


def _as_score_frame(series_or_frame: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if isinstance(series_or_frame, pd.Series):
        frame = series_or_frame.to_frame("score")
    else:
        frame = series_or_frame.copy()
    if list(frame.columns) != ["score"]:
        if len(frame.columns) != 1:
            raise ValueError("candidate input must have exactly one score column")
        frame.columns = ["score"]
    return frame


def compare_10d_candidates(
    candidates: dict[str, pd.Series | pd.DataFrame],
    raw_returns: pd.DataFrame,
    *,
    config: ResearchSessionConfig,
    benchmark_returns: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compare notebook candidate score series with original/inverted orientation."""

    results = []
    for name, values in candidates.items():
        frame = _as_score_frame(values)
        kind = CandidateKind.FACTOR_BASELINE if name.startswith("factor:") else CandidateKind.LGBM_REGRESSOR
        for orientation in (ScoreOrientation.ORIGINAL, ScoreOrientation.INVERTED):
            result = evaluate_candidate(
                frame,
                raw_returns,
                candidate_kind=kind,
                orientation=orientation,
                benchmark_returns=benchmark_returns,
                topk=config.topk,
                rebalance_days=config.rebalance_days,
            )
            result.strength_rationale = f"{name}: {result.strength_rationale}"
            results.append(result)

    report = ComparisonReport(
        market=config.market,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        label_horizon=10,
        rebalance_days=config.rebalance_days,
        candidates=results,
    )
    for candidate in results:
        label = f"{candidate.candidate_kind.value}/{candidate.orientation.value}"
        if candidate.status == CandidateStatus.PROMOTED:
            report.promoted.append(label)
        else:
            report.research_only.append(label)
    eligible = [candidate for candidate in results if candidate.n_periods > 0]
    if eligible:
        best = max(eligible, key=lambda candidate: (candidate.icir, candidate.rank_ic, candidate.excess_return))
        report.summary = {
            "n_candidates": len(results),
            "n_promoted": len(report.promoted),
            "n_research_only": len(report.research_only),
            "best_candidate": f"{best.candidate_kind.value}/{best.orientation.value}",
            "best_icir": best.icir,
            "best_candidate_summary": {
                "rank_ic": best.rank_ic,
                "direction": best.score_direction.recommendation,
                "strength": best.strength_rationale,
                "weakness": best.weakness_rationale,
            },
            "promotion_thresholds": PROMOTION_THRESHOLDS,
        }
    else:
        report.summary = {"n_candidates": len(results), "n_promoted": 0, "n_research_only": len(results)}
    return report.to_dict()


def run_10d_experiment(
    *,
    config: ResearchSessionConfig,
    candidates: dict[str, pd.Series | pd.DataFrame],
    raw_returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run one fixed-10D notebook experiment and optionally write a JSON artifact."""

    report = compare_10d_candidates(
        candidates,
        raw_returns,
        config=config,
        benchmark_returns=benchmark_returns,
    )
    payload = {"schema_version": "1.0", "config": config.to_dict(), "comparison_report": report}
    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = config.experiment_id or f"{config.market}_10d_experiment"
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        payload["artifact_path"] = str(path)
    return payload
