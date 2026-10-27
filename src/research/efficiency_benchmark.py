"""Track B RI-05: Researcher Efficiency Benchmark and Metric Measurement.

Empirically measures researcher friction, code complexity, and reproducibility
comparing traditional ad-hoc research workflows vs. the governed research data slice plane.

Contract Boundaries:
- research_only=true, trade_ready=false.
- Rigorously distinguishes qualitative workflow estimates (heuristic manual steps)
  from empirically measured runtime metrics (AST statement count, tracemalloc peak memory,
  perf_counter execution time, and dynamically verified PIT lookahead interception).
"""

from __future__ import annotations

import ast
import inspect
import json
import time
import tracemalloc
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.research_slice import (
    DEFAULT_REPO_ROOT,
    DataSliceRequest,
    get_research_data_slice,
)


@dataclass(frozen=True)
class ResearchEfficiencyMetrics:
    """Quantitative measurement of researcher efficiency before vs after."""

    problem_name: str
    target_market: str
    target_pool: str
    sample_symbols: list[str]
    benchmark_symbol: str
    date_range: tuple[str, str]
    as_of_cutoff: str

    # 1. Qualitative workflow estimation (Heuristic steps clearly demarcated)
    estimated_baseline_workflow_steps: int
    estimated_optimized_workflow_steps: int
    estimated_steps_reduction_pct: float
    workflow_estimation_note: str
    workflow_steps_breakdown: dict[str, list[str]]

    # 2. Empirically measured caller source code AST statements (dynamically inspected)
    measured_baseline_ast_statements: int
    measured_optimized_ast_statements: int
    measured_ast_statement_reduction_pct: float

    # 3. Empirically verified PIT lookahead interception (via actual execution with end_date > cutoff)
    verified_baseline_intercepts_lookahead: bool
    verified_optimized_intercepts_lookahead: bool

    # 4. Empirically measured runtime performance & memory (perf_counter & tracemalloc)
    measured_baseline_execution_ms: float
    measured_optimized_execution_ms: float
    measured_baseline_peak_bytes: int
    measured_optimized_peak_bytes: int

    # 5. Mathematical equivalence & auditability verification
    data_equivalence_verified: bool
    max_absolute_difference: float
    baseline_has_cryptographic_receipt: bool
    optimized_has_cryptographic_receipt: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compute_factors_from_dataframe(
    df: pd.DataFrame,
    benchmark_symbol: str,
) -> dict[str, dict[str, float]]:
    """Compute 10-day realized volatility and return spread against benchmark."""
    factors: dict[str, dict[str, float]] = {}

    # Pivot close prices: index=time, columns=symbol
    pivoted = df.pivot(index="time", columns="symbol", values="close").sort_index()

    # Daily log returns
    log_returns = np.log(pivoted / pivoted.shift(1)).dropna()

    bench_returns = log_returns[benchmark_symbol] if benchmark_symbol in log_returns else None

    for sym in pivoted.columns:
        if sym == benchmark_symbol:
            continue
        sym_ret = log_returns[sym]
        # 10-day rolling volatility annualized (approx sqrt(252))
        vol10 = float(sym_ret.tail(10).std() * np.sqrt(252)) if len(sym_ret) >= 10 else 0.0

        # Cumulative window return
        cum_ret = float((pivoted[sym].iloc[-1] / pivoted[sym].iloc[0]) - 1.0)

        # Excess return over benchmark
        if bench_returns is not None:
            bench_cum_ret = float((pivoted[benchmark_symbol].iloc[-1] / pivoted[benchmark_symbol].iloc[0]) - 1.0)
            excess_ret = cum_ret - bench_cum_ret
        else:
            excess_ret = 0.0

        factors[sym] = {
            "realized_vol10": round(vol10, 6),
            "cum_return": round(cum_ret, 6),
            "excess_return_vs_bench": round(excess_ret, 6),
        }

    return factors


