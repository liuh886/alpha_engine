"""Unified model-training and frontend data-readiness manifests.

The builder normalizes heterogeneous provider, coverage and catalog manifests
into one fail-closed contract. Model runners and the read-only frontend can then
consume the same component status, coverage, cutoff and content identities.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from src.data.selected_pool_price_publication import (
    PUBLICATION_EVIDENCE_TYPE,
    SelectedPoolPricePublicationError,
    load_selected_pool_price_publication_manifest,
)

ALLOWED_STATUSES = {
    "ready",
    "partial",
    "blocked",
    "not_provided",
    "not_applicable",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ModelDataBundleError(ValueError):
    """Raised when readiness evidence cannot be normalized safely."""


@dataclass(frozen=True)
class ComponentSpec:
    component_id: str
    component_kind: str
    manifest_path: Path
    market: str | None = None


@dataclass(frozen=True)
class DataComponent:
    component_id: str
    component_kind: str
    status: str
    market: str
    pool_id: str
    manifest_path: str
    manifest_sha256: str
    evidence_cutoff: str | None
    first_date: str | None
    last_date: str | None
    expected_symbol_count: int
    ready_symbol_count: int
    coverage_ratio: float
    not_yet_applicable_symbols: tuple[str, ...]
    missing_symbols: tuple[str, ...]
    invalid_symbols: tuple[str, ...]
    quarantined_symbols: tuple[str, ...]
    providers: tuple[str, ...]
    professional_source_ready: bool | None
    research_only: bool
    trade_ready: bool
    details: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "not_yet_applicable_symbols",
            "missing_symbols",
            "invalid_symbols",
            "quarantined_symbols",
            "providers",
        ):
            payload[key] = list(payload[key])
        payload["details"] = dict(self.details)
        return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ModelDataBundleError(f"component manifest is missing: {path}")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ModelDataBundleError(f"component manifest must be a mapping: {path}")
    return payload


def _clean_symbols(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip().upper() for value in values if str(value).strip()}))


def _parse_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ModelDataBundleError(f"invalid evidence date: {value}") from exc


def _ratio(ready: int, expected: int) -> float:
    if expected <= 0:
        return 1.0 if ready <= 0 else 0.0
    return max(0.0, min(1.0, float(ready / expected)))


def _direct_component(
    spec: ComponentSpec,
    path: Path,
    payload: Mapping[str, Any],
) -> DataComponent | None:
    if "component_id" not in payload or "component_kind" not in payload:
        return None
    status = str(payload.get("status", "")).strip().lower()
    if status not in ALLOWED_STATUSES:
        raise ModelDataBundleError(f"unsupported component status: {status}")
    expected = int(payload.get("expected_symbol_count", 0))
    ready = int(payload.get("ready_symbol_count", 0))
    declared_hash = str(payload.get("manifest_sha256", "")).strip().lower()
    actual_hash = _sha256(path)
    if declared_hash and declared_hash != actual_hash:
        raise ModelDataBundleError(f"component manifest hash mismatch: {path}")
    return DataComponent(
        component_id=spec.component_id,
        component_kind=spec.component_kind,
        status=status,
        market=str(spec.market or payload.get("market", "global")).lower(),
        pool_id=str(payload.get("pool_id", "")),
        manifest_path=str(path),
        manifest_sha256=actual_hash,
        evidence_cutoff=_parse_date(payload.get("evidence_cutoff")),
        first_date=_parse_date(payload.get("first_date")),
        last_date=_parse_date(payload.get("last_date")),
        expected_symbol_count=expected,
        ready_symbol_count=ready,
        coverage_ratio=float(payload.get("coverage_ratio", _ratio(ready, expected))),
        not_yet_applicable_symbols=_clean_symbols(
            payload.get("not_yet_applicable_symbols", [])
        ),
        missing_symbols=_clean_symbols(payload.get("missing_symbols", [])),
        invalid_symbols=_clean_symbols(payload.get("invalid_symbols", [])),
        quarantined_symbols=_clean_symbols(payload.get("quarantined_symbols", [])),
        providers=_clean_symbols(payload.get("providers", [])),
        professional_source_ready=(
            bool(payload["professional_source_ready"])
            if "professional_source_ready" in payload
            else None
        ),
        research_only=bool(payload.get("research_only", True)),
        trade_ready=bool(payload.get("trade_ready", False)),
        details=dict(payload.get("details", {})),
    )


def _selected_pool_prices(
    spec: ComponentSpec,
    path: Path,
    payload: Mapping[str, Any],
) -> DataComponent:
    if payload.get("evidence_type") == PUBLICATION_EVIDENCE_TYPE:
        try:
            publication = load_selected_pool_price_publication_manifest(path)
        except SelectedPoolPricePublicationError as exc:
            raise ModelDataBundleError(str(exc)) from exc
        if dict(payload) != publication:
            raise ModelDataBundleError(f"provider publication manifest drift: {path}")
    records = [row for row in payload.get("records", []) if isinstance(row, dict)]
    failures = [row for row in payload.get("failures", []) if isinstance(row, dict)]
    expected = int(payload.get("candidate_count", payload.get("expected_candidate_count", 0)))
    if expected <= 0:
        expected = len(records)
    missing = _clean_symbols(
        [row.get("symbol") for row in failures] + list(payload.get("missing_symbols", []))
    )
    invalid = _clean_symbols(payload.get("invalid_symbols", []))
    quarantined = _clean_symbols(payload.get("quarantined_symbols", []))
    ready = max(0, expected - len(set(missing) | set(invalid) | set(quarantined)))
    promotion_eligible = bool(payload.get("promotion_eligible", False))
    status = "ready" if promotion_eligible and ready == expected else "blocked"
    selected = payload.get("selected_providers", {})
    providers = (
        _clean_symbols(selected.values()) if isinstance(selected, dict) else _clean_symbols([])
    )
    candidate_symbols = set(_clean_symbols(payload.get("candidate_symbols", [])))
    candidate_records = (
        [
            row
            for row in records
            if str(row.get("symbol", "")).strip().upper() in candidate_symbols
        ]
        if candidate_symbols
        else records
    )
    first_dates = [
        str(row.get("first_date", ""))
        for row in candidate_records
        if row.get("first_date")
    ]
    last_dates = [
        str(row.get("last_date", ""))
        for row in candidate_records
        if row.get("last_date")
    ]
    common_first_date = max(first_dates)[:10] if first_dates else None
    common_last_date = min(last_dates)[:10] if last_dates else None
    requested_cutoff = _parse_date(
        payload.get("evidence_cutoff")
        or payload.get("cutoff")
        or payload.get("requested_cutoff")
    )
    return DataComponent(
        component_id=spec.component_id,
        component_kind=spec.component_kind,
        status=status,
        market=str(spec.market or payload.get("market", "")).lower(),
        pool_id=str(payload.get("pool_id", payload.get("universe_id", ""))),
        manifest_path=str(path),
        manifest_sha256=_sha256(path),
        evidence_cutoff=common_last_date or requested_cutoff,
        first_date=common_first_date,
        last_date=common_last_date,
        expected_symbol_count=expected,
        ready_symbol_count=ready,
        coverage_ratio=_ratio(ready, expected),
        not_yet_applicable_symbols=tuple(),
        missing_symbols=missing,
        invalid_symbols=invalid,
        quarantined_symbols=quarantined,
        providers=providers,
        professional_source_ready=None,
        research_only=bool(payload.get("research_only", True)),
        trade_ready=bool(payload.get("trade_ready", False)),
        details={
            "source_status": payload.get("status"),
            "promotion_eligible": promotion_eligible,
            "promotion_blocker": payload.get("promotion_blocker"),
            "benchmark": payload.get("benchmark"),
            "provider_identity_sha256": payload.get("provider_identity_sha256"),
            "requested_cutoff": requested_cutoff,
            "candidate_observation_start": common_first_date,
            "candidate_observation_cutoff": common_last_date,
        },
    )


def _etf_reference_bundle(
    spec: ComponentSpec,
    path: Path,
    payload: Mapping[str, Any],
) -> DataComponent:
    symbols = _clean_symbols(payload.get("symbols", []))
    expected = len(symbols)
    ready_flag = bool(payload.get("strategy_data_ready", False))
    reconciliation = payload.get("reconciliation_status", {})
    quarantined = (
        _clean_symbols(
            symbol
            for symbol, status in reconciliation.items()
            if str(status).lower() == "quarantine"
        )
        if isinstance(reconciliation, dict)
        else tuple()
    )
    ready = expected if ready_flag and not quarantined else max(0, expected - len(quarantined))
    selected = payload.get("selected_providers", {})
    providers = _clean_symbols(selected.values()) if isinstance(selected, dict) else tuple()
    return DataComponent(
        component_id=spec.component_id,
        component_kind=spec.component_kind,
        status="ready" if ready_flag and ready == expected else "blocked",
        market=str(spec.market or "us").lower(),
        pool_id=str(payload.get("bundle_id", payload.get("contract_id", spec.component_id))),
        manifest_path=str(path),
        manifest_sha256=_sha256(path),
        evidence_cutoff=_parse_date(payload.get("evidence_cutoff") or payload.get("last_date")),
        first_date=_parse_date(payload.get("common_history_start")),
        last_date=_parse_date(payload.get("common_history_end") or payload.get("latest_date")),
        expected_symbol_count=expected,
        ready_symbol_count=ready,
        coverage_ratio=_ratio(ready, expected),
        not_yet_applicable_symbols=tuple(),
        missing_symbols=tuple(),
        invalid_symbols=tuple(),
        quarantined_symbols=quarantined,
        providers=providers,
        professional_source_ready=bool(payload.get("professional_source_ready", False)),
        research_only=bool(payload.get("research_only", True)),
        trade_ready=bool(payload.get("trade_ready", False)),
        details={
            "symbols": list(symbols),
            "reconciliation_status": dict(reconciliation)
            if isinstance(reconciliation, dict)
            else {},
            "strategy_data_ready": ready_flag,
        },
    )


def _generic_coverage(
    spec: ComponentSpec,
    path: Path,
    payload: Mapping[str, Any],
) -> DataComponent:
    expected = int(
        payload.get(
            "expected_symbol_count",
            payload.get("candidate_count", payload.get("total_symbols", 0)),
        )
    )
    ready = int(
        payload.get(
            "ready_symbol_count",
            payload.get("ready_candidate_count", payload.get("ready_symbols", 0)),
        )
    )
    if isinstance(payload.get("ready_symbols"), list):
        ready = len(payload["ready_symbols"])
    not_yet_applicable = _clean_symbols(payload.get("not_yet_applicable_symbols", []))
    missing = _clean_symbols(payload.get("missing_symbols", payload.get("missing_candidates", [])))
    invalid = _clean_symbols(payload.get("invalid_symbols", payload.get("invalid_candidates", [])))
    quarantined = _clean_symbols(payload.get("quarantined_symbols", []))
    if expected <= 0:
        expected = ready + len(
            set(not_yet_applicable) | set(missing) | set(invalid) | set(quarantined)
        )
    if ready <= 0 and expected > 0:
        ready = max(
            0,
            expected
            - len(set(not_yet_applicable) | set(missing) | set(invalid) | set(quarantined)),
        )
    declared_status = str(payload.get("status", payload.get("decision", ""))).lower()
    if declared_status in ALLOWED_STATUSES:
        status = declared_status
    elif ready == expected and expected > 0 and not invalid and not quarantined:
        status = "ready"
    elif ready > 0:
        status = "partial"
    else:
        status = "not_provided"
    providers_value = payload.get("providers", payload.get("source_providers", []))
    if isinstance(providers_value, dict):
        providers = _clean_symbols(providers_value.values())
    else:
        providers = _clean_symbols(providers_value)
    return DataComponent(
        component_id=spec.component_id,
        component_kind=spec.component_kind,
        status=status,
        market=str(spec.market or payload.get("market", "global")).lower(),
        pool_id=str(payload.get("pool_id", payload.get("universe_id", ""))),
        manifest_path=str(path),
        manifest_sha256=_sha256(path),
        evidence_cutoff=_parse_date(payload.get("evidence_cutoff") or payload.get("cutoff")),
        first_date=_parse_date(payload.get("first_date") or payload.get("first_available_event")),
        last_date=_parse_date(payload.get("last_date") or payload.get("latest_available_event")),
        expected_symbol_count=expected,
        ready_symbol_count=ready,
        coverage_ratio=float(payload.get("coverage_ratio", _ratio(ready, expected))),
        not_yet_applicable_symbols=not_yet_applicable,
        missing_symbols=missing,
        invalid_symbols=invalid,
        quarantined_symbols=quarantined,
        providers=providers,
        professional_source_ready=(
            bool(payload["professional_source_ready"])
            if "professional_source_ready" in payload
            else None
        ),
        research_only=bool(payload.get("research_only", True)),
        trade_ready=bool(payload.get("trade_ready", False)),
        details={
            "source_status": payload.get("status"),
            "decision": payload.get("decision"),
        },
    )


def normalize_component(spec: ComponentSpec) -> DataComponent:
    path = spec.manifest_path.resolve()
    payload = _load_mapping(path)
    direct = _direct_component(spec, path, payload)
    if direct is not None:
        component = direct
    elif spec.component_kind == "selected_pool_prices":
        component = _selected_pool_prices(spec, path, payload)
    elif spec.component_kind == "etf_reference_bundle":
        component = _etf_reference_bundle(spec, path, payload)
    else:
        component = _generic_coverage(spec, path, payload)
    if component.status not in ALLOWED_STATUSES:
        raise ModelDataBundleError(f"unsupported normalized status: {component.status}")
    if component.ready_symbol_count > component.expected_symbol_count:
        raise ModelDataBundleError(
            f"ready symbols exceed expected symbols: {component.component_id}"
        )
    if component.trade_ready:
        raise ModelDataBundleError(
            f"data component cannot declare trade_ready=true: {component.component_id}"
        )
    return component


def _load_candidate_symbols(profile: Mapping[str, Any], root: Path) -> tuple[str, ...]:
    explicit = profile.get("candidate_symbols")
    if isinstance(explicit, list):
        return _clean_symbols(explicit)
    pool_spec = str(profile.get("candidate_pool_spec", "")).strip()
    if not pool_spec:
        raise ModelDataBundleError("training profile requires candidate symbols or pool spec")
    path = root / pool_spec
    payload = _load_mapping(path)
    symbols = payload.get("symbols", [])
    if not isinstance(symbols, list):
        raise ModelDataBundleError(f"candidate pool symbols must be a list: {path}")
    normalized = _clean_symbols(symbols)
    expected = int(payload.get("candidate_count", len(normalized)))
    if len(normalized) != expected:
        raise ModelDataBundleError(f"candidate pool count mismatch: {path}")
    return normalized


def evaluate_training_profile(
    profile_id: str,
    profile: Mapping[str, Any],
    components: Mapping[str, DataComponent],
    *,
    root: Path,
    evidence_cutoff: str,
) -> dict[str, Any]:
    candidate_symbols = _load_candidate_symbols(profile, root)
    references = _clean_symbols(profile.get("references", []))
    failed_gates: list[str] = []
    overlap = sorted(set(candidate_symbols) & set(references))
    if overlap:
        failed_gates.append(f"candidate_reference_overlap:{','.join(overlap)}")

    candidate_pool_id = str(profile.get("candidate_pool_id", "")).strip()
    requirements: list[dict[str, Any]] = []
    raw_requirements = profile.get("required_components", [])
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise ModelDataBundleError(f"profile has no required components: {profile_id}")
    for raw in raw_requirements:
        if not isinstance(raw, dict):
            raise ModelDataBundleError(f"invalid component requirement: {profile_id}")
        component_id = str(raw.get("component_id", "")).strip()
        accepted = {
            str(value).strip().lower()
            for value in raw.get("accepted_statuses", ["ready"])
        }
        minimum = float(raw.get("minimum_coverage_ratio", 1.0))
        allow_not_yet_applicable = bool(raw.get("allow_not_yet_applicable", False))
        component = components.get(component_id)
        gate_status = "passed"
        gate_reasons: list[str] = []
        applicable_coverage_ratio: float | None = None
        coverage_basis = "all_symbols"
        if component is None:
            gate_status = "failed"
            gate_reasons.append("required_component_missing")
        else:
            if component.status not in accepted:
                gate_status = "failed"
                gate_reasons.append(f"status={component.status} not in {sorted(accepted)}")

            coverage_for_gate = component.coverage_ratio
            if allow_not_yet_applicable:
                coverage_basis = "applicable_symbols"
                not_yet_applicable = set(component.not_yet_applicable_symbols)
                bad_symbols = (
                    set(component.missing_symbols)
                    | set(component.invalid_symbols)
                    | set(component.quarantined_symbols)
                )
                if bad_symbols:
                    gate_status = "failed"
                    gate_reasons.append(
                        "lifecycle_allowance_requires_no_missing_invalid_or_quarantined"
                    )
                if not_yet_applicable & bad_symbols:
                    gate_status = "failed"
                    gate_reasons.append("lifecycle_status_overlap")
                applicable_expected = component.expected_symbol_count - len(
                    not_yet_applicable
                )
                if applicable_expected < 0 or component.ready_symbol_count > applicable_expected:
                    gate_status = "failed"
                    gate_reasons.append("invalid_lifecycle_partition")
                    applicable_coverage_ratio = 0.0
                else:
                    applicable_coverage_ratio = _ratio(
                        component.ready_symbol_count,
                        applicable_expected,
                    )
                coverage_for_gate = applicable_coverage_ratio

            if coverage_for_gate + 1e-12 < minimum:
                gate_status = "failed"
                gate_reasons.append(
                    f"coverage={coverage_for_gate:.6f} below {minimum:.6f}"
                )
            if component.evidence_cutoff and component.evidence_cutoff > evidence_cutoff:
                gate_status = "failed"
                gate_reasons.append(
                    f"component cutoff {component.evidence_cutoff} exceeds {evidence_cutoff}"
                )
            if (
                component.pool_id
                and component.component_kind != "etf_reference_bundle"
                and candidate_pool_id
                and component.pool_id != candidate_pool_id
            ):
                gate_status = "failed"
                gate_reasons.append(f"pool_id={component.pool_id} expected {candidate_pool_id}")
            if component.trade_ready:
                gate_status = "failed"
                gate_reasons.append("component illegally declares trade_ready=true")
        if gate_status == "failed":
            failed_gates.append(f"component:{component_id}:{'|'.join(gate_reasons)}")
        requirements.append(
            {
                "component_id": component_id,
                "accepted_statuses": sorted(accepted),
                "minimum_coverage_ratio": minimum,
                "allow_not_yet_applicable": allow_not_yet_applicable,
                "coverage_basis": coverage_basis,
                "applicable_coverage_ratio": applicable_coverage_ratio,
                "gate_status": gate_status,
                "gate_reasons": gate_reasons,
                "observed": component.to_dict() if component else None,
            }
        )

    return {
        "profile_id": profile_id,
        "market": str(profile.get("market", "")).lower(),
        "candidate_pool_id": candidate_pool_id,
        "candidate_count": len(candidate_symbols),
        "references": list(references),
        "required_components": requirements,
        "status": "ready" if not failed_gates else "blocked",
        "failed_gates": failed_gates,
        "research_only": True,
        "trade_ready": False,
    }


def build_model_data_bundle(
    *,
    root: Path,
    contract_path: Path,
    component_specs: Sequence[ComponentSpec],
    output_root: Path,
    evidence_cutoff: str,
    frontend_data_dir: Path | None = None,
) -> dict[str, Any]:
    normalized_root = root.resolve()
    output = output_root.resolve()
    resolved_contract_path = contract_path.resolve()
    contract = _load_mapping(resolved_contract_path)
    cutoff = _parse_date(evidence_cutoff)
    if cutoff is None:
        raise ModelDataBundleError("evidence_cutoff is required")

    components_list = [normalize_component(spec) for spec in component_specs]
    portable_components: list[DataComponent] = []
    for component in components_list:
        manifest_path = Path(component.manifest_path)
        try:
            portable_path = manifest_path.relative_to(output).as_posix()
        except ValueError:
            portable_components.append(component)
        else:
            portable_components.append(
                replace(component, manifest_path=portable_path)
            )
    components_list = portable_components
    component_ids = [component.component_id for component in components_list]
    if len(component_ids) != len(set(component_ids)):
        raise ModelDataBundleError("component IDs must be unique")
    components = {component.component_id: component for component in components_list}

    profiles_payload = contract.get("profiles", {})
    if not isinstance(profiles_payload, dict):
        raise ModelDataBundleError("contract profiles must be a mapping")
    profile_results = [
        evaluate_training_profile(
            str(profile_id),
            profile,
            components,
            root=normalized_root,
            evidence_cutoff=cutoff,
        )
        for profile_id, profile in sorted(profiles_payload.items())
        if isinstance(profile, dict)
    ]

    contract_hash = _sha256(resolved_contract_path)
    try:
        portable_contract_path = resolved_contract_path.relative_to(
            normalized_root
        ).as_posix()
    except ValueError:
        portable_contract_path = str(resolved_contract_path)
    component_seed = "\n".join(
        f"{component.component_id}:{component.manifest_sha256}"
        for component in sorted(components_list, key=lambda item: item.component_id)
    )
    profile_seed = json.dumps(profile_results, sort_keys=True, separators=(",", ":"))
    bundle_id = hashlib.sha256(
        f"{contract_hash}\n{cutoff}\n{component_seed}\n{profile_seed}".encode("utf-8")
    ).hexdigest()

    output.mkdir(parents=True, exist_ok=True)
    component_payload = [
        component.to_dict()
        for component in sorted(components_list, key=lambda item: item.component_id)
    ]
    summary = {
        "component_count": len(component_payload),
        "ready_component_count": sum(row["status"] == "ready" for row in component_payload),
        "partial_component_count": sum(row["status"] == "partial" for row in component_payload),
        "blocked_component_count": sum(row["status"] == "blocked" for row in component_payload),
        "ready_training_profiles": [
            row["profile_id"] for row in profile_results if row["status"] == "ready"
        ],
        "blocked_training_profiles": [
            row["profile_id"] for row in profile_results if row["status"] == "blocked"
        ],
    }
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest: dict[str, Any] = {
        "schema_version": str(contract.get("schema_version", "1.0")),
        "contract_id": str(contract.get("contract_id", "model_data_bundle_v1")),
        "bundle_id": bundle_id,
        "built_at": built_at,
        "evidence_cutoff": cutoff,
        "contract_path": portable_contract_path,
        "contract_sha256": contract_hash,
        "research_only": True,
        "trade_ready": False,
        "summary": summary,
        "components": component_payload,
        "training_profiles": profile_results,
    }

    components_path = output / "data-components.json"
    profiles_path = output / "training-profiles.json"
    readiness_path = output / "model-data-readiness.json"
    _write_json(components_path, component_payload)
    _write_json(profiles_path, profile_results)
    _write_json(
        readiness_path,
        {
            "schema_version": manifest["schema_version"],
            "bundle_id": bundle_id,
            "built_at": built_at,
            "evidence_cutoff": cutoff,
            "research_only": True,
            "trade_ready": False,
            "summary": summary,
        },
    )
    manifest["frontend_indexes"] = {
        "model_data_readiness": {
            "path": readiness_path.name,
            "sha256": _sha256(readiness_path),
        },
        "data_components": {
            "path": components_path.name,
            "sha256": _sha256(components_path),
        },
        "training_profiles": {
            "path": profiles_path.name,
            "sha256": _sha256(profiles_path),
        },
    }
    manifest_path = output / "model-data-bundle.json"
    _write_json(manifest_path, manifest)

    if frontend_data_dir is not None:
        destination = frontend_data_dir.resolve()
        _write_json(
            destination / "model-data-readiness.json",
            json.loads(readiness_path.read_text(encoding="utf-8")),
        )
        _write_json(destination / "data-components.json", component_payload)
        _write_json(destination / "training-profiles.json", profile_results)

    return manifest


def verify_model_data_bundle(output_root: Path) -> list[str]:
    root = output_root.resolve()
    manifest_path = root / "model-data-bundle.json"
    if not manifest_path.is_file():
        raise ModelDataBundleError("model-data-bundle.json is missing")
    manifest = _load_mapping(manifest_path)
    verified: list[str] = []
    indexes = manifest.get("frontend_indexes", {})
    if not isinstance(indexes, dict):
        raise ModelDataBundleError("frontend_indexes must be a mapping")
    for record in indexes.values():
        if not isinstance(record, dict):
            raise ModelDataBundleError("invalid frontend index record")
        path = root / str(record.get("path", ""))
        digest = str(record.get("sha256", "")).lower()
        if not path.is_file() or not _SHA256.fullmatch(digest):
            raise ModelDataBundleError(f"invalid frontend index: {path}")
        if _sha256(path) != digest:
            raise ModelDataBundleError(f"frontend index hash mismatch: {path}")
        verified.append(path.name)
    for component in manifest.get("components", []):
        if not isinstance(component, dict):
            raise ModelDataBundleError("invalid component record")
        path = Path(str(component.get("manifest_path", "")))
        if not path.is_absolute():
            path = root / path
        digest = str(component.get("manifest_sha256", "")).lower()
        if not path.is_file() or _sha256(path) != digest:
            raise ModelDataBundleError(
                f"source component hash mismatch: {component.get('component_id')}"
            )
    return sorted(verified)
