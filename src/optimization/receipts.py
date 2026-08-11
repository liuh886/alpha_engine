"""Standardized experiment receipt generation.

Produces versioned, identity-bound JSON receipts suitable for machine comparison.
Pure functions, no I/O beyond file writing.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def experiment_identity(contract: Any) -> str:
    """Deterministic identity hash for an experiment contract."""
    payload = json.dumps(
        {
            "experiment_id": contract.experiment_id,
            "market": contract.market,
            "benchmark": contract.benchmark,
            "cost_bps": contract.cost_structure.base_cost_bps,
            "windows": list(contract.windows.labels),
            "candidates": sorted(
                (c.candidate_id, c.role) for c in contract.candidates
            ),
            "baseline": contract.baseline_candidate_id,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def write_receipt(
    output_dir: str | Path,
    experiment_id: str,
    results: list[dict[str, Any]],
    *,
    provider_identity: str = "",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write a standardized experiment receipt.

    Returns path to the written receipt file.
    """
    output = Path(output_dir) / experiment_id
    output.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "schema_version": "2.0.0",
        "experiment_id": experiment_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider_identity": provider_identity,
        "results": results,
        "metadata": metadata or {},
    }

    receipt_path = output / "receipt.json"
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return receipt_path
