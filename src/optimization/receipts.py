"""Standardized result persistence for model optimization experiments.

Every experiment produces a versioned, identity-bound receipt that can be
compared across runs, agents, and time.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.optimization.contracts import ExperimentContract
from src.optimization.metrics import CandidateResult, GateResult


def _default_serializer(obj: Any) -> Any:
    """JSON default serializer for non-standard types."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"unsupported type: {type(obj)!r}")


def experiment_identity(contract: ExperimentContract) -> str:
    """Compute a deterministic identity hash for an experiment contract."""
    payload = json.dumps(
        {
            "experiment_id": contract.experiment_id,
            "model_type": contract.model_type.value,
            "market": contract.market,
            "benchmark": contract.benchmark,
            "cost_bps": contract.cost_structure.base_cost_bps,
            "windows": list(contract.windows.labels),
            "candidates": sorted(
                (c.candidate_id, c.role, c.params) for c in contract.candidates
            ),
            "baseline": contract.baseline_candidate_id,
            "gate_profile": contract.gate_profile.value,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def save_receipt(
    contract: ExperimentContract,
    candidates: list[CandidateResult],
    gates: list[GateResult],
    output_dir: Path,
    *,
    provider_identity: str | None = None,
    runtime_metadata: dict[str, Any] | None = None,
) -> Path:
    """Save a standardized experiment receipt.

    Returns the path to the saved receipt.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    passing = [g for g in gates if g.all_pass]
    passing_ids = [g.candidate_id for g in passing]

    payload: dict[str, Any] = {
        "schema_version": "2.0.0",
        "experiment_id": contract.experiment_id,
        "experiment_identity": experiment_identity(contract),
        "model_type": contract.model_type.value,
        "market": contract.market,
        "benchmark": contract.benchmark,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_structure": {
            "base_cost_bps": contract.cost_structure.base_cost_bps,
            "stress_cost_bps": list(contract.cost_structure.stress_cost_bps),
        },
        "windows": list(contract.windows.labels),
        "n_candidates": len(contract.candidates),
        "n_passing": len(passing),
        "passing_candidate_ids": passing_ids,
        "provider_identity": provider_identity,
        "runtime_metadata": runtime_metadata or {},
        "baseline": {
            "candidate_id": contract.baseline_candidate_id,
        },
        "candidates": [],
        "gate_results": [],
    }

    # Add baseline metrics
    bl = next((c for c in candidates if c.candidate_id == contract.baseline_candidate_id), None)
    if bl:
        payload["baseline"].update({
            "compounded_relative_excess": bl.compounded_relative_excess,
            "worst_drawdown": bl.worst_drawdown,
            "positive_windows": bl.positive_windows,
            "strongest_window_share": bl.strongest_window_share,
        })

    # Add all candidates
    for c in candidates:
        payload["candidates"].append({
            "candidate_id": c.candidate_id,
            "compounded_relative_excess": c.compounded_relative_excess,
            "worst_drawdown": c.worst_drawdown,
            "positive_windows": c.positive_windows,
            "strongest_window_share": c.strongest_window_share,
            "cost_stress": {str(k): v for k, v in c.cost_stress.items()},
            "per_window": {
                w: {
                    "relative_excess": wr.relative_excess,
                    "max_drawdown": wr.max_drawdown,
                    "n_periods": wr.n_periods,
                }
                for w, wr in c.windows.items()
            },
            "metadata": {k: v for k, v in c.metadata.items()
                        if not callable(v) and not isinstance(v, (bytes, bytearray))},
        })

    # Add gate results
    for g in gates:
        payload["gate_results"].append({
            "candidate_id": g.candidate_id,
            "gates": g.gates,
            "all_pass": g.all_pass,
            "selection_score": g.selection_score,
        })

    receipt_path = output_dir / "experiment_receipt.json"
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=_default_serializer)
        + "\n",
        encoding="utf-8",
    )

    # Also save a human-readable summary
    summary_lines = [
        f"# Experiment: {contract.experiment_id}",
        f"Model Type: {contract.model_type.value} | Market: {contract.market} | Benchmark: {contract.benchmark}",
        f"Candidates: {len(contract.candidates)} | Passing: {len(passing)}",
        f"Cost: {contract.cost_structure.base_cost_bps}bps | Windows: {contract.windows.labels}",
        "",
        "## Results (sorted by selection score)",
    ]
    for g in sorted(gates, key=lambda g: g.selection_score, reverse=True):
        c = next((c for c in candidates if c.candidate_id == g.candidate_id), None)
        if c is None:
            continue
        status = "PASS" if g.all_pass else "FAIL"
        summary_lines.append(
            f"- [{status}] {c.candidate_id}: "
            f"excess={c.compounded_relative_excess:.4f} "
            f"dd={c.worst_drawdown:.4f} "
            f"score={g.selection_score:.4f}"
        )
        for gate_name, gate_val in g.gates.items():
            summary_lines.append(f"    {gate_name}: {'PASS' if gate_val else 'FAIL'}")

    summary_path = output_dir / "experiment_summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

    return receipt_path
