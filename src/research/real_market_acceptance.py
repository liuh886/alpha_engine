"""Fail-closed acceptance checks for real-market research data.

This module does not download data, train a model, or infer that a provider is real
from good-looking metrics. It verifies the declared research universe, local CSV
source, and Qlib provider metadata before factor research is allowed to proceed.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.multi_market_readiness import (
    cn_symbol_candidates,
    load_market_watchlist,
    normalize_market_symbol,
)
from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.spec_bound_execution import (
    build_declared_execution_contract,
    contract_sha256,
)

ACCEPTANCE_SCHEMA_VERSION = "1.1"
_REQUIRED_UNIVERSE_METADATA = (
    "universe_id",
    "membership_mode",
    "membership_as_of",
    "asset_type",
    "survivorship_bias",
)
_REQUIRED_CSV_COLUMNS = ("date", "open", "high", "low", "close", "volume")
_OHLC_COLUMNS = ("open", "high", "low", "close")
_MAX_VIOLATION_EXAMPLES = 20


@dataclass(frozen=True)
class AcceptanceCheck:
    """One auditable acceptance result."""

    name: str
    status: str
    message: str
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in {"pass", "warn", "fail"}:
            raise ValueError("acceptance status must be pass, warn, or fail")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_source(spec: ResearchParadigmSpec, root: Path, source: str) -> Path:
    spec_dir = Path(spec.spec_path).parent if spec.spec_path else root
    for candidate in (spec_dir / source, root / source):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"source not found: {source}")


def _load_raw_universe(spec: ResearchParadigmSpec, root: Path) -> tuple[Path, list[Any]]:
    path = _resolve_source(spec, root, str(spec.universe["source"]))
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("universe source must be a YAML mapping")
    raw = payload.get(spec.market)
    if not isinstance(raw, list):
        raise ValueError(f"universe source must contain a list at key '{spec.market}'")
    return path, raw


def _canonical_symbol(market: str, symbol: object) -> str:
    return normalize_market_symbol(market, symbol).normalized_symbol


def _parse_calendar(path: Path) -> list[pd.Timestamp]:
    values: list[pd.Timestamp] = []
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = pd.to_datetime(line, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"invalid calendar date: {line}")
        values.append(pd.Timestamp(parsed).normalize())
    if not values:
        raise ValueError("calendar is empty")
    if values != sorted(set(values)):
        raise ValueError("calendar dates must be unique and strictly increasing")
    return values


def _parse_instruments(path: Path) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    rows: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(f"invalid instrument row: {line}")
        symbol = parts[0].strip()
        start = pd.to_datetime(parts[1].strip(), errors="coerce")
        end = pd.to_datetime(parts[2].strip(), errors="coerce")
        if not symbol or pd.isna(start) or pd.isna(end):
            raise ValueError(f"invalid instrument row: {line}")
        if symbol in rows:
            raise ValueError(f"duplicate provider instrument: {symbol}")
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        if start_ts > end_ts:
            raise ValueError(f"instrument start is after end: {symbol}")
        rows[symbol] = (start_ts, end_ts)
    if not rows:
        raise ValueError("instrument file is empty")
    return rows


def _available_match(market: str, symbol: object, available: set[str]) -> str | None:
    normalized = normalize_market_symbol(market, symbol, available_symbols=available)
    available_upper = {item.upper(): item for item in available}
    for candidate in normalized.candidates:
        if candidate.upper() in available_upper:
            return available_upper[candidate.upper()]
    return None


def _csv_candidates(market: str, symbol: str) -> list[str]:
    candidates = list(cn_symbol_candidates(symbol)) if market == "cn" else [symbol.upper()]
    candidates.extend([symbol, symbol.upper()])
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            result.append(candidate)
            seen.add(candidate)
    return result


def _find_csv(csv_dir: Path, market: str, symbol: str) -> Path | None:
    for candidate in _csv_candidates(market, symbol):
        path = csv_dir / f"{candidate}.csv"
        if path.is_file():
            return path
    return None


def _finite(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.map(math.isfinite)


def _iso_date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).strftime("%Y-%m-%d")


def _violation_record(
    *,
    row_index: int,
    date: Any,
    violation_type: str,
    numeric_row: pd.Series,
    absolute_magnitude: float,
) -> dict[str, Any]:
    scale = max(
        *(abs(float(numeric_row[column])) for column in _OHLC_COLUMNS),
        1e-12,
    )
    return {
        "row_index": int(row_index),
        "date": _iso_date(date),
        "type": violation_type,
        "open": float(numeric_row["open"]),
        "high": float(numeric_row["high"]),
        "low": float(numeric_row["low"]),
        "close": float(numeric_row["close"]),
        "absolute_magnitude": float(absolute_magnitude),
        "relative_magnitude": float(absolute_magnitude / scale),
    }


def _ohlc_order_evidence(
    dates: pd.Series,
    numeric: pd.DataFrame,
) -> dict[str, Any]:
    """Return row-level OHLC-order evidence without repairing source values."""

    violations: list[dict[str, Any]] = []
    invalid_rows: set[int] = set()
    comparisons = (
        ("high_below_open", "high", "open"),
        ("high_below_low", "high", "low"),
        ("high_below_close", "high", "close"),
        ("low_above_open", "open", "low"),
        ("low_above_close", "close", "low"),
    )

    for position, (_, row) in enumerate(numeric.iterrows()):
        if not all(math.isfinite(float(row[column])) for column in _OHLC_COLUMNS):
            continue
        for violation_type, upper_column, lower_column in comparisons:
            upper = float(row[upper_column])
            lower = float(row[lower_column])
            if upper >= lower:
                continue
            invalid_rows.add(position)
            violations.append(
                _violation_record(
                    row_index=position,
                    date=dates.iloc[position] if position < len(dates) else None,
                    violation_type=violation_type,
                    numeric_row=row,
                    absolute_magnitude=lower - upper,
                )
            )

    violations.sort(key=lambda item: (int(item["row_index"]), str(item["type"])))
    max_violation = (
        max(
            violations,
            key=lambda item: (
                float(item["absolute_magnitude"]),
                float(item["relative_magnitude"]),
            ),
        )
        if violations
        else None
    )
    return {
        "invalid_row_count": len(invalid_rows),
        "violation_count": len(violations),
        "examples": violations[:_MAX_VIOLATION_EXAMPLES],
        "examples_truncated": len(violations) > _MAX_VIOLATION_EXAMPLES,
        "max_violation": max_violation,
    }


def _inspect_csv(path: Path) -> dict[str, Any]:
    frame = pd.read_csv(path)
    missing_columns = [column for column in _REQUIRED_CSV_COLUMNS if column not in frame.columns]
    if missing_columns:
        return {"ok": False, "reason": "missing_columns", "missing_columns": missing_columns}
    if frame.empty:
        return {"ok": False, "reason": "empty_csv"}

    dates = pd.to_datetime(frame["date"], errors="coerce")
    invalid_dates = int(dates.isna().sum())
    duplicate_dates = int(dates.duplicated().sum())
    monotonic = bool(dates.is_monotonic_increasing)

    finite_failures: dict[str, int] = {}
    for column in ("open", "high", "low", "close", "volume"):
        finite_failures[column] = int((~_finite(frame[column])).sum())

    numeric = frame.loc[:, ["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    nonpositive_ohlc = int((numeric[list(_OHLC_COLUMNS)] <= 0).any(axis=1).sum())
    negative_volume = int((numeric["volume"] < 0).sum())
    ohlc_evidence = _ohlc_order_evidence(dates, numeric)
    invalid_ohlc_order = int(ohlc_evidence["invalid_row_count"])

    ok = not any(
        (
            invalid_dates,
            duplicate_dates,
            not monotonic,
            sum(finite_failures.values()),
            nonpositive_ohlc,
            negative_volume,
            invalid_ohlc_order,
        )
    )
    return {
        "ok": ok,
        "rows": int(len(frame)),
        "first_date": None if dates.dropna().empty else dates.min().strftime("%Y-%m-%d"),
        "last_date": None if dates.dropna().empty else dates.max().strftime("%Y-%m-%d"),
        "invalid_dates": invalid_dates,
        "duplicate_dates": duplicate_dates,
        "dates_monotonic": monotonic,
        "nonfinite_values": finite_failures,
        "nonpositive_ohlc_rows": nonpositive_ohlc,
        "negative_volume_rows": negative_volume,
        "invalid_ohlc_order_rows": invalid_ohlc_order,
        "ohlc_order_evidence": ohlc_evidence,
    }


def _calendar_coverage_evidence(
    calendar: list[pd.Timestamp],
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    *,
    boundary_gap_days: int,
) -> dict[str, Any]:
    """Evaluate requested date boundaries against effective provider sessions."""

    gap = pd.Timedelta(days=int(boundary_gap_days))
    if not calendar:
        return {
            "ok": False,
            "first_day": None,
            "last_day": None,
            "effective_start_session": None,
            "effective_end_session": None,
            "start_boundary_gap_days": None,
            "end_boundary_gap_days": None,
            "boundary_gap_days": int(boundary_gap_days),
        }

    first = calendar[0]
    last = calendar[-1]
    start_sessions = [session for session in calendar if session >= requested_start]
    end_sessions = [session for session in calendar if session <= requested_end]
    effective_start = start_sessions[0] if start_sessions else None
    effective_end = end_sessions[-1] if end_sessions else None
    start_gap_days = max(0, int((first - requested_start).days))
    end_gap_days = max(0, int((requested_end - last).days))
    ok = first <= requested_start + gap and last >= requested_end - gap

    return {
        "ok": bool(ok),
        "first_day": first.strftime("%Y-%m-%d"),
        "last_day": last.strftime("%Y-%m-%d"),
        "effective_start_session": (
            None if effective_start is None else effective_start.strftime("%Y-%m-%d")
        ),
        "effective_end_session": (
            None if effective_end is None else effective_end.strftime("%Y-%m-%d")
        ),
        "start_boundary_gap_days": start_gap_days,
        "end_boundary_gap_days": end_gap_days,
        "boundary_gap_days": int(boundary_gap_days),
    }


def _check(name: str, passed: bool, message: str, **details: Any) -> AcceptanceCheck:
    return AcceptanceCheck(
        name=name,
        status="pass" if passed else "fail",
        message=message,
        details=details,
    )


def _warning(name: str, message: str, **details: Any) -> AcceptanceCheck:
    return AcceptanceCheck(name=name, status="warn", message=message, details=details)


def evaluate_real_market_acceptance(
    spec: ResearchParadigmSpec,
    *,
    root: str | Path = ".",
    provider_dir: str | Path | None = None,
    csv_dir: str | Path | None = None,
    boundary_gap_days: int = 14,
    minimum_csv_rows: int = 252,
) -> dict[str, Any]:
    """Evaluate whether local data are acceptable for real-market factor research."""

    root_path = Path(root).resolve()
    provider_path = Path(provider_dir).resolve() if provider_dir else root_path / "data" / "watchlist"
    csv_path = Path(csv_dir).resolve() if csv_dir else root_path / "data" / "csv_source"
    checks: list[AcceptanceCheck] = []

    source_path, raw_symbols = _load_raw_universe(spec, root_path)
    metadata_missing = [key for key in _REQUIRED_UNIVERSE_METADATA if key not in spec.universe]
    checks.append(
        _check(
            "universe_metadata",
            not metadata_missing,
            "Research universe has explicit identity and survivorship metadata"
            if not metadata_missing
            else "Research universe identity metadata is incomplete",
            missing_fields=metadata_missing,
        )
    )

    non_string_rows = [index for index, value in enumerate(raw_symbols) if not isinstance(value, str)]
    checks.append(
        _check(
            "source_symbol_types",
            not non_string_rows,
            "All source symbols are explicit YAML strings"
            if not non_string_rows
            else "Numeric YAML symbols can lose leading zeroes",
            non_string_indices=non_string_rows[:50],
            non_string_count=len(non_string_rows),
        )
    )

    loaded = load_market_watchlist(spec.market, watchlist_path=source_path)
    canonical = [_canonical_symbol(spec.market, item) for item in loaded]
    duplicates = sorted({symbol for symbol in canonical if canonical.count(symbol) > 1})
    checks.append(
        _check(
            "canonical_symbol_identity",
            not duplicates and len(canonical) == len(raw_symbols),
            "Universe symbols are unique after market normalization"
            if not duplicates and len(canonical) == len(raw_symbols)
            else "Universe has duplicate or dropped identities after normalization",
            requested_count=len(raw_symbols),
            canonical_count=len(canonical),
            duplicates=duplicates,
        )
    )

    benchmark = _canonical_symbol(spec.market, spec.benchmark)
    checks.append(
        _check(
            "benchmark_exclusion",
            benchmark not in canonical,
            "Benchmark is reference-only and excluded from candidate ranking"
            if benchmark not in canonical
            else "Benchmark is present in the candidate universe",
            benchmark=benchmark,
        )
    )

    fixture_markers = (
        sorted(str(path.relative_to(provider_path)) for path in provider_path.rglob("fixture_manifest.json"))
        if provider_path.is_dir()
        else []
    )
    checks.append(
        _check(
            "real_provider_scope",
            provider_path.is_dir() and not fixture_markers,
            "Provider exists and has no synthetic/test fixture marker"
            if provider_path.is_dir() and not fixture_markers
            else "Provider is missing or marked synthetic/test-only",
            provider_dir=str(provider_path),
            fixture_markers=fixture_markers,
        )
    )

    calendar: list[pd.Timestamp] = []
    calendar_error: str | None = None
    calendar_file = provider_path / "calendars" / "day.txt"
    try:
        calendar = _parse_calendar(calendar_file)
    except Exception as exc:  # noqa: BLE001 - evidence must capture malformed local data
        calendar_error = str(exc)
    requested_start = pd.Timestamp(str(spec.walk_forward["requested_train_start"]))
    requested_end = pd.Timestamp(str(spec.walk_forward["test_end"]))
    calendar_evidence = _calendar_coverage_evidence(
        calendar,
        requested_start,
        requested_end,
        boundary_gap_days=boundary_gap_days,
    )
    calendar_ok = calendar_error is None and bool(calendar_evidence["ok"])
    checks.append(
        _check(
            "calendar_coverage",
            calendar_ok,
            "Provider calendar covers the declared interval using effective market sessions"
            if calendar_ok
            else "Provider calendar does not cover the declared research interval",
            calendar_file=str(calendar_file),
            requested_start=str(requested_start.date()),
            requested_end=str(requested_end.date()),
            error=calendar_error,
            **{key: value for key, value in calendar_evidence.items() if key != "ok"},
        )
    )

    instrument_rows: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    instrument_error: str | None = None
    instrument_file = provider_path / "instruments" / f"{spec.market}.txt"
    try:
        instrument_rows = _parse_instruments(instrument_file)
    except Exception as exc:  # noqa: BLE001
        instrument_error = str(exc)

    available = set(instrument_rows)
    covered: list[str] = []
    unavailable: list[str] = []
    boundary_failures: list[dict[str, str]] = []
    gap = pd.Timedelta(days=int(boundary_gap_days))
    for symbol in canonical:
        match = _available_match(spec.market, symbol, available)
        if match is None:
            unavailable.append(symbol)
            continue
        first, last = instrument_rows[match]
        if first > requested_start + gap or last < requested_end - gap:
            boundary_failures.append(
                {
                    "symbol": symbol,
                    "provider_symbol": match,
                    "first": first.strftime("%Y-%m-%d"),
                    "last": last.strftime("%Y-%m-%d"),
                }
            )
            continue
        covered.append(match)

    minimum_symbols = int(spec.universe["min_symbols"])
    coverage_ok = not instrument_error and len(covered) >= minimum_symbols
    checks.append(
        _check(
            "universe_provider_coverage",
            coverage_ok,
            "Provider contains enough fully covered research symbols"
            if coverage_ok
            else "Provider does not contain enough fully covered research symbols",
            instrument_file=str(instrument_file),
            requested=len(canonical),
            covered=len(covered),
            minimum_symbols=minimum_symbols,
            unavailable=unavailable[:50],
            boundary_failures=boundary_failures[:50],
            error=instrument_error,
        )
    )

    benchmark_match = _available_match(spec.market, benchmark, available)
    benchmark_ok = False
    benchmark_details: dict[str, Any] = {"benchmark": benchmark}
    if benchmark_match is not None:
        first, last = instrument_rows[benchmark_match]
        benchmark_ok = first <= requested_start + gap and last >= requested_end - gap
        benchmark_details.update(
            {
                "provider_symbol": benchmark_match,
                "first": first.strftime("%Y-%m-%d"),
                "last": last.strftime("%Y-%m-%d"),
            }
        )
    checks.append(
        _check(
            "benchmark_provider_coverage",
            benchmark_ok,
            "Reference benchmark is available across the declared interval"
            if benchmark_ok
            else "Reference benchmark is missing or lacks full coverage",
            **benchmark_details,
        )
    )

    csv_symbols = list(dict.fromkeys([*covered, *([benchmark_match] if benchmark_match else [])]))
    csv_results: dict[str, Any] = {}
    missing_csv: list[str] = []
    invalid_csv: list[str] = []
    short_csv: list[str] = []
    for symbol in csv_symbols:
        path = _find_csv(csv_path, spec.market, symbol)
        if path is None:
            missing_csv.append(symbol)
            continue
        try:
            result = _inspect_csv(path)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "reason": "parse_error", "error": str(exc)}
        result["path"] = str(path)
        csv_results[symbol] = result
        if not result.get("ok"):
            invalid_csv.append(symbol)
        if int(result.get("rows", 0)) < int(minimum_csv_rows):
            short_csv.append(symbol)

    csv_ok = bool(csv_symbols) and not missing_csv and not invalid_csv and not short_csv
    checks.append(
        _check(
            "source_csv_integrity",
            csv_ok,
            "All retained symbols and benchmark have valid, non-fabricated OHLCV CSV history"
            if csv_ok
            else "CSV source is missing, malformed, too short, or contains invalid OHLCV values",
            csv_dir=str(csv_path),
            inspected=len(csv_results),
            minimum_rows=minimum_csv_rows,
            missing=missing_csv[:50],
            invalid=invalid_csv[:50],
            too_short=short_csv[:50],
            results=csv_results,
        )
    )

    if spec.universe.get("survivorship_bias") is True:
        checks.append(
            _warning(
                "survivorship_bias",
                "Static current-membership universe is acceptable for exploratory research but not an unbiased historical estimate",
                membership_mode=spec.universe.get("membership_mode"),
                membership_as_of=spec.universe.get("membership_as_of"),
            )
        )

    failures = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    contract = build_declared_execution_contract(spec)
    return {
        "schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "accepted": not failures,
        "summary": {
            "passed": sum(check.status == "pass" for check in checks),
            "warnings": len(warnings),
            "failed": len(failures),
        },
        "inputs": {
            "spec_path": spec.spec_path,
            "universe_source": str(source_path),
            "provider_dir": str(provider_path),
            "csv_dir": str(csv_path),
            "boundary_gap_days": int(boundary_gap_days),
            "universe_source_sha256": contract.get("universe", {}).get("source_sha256"),
            "declared_contract_sha256": contract_sha256(contract),
        },
        "checks": [check.to_dict() for check in checks],
    }


def write_real_market_acceptance_report(report: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output


def run_real_market_acceptance(
    spec_path: str | Path,
    *,
    root: str | Path = ".",
    provider_dir: str | Path | None = None,
    csv_dir: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_research_paradigm_spec(spec_path)
    report = evaluate_real_market_acceptance(
        spec,
        root=root,
        provider_dir=provider_dir,
        csv_dir=csv_dir,
    )
    if output_path is None:
        output_path = (
            Path(root)
            / "artifacts"
            / "research_runs"
            / spec.experiment_id
            / "real_market_acceptance.json"
        )
    write_real_market_acceptance_report(report, output_path)
    report["output_path"] = str(Path(output_path).resolve())
    return report
