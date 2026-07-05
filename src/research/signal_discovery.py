"""Fixed-10-trading-day signal discovery comparison report workflow.

Evaluates candidate models/factors against raw future 10D returns with
deterministic score-direction diagnostics and bucket-return analysis.
Produces a canonical comparison report at
``artifacts/evidence/10d_signal_discovery/{market}_signal_discovery_report.json``.

Research-candidate status is always separated from promoted-candidate status:
the report truthfully reports when no candidate qualifies for promotion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CandidateKind(str, Enum):
    """Kinds of candidates that can be evaluated in a 10D signal discovery run."""

    LGBM_REGRESSOR = "lgbm_regressor"
    RANK_TRANSFORM = "rank_transform"
    FACTOR_BASELINE = "factor_baseline"
    # Retained for winner-label training-target utility; never used as a
    # candidate score in ``run_signal_discovery_comparison``.
    WINNER_BUCKET_CLASSIFIER = "winner_bucket_classifier"


class ScoreOrientation(str, Enum):
    """How model scores map to expected returns."""

    ORIGINAL = "original"
    INVERTED = "inverted"


class CandidateStatus(str, Enum):
    """Research candidate status — separate from promotion eligibility."""

    RESEARCH = "research_candidate"
    PROMOTED = "promoted_candidate"
    REJECTED = "rejected"


class DirectionRecommendation(str, Enum):
    """Deterministic score-direction recommendation."""

    KEEP = "keep_score"
    INVERT = "invert_score"
    NO_SIGNAL = "no_signal"
    INCONCLUSIVE = "inconclusive"


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

REQUIRED_REPORT_METRICS: tuple[str, ...] = (
    "ic",
    "rank_ic",
    "icir",
    "positive_ic_ratio",
    "top_bucket_return",
    "bottom_bucket_return",
    "top_minus_bottom_spread",
    "total_return",
    "benchmark_return",
    "excess_return",
    "sharpe",
    "max_drawdown",
    "turnover",
    "costs",
    "score_direction",
)

PROMOTION_THRESHOLDS: dict[str, float] = {
    "min_icir": 0.3,
    "min_rank_ic": 0.02,
    "min_positive_ic_ratio": 0.55,
    "min_top_minus_bottom": 0.0,
    "min_sharpe": 0.0,
    "max_drawdown": -0.15,
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DirectionDiagnostics:
    """Score-direction diagnostics for one candidate × orientation."""

    top_bucket_return: float = 0.0
    bottom_bucket_return: float = 0.0
    top_minus_bottom_spread: float = 0.0
    bottom_minus_top_spread: float = 0.0
    rank_ic: float = 0.0
    recommendation: str = "inconclusive"
    n_samples: int = 0
    n_dates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_bucket_return": round(self.top_bucket_return, 8),
            "bottom_bucket_return": round(self.bottom_bucket_return, 8),
            "top_minus_bottom_spread": round(self.top_minus_bottom_spread, 8),
            "bottom_minus_top_spread": round(self.bottom_minus_top_spread, 8),
            "rank_ic": round(self.rank_ic, 6),
            "recommendation": self.recommendation,
            "n_samples": self.n_samples,
            "n_dates": self.n_dates,
        }


@dataclass
class CandidateResult:
    """Evaluation result for one candidate kind × orientation."""

    candidate_kind: CandidateKind
    orientation: ScoreOrientation
    ic: float = 0.0
    rank_ic: float = 0.0
    icir: float = 0.0
    positive_ic_ratio: float = 0.0
    total_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    annualized_return: float = 0.0
    volatility: float = 0.0
    turnover: float = 0.0
    costs: float = 0.0
    score_direction: DirectionDiagnostics = field(default_factory=DirectionDiagnostics)
    n_periods: int = 0
    test_start: str = ""
    test_end: str = ""
    status: CandidateStatus = CandidateStatus.RESEARCH
    promotion_blockers: list[str] = field(default_factory=list)
    # Top selected stocks on the last evaluation date
    top_selected_stocks: list[str] = field(default_factory=list)
    # Concise rationale
    strength_rationale: str = ""
    weakness_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_kind": self.candidate_kind.value,
            "orientation": self.orientation.value,
            "ic": round(self.ic, 6),
            "rank_ic": round(self.rank_ic, 6),
            "icir": round(self.icir, 6),
            "positive_ic_ratio": round(self.positive_ic_ratio, 6),
            "total_return": round(self.total_return, 6),
            "benchmark_return": round(self.benchmark_return, 6),
            "excess_return": round(self.excess_return, 6),
            "sharpe": round(self.sharpe, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "annualized_return": round(self.annualized_return, 6),
            "volatility": round(self.volatility, 6),
            "turnover": round(self.turnover, 6),
            "costs": round(self.costs, 8),
            "score_direction": self.score_direction.to_dict(),
            "n_periods": self.n_periods,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "status": self.status.value,
            "promotion_blockers": list(self.promotion_blockers),
            "top_selected_stocks": list(self.top_selected_stocks),
            "strength_rationale": self.strength_rationale,
            "weakness_rationale": self.weakness_rationale,
        }


@dataclass
class ComparisonReport:
    """Fixed-10D signal discovery comparison report.

    The canonical output written to
    ``artifacts/evidence/10d_signal_discovery/{market}_signal_discovery_report.json``.
    """

    market: str
    generated_at: str
    label_horizon: int = 10
    rebalance_days: int = 10
    candidates: list[CandidateResult] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    research_only: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "market": self.market,
            "generated_at": self.generated_at,
            "label_horizon": self.label_horizon,
            "rebalance_days": self.rebalance_days,
            "candidates": [c.to_dict() for c in self.candidates],
            "promoted": list(self.promoted),
            "research_only": list(self.research_only),
            "summary": self.summary,
            "warnings": list(self.warnings),
        }

    def write(self, output_dir: Path) -> Path:
        """Write the report to *output_dir* as ``{market}_signal_discovery_report.json``."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.market}_signal_discovery_report.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return path


