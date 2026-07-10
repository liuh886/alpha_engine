"""Research artifact paths, schemas, and safe writers.

No Qlib dependency.  All artifacts live under
``artifacts/research_runs/{experiment_id}/`` with exactly the standard
filenames defined by ``ResearchRunPaths``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ── Standard artifact filenames (exact contract) ───────────────────────────────

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

# Every standard artifact path key
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

# ── CSV column schemas (exact contract) ────────────────────────────────────────

# Each signal / top-bottom CSV row uses these exact fields:
SIGNALS_LATEST_COLUMNS: tuple[str, ...] = (
    "as_of_date",
    "market",
    "experiment_id",
    "symbol",
    "side",  # "top" | "bottom"
    "rank",
    "score",
    "candidate_name",
    "orientation",
    "holding_horizon_days",
    "research_only",
    "trade_ready",
)

VALID_SIDES: frozenset[str] = frozenset({"top", "bottom"})


# ── ResearchRunPaths ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResearchRunPaths:
    """Standard artifact paths for one research run.

    Exposes exactly 15 path properties plus the ``run_dir`` compatibility
    property and a ``root`` alias for the run directory.
    """

    root: Path  # the experiment run directory

    @property
    def run_dir(self) -> Path:
        """Compatibility alias for *root*."""
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
        """Create the run directory if it does not exist."""
        self.root.mkdir(parents=True, exist_ok=True)

    def artifact_paths(self) -> dict[str, str]:
        """Return all standard artifact paths as serializable strings."""
        return {
            "experiment_spec": str(self.experiment_spec),
            "run_status": str(self.run_status),
            "data_readiness": str(self.data_readiness),
            "universe_report": str(self.universe_report),
            "factor_manifest": str(self.factor_manifest),
            "candidate_manifest": str(self.candidate_manifest),
            "walk_forward_windows": str(self.walk_forward_windows),
            "walk_forward_stability": str(self.walk_forward_stability),
            "model_decision_pack": str(self.model_decision_pack),
            "model_decision_markdown": str(self.model_decision_markdown),
            "signals_latest": str(self.signals_latest),
            "top_bottom_signals_csv": str(self.top_bottom_signals_csv),
            "metrics_summary": str(self.metrics_summary),
            "frontend_payload": str(self.frontend_payload),
        }


# ── Run directory resolution ─────────────────────────────────────────────────


def research_run_dir(
    root: str | Path | None,
    experiment_id: str,
) -> Path:
    """Return the standard run directory for *experiment_id*.

    ``artifacts/research_runs/{experiment_id}`` under *root*.
    Falls back to cwd if *root* is None.
    """
    base = Path(root) if root else Path.cwd()
    return base / "artifacts" / "research_runs" / experiment_id


def build_research_run_paths(
    root: str | Path | None,
    experiment_id: str,
    output_dir: str | Path | None = None,
) -> ResearchRunPaths:
    """Build ``ResearchRunPaths`` from root + experiment_id.

    When *output_dir* is given, it is treated as the parent output root
    and the run directory becomes ``output_dir / experiment_id`` (no
    ``artifacts/research_runs/`` prefix).  Otherwise uses the standard
    ``root / artifacts / research_runs / experiment_id`` layout.
    """
    if output_dir:
        return ResearchRunPaths(Path(output_dir) / experiment_id)
    return ResearchRunPaths(research_run_dir(root, experiment_id))


# ── Compatibility: old resolve_run_dir ────────────────────────────────────────


def resolve_run_dir(
    experiment_id: str,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """Compatibility wrapper.  Prefer ``research_run_dir`` in new code.

    Precedence:
    1. *output_dir* (explicit override)
    2. *root* / artifacts / research_runs / *experiment_id*
    3. cwd / artifacts / research_runs / *experiment_id*
    """
    if output_dir:
        return Path(output_dir) / experiment_id
    return research_run_dir(root, experiment_id)


# ── Safe writers ─────────────────────────────────────────────────────────────


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write a JSON file via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


# Compatibility alias
write_json_safe = write_json


# ── Run status writer ────────────────────────────────────────────────────────


def write_run_status(
    paths: ResearchRunPaths,
    *,
    experiment_id: str,
    status: str,
    reason: str = "",
    failed_stage: str = "",
    trade_ready: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``run_status.json`` and return the payload.

    Always emits: schema_version, experiment_id, status, failed_stage,
    reason, research_only:true, trade_ready:false (unless an explicit
    decision pack ``trade_ready`` is supplied — but the status writer
    defaults to False).

    Always writes, even for skipped runs.
    """
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "status": status,
        "failed_stage": failed_stage,
        "reason": reason,
        "research_only": True,
        "trade_ready": trade_ready,
    }
    if extra:
        payload.update(extra)
    paths.ensure_dir()
    write_json(paths.run_status, payload)
    return payload


# ── Frontend payload builder ─────────────────────────────────────────────────


