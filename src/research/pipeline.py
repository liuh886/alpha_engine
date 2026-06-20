"""Research Pipeline — Observable research workflow with state tracking.

This module provides a unified ResearchRun that tracks each step of the
research process: factor scan → compile → backtest → attribution → promote.

Each step has:
- Status (pending/running/completed/failed)
- Input parameters
- Output artifacts
- Error messages
- Timing information
- Rerun capability

Usage:
    run = ResearchRun(market="cn", goal="Find alpha factors")
    run.start()

    with run.step("factor_scan") as step:
        factors = scan_factors(...)
        step.output = {"factors_found": len(factors)}

    with run.step("backtest") as step:
        result = run_backtest(...)
        step.output = {"ic": result.ic, "sharpe": result.sharpe}

    run.complete(recommendation="Deploy model X")
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

__all__ = ["ResearchRun", "StepStatus", "Step"]


class StepStatus(str, Enum):
    """Status of a research pipeline step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Step:
    """A single step in the research pipeline.

    Attributes
    ----------
    name : str
        Step identifier (e.g., "factor_scan", "backtest").
    status : StepStatus
        Current status of the step.
    input : dict
        Input parameters for this step.
    output : dict
        Output artifacts from this step.
    error : str | None
        Error message if step failed.
    started_at : str | None
        ISO timestamp when step started.
    completed_at : str | None
        ISO timestamp when step completed.
    duration_seconds : float
        How long the step took.
    """

    name: str
    status: StepStatus = StepStatus.PENDING
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
        }


