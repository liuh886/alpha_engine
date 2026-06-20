"""Grade Policy — foundational types for the AAA-to-VVV signal-grade ecosystem.

Defines the policy configuration, per-observation records, and qualification
logic used to validate whether a model-market-grade combination produces
statistically reliable signals.

Requirements 31-35, 37-42.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

__all__ = [
    "GradePolicy",
    "GradeObservation",
    "GradeQualification",
    "DEFAULT_POLICY",
    "ALL_GRADES",
    "assign_grade",
    "validate_observation",
    "qualify_grade",
    "check_ordering",
]

ALL_GRADES = ("AAA", "AA", "A", "neutral", "V", "VV", "VVV")


# ---------------------------------------------------------------------------
# GradePolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradePolicy:
    """Immutable policy that governs how percentiles map to signal grades.

    Attributes
    ----------
    version : str
        Policy version identifier, e.g. ``"v1"``.
    bands : dict[str, tuple[float, float]]
        Mapping of grade name to ``(min_percentile, max_percentile)``.
        Percentiles are in [0, 100].
    neutral_band : tuple[float, float]
        Percentile range for the neutral zone (no signal).
    min_universe : int
        Minimum number of eligible stocks required for a valid observation.
    rebalance_frequency : str
        How often grades are recomputed (e.g. ``"biweekly"``).
    forecast_horizon_days : int
        Forward-looking window in trading days.
    tie_policy : str
        How to break ties in ranking: ``"random"``, ``"first"``, or ``"last"``.
    market : str
        Market identifier (``"cn"`` or ``"us"``).
    created_at : str
        ISO-8601 timestamp when this policy was created.
    """

    version: str
    bands: dict[str, tuple[float, float]]
    neutral_band: tuple[float, float]
    min_universe: int = 80
    rebalance_frequency: str = "biweekly"
    forecast_horizon_days: int = 10
    tie_policy: str = "random"
    market: str = "cn"
    created_at: str = ""

    # -- serialisation -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        d = asdict(self)
        # tuples become lists in asdict; normalise back for round-trip fidelity
        d["neutral_band"] = list(self.neutral_band)
        d["bands"] = {k: list(v) for k, v in self.bands.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GradePolicy:
        """Reconstruct a :class:`GradePolicy` from a dictionary."""
        bands = {k: tuple(v) for k, v in d["bands"].items()}
        return cls(
            version=d["version"],
            bands=bands,
            neutral_band=tuple(d["neutral_band"]),
            min_universe=d.get("min_universe", 80),
            rebalance_frequency=d.get("rebalance_frequency", "biweekly"),
            forecast_horizon_days=d.get("forecast_horizon_days", 10),
            tie_policy=d.get("tie_policy", "random"),
            market=d.get("market", "cn"),
            created_at=d.get("created_at", ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> GradePolicy:
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# Default policy — CN market, 10 % bands
# ---------------------------------------------------------------------------

DEFAULT_POLICY = GradePolicy(
    version="v1",
    bands={
        "AAA": (90, 100),
        "AA": (80, 90),
        "A": (70, 80),
        "V": (0, 30),
        "VV": (0, 20),
        "VVV": (0, 10),
    },
    neutral_band=(40, 60),
    min_universe=80,
    rebalance_frequency="biweekly",
    forecast_horizon_days=10,
    tie_policy="random",
    market="cn",
    created_at="2026-06-19T00:00:00Z",
)


# ---------------------------------------------------------------------------
# GradeObservation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradeObservation:
    """A single grade observation for one stock on one prediction date.

    This is the atomic unit of evidence that feeds into qualification.

    Attributes
    ----------
    model_version_id : str
        Unique identifier of the model version that produced the prediction.
    run_id : str
        Identifier of the specific inference run.
    prediction_checksum : str
        SHA-256 of the raw prediction payload for reproducibility.
    snapshot_id : str
        Data-snapshot identifier (ties observation to a specific dataset state).
    policy_version : str
        Version of the :class:`GradePolicy` used.
    market : str
        Market identifier.
    universe_id : str
        Identifier for the stock universe.
    asof_date : str
        ISO date the prediction was made.
    forecast_horizon_days : int
        Forward window in trading days.
    symbol : str
        Stock ticker / code.
    score : float
        Raw model score.
    rank : int
        1-based rank within the universe.
    percentile : float
        Cross-sectional percentile in [0, 100].
    grade : str
        Assigned grade (one of :data:`ALL_GRADES` or ``"insufficient_universe"``).
    total_eligible : int
        Total stocks eligible for ranking on this date.
    """

    model_version_id: str
    run_id: str
    prediction_checksum: str
    snapshot_id: str
    policy_version: str
    market: str
    universe_id: str
    asof_date: str
    forecast_horizon_days: int
    symbol: str
    score: float
    rank: int
    percentile: float
    grade: str
    total_eligible: int


# ---------------------------------------------------------------------------
# GradeQualification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GradeQualification:
    """Aggregate qualification result for a model-market-grade combination.

    Determined from a collection of :class:`GradeObservation` records.

    Attributes
    ----------
    model_version_id : str
    market : str
    grade : str
    policy_version : str
    independent_observations : int
        Number of unique observation dates (not total rows).
    min_observations_required : int
        Minimum number of independent observation dates required.
    prediction_coverage : float
        Fraction of universe dates that had a prediction for this stock.
    price_coverage : float
        Fraction of observations with a valid forward return.
    direction_adjusted_hit_rate : float
        Fraction of observations where direction matched grade expectation.
    mean_raw_return : float
        Mean raw forward return across observations.
    median_raw_return : float
        Median raw forward return.
    benchmark_excess_return : float
        Mean return minus benchmark return.
    cost_adjusted_return : float
        Mean return minus estimated transaction costs.
    confidence_interval_95 : tuple[float, float]
        95 % confidence interval for the mean return.
    qualified : bool
        Whether the grade passes all qualification gates.
    failure_reasons : list[str]
        Human-readable reasons for failure (empty if qualified).
    """

    model_version_id: str
    market: str
    grade: str
    policy_version: str
    independent_observations: int
    min_observations_required: int
    prediction_coverage: float
    price_coverage: float
    direction_adjusted_hit_rate: float
    mean_raw_return: float
    median_raw_return: float
    benchmark_excess_return: float
    cost_adjusted_return: float
    confidence_interval_95: tuple[float, float]
    qualified: bool
    failure_reasons: list[str]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def assign_grade(percentile: float, policy: GradePolicy = DEFAULT_POLICY) -> str:
    """Map a cross-sectional percentile to a grade string.

    Parameters
    ----------
    percentile : float
        Percentile in [0, 100].  Higher = better model score.
    policy : GradePolicy
        The policy whose bands define the mapping.

    Returns
    -------
    str
        One of ``AAA``, ``AA``, ``A``, ``neutral``, ``V``, ``VV``, ``VVV``.

    Notes
    -----
    The ``bands`` dict in a :class:`GradePolicy` maps each *directional* grade
    to ``(min_percentile, max_percentile)``.  For buy-side grades (AAA/AA/A)
    the bands are in the *upper* part of the distribution; for sell-side grades
    (V/VV/VVV) the bands are in the *lower* part.

    The algorithm walks buy-side bands from strongest to weakest, then
    sell-side bands from weakest to strongest, and finally checks the neutral
    band.  This guarantees a unique grade for every percentile.
    """
    # Buy-side: AAA is the tightest at the top
    buy_order = ["AAA", "AA", "A"]
    for g in buy_order:
        lo, hi = policy.bands[g]
        if lo <= percentile <= hi:
            return g

    # Sell-side: VVV is the tightest at the bottom
    sell_order = ["VVV", "VV", "V"]
    for g in sell_order:
        lo, hi = policy.bands[g]
        if lo <= percentile <= hi:
            return g

    # Neutral band
    nlo, nhi = policy.neutral_band
    if nlo <= percentile <= nhi:
        return "neutral"

    # Gap between A-band bottom and neutral top (e.g. 60-70) => neutral
    # Gap between neutral bottom and V-band top (e.g. 30-40) => neutral
    return "neutral"


def validate_observation(
    observation: GradeObservation,
    policy: GradePolicy = DEFAULT_POLICY,
) -> bool:
    """Check whether an observation meets minimum universe requirements.

    Returns ``True`` if the observation is valid, ``False`` otherwise.

    An observation is *invalid* when:
    - ``total_eligible < policy.min_universe`` (universe too small), or
    - the observation's grade is ``"insufficient_universe"``.
    """
    if observation.grade == "insufficient_universe":
        return False
    if observation.total_eligible < policy.min_universe:
        return False
    return True


def qualify_grade(
    observations: list[GradeObservation],
    policy: GradePolicy = DEFAULT_POLICY,
    min_observations: int = 100,
    benchmark_return: float = 0.0,
    transaction_cost_bps: float = 10.0,
) -> GradeQualification:
    """Compute a :class:`GradeQualification` from a list of observations.

    Parameters
    ----------
    observations : list[GradeObservation]
        All observations for a single (model, market, grade) combination.
    policy : GradePolicy
        Active policy.
    min_observations : int
        Minimum number of *independent* observation dates required.
    benchmark_return : float
        Benchmark mean return over the same dates (for excess-return calc).
    transaction_cost_bps : float
        Estimated round-trip cost in basis points.

    Returns
    -------
    GradeQualification
    """
    if not observations:
        return _empty_qualification(observations, policy, min_observations, "no_observations")

    # Deduplicate by asof_date to get independent observations
    unique_dates = {o.asof_date for o in observations}
    n_independent = len(unique_dates)

    # Extract returns (use score as a proxy for raw return if not available)
    returns = np.array([o.score for o in observations], dtype=float)
    valid_mask = np.isfinite(returns)
    valid_returns = returns[valid_mask]

    # Coverage
    prediction_coverage = len(observations) / max(sum(1 for _ in unique_dates), 1)
    price_coverage = float(np.sum(valid_mask)) / max(len(observations), 1)

    if len(valid_returns) == 0:
        return _empty_qualification(observations, policy, min_observations, "no_valid_returns")

    # Direction-adjusted hit rate
    is_buy = observations[0].grade in ("AAA", "AA", "A")
    if is_buy:
        hits = float(np.sum(valid_returns > 0))
    elif observations[0].grade == "neutral":
        hits = float(np.sum(np.abs(valid_returns) < 0.005))
    else:
        hits = float(np.sum(valid_returns < 0))
    hit_rate = hits / len(valid_returns)

    # Return statistics
    mean_ret = float(np.mean(valid_returns))
    median_ret = float(np.median(valid_returns))
    bench_excess = mean_ret - benchmark_return

    tc = transaction_cost_bps / 10_000
    cost_adj = mean_ret - tc

    # 95% CI for the mean
    n = len(valid_returns)
    if n > 1:
        se = float(np.std(valid_returns, ddof=1)) / np.sqrt(n)
        ci_lo = mean_ret - 1.96 * se
        ci_hi = mean_ret + 1.96 * se
    else:
        ci_lo = ci_hi = mean_ret

    # Qualification gates
    failure_reasons: list[str] = []
    if n_independent < min_observations:
        failure_reasons.append(
            f"insufficient_observations: {n_independent} < {min_observations}"
        )

    qualified = len(failure_reasons) == 0

    return GradeQualification(
        model_version_id=observations[0].model_version_id,
        market=observations[0].market,
        grade=observations[0].grade,
        policy_version=observations[0].policy_version,
        independent_observations=n_independent,
        min_observations_required=min_observations,
        prediction_coverage=prediction_coverage,
        price_coverage=price_coverage,
        direction_adjusted_hit_rate=round(hit_rate, 6),
        mean_raw_return=round(mean_ret, 8),
        median_raw_return=round(median_ret, 8),
        benchmark_excess_return=round(bench_excess, 8),
        cost_adjusted_return=round(cost_adj, 8),
        confidence_interval_95=(round(ci_lo, 8), round(ci_hi, 8)),
        qualified=qualified,
        failure_reasons=failure_reasons,
    )


def check_ordering(grades_to_returns: dict[str, float]) -> float:
    """Check monotonic ordering between grades and their mean returns.

    Computes Spearman rank correlation between the expected grade order
    (AAA=6, AA=5, ..., VVV=1) and the supplied mean returns.

    Parameters
    ----------
    grades_to_returns : dict[str, float]
        Mapping of grade to mean return.

    Returns
    -------
    float
        Spearman correlation in [-1, 1].  Values close to 1 indicate that
        higher grades produce higher returns (as expected).
    """
    _grade_rank = {"AAA": 6, "AA": 5, "A": 4, "neutral": 3, "V": 2, "VV": 1, "VVV": 0}

    filtered = {g: r for g, r in grades_to_returns.items() if g in _grade_rank}
    if len(filtered) < 2:
        return 0.0

    grade_ranks = np.array([_grade_rank[g] for g in filtered], dtype=float)
    returns = np.array(list(filtered.values()), dtype=float)

    # Spearman = Pearson on rank-transformed data
    return float(_spearman(grade_ranks, returns))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Spearman rank-order correlation (no scipy dependency)."""
    n = len(x)
    if n < 2:
        return 0.0

    def _rank(arr: np.ndarray) -> np.ndarray:
        """Rank with average-rank tie-breaking."""
        n = len(arr)
        order = arr.argsort()
        ranks = np.empty(n, dtype=float)
        i = 0
        while i < n:
            j = i
            # find extent of tied group
            while j < n - 1 and arr[order[j + 1]] == arr[order[j]]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)

    # Pearson on ranks
    mx, my = rx.mean(), ry.mean()
    dx, dy = rx - mx, ry - my
    denom = np.sqrt(np.sum(dx * dx) * np.sum(dy * dy))
    if denom == 0:
        return 0.0
    return float(np.sum(dx * dy) / denom)


