"""Multi-market data-readiness helpers for US and CN 10D research."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.research.universe_robustness import filter_universe_by_coverage, load_symbol_date_coverage


@dataclass(frozen=True)
class MarketReadinessSpec:
    """One market-level readiness request."""

    market: str
    symbols: tuple[str, ...]
    benchmark: str
    train_start: str
    test_end: str
    min_symbols: int

    def __post_init__(self) -> None:
        if not self.market:
            raise ValueError("market must be non-empty")
        if not self.symbols:
            raise ValueError("symbols must be non-empty")
        if self.min_symbols < 2:
            raise ValueError("min_symbols must be at least 2")
        if self.min_symbols > len(self.symbols):
            raise ValueError("min_symbols cannot exceed the number of requested symbols")

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "symbols": list(self.symbols),
            "benchmark": self.benchmark,
            "train_start": self.train_start,
            "test_end": self.test_end,
            "min_symbols": self.min_symbols,
        }


@dataclass(frozen=True)
class NormalizedSymbol:
    """A raw symbol and its selected market-specific normalized representation."""

    original_symbol: str
    normalized_symbol: str
    candidates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "original_symbol": self.original_symbol,
            "normalized_symbol": self.normalized_symbol,
            "candidates": list(self.candidates),
        }


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def load_market_watchlist(market: str, *, watchlist_path: str | Path = "configs/watchlist.yaml") -> list[str]:
    """Load raw market symbols from watchlist YAML without silently dropping numeric-looking CN codes."""

    try:
        import yaml

        path = Path(watchlist_path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get(market, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _cn_exchange_for_code(code: str) -> str | None:
    if code.startswith(("0", "1", "2", "3")):
        return "SZ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return None


def cn_symbol_candidates(raw_symbol: object) -> tuple[str, ...]:
    """Return explicit CN symbol-format candidates while preserving six-digit code semantics."""

    raw = str(raw_symbol).strip().upper()
    if not raw:
        return tuple()
    cleaned = raw
    for prefix in ("SZ", "SH"):
        if cleaned.startswith(prefix) and cleaned[len(prefix) :].isdigit():
            cleaned = cleaned[len(prefix) :]
    for suffix in (".SZ", ".SH"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    if cleaned.isdigit():
        code = cleaned.zfill(6)[-6:]
    else:
        code = cleaned
    exchange = _cn_exchange_for_code(code)
    candidates = [code]
    if exchange is not None:
        candidates.extend([f"{code}.{exchange}", f"{exchange}{code}"])
        qlib_prefix = "sh" if exchange == "SH" else "sz"
        candidates.append(f"{qlib_prefix}.{code}")
    return tuple(_dedupe_keep_order(candidates))


def normalize_market_symbol(
    market: str,
    raw_symbol: object,
    *,
    available_symbols: set[str] | None = None,
) -> NormalizedSymbol:
    """Normalize one symbol for a market, selecting a real available format when known."""

    original = str(raw_symbol).strip()
    if market == "cn":
        candidates = cn_symbol_candidates(raw_symbol)
    else:
        candidates = (original.upper(),)
    if not candidates:
        raise ValueError("cannot normalize empty symbol")
    normalized = candidates[0]
    if available_symbols:
        available_upper = {item.upper(): item for item in available_symbols}
        for candidate in candidates:
            if candidate.upper() in available_upper:
                normalized = available_upper[candidate.upper()]
                break
    return NormalizedSymbol(original_symbol=original, normalized_symbol=normalized, candidates=candidates)


def normalize_market_symbols(
    market: str,
    symbols: list[object],
    *,
    available_symbols: set[str] | None = None,
) -> list[NormalizedSymbol]:
    """Normalize and dedupe market symbols while preserving raw-to-normalized mapping."""

    rows: list[NormalizedSymbol] = []
    seen: set[str] = set()
    for raw in symbols:
        normalized = normalize_market_symbol(market, raw, available_symbols=available_symbols)
        if normalized.normalized_symbol not in seen:
            rows.append(normalized)
            seen.add(normalized.normalized_symbol)
    return rows


def default_market_specs(
    *,
    train_start: str = "2021-01-01",
    test_end: str = "2026-06-18",
    watchlist_path: str | Path = "configs/watchlist.yaml",
) -> list[MarketReadinessSpec]:
    """Build standard US and CN readiness specs from local watchlists."""

    us = load_market_watchlist("us", watchlist_path=watchlist_path)
    cn = load_market_watchlist("cn", watchlist_path=watchlist_path)
    us_norm = [row.normalized_symbol for row in normalize_market_symbols("us", us)]
    cn_norm = [row.normalized_symbol for row in normalize_market_symbols("cn", cn)]
    specs: list[MarketReadinessSpec] = []
    if us_norm:
        specs.append(
            MarketReadinessSpec(
                market="us",
                symbols=tuple(us_norm),
                benchmark="QQQ",
                train_start=train_start,
                test_end=test_end,
                min_symbols=min(50, max(8, len(us_norm))),
            )
        )
    if cn_norm:
        specs.append(
            MarketReadinessSpec(
                market="cn",
                symbols=tuple(cn_norm),
                benchmark="000300",
                train_start=train_start,
                test_end=test_end,
                min_symbols=min(50, max(20, len(cn_norm))),
            )
        )
    return specs


def check_market_data_coverage(
    spec: MarketReadinessSpec,
    *,
    available_symbols: set[str] | None = None,
    date_coverage_data: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a fail-closed readiness report for one market."""

    normalized_rows = normalize_market_symbols(spec.market, list(spec.symbols), available_symbols=available_symbols)
    normalized_symbols = tuple(row.normalized_symbol for row in normalized_rows)
    if date_coverage_data is None:
        date_coverage_data = load_symbol_date_coverage(normalized_symbols, spec.train_start, spec.test_end)
    coverage = filter_universe_by_coverage(
        normalized_symbols,
        available_symbols=available_symbols,
        min_symbols=spec.min_symbols,
        date_range=(spec.train_start, spec.test_end),
        date_coverage_data=date_coverage_data,
    )
    coverage.update(
        {
            "market": spec.market,
            "benchmark": spec.benchmark,
            "train_start": spec.train_start,
            "test_end": spec.test_end,
            "min_symbols": spec.min_symbols,
            "normalization": [row.to_dict() for row in normalized_rows],
        }
    )
    if coverage.get("skipped") and not coverage.get("skip_reason"):
        coverage["skip_reason"] = f"{spec.market} skipped because retained symbols are below min_symbols"
    return coverage


