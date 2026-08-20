"""Build exact-pool event stores, coverage evidence and model-data components."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

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
ROOT_MANIFEST_NAME = "event_population_manifest.json"
BUNDLE_SCHEMA_VERSION = "2.0"
MEMBER_PATHS = (
    "corporate_actions/component_manifest.json",
    "corporate_actions/coverage.json",
    "corporate_actions/events.jsonl",
    "fundamentals/component_manifest.json",
    "fundamentals/coverage.json",
    "fundamentals/events.jsonl",
)
REQUIRED_GOVERNANCE_ROLES = (
    "lifecycle_registry",
    "pool_spec",
    "population_contract",
    "reference_instrument_registry",
    "selected_pool_registry",
)


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


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelectedPoolEventPopulationError(f"invalid JSON artifact: {path}") from exc


def _member_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SelectedPoolEventPopulationError(
            f"bundle member escapes output root: {relative}"
        ) from exc
    return candidate


def _file_record(root: Path, relative: str) -> dict[str, Any]:
    path = _member_path(root, relative)
    return {
        "path": relative,
        "sha256": _sha256(path),
        "byte_size": path.stat().st_size,
        "media_type": "application/x-ndjson" if path.suffix == ".jsonl" else "application/json",
    }


def _bundle_id(manifest: Mapping[str, Any]) -> str:
    identity = {
        "schema_version": manifest.get("schema_version"),
        "market": manifest.get("market"),
        "pool_id": manifest.get("pool_id"),
        "evidence_cutoff": manifest.get("evidence_cutoff"),
        "evidence_class": manifest.get("evidence_class"),
        "symbols": manifest.get("symbols"),
        "governance_bindings": manifest.get("governance_bindings"),
        "files": manifest.get("files"),
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _governance_records(paths: Mapping[str, str | Path]) -> list[dict[str, Any]]:
    if tuple(sorted(paths)) != REQUIRED_GOVERNANCE_ROLES:
        raise SelectedPoolEventPopulationError("governance binding roles are not exact")
    root = Path.cwd().resolve()
    records: list[dict[str, Any]] = []
    for role in REQUIRED_GOVERNANCE_ROLES:
        path = Path(paths[role]).resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise SelectedPoolEventPopulationError(
                f"governance binding must be inside repository root: {role}"
            ) from exc
        if not path.is_file():
            raise SelectedPoolEventPopulationError(f"governance binding is missing: {role}")
        records.append(
            {
                "role": role,
                "path": relative,
                "sha256": _sha256(path),
                "byte_size": path.stat().st_size,
            }
        )
    return records


def _yaml_mapping(path: str | Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SelectedPoolEventPopulationError(f"invalid governance YAML: {path}") from exc
    if not isinstance(payload, dict):
        raise SelectedPoolEventPopulationError(f"governance YAML must be a mapping: {path}")
    return payload


def _validate_governance_identity(
    paths: Mapping[str, str | Path],
    *,
    market: str,
    pool_id: str,
    symbols: Sequence[str],
) -> None:
    pool = _yaml_mapping(paths["pool_spec"])
    if pool.get("pool_id") != pool_id or pool.get("symbols") != list(symbols):
        raise SelectedPoolEventPopulationError("pool spec identity does not match publication")
    if pool.get("candidate_count") != len(symbols):
        raise SelectedPoolEventPopulationError("pool spec candidate count does not match publication")

    population_contract = _yaml_mapping(paths["population_contract"])
    market_contract = population_contract.get("markets", {}).get(market, {})
    if not isinstance(market_contract, dict) or market_contract.get("pool_id") != pool_id:
        raise SelectedPoolEventPopulationError("population contract identity mismatch")

    repository_root = Path.cwd().resolve()
    expected_pool_path = Path(paths["pool_spec"]).resolve().relative_to(repository_root).as_posix()
    if market_contract.get("pool_spec") != expected_pool_path:
        raise SelectedPoolEventPopulationError("population contract pool path mismatch")

    pool_registry = _yaml_mapping(paths["selected_pool_registry"])
    registry_market = pool_registry.get("markets", {}).get(market, {})
    if not isinstance(registry_market, dict):
        raise SelectedPoolEventPopulationError("selected-pool registry market is missing")
    if (
        registry_market.get("active_pool_id") != pool_id
        or registry_market.get("pool_spec") != expected_pool_path
        or registry_market.get("candidate_count") != len(symbols)
    ):
        raise SelectedPoolEventPopulationError("selected-pool registry identity mismatch")

    reference_registry = _yaml_mapping(paths["reference_instrument_registry"])
    reference_path = (
        Path(paths["reference_instrument_registry"])
        .resolve()
        .relative_to(repository_root)
        .as_posix()
    )
    if (
        reference_registry.get("registry_id") != "reference_instrument_registry_v1"
        or pool_registry.get("reference_instrument_registry") != reference_path
    ):
        raise SelectedPoolEventPopulationError("reference registry identity mismatch")

    lifecycle_registry = _yaml_mapping(paths["lifecycle_registry"])
    if lifecycle_registry.get("registry_id") != "symbol_identity_and_lifecycle_v1":
        raise SelectedPoolEventPopulationError("lifecycle registry identity mismatch")


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SelectedPoolEventPopulationError(f"invalid JSONL artifact: {path}") from exc
    for line_number, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SelectedPoolEventPopulationError(
                f"invalid JSONL row: {path}:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise SelectedPoolEventPopulationError(
                f"JSONL row must be an object: {path}:{line_number}"
            )
        rows.append(row)
    return rows


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
    events_relative_path: str,
    coverage_path: Path,
    coverage_relative_path: str,
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
            "events_path": events_relative_path,
            "events_sha256": _sha256(events_path),
            "events_byte_size": events_path.stat().st_size,
            "coverage_path": coverage_relative_path,
            "coverage_sha256": _sha256(coverage_path),
            "coverage_byte_size": coverage_path.stat().st_size,
            "explicit_status_count": len(rows),
            "status_counts": {
                status_name: sum(1 for row in rows if row["status"] == status_name)
                for status_name in sorted(ALLOWED_SYMBOL_STATUSES)
            },
        },
    }


def _verify_component(
    *,
    root: Path,
    root_manifest: Mapping[str, Any],
    component_path: str,
    events_path: str,
    coverage_path: str,
    component_kind: str,
) -> None:
    component = _read_json(_member_path(root, component_path))
    if not isinstance(component, dict):
        raise SelectedPoolEventPopulationError(f"component manifest invalid: {component_path}")
    for field in ("market", "pool_id", "evidence_cutoff"):
        if component.get(field) != root_manifest.get(field):
            raise SelectedPoolEventPopulationError(
                f"component identity mismatch: {component_path}.{field}"
            )
    if component.get("component_kind") != component_kind:
        raise SelectedPoolEventPopulationError(
            f"component kind mismatch: {component_path}"
        )
    if component.get("research_only") is not True or component.get("trade_ready") is not False:
        raise SelectedPoolEventPopulationError(
            f"component research boundary mismatch: {component_path}"
        )

    details = component.get("details")
    if not isinstance(details, dict):
        raise SelectedPoolEventPopulationError(f"component details missing: {component_path}")
    expected_member_bindings = {
        "events_path": events_path,
        "events_sha256": _sha256(_member_path(root, events_path)),
        "events_byte_size": _member_path(root, events_path).stat().st_size,
        "coverage_path": coverage_path,
        "coverage_sha256": _sha256(_member_path(root, coverage_path)),
        "coverage_byte_size": _member_path(root, coverage_path).stat().st_size,
    }
    for field, expected in expected_member_bindings.items():
        if details.get(field) != expected:
            raise SelectedPoolEventPopulationError(
                f"component member binding mismatch: {component_path}.{field}"
            )

    coverage = _read_json(_member_path(root, coverage_path))
    if not isinstance(coverage, list) or not all(isinstance(row, dict) for row in coverage):
        raise SelectedPoolEventPopulationError(
            f"component coverage must be an object list: {component_path}"
        )
    symbols = root_manifest.get("symbols")
    if not isinstance(symbols, list) or [row.get("symbol") for row in coverage] != symbols:
        raise SelectedPoolEventPopulationError(
            f"component coverage symbol closure mismatch: {component_path}"
        )
    for row in coverage:
        if row.get("status") not in ALLOWED_SYMBOL_STATUSES:
            raise SelectedPoolEventPopulationError(
                f"component coverage status mismatch: {component_path}"
            )
        if row.get("kind") != component_kind:
            raise SelectedPoolEventPopulationError(
                f"component coverage kind mismatch: {component_path}"
            )
        if not isinstance(row.get("event_count"), int) or int(row["event_count"]) < 0:
            raise SelectedPoolEventPopulationError(
                f"component coverage event count mismatch: {component_path}"
            )

    events = _jsonl_rows(_member_path(root, events_path))
    event_counts = {str(symbol): 0 for symbol in symbols}
    cutoff = date.fromisoformat(str(root_manifest["evidence_cutoff"]))
    event_ids: set[str] = set()
    for event in events:
        symbol = str(event.get("symbol") or "")
        if symbol not in event_counts:
            raise SelectedPoolEventPopulationError(
                f"event outside selected-pool closure: {component_path}/{symbol}"
            )
        if event.get("market") != root_manifest.get("market"):
            raise SelectedPoolEventPopulationError(
                f"event market mismatch: {component_path}/{symbol}"
            )
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in event_ids:
            raise SelectedPoolEventPopulationError(
                f"event identity is missing or duplicated: {component_path}/{symbol}"
            )
        event_ids.add(event_id)
        event_counts[symbol] += 1
        if component_kind == "fundamental_coverage":
            available = str(event.get("available_at") or "")
        else:
            available = str(event.get("announced_at") or event.get("effective_date") or "")
        try:
            available_date = datetime.fromisoformat(available).date()
        except ValueError as exc:
            raise SelectedPoolEventPopulationError(
                f"event availability date invalid: {component_path}/{symbol}"
            ) from exc
        if available_date > cutoff:
            raise SelectedPoolEventPopulationError(
                f"event exceeds evidence cutoff: {component_path}/{symbol}"
            )
    if any(int(row["event_count"]) != event_counts[str(row["symbol"])] for row in coverage):
        raise SelectedPoolEventPopulationError(
            f"component event counts do not match coverage: {component_path}"
        )

    status, ready = _component_status(component_kind, coverage)
    expected = len(symbols)
    missing = sorted(
        str(row["symbol"])
        for row in coverage
        if row["status"] in {"provider_missing", "identity_missing"}
    )
    invalid = sorted(str(row["symbol"]) for row in coverage if row["status"] == "conflict")
    providers = sorted(
        {
            str(provider)
            for row in coverage
            for provider in row.get("providers", [])
            if str(provider)
        }
    )
    expected_values = {
        "status": status,
        "expected_symbol_count": expected,
        "ready_symbol_count": ready,
        "coverage_ratio": ready / expected,
        "missing_symbols": missing,
        "invalid_symbols": invalid,
        "providers": providers,
    }
    for field, expected_value in expected_values.items():
        if component.get(field) != expected_value:
            raise SelectedPoolEventPopulationError(
                f"component coverage summary mismatch: {component_path}.{field}"
            )
    if details.get("explicit_status_count") != expected:
        raise SelectedPoolEventPopulationError(
            f"component explicit status count mismatch: {component_path}"
        )


def verify_selected_pool_event_bundle(
    bundle_root: str | Path,
    *,
    expected_market: str | None = None,
    expected_pool_id: str | None = None,
    expected_symbols: Sequence[str] | None = None,
    expected_cutoff: str | None = None,
    expected_governance_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Verify the complete selected-pool event evidence closure and return its manifest."""

    root = Path(bundle_root).resolve()
    manifest_path = root / ROOT_MANIFEST_NAME
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise SelectedPoolEventPopulationError("event population manifest must be an object")
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise SelectedPoolEventPopulationError("unsupported event population bundle schema")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise SelectedPoolEventPopulationError("event population research boundary mismatch")
    evidence_class = manifest.get("evidence_class")
    if evidence_class not in {"source_bound", "contract_fixture"}:
        raise SelectedPoolEventPopulationError("event population evidence class mismatch")
    if manifest.get("publication_eligible") is not (evidence_class == "source_bound"):
        raise SelectedPoolEventPopulationError("event population publication eligibility mismatch")

    market = str(manifest.get("market") or "")
    pool_id = str(manifest.get("pool_id") or "")
    cutoff = str(manifest.get("evidence_cutoff") or "")
    symbols = manifest.get("symbols")
    if market not in {"us", "cn"} or not pool_id:
        raise SelectedPoolEventPopulationError("event population identity is incomplete")
    try:
        date.fromisoformat(cutoff)
        datetime.fromisoformat(str(manifest.get("generated_at") or ""))
    except ValueError as exc:
        raise SelectedPoolEventPopulationError("event population dates are invalid") from exc
    if not isinstance(symbols, list):
        raise SelectedPoolEventPopulationError("event population symbols must be a list")
    normalized_symbols = [str(value).strip().upper() for value in symbols]
    if normalized_symbols != symbols or len(symbols) != len(set(symbols)) or not symbols:
        raise SelectedPoolEventPopulationError("event population symbols are not exact")
    if manifest.get("expected_symbol_count") != len(symbols):
        raise SelectedPoolEventPopulationError("event population symbol count mismatch")
    if manifest.get("bundle_id") != _bundle_id(manifest):
        raise SelectedPoolEventPopulationError("event population bundle identity mismatch")

    governance = manifest.get("governance_bindings")
    if not isinstance(governance, list) or not all(isinstance(row, dict) for row in governance):
        raise SelectedPoolEventPopulationError("event population governance bindings are invalid")
    governance_roles = tuple(str(row.get("role") or "") for row in governance)
    if evidence_class == "source_bound" and governance_roles != REQUIRED_GOVERNANCE_ROLES:
        raise SelectedPoolEventPopulationError("source-bound governance bindings are incomplete")
    if len(governance_roles) != len(set(governance_roles)):
        raise SelectedPoolEventPopulationError("event population governance roles are duplicated")
    for record in governance:
        relative = str(record.get("path") or "")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise SelectedPoolEventPopulationError("event population governance path is unsafe")
        digest = str(record.get("sha256") or "")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise SelectedPoolEventPopulationError("event population governance digest is invalid")
        if not isinstance(record.get("byte_size"), int) or int(record["byte_size"]) < 0:
            raise SelectedPoolEventPopulationError("event population governance size is invalid")
    if expected_governance_paths is not None:
        _validate_governance_identity(
            expected_governance_paths,
            market=market,
            pool_id=pool_id,
            symbols=symbols,
        )
        if governance != _governance_records(expected_governance_paths):
            raise SelectedPoolEventPopulationError("event population governance identity mismatch")

    expected_identity = {
        "market": expected_market,
        "pool_id": expected_pool_id,
        "evidence_cutoff": expected_cutoff,
    }
    actual_identity = {"market": market, "pool_id": pool_id, "evidence_cutoff": cutoff}
    for field, expected in expected_identity.items():
        if expected is not None and actual_identity[field] != expected:
            raise SelectedPoolEventPopulationError(f"event population {field} mismatch")
    if expected_symbols is not None:
        expected_normalized = [str(value).strip().upper() for value in expected_symbols]
        if symbols != expected_normalized:
            raise SelectedPoolEventPopulationError("event population selected-pool mismatch")

    inventory = manifest.get("files")
    if not isinstance(inventory, list) or not all(isinstance(row, dict) for row in inventory):
        raise SelectedPoolEventPopulationError("event population file inventory is missing")
    inventory_paths = [str(row.get("path") or "") for row in inventory]
    if inventory_paths != list(MEMBER_PATHS):
        raise SelectedPoolEventPopulationError("event population file inventory is not exact")
    actual_paths = sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )
    if actual_paths != sorted((ROOT_MANIFEST_NAME, *MEMBER_PATHS)):
        missing = sorted(set((ROOT_MANIFEST_NAME, *MEMBER_PATHS)) - set(actual_paths))
        extra = sorted(set(actual_paths) - set((ROOT_MANIFEST_NAME, *MEMBER_PATHS)))
        raise SelectedPoolEventPopulationError(
            f"event population file closure mismatch: missing={missing}, extra={extra}"
        )
    for record, relative in zip(inventory, MEMBER_PATHS, strict=True):
        if record != _file_record(root, relative):
            raise SelectedPoolEventPopulationError(
                f"event population member binding mismatch: {relative}"
            )

    components = manifest.get("components")
    expected_components = [
        {
            "component_id": f"corporate_actions.{pool_id}",
            "component_kind": "corporate_action_coverage",
            "manifest_path": "corporate_actions/component_manifest.json",
            "manifest_sha256": _sha256(
                _member_path(root, "corporate_actions/component_manifest.json")
            ),
        },
        {
            "component_id": f"fundamentals.{pool_id}",
            "component_kind": "fundamental_coverage",
            "manifest_path": "fundamentals/component_manifest.json",
            "manifest_sha256": _sha256(_member_path(root, "fundamentals/component_manifest.json")),
        },
    ]
    if components != expected_components:
        raise SelectedPoolEventPopulationError("event population component closure mismatch")

    _verify_component(
        root=root,
        root_manifest=manifest,
        component_path="fundamentals/component_manifest.json",
        events_path="fundamentals/events.jsonl",
        coverage_path="fundamentals/coverage.json",
        component_kind="fundamental_coverage",
    )
    _verify_component(
        root=root,
        root_manifest=manifest,
        component_path="corporate_actions/component_manifest.json",
        events_path="corporate_actions/events.jsonl",
        coverage_path="corporate_actions/coverage.json",
        component_kind="corporate_action_coverage",
    )
    return manifest


