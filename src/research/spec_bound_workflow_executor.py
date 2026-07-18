"""Spec-bound research workflow executor.

Default runtime adapter for the canonical ResearchWorkflow.  Maps market to a
fixed ResearchParadigmSpec, executes the existing spec-bound research path once,
and translates the identity-proven results into the canonical ResearchStep sequence.

``LegacyResearchPipelineExecutor`` remains available as an explicit compatibility
adapter but is no longer the default.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.common.runtime_settings import PROJECT_ROOT
from src.research.paradigm import ResearchParadigmSpec
from src.research.spec_bound_execution import SpecBoundExecutor
from src.research.workflow_types import (
    ResearchStep,
    ResearchWorkflowRequest,
    StepResult,
    WorkflowStatus,
    utc_now,
)

# -- Fixed spec identity mapping ------------------------------------------------

_MARKET_SPEC_MAP: dict[str, str] = {
    "cn": "configs/research_paradigms/cn_10d_csi300_baseline.yaml",
    "us": "configs/research_paradigms/us_10d_qqq_baseline.yaml",
}

_SAFE_SPEC_DIR: Path = (PROJECT_ROOT / "configs" / "research_paradigms").resolve()

# Callable that takes a ResearchParadigmSpec and returns the result dict from
# execute_spec_bound_research.
SpecBoundRunner = Callable[[ResearchParadigmSpec], dict[str, Any]]


# -- Spec resolution (public so tests can exercise resolution in isolation) -----


def resolve_spec(request: ResearchWorkflowRequest) -> ResearchParadigmSpec:
    """Resolve the fixed spec for *request.market*, with optional safe override.

    ``request.metadata['spec_path']`` overrides the market-default mapping but is
    only accepted when the resolved path lives under ``configs/research_paradigms``
    **and** the loaded spec's ``market`` matches ``request.market``.
    """
    spec_path_override = (request.metadata or {}).get("spec_path")

    if spec_path_override:
        resolved = _resolve_safe_override_path(str(spec_path_override))
    else:
        market = str(request.market).lower()
        if market not in _MARKET_SPEC_MAP:
            raise ValueError(
                f"Unsupported market {request.market!r}. "
                f"Supported markets: {sorted(_MARKET_SPEC_MAP)}"
            )
        resolved = str(PROJECT_ROOT / _MARKET_SPEC_MAP[market])

    spec = ResearchParadigmSpec.from_yaml(resolved)

    if spec.market != str(request.market).lower():
        raise ValueError(
            f"Resolved spec market {spec.market!r} does not match "
            f"request market {request.market!r}. Spec: {resolved}"
        )

    return spec


def _resolve_safe_override_path(spec_path: str) -> str:
    raw = Path(spec_path)
    if not raw.is_absolute():
        raw = PROJECT_ROOT / raw
    resolved = raw.resolve()

    # Traversal / out-of-scope protection
    try:
        resolved.relative_to(_SAFE_SPEC_DIR)
    except ValueError:
        raise ValueError(
            f"Spec path {spec_path!r} resolves to {resolved!r} which is "
            f"outside the safe spec directory {_SAFE_SPEC_DIR!r}"
        )

    if not resolved.is_file():
        raise FileNotFoundError(f"Spec override file not found: {resolved}")

    return str(resolved)


# -- Executor ------------------------------------------------------------------


class SpecBoundResearchWorkflowExecutor:
    """Execute the spec-bound research path behind the ResearchWorkflow seam.

    The full spec-bound execution runs **once per workflow run** and the
    identity-proven results are translated into the canonical ``ResearchStep``
    sequence. Evidence-owning stages complete only when their required artifact
    reference exists; the ``PROMOTE`` step carries the canonical
    ``promotion_decision`` and nothing else.

    Heavy Qlib/data execution is injectable via *spec_bound_runner* so
    contract tests remain Qlib/data-free and deterministic.
    """

    def __init__(
        self,
        spec_bound_runner: SpecBoundRunner | None = None,
    ) -> None:
        self._spec_bound_runner = spec_bound_runner
        self._run_id: str | None = None
        self._requested_goal = ""
        self._spec_result: dict[str, Any] | None = None
        self._spec: ResearchParadigmSpec | None = None
        self._failure: Exception | None = None

    # -- ResearchWorkflowExecutor Protocol ---------------------------------

    def run_step(
        self,
        request: ResearchWorkflowRequest,
        step: ResearchStep,
    ) -> StepResult:
        if request.run_id != self._run_id:
            self._reset(request)
            self._execute(request)

        if self._failure is not None:
            return StepResult(
                step=step,
                status=WorkflowStatus.FAILED,
                error=f"{type(self._failure).__name__}: {self._failure}",
            )

        return self._step_result_for(step)

    # -- Internal ----------------------------------------------------------

    def _reset(self, request: ResearchWorkflowRequest) -> None:
        self._run_id = request.run_id
        self._requested_goal = request.goal
        self._spec_result = None
        self._spec = None
        self._failure = None

    def _execute(self, request: ResearchWorkflowRequest) -> None:
        try:
            spec = resolve_spec(request)
            self._spec = spec
            runner = self._spec_bound_runner or self._default_runner
            self._spec_result = runner(spec)
        except Exception as exc:
            self._failure = exc

    def _default_runner(self, spec: ResearchParadigmSpec) -> dict[str, Any]:
        """Production runner: execute with the appropriate market adapter."""
        from src.research.spec_bound_execution import execute_spec_bound_research

        adapter = _resolve_market_adapter(spec.market)
        return execute_spec_bound_research(spec, adapter)

    def _step_result_for(self, step: ResearchStep) -> StepResult:
        assert self._spec_result is not None
        assert self._spec is not None

        now = utc_now()
        run_status = str(self._spec_result.get("status", "failed"))

        if run_status == "skipped":
            return StepResult(
                step=step,
                status=WorkflowStatus.SKIPPED,
                output={
                    **self._base_output(),
                    "reason": str(
                        self._spec_result.get(
                            "skip_reason", "Spec-bound execution was skipped."
                        )
                    ),
                },
                started_at=now,
                completed_at=now,
            )

        if run_status != "passed":
            return StepResult(
                step=step,
                status=WorkflowStatus.FAILED,
                error=f"Spec-bound execution status was {run_status!r}",
                started_at=now,
                completed_at=now,
            )

        if not self._spec_result.get("contract_identity_verified") or not str(
            self._spec_result.get("declared_contract_sha256", "")
        ):
            return StepResult(
                step=step,
                status=WorkflowStatus.FAILED,
                error="Spec-bound execution did not prove contract identity.",
                started_at=now,
                completed_at=now,
            )

        if step is ResearchStep.PROMOTE:
            return self._promote_step_result(now)

        if step is ResearchStep.ATTRIBUTION:
            return StepResult(
                step=step,
                status=WorkflowStatus.SKIPPED,
                output={
                    **self._base_output(),
                    "reason": (
                        "The fixed-10D spec path does not produce a standalone "
                        "attribution artifact."
                    ),
                },
                started_at=now,
                completed_at=now,
            )

        step_output = self._build_step_output(step)
        required_output = {
            ResearchStep.TRAIN: "execution_identity",
            ResearchStep.WALK_FORWARD: "walk_forward_evidence",
            ResearchStep.BACKTEST: "metrics_summary",
        }.get(step)
        if required_output and not step_output.get(required_output):
            return StepResult(
                step=step,
                status=WorkflowStatus.FAILED,
                output=step_output,
                error=(
                    f"Spec-bound execution did not return required "
                    f"{required_output!r} evidence."
                ),
                started_at=now,
                completed_at=now,
            )
        return StepResult(
            step=step,
            status=WorkflowStatus.COMPLETED,
            output=step_output,
            started_at=now,
            completed_at=now,
        )

    def _promote_step_result(self, now: str) -> StepResult:
        """Emit only the canonical promotion_decision from spec-bound execution."""
        assert self._spec_result is not None
        promotion = self._spec_result.get("promotion_decision")

        if not isinstance(promotion, dict):
            return StepResult(
                step=ResearchStep.PROMOTE,
                status=WorkflowStatus.FAILED,
                error=(
                    "Spec-bound execution did not produce a valid "
                    "promotion_decision dict."
                ),
                started_at=now,
                completed_at=now,
            )

        return StepResult(
            step=ResearchStep.PROMOTE,
            status=WorkflowStatus.COMPLETED,
            output=dict(promotion),
            started_at=now,
            completed_at=now,
        )

    def _build_step_output(self, step: ResearchStep) -> dict[str, Any]:
        """Build step-level output metadata backed by spec-bound artifacts."""
        assert self._spec_result is not None
        assert self._spec is not None

        evidence = self._spec_result.get("evidence_paths", {}) or {}

        base = self._base_output()

        if step is ResearchStep.SCAN:
            return {
                **base,
                "stage": "scan",
                "benchmark": self._spec.benchmark,
                "universe_source": str(self._spec.universe.get("source", "")),
            }
        if step is ResearchStep.COMPILE:
            return {
                **base,
                "stage": "compile",
                "factor_library_source": str(
                    self._spec.factor_library.get("source", "")
                ),
            }
        if step is ResearchStep.TRAIN:
            return {
                **base,
                "stage": "train",
                "run_dir": str(self._spec_result.get("run_dir", "")),
                "execution_identity": evidence.get("execution_identity", ""),
            }
        if step is ResearchStep.WALK_FORWARD:
            return {
                **base,
                "stage": "walk_forward",
                "walk_forward_evidence": evidence.get("walk_forward_stability", ""),
            }
        if step is ResearchStep.BACKTEST:
            return {
                **base,
                "stage": "backtest",
                "metrics_summary": evidence.get("metrics_summary", ""),
            }
        return {**base, "stage": str(step.value)}

    def _base_output(self) -> dict[str, Any]:
        assert self._spec_result is not None
        assert self._spec is not None
        return {
            "resolved_spec_path": self._spec.spec_path,
            "experiment_id": self._spec.experiment_id,
            "market": self._spec.market,
            "contract_identity_verified": bool(
                self._spec_result.get("contract_identity_verified")
            ),
            "declared_contract_sha256": str(
                self._spec_result.get("declared_contract_sha256", "")
            ),
            "requested_goal": self._requested_goal,
            "goal_semantics": "audit_metadata_only",
        }


# -- Helpers -------------------------------------------------------------------


def _resolve_market_adapter(market: str) -> SpecBoundExecutor:
    """Lazy-import the correct execution adapter for *market*."""
    if market == "cn":
        from src.research.cn_qlib_execution_adapter import execute_cn_qlib_plan

        return execute_cn_qlib_plan
    elif market == "us":
        from src.research.us_qlib_execution_adapter import execute_us_qlib_plan

        return execute_us_qlib_plan
    raise ValueError(f"No spec-bound execution adapter for market {market!r}")