# ---------------------------------------------------------------------------
# Winner-bucket label generation for training targets only
# ---------------------------------------------------------------------------


def generate_winner_labels(
    raw_returns: pd.DataFrame,
    *,
    top_fraction: float = 0.20,
    min_stocks_per_day: int = 5,
) -> pd.DataFrame:
    """Generate winner-bucket binary labels from raw forward returns.

    For each trading date, the top *top_fraction* of stocks by raw forward
    return are labeled 1 (winner); all others are labeled 0.

    **Training-target utility only.**  Winner labels must never be fed as
    candidate scores into ``evaluate_candidate`` — that would be same-row
    target leakage because winners are defined by the same returns used for
    evaluation.

    Args:
        raw_returns: DataFrame with ``(datetime, instrument)`` MultiIndex and
            a ``"return"`` column containing raw forward returns.
        top_fraction: Fraction of stocks to label as winners per date.
        min_stocks_per_day: Minimum stocks required on a date for labeling.

    Returns:
        DataFrame with the same MultiIndex, a ``"return"`` column, and a
        ``"winner_label"`` column (0 or 1).
    """
    if top_fraction <= 0 or top_fraction > 1:
        raise ValueError(f"top_fraction must be in (0, 1], got {top_fraction}")

    _validate_raw_return_provenance(raw_returns, require_horizon=True)

    df = raw_returns.copy()
    col_name = "return" if "return" in df.columns else df.columns[0]
    df["winner_label"] = 0

    for date, group in df.groupby(level="datetime"):
        valid = group[group[col_name].notna()]
        if len(valid) < min_stocks_per_day:
            continue
        n_top = max(1, int(np.ceil(len(valid) * top_fraction)))
        # Sort descending by return; ties broken by instrument for determinism
        valid_copy = valid.copy()
        valid_copy["__inst"] = valid_copy.index.get_level_values("instrument")
        selected = valid_copy.sort_values(
            [col_name, "__inst"],
            ascending=[False, True],
            kind="mergesort",
            na_position="last",
        ).head(n_top)
        selected_instruments = set(selected.index.get_level_values("instrument"))
        date_mask = df.index.get_level_values("datetime") == date
        instrument_mask = df.index.get_level_values("instrument").isin(selected_instruments)
        df.loc[date_mask & instrument_mask, "winner_label"] = 1

    return df


