"""Parameterized research data slice reader and immutable receipt generator.

Governed under Track B (RI-03B / #1296) and ADR-0005 (PIT Information State Semantics).
Bound by AGENTS.md: research_only=true, trade_ready=false.
Provides pure functional in-memory extraction over existing verified market evidence,
enforcing strict PIT cutoff filtering without copying data into duplicate databases.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import yaml

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


class ResearchDataSliceError(Exception):
    """Raised when data slice resolution fails system integrity checks."""


@dataclass(frozen=True)
class DataSliceRequest:
    """Declared parameter specification for one research data slice."""

    market: str
    pool_id: str
    symbols: tuple[str, ...]
    start_date: str
    end_date: str
    as_of_cutoff: str
    price_mode: str = "anchored_adjusted"
    required_fields: tuple[str, ...] = ("open", "high", "low", "close", "volume")
    include_corporate_actions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "pool_id": self.pool_id,
            "symbols": list(self.symbols),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "as_of_cutoff": self.as_of_cutoff,
            "price_mode": self.price_mode,
            "required_fields": list(self.required_fields),
            "include_corporate_actions": self.include_corporate_actions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DataSliceRequest:
        raw_symbols = data.get("symbols", [])
        if isinstance(raw_symbols, str):
            symbols = tuple(s.strip() for s in raw_symbols.split(",") if s.strip())
        else:
            symbols = tuple(str(s).strip() for s in raw_symbols)

        raw_fields = data.get("required_fields", ("open", "high", "low", "close", "volume"))
        if isinstance(raw_fields, str):
            fields = tuple(f.strip() for f in raw_fields.split(",") if f.strip())
        else:
            fields = tuple(str(f).strip() for f in raw_fields)

        return cls(
            market=str(data["market"]).strip().lower(),
            pool_id=str(data["pool_id"]).strip(),
            symbols=symbols,
            start_date=str(data["start_date"]).strip(),
            end_date=str(data["end_date"]).strip(),
            as_of_cutoff=str(data["as_of_cutoff"]).strip(),
            price_mode=str(data.get("price_mode", "anchored_adjusted")).strip().lower(),
            required_fields=fields,
            include_corporate_actions=bool(data.get("include_corporate_actions", False)),
        )


@dataclass(frozen=True)
class BlockerReason:
    """Structured fail-closed reason explaining why a slice was blocked."""

    code: str
    symbol: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DataSliceResult:
    """Immutable return object containing verified data and its cryptographic receipt."""

    receipt: dict[str, Any]
    data: pd.DataFrame | None


def _validate_iso_date(val: str, field_name: str) -> None:
    try:
        date.fromisoformat(val)
    except (ValueError, TypeError) as exc:
        raise ResearchDataSliceError(f"{field_name} must be a valid ISO date YYYY-MM-DD, got '{val}'") from exc


def get_research_data_slice(
    request: DataSliceRequest,
    root: Path | None = None,
) -> DataSliceResult:
    """Extract a research data slice and generate an immutable evidence receipt.

    Pure functional execution:
    1. Validates market, pool membership and ISO date boundaries.
    2. Enforces fail-closed PIT rules (end_date <= as_of_cutoff; announced_at <= as_of_cutoff).
    3. Streams bar data from verified market evidence without whole-dataset duplication.
    4. Computes deterministic SHA256 of resulting dataset.
    5. Returns DataSliceResult with receipt and DataFrame (or None if blocked).
    """
    repo_root = (root or DEFAULT_REPO_ROOT).resolve()
    blockers: list[BlockerReason] = []

    # 1. Validate dates
    _validate_iso_date(request.start_date, "start_date")
    _validate_iso_date(request.end_date, "end_date")
    _validate_iso_date(request.as_of_cutoff, "as_of_cutoff")

    if request.start_date > request.end_date:
        blockers.append(
            BlockerReason(
                code="INVALID_DATE_RANGE",
                symbol="*",
                message=f"start_date '{request.start_date}' is after end_date '{request.end_date}'.",
            )
        )

    if request.end_date > request.as_of_cutoff:
        blockers.append(
            BlockerReason(
                code="PIT_VIOLATION_LOOKAHEAD_CUTOFF",
                symbol="*",
                message=(
                    f"Requested end_date '{request.end_date}' is after as_of_cutoff "
                    f"'{request.as_of_cutoff}'; lookahead evaluation is strictly forbidden."
                ),
            )
        )

    # 2. Validate market and pool governance
    pool_registry_path = repo_root / "configs/pools/selected_pool_registry_v1.yaml"
    if not pool_registry_path.is_file():
        raise ResearchDataSliceError(f"Pool registry missing: {pool_registry_path}")

    with pool_registry_path.open("r", encoding="utf-8") as f:
        pool_reg = yaml.safe_load(f)

    markets_cfg = pool_reg.get("markets", {})
    if request.market not in markets_cfg:
        blockers.append(
            BlockerReason(
                code="INVALID_MARKET",
                symbol="*",
                message=f"Unsupported market '{request.market}'. Allowed: {list(markets_cfg.keys())}.",
            )
        )
    else:
        market_cfg = markets_cfg[request.market]
        active_pool_id = market_cfg.get("active_pool_id", "")
        if request.pool_id != active_pool_id:
            blockers.append(
                BlockerReason(
                    code="MARKET_POOL_MISMATCH",
                    symbol="*",
                    message=(
                        f"pool_id '{request.pool_id}' is not the active pool for market "
                        f"'{request.market}' (expected '{active_pool_id}')."
                    ),
                )
            )

        pool_spec_rel = market_cfg.get("pool_spec", "")
        pool_spec_path = repo_root / pool_spec_rel
        if not pool_spec_path.is_file():
            raise ResearchDataSliceError(f"Pool spec missing: {pool_spec_path}")

        with pool_spec_path.open("r", encoding="utf-8") as f:
            pool_spec = yaml.safe_load(f)

        governed_symbols = set(pool_spec.get("symbols", []))
        for symbol in request.symbols:
            if symbol not in governed_symbols:
                blockers.append(
                    BlockerReason(
                        code="SYMBOL_NOT_IN_GOVERNED_POOL",
                        symbol=symbol,
                        message=f"Symbol '{symbol}' is not a member of governed pool '{request.pool_id}'.",
                    )
                )

    # 3. Check Corporate Actions & PIT Boundary (Bridge Checks)
    if request.market == "cn":
        bridge_path = repo_root / "data/research/source_reconciliations/cn27/price-basis-v1.json"
        if bridge_path.is_file():
            try:
                bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
                for event in bridge.get("events", []):
                    ev_sym = str(event.get("symbol", "")).strip()
                    if ev_sym in request.symbols:
                        announced_at = str(event.get("announced_at", "")).strip()
                        ex_date = str(event.get("ex_date", "")).strip()
                        if announced_at and announced_at > request.as_of_cutoff:
                            # If requesting anchored_adjusted prices or query dates reach/cross announcement
                            if (
                                request.price_mode == "anchored_adjusted"
                                or request.end_date >= announced_at
                                or (ex_date and request.end_date >= ex_date)
                            ):
                                blockers.append(
                                    BlockerReason(
                                        code="PIT_VIOLATION_FUTURE_EVENT_ANNOUNCEMENT",
                                        symbol=ev_sym,
                                        message=(
                                            f"Corporate action announced_at '{announced_at}' is after "
                                            f"as_of_cutoff '{request.as_of_cutoff}'; "
                                            "lookahead adjustment is strictly forbidden."
                                        ),
                                    )
                                )
            except json.JSONDecodeError as exc:
                raise ResearchDataSliceError(f"Corrupted price basis bridge: {bridge_path}") from exc

    # 4. Stream and filter symbol market evidence
    all_rows: list[dict[str, Any]] = []
    symbol_row_counts: dict[str, int] = {}

    evidence_root = repo_root / "data/research/market_evidence" / request.market / "symbols"

    for symbol in request.symbols:
        symbol_file = evidence_root / f"{symbol}.json"
        if not symbol_file.is_file():
            blockers.append(
                BlockerReason(
                    code="DATA_MISSING_FOR_DATE_RANGE",
                    symbol=symbol,
                    message=f"Market evidence file missing for symbol '{symbol}': {symbol_file}",
                )
            )
            continue

        try:
            symbol_data = json.loads(symbol_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ResearchDataSliceError(f"Corrupted symbol evidence file: {symbol_file}") from exc

        bars: list[dict[str, Any]] = symbol_data.get("bars", [])
        if not bars:
            blockers.append(
                BlockerReason(
                    code="DATA_MISSING_FOR_DATE_RANGE",
                    symbol=symbol,
                    message=f"No bar records found for symbol '{symbol}'.",
                )
            )
            continue

        first_date = str(bars[0].get("time", ""))
        last_date = str(bars[-1].get("time", ""))

        if request.end_date < first_date:
            blockers.append(
                BlockerReason(
                    code="SYMBOL_NOT_YET_LISTED",
                    symbol=symbol,
                    message=(
                        f"Symbol '{symbol}' first available date is '{first_date}', "
                        f"which is after requested end_date '{request.end_date}'."
                    ),
                )
            )
            continue

        if request.start_date > last_date:
            blockers.append(
                BlockerReason(
                    code="DATA_MISSING_FOR_DATE_RANGE",
                    symbol=symbol,
                    message=(
                        f"Requested start_date '{request.start_date}' is after symbol '{symbol}' "
                        f"last available date '{last_date}'."
                    ),
                )
            )
            continue

        # Filter bars in requested range [start_date, end_date]
        matched_bars = [b for b in bars if request.start_date <= str(b.get("time", "")) <= request.end_date]
        if not matched_bars:
            blockers.append(
                BlockerReason(
                    code="DATA_MISSING_FOR_DATE_RANGE",
                    symbol=symbol,
                    message=f"No trading days found in requested range for symbol '{symbol}'.",
                )
            )
            continue

        symbol_rows: list[dict[str, Any]] = []
        for b in matched_bars:
            row: dict[str, Any] = {
                "symbol": symbol,
                "time": b["time"],
            }
            for field in request.required_fields:
                if field not in b:
                    blockers.append(
                        BlockerReason(
                            code="REQUIRED_FIELD_MISSING",
                            symbol=symbol,
                            message=f"Required field '{field}' missing from bar at '{b.get('time')}'.",
                        )
                    )
                    break
                row[field] = b[field]
            symbol_rows.append(row)

        symbol_row_counts[symbol] = len(symbol_rows)
        all_rows.extend(symbol_rows)

    # 5. Load authoritative Source Manifest Hashes
    source_manifest_hashes: dict[str, str] = {}
    catalog_path = repo_root / "data/research/market_evidence" / request.market / "catalog.json"
    if catalog_path.is_file():
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            if "provider_manifest_sha256" in catalog:
                source_manifest_hashes[f"prices.{request.pool_id}"] = catalog["provider_manifest_sha256"]
        except json.JSONDecodeError:
            pass

    ca_manifest_path = (
        repo_root
        / "data/research/model_data_bundle_v1/sources"
        / f"{request.market}_events/corporate_actions/component_manifest.json"
    )
    if ca_manifest_path.is_file():
        try:
            ca_manifest = json.loads(ca_manifest_path.read_text(encoding="utf-8"))
            if "manifest_sha256" in ca_manifest:
                source_manifest_hashes[f"corporate_actions.{request.pool_id}"] = ca_manifest["manifest_sha256"]
            elif "details" in ca_manifest and "events_sha256" in ca_manifest["details"]:
                source_manifest_hashes[f"corporate_actions.{request.pool_id}"] = ca_manifest["details"]["events_sha256"]
        except json.JSONDecodeError:
            pass

    # 6. Compute request hash & slice ID
    request_dict = request.to_dict()
    canonical_req_bytes = json.dumps(request_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request_hash = hashlib.sha256(canonical_req_bytes).hexdigest()
    slice_id = f"slice_{request.market}_{request_hash[:12]}"

    # 7. Assemble outcome
    if blockers:
        receipt = {
            "schema_version": "research_data_slice_v1",
            "slice_id": slice_id,
            "request_hash": request_hash,
            "status": "blocked",
            "blocked_reasons": [b.to_dict() for b in blockers],
            "data_hash": None,
            "total_rows": 0,
            "symbol_row_counts": symbol_row_counts,
            "source_manifest_hashes": source_manifest_hashes,
            "market": request.market,
            "pool_id": request.pool_id,
            "as_of_cutoff": request.as_of_cutoff,
            "rights_label": "academic_and_internal_research_only",
            "research_only": True,
            "trade_ready": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        return DataSliceResult(receipt=receipt, data=None)

    # Sort rows deterministically by (symbol, time)
    all_rows.sort(key=lambda r: (r["symbol"], r["time"]))
    canonical_data_bytes = json.dumps(all_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    data_hash = hashlib.sha256(canonical_data_bytes).hexdigest()

    df = pd.DataFrame(all_rows)

    receipt = {
        "schema_version": "research_data_slice_v1",
        "slice_id": slice_id,
        "request_hash": request_hash,
        "status": "ready",
        "blocked_reasons": [],
        "data_hash": data_hash,
        "total_rows": len(all_rows),
        "symbol_row_counts": symbol_row_counts,
        "source_manifest_hashes": source_manifest_hashes,
        "market": request.market,
        "pool_id": request.pool_id,
        "as_of_cutoff": request.as_of_cutoff,
        "rights_label": "academic_and_internal_research_only",
        "research_only": True,
        "trade_ready": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return DataSliceResult(receipt=receipt, data=df)
