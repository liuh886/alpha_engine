"""Build the single governed operations read model consumed by Strategy Console."""

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

SCHEMA_VERSION = "1.0.0"
QQQ_MODEL = "qqqi_qqq_tqqq_v4_2"
BYD_MODEL = "byd_v1_2_convex_momentum_budget_v1"
SUPPORTED_SIGNAL_MODELS = {QQQ_MODEL, BYD_MODEL}
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


def _pct(value: object, digits: int = 2) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def _num(value: object, digits: int = 2) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number:.{digits}f}"


def _weights(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        number = _finite(raw)
        if number is None:
            raise StrategyOperationsError(f"allocation weight for {key!r} must be finite")
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


def _cadence(model_version_id: str, model_kind: str) -> tuple[str, str]:
    if model_version_id == QQQ_MODEL:
        return "Every completed US market session", "Evaluate at close; target applies to the next eligible open."
    if model_version_id == BYD_MODEL:
        return "Every completed CN market session", "Evaluate after the common close; target applies to the next independently confirmed eligible open."
    if model_kind == "cross_sectional_ranker":
        return "10-session rebalance", "No governed current-target publisher is registered yet."
    return "Governed model cadence", "No governed current-target publisher is registered yet."


def _source(record: Mapping[str, Any], ledger: Mapping[str, Any] | None) -> dict[str, object]:
    result: dict[str, object] = {
        "formal_bundle_id": record.get("bundle_id"),
        "formal_run_id": record.get("run_id"),
        "formal_evidence_cutoff": record.get("evidence_cutoff"),
        "ledger_fingerprint": None,
        "signal_sha256": None,
        "workflow_run_id": None,
        "commit_sha": None,
        "github_issue_number": None,
    }
    if ledger is None:
        return result
    delivery = ledger.get("delivery") if isinstance(ledger.get("delivery"), Mapping) else {}
    workflow = ledger.get("workflow") if isinstance(ledger.get("workflow"), Mapping) else {}
    result.update(
        {
            "ledger_fingerprint": ledger.get("fingerprint"),
            "signal_sha256": ledger.get("signal_sha256"),
            "workflow_run_id": workflow.get("run_id"),
            "commit_sha": workflow.get("commit_sha"),
            "github_issue_number": delivery.get("github_issue_number"),
        }
    )
    return result


def _unavailable(record: Mapping[str, Any], *, awaiting: bool) -> dict[str, object]:
    model_version_id = str(record["model_version_id"])
    cadence, next_policy = _cadence(model_version_id, str(record.get("model_kind", "")))
    if awaiting:
        status = "awaiting_observation"
        state_label = "Awaiting first governed evaluation"
        note = "The signal publisher exists, but no durable evaluation has been committed yet."
    else:
        status = "pipeline_unavailable"
        state_label = "No governed current-target publisher"
        note = "Formal historical evidence is available; live target state is intentionally unavailable."
    return {
        "model_version_id": model_version_id,
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
        "factor_freshness": "unknown" if not awaiting else "blocked",
        "delivery_status": "not available",
        "source_label": "Formal evidence only" if not awaiting else "Governed signal ledger",
        "source_href": None,
        "note": note,
        "drivers": [],
        "source_identity": _source(record, None),
    }


def _delivery(record: Mapping[str, Any]) -> tuple[str, int | None]:
    delivery = record.get("delivery")
    if not isinstance(delivery, Mapping):
        return "not available", None
    status = str(delivery.get("status") or "not available")
    issue = delivery.get("github_issue_number")
    return status, int(issue) if isinstance(issue, int) and not isinstance(issue, bool) else None


def _qqq(record: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, object]:
    signal = ledger.get("signal")
    if not isinstance(signal, Mapping):
        raise StrategyOperationsError("QQQ ledger signal is missing")
    allocations = _allocations(signal.get("current_weights"), signal.get("target_weights"))
    changed = _has_change(allocations)
    fresh = signal.get("data_freshness_ok") is True
    delivery_status, issue_number = _delivery(ledger)
    status = (
        "delivery_failed"
        if delivery_status == "failed"
        else "stale"
        if not fresh
        else "target_pending_execution"
        if changed
        else "current_no_change"
    )
    current_state = int(signal.get("current_state", -1))
    target_state = int(signal.get("target_state", -1))
    from_label = QQQ_STATE_LABELS.get(current_state, f"State {current_state}")
    to_label = QQQ_STATE_LABELS.get(target_state, f"State {target_state}")
    price = signal.get("price_context") if isinstance(signal.get("price_context"), Mapping) else {}
    vol = signal.get("volatility_context") if isinstance(signal.get("volatility_context"), Mapping) else {}
    cadence, next_policy = _cadence(QQQ_MODEL, str(record.get("model_kind", "")))
    return {
        "model_version_id": QQQ_MODEL,
        "status": status,
        "as_of": signal.get("signal_date"),
        "latest_completed_session": signal.get("latest_data_date") or ledger.get("latest_data_date"),
        "decision_cadence": cadence,
        "next_decision_policy": next_policy,
        "state_label": to_label if current_state == target_state else f"{from_label} → {to_label}",
        "decision_reason": signal.get("decision_reason_label") or signal.get("decision_reason") or "Frozen state-machine evaluation.",
        "allocations": allocations,
        "turnover": _finite(signal.get("turnover_units")),
        "estimated_cost": _finite(signal.get("estimated_transaction_cost")),
        "data_freshness": "current" if fresh else "stale",
        "factor_freshness": "current" if fresh and price and vol else "blocked",
        "delivery_status": delivery_status,
        "source_label": "Governed QQQ signal ledger",
        "source_href": f"https://github.com/liuh886/alpha_engine/issues/{issue_number}" if issue_number else None,
        "note": "Target is awaiting next-open execution evidence." if changed else "Latest governed evaluation retained the existing allocation.",
        "drivers": [
            {"label": "VIX close", "value": _num(vol.get("vix_close"))},
            {"label": "VIX retreat", "value": _pct(vol.get("vix_retreat_from_peak"))},
            {"label": "VXN close", "value": _num(vol.get("vxn_close"))},
            {"label": "VXN retreat", "value": _pct(vol.get("vxn_retreat_from_peak"))},
            {"label": "QQQ vs MA20", "value": _pct(price.get("qqq_vs_ma20"))},
        ],
        "source_identity": _source(record, ledger),
    }


def _byd(record: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, object]:
    signal = ledger.get("signal")
    if not isinstance(signal, Mapping):
        raise StrategyOperationsError("BYD ledger signal is missing")
    allocations = _allocations(signal.get("current_weights"), signal.get("target_weights"))
    changed = _has_change(allocations)
    fresh = signal.get("data_freshness_ok") is True
    delivery_status, issue_number = _delivery(ledger)
    status = (
        "delivery_failed"
        if delivery_status == "failed"
        else "stale"
        if not fresh
        else "target_pending_execution"
        if changed
        else "current_no_change"
    )
    factors = signal.get("factor_context") if isinstance(signal.get("factor_context"), Mapping) else {}
    mode = str(signal.get("target_mode") or "")
    cadence, next_policy = _cadence(BYD_MODEL, str(record.get("model_kind", "")))
    return {
        "model_version_id": BYD_MODEL,
        "status": status,
        "as_of": signal.get("signal_date"),
        "latest_completed_session": signal.get("latest_data_date") or ledger.get("latest_data_date"),
        "decision_cadence": cadence,
        "next_decision_policy": next_policy,
        "state_label": BYD_MODE_LABELS.get(mode, mode or "BYD v1.2"),
        "decision_reason": signal.get("transition_label") or signal.get("transition_type") or "Frozen BYD allocation evaluation.",
        "allocations": allocations,
        "turnover": _finite(signal.get("turnover_units")),
        "estimated_cost": _finite(signal.get("estimated_transaction_cost")),
        "data_freshness": "current" if fresh else "stale",
        "factor_freshness": "current" if fresh and factors else "blocked",
        "delivery_status": delivery_status,
        "source_label": "Governed BYD signal ledger",
        "source_href": f"https://github.com/liuh886/alpha_engine/issues/{issue_number}" if issue_number else None,
        "note": "Target allocation is published; brokerage execution is outside Alpha Engine." if changed else "Latest governed evaluation retained the existing allocation.",
        "drivers": [
            {"label": "Market state", "value": str(factors.get("market_state") or "—")},
            {"label": "Volatility state", "value": str(factors.get("vol_state") or "—")},
            {"label": "20D momentum", "value": _pct(factors.get("mom_20"))},
            {"label": "60D momentum", "value": _pct(factors.get("mom_60"))},
            {"label": "252D drawdown", "value": _pct(factors.get("drawdown_252"))},
            {"label": "Financed increment", "value": _pct(factors.get("financed_increment"))},
        ],
        "source_identity": _source(record, ledger),
    }


def build_operations_payload(
    *,
    formal_catalog: Path,
    ledger_root: Path,
    generated_at: str,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for formal in _formal_records(formal_catalog):
        model_version_id = str(formal["model_version_id"])
        try:
            ledger = read_latest_evaluation(
                ledger_root / model_version_id,
                model_version_id=model_version_id,
            )
        except (OSError, json.JSONDecodeError, StrategySignalLedgerError) as exc:
            cadence, next_policy = _cadence(model_version_id, str(formal.get("model_kind", "")))
            records.append(
                {
                    **_unavailable(formal, awaiting=model_version_id in SUPPORTED_SIGNAL_MODELS),
                    "status": "blocked",
                    "decision_cadence": cadence,
                    "next_decision_policy": next_policy,
                    "decision_reason": str(exc),
                    "note": "Governed signal ledger failed validation; operations fail closed.",
                }
            )
            continue
        if ledger is None:
            records.append(_unavailable(formal, awaiting=model_version_id in SUPPORTED_SIGNAL_MODELS))
        elif model_version_id == QQQ_MODEL:
            records.append(_qqq(formal, ledger))
        elif model_version_id == BYD_MODEL:
            records.append(_byd(formal, ledger))
        else:
            blocked = _unavailable(formal, awaiting=False)
            blocked["status"] = "blocked"
            blocked["decision_reason"] = "A signal ledger exists but no governed operations adapter is registered."
            blocked["note"] = "Backend adapter required before this signal can be published."
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
            raise StrategyOperationsError(f"operations record {index} must be an object")
        model_id = value.get("model_version_id")
        if not isinstance(model_id, str) or not model_id:
            raise StrategyOperationsError(f"operations record {index} has no model identity")
        if model_id in seen:
            raise StrategyOperationsError(f"duplicate operations model: {model_id}")
        seen.add(model_id)
        if value.get("status") not in STATUS_VALUES:
            raise StrategyOperationsError(f"invalid operations status for {model_id}")
        if value.get("data_freshness") not in FRESHNESS_VALUES or value.get("factor_freshness") not in FRESHNESS_VALUES:
            raise StrategyOperationsError(f"invalid freshness state for {model_id}")
