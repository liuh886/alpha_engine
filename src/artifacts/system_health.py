"""Build one multi-watermark health snapshot from governed read models."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.artifacts.model_run_bundle_v2 import validate_catalog
from src.governance.active_strategy_catalog import (
    ActiveStrategy,
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)

SCHEMA_VERSION = "1.0.0"
STATES = {"current", "delayed", "blocked", "inconsistent", "not_applicable"}
HEALTH_PRECEDENCE = {
    "not_applicable": 0,
    "current": 1,
    "delayed": 2,
    "blocked": 3,
    "inconsistent": 4,
}


class SystemHealthError(ValueError):
    """Raised when governed health inputs are structurally inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemHealthError(f"invalid health input: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemHealthError(f"health input root must be an object: {path}")
    return payload


def _date(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise SystemHealthError(f"invalid health watermark: {value}") from exc


def _max_date(values: Sequence[str | None]) -> str | None:
    retained = [value for value in values if value]
    return max(retained) if retained else None


def _state_max(states: Sequence[str]) -> str:
    invalid = set(states) - STATES
    if invalid:
        raise SystemHealthError(f"unsupported health states: {sorted(invalid)}")
    return max(states, key=lambda value: HEALTH_PRECEDENCE[value])


def _factor_cutoff(operation: Mapping[str, Any]) -> str | None:
    rows = operation.get("factor_evidence")
    if isinstance(rows, list):
        observed = [
            _date(row.get("observed_at"))
            for row in rows
            if isinstance(row, Mapping)
        ]
        if any(observed):
            return _max_date(observed)
    return _date(operation.get("latest_completed_session"))


def _last_signal_change(strategy: ActiveStrategy, repository_root: Path) -> str | None:
    records_root = repository_root / strategy.signal_ledger / "records"
    if not records_root.is_dir():
        return None
    changed: list[str] = []
    for path in sorted(records_root.glob("*.json")):
        payload = _object(path)
        signal = payload.get("signal")
        if not isinstance(signal, Mapping) or signal.get("should_alert") is not True:
            continue
        observed = _date(payload.get("signal_date") or signal.get("signal_date"))
        if observed:
            changed.append(observed)
    return max(changed) if changed else None


def _delivery_state(status_value: object) -> tuple[str, str | None]:
    status = str(status_value or "")
    if status in {"sent"}:
        return "current", status
    if status in {"not_required", "unchanged", "suppressed"}:
        return "not_applicable", status
    if status in {"failed", "delivery_failed", "error"}:
        return "blocked", status
    if status in {"pending", "skipped_not_configured"}:
        return "delayed", status
    if status in {"not available", ""}:
        return "not_applicable", None
    raise SystemHealthError(f"unsupported delivery status: {status}")


def _operation_state(operation: Mapping[str, Any]) -> str:
    status = str(operation.get("status") or "")
    if status in {"blocked", "pipeline_unavailable", "delivery_failed"}:
        return "blocked"
    if status == "stale":
        return "delayed"
    if status in {
        "awaiting_observation",
        "current_no_change",
        "target_pending_execution",
        "execution_observed",
    }:
        return "current"
    raise SystemHealthError(f"unsupported Strategy Operations status: {status}")


def _freshness_state(value: object) -> str:
    text = str(value or "unknown")
    if text == "current":
        return "current"
    if text == "stale":
        return "delayed"
    if text in {"blocked", "unknown"}:
        return "blocked"
    raise SystemHealthError(f"unsupported freshness status: {text}")


def build_system_health(
    *,
    repository_root: Path,
    formal_catalog: Path,
    formal_freshness: Path,
    operations: Mapping[str, Any],
    model_data_readiness: Path,
    generated_at: str,
) -> dict[str, Any]:
    """Build health from the canonical Strategy Operations read model."""

    root = repository_root.resolve()
    active = load_active_strategy_catalog(root / "configs/strategies/registry.json")
    formal = _object(formal_catalog)
    validate_catalog(formal)
    assert_formal_catalog_matches_active_strategies(formal, active)
    freshness = _object(formal_freshness)
    model_data = _object(model_data_readiness)

    operation_rows = operations.get("records")
    formal_rows = formal.get("records")
    if not isinstance(operation_rows, list) or not isinstance(formal_rows, list):
        raise SystemHealthError("formal/operations records are missing")
    operations_by_model = {
        str(row.get("model_version_id")): row
        for row in operation_rows
        if isinstance(row, Mapping)
    }
    formal_by_model = {
        str(row.get("model_version_id")): row
        for row in formal_rows
        if isinstance(row, Mapping)
    }
    expected_ids = set(active.active_model_version_ids)
    if set(operations_by_model) != expected_ids or set(formal_by_model) != expected_ids:
        raise SystemHealthError("health inputs do not exactly match the active strategy set")

    market_cutoffs = freshness.get("markets")
    if not isinstance(market_cutoffs, Mapping):
        raise SystemHealthError("formal provider-resolved market cutoffs are missing")
    model_data_cutoff = _date(model_data.get("evidence_cutoff"))
    model_data_summary = model_data.get("summary")
    if not isinstance(model_data_summary, Mapping):
        raise SystemHealthError("model-data readiness summary is missing")
    model_data_state = (
        "current"
        if int(model_data_summary.get("blocked_component_count", 0)) == 0
        and int(model_data_summary.get("partial_component_count", 0)) == 0
        else "blocked"
    )

    expected_market_candidates: dict[str, list[str | None]] = {}
    last_changes: dict[str, str | None] = {}
    for strategy in active.strategies:
        operation = operations_by_model[strategy.model_version_id]
        formal_record = formal_by_model[strategy.model_version_id]
        last_changes[strategy.model_version_id] = _last_signal_change(strategy, root)
        expected_market_candidates.setdefault(strategy.market, []).extend(
            [
                _date(market_cutoffs.get(strategy.market)),
                _date(formal_record.get("evidence_cutoff")),
                _date(operation.get("latest_completed_session")),
                _date(operation.get("as_of")),
            ]
        )

    markets: list[dict[str, Any]] = []
    market_state: dict[str, str] = {}
    market_expected: dict[str, str | None] = {}
    for market in sorted(expected_market_candidates):
        provider_cutoff = _date(market_cutoffs.get(market))
        expected_cutoff = _max_date(expected_market_candidates[market])
        if provider_cutoff is None or expected_cutoff is None:
            state = "blocked"
        elif provider_cutoff < expected_cutoff:
            state = "delayed"
        elif provider_cutoff == expected_cutoff:
            state = "current"
        else:
            state = "inconsistent"
        market_state[market] = state
        market_expected[market] = expected_cutoff
        markets.append(
            {
                "market": market,
                "state": state,
                "market_expected_cutoff": expected_cutoff,
                "market_expected_cutoff_source": "max_governed_active_watermark",
                "provider_cutoff": provider_cutoff,
                "provider_cutoff_source": "provider_resolved_common_session",
                "provider_lag_sessions": 0 if state == "current" else None,
                "provider_lag_exact": state == "current",
                "provider_formal_consistency": (
                    "current" if state in {"current", "delayed"} else state
                ),
            }
        )

    strategies: list[dict[str, Any]] = []
    for strategy in active.strategies:
        model_id = strategy.model_version_id
        operation = operations_by_model[model_id]
        formal_record = formal_by_model[model_id]
        provider_cutoff = _date(market_cutoffs.get(strategy.market))
        formal_cutoff = _date(formal_record.get("evidence_cutoff"))
        factor_cutoff = _factor_cutoff(operation)
        signal_evaluation = _date(operation.get("as_of")) or _date(
            operation.get("latest_completed_session")
        )
        delivery_state, delivery_status = _delivery_state(
            operation.get("delivery_status")
        )
        formal_state = (
            "blocked"
            if formal_cutoff is None or provider_cutoff is None
            else ("delayed" if formal_cutoff < provider_cutoff else "current")
        )
        data_state = model_data_state
        if (
            data_state == "current"
            and provider_cutoff is not None
            and model_data_cutoff is not None
            and model_data_cutoff < provider_cutoff
        ):
            data_state = "delayed"
        factor_state = _freshness_state(operation.get("factor_freshness"))
        signal_state = _operation_state(operation)
        internal_state = _state_max(
            [market_state[strategy.market], formal_state, data_state, factor_state, signal_state]
        )
        strategies.append(
            {
                "strategy_id": strategy.strategy_id,
                "model_version_id": model_id,
                "market": strategy.market,
                "state": internal_state,
                "market_expected_cutoff": market_expected[strategy.market],
                "provider_cutoff": provider_cutoff,
                "formal_cutoff": formal_cutoff,
                "model_data_cutoff": model_data_cutoff,
                "factor_cutoff": factor_cutoff,
                "last_signal_evaluation": signal_evaluation,
                "last_signal_change": last_changes[model_id],
                "delivery_state": delivery_state,
                "delivery_status": delivery_status,
                "stages": {
                    "provider": market_state[strategy.market],
                    "formal": formal_state,
                    "model_data": data_state,
                    "factor": factor_state,
                    "signal": signal_state,
                    "delivery": delivery_state,
                },
                "formal_bundle_id": formal_record.get("bundle_id"),
                "formal_run_id": formal_record.get("run_id"),
            }
        )

    deployment_commit = os.environ.get("GITHUB_SHA") or None
    deployment_run = os.environ.get("GITHUB_RUN_ID") or None
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "state": _state_max([row["state"] for row in strategies]),
        "markets": markets,
        "strategies": strategies,
        "deployment": {
            "state": "not_applicable",
            "expected_commit_sha": deployment_commit,
            "workflow_run_id": deployment_run,
            "live_acceptance": "verified_after_deployment",
            "receipt": "deployment.json",
        },
        "model_data": {
            "state": model_data_state,
            "evidence_cutoff": model_data_cutoff,
            "bundle_id": model_data.get("bundle_id"),
        },
        "research_only": True,
        "trade_ready": False,
    }


def validate_system_health(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SystemHealthError("unsupported system health schema")
    if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
        raise SystemHealthError("system health research boundary is invalid")
    if payload.get("state") not in STATES:
        raise SystemHealthError("system health state is invalid")
    markets = payload.get("markets")
    strategies = payload.get("strategies")
    if not isinstance(markets, list) or not markets:
        raise SystemHealthError("system health markets are missing")
    if not isinstance(strategies, list) or not strategies:
        raise SystemHealthError("system health strategies are missing")
    for row in [*markets, *strategies]:
        if not isinstance(row, Mapping) or row.get("state") not in STATES:
            raise SystemHealthError("system health row state is invalid")
    for row in strategies:
        stages = row.get("stages")
        if not isinstance(stages, Mapping):
            raise SystemHealthError("strategy health stages are missing")
        if any(value not in STATES for value in stages.values()):
            raise SystemHealthError("strategy stage state is invalid")


def write_system_health(path: Path, payload: Mapping[str, Any]) -> bool:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    current = path.read_text(encoding="utf-8") if path.is_file() else None
    if current == encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")
    return True