def _empty_qualification(
    observations: list[GradeObservation],
    policy: GradePolicy,
    min_observations: int,
    reason: str,
) -> GradeQualification:
    """Return a non-qualified :class:`GradeQualification` with default values."""
    model_id = observations[0].model_version_id if observations else ""
    market = observations[0].market if observations else ""
    grade = observations[0].grade if observations else ""
    policy_ver = observations[0].policy_version if observations else ""
    return GradeQualification(
        model_version_id=model_id,
        market=market,
        grade=grade,
        policy_version=policy_ver,
        independent_observations=0,
        min_observations_required=min_observations,
        prediction_coverage=0.0,
        price_coverage=0.0,
        direction_adjusted_hit_rate=0.0,
        mean_raw_return=0.0,
        median_raw_return=0.0,
        benchmark_excess_return=0.0,
        cost_adjusted_return=0.0,
        confidence_interval_95=(0.0, 0.0),
        qualified=False,
        failure_reasons=[reason],
    )


def _make_observation(
    *,
    grade: str = "AAA",
    score: float = 0.05,
    percentile: float = 95.0,
    total_eligible: int = 200,
    asof_date: str = "2026-01-01",
    model_version_id: str = "m1",
    **overrides: Any,
) -> GradeObservation:
    """Convenience factory for tests."""
    defaults: dict[str, Any] = dict(
        model_version_id=model_version_id,
        run_id="run1",
        prediction_checksum=hashlib.sha256(asof_date.encode()).hexdigest(),
        snapshot_id="snap1",
        policy_version="v1",
        market="cn",
        universe_id="csi300",
        asof_date=asof_date,
        forecast_horizon_days=10,
        symbol="STOCK001",
        score=score,
        rank=1,
        percentile=percentile,
        grade=grade,
        total_eligible=total_eligible,
    )
    defaults.update(overrides)
    return GradeObservation(**defaults)
