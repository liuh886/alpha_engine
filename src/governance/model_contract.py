"""Read execution/performance semantics from an active strategy's model contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.governance.active_strategy_catalog import ActiveStrategy

SEMANTICS_SCHEMA = "formal_performance_semantics_v1"
REQUIRED_TEXT = (
    "trace_frequency",
    "signal_time",
    "execution_time",
    "return_measurement",
    "price_basis",
    "performance_date_field",
)


class ModelContractError(ValueError):
    """Raised when an active model contract is missing authoritative semantics."""


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip() == "not_declared":
        raise ModelContractError(f"{label} must be explicitly declared")
    return value.strip()


def _model_id(payload: Mapping[str, Any]) -> str:
    direct = payload.get("model_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    baseline = payload.get("current_research_baseline")
    if isinstance(baseline, Mapping):
        nested = baseline.get("model_id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    raise ModelContractError("model contract does not declare model_id")


def load_performance_semantics(
    strategy: ActiveStrategy,
    *,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    path = (root / strategy.model_contract).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ModelContractError(
            f"model contract escapes repository root: {strategy.model_contract}"
        ) from exc
    if not path.is_file():
        raise ModelContractError(f"model contract is missing: {strategy.model_contract}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ModelContractError(f"model contract root must be a mapping: {strategy.model_contract}")
    if _model_id(payload) != strategy.model_version_id:
        raise ModelContractError(
            f"model contract identity mismatch: {_model_id(payload)} != {strategy.model_version_id}"
        )

    raw = payload.get("performance_semantics")
    if not isinstance(raw, Mapping):
        raise ModelContractError(
            f"performance_semantics missing from {strategy.model_contract}"
        )
    if raw.get("schema_version") != SEMANTICS_SCHEMA:
        raise ModelContractError(
            f"unsupported performance semantics schema: {strategy.model_contract}"
        )
    semantics = {key: _text(raw.get(key), label=key) for key in REQUIRED_TEXT}
    offset = raw.get("holding_end_offset_sessions")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ModelContractError("holding_end_offset_sessions must be a non-negative integer")

    raw_cost = raw.get("cost")
    if not isinstance(raw_cost, Mapping):
        raise ModelContractError("performance semantics cost block is missing")
    rate = raw_cost.get("rate_bps")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate < 0:
        raise ModelContractError("performance semantics cost.rate_bps is invalid")
    cost = {
        "rate_bps": float(rate),
        "turnover_formula": _text(raw_cost.get("turnover_formula"), label="cost.turnover_formula"),
        "row_cost_field": _text(raw_cost.get("row_cost_field"), label="cost.row_cost_field"),
        "net_return_formula": _text(
            raw_cost.get("net_return_formula"), label="cost.net_return_formula"
        ),
        "browser_recomputation_permitted": False,
    }
    semantics.update(
        {
            "schema_version": SEMANTICS_SCHEMA,
            "holding_end_offset_sessions": offset,
            "cost": cost,
            "source": strategy.model_contract,
            "research_only": True,
            "trade_ready": False,
        }
    )
    return semantics
