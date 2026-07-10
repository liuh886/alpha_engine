"""Research-run artifact paths and fail-closed Qlib-free writers."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPERIMENT_SPEC_FILENAME = "experiment_spec.json"
RUN_STATUS_FILENAME = "run_status.json"
DATA_READINESS_FILENAME = "data_readiness.json"
UNIVERSE_REPORT_FILENAME = "universe_report.json"
FACTOR_MANIFEST_FILENAME = "factor_manifest.json"
CANDIDATE_MANIFEST_FILENAME = "candidate_manifest.json"
WALK_FORWARD_WINDOWS_FILENAME = "walk_forward_windows.json"
WALK_FORWARD_STABILITY_FILENAME = "walk_forward_stability.json"
MODEL_DECISION_PACK_FILENAME = "model_decision_pack.json"
MODEL_DECISION_MARKDOWN_FILENAME = "model_decision_pack.md"
SIGNALS_LATEST_FILENAME = "signals_latest.json"
TOP_BOTTOM_SIGNALS_CSV_FILENAME = "top_bottom_signals.csv"
METRICS_SUMMARY_FILENAME = "metrics_summary.json"
FRONTEND_PAYLOAD_FILENAME = "frontend_payload.json"

ARTIFACT_PATH_KEYS: tuple[str, ...] = (
    "experiment_spec",
    "run_status",
    "data_readiness",
    "universe_report",
    "factor_manifest",
    "candidate_manifest",
    "walk_forward_windows",
    "walk_forward_stability",
    "model_decision_pack",
    "model_decision_markdown",
    "signals_latest",
    "top_bottom_signals_csv",
    "metrics_summary",
    "frontend_payload",
)
SIGNALS_LATEST_COLUMNS: tuple[str, ...] = (
    "as_of_date",
    "market",
    "experiment_id",
    "symbol",
    "side",
    "rank",
    "score",
    "candidate_name",
    "orientation",
    "holding_horizon_days",
    "research_only",
    "trade_ready",
)
VALID_SIDES = frozenset({"top", "bottom"})
RESERVED_STATUS_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "status",
        "failed_stage",
        "reason",
        "research_only",
        "trade_ready",
    }
)
ARTIFACT_PROFILES: dict[str, tuple[str, ...]] = {
    "research_run_v1": (
        "experiment_spec",
        "run_status",
        "factor_manifest",
        "candidate_manifest",
        "signals_latest",
        "top_bottom_signals_csv",
        "frontend_payload",
    )
}


@dataclass(frozen=True)
class ResearchRunPaths:
    """All possible artifact paths for one experiment."""

    root: Path

    @property
    def run_dir(self) -> Path:
        return self.root

    @property
    def experiment_spec(self) -> Path:
        return self.root / EXPERIMENT_SPEC_FILENAME

    @property
    def run_status(self) -> Path:
        return self.root / RUN_STATUS_FILENAME

    @property
    def data_readiness(self) -> Path:
        return self.root / DATA_READINESS_FILENAME

    @property
    def universe_report(self) -> Path:
        return self.root / UNIVERSE_REPORT_FILENAME

    @property
    def factor_manifest(self) -> Path:
        return self.root / FACTOR_MANIFEST_FILENAME

    @property
    def candidate_manifest(self) -> Path:
        return self.root / CANDIDATE_MANIFEST_FILENAME

    @property
    def walk_forward_windows(self) -> Path:
        return self.root / WALK_FORWARD_WINDOWS_FILENAME

    @property
    def walk_forward_stability(self) -> Path:
        return self.root / WALK_FORWARD_STABILITY_FILENAME

    @property
    def model_decision_pack(self) -> Path:
        return self.root / MODEL_DECISION_PACK_FILENAME

    @property
    def model_decision_markdown(self) -> Path:
        return self.root / MODEL_DECISION_MARKDOWN_FILENAME

    @property
    def signals_latest(self) -> Path:
        return self.root / SIGNALS_LATEST_FILENAME

    @property
    def top_bottom_signals_csv(self) -> Path:
        return self.root / TOP_BOTTOM_SIGNALS_CSV_FILENAME

    @property
    def metrics_summary(self) -> Path:
        return self.root / METRICS_SUMMARY_FILENAME

    @property
    def frontend_payload(self) -> Path:
        return self.root / FRONTEND_PAYLOAD_FILENAME

    def ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def artifact_paths(self, *, existing_only: bool = True) -> dict[str, str]:
        values = {key: str(getattr(self, key)) for key in ARTIFACT_PATH_KEYS}
        if not existing_only:
            return values
        return {key: value for key, value in values.items() if Path(value).is_file()}


def research_run_dir(root: str | Path | None, experiment_id: str) -> Path:
    base = Path(root) if root is not None else Path.cwd()
    return base / "artifacts" / "research_runs" / experiment_id


def build_research_run_paths(
    root: str | Path | None,
    experiment_id: str,
    output_dir: str | Path | None = None,
) -> ResearchRunPaths:
    if output_dir is not None:
        return ResearchRunPaths(Path(output_dir) / experiment_id)
    return ResearchRunPaths(research_run_dir(root, experiment_id))


def resolve_run_dir(
    experiment_id: str,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """Compatibility wrapper for earlier callers."""
    return build_research_run_paths(root, experiment_id, output_dir).run_dir


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write a JSON mapping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


write_json_safe = write_json


def _decision_fields(decision: dict[str, Any] | None) -> tuple[str, bool]:
    decision = decision or {}
    return str(decision.get("status", "")), bool(decision.get("trade_ready", False))


def write_run_status(
    paths: ResearchRunPaths,
    *,
    experiment_id: str,
    status: str,
    reason: str = "",
    failed_stage: str = "",
    decision: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write status without allowing metadata to override safety fields."""
    extra = dict(extra or {})
    overlap = RESERVED_STATUS_FIELDS.intersection(extra)
    if overlap:
        raise ValueError(f"extra cannot override reserved status fields: {sorted(overlap)}")
    _, trade_ready = _decision_fields(decision)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "status": status,
        "failed_stage": failed_stage,
        "reason": reason,
        "research_only": True,
        "trade_ready": trade_ready,
        **extra,
    }
    write_json(paths.run_status, payload)
    return payload


