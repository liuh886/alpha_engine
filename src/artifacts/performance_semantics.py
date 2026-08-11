"""Machine-readable timing and cost semantics for formal performance evidence."""

from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = "formal_performance_semantics_v1"


class PerformanceSemanticsError(ValueError):
    """Raised when formal performance semantics are incomplete or inconsistent."""


def _session_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    return count if count >= 0 and count == value else None


def _declared_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() in {"not_declared", "not declared"}:
        return None
    return text


def build_performance_semantics(
    portfolio_contract: Mapping[str, Any], *, trace_frequency: object
) -> dict[str, Any]:
    """Project timing/cost meaning only from the governed portfolio contract.

    Missing source declarations stay explicit; this function never guesses from
    a model id or from frontend defaults.
    """

    holding = _session_count(
        portfolio_contract.get("horizon_sessions")
        if portfolio_contract.get("horizon_sessions") is not None
        else portfolio_contract.get("holding_sessions")
    )
    delay = _session_count(portfolio_contract.get("execution_delay_sessions"))
    declared_offset = portfolio_contract.get("holding_end_offset_sessions")
    end_offset: int | str | None
    if _session_count(declared_offset) is not None:
        end_offset = int(declared_offset)
    elif _declared_text(declared_offset) is not None:
        end_offset = str(declared_offset)
    else:
        end_offset = holding + delay if holding is not None and delay is not None else None

    raw_cost = portfolio_contract.get("cost_bps")
    cost_bps = (
        float(raw_cost)
        if isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool)
        and raw_cost >= 0
        else None
    )
    turnover_formula = portfolio_contract.get("turnover_formula")
    net_return_formula = portfolio_contract.get("net_return_formula")
    performance_date_field = portfolio_contract.get("performance_date_field")
    if performance_date_field not in {"date", "holding_end_date"}:
        performance_date_field = "holding_end_date" if holding is not None and delay is not None else "date"
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_frequency": str(trace_frequency or "not_declared"),
        "session_unit": str(portfolio_contract.get("session_unit") or "provider_session"),
        "signal_time": str(portfolio_contract.get("signal_time") or "not_declared"),
        "execution_time": str(portfolio_contract.get("execution_time") or "not_declared"),
        "return_measurement": str(
            portfolio_contract.get("return_measurement")
            or portfolio_contract.get("return_expression")
            or "not_declared"
        ),
        "price_basis": str(portfolio_contract.get("price_basis") or "not_declared"),
        "execution_delay_sessions": delay,
        "holding_period_sessions": holding,
        "holding_end_offset_sessions": end_offset,
        "performance_date_field": performance_date_field,
        "cost": {
            "rate_bps": cost_bps,
            "turnover_formula": (
                str(turnover_formula) if turnover_formula else "not_declared"
            ),
            "row_cost_field": "transaction_cost",
            "net_return_formula": (
                str(net_return_formula)
                if net_return_formula
                else "gross_return - transaction_cost"
            ),
            "browser_recomputation_permitted": False,
        },
        "source": "formal.portfolio_contract",
        "research_only": True,
        "trade_ready": False,
    }


def validate_performance_semantics(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise PerformanceSemanticsError("unsupported performance semantics schema")
    if value.get("research_only") is not True or value.get("trade_ready") is not False:
        raise PerformanceSemanticsError("performance semantics safety boundary is invalid")
    if value.get("performance_date_field") not in {"date", "holding_end_date"}:
        raise PerformanceSemanticsError("performance date field is invalid")
    cost = value.get("cost")
    if not isinstance(cost, Mapping) or cost.get("browser_recomputation_permitted") is not False:
        raise PerformanceSemanticsError("formal cost semantics are invalid")
    delay = value.get("execution_delay_sessions")
    holding = value.get("holding_period_sessions")
    offset = value.get("holding_end_offset_sessions")
    if delay is not None and (not isinstance(delay, int) or delay < 0):
        raise PerformanceSemanticsError("execution delay is invalid")
    if holding is not None and (not isinstance(holding, int) or holding < 1):
        raise PerformanceSemanticsError("holding period is invalid")
    fixed_offset = isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0
    policy_offset = _declared_text(offset) is not None
    if not fixed_offset and not policy_offset and offset is not None:
        raise PerformanceSemanticsError("holding-end offset is invalid")
    if delay is not None and holding is not None and fixed_offset:
        if offset != delay + holding:
            raise PerformanceSemanticsError("holding-end offset does not match delay plus holding")
