"""Batch Factor Scanner.

Scans a pool of factor expressions against configurable validation gates,
ranking them by predictive power (ICIR).  Optionally auto-registers passing
factors into the FactorRegistry at the Proposed stage.  Applies
Benjamini-Hochberg FDR correction to control false discovery rate when
scanning large factor pools.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from scipy import stats

from src.common.logging import get_logger
from src.research.factor_evaluator import DEFAULT_GATES, evaluate_factor
from src.research.factor_library import (
    FACTOR_LIBRARY,
    MEAN_REVERSION_LIBRARY,
    MOMENTUM_LIBRARY,
    VOLATILITY_LIBRARY,
    VOLUME_LIBRARY,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Pre-built factor pools
# ---------------------------------------------------------------------------
# Legacy aliases retained for backward compatibility; prefer FACTOR_LIBRARY.

MOMENTUM_FACTORS: list[dict] = MOMENTUM_LIBRARY
VOLATILITY_FACTORS: list[dict] = VOLATILITY_LIBRARY
VOLUME_FACTORS: list[dict] = VOLUME_LIBRARY
MEAN_REVERSION_FACTORS: list[dict] = MEAN_REVERSION_LIBRARY

# Default pool now uses the full combinatorial library (200+ factors).
DEFAULT_FACTOR_POOL: list[dict] = FACTOR_LIBRARY

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Result for a single factor after scanning."""

    name: str
    expression: str
    category: str
    rank_ic: float
    icir: float
    t_stat: float
    quintile_spread: float
    passed: bool
    fail_reasons: list[str] = field(default_factory=list)
    n_periods: int = 0
    raw_p_value: float = 1.0
    adjusted_p_value: float = 1.0
    fdr_significant: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "expression": self.expression,
            "category": self.category,
            "rank_ic": round(self.rank_ic, 6),
            "icir": round(self.icir, 4),
            "t_stat": round(self.t_stat, 4),
            "quintile_spread": round(self.quintile_spread, 6),
            "passed": self.passed,
            "fail_reasons": self.fail_reasons,
            "n_periods": self.n_periods,
            "raw_p_value": round(self.raw_p_value, 8),
            "adjusted_p_value": round(self.adjusted_p_value, 8),
            "fdr_significant": self.fdr_significant,
        }


@dataclass
class ScanReport:
    """Aggregate report from a batch factor scan."""

    market: str
    start_date: str
    end_date: str
    total_scanned: int
    passed: int
    failed: int
    results: list[ScanResult]  # sorted by |icir| descending
    top_factors: list[ScanResult]  # top 20 by |icir| that passed gates
    scan_duration_seconds: float
    fdr_alpha: float = 0.05
    n_fdr_significant: int = 0
    fdr_passed_factors: list[ScanResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_scanned": self.total_scanned,
            "passed": self.passed,
            "failed": self.failed,
            "results": [r.to_dict() for r in self.results],
            "top_factors": [r.to_dict() for r in self.top_factors],
            "scan_duration_seconds": round(self.scan_duration_seconds, 2),
            "fdr_alpha": self.fdr_alpha,
            "n_fdr_significant": self.n_fdr_significant,
            "fdr_passed_factors": [r.to_dict() for r in self.fdr_passed_factors],
        }


# ---------------------------------------------------------------------------
# FDR correction
# ---------------------------------------------------------------------------


