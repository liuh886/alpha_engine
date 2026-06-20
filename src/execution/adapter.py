"""Adapters from existing strategy configuration shapes to execution requests.

The adapter is deliberately Qlib-free: callers pass plain config dictionaries,
scores, current positions, and tradability information. The execution engine
then owns the deterministic target-weight contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.execution.engine import StrategyExecutionEngine
from src.execution.models import (
    ExecutionConfig,
    ExecutionRequest,
    ExecutionResult,
    MarketDataSnapshot,
    PortfolioState,
    RiskPolicy,
    SignalFrame,
)

DEFAULT_CASH = 0.0


def build_execution_request(
    strategy_config: Mapping[str, Any] | None,
    *,
    asof_date: str,
    scores: Any,
    portfolio_positions: Mapping[str, float] | None = None,
    cash: float = DEFAULT_CASH,
    prices: Mapping[str, float] | None = None,
    tradable: Mapping[str, bool] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionRequest:
    """Build an ExecutionRequest from an existing strategy/profile config."""

    config = strategy_config or {}
    strategy_kwargs = _strategy_kwargs(config)
    risk_config = _risk_config(config, strategy_kwargs)

    topk = _coerce_int(
        strategy_kwargs.get("topk", _profile_position_rule(config).get("topk")),
        default=ExecutionConfig().topk,
    )
    max_position_weight = _coerce_float(
        risk_config.get("max_position_weight"),
        default=RiskPolicy().max_position_weight,
    )
    allow_shorts = bool(risk_config.get("allow_shorts", RiskPolicy().allow_shorts))

    return ExecutionRequest(
        signals=SignalFrame(
            asof_date=asof_date,
            scores=_scores_to_mapping(scores),
        ),
        portfolio=PortfolioState(
            cash=float(cash),
            positions=_float_mapping(portfolio_positions),
        ),
        market=MarketDataSnapshot(
            prices=_float_mapping(prices),
            tradable=_bool_mapping(tradable),
            metadata=dict(metadata or {}),
        ),
        risk_policy=RiskPolicy(
            max_position_weight=max_position_weight,
            allow_shorts=allow_shorts,
        ),
        config=ExecutionConfig(topk=topk),
    )


class StrategyExecutionAdapter:
    """Thin facade that executes existing strategy configs through the new core."""

    def __init__(
        self,
        strategy_config: Mapping[str, Any] | None,
        *,
        engine: StrategyExecutionEngine | None = None,
    ) -> None:
        self.strategy_config = strategy_config or {}
        self.engine = engine or StrategyExecutionEngine()

    def build_request(
        self,
        *,
        asof_date: str,
        scores: Any,
        portfolio_positions: Mapping[str, float] | None = None,
        cash: float = DEFAULT_CASH,
        prices: Mapping[str, float] | None = None,
        tradable: Mapping[str, bool] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionRequest:
        return build_execution_request(
            self.strategy_config,
            asof_date=asof_date,
            scores=scores,
            portfolio_positions=portfolio_positions,
            cash=cash,
            prices=prices,
            tradable=tradable,
            metadata=metadata,
        )

    def execute(
        self,
        *,
        asof_date: str,
        scores: Any,
        portfolio_positions: Mapping[str, float] | None = None,
        cash: float = DEFAULT_CASH,
        prices: Mapping[str, float] | None = None,
        tradable: Mapping[str, bool] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        request = self.build_request(
            asof_date=asof_date,
            scores=scores,
            portfolio_positions=portfolio_positions,
            cash=cash,
            prices=prices,
            tradable=tradable,
            metadata=metadata,
        )
        return self.engine.execute(request)


def _strategy_kwargs(config: Mapping[str, Any]) -> dict[str, Any]:
    compiled_strategy = _as_mapping(
        _as_mapping(_as_mapping(config.get("port_analysis_config")).get("strategy")).get("kwargs")
    )
    if compiled_strategy:
        return dict(compiled_strategy)

    profile_strategy = _as_mapping(config.get("strategy"))
    profile_kwargs = _as_mapping(profile_strategy.get("kwargs"))
    if profile_kwargs:
        return dict(profile_kwargs)

    direct_kwargs = _as_mapping(config.get("kwargs"))
    if direct_kwargs:
        return dict(direct_kwargs)

    return dict(config)


def _profile_position_rule(config: Mapping[str, Any]) -> dict[str, Any]:
    strategy = _as_mapping(config.get("strategy"))
    return dict(_as_mapping(strategy.get("position_rule")))


def _risk_config(config: Mapping[str, Any], strategy_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    risk_config = _as_mapping(strategy_kwargs.get("risk_config"))
    if risk_config:
        return dict(risk_config)

    strategy = _as_mapping(config.get("strategy"))
    profile_risk = _as_mapping(strategy.get("risk_config"))
    if profile_risk:
        return dict(profile_risk)

    direct_risk = _as_mapping(config.get("risk_config"))
    if direct_risk:
        return dict(direct_risk)

    return dict(_as_mapping(config.get("risk_policy")))


def _scores_to_mapping(scores: Any) -> dict[str, float]:
    if hasattr(scores, "iloc") and hasattr(scores, "columns"):
        scores = scores.iloc[:, 0]

    raw_scores = scores.to_dict() if hasattr(scores, "to_dict") else scores
    if not isinstance(raw_scores, Mapping):
        raise TypeError("scores must be a mapping, pandas Series, or single-column DataFrame")

    return {
        _instrument_key(instrument): float(score)
        for instrument, score in raw_scores.items()
        if score is not None
    }


def _instrument_key(instrument: Any) -> str:
    if isinstance(instrument, tuple | list) and instrument:
        return str(instrument[-1])
    return str(instrument)


def _float_mapping(values: Mapping[str, float] | None) -> dict[str, float]:
    return {str(key): float(value) for key, value in (values or {}).items()}


def _bool_mapping(values: Mapping[str, bool] | None) -> dict[str, bool]:
    return {str(key): bool(value) for key, value in (values or {}).items()}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _coerce_int(value: Any, *, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _coerce_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    return float(value)
