from __future__ import annotations

import json
import math
import time
from pathlib import Path

import yaml

from src.assistant.base_index import BaseIndex
from src.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Validated stage enum -- fail-closed: only known stages are accepted.
# ---------------------------------------------------------------------------
_MODEL_STAGES = {
    "CANDIDATE",  # Initial: research output, not gate-checked
    "STAGING",  # Walk-forward passed, but not yet fully validated
    "RECOMMENDED",  # Fully validated: inference + reconstruction + walk-forward passed
    "REJECTED",  # Failed gates
    "SUPERSEDED",  # Replaced by a newer model
}

# Valid promotion transitions (from -> set of allowed targets).
_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "CANDIDATE": {"STAGING", "REJECTED"},
    "STAGING": {"RECOMMENDED", "REJECTED", "SUPERSEDED"},
    "RECOMMENDED": {"SUPERSEDED", "REJECTED"},
    "REJECTED": {"CANDIDATE"},  # allow re-entry after fixes
    "SUPERSEDED": set(),  # terminal
}

# Minimum gate evidence required per stage.
_STAGE_GATE_REQUIREMENTS: dict[str, set[str]] = {
    "CANDIDATE": set(),  # no gates required
    "STAGING": {"walk_forward_passed"},  # WF must pass
    "RECOMMENDED": {"walk_forward_passed", "inference_passed"},  # WF + inference
    # REJECTED / SUPERSEDED have no upward requirements
}


def _normalize_stage(value: object) -> str:
    stage = str(value or "CANDIDATE").upper().strip()
    if stage not in _MODEL_STAGES:
        raise ValueError(
            f"Unknown model stage: {stage or '<empty>'}. Expected one of {sorted(_MODEL_STAGES)}"
        )
    return stage


def validate_stage_for_registration(entry: dict) -> str:
    """Return the *safe* stage for a registration entry.

    Fail-closed logic:
    - If walk-forward data is missing or fails, force CANDIDATE (never STAGING/RECOMMENDED).
    - If metrics are missing or non-finite, force CANDIDATE.
    - If the requested stage is STAGING but walk-forward didn't pass, force CANDIDATE.
    - If the requested stage is RECOMMENDED but walk-forward or inference didn't pass,
      force CANDIDATE.
    """
    requested = str(entry.get("stage") or "CANDIDATE").upper().strip()

    # Extract walk-forward data from the entry
    wf = entry.get("walk_forward") or {}
    if isinstance(wf, dict):
        wf_passed = wf.get("gate_passed") is True
    else:
        wf_passed = False

    # Also check top-level gate_passed (propagated by register_model)
    if entry.get("gate_passed") is False:
        wf_passed = False

    # Check metrics: must be non-empty finite numbers
    backtest = entry.get("backtest") or {}
    metrics = backtest.get("metrics") if isinstance(backtest, dict) else {}
    has_valid_metrics = _has_finite_metrics(metrics)

    # Enforce fail-closed rules
    if requested in ("STAGING", "RECOMMENDED"):
        if not wf_passed:
            logger.warning(
                "Stage downgraded: walk-forward not passed",
                requested=requested,
                version_id=entry.get("id"),
            )
            return "CANDIDATE"
        if not has_valid_metrics:
            logger.warning(
                "Stage downgraded: missing or non-finite metrics",
                requested=requested,
                version_id=entry.get("id"),
            )
            return "CANDIDATE"

    if requested == "RECOMMENDED":
        # RECOMMENDED also requires inference pass (checked via entry flags)
        inference_passed = entry.get("inference_passed")
        if inference_passed is not True:
            logger.warning(
                "Stage downgraded: inference not passed for RECOMMENDED",
                version_id=entry.get("id"),
            )
            return "CANDIDATE"

    return requested


def _has_finite_metrics(metrics: object) -> bool:
    """Return True if metrics is a non-empty dict with at least one finite numeric value."""
    if not isinstance(metrics, dict) or not metrics:
        return False
    for v in metrics.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return True
    return False


def validate_evidence_binding(entry: dict) -> list[str]:
    """Check that evidence in *entry* is self-consistent and bound to this model.

    Returns a list of validation error strings (empty == valid).
    """
    errors: list[str] = []

    # 1. Metrics must be non-empty finite numbers
    backtest = entry.get("backtest") or {}
    metrics = backtest.get("metrics") if isinstance(backtest, dict) else {}
    if not _has_finite_metrics(metrics):
        errors.append("Metrics are missing or contain no finite numeric values")

    # 2. Walk-forward data, if present, must have model_id matching entry id
    wf = entry.get("walk_forward")
    if isinstance(wf, dict):
        wf_model_id = wf.get("model_id")
        entry_id = entry.get("id")
        if wf_model_id and entry_id and wf_model_id != entry_id:
            errors.append(
                f"Walk-forward evidence belongs to model {wf_model_id}, not to {entry_id}"
            )

    # 3. Artifact ID, if present, must be a non-empty string
    artifact_id = entry.get("artifact_id")
    if artifact_id is not None and not str(artifact_id).strip():
        errors.append("artifact_id is present but empty")

    # 4. market must be non-empty
    market = str(entry.get("market") or "").strip()
    if not market:
        errors.append("market is empty")

    return errors


