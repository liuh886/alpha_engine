"""Record and verify hash-bound independent operating review declarations.

A declaration is the Owner-controlled assertion that one captured operating
observation was independently reviewed. It never asserts acceptance by itself:
``build_acceptance_report`` still requires 20 on-time eligible sessions per
market. The store is append-only and every bound file is re-hashed here so a
later edit cannot be mistaken for the reviewed evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DECLARATION_SCHEMA_VERSION = "operating_review_declaration_v1"
VERIFICATION_SCHEMA_VERSION = "operating_review_verification_v1"
RESEARCH_ONLY = True
TRADE_READY = False
BINDING_FIELDS = ("final_actions_metadata", "operations_snapshot", "operating_inputs", "decision_delivery_evidence")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _validate_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"invalid sha256 for {label}")
    return value


def iter_bindings(value: Any) -> Iterator[dict[str, Any]]:
    """Yield every ``{path, sha256}`` binding nested in an evidence manifest."""
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and "sha256" in value:
            yield value
            return
        for child in value.values():
            yield from iter_bindings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_bindings(child)


def verify_declaration_bindings(review: dict[str, Any], root: Path, *, identity: str = "") -> int:
    """Fail closed unless every bound file still hashes to its recorded value."""
    verified = 0
    for binding in iter_bindings(review):
        label = f"{identity}:{binding['path']}" if identity else str(binding["path"])
        expected = _validate_sha256(binding["sha256"], label=label)
        path = (root / binding["path"]).resolve()
        if not path.is_file():
            raise ValueError(f"declaration evidence is missing: {label}")
        if sha256_file(path) != expected:
            raise ValueError(f"declaration evidence hash mismatch: {label}")
        verified += 1
    return verified


def declaration_content(declaration: dict[str, Any]) -> dict[str, Any]:
    """Return the content compared for append-only idempotency.

    ``reviewed_at`` is review metadata and ``declaration_digest`` covers the
    whole declaration; neither may make an identical re-record look different.
    """
    return {key: value for key, value in declaration.items() if key not in {"reviewed_at", "declaration_digest"}}


def compute_declaration_digest(declaration: dict[str, Any]) -> str:
    content = {key: value for key, value in declaration.items() if key != "declaration_digest"}
    return "sha256:" + sha256_bytes(canonical_json(content).encode("utf-8"))


def _normalise_reviewed_at(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("reviewed_at must be an ISO 8601 timestamp") from exc
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _relative_path(path: Path, root: Path) -> str:
    root = root.resolve()
    path = path.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return Path(os.path.relpath(path, root)).as_posix()
        except ValueError as exc:
            raise ValueError("bound evidence must share a drive with the declarations store") from exc


def _rebase_and_verify(value: Any, *, evidence_root: Path, store_root: Path, identity: str) -> Any:
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and "sha256" in value:
            label = f"{identity}:{value['path']}"
            expected = _validate_sha256(value["sha256"], label=label)
            path = (evidence_root / value["path"]).resolve()
            if not path.is_file():
                raise ValueError(f"bound evidence is missing: {label}")
            if sha256_file(path) != expected:
                raise ValueError(f"bound evidence hash mismatch: {label}")
            return {**value, "path": _relative_path(path, store_root)}
        return {key: _rebase_and_verify(child, evidence_root=evidence_root, store_root=store_root, identity=identity) for key, child in value.items()}
    if isinstance(value, list):
        return [_rebase_and_verify(child, evidence_root=evidence_root, store_root=store_root, identity=identity) for child in value]
    return value


def _require_evidence(evidence: dict[str, Any], identity: str, observation_sha256: str) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError(f"bound evidence must be an object: {identity}")
    missing = [key for key in ("final_actions_metadata", "operations_snapshot", "decision_delivery_evidence") if key not in evidence]
    if missing:
        raise ValueError(f"declaration is missing bound evidence {missing}: {identity}")
    for key in ("final_actions_metadata", "operations_snapshot"):
        if not isinstance(evidence[key], dict) or not isinstance(evidence[key].get("path"), str):
            raise ValueError(f"declaration {key} must be a bound file: {identity}")
    decision_evidence = evidence.get("decision_delivery_evidence")
    if not isinstance(decision_evidence, list) or not decision_evidence:
        raise ValueError(f"declaration decision_delivery_evidence must be a non-empty list: {identity}")
    recorded = evidence.get("observation_sha256")
    if recorded is not None and recorded != observation_sha256:
        raise ValueError(f"declaration observation hash does not match the observed artifact: {identity}")
    return {key: evidence[key] for key in BINDING_FIELDS if key in evidence}


def _read_observation(path: Path) -> tuple[dict[str, Any], str, str]:
    if not path.is_file():
        raise ValueError(f"operating observation is missing: {path}")
    raw = path.read_bytes()
    try:
        row = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"operating observation is not valid JSON: {path}") from exc
    if not isinstance(row, dict) or row.get("schema_version") != "operating_observation_v1":
        raise ValueError(f"invalid operating observation schema: {path}")
    if row.get("research_only") is not True or row.get("trade_ready") is not False:
        raise ValueError(f"operating observation violates the research boundary: {path}")
    if "run_id" not in row or "run_attempt" not in row:
        raise ValueError(f"operating observation lacks run identity: {path}")
    return row, sha256_bytes(raw), f"{row['run_id']}:{row['run_attempt']}"


def _validate_review_assertions(reviewed_by: Any, manual_interventions: Any, cadence_and_freshness_verified: Any) -> tuple[str, int]:
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError("reviewed_by must be a non-empty reviewer name")
    if type(manual_interventions) is not int or manual_interventions < 0:
        raise ValueError("manual_interventions must be an explicit non-negative integer")
    if cadence_and_freshness_verified is not True:
        raise ValueError("cadence_and_freshness_verified must be explicitly asserted")
    return reviewed_by.strip(), manual_interventions


def load_declarations(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"declarations store is not valid JSON: {path}") from exc
    if not isinstance(store, dict):
        raise ValueError(f"declarations store must be an object keyed by run identity: {path}")
    return store


def write_declarations(path: Path, store: dict[str, Any]) -> None:
    """Write deterministically through a same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".declarations-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def build_declaration(
    *,
    observation_path: Path,
    evidence: dict[str, Any],
    evidence_root: Path,
    declarations_path: Path,
    reviewed_by: Any,
    manual_interventions: Any,
    cadence_and_freshness_verified: Any,
    reviewed_at: datetime | str | None = None,
    run_id: Any = None,
    run_attempt: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Assemble one declaration, verifying the observation and every binding."""
    reviewer, interventions = _validate_review_assertions(reviewed_by, manual_interventions, cadence_and_freshness_verified)
    observation_path = observation_path.resolve()
    row, observation_sha256, identity = _read_observation(observation_path)
    if run_id is not None or run_attempt is not None:
        if str(run_id) != str(row["run_id"]) or str(run_attempt) != str(row["run_attempt"]):
            raise ValueError(f"requested run identity does not match the observation: {run_id}:{run_attempt} != {identity}")
    bound = _require_evidence(evidence, identity, observation_sha256)
    store_root = declarations_path.resolve().parent
    rebased = {key: _rebase_and_verify(value, evidence_root=evidence_root.resolve(), store_root=store_root, identity=identity) for key, value in bound.items()}
    declaration: dict[str, Any] = {
        "schema_version": DECLARATION_SCHEMA_VERSION,
        "observation": {"path": _relative_path(observation_path, store_root), "sha256": observation_sha256},
        "observation_sha256": observation_sha256,
        "manual_interventions": interventions,
        "reviewed_by": reviewer,
        "reviewed_at": _normalise_reviewed_at(reviewed_at),
        "cadence_and_freshness_verified": True,
        **rebased,
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
    declaration["declaration_digest"] = compute_declaration_digest(declaration)
    return identity, declaration


def record_declaration(
    *,
    observation_path: Path,
    evidence: dict[str, Any],
    evidence_root: Path,
    declarations_path: Path,
    reviewed_by: Any,
    manual_interventions: Any,
    cadence_and_freshness_verified: Any,
    reviewed_at: datetime | str | None = None,
    run_id: Any = None,
    run_attempt: Any = None,
) -> dict[str, Any]:
    """Append one declaration, or confirm that an identical one already exists."""
    identity, declaration = build_declaration(
        observation_path=observation_path,
        evidence=evidence,
        evidence_root=evidence_root,
        declarations_path=declarations_path,
        reviewed_by=reviewed_by,
        manual_interventions=manual_interventions,
        cadence_and_freshness_verified=cadence_and_freshness_verified,
        reviewed_at=reviewed_at,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    store = load_declarations(declarations_path)
    existing = store.get(identity)
    if existing is not None:
        if existing.get("declaration_digest") != compute_declaration_digest(existing):
            raise ValueError(f"existing declaration digest is invalid: {identity}")
        if canonical_json(declaration_content(existing)) == canonical_json(declaration_content(declaration)):
            return {"status": "unchanged", "identity": identity, "declaration": existing}
        raise ValueError(f"conflicting declaration already exists for {identity}; the store is append-only")
    store[identity] = declaration
    write_declarations(declarations_path, store)
    return {"status": "recorded", "identity": identity, "declaration": declaration}


def verify_declarations(declarations_path: Path) -> dict[str, Any]:
    """Re-verify every declaration against the observation and bound files."""
    store = load_declarations(declarations_path)
    if not store:
        raise ValueError(f"no review declarations found: {declarations_path}")
    root = declarations_path.resolve().parent
    verified_bindings = 0
    for identity, declaration in sorted(store.items()):
        if not isinstance(declaration, dict):
            raise ValueError(f"declaration must be an object: {identity}")
        if declaration.get("schema_version") != DECLARATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported declaration schema: {identity}")
        _validate_review_assertions(declaration.get("reviewed_by"), declaration.get("manual_interventions"), declaration.get("cadence_and_freshness_verified"))
        if declaration.get("research_only") is not True or declaration.get("trade_ready") is not False:
            raise ValueError(f"declaration violates the research boundary: {identity}")
        if declaration.get("declaration_digest") != compute_declaration_digest(declaration):
            raise ValueError(f"declaration digest mismatch: {identity}")
        observation = declaration.get("observation")
        if not isinstance(observation, dict) or not isinstance(observation.get("path"), str):
            raise ValueError(f"declaration lacks an observation binding: {identity}")
        observation_path = (root / observation["path"]).resolve()
        row, observation_sha256, observed_identity = _read_observation(observation_path)
        if observed_identity != identity:
            raise ValueError(f"declaration observation identity mismatch: {identity} != {observed_identity}")
        expected = _validate_sha256(observation.get("sha256"), label=f"{identity}:observation")
        if expected != observation_sha256 or declaration.get("observation_sha256") != observation_sha256:
            raise ValueError(f"declaration observation hash mismatch: {identity}")
        if not declaration.get("decision_delivery_evidence"):
            raise ValueError(f"declaration decision_delivery_evidence is empty: {identity}")
        verified_bindings += verify_declaration_bindings(declaration, root, identity=identity)
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "declaration_count": len(store),
        "identities": sorted(store),
        "verified_bindings": verified_bindings,
        "research_only": RESEARCH_ONLY,
        "trade_ready": TRADE_READY,
    }
