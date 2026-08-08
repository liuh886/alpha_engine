"""Build the governed current-state read model consumed by Strategy Console."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    read_latest_evaluation,
)
from src.factors.strategy_snapshot import (
    StrategyFactorSnapshotError,
    validate_strategy_factor_snapshot,
)

SCHEMA_VERSION = "2.0.0"
QQQ_FAMILY = "qqq_rotation"
BYD_FAMILY = "byd_allocation"
US_RANKER_FAMILY = "us_ranker"
CN_RANKER_FAMILY = "cn_ranker"
RANKER_FAMILIES = {US_RANKER_FAMILY, CN_RANKER_FAMILY}
SUPPORTED_SIGNAL_FAMILIES = {QQQ_FAMILY, BYD_FAMILY, *RANKER_FAMILIES}
STATUS_VALUES = {
    "pipeline_unavailable",
    "awaiting_observation",
    "current_no_change",
    "target_pending_execution",
    "execution_observed",
    "stale",
    "blocked",
    "delivery_failed",
}
FRESHNESS_VALUES = {"current", "stale", "blocked", "unknown"}
QQQ_STATE_LABELS = {0: "Defensive", 1: "Transition", 2: "Risk-on"}
BYD_MODE_LABELS = {
    "defense": "Defensive",
    "offense": "Offense",
    "convex_expansion": "Convex expansion",
}


class StrategyOperationsError(ValueError):
    """Raised when a governed operations snapshot cannot be constructed."""


def _finite(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        if result == result and abs(result) != float("inf"):
            return result
    return None


def _weights(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        number = _finite(raw)
        if number is None:
            raise StrategyOperationsError(
                f"allocation weight for {key!r} must be finite"
            )
        result[str(key)] = number
    return result


def _allocations(current: object, target: object) -> list[dict[str, object]]:
    current_weights = _weights(current)
    target_weights = _weights(target)
    assets = sorted(set(current_weights) | set(target_weights))
    return [
        {
            "asset": asset,
            "current": current_weights.get(asset, 0.0),
            "target": target_weights.get(asset, 0.0),
            "delta": target_weights.get(asset, 0.0) - current_weights.get(asset, 0.0),
        }
        for asset in assets
    ]


def _has_change(allocations: Sequence[Mapping[str, object]]) -> bool:
    return any(abs(float(row["delta"])) > 1e-9 for row in allocations)


def _formal_records(formal_catalog: Path) -> list[dict[str, Any]]:
    payload = json.loads(formal_catalog.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StrategyOperationsError("formal catalog root must be an object")
    validate_catalog(payload)
    if payload.get("channel") != "formal":
        raise StrategyOperationsError("operations read model requires the formal catalog")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise StrategyOperationsError("formal catalog research boundary is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise StrategyOperationsError("formal catalog contains no records")
    return [dict(record) for record in records if isinstance(record, Mapping)]


def _cadence(record: Mapping[str, Any]) -> tuple[str, str]:
    family = str(record.get("model_family_id", ""))
    if family == QQQ_FAMILY:
        return (
            "Every completed US market session",
            "Evaluate at close; target applies to the next eligible open.",
        )
    if family == BYD_FAMILY:
        return (
            "Every completed CN market session",
            "Evaluate after the common close; target applies to the next independently confirmed eligible open.",
        )
    if family in RANKER_FAMILIES:
        return (
            "Every 10 provider sessions",
            "Publish only on the governed rebalance session; target applies to the next eligible open.",
        )
    return (
        "Governed model cadence",
        "No governed current-target publisher is registered yet.",
    )


def _source(
    record: Mapping[str, Any], ledger: Mapping[str, Any] | None
) -> dict[str, object]:
    result: dict[str, object] = {
        "formal_bundle_id": record.get("bundle_id"),
        "formal_run_id": record.get("run_id"),
        "formal_evidence_cutoff": record.get("evidence_cutoff"),
        "ledger_fingerprint": None,
        "signal_sha256": None,
        "factor_catalog_implementation_hash": None,
        "workflow_run_id": None,
        "commit_sha": None,
        "github_issue_number": None,
    }
    if ledger is None:
        return result
    delivery = (
        ledger.get("delivery") if isinstance(ledger.get("delivery"), Mapping) else {}
    )
    workflow = (
        ledger.get("workflow") if isinstance(ledger.get("workflow"), Mapping) else {}
    )
    signal = ledger.get("signal") if isinstance(ledger.get("signal"), Mapping) else {}
    factor_evidence = (
        signal.get("factor_evidence")
        if isinstance(signal.get("factor_evidence"), Mapping)
        else {}
    )
    result.update(
        {
            "ledger_fingerprint": ledger.get("fingerprint"),
            "signal_sha256": ledger.get("signal_sha256"),
            "factor_catalog_implementation_hash": factor_evidence.get(
                "catalog_implementation_hash"
            ),
            "workflow_run_id": workflow.get("run_id"),
            "commit_sha": workflow.get("commit_sha"),
            "github_issue_number": delivery.get("github_issue_number"),
        }
    )
    return result


def _unavailable(record: Mapping[str, Any], *, awaiting: bool) -> dict[str, object]:
    cadence, next_policy = _cadence(record)
    if awaiting:
        status = "awaiting_observation"
        state_label = "Awaiting first governed evaluation"
        note = (
            "The signal publisher exists, but no cutoff-bound evaluation has been committed yet."
        )
    else:
        status = "pipeline_unavailable"
        state_label = "No governed current-target publisher"
        note = (
            "Formal historical evidence is available; live target state is intentionally unavailable."
        )
    return {
        "model_version_id": str(record["model_version_id"]),
        "status": status,
        "as_of": None,
        "latest_completed_session": record.get("evidence_cutoff"),
        "decision_cadence": cadence,
        "next_decision_policy": next_policy,
        "state_label": state_label,
        "decision_reason": note,
        "allocations": [],
        "turnover": None,
        "estimated_cost": None,
        "data_freshness": "unknown",
        "factor_freshness": "blocked" if awaiting else "unknown",
        "delivery_status": "not available",
        "source_label": (
            "Governed signal ledger" if awaiting else "Formal evidence only"
        ),
        "source_href": None,
        "note": note,
        "factor_evidence": [],
        "source_identity": _source(record, None),
    }


def _delivery(record: Mapping[str, Any]) -> tuple[str, int | None]:
    delivery = record.get("delivery")
    if not isinstance(delivery, Mapping):
        return "not available", None
    status = str(delivery.get("status") or "not available")
    issue = delivery.get("github_issue_number")
    return (
        status,
        int(issue) if isinstance(issue, int) and not isinstance(issue, bool) else None,
    )


def _factor_snapshot(
    signal: Mapping[str, Any], *, latest_data_date: object
) -> tuple[str, list[dict[str, Any]], str | None]:
    payload = signal.get("factor_evidence")
    if payload is None:
        return "blocked", [], "Latest signal predates the canonical factor snapshot contract."
    try:
        validate_strategy_factor_snapshot(payload)
    except StrategyFactorSnapshotError as exc:
        return "blocked", [], f"Canonical factor snapshot failed validation: {exc}"
    if not isinstance(payload, Mapping):
        return "blocked", [], "Canonical factor snapshot is not an object."
    if payload.get("observation_cutoff") != latest_data_date:
        return (
            "blocked",
            [],
            "Canonical factor snapshot cutoff does not match the signal data cutoff.",
        )
    rows = payload.get("factors")
    if not isinstance(rows, list):
        return "blocked", [], "Canonical factor snapshot has no factor rows."
    freshness = str(payload.get("freshness"))
    return freshness, [dict(row) for row in rows if isinstance(row, Mapping)], None


def _qqq_state(signal: Mapping[str, Any]) -> tuple[int, int, str]:
    current = signal.get("current_state", signal.get("current_formal_state", -1))
    target = signal.get("target_state", signal.get("target_formal_state", -1))
    current_state = (
        int(current)
        if isinstance(current, (int, float)) and not isinstance(current, bool)
        else -1
    )
    target_state = (
        int(target)
        if isinstance(target, (int, float)) and not isinstance(target, bool)
        else -1
    )
    from_label = QQQ_STATE_LABELS.get(current_state, f"State {current_state}")
    to_label = QQQ_STATE_LABELS.get(target_state, f"State {target_state}")
    current_overlay = signal.get("current_overlay")
    target_overlay = signal.get("target_overlay")
    if isinstance(target_overlay, str) and target_overlay:
        overlay = (
            target_overlay
            if current_overlay == target_overlay
            else f"{current_overlay or 'base'} → {target_overlay}"
        )
        label = f"{to_label} · {overlay}"
    else:
        label = (
            to_label if current_state == target_state else f"{from_label} → {to_label}"
        )
    return current_state, target_state, label


def _status(
    *,
    delivery_status: str,
    data_fresh: bool,
    factor_freshness: str,
    changed: bool,
) -> str:
    if delivery_status == "failed":
        return "delivery_failed"
    if not data_fresh or factor_freshness == "stale":
        return "stale"
    if factor_freshness != "current":
        return "blocked"
    return "target_pending_execution" if changed else "current_no_change"


def _qqq(record: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, object]:
    signal = ledger.get("signal")
    if not isinstance(signal, Mapping):
        raise StrategyOperationsError("QQQ ledger signal is missing")
    allocations = _allocations(signal.get("current_weights"), signal.get("target_weights"))
    changed = _has_change(allocations)
    data_fresh = signal.get("data_freshness_ok") is True
    delivery_status, issue_number = _delivery(ledger)
    latest = signal.get("latest_data_date") or ledger.get("latest_data_date")
    factor_freshness, factors, factor_error = _factor_snapshot(
        signal, latest_data_date=latest
    )
    _, _, state_label = _qqq_state(signal)
    cadence, next_policy = _cadence(record)
    decision_reason = signal.get("decision_reason_label") or signal.get(
        "decision_reason"
    )
    if not decision_reason:
        current_overlay = signal.get("current_overlay")
        target_overlay = signal.get("target_overlay")
        decision_reason = (
            f"{current_overlay or 'base'} → {target_overlay}"
            if isinstance(target_overlay, str) and current_overlay != target_overlay
            else str(target_overlay or "Frozen QQQ rotation evaluation.")
        )
    return {
        "model_version_id": str(record["model_version_id"]),
        "status": _status(
            delivery_status=delivery_status,
            data_fresh=data_fresh,
            factor_freshness=factor_freshness,
            changed=changed,
        ),
        "as_of": signal.get("signal_date"),
        "latest_completed_session": latest,
        "decision_cadence": cadence,
        "next_decision_policy": next_policy,
        "state_label": state_label,
        "decision_reason": str(decision_reason),
        "allocations": allocations,
        "turnover": _finite(signal.get("turnover_units")),
        "estimated_cost": _finite(signal.get("estimated_transaction_cost")),
        "data_freshness": "current" if data_fresh else "stale",
        "factor_freshness": factor_freshness,
        "delivery_status": delivery_status,
        "source_label": "Governed QQQ signal ledger",
        "source_href": (
            f"https://github.com/liuh886/alpha_engine/issues/{issue_number}"
            if issue_number
            else None
        ),
        "note": factor_error
        or (
            "Target is awaiting next-open execution evidence."
            if changed
            else "Latest governed evaluation retained the existing allocation."
        ),
        "factor_evidence": factors,
        "source_identity": _source(record, ledger),
    }


def _byd(record: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, object]:
    signal = ledger.get("signal")
    if not isinstance(signal, Mapping):
        raise StrategyOperationsError("BYD ledger signal is missing")
    allocations = _allocations(signal.get("current_weights"), signal.get("target_weights"))
    changed = _has_change(allocations)
    data_fresh = signal.get("data_freshness_ok") is True
    delivery_status, issue_number = _delivery(ledger)
    latest = signal.get("latest_data_date") or ledger.get("latest_data_date")
    factor_freshness, factors, factor_error = _factor_snapshot(
        signal, latest_data_date=latest
    )
    mode = str(signal.get("target_mode") or "")
    cadence, next_policy = _cadence(record)
    return {
        "model_version_id": str(record["model_version_id"]),
        "status": _status(
            delivery_status=delivery_status,
            data_fresh=data_fresh,
            factor_freshness=factor_freshness,
            changed=changed,
        ),
        "as_of": signal.get("signal_date"),
        "latest_completed_session": latest,
        "decision_cadence": cadence,
        "next_decision_policy": next_policy,
        "state_label": BYD_MODE_LABELS.get(mode, mode or "BYD allocation"),
        "decision_reason": signal.get("transition_label")
        or signal.get("transition_type")
        or "Frozen BYD allocation evaluation.",
        "allocations": allocations,
        "turnover": _finite(signal.get("turnover_units")),
        "estimated_cost": _finite(signal.get("estimated_transaction_cost")),
        "data_freshness": "current" if data_fresh else "stale",
        "factor_freshness": factor_freshness,
        "delivery_status": delivery_status,
        "source_label": "Governed BYD signal ledger",
        "source_href": (
            f"https://github.com/liuh886/alpha_engine/issues/{issue_number}"
            if issue_number
            else None
        ),
        "note": factor_error
        or (
            "Target allocation is published; brokerage execution is outside Alpha Engine."
            if changed
            else "Latest governed evaluation retained the existing allocation."
        ),
        "factor_evidence": factors,
        "source_identity": _source(record, ledger),
    }


def _ranker(record: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, object]:
    signal = ledger.get("signal")
    if not isinstance(signal, Mapping):
        raise StrategyOperationsError("ranker ledger signal is missing")
    allocations = _allocations(signal.get("current_weights"), signal.get("target_weights"))
    changed = _has_change(allocations)
    data_fresh = signal.get("data_freshness_ok") is True
    delivery_status, issue_number = _delivery(ledger)
    latest = signal.get("latest_data_date") or ledger.get("latest_data_date")
    factor_freshness, factors, factor_error = _factor_snapshot(
        signal, latest_data_date=latest
    )
    family = str(record.get("model_family_id", ""))
    diagnostics = signal.get("diagnostics") if isinstance(signal.get("diagnostics"), Mapping) else {}
    if family == US_RANKER_FAMILY:
        state_label = "US Top-15 rebalance"
    elif diagnostics.get("risk_on") is False:
        state_label = "CN risk-off · CSI300 fallback"
    else:
        state_label = "CN risk-on · sector 4×1"
    cadence, next_policy = _cadence(record)
    return {
        "model_version_id": str(record["model_version_id"]),
        "status": _status(
            delivery_status=delivery_status,
            data_fresh=data_fresh,
            factor_freshness=factor_freshness,
            changed=changed,
        ),
        "as_of": signal.get("signal_date"),
        "latest_completed_session": latest,
        "decision_cadence": cadence,
        "next_decision_policy": next_policy,
        "state_label": state_label,
        "decision_reason": str(signal.get("reason_code") or "Frozen 10-session ranker evaluation."),
        "allocations": allocations,
        "turnover": _finite(signal.get("turnover_units")),
        "estimated_cost": _finite(signal.get("estimated_transaction_cost")),
        "data_freshness": "current" if data_fresh else "stale",
        "factor_freshness": factor_freshness,
        "delivery_status": delivery_status,
        "source_label": "Governed 10-session ranker signal ledger",
        "source_href": (
            f"https://github.com/liuh886/alpha_engine/issues/{issue_number}"
            if issue_number
            else None
        ),
        "note": factor_error
        or (
            "Target is published for the next eligible open."
            if changed
            else "The governed rebalance retained the existing target."
        ),
        "factor_evidence": factors,
        "source_identity": _source(record, ledger),
    }


def build_operations_payload(
    *, formal_catalog: Path, ledger_root: Path, generated_at: str
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for formal in _formal_records(formal_catalog):
        model_version_id = str(formal["model_version_id"])
        family = str(formal.get("model_family_id", ""))
        try:
            ledger = read_latest_evaluation(
                ledger_root / model_version_id,
                model_version_id=model_version_id,
            )
        except (OSError, json.JSONDecodeError, StrategySignalLedgerError) as exc:
            blocked = _unavailable(
                formal, awaiting=family in SUPPORTED_SIGNAL_FAMILIES
            )
            blocked["status"] = "blocked"
            blocked["decision_reason"] = str(exc)
            blocked["note"] = (
                "Governed signal ledger failed validation; operations fail closed."
            )
            records.append(blocked)
            continue
        if ledger is None:
            records.append(
                _unavailable(formal, awaiting=family in SUPPORTED_SIGNAL_FAMILIES)
            )
        elif family == QQQ_FAMILY:
            records.append(_qqq(formal, ledger))
        elif family == BYD_FAMILY:
            records.append(_byd(formal, ledger))
        elif family in RANKER_FAMILIES:
            records.append(_ranker(formal, ledger))
        else:
            blocked = _unavailable(formal, awaiting=False)
            blocked["status"] = "blocked"
            blocked["decision_reason"] = (
                "A signal ledger exists but no governed operations adapter is registered."
            )
            blocked["note"] = (
                "Backend adapter required before this signal can be published."
            )
            records.append(blocked)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "trade_ready": False,
        "records": records,
    }


def validate_operations_payload(payload: object) -> None:
    if not isinstance(payload, Mapping):
        raise StrategyOperationsError("operations payload root must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise StrategyOperationsError("unsupported operations schema")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise StrategyOperationsError("operations research boundary is invalid")
    records = payload.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise StrategyOperationsError("operations records must be a list")
    seen: set[str] = set()
    for index, value in enumerate(records):
        if not isinstance(value, Mapping):
            raise StrategyOperationsError(
                f"operations record {index} must be an object"
            )
        model_id = value.get("model_version_id")
        if not isinstance(model_id, str) or not model_id:
            raise StrategyOperationsError(
                f"operations record {index} has no model identity"
            )
        if model_id in seen:
            raise StrategyOperationsError(f"duplicate operations model: {model_id}")
        seen.add(model_id)
        if value.get("status") not in STATUS_VALUES:
            raise StrategyOperationsError(f"invalid operations status for {model_id}")
        if (
            value.get("data_freshness") not in FRESHNESS_VALUES
            or value.get("factor_freshness") not in FRESHNESS_VALUES
        ):
            raise StrategyOperationsError(
                f"invalid freshness state for {model_id}"
            )
        factor_evidence = value.get("factor_evidence")
        if not isinstance(factor_evidence, Sequence) or isinstance(
            factor_evidence, (str, bytes)
        ):
            raise StrategyOperationsError(
                f"factor evidence must be a list for {model_id}"
            )
        if value.get("factor_freshness") == "current" and not factor_evidence:
            raise StrategyOperationsError(
                f"current factor freshness requires evidence for {model_id}"
            )