def benjamini_hochberg_correction(
    p_values: list[float], alpha: float = 0.05
) -> tuple[list[bool], list[float]]:
    """Apply Benjamini-Hochberg FDR correction.

    Args:
        p_values: list of raw p-values
        alpha: FDR threshold (default 0.05)

    Returns:
        (significant_mask, adjusted_p_values) where significant_mask[i] is True
        if p_value i passes FDR correction
    """
    n = len(p_values)
    if n == 0:
        return [], []

    # Pair each p-value with its original index and sort ascending
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])

    adjusted = [0.0] * n
    # Compute adjusted p-values: p * n / rank (rank is 1-based)
    for rank, (orig_idx, p) in enumerate(indexed, start=1):
        adjusted[orig_idx] = p * n / rank

    # Enforce monotonicity: walk from largest rank downward, ensuring
    # adjusted_p[i] <= adjusted_p[i+1] in sorted order.
    # We work on the sorted order then write back.
    sorted_adjusted = [adjusted[idx] for idx, _ in indexed]
    for i in range(len(sorted_adjusted) - 2, -1, -1):
        sorted_adjusted[i] = min(sorted_adjusted[i], sorted_adjusted[i + 1])
    # Write back to original positions
    for rank, (orig_idx, _p) in enumerate(indexed):
        adjusted[orig_idx] = sorted_adjusted[rank]

    # Clamp to [0, 1]
    adjusted = [min(v, 1.0) for v in adjusted]

    significant = [v <= alpha for v in adjusted]
    return significant, adjusted


def _derive_p_value(t_stat: float, n_periods: int) -> float:
    """Convert a t-statistic to a two-sided p-value.

    Args:
        t_stat: The t-statistic from IC significance testing.
        n_periods: Number of time-series observations (degrees of freedom + 1).

    Returns:
        Two-sided p-value from the t-distribution.
    """
    if n_periods <= 1:
        return 1.0
    df = n_periods - 1
    return float(2 * (1 - stats.t.cdf(abs(t_stat), df=df)))


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------


def _evaluate_single(
    factor: dict,
    market: str,
    start_date: str,
    end_date: str,
    gates: dict | None,
    train_end: str | None = None,
) -> ScanResult:
    """Evaluate a single factor and return a ScanResult."""
    name = factor["name"]
    expression = factor["expression"]
    category = factor.get("category", "custom")

    try:
        eval_result = evaluate_factor(
            expression=expression,
            market=market,
            start_date=start_date,
            end_date=end_date,
            train_end=train_end,
            gates=gates,
        )
        return ScanResult(
            name=name,
            expression=expression,
            category=category,
            rank_ic=eval_result.rank_ic,
            icir=eval_result.icir,
            t_stat=eval_result.t_stat,
            quintile_spread=eval_result.quintile_spread,
            passed=eval_result.passed,
            fail_reasons=eval_result.fail_reasons,
            n_periods=eval_result.n_periods,
        )
    except Exception as exc:
        log.warning("Factor scan failed", name=name, error=str(exc))
        return ScanResult(
            name=name,
            expression=expression,
            category=category,
            rank_ic=0.0,
            icir=0.0,
            t_stat=0.0,
            quintile_spread=0.0,
            passed=False,
            fail_reasons=[f"Evaluation error: {exc}"],
            n_periods=0,
        )


