"""Read-only model operations snapshots.

The production multi-market adapter is not source-bound yet and publishes
explicit absence. Callers supplying observed facts can evaluate existing gates;
this module never invents metrics, drift measurements or paper transactions.
All outputs remain research_only=True and trade_ready=False.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.assistant.champion_manager import ChampionRecord
from src.common.logging import get_logger
from src.portfolio.construction import ConstructionConstraints, PortfolioConstructor, QualifiedSignal
from src.portfolio.operations_gates import GateFacts, OperationalGatePolicy, OperationsGateEngine
from src.portfolio.paper_ledger import PaperTradingLedger

logger = get_logger(__name__)

SCHEMA_VERSION = "model_operations_v1"
SUPPORTED_MARKETS = ("us", "cn")


class ModelOperationsError(ValueError):
    """Raised when Model Operations artifact cannot be constructed or validated."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass
class MarketOperationsSnapshot:
    """Operations summary for one market."""

    market: str
    champion: dict[str, Any] | None
    challenger: dict[str, Any] | None
    drift: dict[str, Any]
    gate_decision: dict[str, Any]
    execution_plan: dict[str, Any] | None
    paper_ledger: dict[str, Any]
    attribution: dict[str, Any]


@dataclass
class ModelOperationsPayload:
    """Root immutable read model for Model Operations."""

    schema_version: str
    generated_at: str
    research_only: bool
    trade_ready: bool
    markets: list[MarketOperationsSnapshot]
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "research_only": self.research_only,
            "trade_ready": self.trade_ready,
            "markets": [
                {
                    "market": m.market,
                    "champion": m.champion,
                    "challenger": m.challenger,
                    "drift": m.drift,
                    "gate_decision": m.gate_decision,
                    "execution_plan": m.execution_plan,
                    "paper_ledger": m.paper_ledger,
                    "attribution": m.attribution,
                }
                for m in self.markets
            ],
        }
        data["digest"] = _digest_payload(data)
        return data


def validate_model_operations_payload(payload: Mapping[str, Any]) -> None:
    """Enforce fail-closed validation on the Model Operations read model."""
    if not isinstance(payload, Mapping):
        raise ModelOperationsError("Payload must be a mapping.")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ModelOperationsError(
            f"Unsupported schema_version: {payload.get('schema_version')}, expected {SCHEMA_VERSION}."
        )
    if payload.get("research_only") is not True:
        raise ModelOperationsError("research_only must be true.")
    if payload.get("trade_ready") is not False:
        raise ModelOperationsError("trade_ready must be false.")
    if not isinstance(payload.get("markets"), list):
        raise ModelOperationsError("markets must be a list.")

    for item in payload["markets"]:
        if not isinstance(item, Mapping):
            raise ModelOperationsError("Market snapshot must be a mapping.")
        if item.get("market") not in SUPPORTED_MARKETS:
            raise ModelOperationsError(f"Unsupported market in payload: {item.get('market')}")
        if not isinstance(item.get("drift"), Mapping):
            raise ModelOperationsError("Market drift must be a mapping.")
        if not isinstance(item.get("gate_decision"), Mapping):
            raise ModelOperationsError("Market gate_decision must be a mapping.")
        if not isinstance(item.get("paper_ledger"), Mapping):
            raise ModelOperationsError("Market paper_ledger must be a mapping.")
        if not isinstance(item.get("attribution"), Mapping):
            raise ModelOperationsError("Market attribution must be a mapping.")


def build_market_operations_snapshot(
    market: str,
    *,
    champion_record: ChampionRecord | None = None,
    challenger_record: dict[str, Any] | None = None,
    gate_facts: GateFacts | None = None,
    gate_policy: OperationalGatePolicy | None = None,
    signals: Sequence[QualifiedSignal] | None = None,
    ledger: PaperTradingLedger | None = None,
    asof_date: str = "2026-09-18",
) -> MarketOperationsSnapshot:
    """Build a deterministic operations snapshot for one market."""
    if market not in SUPPORTED_MARKETS:
        raise ModelOperationsError(f"Market {market} is not supported.")

    # Missing evidence is not a demonstration of a passing operational gate.
    facts = gate_facts or GateFacts(
        data_freshness_status=None,
        data_age_days=None,
        artifact_status=None,
        previous_verified_champion_id=None,
        current_drawdown=None,
        risk_limit_breached=False,
        signal_qualified=None,
        signal_sample_count=None,
        drift_severity=None,
        paper_excess_return=None,
    )
    if champion_record is None:
        facts = replace(facts, artifact_status="missing")
    champion = None if champion_record is None else {
        "model_version_id": champion_record.model_version_id,
        "artifact_id": champion_record.artifact_id,
        "declared_at": champion_record.declared_at,
        "declared_by": champion_record.declared_by,
        "snapshot_id": champion_record.snapshot_id,
        "metrics": dict(champion_record.metrics),
        "previous_champion_id": champion_record.previous_champion_id,
        "promotion_reason": champion_record.promotion_reason,
    }
    decision = OperationsGateEngine(gate_policy or OperationalGatePolicy()).evaluate(
        market=market,
        model_version_id=champion_record.model_version_id if champion_record else "unavailable",
        champion_id=champion_record.artifact_id if champion_record else None,
        facts=facts,
    )
    plan = None
    if decision.plan_eligible and champion_record and signals:
        plan = PortfolioConstructor(constraints=ConstructionConstraints()).build_plan(
            asof_date=asof_date,
            signals=list(signals),
            model_version_id=champion_record.model_version_id,
            data_snapshot_id=champion_record.snapshot_id,
        ).to_dict()
    # Snapshot construction is read-only. It never submits, settles or seeds orders.
    # Ledger/attribution need a source-bound adapter before becoming publishable.
    return MarketOperationsSnapshot(
        market=market,
        champion=champion,
        challenger=challenger_record,
        drift={"overall_severity": facts.drift_severity or "unavailable", "checks": []},
        gate_decision=decision.to_dict(),
        execution_plan=plan,
        paper_ledger={"availability_status": "absent"},
        attribution={"availability_status": "absent"},
    )


def build_model_operations_payload(
    root: Path | None = None,
    *,
    asof_date: str | None = None,
    us_facts: GateFacts | None = None,
    cn_facts: GateFacts | None = None,
) -> ModelOperationsPayload:
    """Materialize the full multi-market model operations read model."""
    # No source-bound multi-market adapter exists yet. Publish explicit absence,
    # rather than fabricate champions or paper performance from the current date.
    return ModelOperationsPayload(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        research_only=True,
        trade_ready=False,
        markets=[],
    )


def write_model_operations_payload(
    payload: ModelOperationsPayload,
    output_path: Path,
) -> Path:
    """Write and validate the model operations payload to an immutable JSON path."""
    data = payload.to_dict()
    validate_model_operations_payload(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
    output_path.write_text(rendered, encoding="utf-8")
    logger.info("Published Model Operations artifact to %s", output_path)
    return output_path
