"""Canonical factor-evidence records and feature-quality normalization.

Factor formulas remain owned by :mod:`src.factors.library`. Evidence records are
immutable research read models that bind one canonical implementation hash to a
market/provider/universe/cutoff and link back to authoritative receipts. They do
not define or execute factors.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EVIDENCE_SCHEMA_VERSION = "1.0"
EVIDENCE_STATUSES = {
    "candidate",
    "validated",
    "rejected",
    "model_active",
    "diagnostic_only",
}


@dataclass(frozen=True)
class FactorEvidenceRecord:
    factor_id: str
    implementation_hash: str
    market: str
    status: str
    use_case: str
    target_horizon_sessions: int | None
    provider_identity_sha256: str | None
    universe_id: str | None
    universe_count: int | None
    cutoff: str | None
    validation: dict[str, Any]
    metrics: dict[str, Any]
    disposition: str
    evidence_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.factor_id or len(self.implementation_hash) != 64:
            raise ValueError("factor evidence requires factor_id and 64-char implementation hash")
        if self.market not in {"us", "cn"}:
            raise ValueError("factor evidence market must be us or cn")
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"unsupported factor evidence status: {self.status}")
        if self.target_horizon_sessions is not None and self.target_horizon_sessions <= 0:
            raise ValueError("target_horizon_sessions must be positive when present")
        if self.universe_count is not None and self.universe_count <= 0:
            raise ValueError("universe_count must be positive when present")
        if not self.evidence_paths:
            raise ValueError("factor evidence must link at least one authoritative receipt")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_paths"] = list(self.evidence_paths)
        return payload


def _first_valid_summary(symbol_quality: dict[str, Any]) -> dict[str, Any]:
    first_dates = [
        str(row["first_valid_date"])
        for row in symbol_quality.values()
        if isinstance(row, dict) and row.get("first_valid_date")
    ]
    last_dates = [
        str(row["last_valid_date"])
        for row in symbol_quality.values()
        if isinstance(row, dict) and row.get("last_valid_date")
    ]
    warmups = [
        int(row["observed_warmup_sessions"])
        for row in symbol_quality.values()
        if isinstance(row, dict) and row.get("observed_warmup_sessions") is not None
    ]
    coverages = [
        float(row["post_warmup_coverage"])
        for row in symbol_quality.values()
        if isinstance(row, dict) and row.get("post_warmup_coverage") is not None
    ]
    return {
        "earliest_first_valid_date": min(first_dates) if first_dates else None,
        "latest_first_valid_date": max(first_dates) if first_dates else None,
        "earliest_last_valid_date": min(last_dates) if last_dates else None,
        "latest_last_valid_date": max(last_dates) if last_dates else None,
        "minimum_observed_warmup_sessions": min(warmups) if warmups else None,
        "maximum_observed_warmup_sessions": max(warmups) if warmups else None,
        "minimum_post_warmup_coverage": min(coverages) if coverages else 0.0,
        "mean_post_warmup_coverage": (
            sum(coverages) / len(coverages) if coverages else 0.0
        ),
    }


def records_from_feature_quality_receipt(
    receipt: dict[str, Any],
    *,
    evidence_path: str,
    status: str = "candidate",
    use_case: str = "feature_quality",
    target_horizon_sessions: int | None = 10,
) -> list[FactorEvidenceRecord]:
    """Normalize the existing Gate-1 feature-quality receipt into factor records."""

    if receipt.get("gate1_pass") is not True:
        raise ValueError("cannot normalize a failing feature-quality receipt as passing evidence")
    market = str(receipt.get("market", ""))
    provider = receipt.get("provider")
    universe = receipt.get("universe")
    factors = receipt.get("factors")
    if not isinstance(provider, dict) or not isinstance(universe, dict) or not isinstance(factors, list):
        raise ValueError("feature-quality receipt is missing provider/universe/factor evidence")
    provider_identity = str(provider.get("provider_identity_sha256") or "")
    cutoff = str(provider.get("cutoff") or "")
    if len(provider_identity) != 64 or not cutoff:
        raise ValueError("feature-quality receipt lacks provider identity or cutoff")

    records: list[FactorEvidenceRecord] = []
    for raw in factors:
        if not isinstance(raw, dict):
            raise ValueError("feature-quality factor row must be a mapping")
        symbol_quality = raw.get("symbol_quality")
        if not isinstance(symbol_quality, dict):
            raise ValueError("feature-quality row lacks symbol_quality")
        summary = _first_valid_summary(symbol_quality)
        checks = raw.get("checks")
        if not isinstance(checks, dict) or not checks or not all(bool(value) for value in checks.values()):
            raise ValueError(f"feature-quality checks did not all pass for {raw.get('factor_id')}")
        validation = {
            "usable_rows": int(raw.get("finite_count", 0)),
            "requested_symbol_count": int(universe.get("requested_symbol_count", 0)),
            "missing_symbol_count": len(raw.get("missing_symbols") or []),
            "inf_count": int(raw.get("inf_count", 0)),
            "near_constant": bool(raw.get("near_constant", False)),
            "expression_window": dict(raw.get("expression_window") or {}),
            "checks": dict(checks),
            "deterministic": bool((receipt.get("determinism") or {}).get("pass")),
            **summary,
        }
        records.append(
            FactorEvidenceRecord(
                factor_id=str(raw["factor_id"]),
                implementation_hash=str(raw["implementation_hash"]),
                market=market,
                status=status,
                use_case=use_case,
                target_horizon_sessions=target_horizon_sessions,
                provider_identity_sha256=provider_identity,
                universe_id=(None if universe.get("universe_id") is None else str(universe["universe_id"])),
                universe_count=int(universe.get("requested_symbol_count", 0)) or None,
                cutoff=cutoff,
                validation=validation,
                metrics={},
                disposition="structural_feature_quality_pass",
                evidence_paths=(evidence_path,),
            )
        )
    return records


def load_factor_evidence(path: str | Path) -> list[FactorEvidenceRecord]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(f"factor evidence file requires schema_version={EVIDENCE_SCHEMA_VERSION}")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise ValueError("factor evidence records must be a list")
    records: list[FactorEvidenceRecord] = []
    identities: set[tuple[str, str, str]] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise ValueError("factor evidence record must be a mapping")
        record = FactorEvidenceRecord(
            factor_id=str(raw.get("factor_id", "")),
            implementation_hash=str(raw.get("implementation_hash", "")),
            market=str(raw.get("market", "")),
            status=str(raw.get("status", "")),
            use_case=str(raw.get("use_case", "")),
            target_horizon_sessions=(
                None
                if raw.get("target_horizon_sessions") is None
                else int(raw["target_horizon_sessions"])
            ),
            provider_identity_sha256=(
                None
                if raw.get("provider_identity_sha256") is None
                else str(raw["provider_identity_sha256"])
            ),
            universe_id=(None if raw.get("universe_id") is None else str(raw["universe_id"])),
            universe_count=(None if raw.get("universe_count") is None else int(raw["universe_count"])),
            cutoff=(None if raw.get("cutoff") is None else str(raw["cutoff"])),
            validation=dict(raw.get("validation") or {}),
            metrics=dict(raw.get("metrics") or {}),
            disposition=str(raw.get("disposition", "")),
            evidence_paths=tuple(str(value) for value in raw.get("evidence_paths") or ()),
        )
        identity = (record.factor_id, record.market, record.use_case)
        if identity in identities:
            raise ValueError(f"duplicate factor evidence identity: {identity}")
        identities.add(identity)
        records.append(record)
    return records
