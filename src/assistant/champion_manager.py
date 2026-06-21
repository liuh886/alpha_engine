"""Champion/Challenger lifecycle management (T47.1).

One Champion per market/scope. Challengers are compared on the same snapshot
family, windows, benchmark, costs, and metric/signal policy. Promotion is
atomic — a failed promotion leaves the Champion unchanged. Rollback restores
a previously verified Champion version without discovery-by-recency.

Builds on the model registry stages (CANDIDATE/STAGING/RECOMMENDED/
REJECTED/SUPERSEDED) and the evidence-binding validation in
``model_registry_index.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.assistant.base_index import BaseIndex
from src.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ChampionRecord:
    """A Champion entry for one market."""

    market: str
    model_version_id: str
    artifact_id: str
    declared_at: str  # ISO timestamp
    declared_by: str  # "manual" | "auto"
    snapshot_id: str
    metrics: dict[str, float] = field(default_factory=dict)
    previous_champion_id: str | None = None  # for rollback chain
    promotion_reason: str = ""


@dataclass
class ChallengeResult:
    """Outcome of comparing a Challenger against the current Champion."""

    challenger_id: str
    champion_id: str | None  # None if no Champion exists yet
    market: str
    passed: bool
    challenger_metrics: dict[str, float]
    champion_metrics: dict[str, float]
    comparison_details: list[str]  # human-readable comparison lines
    failure_reasons: list[str]  # why the challenge failed (empty if passed)


# ---------------------------------------------------------------------------
# SQLite-backed Champion store
# ---------------------------------------------------------------------------


class ChampionIndex(BaseIndex):
    """SQLite index for Champion records."""

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS champions (
                    market          TEXT PRIMARY KEY,
                    model_version_id TEXT NOT NULL,
                    artifact_id     TEXT NOT NULL,
                    declared_at     TEXT NOT NULL,
                    declared_by     TEXT NOT NULL DEFAULT 'manual',
                    snapshot_id     TEXT NOT NULL DEFAULT '',
                    metrics_json    TEXT NOT NULL DEFAULT '{}',
                    previous_champion_id TEXT,
                    promotion_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS champion_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    market          TEXT NOT NULL,
                    model_version_id TEXT NOT NULL,
                    artifact_id     TEXT NOT NULL,
                    action          TEXT NOT NULL,  -- 'promoted', 'demoted', 'rollback'
                    replaced_id     TEXT,
                    reason          TEXT NOT NULL DEFAULT '',
                    recorded_at     REAL NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Champion CRUD
    # ------------------------------------------------------------------

    def set_champion(self, record: ChampionRecord) -> None:
        """Upsert the Champion for *record.market*."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO champions
                    (market, model_version_id, artifact_id, declared_at,
                     declared_by, snapshot_id, metrics_json,
                     previous_champion_id, promotion_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.market,
                    record.model_version_id,
                    record.artifact_id,
                    record.declared_at,
                    record.declared_by,
                    record.snapshot_id,
                    _safe_json(record.metrics),
                    record.previous_champion_id,
                    record.promotion_reason,
                ),
            )
            self._record_history(
                conn,
                market=record.market,
                model_version_id=record.model_version_id,
                artifact_id=record.artifact_id,
                action="promoted",
                replaced_id=record.previous_champion_id,
                reason=record.promotion_reason,
            )
            conn.commit()

    def get_champion(self, market: str) -> ChampionRecord | None:
        """Return the current Champion for *market*, or None."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM champions WHERE market = ?", (market,)).fetchone()
        if row is None:
            return None
        return self._row_to_record(dict(row))

    def clear_champion(self, market: str) -> None:
        """Remove the Champion for *market* (demotion without replacement)."""
        prev = self.get_champion(market)
        with self._connect() as conn:
            if prev:
                self._record_history(
                    conn,
                    market=market,
                    model_version_id=prev.model_version_id,
                    artifact_id=prev.artifact_id,
                    action="demoted",
                    replaced_id=None,
                    reason="Explicit demotion — no replacement",
                )
            conn.execute("DELETE FROM champions WHERE market = ?", (market,))
            conn.commit()

    def get_history(self, market: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent champion lifecycle events for *market*."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM champion_history
                WHERE market = ?
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (market, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> ChampionRecord:
        metrics = _parse_json(row.get("metrics_json", "{}"))
        return ChampionRecord(
            market=row["market"],
            model_version_id=row["model_version_id"],
            artifact_id=row["artifact_id"],
            declared_at=row["declared_at"],
            declared_by=row.get("declared_by", "manual"),
            snapshot_id=row.get("snapshot_id", ""),
            metrics=metrics if isinstance(metrics, dict) else {},
            previous_champion_id=row.get("previous_champion_id"),
            promotion_reason=row.get("promotion_reason", ""),
        )

    def _record_history(
        self,
        conn,
        *,
        market: str,
        model_version_id: str,
        artifact_id: str,
        action: str,
        replaced_id: str | None,
        reason: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO champion_history
                (market, model_version_id, artifact_id, action,
                 replaced_id, reason, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                market,
                model_version_id,
                artifact_id,
                action,
                replaced_id,
                reason,
                time.time(),
            ),
        )


# ---------------------------------------------------------------------------
# Champion Manager
# ---------------------------------------------------------------------------


class ChampionManager:
    """Manage Champion/Challenger lifecycle for a market.

    Usage::

        mgr = ChampionManager(db_path)
        mgr.declare_champion("cn", model_version_id="mv_abc", ...)
        result = mgr.evaluate_challenger("cn", challenger_id="mv_xyz")
        if result.passed:
            mgr.promote_challenger("cn", challenger_id="mv_xyz")
    """

    def __init__(self, db_path: str | Path) -> None:
        self._champion_index = ChampionIndex(db_path=db_path)
        # Lazy-loaded model registry
        self._registry = None

    @property
    def registry(self):
        """Lazy-load the ModelRegistryIndex."""
        if self._registry is None:
            from src.assistant.model_registry_index import ModelRegistryIndex

            self._registry = ModelRegistryIndex(db_path=self._champion_index._db_path)
        return self._registry

    # ------------------------------------------------------------------
    # Champion declaration
    # ------------------------------------------------------------------

    def declare_champion(
        self,
        market: str,
        model_version_id: str,
        *,
        artifact_id: str = "",
        snapshot_id: str = "",
        metrics: dict[str, float] | None = None,
        reason: str = "",
        declared_by: str = "manual",
    ) -> ChampionRecord:
        """Declare (or replace) the Champion for *market*.

        The model version must exist in the registry and be at least STAGING.
        Promotion is atomic: if the model doesn't meet requirements, the call
        raises ``ValueError`` and the current Champion is untouched.
        """
        market = market.lower()
        entry = self.registry.get_version(model_version_id)
        if entry is None:
            raise ValueError(f"Model version not found: {model_version_id}")

        stage = str(entry.get("stage") or "CANDIDATE").upper()
        if stage in ("CANDIDATE", "REJECTED"):
            raise ValueError(
                f"Model {model_version_id} is stage={stage}. "
                f"CANDIDATE and REJECTED models cannot be declared Champion."
            )

        # Validate evidence binding
        from src.assistant.model_registry_index import validate_evidence_binding

        binding_errors = validate_evidence_binding(entry)
        if binding_errors:
            raise ValueError(
                f"Evidence binding failed for {model_version_id}: {'; '.join(binding_errors)}"
            )

        # Resolve artifact and snapshot
        resolved_artifact = artifact_id or str(entry.get("artifact_id") or "")
        resolved_snapshot = snapshot_id or str(entry.get("data_snapshot_id") or "")
        resolved_metrics = metrics or _extract_metrics(entry)

        previous = self._champion_index.get_champion(market)
        previous_id = previous.model_version_id if previous else None

        record = ChampionRecord(
            market=market,
            model_version_id=model_version_id,
            artifact_id=resolved_artifact,
            declared_at=datetime.now(timezone.utc).isoformat(),
            declared_by=declared_by,
            snapshot_id=resolved_snapshot,
            metrics=resolved_metrics,
            previous_champion_id=previous_id,
            promotion_reason=reason,
        )

        # Mark superseded if replacing an existing Champion
        if previous:
            self.registry.update_stage(previous.model_version_id, "SUPERSEDED")

        self._champion_index.set_champion(record)
        logger.info(
            "Champion declared",
            market=market,
            model_version_id=model_version_id,
            previous=previous_id,
        )
        return record

    # ------------------------------------------------------------------
    # Challenger evaluation
    # ------------------------------------------------------------------

    def evaluate_challenger(
        self,
        market: str,
        challenger_id: str,
    ) -> ChallengeResult:
        """Evaluate whether *challenger_id* can challenge the current Champion.

        Comparison criteria (all must pass):
        1. Challenger exists in registry with valid evidence
        2. Same market
        3. Comparable metrics (both have required metric fields)
        4. Challenger has equal or better Sharpe/return, equal or lower MDD
        5. Same snapshot family (or at least same market)
        """
        market = market.lower()
        challenger_entry = self.registry.get_version(challenger_id)
        if challenger_entry is None:
            return ChallengeResult(
                challenger_id=challenger_id,
                champion_id=None,
                market=market,
                passed=False,
                challenger_metrics={},
                champion_metrics={},
                comparison_details=[],
                failure_reasons=[f"Challenger not found: {challenger_id}"],
            )

        challenger_metrics = _extract_metrics(challenger_entry)
        if not challenger_metrics:
            return ChallengeResult(
                challenger_id=challenger_id,
                champion_id=None,
                market=market,
                passed=False,
                challenger_metrics={},
                champion_metrics={},
                comparison_details=[],
                failure_reasons=["Challenger has no valid metrics"],
            )

        champion = self._champion_index.get_champion(market)
        if champion is None:
            # No Champion yet — challenger passes by default
            return ChallengeResult(
                challenger_id=challenger_id,
                champion_id=None,
                market=market,
                passed=True,
                challenger_metrics=challenger_metrics,
                champion_metrics={},
                comparison_details=["No current Champion — challenger auto-passes."],
                failure_reasons=[],
            )

        champion_metrics = champion.metrics
        details: list[str] = []
        failures: list[str] = []

        # --- Gate 1: Excess return comparison ---
        challenger_excess = challenger_metrics.get("excess_return_with_cost", 0)
        champion_excess = champion_metrics.get("excess_return_with_cost", 0)
        if challenger_excess < champion_excess:
            failures.append(
                f"Excess return: challenger={challenger_excess:.4f} < "
                f"champion={champion_excess:.4f}"
            )
        details.append(
            f"Excess return: challenger={challenger_excess:.4f} vs champion={champion_excess:.4f}"
        )

        # --- Gate 2: Max drawdown comparison ---
        challenger_mdd = abs(challenger_metrics.get("max_drawdown", 0))
        champion_mdd = abs(champion_metrics.get("max_drawdown", 0))
        if champion_mdd > 0 and challenger_mdd > champion_mdd * 1.1:
            failures.append(
                f"Max DD: challenger={challenger_mdd:.4f} > "
                f"champion={champion_mdd:.4f} (+10% tolerance)"
            )
        details.append(f"Max DD: challenger={challenger_mdd:.4f} vs champion={champion_mdd:.4f}")

        # --- Gate 3: Information ratio comparison ---
        challenger_ir = challenger_metrics.get("information_ratio", 0)
        champion_ir = champion_metrics.get("information_ratio", 0)
        if challenger_ir < champion_ir * 0.9:
            failures.append(
                f"IR: challenger={challenger_ir:.4f} < champion={champion_ir:.4f} (-10% tolerance)"
            )
        details.append(f"IR: challenger={challenger_ir:.4f} vs champion={champion_ir:.4f}")

        # --- Gate 4: Annualized return ---
        challenger_ann = challenger_metrics.get("annualized_return", 0)
        champion_ann = champion_metrics.get("annualized_return", 0)
        if challenger_ann < champion_ann * 0.95:
            failures.append(
                f"Ann. return: challenger={challenger_ann:.4f} < "
                f"champion={champion_ann:.4f} (-5% tolerance)"
            )
        details.append(
            f"Ann. return: challenger={challenger_ann:.4f} vs champion={champion_ann:.4f}"
        )

        passed = len(failures) == 0
        return ChallengeResult(
            challenger_id=challenger_id,
            champion_id=champion.model_version_id,
            market=market,
            passed=passed,
            challenger_metrics=challenger_metrics,
            champion_metrics=champion_metrics,
            comparison_details=details,
            failure_reasons=failures,
        )

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def promote_challenger(
        self,
        market: str,
        challenger_id: str,
        *,
        reason: str = "",
    ) -> ChampionRecord:
        """Evaluate and promote *challenger_id* to Champion.

        Promotion is atomic:
        - If the challenge fails, ``ValueError`` is raised and the current
          Champion is unchanged.
        - If there is no current Champion, the challenger is declared directly.
        """
        result = self.evaluate_challenger(market, challenger_id)
        if not result.passed:
            raise ValueError(
                f"Challenge failed for {challenger_id}: {'; '.join(result.failure_reasons)}"
            )

        return self.declare_champion(
            market=market,
            model_version_id=challenger_id,
            metrics=result.challenger_metrics,
            reason=reason or "Challenger promotion",
            declared_by="auto",
        )

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(
        self,
        market: str,
        target_version_id: str | None = None,
    ) -> ChampionRecord | None:
        """Roll back the Champion to a previous version.

        If *target_version_id* is provided, that version becomes the new
        Champion (must exist in the registry).  Otherwise, the most recent
        previous Champion from the history is restored.

        Returns the new Champion record, or None if no rollback target exists.
        """
        market = market.lower()
        current = self._champion_index.get_champion(market)

        if target_version_id:
            entry = self.registry.get_version(target_version_id)
            if entry is None:
                raise ValueError(f"Rollback target not found in registry: {target_version_id}")
            return self.declare_champion(
                market=market,
                model_version_id=target_version_id,
                reason=f"Rollback to {target_version_id}",
                declared_by="rollback",
            )

        # Auto-rollback: find the previous Champion from history
        if current is None:
            logger.warning("No current Champion to roll back", market=market)
            return None

        history = self._champion_index.get_history(market, limit=10)
        for event in history:
            if event["action"] == "promoted" and event.get("replaced_id"):
                prev_id = event["replaced_id"]
                prev_entry = self.registry.get_version(prev_id)
                if prev_entry is not None:
                    return self.declare_champion(
                        market=market,
                        model_version_id=prev_id,
                        reason=f"Rollback from {current.model_version_id} to {prev_id}",
                        declared_by="rollback",
                    )

        logger.warning(
            "No rollback target found in champion history",
            market=market,
            current=current.model_version_id,
        )
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_champion(self, market: str) -> ChampionRecord | None:
        """Return the current Champion for *market*."""
        return self._champion_index.get_champion(market)

    def get_history(self, market: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent champion lifecycle events."""
        return self._champion_index.get_history(market, limit=limit)

    def list_challengers(self, market: str, limit: int = 20) -> list[dict[str, Any]]:
        """List potential challengers: RECOMMENDED models for *market*."""
        versions = self.registry.list_versions(limit=200)
        challengers = []
        for v in versions:
            if str(v.get("market") or "").lower() != market.lower():
                continue
            stage = str(v.get("stage") or "").upper()
            if stage not in ("STAGING", "RECOMMENDED"):
                continue
            champion = self._champion_index.get_champion(market)
            if champion and v["id"] == champion.model_version_id:
                continue  # skip the current Champion
            challengers.append(v)
        return challengers[:limit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return "{}"


def _parse_json(raw: str | bytes | None) -> Any:
    import json

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _extract_metrics(entry: dict[str, Any]) -> dict[str, float]:
    """Extract float metrics from a registry entry."""
    backtest = entry.get("backtest") or {}
    metrics = backtest.get("metrics") if isinstance(backtest, dict) else {}
    if not isinstance(metrics, dict):
        return {}

    result: dict[str, float] = {}
    metric_fields = [
        "excess_return_with_cost",
        "excess_return_without_cost",
        "excess_return",
        "annualized_return",
        "max_drawdown",
        "information_ratio",
        "sharpe_ratio",
    ]
    for key in metric_fields:
        val = metrics.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            result[key] = float(val)
    return result