# ---------------------------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------------------------


def _validate_raw_return_provenance(
    raw_returns: pd.DataFrame, *, require_horizon: bool = False
) -> None:
    """Validate that *raw_returns* has mandatory provenance attrs.

    Raises ValueError if ``provenance`` is missing or not ``"raw_forward_return"``,
    or if ``require_horizon`` is True and ``horizon`` != 10.
    """
    provenance = raw_returns.attrs.get("provenance", "")
    if not provenance:
        raise ValueError(
            "Raw returns must have provenance='raw_forward_return' attrs. "
            "Got no provenance attrs."
        )
    if provenance != "raw_forward_return":
        raise ValueError(
            f"Expected raw_forward_return provenance, got {provenance!r}. "
            "Economic evaluation requires raw forward returns, not processed labels."
        )
    if require_horizon:
        horizon = raw_returns.attrs.get("horizon")
        if horizon != 10:
            raise ValueError(
                f"Expected horizon=10 in raw returns attrs, got {horizon!r}. "
                "The 10D signal discovery report requires exactly 10-day forward returns."
            )


# ---------------------------------------------------------------------------
# Direction diagnostics
# ---------------------------------------------------------------------------


def compute_direction_diagnostics(
    scores: pd.Series,
    raw_returns: pd.Series,
    *,
    top_fraction: float = 0.10,
    min_stocks_per_day: int = 5,
) -> DirectionDiagnostics:
    """Compute score-direction diagnostics from aligned scores and raw returns.

    Uses per-date cross-sectional decile analysis (not global pooling).

    Args:
        scores: Predicted scores indexed by ``(datetime, instrument)``.
        raw_returns: Raw forward returns indexed by ``(datetime, instrument)``.
        top_fraction: Fraction for top/bottom bucket (default 0.10 = decile).
        min_stocks_per_day: Minimum stocks required for a date to be included.

    Returns:
        ``DirectionDiagnostics`` with all fields populated.
    """
    # Align on common index
    common_idx = scores.index.intersection(raw_returns.index)
    if len(common_idx) == 0:
        return DirectionDiagnostics(recommendation="no_signal")

    s = scores.loc[common_idx]
    r = raw_returns.loc[common_idx]

    df = pd.DataFrame({"score": s.values, "return": r.values}, index=common_idx).dropna()
    if df.empty:
        return DirectionDiagnostics(recommendation="no_signal")

    # Per-date top/bottom bucket analysis
    per_date_tops: list[float] = []
    per_date_bottoms: list[float] = []
    per_date_rank_ics: list[float] = []

    for date, group in df.groupby(level="datetime"):
        if len(group) < min_stocks_per_day:
            continue
        sg = group.sort_values("score", ascending=False)
        n_stocks = len(sg)
        n_bucket = max(1, int(np.ceil(n_stocks * top_fraction)))
        per_date_tops.append(float(sg["return"].iloc[:n_bucket].mean()))
        per_date_bottoms.append(float(sg["return"].iloc[-n_bucket:].mean()))

        # Cross-sectional rank IC for this date
        if n_stocks >= 5:
            rank_s = sg["score"].rank(method="average")
            rank_r = sg["return"].rank(method="average")
            corr = rank_s.corr(rank_r)
            if np.isfinite(corr):
                per_date_rank_ics.append(float(corr))

    n_dates = len(per_date_tops)
    if n_dates == 0:
        return DirectionDiagnostics(recommendation="no_signal")

    top = float(np.mean(per_date_tops))
    bottom = float(np.mean(per_date_bottoms))
    tmb = top - bottom
    bmt = bottom - top
    rank_ic = float(np.mean(per_date_rank_ics)) if per_date_rank_ics else 0.0

    # Deterministic recommendation
    if tmb > 1e-12 and rank_ic > 0:
        rec = DirectionRecommendation.KEEP.value
    elif tmb < -1e-12 and rank_ic < 0:
        rec = DirectionRecommendation.INVERT.value
    elif abs(tmb) < 1e-12:
        rec = DirectionRecommendation.NO_SIGNAL.value
    else:
        rec = DirectionRecommendation.INCONCLUSIVE.value

    return DirectionDiagnostics(
        top_bucket_return=top,
        bottom_bucket_return=bottom,
        top_minus_bottom_spread=tmb,
        bottom_minus_top_spread=bmt,
        rank_ic=rank_ic,
        recommendation=rec,
        n_samples=len(df),
        n_dates=n_dates,
    )