def build_frontend_payload(
    experiment_id: str,
    *,
    market: str,
    benchmark: str,
    run_status: str = "",
    decision_status: str = "",
    trade_ready: bool = False,
    metrics: dict[str, Any] | None = None,
    gates: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
    top_signals: list[dict[str, Any]] | None = None,
    bottom_signals: list[dict[str, Any]] | None = None,
    windows: list[dict[str, Any]] | None = None,
    artifact_paths: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the fixed frontend payload schema.

    Returns exact minimum keys: schema_version, experiment_id, market,
    benchmark, run_status, decision_status, trade_ready, research_only,
    metrics, gates, readiness, top_signals, bottom_signals, windows,
    artifact_paths.

    - *trade_ready*: False unless ``decision_pack.decision.trade_ready``
      is explicitly True.
    - *research_only*: always True.
    - *top_signals* / *bottom_signals* / *windows*: default empty list.
    - *artifact_paths*: all standard keys as serializable strings.
    - Extra metadata nested under ``metadata``, never replaces fixed keys.

    The payload never contains buy/sell/order/execution keys.
    """
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "market": market,
        "benchmark": benchmark,
        "run_status": run_status,
        "decision_status": decision_status,
        "trade_ready": trade_ready,
        "research_only": True,
        "metrics": metrics if metrics is not None else {},
        "gates": gates if gates is not None else {},
        "readiness": readiness if readiness is not None else {},
        "top_signals": top_signals if top_signals is not None else [],
        "bottom_signals": bottom_signals if bottom_signals is not None else [],
        "windows": windows if windows is not None else [],
        "artifact_paths": artifact_paths if artifact_paths is not None else {},
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


# ── Frontend payload writer ──────────────────────────────────────────────────


def write_frontend_payload(paths: ResearchRunPaths, payload: dict[str, Any]) -> None:
    """Write ``frontend_payload.json``. Always writes, even for skipped runs."""
    paths.ensure_dir()
    write_json(paths.frontend_payload, payload)


# ── Research signals payload builder ─────────────────────────────────────────


def build_research_signals_payload(
    rows: list[dict[str, Any]],
    *,
    market: str = "",
    experiment_id: str = "",
    candidate_name: str = "",
    orientation: str = "",
    holding_horizon_days: int = 10,
    trade_ready: bool = False,
) -> list[dict[str, Any]]:
    """Build a standardised signals_latest row list.

    Each row is filtered to the canonical ``SIGNALS_LATEST_COLUMNS``.
    Missing columns are filled with default values.

    - Invalid *side* values are rejected (must be "top" or "bottom").
    - *research_only* is forced True.
    - *trade_ready* comes from the decision pack.
    - Never emits buy/sell/order/execution fields.
    """
    result: list[dict[str, Any]] = []
    for row in rows:
        side = str(row.get("side", "")).lower()
        if side and side not in VALID_SIDES:
            raise ValueError(
                f"Invalid side '{side}' — must be 'top' or 'bottom'"
            )

        filtered: dict[str, Any] = {
            "as_of_date": row.get("as_of_date", row.get("date", "")),
            "market": row.get("market", market),
            "experiment_id": row.get("experiment_id", experiment_id),
            "symbol": row.get("symbol", ""),
            "side": side,
            "rank": row.get("rank", 0),
            "score": row.get("score", 0.0),
            "candidate_name": row.get("candidate_name", candidate_name),
            "orientation": row.get("orientation", orientation),
            "holding_horizon_days": row.get("holding_horizon_days", holding_horizon_days),
            "research_only": True,
            "trade_ready": row.get("trade_ready", trade_ready),
        }
        result.append(filtered)
    return result


# ── CSV writers ──────────────────────────────────────────────────────────────


def write_top_bottom_signals_csv(
    paths: ResearchRunPaths,
    rows: list[dict[str, Any]],
    *,
    market: str = "",
    experiment_id: str = "",
    candidate_name: str = "",
    orientation: str = "",
    holding_horizon_days: int = 10,
    trade_ready: bool = False,
) -> None:
    """Write ``top_bottom_signals.csv`` with the exact standard columns.

    Writes header even when *rows* is empty.
    Rejects rows with invalid *side* values.
    """
    paths.ensure_dir()
    columns = list(SIGNALS_LATEST_COLUMNS)
    with open(paths.top_bottom_signals_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            side = str(row.get("side", "")).lower()
            if side and side not in VALID_SIDES:
                raise ValueError(
                    f"Invalid side '{side}' — must be 'top' or 'bottom'"
                )
            filtered = {
                "as_of_date": row.get("as_of_date", row.get("date", "")),
                "market": row.get("market", market),
                "experiment_id": row.get("experiment_id", experiment_id),
                "symbol": row.get("symbol", ""),
                "side": side,
                "rank": row.get("rank", 0),
                "score": row.get("score", 0.0),
                "candidate_name": row.get("candidate_name", candidate_name),
                "orientation": row.get("orientation", orientation),
                "holding_horizon_days": row.get("holding_horizon_days", holding_horizon_days),
                "research_only": True,
                "trade_ready": row.get("trade_ready", trade_ready),
            }
            writer.writerow(filtered)


# Compatibility alias
write_top_bottom_csv = write_top_bottom_signals_csv


# ── Skipped run helper ───────────────────────────────────────────────────────


def write_skipped_run(
    paths: ResearchRunPaths,
    *,
    experiment_id: str,
    reason: str,
    market: str = "unknown",
    benchmark: str = "unknown",
) -> dict[str, Any]:
    """Write run_status.json and frontend_payload.json for a skipped run.

    Skipped runs always produce these two files so the frontend and
    run index can discover and display the skip reason.
    """
    status_payload = write_run_status(
        paths,
        experiment_id=experiment_id,
        status="skipped",
        reason=reason,
    )
    frontend = build_frontend_payload(
        experiment_id,
        market=market,
        benchmark=benchmark,
        run_status="skipped",
        artifact_paths=paths.artifact_paths(),
        metadata={"skip_reason": reason},
    )
    write_frontend_payload(paths, frontend)
    return status_payload
