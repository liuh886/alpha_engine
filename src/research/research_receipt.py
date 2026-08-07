"""Finalize Alpha Research Loop receipts with immutable research lineage.

Candidate runners own execution. This module owns cross-runner receipt lineage so
provider/model adapters do not each reinvent factor identity bookkeeping.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.research.factor_library import load_factor_library, select_factor_groups


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _resolve_repo_file(raw: str, *, spec_path: Path) -> Path:
    candidates = (spec_path.parent / raw, PROJECT_ROOT / raw)
    root = PROJECT_ROOT.resolve()
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"research lineage path escapes repository root: {raw}") from exc
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(raw)


def build_factor_lineage(spec_path: str | Path) -> dict[str, Any] | None:
    """Return exact factor-library lineage declared by one research mission.

    Missions without a structured ``factor_library`` return ``None``. Allocation
    runners can attach their deterministic rule-input evidence separately; the
    absence of a Qlib factor library is not represented as an invented factor set.
    """

    path = Path(spec_path).resolve()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("research experiment spec must be a mapping")

    factor_cfg = payload.get("factor_library")
    if factor_cfg is None:
        return None
    if not isinstance(factor_cfg, dict):
        raise ValueError("factor_library must be a mapping")
    source = str(factor_cfg.get("source", "")).strip()
    if not source:
        raise ValueError("factor_library.source must be non-empty")

    library_path = _resolve_repo_file(source, spec_path=path)
    library = load_factor_library(library_path)

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError(
            "research mission with factor_library must declare candidate factor_groups"
        )

    candidate_factors: dict[str, list[str]] = {}
    definitions: dict[str, dict[str, Any]] = {}
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            raise ValueError("candidate entries must be mappings")
        candidate_id = str(raw_candidate.get("candidate_id", "")).strip()
        if not candidate_id:
            raise ValueError("candidate_id must be non-empty")
        groups = [str(value) for value in raw_candidate.get("factor_groups", [])]
        if not groups:
            raise ValueError(f"candidate {candidate_id} must declare factor_groups")

        selected = select_factor_groups(library, groups)
        ids: list[str] = []
        seen: set[str] = set()
        for group in selected:
            for factor in group.factors:
                if factor.id in seen:
                    continue
                seen.add(factor.id)
                ids.append(factor.id)
                definition = factor.to_dict()
                definitions[factor.id] = {
                    **definition,
                    "definition_sha256": _canonical_sha256(definition),
                }
        candidate_factors[candidate_id] = ids

    return {
        "schema_version": "1.0",
        "source": source,
        "source_sha256": _sha256_bytes(library_path.read_bytes()),
        "candidate_factor_ids": candidate_factors,
        "factor_definitions": [definitions[key] for key in sorted(definitions)],
    }


def finalize_research_receipt(
    spec_path: str | Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Attach cross-runner immutable lineage to a research receipt."""

    result = dict(receipt)
    factor_lineage = build_factor_lineage(spec_path)
    if factor_lineage is not None:
        result["factor_lineage"] = factor_lineage
    return result


def write_research_receipt(
    spec_path: str | Path,
    receipt: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Finalize and persist the canonical receipt for one mission run."""

    final = finalize_research_receipt(spec_path, receipt)
    if output_dir is None:
        experiment_id = str(final.get("experiment_id", "")).strip()
        if not experiment_id:
            raise ValueError("research receipt missing experiment_id")
        target = PROJECT_ROOT / "artifacts" / "research_experiments" / experiment_id
    else:
        target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    path = target / "research_receipt.json"
    path.write_text(
        json.dumps(final, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return final
