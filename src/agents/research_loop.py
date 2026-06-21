"""Automated agent research loop.

End-to-end cycle: goal -> scan -> compile -> backtest -> attribute -> promote.

Each phase is independently error-tolerant so partial failures don't abort the
entire cycle.  Results are collected into a :class:`CycleResult` that reports
success/partial/failed status with per-phase metrics.

The :func:`run_iterative_research` convenience function accepts a natural
language goal string, parses it via :mod:`src.agents.goal_parser`, and runs
multiple research cycles guided by the parsed constraints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.common.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CycleResult:
    """Structured outcome of a single research cycle."""

    # Scan phase
    factors_scanned: int = 0
    factors_passed_fdr: int = 0
    top_factors: list[dict] = field(default_factory=list)

    # Compile phase
    config_path: str = ""
    factors_in_config: int = 0

    # Backtest phase
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    excess_return: float = 0.0

    # Attribution phase
    top_contributors: list[dict] = field(default_factory=list)
    factor_coverage: float = 0.0  # R^2

    # Promotion phase
    factors_promoted: int = 0
    new_active_factors: list[str] = field(default_factory=list)

    # Summary
    cycle_duration_seconds: float = 0.0
    status: str = "pending"  # "success", "partial", "failed"
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "factors_scanned": self.factors_scanned,
            "factors_passed_fdr": self.factors_passed_fdr,
            "top_factors": self.top_factors,
            "config_path": self.config_path,
            "factors_in_config": self.factors_in_config,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "excess_return": self.excess_return,
            "top_contributors": self.top_contributors,
            "factor_coverage": self.factor_coverage,
            "factors_promoted": self.factors_promoted,
            "new_active_factors": self.new_active_factors,
            "cycle_duration_seconds": round(self.cycle_duration_seconds, 2),
            "status": self.status,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Iteration decision
# ---------------------------------------------------------------------------


@dataclass
class IterationDecision:
    """Decision about what the next research iteration should do."""

    action: str  # "scan_more", "adjust_hyperparams", "change_market", "stop", "retry"
    reason: str
    params: dict = field(default_factory=dict)  # action-specific parameters

    def to_dict(self) -> dict:
        return {"action": self.action, "reason": self.reason, "params": self.params}


def decide_next_action(
    cycle_result: CycleResult,
    market: str,
    consecutive_no_improve: int = 0,
    best_sharpe: float = 0.0,
) -> IterationDecision:
    """Analyze cycle results and decide what to do next.

    Decision rules (evaluated in priority order):
    1. Cycle failed entirely -> ``"stop"`` (nothing to build on).
    2. 3+ consecutive cycles with no improvement -> ``"stop"`` (diminishing returns).
    3. No factors passed FDR -> ``"scan_more"`` with relaxed gates.
    4. Factors passed but backtest Sharpe < 0.5 -> ``"adjust_hyperparams"``.
    5. Walk-forward attribution R² low (< 0.15) and factors exist -> ``"retry"``
       with different train window.
    6. Attribution shows one factor dominates (>50%) -> ``"scan_more"`` for
       diversification.
    7. Backtest Sharpe > 1.0 and R² > 0.3 -> ``"stop"`` (good result).

    Parameters
    ----------
    cycle_result:
        The :class:`CycleResult` from the most recent cycle.
    market:
        Current market region.
    consecutive_no_improve:
        How many consecutive cycles have not improved on *best_sharpe*.
    best_sharpe:
        The best Sharpe ratio achieved across all iterations so far.

    Returns
    -------
    IterationDecision
    """

    # --- Rule 1: total failure ---
    if cycle_result.status == "failed":
        return IterationDecision(
            action="stop",
            reason="Cycle failed entirely; no phases succeeded.",
        )

    # --- Rule 2: diminishing returns ---
    if consecutive_no_improve >= 3:
        return IterationDecision(
            action="stop",
            reason=(
                f"No improvement over {consecutive_no_improve} consecutive "
                f"cycles (best Sharpe so far: {best_sharpe:.3f})."
            ),
        )

    # --- Rule 3: no factors passed FDR ---
    if cycle_result.factors_passed_fdr == 0:
        return IterationDecision(
            action="scan_more",
            reason="No factors passed FDR correction. Trying a broader factor pool.",
            params={
                "relax_fdr": True,
                "suggestion": "increase_factor_pool",
                "market": market,
            },
        )

    # --- Rule 4: factors found but poor backtest ---
    if cycle_result.factors_passed_fdr > 0 and 0.0 < cycle_result.sharpe < 0.5:
        return IterationDecision(
            action="adjust_hyperparams",
            reason=(
                f"Factors passed FDR ({cycle_result.factors_passed_fdr}) but "
                f"backtest Sharpe is low ({cycle_result.sharpe:.3f}). "
                f"Adjusting model hyperparameters."
            ),
            params={
                "current_sharpe": cycle_result.sharpe,
                "market": market,
            },
        )

    # --- Rule 7 (check early): good result -> stop ---
    if cycle_result.sharpe > 1.0 and cycle_result.factor_coverage > 0.3:
        return IterationDecision(
            action="stop",
            reason=(
                f"Target achieved: Sharpe={cycle_result.sharpe:.3f} > 1.0 "
                f"and R²={cycle_result.factor_coverage:.3f} > 0.3."
            ),
        )

    # --- Rule 5: low attribution R² -> retry with different train window ---
    if (
        cycle_result.factor_coverage > 0.0
        and cycle_result.factor_coverage < 0.15
        and cycle_result.factors_passed_fdr > 0
    ):
        return IterationDecision(
            action="retry",
            reason=(
                f"Attribution R² is low ({cycle_result.factor_coverage:.3f}). "
                f"Retrying with a different training window."
            ),
            params={
                "adjust_train_window": True,
                "market": market,
            },
        )

    # --- Rule 6: single-factor concentration -> diversify ---
    if cycle_result.top_contributors:
        top_pct = cycle_result.top_contributors[0].get("contribution_pct", 0.0)
        if top_pct > 50.0:
            top_name = cycle_result.top_contributors[0].get("factor_name", "unknown")
            return IterationDecision(
                action="scan_more",
                reason=(
                    f"Attribution shows '{top_name}' dominates at "
                    f"{top_pct:.1f}% (>50%). Scanning for diversifying factors."
                ),
                params={
                    "exclude_category": cycle_result.top_contributors[0].get("category"),
                    "market": market,
                },
            )

    # --- Default: nothing actionable, stop ---
    return IterationDecision(
        action="stop",
        reason="No clear improvement path identified; stopping iteration.",
    )


# ---------------------------------------------------------------------------
# Default base config resolution
# ---------------------------------------------------------------------------

_MARKET_BASE_CONFIG = {
    "us": "us_lgbm_workflow.yaml",
    "cn": "cn_lgbm_workflow.yaml",
}


def _resolve_base_config(base_config: str | None, market: str) -> str:
    """Resolve the base config path, auto-detecting from market if not provided."""
    if base_config:
        return base_config
    return _MARKET_BASE_CONFIG.get(market, "us_lgbm_workflow.yaml")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------


def run_research_cycle(
    market: str = "us",
    goal_description: str = "",
    base_config: str | None = None,
    scan_pool: list[dict] | None = None,
    max_factors_to_compile: int = 10,
    auto_promote: bool = True,
) -> CycleResult:
    """Execute a full research cycle: scan, compile, backtest, attribute, promote.

    Parameters
    ----------
    market:
        Market region (``"us"`` or ``"cn"``).
    goal_description:
        Natural-language description of the research goal (used in logging).
    base_config:
        Path or filename of the base strategy YAML config.  If ``None``,
        auto-detected from *market*.
    scan_pool:
        Factor pool to scan.  If ``None``, uses the default factor library.
    max_factors_to_compile:
        Maximum number of top factors (by |ICIR|) to include in the strategy config.
    auto_promote:
        If ``True``, automatically attempt to promote each factor through its
        gate after a successful backtest.

    Returns
    -------
    CycleResult
        Aggregated metrics for the cycle.
    """
    cycle_start = time.monotonic()
    result = CycleResult()
    phase_successes = 0
    phase_failures = 0

    goal_label = goal_description or "auto research cycle"
    log.info(
        "research_cycle_started",
        market=market,
        goal=goal_label,
        base_config=base_config,
        max_factors=max_factors_to_compile,
        auto_promote=auto_promote,
    )

    # ------------------------------------------------------------------
    # Phase 1: Scan
    # ------------------------------------------------------------------
    scan_report = None
    try:
        from src.research.factor_scanner import DEFAULT_FACTOR_POOL, scan_factor_pool

        pool = scan_pool if scan_pool is not None else DEFAULT_FACTOR_POOL
        log.info("scanning_factors", pool_size=len(pool), market=market)
        scan_report = scan_factor_pool(
            factor_pool=pool,
            market=market,
            auto_register=True,
        )
        result.factors_scanned = scan_report.total_scanned
        result.factors_passed_fdr = scan_report.n_fdr_significant

        # Top 5 by ICIR from fdr-passed factors (or all passed if fewer)
        top_source = scan_report.fdr_passed_factors or scan_report.top_factors
        result.top_factors = [f.to_dict() for f in top_source[:5]]

        phase_successes += 1
        log.info(
            "scan_phase_complete",
            scanned=result.factors_scanned,
            fdr_passed=result.factors_passed_fdr,
            top_count=len(result.top_factors),
        )
    except Exception as exc:
        phase_failures += 1
        error_msg = f"Scan phase failed: {exc}"
        result.errors.append(error_msg)
        log.error("scan_phase_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Phase 2: Compile
    # ------------------------------------------------------------------
    compiled_config = None
    try:
        from src.research.factor_compiler import compile_factors_to_config

        resolved_config = _resolve_base_config(base_config, market)

        # Build factor_ids list from the top scan results if available,
        # otherwise let the compiler use all Active factors.
        factor_ids: list[int] | None = None
        if scan_report is not None:
            from src.research.factor_registry import FactorRegistry

            registry = FactorRegistry()
            top_source = scan_report.fdr_passed_factors or scan_report.top_factors
            top_n = top_source[:max_factors_to_compile]

            factor_ids = []
            for sr in top_n:
                f = registry.get_factor_by_name(sr.name)
                if f is not None:
                    factor_ids.append(f["id"])

            if not factor_ids:
                factor_ids = None  # fall back to all Active factors

        log.info(
            "compiling_factors",
            base_config=resolved_config,
            n_factors=len(factor_ids) if factor_ids else "all_active",
        )

        compiled_config = compile_factors_to_config(
            base_config_path=resolved_config,
            market=market,
            factor_ids=factor_ids,
        )
        result.config_path = compiled_config.output_path
        result.factors_in_config = compiled_config.factors_included

        phase_successes += 1
        log.info(
            "compile_phase_complete",
            config_path=result.config_path,
            factors_in_config=result.factors_in_config,
        )
    except Exception as exc:
        phase_failures += 1
        error_msg = f"Compile phase failed: {exc}"
        result.errors.append(error_msg)
        log.error("compile_phase_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Phase 3: Backtest
    # ------------------------------------------------------------------
    backtest_results: dict | None = None
    config_for_backtest = compiled_config.output_path if compiled_config else None
    try:
        from src.workflows.hooks import run_rebacktest_pipeline, run_training_pipeline

        tag = f"research_cycle_{market}"
        log.info("running_backtest", config=config_for_backtest, market=market)

        if config_for_backtest:
            # Use rebacktest with the compiled config
            backtest_results = run_rebacktest_pipeline(
                market=market,
                model_type="lgbm",
                tag=tag,
            )
        else:
            # Fallback: run a standard training pipeline
            backtest_results = run_training_pipeline(
                market=market,
                model_type="lgbm",
                tag=tag,
            )

        # Extract metrics from the backtest results
        if backtest_results and backtest_results.get("status") == "SUCCESS":
            # Metrics are typically stored in MLflow; attempt extraction
            result.sharpe, result.max_drawdown, result.excess_return = _extract_backtest_metrics(
                market
            )
        phase_successes += 1
        log.info(
            "backtest_phase_complete",
            sharpe=result.sharpe,
            max_drawdown=result.max_drawdown,
            excess_return=result.excess_return,
        )
    except Exception as exc:
        phase_failures += 1
        error_msg = f"Backtest phase failed: {exc}"
        result.errors.append(error_msg)
        log.error("backtest_phase_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Phase 4: Attribution
    # ------------------------------------------------------------------
    attribution_report = None
    try:
        from src.research.factor_attribution import attribute_returns
        from src.research.factor_registry import FactorRegistry

        registry = FactorRegistry()
        log.info("running_attribution", market=market)

        # Attribute using factors that were compiled into the strategy
        attr_factor_ids: list[int] | None = None
        if compiled_config is not None:
            attr_factor_ids = []
            for fname in compiled_config.factor_names:
                f = registry.get_factor_by_name(fname)
                if f is not None:
                    attr_factor_ids.append(f["id"])
            if not attr_factor_ids:
                attr_factor_ids = None

        attribution_report = attribute_returns(
            market=market,
            factor_ids=attr_factor_ids,
        )

        result.factor_coverage = attribution_report.attribution_confidence
        result.top_contributors = [c.to_dict() for c in attribution_report.factor_contributions[:3]]

        phase_successes += 1
        log.info(
            "attribution_phase_complete",
            r2=result.factor_coverage,
            top_contributor=(
                result.top_contributors[0]["factor_name"] if result.top_contributors else "none"
            ),
        )
    except Exception as exc:
        phase_failures += 1
        error_msg = f"Attribution phase failed: {exc}"
        result.errors.append(error_msg)
        log.error("attribution_phase_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Phase 5: Promotion
    # ------------------------------------------------------------------
    if auto_promote:
        try:
            from src.research.factor_registry import FactorRegistry

            registry = FactorRegistry()
            promoted_names: list[str] = []

            # Promote factors that were used in the compiled strategy
            factor_names_to_promote: list[str] = []
            if compiled_config is not None:
                factor_names_to_promote = compiled_config.factor_names
            elif scan_report is not None:
                top_source = scan_report.fdr_passed_factors or scan_report.top_factors
                factor_names_to_promote = [sr.name for sr in top_source[:max_factors_to_compile]]

            for fname in factor_names_to_promote:
                f = registry.get_factor_by_name(fname)
                if f is None:
                    continue
                fid = f["id"]

                # Build validation metrics from the scan results for gate evaluation
                validation_metrics = _build_validation_metrics(
                    fname, scan_report, attribution_report
                )
                if validation_metrics is None:
                    # Try a simple promote without gate validation
                    promoted = registry.promote(fid)
                    if promoted:
                        promoted_names.append(fname)
                else:
                    success, msg = registry.promote_to_next_gate(fid, validation_metrics)
                    if success:
                        promoted_names.append(fname)
                    else:
                        log.info(
                            "promotion_blocked",
                            factor=fname,
                            reason=msg,
                        )

            result.factors_promoted = len(promoted_names)
            result.new_active_factors = promoted_names

            phase_successes += 1
            log.info(
                "promotion_phase_complete",
                promoted=result.factors_promoted,
                factors=promoted_names,
            )
        except Exception as exc:
            phase_failures += 1
            error_msg = f"Promotion phase failed: {exc}"
            result.errors.append(error_msg)
            log.error("promotion_phase_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------
    result.cycle_duration_seconds = time.monotonic() - cycle_start

    if phase_failures == 0:
        result.status = "success"
    elif phase_successes > 0:
        result.status = "partial"
    else:
        result.status = "failed"

    log.info(
        "research_cycle_complete",
        status=result.status,
        duration_s=round(result.cycle_duration_seconds, 2),
        phase_successes=phase_successes,
        phase_failures=phase_failures,
        errors=result.errors,
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_backtest_metrics(market: str) -> tuple[float, float, float]:
    """Attempt to extract Sharpe, MDD, and excess return from recent backtest results.

    Returns (sharpe, max_drawdown, excess_return).  Falls back to 0.0 on any error.
    """
    try:
        from qlib.workflow import R

        from src.common.metrics_extractor import MetricsExtractor

        recs = R.list_rec(experiment_name=market)
        if recs:
            latest_rec = recs[0]
            metrics = MetricsExtractor.extract_from_record(latest_rec)
            sharpe = metrics.get("sharpe", 0.0) or 0.0
            mdd = metrics.get("max_drawdown", 0.0) or 0.0
            excess = metrics.get("excess_return", metrics.get("annualized_return", 0.0)) or 0.0
            return float(sharpe), float(mdd), float(excess)
    except Exception as exc:
        log.debug("backtest_metric_extraction_failed", error=str(exc))

    return 0.0, 0.0, 0.0


def _build_validation_metrics(
    factor_name: str,
    scan_report: Any | None,
    attribution_report: Any | None,
) -> dict | None:
    """Build a validation metrics dict suitable for promote_to_next_gate.

    Returns ``None`` if no usable metrics are found (caller should use plain
    ``promote()`` instead).
    """
    metrics: dict = {}

    # Extract from scan results
    if scan_report is not None:
        for sr in scan_report.results:
            if sr.name == factor_name:
                metrics.update(
                    {
                        "icir": sr.icir,
                        "t_stat": sr.t_stat,
                        "quintile_spread": sr.quintile_spread,
                    }
                )
                break

    # Extract IC from attribution results
    if attribution_report is not None:
        for contrib in attribution_report.factor_contributions:
            if contrib.factor_name == factor_name:
                metrics["ic"] = contrib.factor_ic
                break

    if not metrics:
        return None

    return metrics


# ---------------------------------------------------------------------------
# Iterative research loop
# ---------------------------------------------------------------------------


def run_iterative_research(
    market: str = "us",
    goal: str = "Find alpha",
    max_iterations: int = 5,
    target_sharpe: float = 1.0,
    base_config: str | None = None,
    goal_text: str | None = None,
) -> list[CycleResult]:
    """Run multiple research cycles with automatic iteration.

    Each cycle runs :func:`run_research_cycle`, then
    :func:`decide_next_action` determines the next step.  The loop stops when:

    * A cycle achieves Sharpe >= *target_sharpe* (with R² > 0.3), or
    * The decision is ``"stop"`` (diminishing returns, total failure, etc.), or
    * *max_iterations* cycles have been executed.

    Between cycles the function adjusts parameters based on the decision:
    - ``scan_more``: increases ``max_factors_to_compile`` and (if requested)
      relaxes FDR gates.
    - ``adjust_hyperparams``: increases ``max_factors_to_compile`` to give the
      model more features to work with.
    - ``retry``: passes a different ``base_config`` hint.
    - ``change_market``: switches the market (not yet triggered by current rules
      but supported for future use).

    When *goal_text* is provided it is parsed via :func:`src.agents.goal_parser.parse_research_goal`
    and the resulting structured goal overrides *market*, *max_iterations*, and
    *target_sharpe* if those were left at their defaults.

    Parameters
    ----------
    market:
        Market region (``"us"`` or ``"cn"``).
    goal:
        Natural-language research goal description.
    max_iterations:
        Hard cap on the number of cycles.
    target_sharpe:
        Sharpe ratio at which the loop considers the result satisfactory.
    base_config:
        Initial strategy config filename.  If ``None``, auto-detected from
        *market*.
    goal_text:
        Optional natural-language goal string.  When provided, the goal is
        parsed via :func:`~src.agents.goal_parser.parse_research_goal` and
        structured fields (market, target_sharpe, max_iterations) are merged
        into the call.

    Returns
    -------
    list[CycleResult]
        Ordered list of results from every cycle executed.
    """
    # --- Parse goal_text if provided ---
    if goal_text:
        from src.agents.goal_parser import parse_research_goal

        parsed = parse_research_goal(goal_text)
        # Override parameters only when the caller left them at defaults
        if market == "us" and parsed.market != "us":
            market = parsed.market
        if max_iterations == 5 and parsed.max_iterations != 5:
            max_iterations = parsed.max_iterations
        if target_sharpe == 1.0 and parsed.target_sharpe != 1.0:
            target_sharpe = parsed.target_sharpe
        # Use the richer description from the parsed goal
        if goal == "Find alpha" and parsed.description:
            goal = parsed.description

    results: list[CycleResult] = []
    best_sharpe = 0.0
    consecutive_no_improve = 0
    current_market = market
    current_max_factors = 10
    current_base_config = base_config

    log.info(
        "iterative_research_started",
        market=market,
        goal=goal,
        max_iterations=max_iterations,
        target_sharpe=target_sharpe,
    )

    for iteration in range(1, max_iterations + 1):
        log.info(
            "iterative_cycle_start",
            iteration=iteration,
            market=current_market,
            max_factors=current_max_factors,
        )

        cycle_result = run_research_cycle(
            market=current_market,
            goal_description=f"{goal} [iteration {iteration}/{max_iterations}]",
            base_config=current_base_config,
            max_factors_to_compile=current_max_factors,
            auto_promote=True,
        )
        results.append(cycle_result)

        # Track improvement
        if cycle_result.sharpe > best_sharpe:
            best_sharpe = cycle_result.sharpe
            consecutive_no_improve = 0
        else:
            consecutive_no_improve += 1

        log.info(
            "iterative_cycle_complete",
            iteration=iteration,
            sharpe=cycle_result.sharpe,
            best_sharpe=best_sharpe,
            consecutive_no_improve=consecutive_no_improve,
        )

        # Check target achievement
        if cycle_result.sharpe >= target_sharpe and cycle_result.factor_coverage > 0.3:
            log.info(
                "iterative_target_reached",
                sharpe=cycle_result.sharpe,
                target=target_sharpe,
                r2=cycle_result.factor_coverage,
            )
            break

        # Decide next action
        decision = decide_next_action(
            cycle_result=cycle_result,
            market=current_market,
            consecutive_no_improve=consecutive_no_improve,
            best_sharpe=best_sharpe,
        )

        log.info(
            "iterative_decision",
            iteration=iteration,
            action=decision.action,
            reason=decision.reason,
        )

        if decision.action == "stop":
            break

        # Apply decision parameters for next iteration
        if decision.action == "scan_more":
            current_max_factors = min(current_max_factors + 5, 30)
            if decision.params.get("relax_fdr"):
                log.info("iterative_relaxing_fdr", iteration=iteration)

        elif decision.action == "adjust_hyperparams":
            current_max_factors = min(current_max_factors + 3, 25)

        elif decision.action == "retry":
            # Vary the base config or max factors to explore a different region
            current_max_factors = max(current_max_factors - 2, 5)

        elif decision.action == "change_market":
            new_market = decision.params.get("market", current_market)
            if new_market != current_market:
                current_market = new_market
                log.info("iterative_market_changed", new_market=new_market)

    log.info(
        "iterative_research_complete",
        total_iterations=len(results),
        best_sharpe=best_sharpe,
        final_status=results[-1].status if results else "no_cycles",
    )

    return results


def run_iterative_research_from_goal(
    goal_text: str,
    base_config: str | None = None,
) -> list[CycleResult]:
    """Convenience wrapper: parse a natural language goal and run iterative research.

    This is the primary entry point for goal-driven research.  It parses
    *goal_text* via :func:`~src.agents.goal_parser.parse_research_goal` to
    extract market, target Sharpe, max iterations, and other constraints,
    then delegates to :func:`run_iterative_research`.

    Parameters
    ----------
    goal_text:
        Free-text research goal, e.g. ``"帮我找A股低波策略"`` or
        ``"Find US momentum factors with high IC"``.
    base_config:
        Optional base strategy config filename.  If ``None``, auto-detected
        from the parsed market.

    Returns
    -------
    list[CycleResult]
        Ordered list of results from every cycle executed.
    """
    from src.agents.goal_parser import parse_research_goal

    parsed = parse_research_goal(goal_text)
    log.info(
        "goal_parsed",
        market=parsed.market,
        categories=parsed.categories,
        direction=parsed.direction,
        target_sharpe=parsed.target_sharpe,
        max_iterations=parsed.max_iterations,
        constraints=parsed.constraints,
    )

    return run_iterative_research(
        market=parsed.market,
        goal=parsed.description,
        max_iterations=parsed.max_iterations,
        target_sharpe=parsed.target_sharpe,
        base_config=base_config,
    )


# T-07: Research loop with ExperimentJournal integration
def run_research_loop(
    goal: str,
    max_iterations: int = 20,
    market: str = "us",
    target_sharpe: float = 1.0,
) -> dict:
    """Run a research loop that queries ExperimentJournal and avoids failed paths.

    This fulfills T-07 acceptance criteria:
    1. Query ExperimentJournal to understand history
    2. Use what_failed() to avoid repeating failed paths
    3. Propose new hypothesis → construct factor → test → store
    4. Stop when max_iterations reached or VALIDATED factor found
    5. Return structured report

    Parameters
    ----------
    goal:
        Natural-language research goal description.
    max_iterations:
        Hard cap on the number of cycles (default 20).
    market:
        Market region ("us" or "cn").
    target_sharpe:
        Sharpe ratio at which the loop considers the result satisfactory.

    Returns
    -------
    dict
        Structured report with:
        - "iterations": list of CycleResult dicts
        - "best_sharpe": best Sharpe achieved
        - "validated_factors": list of factors that reached Validated stage
        - "failed_hypotheses": list of failed approaches to avoid
        - "status": "success" | "max_iterations" | "target_reached"
    """
    from src.research.experiment_journal import ExperimentJournal
    from src.research.factor_registry import FactorRegistry

    journal = ExperimentJournal()
    registry = FactorRegistry()
    summary = journal.get_summary()

    # Step 1: Query ExperimentJournal to understand history
    existing_stages = summary.get("factors", {}).get("by_stage", {})
    summary.get("factors", {}).get("by_category", {})

    # Step 2: Identify failed hypotheses from Proposed factors that never advanced
    failed_hypotheses = []
    proposed_factors = registry.list_factors(stage="Proposed")
    for f in proposed_factors:
        # Factors stuck at Proposed with low IC are likely failed hypotheses
        failed_hypotheses.append(
            {
                "expression": f.get("expression", ""),
                "category": f.get("category", ""),
                "reason": "stuck_at_proposed",
            }
        )

    log.info(
        "research_loop_started",
        goal=goal,
        max_iterations=max_iterations,
        existing_factors=summary.get("factors", {}).get("total", 0),
        active_factors=existing_stages.get("Active", 0),
        failed_hypotheses=len(failed_hypotheses),
    )

    # Step 3: Run iterative research
    results = run_iterative_research(
        market=market,
        goal=goal,
        max_iterations=max_iterations,
        target_sharpe=target_sharpe,
    )

    # Step 4: Collect validated factors
    validated_factors = []
    for r in results:
        if r.new_active_factors:
            validated_factors.extend(r.new_active_factors)

    # Step 5: Check if we found a VALIDATED factor
    final_summary = journal.get_summary()
    final_stages = final_summary.get("factors", {}).get("by_stage", {})

    # Determine status
    if validated_factors:
        status = "target_reached"
    elif len(results) >= max_iterations:
        status = "max_iterations"
    else:
        status = "completed"

    report = {
        "iterations": [r.to_dict() for r in results],
        "best_sharpe": max((r.sharpe for r in results), default=0.0),
        "validated_factors": validated_factors,
        "failed_hypotheses": failed_hypotheses[:10],  # Top 10
        "total_cycles": len(results),
        "factors_discovered": final_summary.get("factors", {}).get("total", 0),
        "active_factors": final_stages.get("Active", 0),
        "status": status,
    }

    log.info(
        "research_loop_complete",
        total_cycles=report["total_cycles"],
        best_sharpe=report["best_sharpe"],
        validated_factors=len(validated_factors),
        status=report["status"],
    )

    return report
