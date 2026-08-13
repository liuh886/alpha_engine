"""Shared market-data execution primitives for maintained cross-sectional rankers.

This module deliberately owns only the stable data-facing substrate shared by
research execution and exact economic replay: the canonical 10-session return
expression, market runtime selection, governed universe resolution, candidate
factor-expression resolution, and benchmark instrument resolution.

Window policy, training, portfolio construction, costs, support gates and model
promotion remain in their owning modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from src.common.runtime_settings import PROJECT_ROOT
from src.research.factor_library import load_factor_library, select_factor_groups
from src.research.multi_market_readiness import load_market_watchlist, normalize_market_symbols
from src.research.qlib_execution_common import ExecutionRuntime, _resolve_benchmark_instrument

TEN_SESSION_RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"


class RankerCandidateContract(Protocol):
    candidate_id: str
    factor_groups: tuple[str, ...]


class RankerParentContract(Protocol):
    universe: dict[str, Any]


class RankerExperimentContract(Protocol):
    market: str
    benchmark: str
    factor_library_path: Path
    candidates: tuple[RankerCandidateContract, ...]
    parent: RankerParentContract


def runtime_for_market(market: str) -> ExecutionRuntime:
    """Return the maintained Qlib runtime for one supported ranker market."""

    if market == "us":
        from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

        return QlibUSExecutionRuntime()
    if market == "cn":
        from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime

        return QlibCNExecutionRuntime()
    raise ValueError(f"unsupported market: {market}")


def _resolve_repository_file(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"research path escapes repository root: {raw}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def factor_expressions(spec: RankerExperimentContract) -> dict[str, tuple[str, ...]]:
    """Resolve each declared candidate to its ordered, de-duplicated expressions."""

    library = load_factor_library(spec.factor_library_path)
    result: dict[str, tuple[str, ...]] = {}
    for candidate in spec.candidates:
        groups = select_factor_groups(library, list(candidate.factor_groups))
        expressions: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for factor in group.factors:
                if factor.expression not in seen:
                    expressions.append(factor.expression)
                    seen.add(factor.expression)
        if not expressions:
            raise ValueError(f"candidate {candidate.candidate_id} has no factors")
        result[candidate.candidate_id] = tuple(expressions)
    return result


def resolve_symbols(spec: RankerExperimentContract, runtime: ExecutionRuntime) -> list[str]:
    """Resolve the governed watchlist against the exact provider symbol set."""

    universe_path = _resolve_repository_file(str(spec.parent.universe["source"]))
    requested = load_market_watchlist(spec.market, watchlist_path=universe_path)
    available = runtime.available_symbols()
    normalized = normalize_market_symbols(
        spec.market,
        list(requested),
        available_symbols=available,
    )
    resolved = [item.normalized_symbol for item in normalized]
    missing = sorted(set(resolved) - available)
    if missing:
        raise ValueError(f"provider is missing experiment symbols: {missing}")
    min_symbols = int(spec.parent.universe["min_symbols"])
    if len(resolved) < min_symbols:
        raise ValueError(f"resolved universe has {len(resolved)} symbols; requires {min_symbols}")
    return resolved


def benchmark_instrument(
    spec: RankerExperimentContract,
    runtime: ExecutionRuntime,
) -> str:
    """Resolve the declared benchmark to the provider's maintained instrument id."""

    available = runtime.available_symbols()
    if spec.market == "us":
        matches = normalize_market_symbols("us", [spec.benchmark], available_symbols=available)
        if not matches or matches[0].normalized_symbol not in available:
            raise ValueError(f"benchmark {spec.benchmark!r} is unavailable")
        return matches[0].normalized_symbol
    return _resolve_benchmark_instrument(spec.market, spec.benchmark, available)