# ---------------------------------------------------------------------------
# Candidate evaluation
# ---------------------------------------------------------------------------


def _compute_candidate_ic_metrics(
    scores: pd.Series,
    returns: pd.Series,
    min_stocks_per_day: int = 5,
) -> tuple[float, float, float, float]:
    """Compute IC, rank IC, ICIR, and positive IC ratio from aligned series.

    Uses per-date cross-sectional computation — never global pooling.
    """
    common_idx = scores.index.intersection(returns.index)
    if len(common_idx) < min_stocks_per_day:
        return 0.0, 0.0, 0.0, 0.0

    s = scores.loc[common_idx]
    r = returns.loc[common_idx]
    df = pd.DataFrame({"score": s.values, "return": r.values}, index=common_idx).dropna()

    daily_ics: list[float] = []
    daily_rank_ics: list[float] = []

    for date, group in df.groupby(level="datetime"):
        if len(group) < min_stocks_per_day:
            continue
        p = group["score"].values
        rt = group["return"].values

        p_std, rt_std = np.std(p), np.std(rt)
        if p_std < 1e-12 or rt_std < 1e-12:
            continue

        pearson = float(np.corrcoef(p, rt)[0, 1])
        if np.isfinite(pearson):
            daily_ics.append(pearson)

        rank_p = pd.Series(p).rank().values
        rank_rt = pd.Series(rt).rank().values
        rank_corr = float(np.corrcoef(rank_p, rank_rt)[0, 1])
        if np.isfinite(rank_corr):
            daily_rank_ics.append(rank_corr)

    if not daily_ics:
        return 0.0, 0.0, 0.0, 0.0

    mean_ic = float(np.mean(daily_ics))
    std_ic = float(np.std(daily_ics, ddof=1)) if len(daily_ics) > 1 else 0.0
    icir = mean_ic / std_ic if std_ic > 1e-12 else 0.0
    mean_rank_ic = float(np.mean(daily_rank_ics)) if daily_rank_ics else 0.0
    positive_ic_ratio = float(np.mean([1.0 if ic > 0 else 0.0 for ic in daily_ics]))

    return mean_ic, mean_rank_ic, icir, positive_ic_ratio


def _build_rationale(
    result: CandidateResult,
    direction: DirectionDiagnostics,
) -> tuple[str, str]:
    """Build concise strength and weakness rationale strings from metrics."""
    strengths: list[str] = []
    weaknesses: list[str] = []

    if result.icir >= 0.5:
        strengths.append(f"strong ICIR ({result.icir:.3f})")
    elif result.icir >= 0.3:
        strengths.append(f"adequate ICIR ({result.icir:.3f})")
    else:
        weaknesses.append(f"low ICIR ({result.icir:.3f})")

    if result.rank_ic >= 0.03:
        strengths.append(f"solid rank IC ({result.rank_ic:.4f})")
    elif result.rank_ic >= 0.02:
        strengths.append(f"marginal rank IC ({result.rank_ic:.4f})")
    else:
        weaknesses.append(f"weak rank IC ({result.rank_ic:.4f})")

    tmb = direction.top_minus_bottom_spread
    if tmb > 0.001:
        strengths.append(f"positive top−bottom spread ({tmb:.4f})")
    elif tmb > 0:
        strengths.append(f"narrow top−bottom spread ({tmb:.4f})")
    else:
        weaknesses.append(f"negative/flat top−bottom spread ({tmb:.4f})")

    rec = direction.recommendation
    if rec == DirectionRecommendation.KEEP.value:
        strengths.append("direction aligned (keep)")
    elif rec == DirectionRecommendation.INVERT.value:
        strengths.append("direction aligned (invert)")
    else:
        weaknesses.append(f"direction uncertain ({rec})")

    if result.sharpe >= 0.5:
        strengths.append(f"good Sharpe ({result.sharpe:.2f})")
    elif result.sharpe > 0:
        strengths.append(f"positive Sharpe ({result.sharpe:.2f})")
    else:
        weaknesses.append(f"negative Sharpe ({result.sharpe:.2f})")

    return (
        "; ".join(strengths) if strengths else "no clear strengths",
        "; ".join(weaknesses) if weaknesses else "no clear weaknesses",
    )