@dataclass
class ResearchRun:
    """An observable research pipeline run.

    Tracks the complete research lifecycle from factor discovery
    to model deployment recommendation.

    Attributes
    ----------
    run_id : str
        Unique identifier for this run.
    market : str
        Target market (cn/us).
    goal : str
        Research goal description.
    status : StepStatus
        Overall run status.
    steps : list[Step]
        Ordered list of pipeline steps.
    recommendation : str | None
        Final recommendation from this run.
    created_at : str
        ISO timestamp when run was created.
    completed_at : str | None
        ISO timestamp when run completed.
    """

    run_id: str = ""
    market: str = "cn"
    goal: str = ""
    status: StepStatus = StepStatus.PENDING
    steps: list[Step] = field(default_factory=list)
    recommendation: str | None = None
    created_at: str = ""
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.run_id:
            self.run_id = f"rr_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def start(self) -> None:
        """Mark the run as started."""
        self.status = StepStatus.RUNNING
        logger.info("research_run_started", run_id=self.run_id, market=self.market, goal=self.goal)

    @contextmanager
    def step(self, name: str, input_params: dict[str, Any] | None = None):
        """Context manager for executing a pipeline step.

        Usage:
            with run.step("backtest", {"model": "lgbm"}) as step:
                result = do_backtest()
                step.output = {"ic": result.ic}
        """
        step = Step(name=name, input=input_params or {})
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now().isoformat()
        self.steps.append(step)

        logger.info("step_started", run_id=self.run_id, step=name)

        try:
            yield step
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.now().isoformat()
            step.duration_seconds = (
                datetime.fromisoformat(step.completed_at) -
                datetime.fromisoformat(step.started_at)
            ).total_seconds()
            logger.info(
                "step_completed",
                run_id=self.run_id,
                step=name,
                duration=step.duration_seconds,
            )
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = f"{type(exc).__name__}: {exc}"
            step.completed_at = datetime.now().isoformat()
            step.duration_seconds = (
                datetime.fromisoformat(step.completed_at) -
                datetime.fromisoformat(step.started_at)
            ).total_seconds()
            logger.error(
                "step_failed",
                run_id=self.run_id,
                step=name,
                error=step.error,
            )
            raise

    def skip_step(self, name: str, reason: str) -> None:
        """Mark a step as skipped."""
        step = Step(name=name, status=StepStatus.SKIPPED, error=reason)
        self.steps.append(step)
        logger.info("step_skipped", run_id=self.run_id, step=name, reason=reason)

    def complete(self, recommendation: str | None = None) -> None:
        """Mark the run as completed."""
        self.status = StepStatus.COMPLETED
        self.recommendation = recommendation
        self.completed_at = datetime.now().isoformat()
        logger.info(
            "research_run_completed",
            run_id=self.run_id,
            recommendation=recommendation,
            n_steps=len(self.steps),
            n_failed=sum(1 for s in self.steps if s.status == StepStatus.FAILED),
        )

    def fail(self, reason: str) -> None:
        """Mark the run as failed."""
        self.status = StepStatus.FAILED
        self.recommendation = f"FAILED: {reason}"
        self.completed_at = datetime.now().isoformat()
        logger.error("research_run_failed", run_id=self.run_id, reason=reason)

    @property
    def is_complete(self) -> bool:
        return self.status == StepStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self.status == StepStatus.FAILED

    @property
    def failed_steps(self) -> list[Step]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    @property
    def completed_steps(self) -> list[Step]:
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]

    @property
    def total_duration(self) -> float:
        return sum(s.duration_seconds for s in self.steps)

    def get_step(self, name: str) -> Step | None:
        """Get a step by name."""
        for s in self.steps:
            if s.name == name:
                return s
        return None

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of this run."""
        return {
            "run_id": self.run_id,
            "market": self.market,
            "goal": self.goal,
            "status": self.status.value,
            "recommendation": self.recommendation,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "total_duration_seconds": round(self.total_duration, 2),
            "steps": [s.to_dict() for s in self.steps],
            "n_steps": len(self.steps),
            "n_completed": len(self.completed_steps),
            "n_failed": len(self.failed_steps),
        }

    def save(self, path: Path | str | None = None) -> Path:
        """Save run summary to JSON file."""
        if path is None:
            from src.common.paths import ARTIFACTS_DIR
            path = ARTIFACTS_DIR / "research_runs" / f"{self.run_id}.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.get_summary(), f, indent=2)
        logger.info("research_run_saved", path=str(path))
        return path

    @classmethod
    def load(cls, path: Path | str) -> ResearchRun:
        """Load a run from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        run = cls(
            run_id=data["run_id"],
            market=data["market"],
            goal=data["goal"],
        )
        run.status = StepStatus(data["status"])
        run.recommendation = data.get("recommendation")
        run.created_at = data["created_at"]
        run.completed_at = data.get("completed_at")
        for step_data in data.get("steps", []):
            step = Step(
                name=step_data["name"],
                status=StepStatus(step_data["status"]),
                input=step_data.get("input", {}),
                output=step_data.get("output", {}),
                error=step_data.get("error"),
                started_at=step_data.get("started_at"),
                completed_at=step_data.get("completed_at"),
                duration_seconds=step_data.get("duration_seconds", 0),
            )
            run.steps.append(step)
        return run


# ---------------------------------------------------------------------------
# Standard pipeline steps
# ---------------------------------------------------------------------------


