"""Evidence-complete cumulative factor knowledge registry.

This module intentionally lives beside the legacy :mod:`factor_registry`.
It creates additive v2 tables in the same SQLite database so existing APIs can
continue to read legacy rows while new research uses fail-closed identities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.assistant.base_index import BaseIndex

FACTOR_STATUSES = {
    "legacy_unverified",
    "data_blocked",
    "rejected",
    "market_specific_clue",
    "candidate",
    "redundant",
    "independent_validation_required",
    "retired",
}

INFORMATION_FAMILIES = {
    "price_trend",
    "risk",
    "valuation",
    "quality",
    "growth",
    "revisions",
    "event",
    "flow",
    "composite",
    "other",
}

SERIES_KINDS = {"score", "portfolio_return", "selection"}

AUTHORITATIVE_EVIDENCE_FIELDS = (
    "market",
    "universe_version",
    "benchmark",
    "horizon_sessions",
    "provider_identity",
    "data_validity_level",
    "development_start",
    "development_end",
    "falsification_start",
    "falsification_end",
    "reserved_start",
    "cost_bps",
    "execution_contract",
    "evidence_manifest_hash",
)

AUTHORITATIVE_EVALUATION_METRICS = (
    "after_cost_return",
    "benchmark_relative_return",
    "max_drawdown",
    "downside_capture",
    "annual_turnover",
    "average_holding_sessions",
    "max_single_symbol_concentration",
    "coverage_ratio",
    "development_falsification_stability",
)

LEGACY_CATEGORY_TO_FAMILY = {
    "momentum": "price_trend",
    "mean_reversion": "price_trend",
    "technical": "price_trend",
    "volatility": "risk",
    "risk": "risk",
    "quality": "quality",
    "growth": "growth",
    "valuation": "valuation",
    "volume": "flow",
    "cross_field": "composite",
    "composite": "composite",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _require_nonempty(payload: Mapping[str, Any], fields: Sequence[str], *, label: str) -> None:
    missing = [field for field in fields if payload.get(field) in (None, "")]
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(missing)}")


def _json_or_empty(value: Any) -> str:
    if value in (None, ""):
        value = {}
    return _canonical_json(value if isinstance(value, Mapping) else {"value": value})


@dataclass(frozen=True)
class FactorCardInput:
    stable_factor_key: str
    factor_version: str
    name: str
    canonical_definition: str
    information_family: str
    update_frequency: str
    availability_lag_days: int
    transformation: str
    orientation: str
    neutralization: str
    thesis: str
    code_identity: str
    status: str = "candidate"
    spec_path: str = ""
    source_report_path: str = ""
    source_kind: str = "native_v2"
    source_ref: str = ""


class FactorKnowledgeRegistry(BaseIndex):
    """Authoritative factor cards, evidence, evaluations, and relationships."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from src.common.paths import ARTIFACTS_DIR

            db_path = ARTIFACTS_DIR / "factor_registry.db"
        super().__init__(db_path=db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS factor_cards_v2 (
                    card_id TEXT PRIMARY KEY,
                    stable_factor_key TEXT NOT NULL,
                    factor_version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    canonical_definition TEXT NOT NULL,
                    information_family TEXT NOT NULL,
                    update_frequency TEXT NOT NULL,
                    availability_lag_days INTEGER NOT NULL,
                    transformation TEXT NOT NULL,
                    orientation TEXT NOT NULL,
                    neutralization TEXT NOT NULL,
                    thesis TEXT NOT NULL,
                    code_identity TEXT NOT NULL,
                    spec_path TEXT NOT NULL DEFAULT '',
                    source_report_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    source_kind TEXT NOT NULL DEFAULT 'native_v2',
                    source_ref TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(stable_factor_key, factor_version),
                    UNIQUE(source_kind, source_ref)
                );

                CREATE TABLE IF NOT EXISTS factor_evidence_v2 (
                    evidence_id TEXT PRIMARY KEY,
                    card_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    universe_version TEXT NOT NULL,
                    benchmark TEXT NOT NULL,
                    horizon_sessions INTEGER NOT NULL,
                    provider_identity TEXT NOT NULL,
                    data_validity_level TEXT NOT NULL,
                    development_start TEXT NOT NULL,
                    development_end TEXT NOT NULL,
                    falsification_start TEXT NOT NULL,
                    falsification_end TEXT NOT NULL,
                    reserved_start TEXT NOT NULL,
                    reserved_end TEXT NOT NULL DEFAULT '',
                    cost_bps REAL,
                    execution_contract TEXT NOT NULL,
                    evidence_manifest_hash TEXT NOT NULL,
                    authoritative INTEGER NOT NULL DEFAULT 0,
                    decision_status TEXT NOT NULL,
                    failure_class TEXT NOT NULL DEFAULT '',
                    lessons_learned TEXT NOT NULL DEFAULT '',
                    source_kind TEXT NOT NULL DEFAULT 'native_v2',
                    source_ref TEXT NOT NULL DEFAULT '',
                    identity_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(card_id) REFERENCES factor_cards_v2(card_id),
                    UNIQUE(card_id, evidence_manifest_hash),
                    UNIQUE(source_kind, source_ref)
                );

                CREATE TABLE IF NOT EXISTS factor_evaluations_v2 (
                    evaluation_id TEXT PRIMARY KEY,
                    evidence_id TEXT NOT NULL UNIQUE,
                    ic REAL,
                    rank_ic REAL,
                    icir REAL,
                    t_stat REAL,
                    positive_ratio REAL,
                    mean_decay_1d REAL,
                    mean_decay_5d REAL,
                    quintile_spread REAL,
                    after_cost_return REAL,
                    benchmark_relative_return REAL,
                    max_drawdown REAL,
                    downside_capture REAL,
                    annual_turnover REAL,
                    average_holding_sessions REAL,
                    max_single_symbol_concentration REAL,
                    positive_basket_contribution_ratio REAL,
                    coverage_ratio REAL,
                    development_falsification_stability REAL,
                    cash_utilization REAL,
                    failed_gates_json TEXT NOT NULL,
                    regime_behavior_json TEXT NOT NULL,
                    basket_behavior_json TEXT NOT NULL,
                    required_metrics_complete INTEGER NOT NULL,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES factor_evidence_v2(evidence_id)
                );

                CREATE TABLE IF NOT EXISTS factor_series_artifacts_v2 (
                    artifact_id TEXT PRIMARY KEY,
                    evidence_id TEXT NOT NULL,
                    series_kind TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES factor_evidence_v2(evidence_id),
                    UNIQUE(evidence_id, series_kind)
                );

                CREATE TABLE IF NOT EXISTS factor_relationships_v2 (
                    relationship_id TEXT PRIMARY KEY,
                    left_card_id TEXT NOT NULL,
                    right_card_id TEXT NOT NULL,
                    evidence_scope_hash TEXT NOT NULL,
                    score_correlation REAL,
                    return_correlation REAL,
                    selection_overlap REAL,
                    turnover_overlap REAL,
                    redundancy_cluster TEXT NOT NULL DEFAULT '',
                    source_manifest_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(left_card_id) REFERENCES factor_cards_v2(card_id),
                    FOREIGN KEY(right_card_id) REFERENCES factor_cards_v2(card_id),
                    UNIQUE(left_card_id, right_card_id, evidence_scope_hash)
                );

                CREATE TABLE IF NOT EXISTS factor_combination_usage_v2 (
                    usage_id TEXT PRIMARY KEY,
                    card_id TEXT NOT NULL,
                    combination_id TEXT NOT NULL,
                    weight REAL NOT NULL,
                    role TEXT NOT NULL,
                    evidence_manifest_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(card_id) REFERENCES factor_cards_v2(card_id),
                    UNIQUE(card_id, combination_id, evidence_manifest_hash)
                );

                CREATE TABLE IF NOT EXISTS factor_migration_history_v2 (
                    migration_key TEXT PRIMARY KEY,
                    source_table TEXT NOT NULL,
                    source_row_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    migrated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def register_card(self, card: FactorCardInput) -> str:
        if not card.stable_factor_key.strip() or not card.factor_version.strip():
            raise ValueError("stable_factor_key and factor_version are required")
        if card.information_family not in INFORMATION_FAMILIES:
            raise ValueError(f"invalid information family: {card.information_family}")
        if card.status not in FACTOR_STATUSES:
            raise ValueError(f"invalid factor status: {card.status}")
        if card.availability_lag_days < 0:
            raise ValueError("availability_lag_days must be non-negative")

        identity = {
            "stable_factor_key": card.stable_factor_key.strip(),
            "factor_version": card.factor_version.strip(),
        }
        card_id = _stable_id("factor", identity)
        now = _now()
        payload = (
            card_id,
            identity["stable_factor_key"],
            identity["factor_version"],
            card.name.strip(),
            card.canonical_definition.strip(),
            card.information_family,
            card.update_frequency.strip(),
            int(card.availability_lag_days),
            card.transformation.strip(),
            card.orientation.strip(),
            card.neutralization.strip(),
            card.thesis.strip(),
            card.code_identity.strip(),
            card.spec_path.strip(),
            card.source_report_path.strip(),
            card.status,
            card.source_kind.strip() or "native_v2",
            card.source_ref.strip(),
            now,
            now,
        )
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM factor_cards_v2 WHERE card_id = ?", (card_id,)
            ).fetchone()
            if existing is not None:
                comparable = {
                    "name": card.name.strip(),
                    "canonical_definition": card.canonical_definition.strip(),
                    "information_family": card.information_family,
                    "update_frequency": card.update_frequency.strip(),
                    "availability_lag_days": int(card.availability_lag_days),
                    "transformation": card.transformation.strip(),
                    "orientation": card.orientation.strip(),
                    "neutralization": card.neutralization.strip(),
                    "thesis": card.thesis.strip(),
                    "code_identity": card.code_identity.strip(),
                    "spec_path": card.spec_path.strip(),
                    "source_report_path": card.source_report_path.strip(),
                    "status": card.status,
                    "source_kind": card.source_kind.strip() or "native_v2",
                    "source_ref": card.source_ref.strip(),
                }
                for key, value in comparable.items():
                    if existing[key] != value:
                        raise ValueError(f"factor card identity is immutable; mismatch in {key}")
                return card_id
            conn.execute(
                """
                INSERT INTO factor_cards_v2 (
                    card_id, stable_factor_key, factor_version, name,
                    canonical_definition, information_family, update_frequency,
                    availability_lag_days, transformation, orientation,
                    neutralization, thesis, code_identity, spec_path,
                    source_report_path, status, source_kind, source_ref,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
        return card_id

    def update_card_status(self, card_id: str, status: str) -> None:
        if status not in FACTOR_STATUSES:
            raise ValueError(f"invalid factor status: {status}")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE factor_cards_v2 SET status = ?, updated_at = ? WHERE card_id = ?",
                (status, _now(), card_id),
            )
            if cur.rowcount != 1:
                raise KeyError(card_id)

    def get_card(self, card_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._row(
                conn.execute(
                    "SELECT * FROM factor_cards_v2 WHERE card_id = ?", (card_id,)
                ).fetchone()
            )

    def list_cards(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in FACTOR_STATUSES:
            raise ValueError(f"invalid factor status: {status}")
        sql = "SELECT * FROM factor_cards_v2"
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY stable_factor_key, factor_version"
        with self._connect() as conn:
            return [self._row(row) for row in conn.execute(sql, params).fetchall()]

    def record_evidence(self, card_id: str, payload: Mapping[str, Any]) -> str:
        if self.get_card(card_id) is None:
            raise KeyError(card_id)
        decision_status = str(payload.get("decision_status", ""))
        if decision_status not in FACTOR_STATUSES:
            raise ValueError(f"invalid evidence decision status: {decision_status}")
        authoritative = bool(payload.get("authoritative", False))
        if authoritative:
            _require_nonempty(payload, AUTHORITATIVE_EVIDENCE_FIELDS, label="authoritative evidence")
            if decision_status in {"legacy_unverified", "data_blocked"}:
                raise ValueError("authoritative evidence cannot use an unverified or blocked status")

        normalized = {
            "card_id": card_id,
            "market": str(payload.get("market", "")),
            "universe_version": str(payload.get("universe_version", "")),
            "benchmark": str(payload.get("benchmark", "")),
            "horizon_sessions": int(payload.get("horizon_sessions") or 0),
            "provider_identity": str(payload.get("provider_identity", "")),
            "data_validity_level": str(payload.get("data_validity_level", "")),
            "development_start": str(payload.get("development_start", "")),
            "development_end": str(payload.get("development_end", "")),
            "falsification_start": str(payload.get("falsification_start", "")),
            "falsification_end": str(payload.get("falsification_end", "")),
            "reserved_start": str(payload.get("reserved_start", "")),
            "reserved_end": str(payload.get("reserved_end", "")),
            "cost_bps": payload.get("cost_bps"),
            "execution_contract": str(payload.get("execution_contract", "")),
            "evidence_manifest_hash": str(payload.get("evidence_manifest_hash", "")),
            "authoritative": authoritative,
            "decision_status": decision_status,
            "failure_class": str(payload.get("failure_class", "")),
            "lessons_learned": str(payload.get("lessons_learned", "")),
            "source_kind": str(payload.get("source_kind", "native_v2")),
            "source_ref": str(payload.get("source_ref", "")),
        }
        evidence_id = _stable_id("evidence", normalized)
        identity_json = _canonical_json(normalized)
        manifest = normalized["evidence_manifest_hash"]
        with self._connect() as conn:
            if manifest:
                existing_manifest = conn.execute(
                    "SELECT evidence_id, identity_json FROM factor_evidence_v2 WHERE evidence_manifest_hash = ?",
                    (manifest,),
                ).fetchone()
                if existing_manifest is not None and existing_manifest["identity_json"] != identity_json:
                    raise ValueError("evidence manifest hash is already bound to a different identity")
            existing = conn.execute(
                "SELECT identity_json FROM factor_evidence_v2 WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            if existing is not None:
                if existing["identity_json"] != identity_json:
                    raise ValueError("evidence identity is immutable")
                return evidence_id
            conn.execute(
                """
                INSERT INTO factor_evidence_v2 (
                    evidence_id, card_id, market, universe_version, benchmark,
                    horizon_sessions, provider_identity, data_validity_level,
                    development_start, development_end, falsification_start,
                    falsification_end, reserved_start, reserved_end, cost_bps,
                    execution_contract, evidence_manifest_hash, authoritative,
                    decision_status, failure_class, lessons_learned, source_kind,
                    source_ref, identity_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    card_id,
                    normalized["market"],
                    normalized["universe_version"],
                    normalized["benchmark"],
                    normalized["horizon_sessions"],
                    normalized["provider_identity"],
                    normalized["data_validity_level"],
                    normalized["development_start"],
                    normalized["development_end"],
                    normalized["falsification_start"],
                    normalized["falsification_end"],
                    normalized["reserved_start"],
                    normalized["reserved_end"],
                    normalized["cost_bps"],
                    normalized["execution_contract"],
                    manifest,
                    int(authoritative),
                    decision_status,
                    normalized["failure_class"],
                    normalized["lessons_learned"],
                    normalized["source_kind"],
                    normalized["source_ref"],
                    identity_json,
                    _now(),
                ),
            )
        return evidence_id

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._row(
                conn.execute(
                    "SELECT * FROM factor_evidence_v2 WHERE evidence_id = ?",
                    (evidence_id,),
                ).fetchone()
            )

    def list_evidence(self, card_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM factor_evidence_v2"
        params: tuple[Any, ...] = ()
        if card_id is not None:
            sql += " WHERE card_id = ?"
            params = (card_id,)
        sql += " ORDER BY created_at"
        with self._connect() as conn:
            return [self._row(row) for row in conn.execute(sql, params).fetchall()]

    def record_evaluation(self, evidence_id: str, metrics: Mapping[str, Any]) -> str:
        evidence = self.get_evidence(evidence_id)
        if evidence is None:
            raise KeyError(evidence_id)
        missing = [
            field
            for field in AUTHORITATIVE_EVALUATION_METRICS
            if metrics.get(field) is None
        ]
        if bool(evidence["authoritative"]) and missing:
            raise ValueError(
                "authoritative evaluation missing required metrics: " + ", ".join(missing)
            )
        evaluation_id = _stable_id(
            "evaluation",
            {"evidence_id": evidence_id, "metrics": dict(metrics)},
        )
        failed_gates = list(metrics.get("failed_gates", []))
        normalized_metrics = dict(metrics)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT metrics_json FROM factor_evaluations_v2 WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            metrics_json = _canonical_json(normalized_metrics)
            if existing is not None:
                if existing["metrics_json"] != metrics_json:
                    raise ValueError("evaluation is immutable for an evidence identity")
                return evaluation_id
            conn.execute(
                """
                INSERT INTO factor_evaluations_v2 (
                    evaluation_id, evidence_id, ic, rank_ic, icir, t_stat,
                    positive_ratio, mean_decay_1d, mean_decay_5d,
                    quintile_spread, after_cost_return,
                    benchmark_relative_return, max_drawdown, downside_capture,
                    annual_turnover, average_holding_sessions,
                    max_single_symbol_concentration,
                    positive_basket_contribution_ratio, coverage_ratio,
                    development_falsification_stability, cash_utilization,
                    failed_gates_json, regime_behavior_json,
                    basket_behavior_json, required_metrics_complete,
                    metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    evidence_id,
                    metrics.get("ic"),
                    metrics.get("rank_ic"),
                    metrics.get("icir"),
                    metrics.get("t_stat"),
                    metrics.get("positive_ratio"),
                    metrics.get("mean_decay_1d"),
                    metrics.get("mean_decay_5d"),
                    metrics.get("quintile_spread"),
                    metrics.get("after_cost_return"),
                    metrics.get("benchmark_relative_return"),
                    metrics.get("max_drawdown"),
                    metrics.get("downside_capture"),
                    metrics.get("annual_turnover"),
                    metrics.get("average_holding_sessions"),
                    metrics.get("max_single_symbol_concentration"),
                    metrics.get("positive_basket_contribution_ratio"),
                    metrics.get("coverage_ratio"),
                    metrics.get("development_falsification_stability"),
                    metrics.get("cash_utilization"),
                    _canonical_json({"items": failed_gates}),
                    _json_or_empty(metrics.get("regime_behavior")),
                    _json_or_empty(metrics.get("basket_behavior")),
                    int(not missing),
                    metrics_json,
                    _now(),
                ),
            )
        return evaluation_id

    def attach_series_artifact(
        self,
        evidence_id: str,
        *,
        series_kind: str,
        artifact_path: str,
        sha256: str,
        start_date: str,
        end_date: str,
        row_count: int,
    ) -> str:
        if self.get_evidence(evidence_id) is None:
            raise KeyError(evidence_id)
        if series_kind not in SERIES_KINDS:
            raise ValueError(f"invalid series kind: {series_kind}")
        if row_count <= 0 or not sha256 or not artifact_path:
            raise ValueError("series artifact path, sha256, and positive row_count are required")
        identity = {
            "evidence_id": evidence_id,
            "series_kind": series_kind,
            "artifact_path": artifact_path,
            "sha256": sha256,
            "start_date": start_date,
            "end_date": end_date,
            "row_count": int(row_count),
        }
        artifact_id = _stable_id("series", identity)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM factor_series_artifacts_v2 WHERE evidence_id = ? AND series_kind = ?",
                (evidence_id, series_kind),
            ).fetchone()
            if existing is not None:
                for key in ("artifact_path", "sha256", "start_date", "end_date", "row_count"):
                    if existing[key] != identity[key]:
                        raise ValueError("series artifact identity is immutable")
                return existing["artifact_id"]
            conn.execute(
                """
                INSERT INTO factor_series_artifacts_v2 (
                    artifact_id, evidence_id, series_kind, artifact_path,
                    sha256, start_date, end_date, row_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    evidence_id,
                    series_kind,
                    artifact_path,
                    sha256,
                    start_date,
                    end_date,
                    int(row_count),
                    _now(),
                ),
            )
        return artifact_id

    def record_relationship(
        self,
        left_card_id: str,
        right_card_id: str,
        *,
        evidence_scope_hash: str,
        source_manifest_hash: str,
        score_correlation: float | None = None,
        return_correlation: float | None = None,
        selection_overlap: float | None = None,
        turnover_overlap: float | None = None,
        redundancy_cluster: str = "",
    ) -> str:
        if left_card_id == right_card_id:
            raise ValueError("relationship requires two distinct factor cards")
        if self.get_card(left_card_id) is None or self.get_card(right_card_id) is None:
            raise KeyError("relationship references an unknown factor card")
        left, right = sorted((left_card_id, right_card_id))
        identity = {
            "left_card_id": left,
            "right_card_id": right,
            "evidence_scope_hash": evidence_scope_hash,
        }
        relationship_id = _stable_id("relationship", identity)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM factor_relationships_v2 WHERE relationship_id = ?",
                (relationship_id,),
            ).fetchone()
            comparable = {
                "score_correlation": score_correlation,
                "return_correlation": return_correlation,
                "selection_overlap": selection_overlap,
                "turnover_overlap": turnover_overlap,
                "redundancy_cluster": redundancy_cluster,
                "source_manifest_hash": source_manifest_hash,
            }
            if existing is not None:
                for key, value in comparable.items():
                    if existing[key] != value:
                        raise ValueError("factor relationship is immutable")
                return relationship_id
            conn.execute(
                """
                INSERT INTO factor_relationships_v2 (
                    relationship_id, left_card_id, right_card_id,
                    evidence_scope_hash, score_correlation, return_correlation,
                    selection_overlap, turnover_overlap, redundancy_cluster,
                    source_manifest_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relationship_id,
                    left,
                    right,
                    evidence_scope_hash,
                    score_correlation,
                    return_correlation,
                    selection_overlap,
                    turnover_overlap,
                    redundancy_cluster,
                    source_manifest_hash,
                    _now(),
                ),
            )
        return relationship_id

    def record_combination_usage(
        self,
        card_id: str,
        *,
        combination_id: str,
        weight: float,
        role: str,
        evidence_manifest_hash: str,
    ) -> str:
        if self.get_card(card_id) is None:
            raise KeyError(card_id)
        identity = {
            "card_id": card_id,
            "combination_id": combination_id,
            "evidence_manifest_hash": evidence_manifest_hash,
        }
        usage_id = _stable_id("usage", identity)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM factor_combination_usage_v2 WHERE usage_id = ?",
                (usage_id,),
            ).fetchone()
            if existing is not None:
                if float(existing["weight"]) != float(weight) or existing["role"] != role:
                    raise ValueError("combination usage is immutable")
                return usage_id
            conn.execute(
                """
                INSERT INTO factor_combination_usage_v2 (
                    usage_id, card_id, combination_id, weight, role,
                    evidence_manifest_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_id,
                    card_id,
                    combination_id,
                    float(weight),
                    role,
                    evidence_manifest_hash,
                    _now(),
                ),
            )
        return usage_id

    def evidence_completeness_report(self) -> dict[str, Any]:
        with self._connect() as conn:
            cards = conn.execute("SELECT COUNT(*) FROM factor_cards_v2").fetchone()[0]
            evidence_rows = conn.execute("SELECT * FROM factor_evidence_v2").fetchall()
            evaluations = {
                row["evidence_id"]: row
                for row in conn.execute("SELECT * FROM factor_evaluations_v2").fetchall()
            }
        incomplete: list[dict[str, Any]] = []
        authoritative_count = 0
        for row in evidence_rows:
            missing_identity = [
                field for field in AUTHORITATIVE_EVIDENCE_FIELDS if row[field] in (None, "", 0)
            ]
            evaluation = evaluations.get(row["evidence_id"])
            missing_metrics = list(AUTHORITATIVE_EVALUATION_METRICS)
            if evaluation is not None:
                missing_metrics = [
                    field for field in AUTHORITATIVE_EVALUATION_METRICS if evaluation[field] is None
                ]
            if bool(row["authoritative"]):
                authoritative_count += 1
            if missing_identity or missing_metrics or evaluation is None:
                incomplete.append(
                    {
                        "evidence_id": row["evidence_id"],
                        "card_id": row["card_id"],
                        "decision_status": row["decision_status"],
                        "missing_identity_fields": missing_identity,
                        "missing_evaluation_metrics": missing_metrics,
                        "evaluation_present": evaluation is not None,
                    }
                )
        return {
            "schema_version": "2.0",
            "factor_card_count": cards,
            "evidence_count": len(evidence_rows),
            "authoritative_evidence_count": authoritative_count,
            "incomplete_evidence_count": len(incomplete),
            "incomplete": incomplete,
        }

    def migrate_legacy_registry(self) -> dict[str, int]:
        """Backfill legacy tables without deleting or rewriting any legacy row."""

        counts = {"cards": 0, "evidence": 0, "evaluations": 0, "usage": 0}
        with self._connect() as conn:
            table_names = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "factors" not in table_names:
                return counts
            legacy_factors = conn.execute("SELECT * FROM factors ORDER BY id").fetchall()
            legacy_validations = (
                conn.execute("SELECT * FROM factor_validations ORDER BY id").fetchall()
                if "factor_validations" in table_names
                else []
            )
            legacy_usage = (
                conn.execute("SELECT * FROM factor_usage ORDER BY id").fetchall()
                if "factor_usage" in table_names
                else []
            )

        card_by_legacy_id: dict[int, str] = {}
        for row in legacy_factors:
            source_ref = f"factors:{row['id']}"
            card = FactorCardInput(
                stable_factor_key=f"legacy::{row['name']}",
                factor_version="legacy-v1",
                name=str(row["name"]),
                canonical_definition=str(row["expression"]),
                information_family=LEGACY_CATEGORY_TO_FAMILY.get(
                    str(row["category"]), "other"
                ),
                update_frequency="legacy_unknown",
                availability_lag_days=0,
                transformation="legacy_unknown",
                orientation=str(row["direction"] or "legacy_unknown"),
                neutralization="legacy_unknown",
                thesis=str(row["thesis"] or ""),
                code_identity="legacy_registry_row",
                status="legacy_unverified",
                source_kind="legacy_factor_registry",
                source_ref=source_ref,
            )
            before = self._migration_exists("factor_card", source_ref)
            card_id = self.register_card(card)
            card_by_legacy_id[int(row["id"])] = card_id
            if not before:
                self._mark_migrated("factors", source_ref, "factor_card", card_id)
                counts["cards"] += 1

        for row in legacy_validations:
            card_id = card_by_legacy_id.get(int(row["factor_id"]))
            if card_id is None:
                continue
            source_ref = f"factor_validations:{row['id']}"
            before = self._migration_exists("factor_evidence", source_ref)
            legacy_payload = {key: row[key] for key in row.keys()}
            manifest = hashlib.sha256(_canonical_json(legacy_payload).encode()).hexdigest()
            evidence_id = self.record_evidence(
                card_id,
                {
                    "market": str(row["market"] or "legacy_unknown"),
                    "universe_version": "legacy_unknown",
                    "benchmark": "legacy_unknown",
                    "horizon_sessions": 0,
                    "provider_identity": "legacy_unknown",
                    "data_validity_level": "legacy_unknown",
                    "development_start": "",
                    "development_end": "",
                    "falsification_start": "",
                    "falsification_end": "",
                    "reserved_start": "",
                    "reserved_end": "",
                    "cost_bps": None,
                    "execution_contract": "legacy_unknown",
                    "evidence_manifest_hash": manifest,
                    "authoritative": False,
                    "decision_status": "legacy_unverified",
                    "failure_class": "legacy_evidence_incomplete",
                    "lessons_learned": (
                        "Legacy validation retained for audit; current PIT, cost, "
                        "turnover, and evidence identities are incomplete."
                    ),
                    "source_kind": "legacy_factor_registry",
                    "source_ref": source_ref,
                },
            )
            if not before:
                self._mark_migrated(
                    "factor_validations", source_ref, "factor_evidence", evidence_id
                )
                counts["evidence"] += 1
            metrics = {
                "ic": row["ic"],
                "rank_ic": row["rank_ic"],
                "icir": row["icir"],
                "t_stat": row["t_stat"],
                "positive_ratio": row["positive_ratio"],
                "mean_decay_1d": row["mean_decay_1d"],
                "mean_decay_5d": row["mean_decay_5d"],
                "quintile_spread": row["quintile_spread"],
                "failed_gates": [] if bool(row["passed"]) else ["legacy_validation_failed"],
            }
            evaluation_exists = self._migration_exists("factor_evaluation", source_ref)
            evaluation_id = self.record_evaluation(evidence_id, metrics)
            if not evaluation_exists:
                self._mark_migrated(
                    "factor_validations", source_ref, "factor_evaluation", evaluation_id
                )
                counts["evaluations"] += 1

        for row in legacy_usage:
            card_id = card_by_legacy_id.get(int(row["factor_id"]))
            if card_id is None:
                continue
            source_ref = f"factor_usage:{row['id']}"
            if self._migration_exists("factor_usage", source_ref):
                continue
            combination_id = str(row["strategy_config"] or "legacy_unknown_strategy")
            manifest = hashlib.sha256(source_ref.encode()).hexdigest()
            usage_id = self.record_combination_usage(
                card_id,
                combination_id=combination_id,
                weight=float(row["weight"] or 0.0),
                role="legacy_unverified",
                evidence_manifest_hash=manifest,
            )
            self._mark_migrated("factor_usage", source_ref, "factor_usage", usage_id)
            counts["usage"] += 1
        return counts

    def _migration_exists(self, target_type: str, source_ref: str) -> bool:
        key = f"{target_type}:{source_ref}"
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM factor_migration_history_v2 WHERE migration_key = ?",
                    (key,),
                ).fetchone()
                is not None
            )

    def _mark_migrated(
        self,
        source_table: str,
        source_ref: str,
        target_type: str,
        target_id: str,
    ) -> None:
        key = f"{target_type}:{source_ref}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO factor_migration_history_v2 (
                    migration_key, source_table, source_row_id, target_type,
                    target_id, migrated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, source_table, source_ref, target_type, target_id, _now()),
            )