def _top_selected_stocks(
    scores: pd.Series,
    topk: int,
) -> list[str]:
    """Return the top-*topk* stock instruments on the last evaluation date."""
    if scores.empty or topk <= 0:
        return []
    dates = sorted(scores.index.get_level_values("datetime").unique())
    if not dates:
        return []
    last_date = dates[-1]
    last_scores = scores.xs(last_date, level="datetime", drop_level=False)
    top = last_scores.nlargest(min(topk, len(last_scores)))
    return [str(i) for i in top.index.get_level_values("instrument")]


def _make_ranking_candidate(
    predictions: pd.DataFrame,
) -> pd.DataFrame:
    """Derive a per-date rank-transform candidate from LGBM predictions.

    For each date, scores are replaced with percentile rank in [0, 1], where
    a larger original score remains a larger rank score. Labeled honestly as
    RANK_TRANSFORM (derived from LGBM).
    """
    scores = predictions["score"]
    ranks = scores.groupby(level="datetime", group_keys=False).apply(
        lambda g: g.rank(ascending=True, method="average") / len(g)
    )
    return ranks.to_frame("score")


def evaluate_candidate(
    predictions: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    candidate_kind: CandidateKind,
    orientation: ScoreOrientation = ScoreOrientation.ORIGINAL,
    benchmark_returns: pd.DataFrame | None = None,
    topk: int = 15,
    rebalance_days: int = 10,
    cost_bps: int = 20,
    top_fraction: float = 0.10,
) -> CandidateResult:
    """Evaluate one candidate × orientation against raw forward returns.

    Args:
        predictions: DataFrame with ``(datetime, instrument)`` MultiIndex and
            a ``"score"`` column.
        raw_returns: DataFrame with ``(datetime, instrument)`` MultiIndex and
            a ``"return"`` column of **raw** forward returns.
        candidate_kind: Kind of candidate being evaluated.
        orientation: Whether to evaluate original or inverted scores.
        benchmark_returns: Optional benchmark returns for excess computation.
        topk: Number of stocks in top bucket for backtest.
        rebalance_days: Rebalance interval in trading days.
        cost_bps: Round-trip transaction cost in basis points.
        top_fraction: Fraction for top/bottom bucket analysis.

    Returns:
        ``CandidateResult`` with all metrics populated.  Backtest failures
        are recorded as promotion blockers — never silently swallowed.
    """
    # Validate raw return provenance
    _validate_raw_return_provenance(raw_returns, require_horizon=True)

    # Apply orientation
    scores = predictions["score"].copy()
    if orientation == ScoreOrientation.INVERTED:
        scores = -scores

    returns = raw_returns["return"]

    # Align on common dates
    common_idx = scores.index.intersection(returns.index)
    if len(common_idx) == 0:
        return CandidateResult(
            candidate_kind=candidate_kind,
            orientation=orientation,
            promotion_blockers=["No common dates between predictions and returns"],
        )

    scores_aligned = scores.loc[common_idx]
    returns_aligned = returns.loc[common_idx]

    # Drop non-finite
    mask = scores_aligned.notna() & returns_aligned.notna()
    scores_aligned = scores_aligned[mask]
    returns_aligned = returns_aligned[mask]

    if len(scores_aligned) < 10:
        return CandidateResult(
            candidate_kind=candidate_kind,
            orientation=orientation,
            promotion_blockers=["Insufficient data after alignment (< 10 observations)"],
        )

    # IC metrics
    ic, rank_ic, icir, positive_ic_ratio = _compute_candidate_ic_metrics(
        scores_aligned, returns_aligned
    )

    # Direction diagnostics
    direction = compute_direction_diagnostics(
        scores_aligned, returns_aligned, top_fraction=top_fraction
    )

    # Top selected stocks
    top_stocks = _top_selected_stocks(scores_aligned, topk)

    # Vectorized backtest for economic metrics
    from src.research.vectorized_backtest import run_vectorized_backtest

    pred_df = scores_aligned.to_frame("score")
    ret_df = returns_aligned.to_frame("return")
    ret_df.attrs.update(raw_returns.attrs)

    bt_result = None
    bt_error: str | None = None
    try:
        bt_result = run_vectorized_backtest(
            predictions=pred_df,
            returns=ret_df,
            benchmark_returns=benchmark_returns,
            topk=topk,
            rebalance_days=rebalance_days,
            cost_bps=cost_bps,
            non_overlapping=True,
            require_raw_10d_returns=True,
        )
    except Exception as exc:
        bt_error = f"Backtest failed: {exc}"

    # Build blockers list from backtest result
    blockers: list[str] = []
    if bt_error is not None:
        blockers.append(bt_error)

    if bt_result is not None:
        if icir < PROMOTION_THRESHOLDS["min_icir"]:
            blockers.append(f"ICIR {icir:.4f} < {PROMOTION_THRESHOLDS['min_icir']}")
        if rank_ic < PROMOTION_THRESHOLDS["min_rank_ic"]:
            blockers.append(f"Rank IC {rank_ic:.4f} < {PROMOTION_THRESHOLDS['min_rank_ic']}")
        if positive_ic_ratio < PROMOTION_THRESHOLDS["min_positive_ic_ratio"]:
            blockers.append(
                f"Positive IC ratio {positive_ic_ratio:.4f} < "
                f"{PROMOTION_THRESHOLDS['min_positive_ic_ratio']}"
            )
        if direction.top_minus_bottom_spread <= PROMOTION_THRESHOLDS["min_top_minus_bottom"]:
            blockers.append(
                f"Top−bottom spread {direction.top_minus_bottom_spread:.6f} ≤ "
                f"{PROMOTION_THRESHOLDS['min_top_minus_bottom']}"
            )
        if bt_result.sharpe_ratio < PROMOTION_THRESHOLDS["min_sharpe"]:
            blockers.append(
                f"Sharpe {bt_result.sharpe_ratio:.4f} < {PROMOTION_THRESHOLDS['min_sharpe']}"
            )
        if bt_result.max_drawdown < PROMOTION_THRESHOLDS["max_drawdown"]:
            blockers.append(
                f"Max drawdown {bt_result.max_drawdown:.4f} < "
                f"{PROMOTION_THRESHOLDS['max_drawdown']}"
            )

    # Error candidates remain RESEARCH with blockers; never promoted
    if bt_error is not None:
        status = CandidateStatus.RESEARCH
    elif blockers:
        status = CandidateStatus.RESEARCH
    else:
        status = CandidateStatus.PROMOTED

    # Build result — use backtest values when available, zero otherwise
    result = CandidateResult(
        candidate_kind=candidate_kind,
        orientation=orientation,
        ic=ic,
        rank_ic=rank_ic,
        icir=icir,
        positive_ic_ratio=positive_ic_ratio,
        total_return=bt_result.total_return if bt_result else 0.0,
        benchmark_return=bt_result.benchmark_return if bt_result else 0.0,
        excess_return=bt_result.excess_return if bt_result else 0.0,
        sharpe=bt_result.sharpe_ratio if bt_result else 0.0,
        max_drawdown=bt_result.max_drawdown if bt_result else 0.0,
        annualized_return=bt_result.annual_return if bt_result else 0.0,
        volatility=bt_result.volatility if bt_result else 0.0,
        turnover=bt_result.turnover if bt_result else 0.0,
        costs=bt_result.costs if bt_result else 0.0,
        score_direction=direction,
        n_periods=bt_result.n_periods if bt_result else 0,
        test_start=bt_result.test_start if bt_result else "",
        test_end=bt_result.test_end if bt_result else "",
        status=status,
        promotion_blockers=blockers,
        top_selected_stocks=top_stocks,
    )

    # Build rationale
    strength, weakness = _build_rationale(result, direction)
    result.strength_rationale = strength
    result.weakness_rationale = weakness

    return result


