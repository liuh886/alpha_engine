"""Shared runner behind the US/CN feature-quality validation CLIs.

The two market CLIs were near-identical copies (docstring, adapter import,
default spec, failure stage and market gate). Research semantics stay in the
YAML contracts and the market adapters; this module owns only the shared
prepare/execute/failure-record flow parameterized by market.
"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any, Literal

from src.research.cn_qlib_execution_adapter import (
    QlibCNExecutionRuntime,
    execute_cn_qlib_plan,
)
from src.research.paradigm import dry_run_paradigm, load_research_paradigm_spec
from src.research.research_artifacts import (
    build_research_run_paths,
    write_run_status,
)
from src.research.spec_bound_execution import execute_spec_bound_research
from src.research.us_qlib_execution_adapter import (
    QlibUSExecutionRuntime,
    execute_us_qlib_plan,
)

Market = Literal["us", "cn"]

_ADAPTERS = {
    "us": (QlibUSExecutionRuntime, execute_us_qlib_plan),
    "cn": (QlibCNExecutionRuntime, execute_cn_qlib_plan),
}


def record_unhandled_failure(
    *,
    root: Path,
    output_dir: str | Path | None,
    experiment_id: str,
    failed_stage: str,
    exc: Exception,
) -> None:
    """Write an auditable failure unless a more specific gate already did so."""
    paths = build_research_run_paths(
        root,
        experiment_id,
        output_dir=output_dir,
    )
    existing: dict[str, Any] = {}
    if paths.run_status.is_file():
        try:
            payload = json.loads(paths.run_status.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except (OSError, json.JSONDecodeError):
            existing = {}
    if existing.get("status") == "failed":
        return
    write_run_status(
        paths,
        experiment_id=experiment_id,
        status="failed",
        failed_stage=failed_stage,
        reason=f"{type(exc).__name__}: {exc}",
        extra={"exception_type": type(exc).__name__},
    )


def run_feature_quality_validation(
    root: Path,
    *,
    market: Market,
    script_name: str,
    spec_path: str | Path,
    output_dir: str | Path | None = None,
    provider_uri: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare and execute one market research spec without CLI-owned semantics."""
    runtime_cls, execute_plan = _ADAPTERS[market]
    spec_file = Path(spec_path)
    if not spec_file.is_absolute():
        spec_file = root / spec_file
    spec = load_research_paradigm_spec(spec_file)
    if spec.market != market:
        raise ValueError(f"{script_name} requires a {market.upper()} spec")

    dry_run_paradigm(spec, root=root, output_dir=output_dir)
    runtime = runtime_cls(provider_uri=provider_uri)
    executor = partial(execute_plan, runtime=runtime)
    try:
        return execute_spec_bound_research(
            spec,
            executor,
            root=root,
            output_dir=output_dir,
        )
    except Exception as exc:
        record_unhandled_failure(
            root=root,
            output_dir=output_dir,
            experiment_id=spec.experiment_id,
            failed_stage=f"{market}_qlib_execution",
            exc=exc,
        )
        raise
