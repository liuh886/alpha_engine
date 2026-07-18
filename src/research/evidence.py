"""Lightweight evidence aggregation for research conclusions.

The ledger is intentionally read-only and dependency-light: it reads JSON
artifacts and SQLite registry rows without initializing Qlib, MLflow, or model
runtime components.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class EvidenceStatus(str, Enum):
    """Availability status for a piece of evidence."""

    FOUND = "found"
    PARTIAL = "partial"
    MISSING = "missing"
    ERROR = "error"


@dataclass(frozen=True)
class EvidenceSource:
    """A source consulted while building an evidence bundle."""

    name: str
    status: EvidenceStatus
    path: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "path": self.path,
            "detail": self.detail,
        }


@dataclass
class EvidenceBundle:
    """Evidence summary for a research/model/factor conclusion."""

    subject_type: str
    subject_id: str
    generated_at: str
    sources: list[EvidenceSource] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    decision: str | None = None
    completeness_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "generated_at": self.generated_at,
            "sources": [source.to_dict() for source in self.sources],
            "metrics": self.metrics,
            "warnings": list(self.warnings),
            "decision": self.decision,
            "completeness_score": self.completeness_score,
        }


class EvidenceLedger:
    """Build minimal evidence bundles from existing Alpha Engine artifacts."""

    def __init__(
        self,
        artifacts_dir: str | Path | None = None,
        factor_db_path: str | Path | None = None,
        model_list_path: str | Path | None = None,
    ) -> None:
        if artifacts_dir is None:
            from src.common.paths import ARTIFACTS_DIR

            artifacts_dir = ARTIFACTS_DIR
        self.artifacts_dir = Path(artifacts_dir)
        self.factor_db_path = (
            Path(factor_db_path)
            if factor_db_path is not None
            else self.artifacts_dir / "factor_registry.db"
        )
        self.model_list_path = (
            Path(model_list_path)
            if model_list_path is not None
            else self.artifacts_dir / "models" / "model_list.yaml"
        )
        self._last_bundle: EvidenceBundle | None = None

    def build_bundle(
        self,
        subject_type: str,
        subject_id: str,
        market: str | None = None,
    ) -> EvidenceBundle:
        """Build an evidence bundle for a known subject type."""
        normalized_type = subject_type.strip().lower()
        if normalized_type in {"research_run", "research-run", "run"}:
            return self.from_research_run(subject_id)
        if normalized_type == "factor":
            return self.from_factor(subject_id, market=market)
        if normalized_type in {"model", "model_version", "model-version"}:
            return self.from_model(subject_id)

        bundle = self._empty_bundle(subject_type=normalized_type, subject_id=subject_id)
        bundle.warnings.append(f"Unsupported evidence subject_type: {subject_type}")
        bundle.sources.append(
            EvidenceSource(
                name="evidence_ledger",
                status=EvidenceStatus.MISSING,
                detail="No reader is registered for this subject type.",
            )
        )
        bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
        self._last_bundle = bundle
        return bundle

    def from_research_run(self, run_id: str) -> EvidenceBundle:
        """Build evidence from ``artifacts/research_runs/{run_id}.json``."""
        bundle = self._empty_bundle(subject_type="research_run", subject_id=run_id)
        run_path = self.artifacts_dir / "research_runs" / f"{run_id}.json"

        if not run_path.exists():
            bundle.sources.append(
                EvidenceSource(
                    name="research_run_artifact",
                    status=EvidenceStatus.MISSING,
                    path=str(run_path),
                )
            )
            bundle.warnings.append(f"Research run artifact not found: {run_path}")
            bundle.decision = "missing_artifact"
            bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
            self._last_bundle = bundle
            return bundle

        try:
            data = self._read_json(run_path)
        except (OSError, json.JSONDecodeError) as exc:
            bundle.sources.append(
                EvidenceSource(
                    name="research_run_artifact",
                    status=EvidenceStatus.ERROR,
                    path=str(run_path),
                    detail=str(exc),
                )
            )
            bundle.warnings.append(f"Research run artifact could not be read: {exc}")
            bundle.decision = "artifact_error"
            bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
            self._last_bundle = bundle
            return bundle

        bundle.sources.append(
            EvidenceSource(
                name="research_run_artifact",
                status=EvidenceStatus.FOUND,
                path=str(run_path),
            )
        )
        bundle.metrics = self._research_run_metrics(data)
        bundle.decision = self._resolve_promotion_decision(run_path)
        bundle.warnings.extend(self._research_run_warnings(data))
        bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
        self._last_bundle = bundle
        return bundle

    def from_factor(
        self, factor_id_or_name: str | int, market: str | None = None
    ) -> EvidenceBundle:
        """Build evidence from the factor registry and optional factor artifact."""
        subject_id = str(factor_id_or_name)
        bundle = self._empty_bundle(subject_type="factor", subject_id=subject_id)

        artifact_path = self.artifacts_dir / "factors" / f"{subject_id}.json"
        if artifact_path.exists():
            bundle.sources.append(
                EvidenceSource(
                    name="factor_artifact",
                    status=EvidenceStatus.FOUND,
                    path=str(artifact_path),
                )
            )
            try:
                bundle.metrics["artifact"] = self._read_json(artifact_path)
            except (OSError, json.JSONDecodeError) as exc:
                bundle.sources[-1] = EvidenceSource(
                    name="factor_artifact",
                    status=EvidenceStatus.ERROR,
                    path=str(artifact_path),
                    detail=str(exc),
                )
                bundle.warnings.append(f"Factor artifact could not be read: {exc}")
        else:
            bundle.sources.append(
                EvidenceSource(
                    name="factor_artifact",
                    status=EvidenceStatus.MISSING,
                    path=str(artifact_path),
                )
            )
            bundle.warnings.append(f"Factor artifact not found: {artifact_path}")

        factor_data = self._read_factor_registry(subject_id, market=market)
        bundle.sources.append(factor_data["source"])
        bundle.warnings.extend(factor_data["warnings"])
        if factor_data["metrics"]:
            bundle.metrics.update(factor_data["metrics"])
        bundle.decision = self._factor_decision(bundle.metrics)
        bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
        self._last_bundle = bundle
        return bundle

    def from_model(self, version_id: str) -> EvidenceBundle:
        """Build model evidence from ``artifacts/models/model_list.yaml``."""
        bundle = self._empty_bundle(subject_type="model", subject_id=version_id)
        if not self.model_list_path.exists():
            bundle.sources.append(
                EvidenceSource(
                    name="model_registry",
                    status=EvidenceStatus.MISSING,
                    path=str(self.model_list_path),
                )
            )
            bundle.warnings.append(f"Model registry not found: {self.model_list_path}")
            bundle.decision = "missing_artifact"
            bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
            self._last_bundle = bundle
            return bundle

        try:
            data = yaml.safe_load(self.model_list_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            bundle.sources.append(
                EvidenceSource(
                    name="model_registry",
                    status=EvidenceStatus.ERROR,
                    path=str(self.model_list_path),
                    detail=str(exc),
                )
            )
            bundle.warnings.append(f"Model registry could not be read: {exc}")
            bundle.decision = "artifact_error"
            bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
            self._last_bundle = bundle
            return bundle

        models = data.get("models", []) if isinstance(data, dict) else []
        model = next((item for item in models if str(item.get("id")) == str(version_id)), None)
        if model is None:
            bundle.sources.append(
                EvidenceSource(
                    name="model_registry",
                    status=EvidenceStatus.MISSING,
                    path=str(self.model_list_path),
                )
            )
            bundle.warnings.append(f"Model version not found in registry: {version_id}")
            bundle.decision = "missing_model"
            bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
            self._last_bundle = bundle
            return bundle

        bundle.sources.append(
            EvidenceSource(
                name="model_registry",
                status=EvidenceStatus.FOUND,
                path=str(self.model_list_path),
            )
        )
        bundle.metrics["model"] = model
        bundle.decision = str(model.get("stage") or model.get("description") or "registered")
        if not model.get("walk_forward") and model.get("gate_passed") is not True:
            bundle.warnings.append("Model registry entry has no explicit walk-forward evidence.")
        bundle.completeness_score = self._score(bundle.sources, bundle.warnings)
        self._last_bundle = bundle
        return bundle

    def to_dict(self) -> dict[str, Any]:
        """Return the most recently built bundle as a JSON-serializable dict."""
        if self._last_bundle is None:
            return {
                "artifacts_dir": str(self.artifacts_dir),
                "factor_db_path": str(self.factor_db_path),
                "model_list_path": str(self.model_list_path),
                "last_bundle": None,
            }
        return self._last_bundle.to_dict()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _empty_bundle(self, subject_type: str, subject_id: str) -> EvidenceBundle:
        return EvidenceBundle(
            subject_type=subject_type,
            subject_id=str(subject_id),
            generated_at=self._now(),
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {"value": data}
        return data

    @staticmethod
    def _research_run_metrics(data: dict[str, Any]) -> dict[str, Any]:
        metric_keys = (
            "market",
            "status",
            "n_steps",
            "n_completed",
            "n_failed",
            "total_duration_seconds",
            "created_at",
            "completed_at",
        )
        metrics = {key: data.get(key) for key in metric_keys if key in data}
        failed_steps = [
            step.get("name")
            for step in data.get("steps", [])
            if isinstance(step, dict) and step.get("status") == "failed"
        ]
        if failed_steps:
            metrics["failed_steps"] = failed_steps
        return metrics

    @staticmethod
    def _research_run_warnings(data: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        if data.get("status") == "failed":
            warnings.append("Research run failed.")
        for step in data.get("steps", []):
            if isinstance(step, dict) and step.get("error"):
                name = step.get("name", "unknown")
                warnings.append(f"Step {name} error: {step['error']}")
        return warnings

    @staticmethod
    def _resolve_promotion_decision(run_path: Path) -> str | None:
        """Return a canonical promotion decision status, never a legacy string.

        Checks the run-specific artifact directory for ``promotion_decision.json``.
        Legacy strings such as ``"deploy"``, ``"promote"``, or ``"DEPLOY"``
        are never treated as authoritative — they are downgraded to
        ``"non_promoted:legacy"``.
        """
        promotion_path = run_path.parent / run_path.stem / "promotion_decision.json"
        if promotion_path.is_file():
            try:
                from src.research.promotion_consumers import load_promotion_payload

                payload = load_promotion_payload(promotion_path)
                if payload["subject_id"] != run_path.stem:
                    return "invalid_promotion_artifact:subject_mismatch"
                return str(payload["status"])
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                return "invalid_promotion_artifact"
        # No canonical decision found — never fall back to legacy recommendation.
        return "non_promoted:no_canonical_decision"

    def _read_factor_registry(self, subject_id: str, market: str | None = None) -> dict[str, Any]:
        if not self.factor_db_path.exists():
            return {
                "source": EvidenceSource(
                    name="factor_registry",
                    status=EvidenceStatus.MISSING,
                    path=str(self.factor_db_path),
                ),
                "metrics": {},
                "warnings": [f"Factor registry database not found: {self.factor_db_path}"],
            }

        try:
            with sqlite3.connect(self.factor_db_path) as conn:
                conn.row_factory = sqlite3.Row
                factor = self._lookup_factor(conn, subject_id)
                if factor is None:
                    return {
                        "source": EvidenceSource(
                            name="factor_registry",
                            status=EvidenceStatus.MISSING,
                            path=str(self.factor_db_path),
                        ),
                        "metrics": {},
                        "warnings": [f"Factor not found in registry: {subject_id}"],
                    }
                validations = self._lookup_validations(conn, factor["id"], market=market)
                usage = self._lookup_usage(conn, factor["id"])
        except sqlite3.Error as exc:
            return {
                "source": EvidenceSource(
                    name="factor_registry",
                    status=EvidenceStatus.ERROR,
                    path=str(self.factor_db_path),
                    detail=str(exc),
                ),
                "metrics": {},
                "warnings": [f"Factor registry could not be read: {exc}"],
            }

        warnings = []
        if market and not validations:
            warnings.append(f"No factor validation found for market: {market}")
        elif not validations:
            warnings.append("No factor validations found.")

        return {
            "source": EvidenceSource(
                name="factor_registry",
                status=EvidenceStatus.FOUND,
                path=str(self.factor_db_path),
            ),
            "metrics": {
                "factor": dict(factor),
                "latest_validation": dict(validations[0]) if validations else None,
                "validation_count": len(validations),
                "usage_count": len(usage),
            },
            "warnings": warnings,
        }

    @staticmethod
    def _lookup_factor(conn: sqlite3.Connection, subject_id: str) -> sqlite3.Row | None:
        if subject_id.isdigit():
            row = conn.execute("SELECT * FROM factors WHERE id = ?", (int(subject_id),)).fetchone()
            if row is not None:
                return row
        return conn.execute("SELECT * FROM factors WHERE name = ?", (subject_id,)).fetchone()

    @staticmethod
    def _lookup_validations(
        conn: sqlite3.Connection,
        factor_id: int,
        market: str | None = None,
    ) -> list[sqlite3.Row]:
        params: list[Any] = [factor_id]
        where = "factor_id = ?"
        if market:
            where += " AND market = ?"
            params.append(market.strip().lower())
        return conn.execute(
            f"SELECT * FROM factor_validations WHERE {where} ORDER BY validated_at DESC",
            tuple(params),
        ).fetchall()

    @staticmethod
    def _lookup_usage(conn: sqlite3.Connection, factor_id: int) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT * FROM factor_usage WHERE factor_id = ? ORDER BY added_at DESC",
            (factor_id,),
        ).fetchall()

    @staticmethod
    def _factor_decision(metrics: dict[str, Any]) -> str | None:
        factor = metrics.get("factor")
        if isinstance(factor, dict) and factor.get("stage"):
            return str(factor["stage"])
        latest_validation = metrics.get("latest_validation")
        if isinstance(latest_validation, dict):
            return "validation_passed" if latest_validation.get("passed") else "validation_failed"
        return "insufficient_evidence"

    @staticmethod
    def _score(sources: list[EvidenceSource], warnings: list[str]) -> float:
        if not sources:
            return 0.0
        weights = {
            EvidenceStatus.FOUND: 1.0,
            EvidenceStatus.PARTIAL: 0.5,
            EvidenceStatus.MISSING: 0.0,
            EvidenceStatus.ERROR: 0.0,
        }
        base = sum(weights[source.status] for source in sources) / len(sources)
        penalty = min(0.4, len(warnings) * 0.1)
        return round(max(0.0, base - penalty), 3)