# ---------------------------------------------------------------------------
# Main workflow: run comparison
# ---------------------------------------------------------------------------


def run_signal_discovery_comparison(
    market: str,
    lgbm_predictions: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    factor_baseline_predictions: pd.DataFrame | None = None,
    benchmark_returns: pd.DataFrame | None = None,
    topk: int = 15,
    rebalance_days: int = 10,
    cost_bps: int = 20,
    output_dir: Path | None = None,
) -> ComparisonReport:
    """Run the fixed-10D signal discovery comparison across candidate kinds.

    Evaluates three candidate families in both original and inverted orientations:

    1. **LGBM regressor** — current model predictions.
    2. **Rank transform** — per-date descending rank of LGBM predictions
       (derived, labeled honestly).
    3. **Factor baseline** — explicit historical-price factor scores passed
       via *factor_baseline_predictions*.  If missing, a warning is recorded
       and no factor-baseline candidate is fabricated.

    Winner-bucket labels are **never** evaluated as candidate scores — that
    would be same-row target leakage because winners are defined from the
    same returns used for evaluation.

    Produces a ``ComparisonReport`` and writes it to *output_dir* when provided.

    Args:
        market: ``"us"`` or ``"cn"``.
        lgbm_predictions: Predictions from the LGBM regressor with a ``"score"``
            column and ``(datetime, instrument)`` MultiIndex.
        raw_returns: Raw forward returns with a ``"return"`` column and
            ``(datetime, instrument)`` MultiIndex.  Must have provenance attrs.
        factor_baseline_predictions: Explicit historical-price factor scores
            with a ``"score"`` column and matching index.  If None, the factor
            baseline candidate is skipped with a warning.
        benchmark_returns: Optional benchmark returns for excess computation.
        topk: Top-N stocks for backtest.
        rebalance_days: Rebalance interval in trading days.
        cost_bps: Round-trip cost in basis points.
        output_dir: If provided, the report is written to
            ``{output_dir}/{market}_signal_discovery_report.json``.

    Returns:
        ``ComparisonReport`` with all candidates evaluated.
    """
    report = ComparisonReport(
        market=market,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        label_horizon=10,
        rebalance_days=rebalance_days,
    )

    candidates: list[CandidateResult] = []

    # --- LGBM Regressor ---
    for orientation in (ScoreOrientation.ORIGINAL, ScoreOrientation.INVERTED):
        try:
            result = evaluate_candidate(
                predictions=lgbm_predictions,
                raw_returns=raw_returns,
                candidate_kind=CandidateKind.LGBM_REGRESSOR,
                orientation=orientation,
                benchmark_returns=benchmark_returns,
                topk=topk,
                rebalance_days=rebalance_days,
                cost_bps=cost_bps,
            )
            candidates.append(result)
        except Exception as exc:
            report.warnings.append(
                f"LGBM regressor {orientation.value} evaluation failed: {exc}"
            )

    # --- Rank transform (derived from LGBM, labeled honestly) ---
    try:
        rank_pred = _make_ranking_candidate(lgbm_predictions)
        for orientation in (ScoreOrientation.ORIGINAL, ScoreOrientation.INVERTED):
            try:
                result = evaluate_candidate(
                    predictions=rank_pred,
                    raw_returns=raw_returns,
                    candidate_kind=CandidateKind.RANK_TRANSFORM,
                    orientation=orientation,
                    benchmark_returns=benchmark_returns,
                    topk=topk,
                    rebalance_days=rebalance_days,
                    cost_bps=cost_bps,
                )
                candidates.append(result)
            except Exception as exc:
                report.warnings.append(
                    f"Rank transform {orientation.value} evaluation failed: {exc}"
                )
    except Exception as exc:
        report.warnings.append(f"Rank transform candidate creation failed: {exc}")

    # --- Factor baseline (explicit historical-price input required) ---
    if factor_baseline_predictions is not None:
        for orientation in (ScoreOrientation.ORIGINAL, ScoreOrientation.INVERTED):
            try:
                result = evaluate_candidate(
                    predictions=factor_baseline_predictions,
                    raw_returns=raw_returns,
                    candidate_kind=CandidateKind.FACTOR_BASELINE,
                    orientation=orientation,
                    benchmark_returns=benchmark_returns,
                    topk=topk,
                    rebalance_days=rebalance_days,
                    cost_bps=cost_bps,
                )
                candidates.append(result)
            except Exception as exc:
                report.warnings.append(
                    f"Factor baseline {orientation.value} evaluation failed: {exc}"
                )
    else:
        report.warnings.append(
            "Factor baseline candidate skipped: no factor_baseline_predictions provided. "
            "Load historical-price factor scores (e.g. $close / Ref($close, 10) - 1) "
            "and pass them as explicit input."
        )

    report.candidates = candidates

    # --- Classify candidates ---
    promoted: list[str] = []
    research_only: list[str] = []
    for c in candidates:
        label = f"{c.candidate_kind.value}/{c.orientation.value}"
        if c.status == CandidateStatus.PROMOTED:
            promoted.append(label)
        else:
            research_only.append(label)

    report.promoted = promoted
    report.research_only = research_only

    # --- Summary ---
    best_candidate_summary: dict[str, Any] = {}
    if candidates:
        # Direction is an explicit research parameter, so either orientation
        # may be the current best result.
        eligible_candidates = [c for c in candidates if c.n_periods > 0]
        if eligible_candidates:
            best = max(eligible_candidates, key=lambda c: (c.icir, c.excess_return))
            best_candidate_summary = {
                "candidate": f"{best.candidate_kind.value}/{best.orientation.value}",
                "icir": best.icir,
                "rank_ic": best.rank_ic,
                "direction": best.score_direction.recommendation,
                "strength": best.strength_rationale,
                "weakness": best.weakness_rationale,
            }

    report.summary = {
        "n_candidates": len(candidates),
        "n_promoted": len(promoted),
        "n_research_only": len(research_only),
        "best_candidate": best_candidate_summary.get("candidate"),
        "best_icir": best_candidate_summary.get("icir"),
        "best_candidate_summary": best_candidate_summary,
        "promotion_thresholds": PROMOTION_THRESHOLDS,
        "data_contracts": {
            "training_labels": "processed targets for fitting only; never economic returns",
            "raw_future_returns": "unprocessed Ref($close, -10) / $close - 1",
            "benchmark_excess_return": "stock raw 10D return minus same-date benchmark raw 10D return",
            "processed_rank_labels": "winner/rank targets for training only",
            "economic_returns": "raw_forward_return with horizon=10",
            "factor_baseline": "historical $close / Ref($close, 10) - 1",
        },
    }

    if not promoted:
        report.warnings.append(
            "No candidate met all promotion thresholds. "
            "All candidates remain at research-candidate status."
        )

    # --- Write report with relative path ---
    if output_dir is not None:
        report.summary["report_path"] = (
            f"artifacts/evidence/10d_signal_discovery/"
            f"{market}_signal_discovery_report.json"
        )
        report.write(output_dir)

    return report


# ---------------------------------------------------------------------------
# Integration helper for generate_release_candidate.py
# ---------------------------------------------------------------------------


def canonical_output_dir(project_root: Path) -> Path:
    """Return the canonical 10D signal discovery output directory."""
    return project_root / "artifacts" / "evidence" / "10d_signal_discovery"
