"""SQLite-backed factor lifecycle registry.

Tracks factors from proposal through validation and active use,
including per-market validation metrics and strategy usage records.
Follows the same SQLite patterns as ArenaIndex (BaseIndex / metadata_db.connect).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.assistant.base_index import BaseIndex
from src.common.logging import get_logger

__all__ = [
    "FactorRegistry",
    "FactorRecord",
    "FactorValidationRecord",
    "FactorUsageRecord",
    "RegistryStats",
    "VALIDATION_GATES",
    "GATE_1_THRESHOLDS",
    "GATE_2_THRESHOLDS",
    "GATE_3_THRESHOLDS",
    "STAGE_PROPOSED",
    "STAGE_CANDIDATE",
    "STAGE_VALIDATED",
    "STAGE_ACTIVE",
    "STAGE_DEPRECATED",
    "STAGE_QUARANTINED",
]

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Stage constants
# ---------------------------------------------------------------------------

STAGE_PROPOSED = "Proposed"
STAGE_CANDIDATE = "Candidate"    # Gate 1 passed
STAGE_VALIDATED = "Validated"    # Gate 2 passed
STAGE_ACTIVE = "Active"          # Gate 3 passed
STAGE_WATCH = "Watch"            # Decay detected, monitoring
STAGE_DEPRECATED = "Deprecated"
STAGE_RETIRED = "Retired"        # Permanently removed
STAGE_QUARANTINED = "Quarantined"  # Invalid/suspect record, excluded from queries

_STAGE_ORDER = [STAGE_PROPOSED, STAGE_CANDIDATE, STAGE_VALIDATED, STAGE_ACTIVE, STAGE_WATCH, STAGE_DEPRECATED, STAGE_RETIRED, STAGE_QUARANTINED]

# ---------------------------------------------------------------------------
# Configurable validation gate thresholds
# ---------------------------------------------------------------------------

# Legacy single-gate thresholds (kept for backward compatibility with
# ``record_validation`` and ``_evaluate_gates``)
VALIDATION_GATES: dict[str, float] = {
    "min_icir": 0.3,             # Calibrated for walk-forward IC level (~0.09)
    "min_t_stat": 1.5,           # Relaxed for small stock universe (118 stocks)
    "min_positive_ratio": 0.55,  # fraction of periods with positive IC
    "min_quintile_spread": 0.001,  # Lowered: real IC produces smaller spreads
    "min_ic_decay_5d_ratio": 0.3,  # IC at 5d should retain at least 30% of IC at 1d
}

# --- Three-tier promotion gates ---
# Calibrated for walk-forward IC level (model IC=0.09, ICIR=1.46)

GATE_1_THRESHOLDS: dict[str, float] = {
    "min_icir": 0.3,
    "min_t_stat": 1.5,
    "min_positive_ratio": 0.55,
}

GATE_2_THRESHOLDS: dict[str, float] = {
    "min_icir": 0.5,              # Calibrated for walk-forward IC level
    "min_t_stat": 2.0,            # Standard 95% confidence
    "min_positive_ratio": 0.60,   # Higher consistency required
    "min_quintile_spread": 0.001,
    "min_ic_decay_5d_ratio": 0.3,  # IC should retain at least 30% at 5d
}

GATE_3_THRESHOLDS: dict[str, float] = {
    "min_icir": 1.0,              # Production quality (walk-forward model ICIR=1.46)
    "min_t_stat": 2.5,            # High confidence
    "min_positive_ratio": 0.65,
    "min_quintile_spread": 0.002,
    "min_ic_decay_5d_ratio": 0.4,  # IC should retain at least 40% at 5d
    "max_correlation_with_active": 0.7,  # not redundant with existing factors
}

# Mapping from current stage to the gate that must be passed for promotion.
_GATE_FOR_STAGE: dict[str, dict[str, float]] = {
    STAGE_PROPOSED: GATE_1_THRESHOLDS,
    STAGE_CANDIDATE: GATE_2_THRESHOLDS,
    STAGE_VALIDATED: GATE_3_THRESHOLDS,
}

# ---------------------------------------------------------------------------
# Data classes for typed results
# ---------------------------------------------------------------------------


@dataclass
class FactorRecord:
    """Typed representation of a row from the ``factors`` table."""

    id: int
    name: str
    expression: str
    category: str
    direction: str
    lookback_days: int
    thesis: str
    stage: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "expression": self.expression,
            "category": self.category,
            "direction": self.direction,
            "lookback_days": self.lookback_days,
            "thesis": self.thesis,
            "stage": self.stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class FactorValidationRecord:
    """Typed representation of a row from the ``factor_validations`` table."""

    id: int
    factor_id: int
    market: str
    ic: float | None
    rank_ic: float | None
    icir: float | None
    t_stat: float | None
    positive_ratio: float | None
    mean_decay_1d: float | None
    mean_decay_5d: float | None
    quintile_spread: float | None
    passed: bool
    validated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "factor_id": self.factor_id,
            "market": self.market,
            "ic": self.ic,
            "rank_ic": self.rank_ic,
            "icir": self.icir,
            "t_stat": self.t_stat,
            "positive_ratio": self.positive_ratio,
            "mean_decay_1d": self.mean_decay_1d,
            "mean_decay_5d": self.mean_decay_5d,
            "quintile_spread": self.quintile_spread,
            "passed": self.passed,
            "validated_at": self.validated_at,
        }


@dataclass
class FactorUsageRecord:
    """Typed representation of a row from the ``factor_usage`` table."""

    id: int
    factor_id: int
    strategy_config: str | None
    weight: float
    added_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "factor_id": self.factor_id,
            "strategy_config": self.strategy_config,
            "weight": self.weight,
            "added_at": self.added_at,
        }


@dataclass
class RegistryStats:
    """Summary statistics for the factor registry."""

    total_factors: int
    by_stage: dict[str, int]
    by_category: dict[str, int]
    by_direction: dict[str, int]
    total_validations: int
    total_passed_validations: int
    total_usage_records: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_factors": self.total_factors,
            "by_stage": self.by_stage,
            "by_category": self.by_category,
            "by_direction": self.by_direction,
            "total_validations": self.total_validations,
            "total_passed_validations": self.total_passed_validations,
            "total_usage_records": self.total_usage_records,
        }


# ---------------------------------------------------------------------------
# FactorRegistry
# ---------------------------------------------------------------------------


class FactorRegistry(BaseIndex):
    """SQLite-backed factor lifecycle store.

    Manages factors from proposal through validation and active use.
    Inherits connection management (``_connect`` context manager, ``row_factory``,
    WAL journal mode) from ``BaseIndex`` which delegates to
    ``src.assistant.metadata_db.connect``.

    Usage::

        registry = FactorRegistry()                        # default artifacts/factor_registry.db
        fid = registry.register_factor("mom_10d", "Ref($close, -10)/$close - 1",
                                        category="momentum", thesis="10-day momentum")
        registry.record_validation(fid, "us", {"ic": 0.03, "rank_ic": 0.04, ...})
        registry.promote(fid)
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            from src.common.paths import ARTIFACTS_DIR

            db_path = str(ARTIFACTS_DIR / "factor_registry.db")
        super().__init__(db_path=db_path)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    expression TEXT NOT NULL UNIQUE,
                    category TEXT DEFAULT 'custom',
                    direction TEXT DEFAULT 'long',
                    lookback_days INTEGER DEFAULT 10,
                    thesis TEXT DEFAULT '',
                    stage TEXT DEFAULT 'Proposed',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_id INTEGER NOT NULL,
                    market TEXT NOT NULL,
                    ic REAL,
                    rank_ic REAL,
                    icir REAL,
                    t_stat REAL,
                    positive_ratio REAL,
                    mean_decay_1d REAL,
                    mean_decay_5d REAL,
                    quintile_spread REAL,
                    passed INTEGER DEFAULT 0,
                    validated_at TEXT NOT NULL,
                    FOREIGN KEY (factor_id) REFERENCES factors(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    factor_id INTEGER NOT NULL,
                    strategy_config TEXT,
                    weight REAL DEFAULT 1.0,
                    added_at TEXT NOT NULL,
                    FOREIGN KEY (factor_id) REFERENCES factors(id)
                )
                """
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        """ISO-8601 timestamp string."""
        return datetime.now().isoformat()

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a sqlite3.Row to a plain dict."""
        return {k: row[k] for k in row.keys()}

    @staticmethod
    def _factor_from_row(row: Any) -> FactorRecord:
        d = {k: row[k] for k in row.keys()}
        return FactorRecord(**d)

    @staticmethod
    def _validation_from_row(row: Any) -> FactorValidationRecord:
        d = {k: row[k] for k in row.keys()}
        d["passed"] = bool(d.get("passed", 0))
        return FactorValidationRecord(**d)

    @staticmethod
    def _usage_from_row(row: Any) -> FactorUsageRecord:
        d = {k: row[k] for k in row.keys()}
        return FactorUsageRecord(**d)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register_factor(
        self,
        name: str,
        expression: str,
        category: str = "custom",
        direction: str = "long",
        lookback_days: int = 10,
        thesis: str = "",
    ) -> int:
        """Register a new factor and return its ``id``.

        If a factor with the same *expression* already exists, returns the
        existing factor's id (idempotent).  Raises ``sqlite3.IntegrityError``
        if a factor with the same *name* but a different expression already
        exists.
        """
        name = str(name).strip()
        expression = str(expression).strip()
        if not name:
            raise ValueError("name is required")
        if not expression:
            raise ValueError("expression is required")

        # Check for existing factor with the same expression
        existing = self.get_factor_by_expression(expression)
        if existing is not None:
            logger.info(
                "Factor with expression already exists, returning existing id",
                existing_id=existing["id"],
                expression=expression,
            )
            return existing["id"]

        now = self._now()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO factors (name, expression, category, direction,
                                     lookback_days, thesis, stage, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, expression, category, direction, lookback_days, thesis, STAGE_PROPOSED, now, now),
            )
            factor_id = cur.lastrowid
        logger.info("factor_registered", factor_id=factor_id, name=name, category=category)
        return factor_id

    def get_factor(self, factor_id: int) -> dict | None:
        """Return a factor by its integer ``id``, or ``None``."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM factors WHERE id = ?", (factor_id,)).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_factor_by_name(self, name: str) -> dict | None:
        """Return a factor by its unique ``name``, or ``None``."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM factors WHERE name = ?", (name.strip(),)).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_factor_by_expression(self, expression: str) -> dict | None:
        """Return a factor by its exact ``expression`` string, or ``None``."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM factors WHERE expression = ?", (expression.strip(),)
            ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_factors(
        self,
        stage: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """List factors, optionally filtered by *stage* and/or *category*.

        Quarantined factors are excluded unless ``stage=STAGE_QUARANTINED``
        is explicitly passed.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        else:
            # Exclude quarantined records by default
            clauses.append("stage != ?")
            params.append(STAGE_QUARANTINED)
        if category:
            clauses.append("category = ?")
            params.append(category)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM factors{where} ORDER BY created_at DESC"

        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_factors(self, query: str, *, include_quarantined: bool = False) -> list[dict]:
        """Free-text search across factor ``name``, ``thesis``, and ``expression``.

        Quarantined factors are excluded by default unless
        ``include_quarantined=True``.
        """
        q = f"%{query.strip()}%"
        if include_quarantined:
            sql = """
                SELECT * FROM factors
                WHERE name LIKE ? OR thesis LIKE ? OR expression LIKE ?
                ORDER BY created_at DESC
            """
            params = (q, q, q)
        else:
            sql = """
                SELECT * FROM factors
                WHERE (name LIKE ? OR thesis LIKE ? OR expression LIKE ?) AND stage != ?
                ORDER BY created_at DESC
            """
            params = (q, q, q, STAGE_QUARANTINED)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle / stage management
    # ------------------------------------------------------------------

    def update_stage(self, factor_id: int, new_stage: str) -> bool:
        """Set the stage of a factor to *new_stage*.

        Returns ``True`` if the row was updated, ``False`` if the factor
        was not found.
        """
        if new_stage not in _STAGE_ORDER:
            raise ValueError(f"Invalid stage '{new_stage}'. Must be one of {_STAGE_ORDER}")

        now = self._now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE factors SET stage = ?, updated_at = ? WHERE id = ?",
                (new_stage, now, factor_id),
            )
        updated = cur.rowcount > 0
        if updated:
            logger.info("factor_stage_updated", factor_id=factor_id, new_stage=new_stage)
        return updated

    def promote(self, factor_id: int) -> bool:
        """Promote a factor to the next stage: Proposed -> Validated -> Active.

        Returns ``True`` if promoted, ``False`` if the factor was not found
        or is already at the maximum promotable stage (Active or Deprecated).
        """
        with self._connect() as conn:
            row = conn.execute("SELECT stage FROM factors WHERE id = ?", (factor_id,)).fetchone()
        if not row:
            return False

        current = row["stage"]
        if current not in _STAGE_ORDER:
            return False

        idx = _STAGE_ORDER.index(current)
        # Cannot promote beyond Active; Deprecated is terminal
        if idx >= _STAGE_ORDER.index(STAGE_ACTIVE):
            logger.debug("factor_already_at_max_promotable_stage", factor_id=factor_id, stage=current)
            return False

        new_stage = _STAGE_ORDER[idx + 1]
        return self.update_stage(factor_id, new_stage)

    def demote(self, factor_id: int) -> bool:
        """Demote a factor: Active -> Deprecated.

        Returns ``True`` if demoted, ``False`` if the factor was not found
        or is not currently Active.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT stage FROM factors WHERE id = ?", (factor_id,)).fetchone()
        if not row:
            return False

        current = row["stage"]
        if current != STAGE_ACTIVE:
            logger.debug("cannot_demote_non_active_factor", factor_id=factor_id, stage=current)
            return False

        return self.update_stage(factor_id, STAGE_DEPRECATED)

    # ------------------------------------------------------------------
    # Quarantine
    # ------------------------------------------------------------------

    def quarantine_factor(self, factor_id: int, reason: str = "") -> bool:
        """Quarantine a factor, marking it as invalid or suspect.

        Quarantined factors are excluded from ``list_factors`` and
        ``search_factors`` by default.  They are not deleted -- the
        original record is preserved for auditing.

        Returns ``True`` if the factor was quarantined, ``False`` if the
        factor was not found.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT stage FROM factors WHERE id = ?", (factor_id,)).fetchone()
        if not row:
            return False

        now = self._now()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE factors SET stage = ?, thesis = CASE WHEN thesis = '' THEN ? ELSE thesis || ' | ' || ? END, updated_at = ? WHERE id = ?",
                (STAGE_QUARANTINED, f"[QUARANTINED] {reason}", f"[QUARANTINED] {reason}", now, factor_id),
            )
        if cur.rowcount > 0:
            logger.info("factor_quarantined", factor_id=factor_id, reason=reason)
            return True
        return False

    def quarantine_by_name_pattern(self, pattern: str, reason: str = "") -> int:
        """Quarantine all factors whose name matches a SQL LIKE pattern.

        Common patterns::

            quarantine_by_name_pattern("test_%",  "test records")
            quarantine_by_name_pattern("%_dummy",  "dummy records")
            quarantine_by_name_pattern("run_123%", "test run")

        Returns the number of factors quarantined.
        """
        now = self._now()
        reason_prefix = f"[QUARANTINED] {reason}" if reason else "[QUARANTINED]"
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE factors
                SET stage = ?,
                    thesis = CASE WHEN thesis = '' THEN ? ELSE thesis || ' | ' || ? END,
                    updated_at = ?
                WHERE name LIKE ? AND stage != ?
                """,
                (STAGE_QUARANTINED, reason_prefix, reason_prefix, now, pattern, STAGE_QUARANTINED),
            )
        count = cur.rowcount
        if count > 0:
            logger.info("factors_quarantined_by_pattern", pattern=pattern, count=count, reason=reason)
        return count

    def list_quarantined(self) -> list[dict]:
        """Return all quarantined factors."""
        return self.list_factors(stage=STAGE_QUARANTINED)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _evaluate_gates(self, metrics: dict[str, Any]) -> bool:
        """Check whether *metrics* pass all validation gates.

        Returns ``True`` if every applicable gate is satisfied.  Missing
        metrics are treated as non-failing (the gate is skipped).
        """
        icir = metrics.get("icir")
        t_stat = metrics.get("t_stat")
        positive_ratio = metrics.get("positive_ratio")
        quintile_spread = metrics.get("quintile_spread")
        mean_decay_1d = metrics.get("mean_decay_1d")
        mean_decay_5d = metrics.get("mean_decay_5d")

        if icir is not None and icir < VALIDATION_GATES["min_icir"]:
            return False
        if t_stat is not None and t_stat < VALIDATION_GATES["min_t_stat"]:
            return False
        if positive_ratio is not None and positive_ratio < VALIDATION_GATES["min_positive_ratio"]:
            return False
        if quintile_spread is not None and quintile_spread < VALIDATION_GATES["min_quintile_spread"]:
            return False

        # Decay ratio: IC at 5d should retain at least min_ratio of IC at 1d.
        if mean_decay_1d is not None and mean_decay_5d is not None:
            if abs(mean_decay_1d) > 1e-10:
                decay_ratio = mean_decay_5d / mean_decay_1d
                if decay_ratio < VALIDATION_GATES["min_ic_decay_5d_ratio"]:
                    return False

        return True

    @staticmethod
    def _evaluate_gate_metrics(metrics: dict[str, Any], gate: dict[str, float]) -> tuple[bool, str]:
        """Check *metrics* against the thresholds in *gate*.

        Returns ``(passed, reason)`` where *reason* explains the first failure.
        Missing metrics are treated as non-failing (the gate is skipped).
        """
        icir = metrics.get("icir")
        t_stat = metrics.get("t_stat")
        positive_ratio = metrics.get("positive_ratio")
        quintile_spread = metrics.get("quintile_spread")
        mean_decay_1d = metrics.get("mean_decay_1d")
        mean_decay_5d = metrics.get("mean_decay_5d")

        if icir is not None and icir < gate.get("min_icir", 0):
            return False, f"icir={icir:.4f} < min_icir={gate['min_icir']}"
        if t_stat is not None and t_stat < gate.get("min_t_stat", 0):
            return False, f"t_stat={t_stat:.4f} < min_t_stat={gate['min_t_stat']}"
        if positive_ratio is not None and positive_ratio < gate.get("min_positive_ratio", 0):
            return False, f"positive_ratio={positive_ratio:.4f} < min_positive_ratio={gate['min_positive_ratio']}"
        if quintile_spread is not None and quintile_spread < gate.get("min_quintile_spread", 0):
            return False, f"quintile_spread={quintile_spread:.6f} < min_quintile_spread={gate['min_quintile_spread']}"

        min_decay = gate.get("min_ic_decay_5d_ratio")
        if min_decay is not None and mean_decay_1d is not None and mean_decay_5d is not None:
            if abs(mean_decay_1d) > 1e-10:
                decay_ratio = mean_decay_5d / mean_decay_1d
                if decay_ratio < min_decay:
                    return False, (
                        f"IC decay 5d/1d ratio={decay_ratio:.4f} < "
                        f"min={min_decay:.4f} (decays too fast)"
                    )

        return True, ""

    def promote_to_next_gate(self, factor_id: int, validation_metrics: dict) -> tuple[bool, str]:
        """Attempt to promote a factor to the next gate level.

        Checks *validation_metrics* against the tier-specific thresholds for
        the factor's current stage.  For Gate 3 (Validated -> Active) the
        correlation with existing Active factors is also checked via
        :meth:`check_factor_correlation` if ``ic_series`` is provided in
        *validation_metrics*.

        Returns ``(success, message)`` where *message* explains why if failed.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT stage FROM factors WHERE id = ?", (factor_id,)).fetchone()
        if not row:
            return False, f"Factor {factor_id} not found"

        current_stage = row["stage"]

        # Handle legacy "Validated" factors: treat as if they passed Gate 2
        # and are eligible for Gate 3 promotion.
        if current_stage == STAGE_VALIDATED:
            gate = GATE_3_THRESHOLDS
            next_stage = STAGE_ACTIVE
        elif current_stage == STAGE_ACTIVE:
            return False, f"Factor is already at stage '{current_stage}' (no further promotion)"
        elif current_stage not in _GATE_FOR_STAGE:
            return False, f"Cannot promote factor in stage '{current_stage}'"
        else:
            gate = _GATE_FOR_STAGE[current_stage]
            idx = _STAGE_ORDER.index(current_stage)
            if idx >= _STAGE_ORDER.index(STAGE_ACTIVE):
                return False, f"Factor is already at stage '{current_stage}' (no further promotion)"
            next_stage = _STAGE_ORDER[idx + 1]

        # Gate 3 extra: correlation with active factors
        if current_stage == STAGE_VALIDATED:
            ic_series = validation_metrics.get("ic_series")
            if ic_series is not None:
                max_corr = self.check_factor_correlation(factor_id, ic_series)
                max_corr_threshold = gate.get("max_correlation_with_active", 0.7)
                if max_corr > max_corr_threshold:
                    return False, (
                        f"Factor is too correlated with an existing Active factor: "
                        f"max_corr={max_corr:.4f} > threshold={max_corr_threshold}"
                    )

        passed, reason = self._evaluate_gate_metrics(validation_metrics, gate)
        if not passed:
            return False, reason

        self.update_stage(factor_id, next_stage)
        return True, f"Promoted to {next_stage}"

    def check_factor_correlation(self, factor_id: int, new_factor_ic_series: list[float]) -> float:
        """Check correlation of a new factor's IC time series with existing Active factors.

        Returns the maximum absolute Pearson correlation between *new_factor_ic_series*
        and any Active factor's most recent validation IC series.  Used in Gate 3.
        """
        if not new_factor_ic_series:
            return 0.0

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT fv.ic, fv.factor_id FROM factor_validations fv
                INNER JOIN factors f ON f.id = fv.factor_id
                WHERE f.stage = ? AND fv.factor_id != ? AND fv.passed = 1
                ORDER BY fv.validated_at DESC
                """,
                (STAGE_ACTIVE, factor_id),
            ).fetchall()

        if not rows:
            return 0.0

        # Gather IC values from active factors.  Each row is a single IC value;
        # we treat the series of all recent validation ICs as the "IC series"
        # for correlation purposes.
        max_corr = 0.0
        active_ics = [float(r["ic"]) for r in rows if r["ic"] is not None]
        if not active_ics:
            return 0.0

        # Build paired lists of equal length by truncating to the shorter one
        n = min(len(new_factor_ic_series), len(active_ics))
        if n < 3:
            return 0.0

        xs = new_factor_ic_series[:n]
        ys = active_ics[:n]

        # Compute Pearson correlation manually (avoids numpy/scipy dependency)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

        if std_x < 1e-15 or std_y < 1e-15:
            return 0.0

        corr = cov / (std_x * std_y)
        max_corr = abs(corr)

        return max_corr

    def record_validation(self, factor_id: int, market: str, metrics: dict[str, Any]) -> int:
        """Record a validation run for *factor_id* on *market*.

        *metrics* keys recognised (all optional except those you want gates
        to check): ``ic``, ``rank_ic``, ``icir``, ``t_stat``,
        ``positive_ratio``, ``mean_decay_1d``, ``mean_decay_5d``,
        ``quintile_spread``.

        Returns the new validation row id.
        """
        market = str(market).strip().lower()
        if not market:
            raise ValueError("market is required")

        passed = self._evaluate_gates(metrics)
        now = self._now()

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO factor_validations
                    (factor_id, market, ic, rank_ic, icir, t_stat,
                     positive_ratio, mean_decay_1d, mean_decay_5d,
                     quintile_spread, passed, validated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    factor_id,
                    market,
                    metrics.get("ic"),
                    metrics.get("rank_ic"),
                    metrics.get("icir"),
                    metrics.get("t_stat"),
                    metrics.get("positive_ratio"),
                    metrics.get("mean_decay_1d"),
                    metrics.get("mean_decay_5d"),
                    metrics.get("quintile_spread"),
                    int(passed),
                    now,
                ),
            )
            val_id = cur.lastrowid
        logger.info(
            "factor_validation_recorded",
            factor_id=factor_id,
            market=market,
            passed=passed,
            validation_id=val_id,
        )
        return val_id

    def get_validations(self, factor_id: int) -> list[dict]:
        """Return all validation records for *factor_id*, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM factor_validations WHERE factor_id = ? ORDER BY validated_at DESC",
                (factor_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def is_validated(self, factor_id: int, market: str) -> bool:
        """Return ``True`` if *factor_id* has at least one passing validation for *market*."""
        market = str(market).strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM factor_validations
                WHERE factor_id = ? AND market = ? AND passed = 1
                LIMIT 1
                """,
                (factor_id, market),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def record_usage(
        self,
        factor_id: int,
        strategy_config: str,
        weight: float = 1.0,
    ) -> None:
        """Record that *factor_id* is used by *strategy_config* with *weight*."""
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO factor_usage (factor_id, strategy_config, weight, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (factor_id, strategy_config, weight, now),
            )
        logger.info("factor_usage_recorded", factor_id=factor_id, strategy_config=strategy_config)

    def get_usage(self, factor_id: int) -> list[dict]:
        """Return all usage records for *factor_id*."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM factor_usage WHERE factor_id = ? ORDER BY added_at DESC",
                (factor_id,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return summary statistics across the registry.

        Includes counts by stage, category, direction, and validation totals.
        """
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM factors").fetchone()[0]

            stage_rows = conn.execute(
                "SELECT stage, COUNT(*) AS cnt FROM factors GROUP BY stage"
            ).fetchall()
            by_stage = {r["stage"]: r["cnt"] for r in stage_rows}

            cat_rows = conn.execute(
                "SELECT category, COUNT(*) AS cnt FROM factors GROUP BY category"
            ).fetchall()
            by_category = {r["category"]: r["cnt"] for r in cat_rows}

            dir_rows = conn.execute(
                "SELECT direction, COUNT(*) AS cnt FROM factors GROUP BY direction"
            ).fetchall()
            by_direction = {r["direction"]: r["cnt"] for r in dir_rows}

            total_val = conn.execute("SELECT COUNT(*) FROM factor_validations").fetchone()[0]
            total_passed = conn.execute(
                "SELECT COUNT(*) FROM factor_validations WHERE passed = 1"
            ).fetchone()[0]
            total_usage = conn.execute("SELECT COUNT(*) FROM factor_usage").fetchone()[0]

        return {
            "total_factors": total,
            "by_stage": by_stage,
            "by_category": by_category,
            "by_direction": by_direction,
            "total_validations": total_val,
            "total_passed_validations": total_passed,
            "total_usage_records": total_usage,
        }
