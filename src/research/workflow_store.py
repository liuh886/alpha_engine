"""Filesystem store for canonical research workflow results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.research.workflow_types import (
    ResearchStep,
    ResearchWorkflowRequest,
    ResearchWorkflowResult,
    StepResult,
    WorkflowStatus,
)


class ResearchWorkflowStore:
    """Persist workflow summaries as JSON without owning execution semantics."""

    def __init__(self, artifacts_dir: str | Path | None = None) -> None:
        if artifacts_dir is None:
            from src.common.paths import ARTIFACTS_DIR

            artifacts_dir = ARTIFACTS_DIR
        self.artifacts_dir = Path(artifacts_dir)
        self.runs_dir = self.artifacts_dir / "research_workflows"

    def save(self, result: ResearchWorkflowResult) -> Path:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self.runs_dir / f"{result.run_id}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> ResearchWorkflowResult:
        path = self.runs_dir / f"{run_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._from_dict(data)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.runs_dir.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(
            self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append(data)
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> ResearchWorkflowResult:
        request_data = data["request"]
        request = ResearchWorkflowRequest(
            market=request_data.get("market", "cn"),
            goal=request_data.get("goal", "Find alpha factors"),
            model_type=request_data.get("model_type", "lgbm"),
            run_id=request_data.get("run_id"),
            requested_by=request_data.get("requested_by", "adapter"),
            metadata=request_data.get("metadata", {}),
        )
        steps = [
            StepResult(
                step=ResearchStep(step["step"]),
                status=WorkflowStatus(step["status"]),
                output=step.get("output", {}),
                error=step.get("error"),
                started_at=step.get("started_at"),
                completed_at=step.get("completed_at"),
            )
            for step in data.get("steps", [])
        ]
        return ResearchWorkflowResult(
            run_id=data["run_id"],
            request=request,
            status=WorkflowStatus(data.get("status", WorkflowStatus.PENDING.value)),
            steps=steps,
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            evidence_bundle_id=data.get("evidence_bundle_id"),
            warnings=data.get("warnings", []),
            promotion_decision=data.get("promotion_decision"),
        )
