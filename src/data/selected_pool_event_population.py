"""Build exact-pool event stores, coverage evidence and model-data components."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.data.corporate_actions.event_store import CorporateActionEvent
from src.data.fundamentals.event_store import FundamentalEvent

ALLOWED_SYMBOL_STATUSES = {
    "ready",
    "partial",
    "provider_missing",
    "identity_missing",
    "conflict",
    "no_event_observed",
}


class SelectedPoolEventPopulationError(ValueError):
    """Raised when event population cannot preserve exact-pool evidence."""


@dataclass(frozen=True)
class SymbolPopulation:
    symbol: str
    status: str
    events: Sequence[FundamentalEvent | CorporateActionEvent]
    providers: Sequence[str]
    error: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, events: Iterable[Any]) -> int:
    rows = sorted(
        (event.to_dict() for event in events),
        key=lambda row: (
            str(
                row.get("available_at")
                or row.get("announced_at")
                or row.get("effective_date")
                or ""
            ),
            str(row.get("symbol") or ""),
            str(row.get("field") or row.get("event_type") or ""),
            str(row.get("event_id") or ""),
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            )
    return len(rows)


def _validate_populations(
    symbols: Sequence[str],
    populations: Mapping[str, SymbolPopulation],
) -> None:
    expected = [str(value).strip().upper() for value in symbols]
    if len(expected) != len(set(expected)) or not expected:
        raise SelectedPoolEventPopulationError("selected-pool symbols must be exact")
    if set(expected) != set(populations):
        missing = sorted(set(expected) - set(populations))
        extra = sorted(set(populations) - set(expected))
        raise SelectedPoolEventPopulationError(
            f"population symbol mismatch: missing={missing}, extra={extra}"
        )
    for symbol, population in populations.items():
        if population.symbol.upper() != symbol:
            raise SelectedPoolEventPopulationError(f"population symbol identity mismatch: {symbol}")
        if population.status not in ALLOWED_SYMBOL_STATUSES:
            raise SelectedPoolEventPopulationError(
                f"unsupported population status: {population.status}"
            )
        for event in population.events:
            if event.symbol != symbol:
                raise SelectedPoolEventPopulationError(
                    f"event outside declared symbol population: {symbol}"
                )


def _availability_date(event: FundamentalEvent | CorporateActionEvent) -> date:
    """Return the first date on which an event was knowable to the model."""

    if isinstance(event, FundamentalEvent):
        return datetime.fromisoformat(event.available_at).date()
    if event.announced_at:
        return datetime.fromisoformat(event.announced_at).date()
    return date.fromisoformat(event.effective_date)


def _apply_evidence_cutoff(
    populations: Mapping[str, SymbolPopulation],
    *,
    cutoff: date,
    kind: str,
) -> tuple[dict[str, SymbolPopulation], dict[str, int]]:
    """Exclude observations that were not knowable at the evidence cutoff."""

    filtered: dict[str, SymbolPopulation] = {}
    removed: dict[str, int] = {}
    for symbol, population in populations.items():
        events = [event for event in population.events if _availability_date(event) <= cutoff]
        removed[symbol] = len(population.events) - len(events)
        status = population.status
        if not events and population.events and status in {"ready", "partial"}:
            status = "partial" if kind == "fundamentals" else "no_event_observed"
        filtered[symbol] = SymbolPopulation(
            symbol=population.symbol,
            status=status,
            events=events,
            providers=population.providers,
            error=population.error,
        )
    return filtered, removed


def _coverage_rows(
    symbols: Sequence[str],
    populations: Mapping[str, SymbolPopulation],
    *,
    kind: str,
    cutoff_removed: Mapping[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        population = populations[symbol]
        events = list(population.events)
        available_dates: list[str] = []
        effective_dates: list[str] = []
        field_counts: dict[str, int] = {}
        for event in events:
            payload = event.to_dict()
            available_dates.append(_availability_date(event).isoformat())
            effective_date = str(payload.get("effective_date") or "")
            if effective_date:
                effective_dates.append(effective_date[:10])
            key = str(payload.get("field") or payload.get("event_type") or "unknown")
            field_counts[key] = field_counts.get(key, 0) + 1
        rows.append(
            {
                "symbol": symbol,
                "kind": kind,
                "status": population.status,
                "event_count": len(events),
                "first_event_date": min(available_dates) if available_dates else None,
                "latest_event_date": max(available_dates) if available_dates else None,
                "first_available_date": (min(available_dates) if available_dates else None),
                "latest_available_date": (max(available_dates) if available_dates else None),
                "first_effective_date": (min(effective_dates) if effective_dates else None),
                "latest_effective_date": (max(effective_dates) if effective_dates else None),
                "excluded_after_cutoff": int(cutoff_removed.get(symbol, 0)),
                "fields_or_types": dict(sorted(field_counts.items())),
                "providers": sorted(set(population.providers)),
                "error": population.error,
            }
        )
    return rows


def _component_status(kind: str, rows: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    blockers = {"provider_missing", "identity_missing", "conflict"}
    blocked = sum(1 for row in rows if str(row["status"]) in blockers)
    if kind == "corporate_action_coverage":
        ready = len(rows) - blocked
    else:
        ready = sum(
            1
            for row in rows
            if str(row["status"]) in {"ready", "partial"} and int(row.get("event_count", 0)) > 0
        )
    if blocked:
        status = "partial" if ready else "blocked"
    elif ready == len(rows):
        status = "ready"
    else:
        status = "partial"
    return status, ready


def _component_manifest(
    *,
    component_id: str,
    component_kind: str,
    market: str,
    pool_id: str,
    evidence_cutoff: str,
    rows: Sequence[Mapping[str, Any]],
    events_path: Path,
) -> dict[str, Any]:
    status, ready = _component_status(component_kind, rows)
    missing = sorted(
        str(row["symbol"])
        for row in rows
        if str(row["status"]) in {"provider_missing", "identity_missing"}
    )
    invalid = sorted(str(row["symbol"]) for row in rows if str(row["status"]) == "conflict")
    providers = sorted(
        {str(provider) for row in rows for provider in row.get("providers", []) if str(provider)}
    )
    expected = len(rows)
    return {
        "schema_version": "1.0",
        "component_id": component_id,
        "component_kind": component_kind,
        "status": status,
        "market": market,
        "pool_id": pool_id,
        "evidence_cutoff": evidence_cutoff,
        "first_date": min(
            (str(row["first_event_date"]) for row in rows if row.get("first_event_date")),
            default=None,
        ),
        "last_date": max(
            (str(row["latest_event_date"]) for row in rows if row.get("latest_event_date")),
            default=None,
        ),
        "expected_symbol_count": expected,
        "ready_symbol_count": ready,
        "coverage_ratio": ready / expected if expected else 0.0,
        "missing_symbols": missing,
        "invalid_symbols": invalid,
        "quarantined_symbols": [],
        "providers": providers,
        "research_only": True,
        "trade_ready": False,
        "details": {
            "events_path": str(events_path),
            "events_sha256": _sha256(events_path),
            "explicit_status_count": len(rows),
            "status_counts": {
                status_name: sum(1 for row in rows if row["status"] == status_name)
                for status_name in sorted(ALLOWED_SYMBOL_STATUSES)
            },
        },
    }


def build_selected_pool_event_artifacts(
    *,
    market: str,
    pool_id: str,
    symbols: Sequence[str],
    fundamentals: Mapping[str, SymbolPopulation],
    corporate_actions: Mapping[str, SymbolPopulation],
    evidence_cutoff: str,
    output_root: str | Path,
    source_reuse: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write two event stores and their direct model-data component manifests."""

    normalized_symbols = [str(value).strip().upper() for value in symbols]
    _validate_populations(normalized_symbols, fundamentals)
    _validate_populations(normalized_symbols, corporate_actions)
    try:
        cutoff = date.fromisoformat(evidence_cutoff)
    except ValueError as exc:
        raise SelectedPoolEventPopulationError("evidence_cutoff must be an ISO date") from exc
    fundamentals, fundamental_removed = _apply_evidence_cutoff(
        fundamentals,
        cutoff=cutoff,
        kind="fundamentals",
    )
    corporate_actions, corporate_removed = _apply_evidence_cutoff(
        corporate_actions,
        cutoff=cutoff,
        kind="corporate_actions",
    )
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)

    fundamental_path = output / "fundamentals/events.jsonl"
    corporate_path = output / "corporate_actions/events.jsonl"
    _write_jsonl(
        fundamental_path,
        (event for symbol in normalized_symbols for event in fundamentals[symbol].events),
    )
    _write_jsonl(
        corporate_path,
        (event for symbol in normalized_symbols for event in corporate_actions[symbol].events),
    )

    fundamental_rows = _coverage_rows(
        normalized_symbols,
        fundamentals,
        kind="fundamental_coverage",
        cutoff_removed=fundamental_removed,
    )
    corporate_rows = _coverage_rows(
        normalized_symbols,
        corporate_actions,
        kind="corporate_action_coverage",
        cutoff_removed=corporate_removed,
    )
    _write_json(output / "fundamentals/coverage.json", fundamental_rows)
    _write_json(output / "corporate_actions/coverage.json", corporate_rows)

    fundamental_manifest = _component_manifest(
        component_id=f"fundamentals.{pool_id}",
        component_kind="fundamental_coverage",
        market=market,
        pool_id=pool_id,
        evidence_cutoff=evidence_cutoff,
        rows=fundamental_rows,
        events_path=fundamental_path,
    )
    corporate_manifest = _component_manifest(
        component_id=f"corporate_actions.{pool_id}",
        component_kind="corporate_action_coverage",
        market=market,
        pool_id=pool_id,
        evidence_cutoff=evidence_cutoff,
        rows=corporate_rows,
        events_path=corporate_path,
    )
    _write_json(output / "fundamentals/component_manifest.json", fundamental_manifest)
    _write_json(output / "corporate_actions/component_manifest.json", corporate_manifest)
    root_manifest = {
        "schema_version": "1.0",
        "bundle_id": f"{pool_id}_event_population_v1",
        "market": market,
        "pool_id": pool_id,
        "evidence_cutoff": evidence_cutoff,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "expected_symbol_count": len(normalized_symbols),
        "cutoff_filter": {
            "availability_policy": (
                "fundamentals.available_at; corporate_actions.announced_at_or_effective_date"
            ),
            "fundamental_events_excluded": sum(fundamental_removed.values()),
            "corporate_action_events_excluded": sum(corporate_removed.values()),
        },
        "fundamental_component": fundamental_manifest,
        "corporate_action_component": corporate_manifest,
        "research_only": True,
        "trade_ready": False,
    }
    if source_reuse is not None:
        root_manifest["source_reuse"] = dict(source_reuse)
    _write_json(output / "event_population_manifest.json", root_manifest)
    return root_manifest