def run_ad_hoc_baseline(
    repo_root: Path,
    market: str,
    symbols: list[str],
    benchmark_symbol: str,
    start_date: str,
    end_date: str,
    as_of_cutoff: str,
) -> tuple[dict[str, dict[str, float]], float]:
    """Execute baseline research workflow: ad-hoc file parsing and data assembly.

    Simulates the traditional script written by a researcher:
    1. Parse individual symbol JSON files.
    2. Extract and filter bars.
    3. Check fields manually.
    4. Assemble DataFrame.
    5. Compute factors.
    """
    t0 = time.perf_counter()

    evidence_root = repo_root / "data/research/market_evidence" / market / "symbols"
    all_symbols = list(set(symbols + [benchmark_symbol]))

    records: list[dict[str, Any]] = []
    for sym in all_symbols:
        fpath = evidence_root / f"{sym}.json"
        if not fpath.is_file():
            continue
        data = json.loads(fpath.read_text(encoding="utf-8"))
        bars = data.get("bars", [])
        for b in bars:
            t = str(b.get("time", ""))
            if start_date <= t <= end_date:
                records.append({
                    "symbol": sym,
                    "time": t,
                    "close": float(b["close"]),
                })

    df = pd.DataFrame(records)
    if df.empty:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {}, elapsed_ms

    factors = _compute_factors_from_dataframe(df, benchmark_symbol)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return factors, elapsed_ms


def run_slice_optimized(
    repo_root: Path,
    market: str,
    pool_id: str,
    symbols: list[str],
    benchmark_symbol: str,
    start_date: str,
    end_date: str,
    as_of_cutoff: str,
) -> tuple[dict[str, dict[str, float]], dict[str, Any], float]:
    """Execute modern research workflow: governed data slice extraction.

    Researcher writes declarative DataSliceRequest and consumes verified DataFrame.
    """
    t0 = time.perf_counter()

    all_symbols = list(set(symbols + [benchmark_symbol]))
    request = DataSliceRequest(
        market=market,
        pool_id=pool_id,
        symbols=all_symbols,
        start_date=start_date,
        end_date=end_date,
        as_of_cutoff=as_of_cutoff,
        price_mode="anchored_adjusted",
        required_fields=["open", "high", "low", "close", "volume"],
    )

    result = get_research_data_slice(request, root=repo_root)
    if not result.is_ready or result.data is None:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {}, result.receipt, elapsed_ms

    factors = _compute_factors_from_dataframe(result.data, benchmark_symbol)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return factors, result.receipt, elapsed_ms


def _count_ast_statements(func: Any) -> int:
    """Dynamically count AST statement nodes within a function body."""
    src = inspect.getsource(func)
    tree = ast.parse(src)
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt))


