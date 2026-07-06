"""Walk-forward stability summaries for fixed-ten-day candidates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.research.ten_day_model_gates import evaluate_model_gates


@dataclass(frozen=True)
class WalkForwardWindow:
    """Date boundaries for one train/test research window."""

    train_start: str
    train_end: str
    test_start: str
    test_end: str
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label or f"{self.train_start}_{self.train_end}__{self.test_start}_{self.test_end}",
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
        }


def slice_multiindex_dates(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Slice a (datetime, instrument)-indexed frame by inclusive date bounds."""

    if "datetime" not in frame.index.names:
        raise ValueError("frame index must include a datetime level")
    dates = frame.index.get_level_values("datetime")
    mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    result = frame.loc[mask].copy()
    result.attrs.update(frame.attrs)
    return result


def _candidate_label(candidate: dict[str, Any]) -> str:
    name = candidate.get("candidate_name") or candidate.get("candidate_kind") or "unknown"
    kind = candidate.get("candidate_kind") or "unknown"
    orientation = candidate.get("orientation") or "unknown"
    return f"{name}/{kind}/{orientation}"


def summarize_walk_forward_reports(
    reports: list[dict[str, Any]],
    *,
    min_windows: int = 3,
) -> dict[str, Any]:
    """Aggregate candidate stability across multiple 10D comparison reports.

    Each item may be either a full run_10d_experiment payload or a bare
    comparison_report. The summary is intentionally conservative: a candidate is
    considered stable only if it appears in enough windows, has positive mean
    signal, positive spread in most windows, and never breaches the drawdown
    floor too badly.
    """

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report_index, payload in enumerate(reports):
        report = payload.get("comparison_report", payload)
        for candidate in report.get("candidates", []):
            row = dict(candidate)
            row["window_index"] = report_index
            grouped[_candidate_label(candidate)].append(row)

    rows: list[dict[str, Any]] = []
    for label, candidates in grouped.items():
        icirs = [float(item.get("icir", 0.0)) for item in candidates]
        rank_ics = [float(item.get("rank_ic", 0.0)) for item in candidates]
        drawdowns = [float(item.get("max_drawdown", 0.0)) for item in candidates]
        spreads = [
            float((item.get("score_direction") or {}).get("top_minus_bottom_spread", 0.0))
            for item in candidates
        ]
        gate_rows = [evaluate_model_gates(item) for item in candidates]
        n_windows = len(candidates)
        positive_spread_ratio = sum(1 for value in spreads if value > 0.0) / n_windows if n_windows else 0.0
        positive_icir_ratio = sum(1 for value in icirs if value > 0.0) / n_windows if n_windows else 0.0
        positive_rank_ic_ratio = sum(1 for value in rank_ics if value > 0.0) / n_windows if n_windows else 0.0
        ready_ratio = (
            sum(1 for gate in gate_rows if gate["ready_for_trade_guidance"]) / n_windows if n_windows else 0.0
        )
        mean_icir = sum(icirs) / n_windows if n_windows else 0.0
        mean_rank_ic = sum(rank_ics) / n_windows if n_windows else 0.0
        mean_spread = sum(spreads) / n_windows if n_windows else 0.0
        worst_drawdown = min(drawdowns) if drawdowns else 0.0
        stable = (
            n_windows >= min_windows
            and mean_icir > 0.0
            and mean_rank_ic > 0.0
            and positive_spread_ratio >= 0.60
            and positive_icir_ratio >= 0.60
            and positive_rank_ic_ratio >= 0.60
            and worst_drawdown >= -0.20
        )
        rows.append(
            {
                "candidate": label,
                "n_windows": n_windows,
                "mean_icir": mean_icir,
                "mean_rank_ic": mean_rank_ic,
                "mean_spread": mean_spread,
                "positive_icir_ratio": positive_icir_ratio,
                "positive_rank_ic_ratio": positive_rank_ic_ratio,
                "positive_spread_ratio": positive_spread_ratio,
                "worst_drawdown": worst_drawdown,
                "ready_ratio": ready_ratio,
                "stable_research_candidate": stable,
            }
        )

    rows.sort(
        key=lambda row: (
            bool(row["stable_research_candidate"]),
            float(row["mean_icir"]),
            float(row["positive_spread_ratio"]),
            float(row["worst_drawdown"]),
        ),
        reverse=True,
    )
    stable_rows = [row for row in rows if row["stable_research_candidate"]]
    return {
        "schema_version": "1.0",
        "min_windows": min_windows,
        "n_reports": len(reports),
        "n_candidates": len(rows),
        "candidates": rows,
        "best_candidate": stable_rows[0]["candidate"] if stable_rows else None,
    }