def _safe_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        logger.debug("Failed to serialize value to JSON", exc_info=True)
        return "{}"


class ModelRegistryIndex(BaseIndex):
    """
    Minimal SQLite-backed model registry index.

    Source-of-truth remains `models/model_list.yaml` for now; this index enables fast
    queries and supports dashboard/server features without scanning YAML each time.
    """

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS model_versions (
                    id TEXT PRIMARY KEY,
                    tag TEXT,
                    name TEXT,
                    market TEXT,
                    model_type TEXT,
                    path TEXT,
                    run_id TEXT,
                    created_at TEXT,
                    stage TEXT DEFAULT 'STAGING',
                    description TEXT,
                    params_json TEXT,
                    metrics_json TEXT,
                    feature_importance_json TEXT,
                    payload_json TEXT,
                    created_ts REAL
                )
                """
            )
            # Migration for existing DBs
            cursor = conn.execute("PRAGMA table_info(model_versions)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "feature_importance_json" not in cols:
                conn.execute("ALTER TABLE model_versions ADD COLUMN feature_importance_json TEXT")
            if "stage" not in cols:
                conn.execute("ALTER TABLE model_versions ADD COLUMN stage TEXT DEFAULT 'STAGING'")
                conn.execute(
                    """
                    UPDATE model_versions
                    SET stage = CASE
                        WHEN upper(description) LIKE '%RECOMMENDED%' THEN 'RECOMMENDED'
                        ELSE 'STAGING'
                    END
                    """
                )

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_versions_run_id ON model_versions(run_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_versions_market ON model_versions(market)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_versions_created_at ON model_versions(created_at)"
            )

    def upsert_entry(self, entry: dict, *, validate: bool = True) -> bool:
        """Insert or update a model registry entry.

        Parameters
        ----------
        entry : dict
            The model entry to upsert.
        validate : bool
            When True (default), apply fail-closed stage validation via
            ``validate_stage_for_registration``.  Set to False for bulk
            YAML imports where the stage is trusted.
        """
        if not isinstance(entry, dict):
            return False
        version_id = str(entry.get("id") or "").strip()
        if not version_id:
            return False

        tag = str(entry.get("tag") or "")
        name = str(entry.get("name") or tag or version_id)
        market = str(entry.get("market") or "")
        model_type = str(entry.get("type") or entry.get("model_type") or "")
        path = str(entry.get("path") or "")
        run_id = str(entry.get("run_id") or "")
        created_at = str(entry.get("created_at") or "")

        # Fail-closed stage validation: downgrade if gates not satisfied
        if validate:
            stage = validate_stage_for_registration(entry)
        else:
            stage = _normalize_stage(entry.get("stage"))

        description = str(entry.get("description") or "")

        params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
        metrics = (
            (entry.get("backtest") or {}).get("metrics")
            if isinstance(entry.get("backtest"), dict)
            else {}
        )
        if not isinstance(metrics, dict):
            metrics = {}

        feature_importance = entry.get("feature_importance") or {}
        if not isinstance(feature_importance, dict):
            feature_importance = {}

        now = time.time()
        payload_json = _safe_json(entry)
        params_json = _safe_json(params)
        metrics_json = _safe_json(metrics)
        feature_importance_json = _safe_json(feature_importance)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_versions (
                    id, tag, name, market, model_type, path, run_id, created_at, stage, description,
                    params_json, metrics_json, feature_importance_json, payload_json, created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    tag=excluded.tag,
                    name=excluded.name,
                    market=excluded.market,
                    model_type=excluded.model_type,
                    path=excluded.path,
                    run_id=excluded.run_id,
                    created_at=excluded.created_at,
                    stage=excluded.stage,
                    description=excluded.description,
                    params_json=excluded.params_json,
                    metrics_json=excluded.metrics_json,
                    feature_importance_json=excluded.feature_importance_json,
                    payload_json=excluded.payload_json
                """,
                (
                    version_id,
                    tag,
                    name,
                    market,
                    model_type,
                    path,
                    run_id,
                    created_at,
                    stage,
                    description,
                    params_json,
                    metrics_json,
                    feature_importance_json,
                    payload_json,
                    now,
                ),
            )
        return True

    def upsert_from_model_list_yaml(
        self, yaml_path: str | Path, *, project_root: str | Path | None = None
    ) -> int:
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            return 0
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("Failed to parse model_list YAML", path=str(yaml_path), exc_info=True)
            return 0

        models = data.get("models", [])
        if not isinstance(models, list):
            return 0

        n = 0
        for entry in models:
            if not isinstance(entry, dict):
                continue
            if self.upsert_entry(entry):
                n += 1
        return n

    def list_versions(self, *, limit: int = 100, market: str | None = None) -> list[dict]:
        limit = int(limit) if limit is not None else 100
        if limit <= 0:
            return []

        market_s = str(market).strip().lower() if market else ""
        if market_s:
            sql = "SELECT * FROM model_versions WHERE lower(market) = ? ORDER BY created_at DESC, created_ts DESC LIMIT ?"
            params = (market_s, limit)
        else:
            sql = "SELECT * FROM model_versions ORDER BY created_at DESC, created_ts DESC LIMIT ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_version(self, version_id: str) -> dict | None:
        version_id = str(version_id or "").strip()
        if not version_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_versions WHERE id = ?", (version_id,)
            ).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        for k in (
            "formats_json",
            "paths_json",
            "meta_json",
            "params_json",
            "metrics_json",
            "feature_importance_json",
        ):
            raw = out.get(k)
            if not raw:
                continue
            try:
                out[k.replace("_json", "")] = json.loads(raw)
            except Exception:
                logger.debug(
                    "Failed to decode JSON field", field=k, version_id=version_id, exc_info=True
                )
                out[k.replace("_json", "")] = {}
        payload = {}
        raw_payload = out.get("payload_json")
        if raw_payload:
            try:
                decoded = json.loads(raw_payload)
                payload = decoded if isinstance(decoded, dict) else {}
            except Exception:
                logger.debug(
                    "Failed to decode model payload",
                    version_id=version_id,
                    exc_info=True,
                )
        out["payload"] = payload
        for key, value in payload.items():
            out.setdefault(key, value)
        return out

    def update_stage(self, version_id: str, stage: str) -> bool:
        version_id = str(version_id or "").strip()
        stage = _normalize_stage(stage)
        if not version_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM model_versions WHERE id = ?", (version_id,)
            ).fetchone()
            if row is None:
                return False
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload["stage"] = stage
            cur = conn.execute(
                """
                UPDATE model_versions
                SET stage = ?, description = ?, payload_json = ?
                WHERE id = ?
                """,
                (stage, f"Stage: {stage}", _safe_json(payload), version_id),
            )
        return bool(cur.rowcount and cur.rowcount > 0)

    def delete_version(self, version_id: str) -> bool:
        version_id = str(version_id or "").strip()
        if not version_id:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM model_versions WHERE id = ?", (version_id,))
        return bool(cur.rowcount and cur.rowcount > 0)

    def delete_versions_for_run(self, run_id: str) -> bool:
        run_id = str(run_id or "").strip()
        if not run_id:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM model_versions WHERE run_id = ?", (run_id,))
        return bool(cur.rowcount and cur.rowcount > 0)

    def promote_model(
        self,
        version_id: str,
        *,
        target_stage: str,
        evidence: dict | None = None,
    ) -> dict:
        """Atomically promote a model to *target_stage* if gates are satisfied.

        Returns ``{"ok": True, "stage": <new_stage>}`` on success, or
        ``{"ok": False, "reason": <str>}`` on failure.  When the DB supports
        transactions (SQLite does), the update is atomic -- either all columns
        change or nothing changes.

        Parameters
        ----------
        version_id : str
            The model version ID to promote.
        target_stage : str
            The desired stage (must be in ``_MODEL_STAGES``).
        evidence : dict, optional
            Gate evidence keyed by gate name.  Expected keys:
            - ``walk_forward_passed`` (bool)
            - ``inference_passed`` (bool)
            - ``reconstruction_passed`` (bool)
        """
        version_id = str(version_id or "").strip()
        if not version_id:
            return {"ok": False, "reason": "version_id is empty"}

        try:
            target = _normalize_stage(target_stage)
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}

        evidence = evidence or {}

        # 1. Fetch current stage
        with self._connect() as conn:
            row = conn.execute(
                "SELECT stage, payload_json FROM model_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "reason": f"Model {version_id} not found"}

            current_stage = row["stage"] or "CANDIDATE"

        # 2. Validate transition
        allowed = _STAGE_TRANSITIONS.get(current_stage, set())
        if target not in allowed:
            return {
                "ok": False,
                "reason": (
                    f"Invalid transition: {current_stage} -> {target}. "
                    f"Allowed targets from {current_stage}: {sorted(allowed) or '(none)'}"
                ),
            }

        # 3. Validate gate evidence for the target stage
        required_gates = _STAGE_GATE_REQUIREMENTS.get(target, set())
        missing = []
        for gate in required_gates:
            if not evidence.get(gate):
                missing.append(gate)
        if missing:
            return {
                "ok": False,
                "reason": f"Missing required gate evidence for {target}: {sorted(missing)}",
            }

        # 4. Atomic update (single transaction)
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload["stage"] = target
        payload["promoted_from"] = current_stage
        payload["promotion_evidence"] = evidence

        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE model_versions
                SET stage = ?, description = ?, payload_json = ?
                WHERE id = ?
                """,
                (
                    target,
                    f"Stage: {target} (promoted from {current_stage})",
                    _safe_json(payload),
                    version_id,
                ),
            )
            if not cur.rowcount:
                return {"ok": False, "reason": "Update affected zero rows"}

        logger.info(
            "Model promoted",
            version_id=version_id,
            from_stage=current_stage,
            to_stage=target,
        )
        return {"ok": True, "stage": target, "previous_stage": current_stage}