def summarize_multi_market_readiness(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarize readiness across markets without manufacturing model conclusions."""

    market_rows = []
    for market, report in reports.items():
        market_rows.append(
            {
                "market": market,
                "requested": len(report.get("requested_symbols", [])),
                "retained": len(report.get("retained_symbols", [])),
                "coverage_ratio": report.get("coverage_ratio", 0.0),
                "sufficient": bool(report.get("sufficient")),
                "skipped": bool(report.get("skipped")),
                "skip_reason": report.get("skip_reason"),
            }
        )
    return {
        "schema_version": "1.0",
        "n_markets": len(reports),
        "ready_markets": [row["market"] for row in market_rows if row["sufficient"] and not row["skipped"]],
        "skipped_markets": [row["market"] for row in market_rows if row["skipped"]],
        "markets": market_rows,
    }


def render_readiness_markdown(reports: dict[str, dict[str, Any]], summary: dict[str, Any]) -> str:
    """Render a compact multi-market readiness report."""

    lines = [
        "# AlphaEngine Multi-Market Data Readiness",
        "",
        f"Ready markets: `{summary.get('ready_markets', [])}`",
        f"Skipped markets: `{summary.get('skipped_markets', [])}`",
        "",
        "| Market | Requested | Retained | Coverage ratio | Status | Skip reason |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in summary.get("markets", []):
        status = "ready" if row["sufficient"] and not row["skipped"] else "skipped"
        lines.append(
            f"| {row['market']} | {row['requested']} | {row['retained']} | "
            f"{float(row['coverage_ratio']):.3f} | {status} | {row.get('skip_reason') or ''} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "Coverage is fail-closed. A skipped market produces no model evidence.",
            "CN symbols are normalized explicitly and leading zeroes are preserved.",
            "",
        ]
    )
    for market, report in reports.items():
        lines.extend(
            [
                f"## {market.upper()} details",
                "",
                f"- Benchmark: `{report.get('benchmark')}`",
                f"- Train start: `{report.get('train_start')}`",
                f"- Test end: `{report.get('test_end')}`",
                f"- Requested symbols: `{len(report.get('requested_symbols', []))}`",
                f"- Retained symbols: `{len(report.get('retained_symbols', []))}`",
                f"- Skipped: `{bool(report.get('skipped'))}`",
                f"- Skip reason: `{report.get('skip_reason')}`",
                "",
            ]
        )
    return "\n".join(lines)
