"""Build a manifest-bound adjusted OHLCV snapshot for the frozen US pool."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from src.data.adapters.base import FetchRequest, FetchResult
from src.data.adapters.yfinance_adapter import YFinanceAdapter

NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_POOL = Path("configs/pools/us_small_pool_v1.yaml")
DEFAULT_START = "2024-01-01"
POST_CLOSE_TIME = time(18, 0)
MAX_STALE_CALENDAR_DAYS = 5


class DailyBarsAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult: ...


@dataclass(frozen=True)
class PoolSymbol:
    canonical_symbol: str
    provider_symbol: str
    role: str
    basket: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _repository_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise ValueError(f"unable to resolve repository root from {path}")


def load_pool_symbols(pool_path: str | Path = DEFAULT_POOL) -> tuple[list[PoolSymbol], Path]:
    resolved = Path(pool_path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("US pool must be a YAML mapping")
    if payload.get("pool_id") != "us_small_pool_v1" or payload.get("market") != "us":
        raise ValueError("price snapshot requires frozen us_small_pool_v1")
    symbols: list[PoolSymbol] = []
    for basket, meta in payload.get("baskets", {}).items():
        for raw_symbol in meta.get("symbols", []):
            symbol = str(raw_symbol).strip().upper()
            symbols.append(
                PoolSymbol(
                    canonical_symbol=symbol,
                    provider_symbol=symbol,
                    role="candidate",
                    basket=str(basket),
                )
            )
    for canonical, meta in payload.get("references", {}).items():
        symbols.append(
            PoolSymbol(
                canonical_symbol=str(canonical).strip().upper(),
                provider_symbol=str(meta.get("provider_symbol", canonical)).strip(),
                role=str(meta.get("role", "reference")),
                basket="reference",
            )
        )
    canonical = [row.canonical_symbol for row in symbols]
    if not symbols or len(canonical) != len(set(canonical)):
        raise ValueError("US pool symbols must be non-empty and unique")
    return symbols, resolved


def resolve_safe_request_through(
    *,
    requested_through: str | None = None,
    now_utc: datetime | None = None,
) -> date:
    """Return a safe calendar cutoff that cannot include an open US session."""

    if requested_through:
        return date.fromisoformat(requested_through)
    current_utc = now_utc or datetime.now(timezone.utc)
    if current_utc.tzinfo is None:
        current_utc = current_utc.replace(tzinfo=timezone.utc)
    local = current_utc.astimezone(NEW_YORK)
    if local.weekday() < 5 and local.time() >= POST_CLOSE_TIME:
        return local.date()
    return local.date() - timedelta(days=1)


def _normalise_result(result: FetchResult, symbol: PoolSymbol) -> pd.DataFrame:
    frame = result.df.copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            f"provider result for {symbol.canonical_symbol} missing columns: {missing}"
        )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    if frame.empty:
        raise ValueError(f"provider returned no usable rows for {symbol.canonical_symbol}")
    if frame.duplicated(["date"]).any():
        raise ValueError(f"provider returned duplicate dates for {symbol.canonical_symbol}")
    invalid_ohlc = frame[
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (frame["volume"] < 0)
    ]
    if not invalid_ohlc.empty:
        raise ValueError(f"provider returned invalid OHLCV for {symbol.canonical_symbol}")
    frame["symbol"] = symbol.canonical_symbol
    return frame[["date", "symbol", "open", "high", "low", "close", "volume"]].sort_values(
        "date"
    )


def _write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"immutable US price snapshot conflict: {path}")
        return
    path.write_bytes(content)


def build_us_pool_price_snapshot(
    *,
    output_root: str | Path,
    requested_through: str | None = None,
    start_date: str = DEFAULT_START,
    pool_path: str | Path = DEFAULT_POOL,
    adapter: DailyBarsAdapter | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Fetch every frozen symbol and write one common-latest-date snapshot."""

    target = resolve_safe_request_through(
        requested_through=requested_through,
        now_utc=now_utc,
    )
    start = date.fromisoformat(start_date)
    if start >= target:
        raise ValueError("snapshot start_date must precede requested-through date")
    symbols, resolved_pool = load_pool_symbols(pool_path)
    provider = adapter or YFinanceAdapter()
    frames: list[pd.DataFrame] = []
    coverage: list[dict[str, Any]] = []
    for symbol in symbols:
        result = provider.fetch_daily_bars(
            FetchRequest(
                symbol=symbol.provider_symbol,
                market="us",
                start=start.isoformat(),
                end=target.isoformat(),
            )
        )
        frame = _normalise_result(result, symbol)
        observed_provider_symbol = str(result.provider_symbol or symbol.provider_symbol)
        latest = frame["date"].max().date()
        first = frame["date"].min().date()
        source_identity = _canonical_hash(
            {
                "provider": result.provider,
                "canonical_symbol": symbol.canonical_symbol,
                "provider_symbol": observed_provider_symbol,
                "rows": frame.assign(date=frame["date"].dt.strftime("%Y-%m-%d")).to_dict(
                    orient="records"
                ),
            }
        )
        coverage.append(
            {
                "canonical_symbol": symbol.canonical_symbol,
                "provider_symbol": observed_provider_symbol,
                "role": symbol.role,
                "basket": symbol.basket,
                "provider": result.provider,
                "first_date": first.isoformat(),
                "latest_date": latest.isoformat(),
                "row_count": len(frame),
                "source_identity_sha256": source_identity,
            }
        )
        frames.append(frame)

    latest_dates = {row["latest_date"] for row in coverage}
    if len(latest_dates) != 1:
        details = ", ".join(
            f"{row['canonical_symbol']}={row['latest_date']}" for row in coverage
        )
        raise ValueError("US pool latest-session coverage is inconsistent: " + details)
    resolved_as_of = date.fromisoformat(next(iter(latest_dates)))
    if resolved_as_of > target:
        raise ValueError("provider returned rows beyond requested-through cutoff")
    if (target - resolved_as_of).days > MAX_STALE_CALENDAR_DAYS:
        raise ValueError(
            f"US pool snapshot is stale: target={target}, latest={resolved_as_of}"
        )
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(NEW_YORK)
    if (
        requested_through is None
        and resolved_as_of == local_now.date()
        and local_now.time() < POST_CLOSE_TIME
    ):
        raise ValueError("intraday US daily bar cannot be accepted as a complete session")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["date"].dt.date <= resolved_as_of]
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    expected = {row.canonical_symbol for row in symbols}
    latest_rows = combined[combined["date"].dt.date == resolved_as_of]
    observed_latest = set(latest_rows["symbol"])
    if observed_latest != expected:
        missing = sorted(expected - observed_latest)
        raise ValueError("latest session is missing frozen symbols: " + ", ".join(missing))

    output = Path(output_root).resolve() / resolved_as_of.isoformat()
    output.mkdir(parents=True, exist_ok=True)
    prices_path = output / "prices.csv"
    csv_frame = combined.copy()
    csv_frame["date"] = csv_frame["date"].dt.strftime("%Y-%m-%d")
    csv_bytes = csv_frame.to_csv(index=False).encode("utf-8")
    _write_immutable(prices_path, csv_bytes)

    coverage_payload = {
        "schema_version": "1.0",
        "snapshot_id": "us_small_pool_yfinance_snapshot_v1",
        "pool_id": "us_small_pool_v1",
        "requested_through": target.isoformat(),
        "resolved_as_of_date": resolved_as_of.isoformat(),
        "provider": provider.name,
        "candidate_and_reference_count": len(symbols),
        "all_latest_session_complete": True,
        "rows": coverage,
    }
    coverage_path = output / "coverage_report.json"
    coverage_bytes = json.dumps(
        coverage_payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    _write_immutable(coverage_path, coverage_bytes)

    decision = {
        "schema_version": "1.0",
        "decision": "us_pool_price_snapshot_ready",
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "provider": provider.name,
        "pool_id": "us_small_pool_v1",
        "requested_through": target.isoformat(),
        "resolved_as_of_date": resolved_as_of.isoformat(),
        "symbol_count": len(symbols),
        "row_count": len(combined),
        "prices_csv": str(prices_path),
    }
    decision_path = output / "decision.json"
    decision_bytes = json.dumps(
        decision, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    _write_immutable(decision_path, decision_bytes)

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "snapshot_id": "us_small_pool_yfinance_snapshot_v1",
        "research_only": True,
        "trade_ready": False,
        "inputs": {
            "pool_sha256": _sha256_file(resolved_pool),
            "provider": provider.name,
            "start_date": start.isoformat(),
            "requested_through": target.isoformat(),
            "source_identities": {
                row["canonical_symbol"]: row["source_identity_sha256"]
                for row in coverage
            },
        },
        "outputs": {
            "prices.csv": _sha256_file(prices_path),
            "coverage_report.json": _sha256_file(coverage_path),
            "decision.json": _sha256_file(decision_path),
        },
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    manifest_path = output / "evidence_manifest.json"
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")
    _write_immutable(manifest_path, manifest_bytes)
    return decision