def run_research_pipeline(
    market: str = "cn",
    goal: str = "Find alpha factors",
    model_type: str = "lgbm",
    existing_run: ResearchRun | None = None,
    _train_fn: Any | None = None,
) -> ResearchRun:
    """Execute the standard research pipeline.

    Steps:
    1. Factor scan — discover candidate factors
    2. Compile — compile profile to workflow config
    3. Train — train model with selected features
    4. Walk-forward — validate with expanding window
    5. Backtest — full backtest with trading simulation
    6. Attribution — decompose returns by factor
    7. Promote — recommend deployment if metrics pass

    Parameters
    ----------
    existing_run : ResearchRun, optional
        If provided, use this run instead of creating a new one.
        This allows the API to track the same run throughout.
    _train_fn : callable, optional
        Injected training function. Defaults to ``run_training_pipeline``
        from ``src.workflows.hooks``.  Injected by the legacy adapter
        (``workflow_legacy.py``) so that the research pipeline does not
        directly import hooks when called through the proper seam.

    .. note::
        This function is a **legacy adapter bridge**.  Direct callers
        (API, scripts) may omit ``_train_fn`` and get the hooks fallback.
        The canonical seam is through ``LegacyResearchPipelineExecutor``
        in ``workflow_legacy.py``, which always injects the function.

    Returns
    -------
    ResearchRun
        Completed run with all step outputs.
    """
    run = existing_run or ResearchRun(market=market, goal=goal)
    if run.status != StepStatus.RUNNING:
        run.start()
    run.save()  # Persist state after each major step

    # Step 1: Factor scan
    with run.step("factor_scan", {"market": market}) as step:
        from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

        registry = FactorRegistry()
        active = registry.list_factors(stage=STAGE_ACTIVE)
        step.output = {
            "active_factors": len(active),
            "factor_names": [f["name"] for f in active[:10]],
        }
    run.save()

    # Step 2: Compile profile
    with run.step("compile", {"market": market, "model_type": model_type}) as step:
        from src.workflows.profile_compiler import compile_strategy_profile

        profile_path = f"configs/strategy_profile_{market}.json"
        config_path = compile_strategy_profile(market=market, profile_path=profile_path)
        step.output = {"config_path": str(config_path)}
    run.save()

    # Step 3: Train model
    with run.step("train", {"market": market, "model_type": model_type}) as step:
        train = _train_fn
        if train is None:
            from src.workflows.hooks import run_training_pipeline

            train = run_training_pipeline
        result = train(market=market, model_type=model_type, tag=f"pipeline_{run.run_id}")
        step.output = result
    run.save()

    # Step 4: Walk-forward validation
    with run.step("walk_forward", {"market": market, "model_type": model_type}) as step:
        from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
        from src.research.walk_forward import walk_forward_validate

        cfg = build_qlib_init_cfg(None, market=market)
        safe_qlib_init(cfg)

        wf_result = walk_forward_validate(
            market=market,
            model_type=model_type,
            train_start="2021-01-01",
            train_end="2025-01-01",
            test_window_months=6,
            step_months=3,
        )
        step.output = {
            "mean_ic": wf_result.mean_ic,
            "ic_ir": wf_result.ic_ir,
            "consistency": wf_result.consistency_score,
            "n_splits": len(wf_result.splits),
        }
    run.save()

    # Step 5: Backtest — extract performance from walk-forward results
    with run.step("backtest", {"market": market}) as step:
        wf_dir = Path("artifacts/walk_forward")
        wf_files = sorted(wf_dir.glob(f"{market}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        if wf_files:
            with open(wf_files[0]) as f:
                wf_data = json.load(f)

            # Extract per-split performance metrics
            split_metrics = []
            for split in wf_data.get("splits", []):
                if split.get("status") == "success":
                    split_metrics.append({
                        "split_id": split["split_id"],
                        "train_end": split.get("train_end"),
                        "test_start": split.get("test_start"),
                        "test_end": split.get("test_end"),
                        "ic": split.get("ic"),
                        "rank_ic": split.get("rank_ic"),
                        "sharpe": split.get("sharpe"),
                        "max_drawdown": split.get("max_drawdown"),
                        "annual_return": split.get("annual_return"),
                    })

            # Aggregate performance
            ics = [s["ic"] for s in split_metrics if s.get("ic") is not None]
            sharpes = [s["sharpe"] for s in split_metrics if s.get("sharpe") is not None]
            returns = [s["annual_return"] for s in split_metrics if s.get("annual_return") is not None]
            drawdowns = [s["max_drawdown"] for s in split_metrics if s.get("max_drawdown") is not None]

            step.output = {
                "source": str(wf_files[0]),
                "n_splits": len(split_metrics),
                "mean_ic": float(np.mean(ics)) if ics else None,
                "std_ic": float(np.std(ics)) if ics else None,
                "ic_ir": float(np.mean(ics) / np.std(ics)) if ics and np.std(ics) > 1e-10 else None,
                "mean_sharpe": float(np.mean(sharpes)) if sharpes else None,
                "mean_annual_return": float(np.mean(returns)) if returns else None,
                "max_drawdown": float(np.min(drawdowns)) if drawdowns else None,
                "consistency": sum(1 for ic in ics if ic > 0) / len(ics) if ics else 0,
                "split_details": split_metrics,
                "backtest_status": "from_walkforward",
            }
        else:
            step.output = {"backtest_status": "no_walkforward_results"}
    run.save()

    # Step 6: Attribution — decompose factor contributions
    with run.step("attribution", {"market": market}) as step:
        try:
            from src.research.factor_attribution import attribute_returns
            from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry

            registry = FactorRegistry()
            active_factors = registry.list_factors(stage=STAGE_ACTIVE)

            if active_factors:
                # Get factor IDs for active factors with expressions
                factor_ids = [f["id"] for f in active_factors[:10] if f.get("expression")]

                if factor_ids:
                    report = attribute_returns(
                        market=market,
                        start_date="2025-01-01",
                        end_date="2026-06-18",
                        factor_ids=factor_ids,
                    )
                    step.output = {
                        "attribution_status": "factor_model",
                        "total_return": report.total_return,
                        "excess_return": report.excess_return,
                        "factor_coverage": report.factor_coverage,
                        "attribution_confidence": report.attribution_confidence,
                        "n_factors": len(report.factor_contributions),
                        "top_contributions": [
                            {
                                "factor": fc.factor_name,
                                "return_contribution_pct": round(fc.return_contribution_pct, 2),
                                "risk_contribution_pct": round(fc.risk_contribution_pct, 2),
                                "ic": round(fc.factor_ic, 4),
                            }
                            for fc in sorted(
                                report.factor_contributions,
                                key=lambda x: abs(x.return_contribution_pct),
                                reverse=True,
                            )[:5]
                        ],
                    }
                else:
                    step.output = {"attribution_status": "no_factor_expressions"}
            else:
                step.output = {"attribution_status": "no_active_factors"}
        except Exception as e:
            # Fallback to walk-forward IC-based attribution
            logger.warning("factor_attribution_failed", error=str(e))
            wf_dir = Path("artifacts/walk_forward")
            wf_files = sorted(wf_dir.glob(f"{market}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if wf_files:
                with open(wf_files[0]) as f:
                    wf_data = json.load(f)
                split_ics = [
                    {"split_id": s["split_id"], "ic": s["ic"], "rank_ic": s.get("rank_ic")}
                    for s in wf_data.get("splits", [])
                    if s.get("status") == "success" and s.get("ic") is not None
                ]
                step.output = {
                    "attribution_status": "fallback_walkforward",
                    "mean_ic": wf_data.get("mean_ic", 0),
                    "ic_ir": wf_data.get("ic_ir", 0),
                    "n_splits": len(split_ics),
                    "error": str(e)[:200],
                }
            else:
                step.output = {"attribution_status": "failed", "error": str(e)[:200]}
    run.save()

    # Step 7: Promote recommendation
    with run.step("promote") as step:
        wf_step = run.get_step("walk_forward")
        if wf_step and wf_step.status == StepStatus.COMPLETED:
            ic = wf_step.output.get("mean_ic", 0)
            if ic > 0.1:
                step.output = {"recommendation": "DEPLOY", "reason": f"IC={ic:.4f} > 0.1 threshold"}
                run.complete(recommendation=f"Deploy model: IC={ic:.4f}")
            else:
                step.output = {"recommendation": "ITERATE", "reason": f"IC={ic:.4f} < 0.1 threshold"}
                run.complete(recommendation=f"Iterate: IC={ic:.4f} below threshold")
        else:
            step.output = {"recommendation": "FAILED", "reason": "Walk-forward did not complete"}
            run.fail("Walk-forward validation failed")
    run.save()

    # Save run
    run.save()
    return run
