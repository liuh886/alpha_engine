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
INCOMPLETE_CUTOFF_RETRY_SECONDS = 30.0


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


def _audit_source(path: Path, symbol: str) -> dict[str, Any]:
    if not path.is_file():
        return {"symbol": symbol, "status": "missing", "errors": ["missing"]}
    try:
        frame = _normalize_frame(pd.read_csv(path), symbol=symbol)
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


def _default_router(market: str) -> MarketDataRouter:
    adapters: list[MarketDataAdapter]
    policy: dict[str, list[str]]
    if market == "cn":
        adapters = [
            YFinanceAdapter(),
            EFinanceAdapter(),
            AkShareAdapter(),
            BaoStockAdapter(),
        ]
        policy = {"cn": ["yfinance", "efinance", "akshare", "baostock"]}
    elif market == "us":
        adapters = [YFinanceAdapter()]
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
                observed_at = pd.Timestamp(dates.max())
                observed_last_date = observed_at.date().isoformat()
                cutoff_complete = observed_at >= cutoff_at

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
        "identity_contracts": {
            symbol: contract
            for symbol in [*candidates, benchmark, *auxiliary_symbols]
            if (contract := _identity_contract(market, symbol)) is not None
        },
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
) -> dict[str, Any]:
    """Build one isolated provider through ``cutoff`` for the selected pool."""

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
    required = [*candidates, benchmark, *auxiliaries]

    source_dir = Path(source_csv_dir).resolve()
    destination = Path(output_root).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"output root is not empty: {destination}")

    before = {
        symbol: _audit_source(source_dir / f"{symbol}.csv", symbol)
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
    data_router = router or _default_router(market_key)

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
                identity = _validate_provider_identity(
                    market=market_key,
                    symbol=symbol,
                    provider_symbol=response.result.provider_symbol,
                )
                fetched = _normalize_frame(response.result.df, symbol=symbol)
                fetched = _slice_requested_window(
                    fetched,
                    symbol=symbol,
                    start=start,
                    cutoff=cutoff,
                )
                if incremental:
                    governed = _normalize_frame(
                        pd.read_csv(source_path), symbol=symbol
                    )
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

            records.append(
                {
                    "symbol": symbol,
                    "action": (
                        "fetched_full_refresh"
                        if full_refresh
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
            )

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
        if failures:
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

        after = {
            symbol: _audit_source(csv_out / f"{symbol}.csv", symbol)
            for symbol in required
        }
        blocked = [
            symbol for symbol in required if after[symbol]["status"] != "ready"
        ]
        if blocked:
            raise RuntimeError(
                f"isolated selected-pool build remains blocked: {blocked}"
            )

        provider_dir = stage / "data" / "providers" / market_key
        provider_manifest = build_market_provider(
            csv_dir=csv_out,
            provider_dir=provider_dir,
            market=market_key,
            include_fields=DEFAULT_FIELDS,
        )
        cutoff_ts = pd.Timestamp(cutoff)
        stale_symbols = sorted(
            symbol
            for symbol, audit in after.items()
            if pd.Timestamp(str(audit["last_date"])) < cutoff_ts
        )
        manifest.update(
            {
                "status": "selected_pool_price_refresh_ready",
                "failure_count": 0,
                "failed_symbols": [],
                "stale_symbols": stale_symbols,
                "after": after,
                "provider_identity_sha256": provider_manifest.get(
                    "provider_identity_sha256"
                ),
                "all_sources_ready": True,
                "all_sources_current": not stale_symbols,
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
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