def scan_factor_pool(
    factor_pool: list[dict] | None = None,
    market: str = "us",
    start_date: str = "2021-01-01",
    end_date: str = None,
    train_end: str | None = None,
    gates: dict | None = None,
    max_workers: int = 4,
    auto_register: bool = False,
    pool_path: str = "",
) -> ScanReport:
    """Scan a pool of factor expressions against validation gates.

    For each factor in *factor_pool* the function calls
    :func:`src.research.factor_evaluator.evaluate_factor` and collects the
    results into a :class:`ScanReport` sorted by absolute ICIR descending.

    Parameters
    ----------
    factor_pool:
        List of dicts, each with ``"name"``, ``"expression"``, and optionally
        ``"category"`` keys.  When ``None``, the pool is resolved via
        *pool_path* or falls back to :data:`FACTOR_LIBRARY`.
    market:
        ``"us"`` or ``"cn"``.
    start_date / end_date:
        Evaluation window.
    train_end:
        If provided, IC/quintile metrics are computed only on data after
        this date (out-of-sample).  When ``None``, the entire range is
        used (in-sample).
    gates:
        Override default gate thresholds.  Keys match
        ``factor_evaluator.DEFAULT_GATES``.
    max_workers:
        Maximum parallel evaluations.  Set to 1 for sequential execution.
    auto_register:
        If ``True``, factors that pass gates are registered in the
        :class:`FactorRegistry` at the Proposed stage.
    pool_path:
        Path to a custom YAML factor pool file.  When non-empty, overrides
        *factor_pool* and loads factors via
        :func:`src.research.factor_library.load_factor_pool_from_yaml`.

    Returns
    -------
    ScanReport
    """
    from src.common.dates import default_end_date

    end_date = end_date or default_end_date()
    # Resolve the factor pool: explicit path > explicit list > default library
    if pool_path:
        from src.research.factor_library import load_factor_pool_from_yaml

        factor_pool = load_factor_pool_from_yaml(pool_path)
    elif factor_pool is None:
        factor_pool = FACTOR_LIBRARY

    gates = gates or dict(DEFAULT_GATES)
    t0 = time.monotonic()

    log.info(
        "factor_scan_started",
        pool_size=len(factor_pool),
        market=market,
        start=start_date,
        end=end_date,
        train_end=train_end,
        oos_mode=train_end is not None,
        max_workers=max_workers,
        auto_register=auto_register,
    )

    results: list[ScanResult] = []

    if max_workers <= 1:
        for factor in factor_pool:
            results.append(_evaluate_single(factor, market, start_date, end_date, gates, train_end))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _evaluate_single, factor, market, start_date, end_date, gates, train_end
                ): factor["name"]
                for factor in factor_pool
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    log.warning("Scan worker failed", name=name, error=str(exc))

    # Sort by |icir| descending
    results.sort(key=lambda r: abs(r.icir), reverse=True)

    # ------------------------------------------------------------------
    # FDR correction: derive p-values from t-stats and apply BH procedure
    # ------------------------------------------------------------------
    fdr_alpha = 0.05
    raw_p_values = [_derive_p_value(r.t_stat, r.n_periods) for r in results]
    significant_mask, adjusted_p_values = benjamini_hochberg_correction(
        raw_p_values, alpha=fdr_alpha
    )

    for i, result in enumerate(results):
        result.raw_p_value = raw_p_values[i]
        result.adjusted_p_value = adjusted_p_values[i]
        result.fdr_significant = significant_mask[i]

    fdr_passed_factors = [r for r in results if r.passed and r.fdr_significant]

    passed_results = [r for r in results if r.passed]
    top_factors = passed_results[:20]

    elapsed = time.monotonic() - t0

    report = ScanReport(
        market=market,
        start_date=start_date,
        end_date=end_date,
        total_scanned=len(results),
        passed=len(passed_results),
        failed=len(results) - len(passed_results),
        results=results,
        top_factors=top_factors,
        scan_duration_seconds=elapsed,
        fdr_alpha=fdr_alpha,
        n_fdr_significant=len(fdr_passed_factors),
        fdr_passed_factors=fdr_passed_factors,
    )

    log.info(
        "factor_scan_complete",
        total=report.total_scanned,
        passed=report.passed,
        failed=report.failed,
        fdr_alpha=fdr_alpha,
        n_fdr_significant=report.n_fdr_significant,
        duration_s=round(elapsed, 2),
    )

    # Auto-register passed factors
    if auto_register and passed_results:
        _auto_register_factors(passed_results)

    return report


def _auto_register_factors(passed_results: list[ScanResult]) -> None:
    """Register passed factors in the FactorRegistry at the Proposed stage."""
    from src.research.factor_registry import FactorRegistry

    registry = FactorRegistry()
    registered = 0
    skipped = 0

    for result in passed_results:
        try:
            registry.register_factor(
                name=result.name,
                expression=result.expression,
                category=result.category,
            )
            registered += 1
            log.info("auto_registered_factor", name=result.name)
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                skipped += 1
                log.debug("auto_register_skipped_exists", name=result.name)
            else:
                log.warning(
                    "auto_register_failed",
                    name=result.name,
                    error=str(exc),
                )

    log.info(
        "auto_register_summary",
        registered=registered,
        skipped=skipped,
    )