def _install_verified_bundle(staging: Path, target: Path) -> None:
    if target.exists() and not target.is_dir():
        raise SelectedPoolEventPopulationError("event population output root must be a directory")
    if not target.exists():
        os.replace(staging, target)
        return
    if any(path.is_file() for path in target.rglob("*")):
        raise SelectedPoolEventPopulationError(
            "event population destination already contains evidence"
        )
    shutil.rmtree(target)
    os.replace(staging, target)


def publish_selected_pool_event_bundle(
    *,
    market: str,
    pool_id: str,
    symbols: Sequence[str],
    fundamentals: Mapping[str, SymbolPopulation],
    corporate_actions: Mapping[str, SymbolPopulation],
    evidence_cutoff: str,
    output_root: str | Path,
    source_reuse: Mapping[str, Any] | None = None,
    governance_paths: Mapping[str, str | Path] | None = None,
    evidence_class: str = "source_bound",
) -> dict[str, Any]:
    """Build, verify, and transactionally publish selected-pool event evidence."""

    normalized_symbols = [str(value).strip().upper() for value in symbols]
    if evidence_class not in {"source_bound", "contract_fixture"}:
        raise SelectedPoolEventPopulationError("unsupported event population evidence class")
    if evidence_class == "source_bound" and governance_paths is None:
        raise SelectedPoolEventPopulationError(
            "source-bound event evidence requires exact governance bindings"
        )
    governance_bindings = _governance_records(governance_paths or {}) if governance_paths else []
    if governance_paths:
        _validate_governance_identity(
            governance_paths,
            market=market,
            pool_id=pool_id,
            symbols=normalized_symbols,
        )
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
    target = Path(output_root).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=str(target.parent)))

    try:
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
        fundamental_coverage_path = output / "fundamentals/coverage.json"
        corporate_coverage_path = output / "corporate_actions/coverage.json"
        _write_json(fundamental_coverage_path, fundamental_rows)
        _write_json(corporate_coverage_path, corporate_rows)

        fundamental_manifest = _component_manifest(
            component_id=f"fundamentals.{pool_id}",
            component_kind="fundamental_coverage",
            market=market,
            pool_id=pool_id,
            evidence_cutoff=evidence_cutoff,
            rows=fundamental_rows,
            events_path=fundamental_path,
            events_relative_path="fundamentals/events.jsonl",
            coverage_path=fundamental_coverage_path,
            coverage_relative_path="fundamentals/coverage.json",
        )
        corporate_manifest = _component_manifest(
            component_id=f"corporate_actions.{pool_id}",
            component_kind="corporate_action_coverage",
            market=market,
            pool_id=pool_id,
            evidence_cutoff=evidence_cutoff,
            rows=corporate_rows,
            events_path=corporate_path,
            events_relative_path="corporate_actions/events.jsonl",
            coverage_path=corporate_coverage_path,
            coverage_relative_path="corporate_actions/coverage.json",
        )
        _write_json(output / "fundamentals/component_manifest.json", fundamental_manifest)
        _write_json(output / "corporate_actions/component_manifest.json", corporate_manifest)
        root_manifest = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "market": market,
            "pool_id": pool_id,
            "evidence_cutoff": evidence_cutoff,
            "evidence_class": evidence_class,
            "publication_eligible": evidence_class == "source_bound",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "expected_symbol_count": len(normalized_symbols),
            "symbols": normalized_symbols,
            "cutoff_filter": {
                "availability_policy": (
                    "fundamentals.available_at; corporate_actions.announced_at_or_effective_date"
                ),
                "fundamental_events_excluded": sum(fundamental_removed.values()),
                "corporate_action_events_excluded": sum(corporate_removed.values()),
            },
            "research_only": True,
            "trade_ready": False,
            "governance_bindings": governance_bindings,
        }
        if source_reuse is not None:
            root_manifest["source_reuse"] = dict(source_reuse)
        root_manifest["files"] = [_file_record(output, relative) for relative in MEMBER_PATHS]
        root_manifest["components"] = [
            {
                "component_id": f"corporate_actions.{pool_id}",
                "component_kind": "corporate_action_coverage",
                "manifest_path": "corporate_actions/component_manifest.json",
                "manifest_sha256": _sha256(
                    output / "corporate_actions/component_manifest.json"
                ),
            },
            {
                "component_id": f"fundamentals.{pool_id}",
                "component_kind": "fundamental_coverage",
                "manifest_path": "fundamentals/component_manifest.json",
                "manifest_sha256": _sha256(output / "fundamentals/component_manifest.json"),
            },
        ]
        root_manifest["bundle_id"] = _bundle_id(root_manifest)
        _write_json(output / ROOT_MANIFEST_NAME, root_manifest)
        verified = verify_selected_pool_event_bundle(
            output,
            expected_market=market,
            expected_pool_id=pool_id,
            expected_symbols=normalized_symbols,
            expected_cutoff=evidence_cutoff,
            expected_governance_paths=governance_paths,
        )
        _install_verified_bundle(output, target)
        return verified
    finally:
        if output.exists():
            shutil.rmtree(output)
