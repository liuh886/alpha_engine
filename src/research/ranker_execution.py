"""Shared market-data execution primitives for maintained cross-sectional rankers.

This module owns only the stable data-facing substrate shared by research
execution and exact economic replay: the canonical 10-session return expression,
market runtime selection, governed universe resolution, canonical candidate
factor resolution, and benchmark instrument resolution.

Window policy, training, portfolio construction, costs, support gates and model
promotion remain in their owning modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.library import load_factor_library
from src.factors.model_contract import resolve_canonical_factor_ids
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
    raw: dict[str, Any]


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


def _raw_candidate_map(spec: RankerExperimentContract) -> dict[str, dict[str, Any]]:
    rows = spec.raw.get("candidates")
    if not isinstance(rows, list):
        raise ValueError("ranker experiment requires candidate mappings")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ranker candidate entries must be mappings")
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id or candidate_id in result:
            raise ValueError(f"invalid or duplicate candidate id: {candidate_id!r}")
        result[candidate_id] = row
    expected = {candidate.candidate_id for candidate in spec.candidates}
    if set(result) != expected:
        raise ValueError("raw candidate metadata differs from validated experiment candidates")
    return result


def candidate_factor_contracts(
    spec: RankerExperimentContract,
) -> dict[str, dict[str, Any]]:
    """Resolve candidate factors across maintained canonical libraries.

    The primary factor groups continue to come from the experiment's declared
    factor library. A candidate may then append explicit canonical factor IDs
    from additional maintained library sources. Definitions are never copied
    into the experiment spec and duplicate IDs/expressions fail closed through
    :func:`resolve_canonical_factor_ids`.
    """

    factor_cfg = spec.raw.get("factor_library") or {}
    primary_source = str(factor_cfg.get("source", "")).strip()
    if not primary_source:
        raise ValueError("ranker experiment requires factor_library.source")
    primary = load_factor_library(spec.factor_library_path)
    raw_candidates = _raw_candidate_map(spec)

    contracts: dict[str, dict[str, Any]] = {}
    for candidate in spec.candidates:
        base_definitions = primary.factors_for_groups(candidate.factor_groups)
        factor_ids = [definition.factor_id for definition in base_definitions]
        library_sources = [primary_source]

        additions = raw_candidates[candidate.candidate_id].get("canonical_factor_additions")
        if additions is not None:
            if not isinstance(additions, dict):
                raise ValueError(
                    f"candidate {candidate.candidate_id} canonical_factor_additions "
                    "must be a mapping"
                )
            raw_sources = additions.get("library_sources")
            raw_ids = additions.get("factor_ids")
            if not isinstance(raw_sources, list) or not raw_sources:
                raise ValueError(
                    f"candidate {candidate.candidate_id} additions require library_sources"
                )
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ValueError(f"candidate {candidate.candidate_id} additions require factor_ids")
            library_sources.extend(str(value).strip() for value in raw_sources)
            factor_ids.extend(str(value).strip() for value in raw_ids)

        definitions = resolve_canonical_factor_ids(
            root=PROJECT_ROOT,
            library_sources=library_sources,
            factor_ids=factor_ids,
        )
        contracts[candidate.candidate_id] = {
            "library_sources": tuple(library_sources),
            "factor_ids": tuple(definition.factor_id for definition in definitions),
            "expressions": tuple(definition.expression for definition in definitions),
            "implementation_hashes": {
                definition.factor_id: definition.implementation_hash for definition in definitions
            },
        }
    return contracts


def factor_expressions(spec: RankerExperimentContract) -> dict[str, tuple[str, ...]]:
    """Resolve each declared candidate to ordered canonical expressions."""

    return {
        candidate_id: tuple(contract["expressions"])
        for candidate_id, contract in candidate_factor_contracts(spec).items()
    }


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
