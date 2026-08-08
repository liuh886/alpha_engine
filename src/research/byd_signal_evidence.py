"""Evidence binding for governed BYD v1.2 signal publications.

The model-specific signal builder owns the allocation decision. This module owns
publication semantics that must not be confused with that decision: whether the
close-time evidence is current, whether the latest observed open was eligible,
and the immutable identity of the fully materialized evidence packet.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


class BYDSignalEvidenceError(ValueError):
    """Raised when a BYD signal cannot be bound to current governed evidence."""


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BYDSignalEvidenceError(f"{label} must be an object")
    return value


def close_evidence_is_current(
    shadow: Mapping[str, Any],
    paired: Mapping[str, Any],
    expansion: Mapping[str, Any],
) -> bool:
    """Return whether the close-time decision inputs are current and corroborated.

    Same-session open eligibility is deliberately excluded. The formal execution
    contract already says the close-time target waits for the next independently
    confirmed eligible open, so an unusable *past* open cannot make current close
    data stale.
    """

    dates = {
        str(shadow.get("signal_date") or ""),
        str(paired.get("signal_date") or ""),
        str(expansion.get("signal_date") or ""),
    }
    if len(dates) != 1 or "" in dates:
        return False

    paired_byd = _mapping(paired.get("byd"), label="paired.byd")
    paired_etf = _mapping(paired.get("etf"), label="paired.etf")
    factors = _mapping(expansion.get("factors"), label="expansion.factors")
    required_factors = {"market_state", "vol_state", "mom_20", "mom_60", "drawdown_252"}
    if not required_factors.issubset(factors):
        return False

    return bool(
        shadow.get("prospective_eligible") is True
        and paired_byd.get("prospective_eligible") is True
        and paired_etf.get("independent_raw_confirmed") is True
        and shadow.get("data_version")
        and paired.get("data_version")
        and expansion.get("data_version")
    )


def bind_final_signal_identity(alert: dict[str, Any]) -> dict[str, Any]:
    """Bind the signal fingerprint to decision, source and canonical factor identity."""

    decision_fingerprint = str(alert.get("fingerprint") or "").strip()
    if not decision_fingerprint:
        raise BYDSignalEvidenceError("signal decision fingerprint is missing")
    provenance = _mapping(alert.get("data_provenance"), label="signal.data_provenance")
    factor_evidence = _mapping(alert.get("factor_evidence"), label="signal.factor_evidence")
    catalog_hash = str(factor_evidence.get("catalog_implementation_hash") or "").strip()
    source_sha256 = str(factor_evidence.get("source_sha256") or "").strip()
    if len(catalog_hash) != 64 or len(source_sha256) != 64:
        raise BYDSignalEvidenceError("canonical factor identity is incomplete")

    identity = {
        "decision_fingerprint": decision_fingerprint,
        "source_manifests": dict(sorted((str(k), str(v)) for k, v in provenance.items() if k.endswith("_sha256"))),
        "factor_catalog_implementation_hash": catalog_hash,
        "factor_source_sha256": source_sha256,
    }
    final_fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]

    alert["decision_fingerprint"] = decision_fingerprint
    alert["fingerprint"] = final_fingerprint
    alert["evidence_identity"] = identity
    markdown = alert.get("markdown")
    if isinstance(markdown, str):
        alert["markdown"] = markdown.replace(
            f"signal-fingerprint:{decision_fingerprint}",
            f"signal-fingerprint:{final_fingerprint}",
        )
    return alert