def measure_efficiency_metrics(
    repo_root: Path | None = None,
) -> ResearchEfficiencyMetrics:
    """Measure empirical efficiency metrics on US tech cross-section."""
    root = (repo_root or DEFAULT_REPO_ROOT).resolve()

    market = "us"
    pool_id = "us_selected_equities_v2"
    sample_symbols = ["AAPL", "GOOGL", "MSFT", "NVDA"]
    benchmark_symbol = "QQQ"
    start_date = "2026-08-01"
    end_date = "2026-08-31"
    as_of_cutoff = "2026-09-04"

    # 1. Measure baseline execution and peak memory
    tracemalloc.start()
    baseline_factors, baseline_ms = run_ad_hoc_baseline(
        root, market, sample_symbols, benchmark_symbol, start_date, end_date, as_of_cutoff
    )
    _, baseline_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 2. Measure optimized execution and peak memory
    tracemalloc.start()
    optimized_factors, receipt, optimized_ms = run_slice_optimized(
        root, market, pool_id, sample_symbols, benchmark_symbol, start_date, end_date, as_of_cutoff
    )
    _, optimized_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 3. Verify mathematical equivalence
    max_diff = 0.0
    for sym in sample_symbols:
        for metric in ["realized_vol10", "cum_return", "excess_return_vs_bench"]:
            diff = abs(baseline_factors[sym][metric] - optimized_factors[sym][metric])
            if diff > max_diff:
                max_diff = diff

    # 4. Dynamically count AST statements
    baseline_ast_stmts = _count_ast_statements(run_ad_hoc_baseline)
    optimized_ast_stmts = _count_ast_statements(run_slice_optimized)
    ast_reduction_pct = (
        ((baseline_ast_stmts - optimized_ast_stmts) / baseline_ast_stmts) * 100.0
        if baseline_ast_stmts > 0
        else 0.0
    )

    # 5. Dynamically verify PIT lookahead interception via actual challenge execution
    lookahead_end = "2026-09-10"  # After cutoff 2026-09-04
    lookahead_base_factors, _ = run_ad_hoc_baseline(
        root, market, sample_symbols, benchmark_symbol, start_date, lookahead_end, as_of_cutoff
    )
    # Baseline silently extracts data past cutoff -> interception is False
    verified_baseline_intercepts_lookahead = bool(len(lookahead_base_factors) == 0)

    # Optimized detects end_date > cutoff -> returns blocked with structured blocker code
    _, lookahead_receipt, _ = run_slice_optimized(
        root, market, pool_id, sample_symbols, benchmark_symbol, start_date, lookahead_end, as_of_cutoff
    )
    verified_optimized_intercepts_lookahead = bool(
        lookahead_receipt.get("status") == "blocked"
        and any(
            b.get("code") == "PIT_VIOLATION_LOOKAHEAD_CUTOFF"
            for b in lookahead_receipt.get("blocked_reasons", [])
        )
    )

    # 6. Qualitative workflow estimation (Transparently reported as heuristic human steps)
    estimated_baseline_steps = 7
    estimated_optimized_steps = 2
    steps_reduction = (
        ((estimated_baseline_steps - estimated_optimized_steps) / estimated_baseline_steps) * 100.0
    )

    steps_breakdown = {
        "baseline_workflow_steps": [
            "1. Manually identify data source location and directory layout",
            "2. Read and parse individual JSON/CSV files per symbol into memory",
            "3. Manually filter date range and align observation calendar",
            "4. Manually check if any corporate action or announcement date violates cutoff",
            "5. Manually verify required fields exist across all symbols",
            "6. Convert raw dictionary records to pandas DataFrame",
            "7. Compute factor vectors and relative benchmark returns",
        ],
        "optimized_workflow_steps": [
            "1. Declare DataSliceRequest specification with market, pool, dates and cutoff",
            "2. Consume clean DataFrame directly and compute factor vectors",
        ],
    }

    return ResearchEfficiencyMetrics(
        problem_name="US Tech Cross-Section Low-Volatility Excess Return",
        target_market=market,
        target_pool=pool_id,
        sample_symbols=sample_symbols,
        benchmark_symbol=benchmark_symbol,
        date_range=(start_date, end_date),
        as_of_cutoff=as_of_cutoff,
        estimated_baseline_workflow_steps=estimated_baseline_steps,
        estimated_optimized_workflow_steps=estimated_optimized_steps,
        estimated_steps_reduction_pct=round(steps_reduction, 2),
        workflow_estimation_note=(
            "Heuristic workflow steps represent human-level task steps required from "
            "formulating the hypothesis to computing factors; clearly separated from "
            "empirical runtime measurements."
        ),
        workflow_steps_breakdown=steps_breakdown,
        measured_baseline_ast_statements=baseline_ast_stmts,
        measured_optimized_ast_statements=optimized_ast_stmts,
        measured_ast_statement_reduction_pct=round(ast_reduction_pct, 2),
        verified_baseline_intercepts_lookahead=verified_baseline_intercepts_lookahead,
        verified_optimized_intercepts_lookahead=verified_optimized_intercepts_lookahead,
        measured_baseline_execution_ms=round(baseline_ms, 2),
        measured_optimized_execution_ms=round(optimized_ms, 2),
        measured_baseline_peak_bytes=baseline_peak_bytes,
        measured_optimized_peak_bytes=optimized_peak_bytes,
        data_equivalence_verified=bool(max_diff < 1e-5),
        max_absolute_difference=round(max_diff, 8),
        baseline_has_cryptographic_receipt=False,
        optimized_has_cryptographic_receipt=bool(receipt.get("data_hash")),
    )
