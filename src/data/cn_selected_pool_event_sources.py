"""Acquire CN selected-pool event sources with bounded provider concurrency."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from src.data.corporate_actions.ashare_public_actions import (
    AsharePublicActionClient,
    eastmoney_dividend_to_events,
)
from src.data.exact_frame_cache import (
    ExactFrameSnapshot,
    load_exact_frame_snapshot,
    write_exact_frame_snapshot,
)
from src.data.fundamentals.ashare_public_financials import (
    AsharePublicFinancialClient,
    cninfo_period_disclosures,
    sina_statement_to_events,
)
from src.data.selected_pool_event_population import SymbolPopulation

STATEMENTS = ("资产负债表", "利润表", "现金流量表")
STATEMENT_CACHE_NAMES = {
    "资产负债表": "balance_sheet",
    "利润表": "income_statement",
    "现金流量表": "cash_flow_statement",
}
_LANE_ORDER = ("cninfo_disclosures", "sina_statements", "eastmoney_dividends")
_REUSE_MODES = {"exact_cutoff_reuse", "legacy_exact_cutoff_reuse"}


@dataclass(frozen=True)
class CnEventSourcePopulation:
    """Exact-pool populations and the acquisition receipt used to produce them."""

    fundamentals: Mapping[str, SymbolPopulation]
    corporate_actions: Mapping[str, SymbolPopulation]
    source_reuse: Mapping[str, Any]


@dataclass(frozen=True)
class _LaneResult:
    frames: Mapping[str, pd.DataFrame] | None
    retrieved_at: str | None
    mode: str
    duration_ms: int
    error: str | None = None


def _cn_exchange(symbol: str) -> str:
    if symbol.startswith(("4", "8", "9")):
        return "BSE"
    return "SSE" if symbol.startswith(("5", "6")) else "SZSE"


def _duration_ms(started_at: float, clock: Callable[[], float]) -> int:
    return max(0, int(round((clock() - started_at) * 1000)))


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _validate_frames(
    frames: Mapping[str, pd.DataFrame],
    frame_names: Sequence[str],
) -> dict[str, pd.DataFrame]:
    expected = tuple(frame_names)
    if set(frames) != set(expected):
        raise ValueError("provider lane returned an unexpected frame set")
    normalized: dict[str, pd.DataFrame] = {}
    for name in expected:
        frame = frames[name]
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"provider lane value is not a DataFrame: {name}")
        normalized[name] = frame
    return normalized


def _acquire_lane(
    *,
    cache_root: Path | None,
    identity: Mapping[str, Any],
    frame_names: Sequence[str],
    retrieved_at: str,
    refresh_cache: bool,
    fetch: Callable[[], Mapping[str, pd.DataFrame]],
    legacy_snapshot: ExactFrameSnapshot | None,
    clock: Callable[[], float],
) -> _LaneResult:
    started_at = clock()
    try:
        if cache_root is not None and not refresh_cache:
            snapshot = load_exact_frame_snapshot(
                cache_root,
                identity=identity,
                frame_names=frame_names,
            )
            if snapshot is not None:
                return _LaneResult(
                    snapshot.frames,
                    snapshot.retrieved_at,
                    "exact_cutoff_reuse",
                    _duration_ms(started_at, clock),
                )
            if legacy_snapshot is not None:
                frames = _validate_frames(
                    {name: legacy_snapshot.frames[name] for name in frame_names},
                    frame_names,
                )
                write_exact_frame_snapshot(
                    cache_root,
                    identity=identity,
                    retrieved_at=legacy_snapshot.retrieved_at,
                    frames=frames,
                )
                return _LaneResult(
                    frames,
                    legacy_snapshot.retrieved_at,
                    "legacy_exact_cutoff_reuse",
                    _duration_ms(started_at, clock),
                )

        frames = _validate_frames(fetch(), frame_names)
        if cache_root is not None:
            write_exact_frame_snapshot(
                cache_root,
                identity=identity,
                retrieved_at=retrieved_at,
                frames=frames,
            )
        return _LaneResult(
            frames,
            retrieved_at,
            "source_fetch",
            _duration_ms(started_at, clock),
        )
    except Exception as exc:
        return _LaneResult(
            None,
            None,
            "source_fetch_failed",
            _duration_ms(started_at, clock),
            _error(exc),
        )


def _legacy_snapshot(
    cache_root: Path | None,
    *,
    identity: Mapping[str, Any],
    refresh_cache: bool,
) -> ExactFrameSnapshot | None:
    if cache_root is None or refresh_cache:
        return None
    if (
        (cache_root / "cninfo" / "metadata.json").is_file()
        and (cache_root / "sina" / "metadata.json").is_file()
    ):
        return None
    return load_exact_frame_snapshot(
        cache_root,
        identity=identity,
        frame_names=["disclosures", *STATEMENT_CACHE_NAMES.values()],
    )


def _latest_retrieved_at(*values: str | None) -> str:
    normalized = [value for value in values if value]
    if len(normalized) != len(values):
        raise ValueError("all successful source lanes require retrieved_at")

    def parsed(value: str) -> datetime:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("source retrieved_at must be timezone-aware")
        return result

    return max(normalized, key=parsed)


def _percentile(values: Sequence[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _lane_summary(results: Mapping[str, _LaneResult]) -> dict[str, Any]:
    modes = {symbol: result.mode for symbol, result in results.items()}
    durations = {symbol: result.duration_ms for symbol, result in results.items()}
    slowest = sorted(durations.items(), key=lambda item: (-item[1], item[0]))[:5]
    return {
        "exact_cutoff_reuse_count": sum(
            result.mode == "exact_cutoff_reuse" for result in results.values()
        ),
        "legacy_exact_cutoff_reuse_count": sum(
            result.mode == "legacy_exact_cutoff_reuse" for result in results.values()
        ),
        "source_fetch_count": sum(
            result.mode == "source_fetch" for result in results.values()
        ),
        "source_fetch_failed_count": sum(
            result.mode == "source_fetch_failed" for result in results.values()
        ),
        "modes": modes,
        "duration_ms": {
            "total_provider_work": sum(durations.values()),
            "p50": _percentile(list(durations.values()), 0.50),
            "p95": _percentile(list(durations.values()), 0.95),
            "max": max(durations.values(), default=0),
            "slowest_symbols": [
                {"symbol": symbol, "duration_ms": duration}
                for symbol, duration in slowest
            ],
        },
    }


def _aggregate_summary(modes: Mapping[str, str]) -> dict[str, Any]:
    return {
        "exact_cutoff_reuse_count": sum(
            mode == "exact_cutoff_reuse" for mode in modes.values()
        ),
        "source_fetch_count": sum(mode == "source_fetch" for mode in modes.values()),
        "source_fetch_failed_count": sum(
            mode in {"source_fetch_failed", "source_transform_failed"}
            for mode in modes.values()
        ),
        "mixed_source_reuse_count": sum(
            mode == "mixed_source_reuse" for mode in modes.values()
        ),
        "modes": dict(modes),
    }


def _fundamental_mode(cninfo: _LaneResult, sina: _LaneResult) -> str:
    modes = {cninfo.mode, sina.mode}
    if "source_fetch_failed" in modes:
        return "source_fetch_failed"
    if modes == {"source_fetch"}:
        return "source_fetch"
    if modes.issubset(_REUSE_MODES):
        return "exact_cutoff_reuse"
    return "mixed_source_reuse"


def _default_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _emit_progress(
    progress: Callable[[str], None],
    *,
    symbol: str,
    symbol_index: int,
    symbol_count: int,
    duration_ms: int,
    lanes: Mapping[str, _LaneResult],
    fundamental_status: str,
    action_status: str,
) -> None:
    progress(
        json.dumps(
            {
                "event": "cn_selected_pool_symbol_complete",
                "symbol": symbol,
                "symbol_index": symbol_index,
                "symbol_count": symbol_count,
                "duration_ms": duration_ms,
                "lane_modes": {name: lanes[name].mode for name in _LANE_ORDER},
                "lane_duration_ms": {
                    name: lanes[name].duration_ms for name in _LANE_ORDER
                },
                "fundamental_status": fundamental_status,
                "corporate_action_status": action_status,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def populate_cn_selected_pool_event_sources(
    symbols: Sequence[str],
    field_map: Mapping[str, Any],
    retrieved_at: str,
    *,
    start_date: str,
    end_date: str,
    source_cache_root: Path | None = None,
    refresh_source_cache: bool = False,
    clock: Callable[[], float] = perf_counter,
    progress: Callable[[str], None] = _default_progress,
) -> CnEventSourcePopulation:
    """Populate one exact CN pool with one concurrent lane per provider."""

    selected_symbols = [str(symbol).strip().upper() for symbol in symbols]
    if not selected_symbols or len(selected_symbols) != len(set(selected_symbols)):
        raise ValueError("CN selected-pool symbols must be non-empty and unique")

    disclosure_client = AsharePublicFinancialClient()
    statement_client = AsharePublicFinancialClient()
    action_client = AsharePublicActionClient()
    cache_root = Path(source_cache_root) if source_cache_root is not None else None
    start_compact = start_date.replace("-", "")
    end_compact = end_date.replace("-", "")
    fundamentals: dict[str, SymbolPopulation] = {}
    actions: dict[str, SymbolPopulation] = {}
    lane_results: dict[str, dict[str, _LaneResult]] = {
        name: {} for name in _LANE_ORDER
    }
    fundamental_modes: dict[str, str] = {}
    action_modes: dict[str, str] = {}
    run_started_at = clock()

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="cn-event-source") as executor:
        for symbol_index, symbol in enumerate(selected_symbols, start=1):
            symbol_started_at = clock()
            exchange = _cn_exchange(symbol)
            base_identity = {
                "market": "cn",
                "symbol": symbol,
                "exchange": exchange,
                "start": start_date,
                "cutoff": end_date,
            }
            legacy = _legacy_snapshot(
                cache_root / "fundamentals" / symbol if cache_root is not None else None,
                identity={
                    **base_identity,
                    "source_provider": "akshare_sina_financial_report_cninfo_time",
                },
                refresh_cache=refresh_source_cache,
            )
            cninfo_future = executor.submit(
                _acquire_lane,
                cache_root=(
                    cache_root / "fundamentals" / symbol / "cninfo"
                    if cache_root is not None
                    else None
                ),
                identity={**base_identity, "source_provider": "akshare_cninfo_disclosures"},
                frame_names=["disclosures"],
                retrieved_at=retrieved_at,
                refresh_cache=refresh_source_cache,
                fetch=lambda symbol=symbol: {
                    "disclosures": disclosure_client.fetch_disclosures(
                        symbol=symbol,
                        start_date=start_compact,
                        end_date=end_compact,
                    )
                },
                legacy_snapshot=legacy,
                clock=clock,
            )
            sina_future = executor.submit(
                _acquire_lane,
                cache_root=(
                    cache_root / "fundamentals" / symbol / "sina"
                    if cache_root is not None
                    else None
                ),
                identity={
                    **base_identity,
                    "source_provider": "akshare_sina_financial_reports",
                },
                frame_names=list(STATEMENT_CACHE_NAMES.values()),
                retrieved_at=retrieved_at,
                refresh_cache=refresh_source_cache,
                fetch=lambda symbol=symbol, exchange=exchange: {
                    STATEMENT_CACHE_NAMES[statement]: statement_client.fetch_statement(
                        symbol=symbol,
                        exchange=exchange,
                        statement=statement,
                    )
                    for statement in STATEMENTS
                },
                legacy_snapshot=legacy,
                clock=clock,
            )
            action_future = executor.submit(
                _acquire_lane,
                cache_root=(
                    cache_root / "corporate_actions" / symbol
                    if cache_root is not None
                    else None
                ),
                identity={
                    **base_identity,
                    "source_provider": "akshare_eastmoney_dividend",
                },
                frame_names=["dividends"],
                retrieved_at=retrieved_at,
                refresh_cache=refresh_source_cache,
                fetch=lambda symbol=symbol: {
                    "dividends": action_client.fetch_dividends(symbol=symbol)
                },
                legacy_snapshot=None,
                clock=clock,
            )
            current_lanes = {
                "cninfo_disclosures": cninfo_future.result(),
                "sina_statements": sina_future.result(),
                "eastmoney_dividends": action_future.result(),
            }
            for lane_name, result in current_lanes.items():
                lane_results[lane_name][symbol] = result

            cninfo = current_lanes["cninfo_disclosures"]
            sina = current_lanes["sina_statements"]
            fundamental_modes[symbol] = _fundamental_mode(cninfo, sina)
            if cninfo.error or sina.error:
                failures = [
                    f"{name}: {result.error}"
                    for name, result in (
                        ("cninfo_disclosures", cninfo),
                        ("sina_statements", sina),
                    )
                    if result.error
                ]
                fundamentals[symbol] = SymbolPopulation(
                    symbol,
                    "provider_missing",
                    [],
                    ["akshare_sina_financial_report_cninfo_time"],
                    "; ".join(failures),
                )
            else:
                try:
                    if cninfo.frames is None or sina.frames is None:
                        raise ValueError("successful fundamental lanes require frames")
                    source_retrieved_at = _latest_retrieved_at(
                        cninfo.retrieved_at,
                        sina.retrieved_at,
                    )
                    disclosures = cninfo_period_disclosures(cninfo.frames["disclosures"])
                    events = []
                    for statement in STATEMENTS:
                        events.extend(
                            sina_statement_to_events(
                                sina.frames[STATEMENT_CACHE_NAMES[statement]],
                                disclosures=disclosures,
                                symbol=symbol,
                                exchange=exchange,
                                statement=statement,
                                field_map=field_map,
                                retrieved_at=source_retrieved_at,
                            )
                        )
                    unique = {event.event_id: event for event in events}
                    ordered = sorted(unique.values(), key=lambda event: event.event_id)
                    fundamentals[symbol] = SymbolPopulation(
                        symbol,
                        "ready" if ordered else "partial",
                        ordered,
                        ["akshare_sina_financial_report_cninfo_time"],
                    )
                except Exception as exc:
                    fundamental_modes[symbol] = "source_transform_failed"
                    fundamentals[symbol] = SymbolPopulation(
                        symbol,
                        "provider_missing",
                        [],
                        ["akshare_sina_financial_report_cninfo_time"],
                        _error(exc),
                    )

            action = current_lanes["eastmoney_dividends"]
            action_modes[symbol] = action.mode
            if action.error:
                actions[symbol] = SymbolPopulation(
                    symbol,
                    "provider_missing",
                    [],
                    ["akshare_eastmoney_dividend"],
                    action.error,
                )
            else:
                try:
                    if action.frames is None or action.retrieved_at is None:
                        raise ValueError("successful dividend lane requires frames")
                    events = eastmoney_dividend_to_events(
                        action.frames["dividends"],
                        symbol=symbol,
                        exchange=exchange,
                        retrieved_at=action.retrieved_at,
                    )
                    actions[symbol] = SymbolPopulation(
                        symbol,
                        "ready" if events else "no_event_observed",
                        events,
                        ["akshare_eastmoney_dividend"],
                    )
                except Exception as exc:
                    action_modes[symbol] = "source_transform_failed"
                    actions[symbol] = SymbolPopulation(
                        symbol,
                        "provider_missing",
                        [],
                        ["akshare_eastmoney_dividend"],
                        _error(exc),
                    )

            _emit_progress(
                progress,
                symbol=symbol,
                symbol_index=symbol_index,
                symbol_count=len(selected_symbols),
                duration_ms=_duration_ms(symbol_started_at, clock),
                lanes=current_lanes,
                fundamental_status=fundamentals[symbol].status,
                action_status=actions[symbol].status,
            )

    source_reuse = {
        "schema_version": "2.0",
        "identity_policy": "market_symbol_exchange_start_exact_cutoff_provider",
        "expected_symbol_count": len(selected_symbols),
        "execution": {
            "symbol_order": "selected_pool_order",
            "cross_symbol_concurrency": 1,
            "provider_lane_count": 3,
            "max_concurrency_per_provider": 1,
            "elapsed_ms": _duration_ms(run_started_at, clock),
        },
        "fundamentals": _aggregate_summary(fundamental_modes),
        "corporate_actions": _aggregate_summary(action_modes),
        "provider_lanes": {
            name: _lane_summary(lane_results[name]) for name in _LANE_ORDER
        },
        "cached_retrieved_at_is_preserved": True,
        "research_only": True,
        "trade_ready": False,
    }
    return CnEventSourcePopulation(
        fundamentals=fundamentals,
        corporate_actions=actions,
        source_reuse=source_reuse,
    )
