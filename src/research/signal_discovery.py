"""Fixed-10-trading-day signal discovery comparison report workflow.

Evaluates candidate models/factors against raw future 10D returns with
deterministic score-direction diagnostics and bucket-return analysis. The module
keeps research-candidate evidence separate from promoted-candidate evidence.
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


class CandidateKind(str, Enum):
    """Kinds of candidates that can be evaluated in a 10D discovery run."""

    LGBM_REGRESSOR = "lgbm_regressor"
    LGBM_LAMBDARANK = "lgbm_lambdarank"
    RANK_TRANSFORM = "rank_transform"
    FACTOR_BASELINE = "factor_baseline"
    WINNER_BUCKET_CLASSIFIER = "winner_bucket_classifier"


class ScoreOrientation(str, Enum):
    """Applied score orientation for one candidate result."""

    ORIGINAL = "original"
    INVERTED = "inverted"


class CandidateStatus(str, Enum):
    """Research candidate status, separate from production promotion."""

    RESEARCH = "research_candidate"
    PROMOTED = "promoted_candidate"
    REJECTED = "rejected"


class DirectionRecommendation(str, Enum):
    """Recommendation for the score series being diagnosed."""

    KEEP = "keep_score"
    INVERT = "invert_score"
    NO_SIGNAL = "no_signal"
    INCONCLUSIVE = "inconclusive"


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

_ALLOWED_WINNER_PREDICTION_PROVENANCE = "out_of_sample_winner_prediction"


@dataclass
class DirectionDiagnostics:
    """Diagnostics for one already-oriented score series."""

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
            "top_bucket_return": round(float(self.top_bucket_return), 8),
            "bottom_bucket_return": round(float(self.bottom_bucket_return), 8),
            "top_minus_bottom_spread": round(float(self.top_minus_bottom_spread), 8),
            "bottom_minus_top_spread": round(float(self.bottom_minus_top_spread), 8),
            "rank_ic": round(float(self.rank_ic), 6),
            "recommendation": self.recommendation,
            "n_samples": int(self.n_samples),
            "n_dates": int(self.n_dates),
        }


@dataclass
class CandidateResult:
    """Evaluation result for one candidate kind and applied orientation."""

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
    top_selected_stocks: list[str] = field(default_factory=list)
    strength_rationale: str = ""
    weakness_rationale: str = ""
    candidate_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_kind": self.candidate_kind.value,
            "orientation": self.orientation.value,
            "ic": round(float(self.ic), 6),
            "rank_ic": round(float(self.rank_ic), 6),
            "icir": round(float(self.icir), 6),
            "positive_ic_ratio": round(float(self.positive_ic_ratio), 6),
            "total_return": round(float(self.total_return), 6),
            "benchmark_return": round(float(self.benchmark_return), 6),
            "excess_return": round(float(self.excess_return), 6),
            "sharpe": round(float(self.sharpe), 6),
            "max_drawdown": round(float(self.max_drawdown), 6),
            "annualized_return": round(float(self.annualized_return), 6),
            "volatility": round(float(self.volatility), 6),
            "turnover": round(float(self.turnover), 6),
            "costs": round(float(self.costs), 8),
            "score_direction": self.score_direction.to_dict(),
            "n_periods": int(self.n_periods),
            "test_start": self.test_start,
            "test_end": self.test_end,
            "status": self.status.value,
            "promotion_blockers": list(self.promotion_blockers),
            "top_selected_stocks": list(self.top_selected_stocks),
            "strength_rationale": self.strength_rationale,
            "weakness_rationale": self.weakness_rationale,
            "candidate_name": self.candidate_name,
        }


@dataclass
class ComparisonReport:
    """Canonical fixed-10D signal discovery comparison report."""

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
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.market}_signal_discovery_report.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path


def _validate_raw_return_provenance(
    raw_returns: pd.DataFrame, *, require_horizon: bool = False
) -> None:
    """Require raw unprocessed forward returns for economic evaluation."""

    provenance = raw_returns.attrs.get("provenance", "")
    if provenance != "raw_forward_return":
        raise ValueError(
            "Economic evaluation requires provenance='raw_forward_return'; "
            f"got {provenance!r}. Processed labels are not valid returns."
        )
    if require_horizon:
        horizon = raw_returns.attrs.get("horizon")
        if horizon is not None and horizon != 10:
            raise ValueError(
                "The 10D signal discovery report requires returns attrs horizon=10"
            )
    if list(raw_returns.columns) != ["return"]:
        raise ValueError("Economic evaluation requires a single 'return' column")


def generate_winner_labels(
    raw_returns: pd.DataFrame,
    *,
    top_fraction: float = 0.20,
    min_stocks_per_day: int = 5,
) -> pd.DataFrame:
    """Generate same-row winner labels for training-target construction only."""

    if top_fraction <= 0 or top_fraction > 1:
        raise ValueError(f"top_fraction must be in (0, 1], got {top_fraction}")
    _validate_raw_return_provenance(raw_returns, require_horizon=True)

    df = raw_returns.copy()
    df["winner_label"] = 0

    for date, group in df.groupby(level="datetime"):
        valid = group[group["return"].notna()]
        if len(valid) < min_stocks_per_day:
            continue
        n_top = max(1, int(np.ceil(len(valid) * top_fraction)))
        stable = valid.copy()
        stable["__instrument"] = stable.index.get_level_values("instrument")
        winners = stable.sort_values(
            ["return", "__instrument"],
            ascending=[False, True],
            kind="mergesort",
            na_position="last",
        ).head(n_top)
        winner_instruments = set(winners.index.get_level_values("instrument"))
        date_mask = df.index.get_level_values("datetime") == date
        inst_mask = df.index.get_level_values("instrument").isin(winner_instruments)
        df.loc[date_mask & inst_mask, "winner_label"] = 1

    return df


def _ensure_multiindex(series: pd.Series) -> None:
    if not isinstance(series.index, pd.MultiIndex):
        raise ValueError("Expected a (datetime, instrument) MultiIndex")
    missing = {"datetime", "instrument"} - set(series.index.names)
    if missing:
        raise ValueError(f"Missing MultiIndex levels: {sorted(missing)}")


def _clean_aligned(scores: pd.Series, returns: pd.Series) -> pd.DataFrame:
    _ensure_multiindex(scores)
    _ensure_multiindex(returns)
    common_idx = scores.index.intersection(returns.index)
    if len(common_idx) == 0:
        return pd.DataFrame(columns=["score", "return"], index=common_idx)
    df = pd.DataFrame(
        {
            "score": scores.loc[common_idx].astype(float).values,
            "return": returns.loc[common_idx].astype(float).values,
        },
        index=common_idx,
    )
    return df.replace([np.inf, -np.inf], np.nan).dropna()


def compute_direction_diagnostics(
    scores: pd.Series,
    raw_returns: pd.Series,
    *,
    top_fraction: float = 0.10,
    min_stocks_per_day: int = 5,
) -> DirectionDiagnostics:
    """Diagnose the already-oriented score series.

    ``recommendation='keep_score'`` means the current score orientation points
    forward. ``recommendation='invert_score'`` means the current orientation
    still points backward and should not be described as aligned.
    """

    if top_fraction <= 0 or top_fraction > 0.5:
        raise ValueError("top_fraction must be in (0, 0.5]")
    df = _clean_aligned(scores, raw_returns)
    if df.empty:
        return DirectionDiagnostics(recommendation=DirectionRecommendation.NO_SIGNAL.value)

    top_returns: list[float] = []
    bottom_returns: list[float] = []
    rank_ics: list[float] = []

    for _, group in df.groupby(level="datetime"):
        if len(group) < min_stocks_per_day:
            continue
        ordered = group.sort_values("score", ascending=False)
        n_bucket = max(1, int(np.ceil(len(ordered) * top_fraction)))
        top_returns.append(float(ordered["return"].iloc[:n_bucket].mean()))
        bottom_returns.append(float(ordered["return"].iloc[-n_bucket:].mean()))

        rank_corr = ordered["score"].rank(method="average").corr(
            ordered["return"].rank(method="average")
        )
        if np.isfinite(rank_corr):
            rank_ics.append(float(rank_corr))

    if not top_returns:
        return DirectionDiagnostics(recommendation=DirectionRecommendation.NO_SIGNAL.value)

    top = float(np.mean(top_returns))
    bottom = float(np.mean(bottom_returns))
    spread = top - bottom
    rank_ic = float(np.mean(rank_ics)) if rank_ics else 0.0

    if spread > 1e-12 and rank_ic > 0:
        recommendation = DirectionRecommendation.KEEP.value
    elif spread < -1e-12 and rank_ic < 0:
        recommendation = DirectionRecommendation.INVERT.value
    elif abs(spread) <= 1e-12:
        recommendation = DirectionRecommendation.NO_SIGNAL.value
    else:
        recommendation = DirectionRecommendation.INCONCLUSIVE.value

    return DirectionDiagnostics(
        top_bucket_return=top,
        bottom_bucket_return=bottom,
        top_minus_bottom_spread=spread,
        bottom_minus_top_spread=-spread,
        rank_ic=rank_ic,
        recommendation=recommendation,
        n_samples=len(df),
        n_dates=len(top_returns),
    )


def _compute_candidate_ic_metrics(
    scores: pd.Series,
    returns: pd.Series,
    min_stocks_per_day: int = 5,
) -> tuple[float, float, float, float]:
    """Compute mean daily Pearson IC, rank IC, ICIR, and positive IC ratio."""

    df = _clean_aligned(scores, returns)
    if df.empty:
        return 0.0, 0.0, 0.0, 0.0

    daily_ics: list[float] = []
    daily_rank_ics: list[float] = []
    for _, group in df.groupby(level="datetime"):
        if len(group) < min_stocks_per_day:
            continue
        if group["score"].std(ddof=0) < 1e-12 or group["return"].std(ddof=0) < 1e-12:
            continue
        ic = group["score"].corr(group["return"])
        rank_ic = group["score"].rank(method="average").corr(
            group["return"].rank(method="average")
        )
        if np.isfinite(ic):
            daily_ics.append(float(ic))
        if np.isfinite(rank_ic):
            daily_rank_ics.append(float(rank_ic))

    if not daily_ics:
        return 0.0, 0.0, 0.0, 0.0

    mean_ic = float(np.mean(daily_ics))
    std_ic = float(np.std(daily_ics, ddof=1)) if len(daily_ics) > 1 else 0.0
    icir = mean_ic / std_ic if std_ic > 1e-12 else 0.0
    mean_rank_ic = float(np.mean(daily_rank_ics)) if daily_rank_ics else 0.0
    positive_ic_ratio = float(np.mean([ic > 0 for ic in daily_ics]))
    return mean_ic, mean_rank_ic, icir, positive_ic_ratio


def _build_rationale(
    result: CandidateResult,
    direction: DirectionDiagnostics,
) -> tuple[str, str]:
    """Build rationale for the already-applied score orientation."""

    strengths: list[str] = []
    weaknesses: list[str] = []

    if result.icir >= 0.5:
        strengths.append(f"strong ICIR ({result.icir:.3f})")
    elif result.icir >= PROMOTION_THRESHOLDS["min_icir"]:
        strengths.append(f"adequate ICIR ({result.icir:.3f})")
    else:
        weaknesses.append(f"low ICIR ({result.icir:.3f})")

    if result.rank_ic >= 0.03:
        strengths.append(f"solid rank IC ({result.rank_ic:.4f})")
    elif result.rank_ic >= PROMOTION_THRESHOLDS["min_rank_ic"]:
        strengths.append(f"marginal rank IC ({result.rank_ic:.4f})")
    else:
        weaknesses.append(f"weak rank IC ({result.rank_ic:.4f})")

    spread = direction.top_minus_bottom_spread
    if spread > 0.001:
        strengths.append(f"positive oriented top−bottom spread ({spread:.4f})")
    elif spread > 0:
        strengths.append(f"narrow positive oriented spread ({spread:.4f})")
    else:
        weaknesses.append(f"negative/flat oriented spread ({spread:.4f})")

    if direction.recommendation == DirectionRecommendation.KEEP.value:
        strengths.append(f"applied orientation is aligned ({result.orientation.value})")
    elif direction.recommendation == DirectionRecommendation.INVERT.value:
        weaknesses.append(
            f"applied orientation still points backward ({result.orientation.value})"
        )
    else:
        weaknesses.append(f"direction uncertain ({direction.recommendation})")

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


def _top_selected_stocks(scores: pd.Series, topk: int) -> list[str]:
    if scores.empty or topk <= 0:
        return []
    dates = sorted(scores.index.get_level_values("datetime").unique())
    if not dates:
        return []
    last_scores = scores.xs(dates[-1], level="datetime", drop_level=False)
    top = last_scores.nlargest(min(topk, len(last_scores)))
    return [str(i) for i in top.index.get_level_values("instrument")]


def _make_ranking_candidate(predictions: pd.DataFrame) -> pd.DataFrame:
    """Derive per-date percentile ranks from LGBM predictions."""

    ranks = predictions["score"].groupby(level="datetime", group_keys=False).apply(
        lambda g: g.rank(ascending=True, method="average") / len(g)
    )
    return ranks.to_frame("score")


def _validate_prediction_contract(
    predictions: pd.DataFrame,
    candidate_kind: CandidateKind,
) -> None:
    if list(predictions.columns) != ["score"]:
        raise ValueError("Candidate predictions must have a single 'score' column")
    if candidate_kind == CandidateKind.WINNER_BUCKET_CLASSIFIER:
        provenance = predictions.attrs.get("provenance")
        if provenance != _ALLOWED_WINNER_PREDICTION_PROVENANCE:
            raise ValueError(
                "winner_bucket_classifier evaluation requires out-of-sample "
                "winner predictions, not same-row winner labels derived from returns. "
                f"Expected predictions.attrs['provenance']="
                f"{_ALLOWED_WINNER_PREDICTION_PROVENANCE!r}, got {provenance!r}."
            )


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
    """Evaluate one candidate orientation against raw forward returns."""

    if not isinstance(candidate_kind, CandidateKind):
        candidate_kind = CandidateKind(candidate_kind)
    if not isinstance(orientation, ScoreOrientation):
        orientation = ScoreOrientation(orientation)

    _validate_prediction_contract(predictions, candidate_kind)
    _validate_raw_return_provenance(raw_returns, require_horizon=True)

    base_scores = predictions["score"].copy()
    scores = -base_scores if orientation == ScoreOrientation.INVERTED else base_scores
    returns = raw_returns["return"]
    df = _clean_aligned(scores, returns)

    if df.empty:
        return CandidateResult(
            candidate_kind=candidate_kind,
            orientation=orientation,
            promotion_blockers=["No common non-null observations between scores and returns"],
        )
    if len(df) < 10:
        return CandidateResult(
            candidate_kind=candidate_kind,
            orientation=orientation,
            promotion_blockers=["Insufficient data after alignment (< 10 observations)"],
        )

    scores_aligned = df["score"]
    returns_aligned = df["return"]
    ic, rank_ic, icir, positive_ic_ratio = _compute_candidate_ic_metrics(
        scores_aligned, returns_aligned
    )
    direction = compute_direction_diagnostics(
        scores_aligned,
        returns_aligned,
        top_fraction=top_fraction,
    )
    top_stocks = _top_selected_stocks(scores_aligned, topk)

    from src.research.vectorized_backtest import run_vectorized_backtest

    pred_df = scores_aligned.to_frame("score")
    ret_df = returns_aligned.to_frame("return")
    ret_df.attrs.update(raw_returns.attrs)
    ret_df.attrs.setdefault("horizon", 10)

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
    except Exception as exc:  # pragma: no cover - exercised via callers/tests
        bt_error = f"Backtest failed: {exc}"

    blockers: list[str] = []
    if bt_error:
        blockers.append(bt_error)
    if bt_result is not None:
        if icir < PROMOTION_THRESHOLDS["min_icir"]:
            blockers.append(f"ICIR {icir:.4f} < {PROMOTION_THRESHOLDS['min_icir']}")
        if rank_ic < PROMOTION_THRESHOLDS["min_rank_ic"]:
            blockers.append(
                f"Rank IC {rank_ic:.4f} < {PROMOTION_THRESHOLDS['min_rank_ic']}"
            )
        if positive_ic_ratio < PROMOTION_THRESHOLDS["min_positive_ic_ratio"]:
            blockers.append(
                f"Positive IC ratio {positive_ic_ratio:.4f} < "
                f"{PROMOTION_THRESHOLDS['min_positive_ic_ratio']}"
            )
        if direction.top_minus_bottom_spread <= PROMOTION_THRESHOLDS[
            "min_top_minus_bottom"
        ]:
            blockers.append(
                f"Top−bottom spread {direction.top_minus_bottom_spread:.6f} ≤ "
                f"{PROMOTION_THRESHOLDS['min_top_minus_bottom']}"
            )
        if bt_result.sharpe_ratio < PROMOTION_THRESHOLDS["min_sharpe"]:
            blockers.append(
                f"Sharpe {bt_result.sharpe_ratio:.4f} < "
                f"{PROMOTION_THRESHOLDS['min_sharpe']}"
            )
        if bt_result.max_drawdown < PROMOTION_THRESHOLDS["max_drawdown"]:
            blockers.append(
                f"Max drawdown {bt_result.max_drawdown:.4f} < "
                f"{PROMOTION_THRESHOLDS['max_drawdown']}"
            )

    status = CandidateStatus.RESEARCH if blockers or bt_error else CandidateStatus.PROMOTED
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
    result.strength_rationale, result.weakness_rationale = _build_rationale(
        result,
        direction,
    )
    return result


def _append_candidate(
    report: ComparisonReport,
    candidates: list[CandidateResult],
    *,
    name: str,
    predictions: pd.DataFrame,
    raw_returns: pd.DataFrame,
    candidate_kind: CandidateKind,
    benchmark_returns: pd.DataFrame | None,
    topk: int,
    rebalance_days: int,
    cost_bps: int,
) -> None:
    for orientation in (ScoreOrientation.ORIGINAL, ScoreOrientation.INVERTED):
        try:
            candidates.append(
                evaluate_candidate(
                    predictions=predictions,
                    raw_returns=raw_returns,
                    candidate_kind=candidate_kind,
                    orientation=orientation,
                    benchmark_returns=benchmark_returns,
                    topk=topk,
                    rebalance_days=rebalance_days,
                    cost_bps=cost_bps,
                )
            )
        except Exception as exc:
            report.warnings.append(f"{name} {orientation.value} evaluation failed: {exc}")


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
    """Run the fixed-10D comparison across available candidate families."""

    report = ComparisonReport(
        market=market,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        label_horizon=10,
        rebalance_days=rebalance_days,
    )
    _validate_raw_return_provenance(raw_returns, require_horizon=True)

    candidates: list[CandidateResult] = []
    _append_candidate(
        report,
        candidates,
        name="LGBM regressor",
        predictions=lgbm_predictions,
        raw_returns=raw_returns,
        candidate_kind=CandidateKind.LGBM_REGRESSOR,
        benchmark_returns=benchmark_returns,
        topk=topk,
        rebalance_days=rebalance_days,
        cost_bps=cost_bps,
    )

    try:
        rank_predictions = _make_ranking_candidate(lgbm_predictions)
        _append_candidate(
            report,
            candidates,
            name="Rank transform",
            predictions=rank_predictions,
            raw_returns=raw_returns,
            candidate_kind=CandidateKind.RANK_TRANSFORM,
            benchmark_returns=benchmark_returns,
            topk=topk,
            rebalance_days=rebalance_days,
            cost_bps=cost_bps,
        )
    except Exception as exc:
        report.warnings.append(f"Rank transform candidate creation failed: {exc}")

    if factor_baseline_predictions is not None:
        _append_candidate(
            report,
            candidates,
            name="Factor baseline",
            predictions=factor_baseline_predictions,
            raw_returns=raw_returns,
            candidate_kind=CandidateKind.FACTOR_BASELINE,
            benchmark_returns=benchmark_returns,
            topk=topk,
            rebalance_days=rebalance_days,
            cost_bps=cost_bps,
        )
    else:
        report.warnings.append(
            "Factor baseline candidate skipped: no factor_baseline_predictions provided."
        )

    report.candidates = candidates
    for candidate in candidates:
        label = f"{candidate.candidate_kind.value}/{candidate.orientation.value}"
        if candidate.status == CandidateStatus.PROMOTED:
            report.promoted.append(label)
        else:
            report.research_only.append(label)

    eligible = [c for c in candidates if c.n_periods > 0]
    best_candidate_summary: dict[str, Any] = {}
    if eligible:
        best = max(eligible, key=lambda c: (c.icir, c.rank_ic, c.excess_return))
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
        "n_promoted": len(report.promoted),
        "n_research_only": len(report.research_only),
        "best_candidate": best_candidate_summary.get("candidate"),
        "best_icir": best_candidate_summary.get("icir"),
        "best_candidate_summary": best_candidate_summary,
        "promotion_thresholds": PROMOTION_THRESHOLDS,
        "data_contracts": {
            "training_labels": "processed targets for fitting only; never economic returns",
            "raw_future_returns": "unprocessed Ref($close, -10) / $close - 1",
            "benchmark_excess_return": (
                "stock raw 10D return minus same-date benchmark raw 10D return"
            ),
            "processed_rank_labels": "winner/rank targets for training only",
            "economic_returns": "raw_forward_return with horizon=10",
            "factor_baseline": "historical $close / Ref($close, 10) - 1",
            "winner_bucket_labels": (
                "same-row training labels only unless replaced by explicit "
                "out-of-sample winner predictions"
            ),
        },
    }

    if not report.promoted:
        report.warnings.append(
            "No candidate met all promotion thresholds. "
            "All candidates remain at research-candidate status."
        )

    if output_dir is not None:
        report.summary["report_path"] = (
            f"artifacts/evidence/10d_signal_discovery/"
            f"{market}_signal_discovery_report.json"
        )
        report.write(output_dir)

    return report


def canonical_output_dir(project_root: Path) -> Path:
    """Return the canonical 10D signal discovery output directory."""

    return project_root / "artifacts" / "evidence" / "10d_signal_discovery"
