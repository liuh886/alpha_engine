"""Build an isolated selected-pool provider through a requested market cutoff.

The canonical source directory is never overwritten. Normal operation reuses
validated history, refreshes only missing/invalid/out-of-date symbols, and
merges newly fetched observations into that governed history. ``--full-refresh``
remains the explicit expensive path that rebuilds every required symbol.

A transient fetch failure may retain an already-validated canonical source as
explicitly stale evidence. Missing/invalid canonical sources and provider
identity/normalization failures still fail closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.build_market_providers import DEFAULT_FIELDS, build_market_provider
from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.adapters.base import MarketDataAdapter
from src.data.adapters.efinance_adapter import EFinanceAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.router import MarketDataRouter, RouterResponse
from src.data.symbol_identity import (
    selected_pool_provider_identity_contract,
    validate_selected_pool_provider_identity,
)
from src.data.validation.schema import validate_market_data
from src.research.selected_pool_guard import resolve_selected_pool

REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
LIFECYCLE_REGISTRY = Path(
    "configs/data_quality/symbol_identity_and_lifecycle_v1.yaml"
)
BENCHMARKS = {"cn": "000300", "us": "QQQ"}
CANONICAL_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
)
INCOMPLETE_CUTOFF_RETRY_SECONDS = 2.0
# Providers that report raw (unadjusted) prices and withhold volume/amount.
# They may only extend an existing governed seed: the overlap is checked
# exactly against the governed rows and only strictly newer sessions are
# appended. A full replacement would silently swap the adjusted basis.
_RAW_PRICE_TAIL_FALLBACK_PROVIDERS = frozenset({"akshare_sina_fund"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_pool(path: Path, market: str) -> list[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("selected-pool contract must be a mapping")
    if str(payload.get("market", "")).lower() != market:
        raise ValueError("selected-pool market does not match request")
    symbols = [str(item).strip().upper() for item in payload.get("symbols", [])]
    expected = int(payload.get("candidate_count", 0))
    if expected <= 0 or len(symbols) != expected or len(set(symbols)) != expected:
        raise ValueError("selected-pool identity is not exact")
    return symbols


def _terminal_listing_contracts(
    project_root: Path, market: str
) -> dict[str, dict[str, Any]]:
    """Load exact terminal-listing boundaries for one market."""

    path = project_root / LIFECYCLE_REGISTRY
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    terminal = ((payload or {}).get("rules") or {}).get("terminal_listings")
    if not isinstance(terminal, dict):
        raise ValueError("terminal-listing lifecycle registry is invalid")
    contracts: dict[str, dict[str, Any]] = {}
    for raw_symbol, raw_contract in terminal.items():
        if not isinstance(raw_contract, dict):
            raise ValueError("terminal-listing contract must be a mapping")
        if str(raw_contract.get("market") or "").lower() != market:
            continue
        symbol = str(raw_symbol).strip().upper()
        terminal_date = str(raw_contract.get("terminal_date") or "")
        try:
            pd.Timestamp(terminal_date)
        except ValueError as exc:
            raise ValueError(f"invalid terminal date for {symbol}") from exc
        if (
            raw_contract.get("active_universe_after_terminal_date_allowed") is not False
            or raw_contract.get("historical_rows_retained") is not True
        ):
            raise ValueError(f"terminal lifecycle boundary is incomplete: {symbol}")
        contracts[symbol] = dict(raw_contract)
    return contracts


def _retained_terminal_history(
    source_path: Path,
    *,
    symbol: str,
    start: str,
    contract: dict[str, Any],
) -> pd.DataFrame:
    """Return governed history closed exactly at the final trading session."""

    if not source_path.is_file():
        raise ValueError(f"governed terminal history is missing: {symbol}")
    frame = _normalize_frame(pd.read_csv(source_path), symbol=symbol)
    start_at = pd.Timestamp(start).normalize()
    terminal_at = pd.Timestamp(str(contract["terminal_date"])).normalize()
    if frame.iloc[0]["date"] > start_at + pd.Timedelta(days=10):
        raise ValueError(
            f"governed terminal history does not reach requested start: {symbol}"
        )
    frame = _slice_requested_window(
        frame,
        symbol=symbol,
        start=start,
        cutoff=terminal_at.date().isoformat(),
    )
    if frame.empty or frame.iloc[-1]["date"] != terminal_at:
        raise ValueError(
            f"governed terminal history does not close at terminal date: {symbol}"
        )
    return frame


def _terminal_history_source(
    project_root: Path,
    default_source: Path,
    *,
    symbol: str,
    contract: dict[str, Any],
) -> Path:
    """Resolve and verify the immutable history source declared by lifecycle."""

    raw_path = str(contract.get("governed_history_path") or "").strip()
    if not raw_path:
        return default_source
    root = project_root.resolve()
    source = (root / raw_path).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"governed terminal history escapes repository: {symbol}") from exc
    expected = str(contract.get("governed_history_sha256") or "").strip().lower()
    if len(expected) != 64 or not source.is_file() or _sha256(source) != expected:
        raise ValueError(f"governed terminal history identity mismatch: {symbol}")
    return source


def _normalize_auxiliary_symbols(
    values: list[str] | tuple[str, ...] | None,
    *,
    candidates: list[str],
    benchmark: str,
) -> list[str]:
    auxiliary = [
        str(value).strip().upper()
        for value in (values or [])
        if str(value).strip()
    ]
    if len(auxiliary) != len(set(auxiliary)):
        raise ValueError("auxiliary symbols must be unique")
    reserved = set(candidates) | {benchmark}
    return [symbol for symbol in auxiliary if symbol not in reserved]


def _normalize_session_dates(values: pd.Series, *, symbol: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    try:
        return parsed.dt.tz_localize(None).dt.normalize()
    except (AttributeError, TypeError) as exc:
        raise ValueError(f"{symbol} contains incompatible date values") from exc


def _normalize_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    missing = sorted(set(CANONICAL_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"{symbol} is missing columns: {missing}")
    result = frame.loc[:, list(CANONICAL_COLUMNS)].copy()
    result["date"] = _normalize_session_dates(result["date"], symbol=symbol)
    for column in CANONICAL_COLUMNS[1:]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result["date"].isna().any():
        raise ValueError(f"{symbol} contains unparseable dates")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any():
        raise ValueError(f"{symbol} contains duplicate dates")
    ok, _, errors = validate_market_data(result, symbol)
    if not ok:
        raise ValueError(f"{symbol} schema validation failed: {errors}")
    return result


def _requested_window_bounds(
    start: str, cutoff: str
) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        start_at = pd.Timestamp(start).tz_localize(None).normalize()
        cutoff_at = pd.Timestamp(cutoff).tz_localize(None).normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"requested date window is invalid: {start} through {cutoff}"
        ) from exc
    if pd.isna(start_at) or pd.isna(cutoff_at) or start_at > cutoff_at:
        raise ValueError(
            f"requested date window is invalid: {start} through {cutoff}"
        )
    return start_at, cutoff_at


def _slice_requested_window(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    cutoff: str,
) -> pd.DataFrame:
    start_at, cutoff_at = _requested_window_bounds(start, cutoff)
    result = frame.loc[frame["date"].between(start_at, cutoff_at)].copy()
    if result.empty:
        raise ValueError(
            f"{symbol} has no governed history from {start} through {cutoff}"
        )
    return result


def _audit_source(path: Path, symbol: str, *, market: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {"symbol": symbol, "status": "missing", "errors": ["missing"]}
    try:
        frame = _normalize_frame(pd.read_csv(path), symbol=symbol)
        if market == "us":
            # A current last_date does not establish consistent historical
            # adjusted OHLCV after a provider's split restatement.
            from src.research.us87_price_integrity import audit_dataframe
            events = audit_dataframe(frame, symbol=symbol)
            if events:
                raise ValueError(
                    "BLOCKED_PRICE_SCALE_INTEGRITY: "
                    + ", ".join(f'{e["date"]} ({e["close_ratio"]}x)' for e in events[:6]))
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "invalid",
            "errors": [f"{type(exc).__name__}: {exc}"],
            "sha256": _sha256(path),
        }
    return {
        "symbol": symbol,
        "status": "ready",
        "rows": int(len(frame)),
        "first_date": frame["date"].min().date().isoformat(),
        "last_date": frame["date"].max().date().isoformat(),
        "sha256": _sha256(path),
    }


def _default_router(market: str, evidence_root: Path | None = None) -> MarketDataRouter:
    adapters: list[MarketDataAdapter]
    policy: dict[str, list[str]]
    if market == "cn":
        # Yahoo is quarantined last for CN, matching the hardened v2 chain:
        # domestic providers first, Yahoo only as a last resort so a vendor
        # outage surfaces as stale evidence instead of silently winning.
        adapters = [
            EFinanceAdapter(),
            AkShareAdapter(),
            BaoStockAdapter(),
            YFinanceAdapter(),
        ]
        policy = {"cn": ["efinance", "akshare", "baostock", "yfinance"]}
    elif market == "us":
        adapters = [YFinanceAdapter(evidence_root=evidence_root)]
        policy = {"us": ["yfinance"]}
    else:
        raise ValueError(f"unsupported market: {market}")
    return MarketDataRouter(adapters=adapters, policy=policy)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, lineterminator="\n")


def _attempts(response: RouterResponse) -> list[dict[str, Any]]:
    return [attempt.to_dict() for attempt in response.attempts]


def _identity_contract(market: str, symbol: str) -> dict[str, str] | None:
    return selected_pool_provider_identity_contract(market, symbol)


def _validate_provider_identity(
    *, market: str, symbol: str, provider_symbol: str | None
) -> dict[str, str] | None:
    return validate_selected_pool_provider_identity(
        market=market,
        symbol=symbol,
        provider_symbol=provider_symbol,
    )


def _fetch_with_retries(
    router: MarketDataRouter,
    *,
    symbol: str,
    market: str,
    start: str,
    cutoff: str,
    max_rounds: int,
) -> tuple[RouterResponse, list[dict[str, Any]]]:
    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")
    combined_attempts: list[dict[str, Any]] = []
    last_response = RouterResponse(result=None, attempts=[])
    for round_number in range(1, max_rounds + 1):
        response = router.fetch_daily_bars(
            symbol=symbol,
            market=market,
            start=start,
            end=cutoff,
            validate=True,
            prefer_complete_end=True,
        )
        last_response = response
        _, cutoff_at = _requested_window_bounds(start, cutoff)
        observed_last_date: str | None = None
        cutoff_complete = False
        if response.ok and response.result is not None:
            raw_dates = response.result.df.get("date")
            try:
                dates = (
                    _normalize_session_dates(raw_dates, symbol=symbol).dropna()
                    if isinstance(raw_dates, pd.Series)
                    else pd.Series(dtype="datetime64[ns]")
                )
            except ValueError:
                dates = pd.Series(dtype="datetime64[ns]")
            if not dates.empty:
                dates = dates.loc[dates <= cutoff_at]
            if not dates.empty:
                observed_at = pd.Timestamp(dates.max())
                observed_last_date = observed_at.date().isoformat()
                cutoff_complete = observed_at == cutoff_at

        for attempt in _attempts(response):
            row = {"round": round_number, **attempt}
            if response.ok and attempt.get("ok") is True:
                row.update(
                    {
                        "requested_cutoff": cutoff_at.date().isoformat(),
                        "observed_last_date": observed_last_date,
                        "cutoff_complete": cutoff_complete,
                    }
                )
                if not cutoff_complete:
                    row["ok"] = False
                    row["error"] = (
                        "provider response ended before requested cutoff"
                    )
            combined_attempts.append(row)

        if response.ok and cutoff_complete:
            return response, combined_attempts
        if round_number < max_rounds:
            delay = (
                INCOMPLETE_CUTOFF_RETRY_SECONDS * round_number
                if response.ok
                else float(round_number * 2)
            )
            time.sleep(delay)
    return last_response, combined_attempts


def _source_needs_refresh(audit: dict[str, Any], *, cutoff: str) -> bool:
    if audit.get("status") != "ready":
        return True
    return pd.Timestamp(str(audit["last_date"])) < pd.Timestamp(cutoff)


def _copy_requested_window(
    *,
    source_path: Path,
    output_path: Path,
    symbol: str,
    start: str,
    cutoff: str,
) -> pd.DataFrame:
    frame = _normalize_frame(pd.read_csv(source_path), symbol=symbol)
    frame = _slice_requested_window(
        frame,
        symbol=symbol,
        start=start,
        cutoff=cutoff,
    )
    _write_csv(output_path, frame)
    return frame


def _retain_stale_source(
    *,
    source_path: Path,
    output_path: Path,
    symbol: str,
    market: str,
    start: str,
    cutoff: str,
    audit: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if audit.get("status") != "ready":
        return None
    frame = _copy_requested_window(
        source_path=source_path,
        output_path=output_path,
        symbol=symbol,
        start=start,
        cutoff=cutoff,
    )
    return {
        "symbol": symbol,
        "action": "retained_stale_source",
        "stale_reason": "provider_fetch_failed",
        "source_sha256": audit["sha256"],
        "output_sha256": _sha256(output_path),
        "rows": int(len(frame)),
        "first_date": frame["date"].min().date().isoformat(),
        "last_date": frame["date"].max().date().isoformat(),
        "attempts": attempts,
        "identity_contract": _identity_contract(market, symbol),
    }


def _log_stale_diagnostics(
    *,
    records: list[dict[str, Any]],
    cutoff: str,
    audits: dict[str, Any] | None = None,
) -> None:
    """Print one compact line per stale/failed symbol for CI triage.

    Print-only: the manifest schema is unchanged. Each line names the seed
    last date, the requested cutoff, every provider tried with its round, and
    the distinct error classes, so the next 515180-style outage is diagnosable
    from the workflow log without downloading artifacts.
    """

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("action") not in {"retained_stale_source", "fetch_failed"}:
            continue
        attempts = record.get("attempts")
        if not isinstance(attempts, list):
            attempts = []
        providers = sorted(
            {
                str(attempt.get("provider"))
                for attempt in attempts
                if isinstance(attempt, dict) and attempt.get("provider")
            }
        )
        rounds = sorted(
            {
                attempt.get("round")
                for attempt in attempts
                if isinstance(attempt, dict) and attempt.get("round") is not None
            }
        )
        errors = sorted(
            {
                str(attempt.get("error") or "")[:160]
                for attempt in attempts
                if isinstance(attempt, dict) and not attempt.get("ok")
            }
        )
        seed_last_date: object = None
        if isinstance(audits, dict):
            audit = audits.get(str(record.get("symbol"))) or {}
            if isinstance(audit, dict):
                seed_last_date = audit.get("last_date")
        print(
            "[stale-diagnostic] "
            f"symbol={record.get('symbol')} action={record.get('action')} "
            f"seed_last_date={seed_last_date} requested_cutoff={cutoff} "
            f"providers_tried={','.join(providers) or 'none'} "
            f"rounds={','.join(str(round_number) for round_number in rounds) or 'none'} "
            f"error_classes={errors[:3] or ['none']}",
            flush=True,
        )


def _identity_contracts_for(
    market: str,
    candidates: list[str],
    benchmark: str,
    auxiliaries: list[str],
) -> dict[str, dict[str, str]]:
    return {
        symbol: contract
        for symbol in [*candidates, benchmark, *auxiliaries]
        if (contract := _identity_contract(market, symbol)) is not None
    }


def _optional_auxiliary_gap(
    failure: dict[str, Any],
    *,
    market: str,
    default_reason: str = "unavailable",
) -> dict[str, Any]:
    """Project one optional-reference failure into a scoped, reasoned gap."""

    symbol = str(failure.get("symbol") or "").strip().upper()
    attempts = failure.get("attempts")
    rows = [row for row in attempts if isinstance(row, dict)] if isinstance(attempts, list) else []
    attempted_providers = sorted(
        {
            str(row.get("provider")).strip().lower()
            for row in rows
            if str(row.get("provider") or "").strip()
        }
    )
    errors = [
        str(row.get("error") or "").strip()
        for row in rows
        if row.get("ok") is not True and str(row.get("error") or "").strip()
    ]
    reason = str(failure.get("error") or "").strip()
    if not reason and errors:
        reason = errors[-1]
    if not reason:
        reason = str(failure.get("action") or default_reason).strip() or default_reason
    return {
        "symbol": symbol,
        "role": "optional_reference",
        "market": market,
        "status": "missing",
        "reason": reason[:500],
        "attempted_providers": attempted_providers,
    }


def _base_manifest(
    *,
    market: str,
    pool_id: str,
    candidates: list[str],
    benchmark: str,
    auxiliary_symbols: list[str],
    start: str,
    cutoff: str,
    targets: list[str],
    before: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    full_refresh: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "1.2",
        "evidence_type": "selected_pool_price_refresh_v1",
        "market": market,
        "pool_id": pool_id,
        "candidate_count": len(candidates),
        "candidate_symbols": candidates,
        "benchmark": benchmark,
        "auxiliary_symbols": auxiliary_symbols,
        "start": start,
        "cutoff": cutoff,
        "refresh_mode": "full" if full_refresh else "repair_only",
        "target_count": len(targets),
        "targets": targets,
        "before": before,
        "records": records,
        "optional_auxiliary_gaps": [],
        "identity_contracts": _identity_contracts_for(
            market, candidates, benchmark, auxiliary_symbols
        ),
        "research_only": True,
        "trade_ready": False,
    }


def refresh_selected_pool_prices(
    *,
    root: str | Path,
    market: str,
    source_csv_dir: str | Path,
    output_root: str | Path,
    start: str,
    cutoff: str,
    router: MarketDataRouter | None = None,
    max_rounds: int = 2,
    full_refresh: bool = False,
    auxiliary_symbols: list[str] | tuple[str, ...] | None = None,
    optional_auxiliary_symbols: tuple[str, ...] = (),
    full_history_fallback_symbols: tuple[str, ...] = (),
    allow_partial: bool = False,
    provider_evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Build one isolated provider through ``cutoff`` for the selected pool.

    With ``allow_partial=True`` symbols that fail without a ready-source
    fallback are quarantined (excluded from the provider, named in the
    manifest) instead of melting the whole market build. A quarantined
    benchmark is never degradable: without the market clock the provider
    cannot watermark any strategy, so it still fails closed.

    ``optional_auxiliary_symbols`` names declared optional reference
    auxiliaries (for example a non-executable index or volatility reference).
    A missing, stale or quarantined optional reference is recorded as a scoped
    gap and never blocks publication of the candidate pool, benchmark or
    required formal holdings.
    """

    _requested_window_bounds(start, cutoff)
    project_root = Path(root).resolve()
    market_key = str(market).lower()
    binding = resolve_selected_pool(
        market_key,
        registry_path=project_root / REGISTRY,
        authoritative=True,
        require_data_ready=False,
    )
    candidates = _load_pool(binding.pool_spec, market_key)
    terminal_contracts = _terminal_listing_contracts(project_root, market_key)
    benchmark = BENCHMARKS[market_key]
    auxiliaries = _normalize_auxiliary_symbols(
        auxiliary_symbols,
        candidates=candidates,
        benchmark=benchmark,
    )
    optional_scope = {
        str(symbol).strip().upper()
        for symbol in optional_auxiliary_symbols
        if str(symbol).strip()
    }
    unscoped_optional = optional_scope - set(auxiliaries)
    if unscoped_optional:
        raise ValueError(
            "optional references must be requested auxiliaries: "
            + ", ".join(sorted(unscoped_optional))
        )
    if not set(full_history_fallback_symbols).issubset(auxiliaries):
        raise ValueError("full-history fallback must be scoped to requested auxiliaries")
    required = [*candidates, benchmark, *auxiliaries]

    source_dir = Path(source_csv_dir).resolve()
    destination = Path(output_root).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"output root is not empty: {destination}")

    before = {
        symbol: _audit_source(source_dir / f"{symbol}.csv", symbol, market=market_key)
        for symbol in required
    }
    targets = (
        list(required)
        if full_refresh
        else [
            symbol
            for symbol in required
            if _source_needs_refresh(before[symbol], cutoff=cutoff)
        ]
    )
    target_set = set(targets)
    if provider_evidence_root is not None and (router is not None or market_key != "us"):
        raise ValueError("exact response capture requires the canonical US router")
    data_router = router or _default_router(market_key, provider_evidence_root)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.rmdir()

    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-staging-", dir=destination.parent
    ) as temporary:
        stage = Path(temporary) / "payload"
        csv_out = stage / "data" / "csv_source"
        csv_out.mkdir(parents=True)
        records: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for symbol in required:
            source_path = source_dir / f"{symbol}.csv"
            output_path = csv_out / f"{symbol}.csv"
            audit = before[symbol]
            terminal_contract = terminal_contracts.get(symbol)

            if (
                terminal_contract is not None
                and pd.Timestamp(cutoff)
                > pd.Timestamp(str(terminal_contract["terminal_date"]))
            ):
                try:
                    terminal_source = _terminal_history_source(
                        project_root,
                        source_path,
                        symbol=symbol,
                        contract=terminal_contract,
                    )
                    frame = _retained_terminal_history(
                        terminal_source,
                        symbol=symbol,
                        start=start,
                        contract=terminal_contract,
                    )
                    _write_csv(output_path, frame)
                except Exception as exc:
                    failure = {
                        "symbol": symbol,
                        "action": "terminal_history_failed",
                        "previous_status": audit["status"],
                        "error": f"{type(exc).__name__}: {exc}",
                        "attempts": [],
                    }
                    records.append(failure)
                    failures.append(failure)
                    continue
                records.append(
                    {
                        "symbol": symbol,
                        "action": "retained_governed_terminal_history",
                        "source_path": str(
                            terminal_contract.get("governed_history_path")
                            or terminal_source.name
                        ),
                        "source_sha256": _sha256(terminal_source),
                        "output_sha256": _sha256(output_path),
                        "rows": int(len(frame)),
                        "first_date": frame["date"].min().date().isoformat(),
                        "last_date": frame["date"].max().date().isoformat(),
                        "terminal_lifecycle": terminal_contract,
                        "attempts": [],
                    }
                )
                continue

            if symbol not in target_set:
                frame = _copy_requested_window(
                    source_path=source_path,
                    output_path=output_path,
                    symbol=symbol,
                    start=start,
                    cutoff=cutoff,
                )
                records.append(
                    {
                        "symbol": symbol,
                        "action": "copied_verified_source",
                        "source_sha256": audit["sha256"],
                        "output_sha256": _sha256(output_path),
                        "rows": int(len(frame)),
                        "first_date": frame["date"].min().date().isoformat(),
                        "last_date": frame["date"].max().date().isoformat(),
                        "attempts": [],
                        "identity_contract": _identity_contract(market_key, symbol),
                    }
                )
                continue

            incremental = not full_refresh and audit.get("status") == "ready"
            fetch_start = start
            if incremental:
                fetch_start = max(
                    pd.Timestamp(start), pd.Timestamp(str(audit["last_date"]))
                ).date().isoformat()

            response, attempt_rows = _fetch_with_retries(
                data_router,
                symbol=symbol,
                market=market_key,
                start=fetch_start,
                cutoff=cutoff,
                max_rounds=max_rounds,
            )
            full_history_fallback = (
                symbol in full_history_fallback_symbols
                and response.ok and response.result is not None
                and response.result.provider == "yfinance"
            )
            if full_history_fallback:
                # Formal auxiliary Yahoo admission requires a complete source
                # vintage. Never label a seed+tail merge as a full refresh.
                if fetch_start != start:
                    response, full_attempts = _fetch_with_retries(
                        data_router, symbol=symbol, market=market_key,
                        start=start, cutoff=cutoff, max_rounds=max_rounds,
                    )
                    attempt_rows.extend(full_attempts)
                incremental = False
                fetch_start = start
            if not response.ok or response.result is None:
                retained = _retain_stale_source(
                    source_path=source_path,
                    output_path=output_path,
                    symbol=symbol,
                    market=market_key,
                    start=start,
                    cutoff=cutoff,
                    audit=audit,
                    attempts=attempt_rows,
                )
                if retained is not None:
                    records.append(retained)
                    continue
                failure = {
                    "symbol": symbol,
                    "action": "fetch_failed",
                    "previous_status": audit["status"],
                    "attempts": attempt_rows,
                }
                records.append(failure)
                failures.append(failure)
                continue

            try:
                selected_provider = str(response.result.provider or "").strip().lower()
                raw_tail_fallback = selected_provider in _RAW_PRICE_TAIL_FALLBACK_PROVIDERS
                if raw_tail_fallback and not incremental:
                    raise ValueError(
                        f"{selected_provider} is a raw-price incremental tail fallback "
                        "and cannot replace governed adjusted history without a sealed "
                        "incremental seed"
                    )
                identity = _validate_provider_identity(
                    market=market_key,
                    symbol=symbol,
                    provider_symbol=response.result.provider_symbol,
                )
                fetched = _normalize_frame(response.result.df, symbol=symbol)
                if (incremental or full_history_fallback) and not fetched["date"].eq(pd.Timestamp(cutoff)).any():
                    retained = _retain_stale_source(
                        source_path=source_path, output_path=output_path,
                        symbol=symbol, market=market_key, start=start,
                        cutoff=cutoff, audit=audit, attempts=attempt_rows,
                    )
                    if retained is None:
                        raise ValueError("provider response does not reach the requested cutoff")
                    retained["stale_reason"] = "provider_cutoff_incomplete"
                    records.append(retained)
                    continue
                fetched = _slice_requested_window(
                    fetched,
                    symbol=symbol,
                    start=fetch_start,
                    cutoff=cutoff,
                )
                if full_history_fallback and audit.get("status") == "ready":
                    seeded = _normalize_frame(pd.read_csv(source_path), symbol=symbol)
                    seeded = seeded.loc[seeded["date"].between(pd.Timestamp(start), pd.Timestamp(cutoff))]
                    if not set(seeded["date"]).issubset(set(fetched["date"])):
                        raise ValueError("full-history fallback omits governed observation dates")
                if incremental:
                    governed = _normalize_frame(
                        pd.read_csv(source_path), symbol=symbol
                    )
                    cutoff_fallback = raw_tail_fallback or any(
                        attempt.requested_end_present is False
                        and attempt.provider != response.result.provider
                        for attempt in response.attempts
                    )
                    if cutoff_fallback:
                        old = governed.loc[governed["date"] == pd.Timestamp(fetch_start)]
                        new = fetched.loc[fetched["date"] == pd.Timestamp(fetch_start)]
                        # Exact price and adjustment factor matching is strictly required to prevent
                        # price basis drift or unannounced adjustment flips.
                        fields = ("open", "high", "low", "close", "factor")
                        vol_scale = 1.0
                        if len(old) != 1 or len(new) != 1:
                            detail = f"governed_rows={len(old)}, fetched_rows={len(new)}"
                        else:
                            mismatched = [field for field in fields if not math.isclose(
                                float(old.iloc[0][field]), float(new.iloc[0][field]),
                                rel_tol=1e-6, abs_tol=1e-8,
                            )]
                            # Volume governance: check if volume matches or represents a known unit scale
                            # (e.g. shares vs lots: ratio 100 or 0.01). If volume ratio cannot be confirmed,
                            # block volume-dependent research rather than silently accepting/overwriting.
                            if "volume" in old.columns and "volume" in new.columns:
                                old_vol = float(old.iloc[0]["volume"])
                                new_vol = float(new.iloc[0]["volume"])
                                if old_vol > 0 and new_vol > 0:
                                    vol_ratio = new_vol / old_vol
                                    if math.isclose(vol_ratio, 1.0, rel_tol=1e-3):
                                        vol_scale = 1.0
                                    elif math.isclose(vol_ratio, 100.0, rel_tol=1e-3):
                                        vol_scale = 0.01  # fallback in shares, governed in lots
                                    elif math.isclose(vol_ratio, 0.01, rel_tol=1e-3):
                                        vol_scale = 100.0  # fallback in lots, governed in shares
                                    else:
                                        mismatched.append("volume")
                            detail = f"mismatched_fields={','.join(mismatched)}" if mismatched else ""
                        if detail:
                            raise ValueError(
                                "cutoff fallback differs from governed overlap price, "
                                "adjustment or volume basis: "
                                f"provider={response.result.provider}; overlap={fetch_start}; {detail}"
                            )
                        if vol_scale != 1.0 and "volume" in fetched.columns:
                            fetched["volume"] = fetched["volume"] * vol_scale
                        # Immutability barrier: fallback vendor across different providers must NEVER
                        # overwrite governed historical records or alter units in the overlap window.
                        # Only append forward extension dates strictly beyond the governed cutoff.
                        governed_cutoff_ts = governed["date"].max()
                        extension = fetched.loc[fetched["date"] > governed_cutoff_ts].copy()
                        frame = pd.concat([governed, extension], ignore_index=True)
                    else:
                        frame = pd.concat([governed, fetched], ignore_index=True)
                        frame = frame.drop_duplicates(subset=["date"], keep="last")
                    frame = _normalize_frame(frame, symbol=symbol)
                else:
                    frame = fetched
                frame = _slice_requested_window(
                    frame,
                    symbol=symbol,
                    start=start,
                    cutoff=cutoff,
                )
                if market_key == "us":
                    from src.research.us87_price_integrity import audit_dataframe
                    events = audit_dataframe(frame, symbol=symbol)
                    if events:
                        raise ValueError(
                            "BLOCKED_PRICE_SCALE_INTEGRITY: vendor full-history "
                            "or incremental price response remains inconsistent: "
                            + ", ".join(e["date"] for e in events[:6]))
                _write_csv(output_path, frame)
            except Exception as exc:
                failure = {
                    "symbol": symbol,
                    "action": "normalization_or_identity_failed",
                    "previous_status": audit["status"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "attempts": attempt_rows,
                }
                records.append(failure)
                failures.append(failure)
                continue

            success_record = {
                "symbol": symbol,
                "action": (
                    "fetched_full_refresh"
                    if full_refresh or full_history_fallback
                    else (
                        "fetched_incremental_update"
                        if incremental
                        else "fetched_replacement"
                    )
                ),
                "provider": response.result.provider,
                "provider_symbol": response.result.provider_symbol,
                "identity_contract": identity,
                "output_sha256": _sha256(output_path),
                "rows": int(len(frame)),
                "first_date": frame["date"].min().date().isoformat(),
                "last_date": frame["date"].max().date().isoformat(),
                "attempts": attempt_rows,
            }
            if response.result.provenance is not None:
                success_record["source_provenance"] = response.result.provenance
            records.append(success_record)

        manifest = _base_manifest(
            market=market_key,
            pool_id=binding.pool_id,
            candidates=candidates,
            benchmark=benchmark,
            auxiliary_symbols=auxiliaries,
            start=start,
            cutoff=cutoff,
            targets=targets,
            before=before,
            records=records,
            full_refresh=full_refresh,
        )
        scoped_optional_failed: set[str] = set()
        optional_gaps: list[dict[str, Any]] = []
        if failures:
            _log_stale_diagnostics(records=records, cutoff=cutoff, audits=before)
            quarantined = [str(row["symbol"]) for row in failures]
            failed_set = {str(row["symbol"]).strip().upper() for row in failures}
            optional_failed = sorted(failed_set & optional_scope)
            required_failed = sorted(failed_set - optional_scope)
            materialized = [
                symbol
                for symbol in required
                if symbol not in failed_set
                and (csv_out / f"{symbol}.csv").is_file()
            ]
            if (
                materialized
                and benchmark not in failed_set
                and optional_failed
                and not required_failed
            ):
                # Declared optional references never block publication of the
                # candidate pool, benchmark or required formal holdings. The
                # absence is recorded with its reason and no series is
                # fabricated or substituted.
                scoped_optional_failed = set(optional_failed)
                failure_by_symbol = {
                    str(row["symbol"]).strip().upper(): row for row in failures
                }
                optional_gaps = sorted(
                    (
                        _optional_auxiliary_gap(
                            failure_by_symbol[symbol],
                            market=market_key,
                        )
                        for symbol in optional_failed
                    ),
                    key=lambda gap: str(gap["symbol"]),
                )
                records = [
                    row
                    for row in records
                    if str(row.get("symbol", "")).strip().upper()
                    not in scoped_optional_failed
                ]
                auxiliaries = [
                    symbol for symbol in auxiliaries if symbol not in scoped_optional_failed
                ]
                manifest["records"] = records
                manifest["auxiliary_symbols"] = auxiliaries
                manifest["optional_auxiliary_gaps"] = optional_gaps
                manifest["identity_contracts"] = _identity_contracts_for(
                    market_key, candidates, benchmark, auxiliaries
                )
            elif (
                allow_partial
                and materialized
                and benchmark not in failed_set
            ):
                manifest.update(
                    {
                        "status": "selected_pool_price_refresh_partial",
                        "failure_count": len(failures),
                        "failed_symbols": quarantined,
                        "quarantined_symbols": sorted(quarantined),
                        "all_sources_ready": False,
                        "all_sources_current": False,
                    }
                )
            else:
                manifest.update(
                    {
                        "status": "selected_pool_price_refresh_blocked",
                        "failure_count": len(failures),
                        "failed_symbols": [row["symbol"] for row in failures],
                        "failures": failures,
                        "all_sources_ready": False,
                        "all_sources_current": False,
                    }
                )
                shutil.rmtree(stage / "data", ignore_errors=True)
                _write_json(
                    stage / "artifacts" / "selected_pool_price_refresh_manifest.json",
                    manifest,
                )
                stage.replace(destination)
                raise RuntimeError(
                    "selected-pool refresh failed for symbols: "
                    + ", ".join(str(row["symbol"]) for row in failures)
                )

        quarantined_symbols = [
            str(value)
            for value in manifest.get("quarantined_symbols", [])
            if str(value).strip()
        ]
        covered = [
            symbol
            for symbol in required
            if symbol not in set(quarantined_symbols)
            and symbol not in scoped_optional_failed
        ]
        after = {
            symbol: _audit_source(csv_out / f"{symbol}.csv", symbol, market=market_key)
            for symbol in covered
        }
        blocked = [
            symbol for symbol in covered if after[symbol]["status"] != "ready"
        ]
        if blocked:
            raise RuntimeError(
                f"isolated selected-pool build remains blocked: {blocked}; "
                + "; ".join(
                    f"{symbol}={after[symbol].get('errors')}" for symbol in blocked
                )
            )

        cutoff_ts = pd.Timestamp(cutoff)
        stale_symbols = sorted(
            symbol
            for symbol, audit in after.items()
            if pd.Timestamp(str(audit["last_date"])) < cutoff_ts
        )
        optional_stale = sorted(
            symbol for symbol in stale_symbols if symbol in optional_scope
        )
        if optional_stale:
            # An optional reference that cannot reach the cutoff is absent,
            # not stale evidence to republish. Exclude it at the provider
            # boundary and record the scoped gap.
            optional_stale_set = set(optional_stale)
            record_by_symbol = {
                str(row.get("symbol", "")).strip().upper(): row
                for row in records
                if isinstance(row, dict)
            }
            for symbol in optional_stale:
                (csv_out / f"{symbol}.csv").unlink(missing_ok=True)
                gap = _optional_auxiliary_gap(
                    record_by_symbol.get(symbol, {"symbol": symbol}),
                    market=market_key,
                    default_reason="stale_before_cutoff",
                )
                # A failed fetch that retained a stale seed is still a stale
                # series, not a provider-contract reason.
                gap["reason"] = "stale_before_cutoff"
                optional_gaps.append(gap)
            optional_gaps = sorted(optional_gaps, key=lambda gap: str(gap["symbol"]))
            records = [
                row
                for row in records
                if str(row.get("symbol", "")).strip().upper() not in optional_stale_set
            ]
            after = {
                symbol: audit
                for symbol, audit in after.items()
                if symbol not in optional_stale_set
            }
            stale_symbols = [
                symbol for symbol in stale_symbols if symbol not in optional_stale_set
            ]
            auxiliaries = [
                symbol for symbol in auxiliaries if symbol not in optional_stale_set
            ]
            manifest["records"] = records
            manifest["auxiliary_symbols"] = auxiliaries
            manifest["optional_auxiliary_gaps"] = optional_gaps
            manifest["identity_contracts"] = _identity_contracts_for(
                market_key, candidates, benchmark, auxiliaries
            )
        if stale_symbols:
            _log_stale_diagnostics(records=records, cutoff=cutoff, audits=after)

        provider_dir = stage / "data" / "providers" / market_key
        provider_manifest = build_market_provider(
            csv_dir=csv_out,
            provider_dir=provider_dir,
            market=market_key,
            include_fields=DEFAULT_FIELDS,
        )
        manifest.update(
            {
                "stale_symbols": stale_symbols,
                "after": after,
                "provider_identity_sha256": provider_manifest.get(
                    "provider_identity_sha256"
                ),
                "all_sources_current": not stale_symbols
                and not quarantined_symbols,
            }
        )
        if not quarantined_symbols:
            manifest.update(
                {
                    "status": "selected_pool_price_refresh_ready",
                    "failure_count": 0,
                    "failed_symbols": [],
                    "all_sources_ready": True,
                }
            )
        _write_json(
            stage / "artifacts" / "selected_pool_price_refresh_manifest.json",
            manifest,
        )
        stage.replace(destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument(
        "--source-csv-dir", type=Path, default=Path("data/csv_clean")
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", default="2026-06-18")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--provider-evidence-root", type=Path,
                        help="Private directory retaining exact Yahoo raw responses and normalization evidence.")
    parser.add_argument(
        "--auxiliary-symbol",
        action="append",
        default=[],
        help="Additional formal/reference security to include in the same provider.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Rebuild every candidate, benchmark, and auxiliary security.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Quarantine symbols that fail without a ready-source fallback "
            "instead of melting the whole market build. A quarantined "
            "benchmark still fails closed."
        ),
    )
    args = parser.parse_args()

    payload = refresh_selected_pool_prices(
        root=args.root,
        market=args.market,
        source_csv_dir=args.source_csv_dir,
        output_root=args.output_root,
        start=args.start,
        cutoff=args.cutoff,
        max_rounds=args.max_rounds,
        full_refresh=args.full_refresh,
        auxiliary_symbols=args.auxiliary_symbol,
        allow_partial=args.allow_partial,
        provider_evidence_root=args.provider_evidence_root,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
