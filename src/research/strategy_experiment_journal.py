"""Persistent memory for rule-based strategy contracts and backtest runs.

Model training remains tracked by MLflow and ``MLRegistry``. This journal covers
non-ML strategies whose source of truth is a frozen research contract plus a
reproducible backtest record.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

_REQUIRED_FIELDS = {
    "schema_version",
    "experiment_id",
    "run_id",
    "created_at",
    "status",
    "market",
    "strategy_family",
    "research_only",
    "trade_ready",
    "contract",
    "metrics",
}
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _default_root() -> Path:
    from src.common.paths import ARTIFACTS_DIR

    return ARTIFACTS_DIR / "strategy_runs"


def _validate_token(value: str, field: str) -> str:
    token = str(value).strip()
    if not token or not _SAFE_TOKEN.fullmatch(token):
        raise ValueError(f"{field} must contain only letters, numbers, '.', '_' or '-'")
    return token


def validate_strategy_run_record(record: Mapping[str, Any]) -> None:
    """Validate the minimum immutable identity of a strategy run record."""

    missing = sorted(_REQUIRED_FIELDS - set(record))
    if missing:
        raise ValueError(f"strategy run record missing required fields: {missing}")
    _validate_token(str(record["experiment_id"]), "experiment_id")
    _validate_token(str(record["run_id"]), "run_id")
    if not isinstance(record["metrics"], Mapping):
        raise ValueError("metrics must be a mapping")
    if not isinstance(record["contract"], Mapping):
        raise ValueError("contract must be a mapping")


def write_strategy_run_record(
    record: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> Path:
    """Atomically persist one strategy run under experiment/run identity."""

    validate_strategy_run_record(record)
    base = Path(root) if root is not None else _default_root()
    experiment_id = _validate_token(str(record["experiment_id"]), "experiment_id")
    run_id = _validate_token(str(record["run_id"]), "run_id")
    run_dir = base / experiment_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_record.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(dict(record), ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temp.replace(path)
    return path


def load_strategy_run_records(
    *,
    root: str | Path | None = None,
    market: str | None = None,
    experiment_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Load strategy run records newest first, failing closed on malformed files."""

    base = Path(root) if root is not None else _default_root()
    if not base.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in base.glob("*/*/run_record.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_strategy_run_record(data)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if market and str(data.get("market", "")).lower() != market.lower():
            continue
        if experiment_id and data.get("experiment_id") != experiment_id:
            continue
        if status and data.get("status") != status:
            continue
        data["_file"] = str(path)
        records.append(data)
    return sorted(records, key=lambda item: str(item.get("created_at", "")), reverse=True)


class StrategyExperimentJournal:
    """Query interface for frozen strategy contracts and their backtest records."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else _default_root()

    def record(self, record: Mapping[str, Any]) -> Path:
        return write_strategy_run_record(record, root=self.root)

    def list_runs(
        self,
        *,
        market: str | None = None,
        experiment_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return load_strategy_run_records(
            root=self.root,
            market=market,
            experiment_id=experiment_id,
            status=status,
        )[:limit]

    def latest(self, experiment_id: str) -> dict[str, Any] | None:
        runs = self.list_runs(experiment_id=experiment_id, limit=1)
        return runs[0] if runs else None

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        matches = []
        for record in self.list_runs(limit=10_000):
            if needle in json.dumps(record, ensure_ascii=False, default=str).lower():
                matches.append(record)
                if len(matches) >= limit:
                    break
        return matches

    def summary(self, market: str | None = None) -> dict[str, Any]:
        runs = self.list_runs(market=market, limit=10_000)
        by_status: dict[str, int] = {}
        experiments: set[str] = set()
        for run in runs:
            status = str(run.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1
            experiments.add(str(run["experiment_id"]))
        return {
            "total_runs": len(runs),
            "total_experiments": len(experiments),
            "by_status": by_status,
            "latest_created_at": runs[0].get("created_at") if runs else None,
        }