def build_frontend_payload(
    experiment_id: str,
    *,
    market: str,
    benchmark: str,
    run_status: str = "",
    decision: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    gates: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
    top_signals: list[dict[str, Any]] | None = None,
    bottom_signals: list[dict[str, Any]] | None = None,
    windows: list[dict[str, Any]] | None = None,
    artifact_paths: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a research-only payload; trade readiness derives from decision only."""
    decision_status, trade_ready = _decision_fields(decision)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "market": market,
        "benchmark": benchmark,
        "run_status": run_status,
        "decision_status": decision_status,
        "trade_ready": trade_ready,
        "research_only": True,
        "metrics": dict(metrics or {}),
        "gates": dict(gates or {}),
        "readiness": dict(readiness or {}),
        "top_signals": list(top_signals or []),
        "bottom_signals": list(bottom_signals or []),
        "windows": list(windows or []),
        "artifact_paths": dict(artifact_paths or {}),
    }
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def write_frontend_payload(paths: ResearchRunPaths, payload: dict[str, Any]) -> None:
    write_json(paths.frontend_payload, payload)


def build_research_signals_payload(
    rows: list[dict[str, Any]],
    *,
    market: str = "",
    experiment_id: str = "",
    candidate_name: str = "",
    orientation: str = "",
    holding_horizon_days: int = 10,
    decision: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize signal rows and ignore row-level readiness claims."""
    _, trade_ready = _decision_fields(decision)
    result: list[dict[str, Any]] = []
    for row in rows:
        side = str(row.get("side", "")).lower()
        if side not in VALID_SIDES:
            raise ValueError("side must be 'top' or 'bottom'")
        result.append(
            {
                "as_of_date": row.get("as_of_date", row.get("date", "")),
                "market": row.get("market", market),
                "experiment_id": row.get("experiment_id", experiment_id),
                "symbol": row.get("symbol", ""),
                "side": side,
                "rank": row.get("rank", 0),
                "score": row.get("score", 0.0),
                "candidate_name": row.get("candidate_name", candidate_name),
                "orientation": row.get("orientation", orientation),
                "holding_horizon_days": row.get(
                    "holding_horizon_days", holding_horizon_days
                ),
                "research_only": True,
                "trade_ready": trade_ready,
            }
        )
    return result


def write_top_bottom_signals_csv(
    paths: ResearchRunPaths,
    rows: list[dict[str, Any]],
    *,
    market: str = "",
    experiment_id: str = "",
    candidate_name: str = "",
    orientation: str = "",
    holding_horizon_days: int = 10,
    decision: dict[str, Any] | None = None,
) -> None:
    normalized = build_research_signals_payload(
        rows,
        market=market,
        experiment_id=experiment_id,
        candidate_name=candidate_name,
        orientation=orientation,
        holding_horizon_days=holding_horizon_days,
        decision=decision,
    )
    paths.ensure_dir()
    with paths.top_bottom_signals_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SIGNALS_LATEST_COLUMNS))
        writer.writeheader()
        writer.writerows(normalized)


write_top_bottom_csv = write_top_bottom_signals_csv


def validate_artifact_completeness(
    paths: ResearchRunPaths, *, profile: str
) -> dict[str, Any]:
    """Fail closed when a declared artifact profile is incomplete."""
    if profile not in ARTIFACT_PROFILES:
        raise ValueError(f"Unknown artifact profile '{profile}'")
    required = ARTIFACT_PROFILES[profile]
    missing = [key for key in required if not getattr(paths, key).is_file()]
    if missing:
        raise ValueError(f"Missing required artifacts for {profile}: {missing}")
    return {"profile": profile, "complete": True, "required": list(required)}


def write_skipped_run(
    paths: ResearchRunPaths,
    *,
    experiment_id: str,
    reason: str,
    market: str = "unknown",
    benchmark: str = "unknown",
) -> dict[str, Any]:
    status = write_run_status(
        paths,
        experiment_id=experiment_id,
        status="skipped",
        reason=reason,
    )
    payload = build_frontend_payload(
        experiment_id,
        market=market,
        benchmark=benchmark,
        run_status="skipped",
        artifact_paths={
            **paths.artifact_paths(existing_only=True),
            "frontend_payload": str(paths.frontend_payload),
        },
        metadata={"skip_reason": reason},
    )
    write_frontend_payload(paths, payload)
    return status
