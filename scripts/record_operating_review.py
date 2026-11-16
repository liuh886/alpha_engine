#!/usr/bin/env python3
"""Record or verify hash-bound A1 operating review declarations.

``record`` is Owner-only evidence capture: it never signs or accepts anything
on the Owner's behalf. ``verify`` re-hashes every declaration and fails closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.artifacts.operating_review_declarations import (  # noqa: E402
    record_declaration,
    sha256_file,
    verify_declarations,
)


def _observation_path(args: argparse.Namespace) -> Path:
    if args.observation:
        return args.observation
    if args.run_id is None or args.run_attempt is None or args.observation_root is None:
        raise ValueError("provide --observation or --run-id/--run-attempt with --observation-root")
    return args.observation_root / "operating-observation.json"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"evidence file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"evidence file is not valid JSON: {path}") from exc


def _select_draft(payload: Any, identity: str | None, observation_sha256: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("review draft must be an object")
    if identity and identity in payload:
        review = payload[identity]
    elif any(isinstance(value, dict) and value.get("observation_sha256") == observation_sha256 for value in payload.values()):
        review = next(value for value in payload.values() if isinstance(value, dict) and value.get("observation_sha256") == observation_sha256)
    elif any(key in payload for key in ("final_actions_metadata", "observation_sha256", "decision_delivery_evidence")):
        review = payload
    elif len(payload) == 1:
        review = next(iter(payload.values()))
    else:
        raise ValueError("review draft does not contain the requested observation identity")
    if not isinstance(review, dict):
        raise ValueError("review draft entry must be an object")
    return review


def _bind_paths(value: Any, base: Path) -> Any:
    """Normalise marked ``{"path": ...}`` entries and compute missing hashes."""
    if isinstance(value, dict):
        if isinstance(value.get("path"), str):
            path = (base / value["path"]).resolve()
            sha256 = value.get("sha256")
            if sha256 is None:
                if not path.is_file():
                    raise ValueError(f"bound evidence is missing: {path}")
                sha256 = sha256_file(path)
            return {**value, "path": str(path), "sha256": sha256}
        return {key: _bind_paths(child, base) for key, child in value.items()}
    if isinstance(value, list):
        return [_bind_paths(child, base) for child in value]
    return value


def _explicit_evidence(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if args.final_actions_metadata is None or args.operations_snapshot is None or args.decision_delivery_evidence is None:
        raise ValueError("provide --draft, or --final-actions-metadata, --operations-snapshot and --decision-delivery-evidence")
    base = Path.cwd()

    def bound(path: Path) -> dict[str, str]:
        resolved = path.resolve()
        if not resolved.is_file():
            raise ValueError(f"bound evidence is missing: {path}")
        return {"path": str(resolved), "sha256": sha256_file(resolved)}

    decision_payload = _load_json(args.decision_delivery_evidence)
    if isinstance(decision_payload, dict) and "decision_delivery_evidence" in decision_payload:
        decision_payload = decision_payload["decision_delivery_evidence"]
    if not isinstance(decision_payload, list) or not decision_payload:
        raise ValueError("decision delivery evidence must be a non-empty list")
    evidence: dict[str, Any] = {
        "final_actions_metadata": bound(args.final_actions_metadata),
        "operations_snapshot": bound(args.operations_snapshot),
        "decision_delivery_evidence": _bind_paths(decision_payload, args.decision_delivery_evidence.parent),
    }
    if args.operating_inputs is not None:
        inputs = _load_json(args.operating_inputs)
        if not isinstance(inputs, dict):
            raise ValueError("operating inputs must be an object")
        evidence["operating_inputs"] = _bind_paths(inputs, args.operating_inputs.parent)
    return evidence, base


def _record(args: argparse.Namespace) -> dict[str, Any]:
    observation = _observation_path(args)
    hint = f"{args.run_id}:{args.run_attempt}" if args.run_id is not None and args.run_attempt is not None else None
    if args.draft is not None:
        observation_sha256 = sha256_file(observation)
        evidence, evidence_root = _select_draft(_load_json(args.draft), hint, observation_sha256), args.draft.parent
    else:
        evidence, evidence_root = _explicit_evidence(args)
    result = record_declaration(
        observation_path=observation,
        evidence=evidence,
        evidence_root=evidence_root,
        declarations_path=args.declarations,
        reviewed_by=args.reviewed_by,
        manual_interventions=args.manual_interventions,
        cadence_and_freshness_verified=args.cadence_and_freshness_verified,
        reviewed_at=args.reviewed_at,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )
    return {
        "status": result["status"],
        "identity": result["identity"],
        "declarations": str(args.declarations.resolve()),
        "declaration_digest": result["declaration"]["declaration_digest"],
        "research_only": True,
        "trade_ready": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record", help="Append one Owner review declaration after verifying all bindings.")
    record.add_argument("--declarations", type=Path, required=True)
    identity = record.add_mutually_exclusive_group(required=True)
    identity.add_argument("--observation", type=Path)
    identity.add_argument("--run-id", help="Requires --run-attempt and --observation-root.")
    record.add_argument("--run-attempt")
    record.add_argument("--observation-root", type=Path)
    record.add_argument("--draft", type=Path, help="Bound evidence manifest from the existing review draft.")
    record.add_argument("--final-actions-metadata", type=Path)
    record.add_argument("--operations-snapshot", type=Path)
    record.add_argument("--operating-inputs", type=Path)
    record.add_argument("--decision-delivery-evidence", type=Path)
    record.add_argument("--manual-interventions", type=int, required=True)
    record.add_argument("--reviewed-by", required=True)
    record.add_argument("--cadence-and-freshness-verified", action="store_true")
    record.add_argument("--reviewed-at", help="ISO 8601 review time; defaults to now in UTC.")

    verify = commands.add_parser("verify", help="Re-verify every declaration against current files.")
    verify.add_argument("--declarations", type=Path, required=True)
    verify.add_argument("--output", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            payload = _record(args)
        else:
            payload = verify_declarations(args.declarations)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
