"""Refresh selected-pool prices into an isolated, manifest-bound provider.

The command never overwrites the authoritative source directory. It can either
refresh only missing/invalid symbols or rebuild the complete selected pool plus
benchmark. Every provider attempt is recorded, the exact pool is validated, and
only a complete provider or diagnostics-only blocked result is published.
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
from src.data.validation.schema import validate_market_data
from src.research.selected_pool_guard import resolve_selected_pool

REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
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
IDENTITY_CONTRACTS: dict[tuple[str, str], dict[str, str]] = {
    ("us", "TIGO"): {
        "expected_provider_symbol": "TIGO",
        "expected_issuer": "Millicom International Cellular S.A.",
        "forbidden_substitute": "TYGO",
    }
}


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


def _normalize_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    missing = sorted(set(CANONICAL_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"{symbol} is missing columns: {missing}")
    result = frame.loc[:, list(CANONICAL_COLUMNS)].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
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
    return IDENTITY_CONTRACTS.get((market.lower(), symbol.upper()))


def _validate_provider_identity(
    *, market: str, symbol: str, provider_symbol: str | None
) -> dict[str, str] | None:
    contract = _identity_contract(market, symbol)
    if contract is None:
        return None
    observed = str(provider_symbol or symbol).strip().upper()
    expected = contract["expected_provider_symbol"].upper()
    forbidden = contract["forbidden_substitute"].upper()
    if observed == forbidden:
        raise ValueError(
            f"forbidden identity substitution for {symbol}: observed={observed}"
        )
    if observed != expected:
        raise ValueError(
            f"provider identity mismatch for {symbol}: "
            f"expected={expected} observed={observed}"
        )
    return contract


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
        for attempt in _attempts(response):
            combined_attempts.append({"round": round_number, **attempt})
        last_response = response
        if response.ok:
            return response, combined_attempts
        if round_number < max_rounds:
            time.sleep(float(round_number * 2))
    return last_response, combined_attempts


def _base_manifest(
    *,
    market: str,
    pool_id: str,
    candidates: list[str],
    benchmark: str,
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
        "benchmark": benchmark,
        "start": start,
        "cutoff": cutoff,
        "refresh_mode": "full" if full_refresh else "repair_only",
        "target_count": len(targets),
        "targets": targets,
        "before": before,
        "records": records,
        "identity_contracts": {
            symbol: contract
            for symbol in candidates
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
) -> dict[str, Any]:
    """Build one isolated, exact selected-pool price source and provider."""

    project_root = Path(root).resolve()
    market_key = str(market).lower()
    binding = resolve_selected_pool(
        market_key,
        registry_path=project_root / REGISTRY,
        authoritative=True,
        require_data_ready=False,
    )
    candidates = _load_pool(binding.pool_spec, market_key)
    benchmark = BENCHMARKS[market_key]
    required = [*candidates, benchmark]

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
            if before[symbol]["status"] != "ready"
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
            if symbol not in target_set:
                shutil.copy2(source_path, output_path)
                records.append(
                    {
                        "symbol": symbol,
                        "action": "copied_verified_source",
                        "source_sha256": before[symbol]["sha256"],
                        "output_sha256": _sha256(output_path),
                        "attempts": [],
                        "identity_contract": _identity_contract(
                            market_key, symbol
                        ),
                    }
                )
                continue

            response, attempt_rows = _fetch_with_retries(
                data_router,
                symbol=symbol,
                market=market_key,
                start=start,
                cutoff=cutoff,
                max_rounds=max_rounds,
            )
            if not response.ok or response.result is None:
                failure = {
                    "symbol": symbol,
                    "action": "fetch_failed",
                    "previous_status": before[symbol]["status"],
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
                frame = _normalize_frame(response.result.df, symbol=symbol)
                frame = frame.loc[frame["date"] <= pd.Timestamp(cutoff)].copy()
                if frame.empty:
                    raise ValueError("provider returned no rows through cutoff")
                _write_csv(output_path, frame)
            except Exception as exc:
                failure = {
                    "symbol": symbol,
                    "action": "normalization_or_identity_failed",
                    "previous_status": before[symbol]["status"],
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
                        else "fetched_replacement"
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
        manifest.update(
            {
                "status": "selected_pool_price_refresh_ready",
                "failure_count": 0,
                "failed_symbols": [],
                "after": after,
                "provider_identity_sha256": provider_manifest.get(
                    "provider_identity_sha256"
                ),
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
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Fetch every candidate and benchmark instead of only blocked files.",
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
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
