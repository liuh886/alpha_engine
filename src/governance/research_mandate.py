"""Composed research mandates: one hash-bound artifact per research mission.

A mandate bundles the governed inputs a mission consumes (candidate pool,
selected-pool governance, reference instruments) plus cadence, cost
schedule and the non-negotiable research boundary into a single identity.
Experiments, trainings and the console consume the mission by ``mandate_id``
instead of reassembling five separate files each time.

Authoring: write the YAML with ``sha256`` fields set to the current bytes of
each referenced file (``hashlib.sha256(path.read_bytes()).hexdigest()``).
Loading fails closed when any binding drifts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml

from src.common.runtime_settings import PROJECT_ROOT

SCHEMA_VERSION = "1.0"
MARKETS = {"us", "cn", "hk"}
CADENCES = {"daily", "weekly", "biweekly", "monthly"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
DEFAULT_MANDATE_PATH = Path("configs/mandates/cn_research_mandate_v1.yaml")

_BOUNDARIES = {
    "research_only": True,
    "trade_ready": False,
    "automatic_promotion": False,
}


class ResearchMandateError(ValueError):
    """Raised when a mandate document or its bindings are not authoritative."""


def _required_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchMandateError(f"{label} must be a non-empty string")
    return value.strip()


def _slug(value: object, *, label: str) -> str:
    text = _required_string(value, label=label)
    if not SLUG.fullmatch(text):
        raise ResearchMandateError(f"invalid {label}: {text!r}")
    return text


def _relative_path(value: object, *, label: str) -> PurePosixPath:
    text = _required_string(value, label=label).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ResearchMandateError(f"unsafe {label}: {text!r}")
    return path


def expected_sha256(relative: str | PurePosixPath) -> str:
    path = PROJECT_ROOT / relative
    if not path.is_file():
        raise ResearchMandateError(f"mandate-referenced file is missing: {relative}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class MandateBinding:
    role: str
    ref: str
    sha256: str


@dataclass(frozen=True)
class ResearchMandate:
    mandate_id: str
    display_name: str
    market: str
    purpose: str
    benchmark_symbol: str
    rebalance_cadence: str
    base_cost_bps: float
    stress_cost_bps: float
    bindings: tuple[MandateBinding, ...]
    source_path: str


def _binding(raw: Mapping[str, Any], *, label: str) -> MandateBinding:
    if not isinstance(raw, Mapping):
        raise ResearchMandateError(f"{label} must be a mapping")
    ref = _relative_path(raw.get("ref"), label=f"{label}.ref")
    declared = _required_string(raw.get("sha256"), label=f"{label}.sha256")
    actual = expected_sha256(ref)
    if actual != declared:
        raise ResearchMandateError(
            f"{label} binding drifted for {ref}: declared={declared} actual={actual}"
        )
    return MandateBinding(
        role=_required_string(raw.get("role"), label=f"{label}.role"),
        ref=ref.as_posix(),
        sha256=actual,
    )


def load_research_mandate(path: str | Path = DEFAULT_MANDATE_PATH) -> ResearchMandate:
    mandate_path = PROJECT_ROOT / path
    if not mandate_path.is_file():
        raise ResearchMandateError(f"mandate file is missing: {path}")
    payload = yaml.safe_load(mandate_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ResearchMandateError("mandate root must be a mapping")

    schema_version = _required_string(payload.get("schema_version"), label="schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ResearchMandateError(f"unsupported mandate schema_version: {schema_version}")

    market = _required_string(payload.get("market"), label="market")
    if market not in MARKETS:
        raise ResearchMandateError(f"unsupported mandate market: {market}")

    boundaries = payload.get("evidence_boundaries")
    if not isinstance(boundaries, Mapping):
        raise ResearchMandateError("evidence_boundaries must be a mapping")
    for key, required in _BOUNDARIES.items():
        if boundaries.get(key) is not required:
            raise ResearchMandateError(
                f"evidence_boundaries.{key} must be {required!r}"
            )

    costs = payload.get("cost_schedule_bps")
    if not isinstance(costs, Mapping):
        raise ResearchMandateError("cost_schedule_bps must be a mapping")
    base_bps = float(costs.get("base", 0.0))
    stress_bps = float(costs.get("stress", 0.0))
    if base_bps <= 0.0 or stress_bps < base_bps:
        raise ResearchMandateError("cost_schedule_bps requires stress >= base > 0")

    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, Mapping) or not raw_bindings:
        raise ResearchMandateError("bindings must be a non-empty mapping")
    bindings = tuple(
        _binding(raw_bindings[key], label=f"bindings.{key}") for key in sorted(raw_bindings)
    )

    cadence = payload.get("rebalance_cadence")
    if cadence not in CADENCES:
        raise ResearchMandateError(f"unsupported rebalance_cadence: {cadence!r}")

    return ResearchMandate(
        mandate_id=_slug(payload.get("mandate_id"), label="mandate_id"),
        display_name=_required_string(payload.get("display_name"), label="display_name"),
        market=market,
        purpose=_required_string(payload.get("purpose"), label="purpose"),
        benchmark_symbol=_required_string(
            payload.get("benchmark_symbol"), label="benchmark_symbol"
        ),
        rebalance_cadence=str(cadence),
        base_cost_bps=base_bps,
        stress_cost_bps=stress_bps,
        bindings=bindings,
        source_path=Path(path).as_posix(),
    )
