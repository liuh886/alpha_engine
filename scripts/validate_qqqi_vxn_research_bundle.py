#!/usr/bin/env python3
"""Validate the durable QQQI/QQQ/TQQQ research result bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import nbformat
from nbformat import NotebookNode

SNAPSHOT = Path(
    "docs/research/snapshots/qqqi_vxn_v4_1_v4_2_2026-07-31.json"
)
POLICY = Path("docs/research/qqqi_vxn_research_result_and_notebook_policy.md")
LEDGER = Path("docs/research/qqqi_qqq_tqqq_experiment_ledger.md")
IMMUTABLE_NOTEBOOK = Path(
    "notebooks/16_qqqi_qqq_tqqq_vxn_v4_1_backtest_review.ipynb"
)
ROLLING_NOTEBOOK = Path(
    "notebooks/17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb"
)
BASELINE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_leverage_v4_1.yaml"
)
BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)


def _notebook_source(notebook: NotebookNode) -> str:
    return "\n".join(
        "".join(cell.get("source", ""))
        for cell in notebook.cells
    )


def _error_outputs(notebook: NotebookNode) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for cell_index, cell in enumerate(notebook.cells):
        if cell.cell_type != "code":
            continue
        for output in cell.get("outputs", []):
            if output.get("output_type") == "error":
                errors.append(
                    {
                        "cell_index": cell_index,
                        "ename": output.get("ename"),
                        "evalue": output.get("evalue"),
                    }
                )
    return errors


def validate_bundle(root: Path, *, require_executed: bool) -> None:
    """Validate files, snapshot semantics and rolling-notebook linkage."""

    required = (
        SNAPSHOT,
        POLICY,
        LEDGER,
        IMMUTABLE_NOTEBOOK,
        ROLLING_NOTEBOOK,
        BASELINE_CONTRACT,
        BRIDGE_CONTRACT,
    )
    missing = [str(path) for path in required if not (root / path).exists()]
    if missing:
        raise FileNotFoundError(f"missing research bundle files: {missing}")

    snapshot = json.loads((root / SNAPSHOT).read_text(encoding="utf-8"))
    expected_strategies = {
        "qqqi_qqq_tqqq_vxn_leverage_v4_1",
        "qqqi_qqq_tqqq_vxn_bridge_v4_2",
    }
    if not expected_strategies.issubset(snapshot.get("strategies", {})):
        raise ValueError("snapshot does not contain both active candidates")
    status = snapshot.get("research_status", {})
    if status.get("research_only") is not True:
        raise ValueError("snapshot must remain research-only")
    if status.get("trade_ready") is not False:
        raise ValueError("snapshot must not mark a candidate trade-ready")
    if status.get("prospective_monitoring_start") != "2026-08-01":
        raise ValueError("unexpected prospective monitoring boundary")

    for document in snapshot.get("companion_documents", []):
        if not (root / document).exists():
            raise FileNotFoundError(f"snapshot companion document is missing: {document}")

    notebooks = snapshot.get("notebooks", {})
    if notebooks.get("immutable_v4_1_review") != str(IMMUTABLE_NOTEBOOK):
        raise ValueError("snapshot immutable notebook link is stale")
    if notebooks.get("rolling_current_review") != str(ROLLING_NOTEBOOK):
        raise ValueError("snapshot rolling notebook link is stale")

    rolling = nbformat.read(root / ROLLING_NOTEBOOK, as_version=4)
    bundle = rolling.metadata.get("alpha_engine_research_bundle", {})
    expected_metadata = {
        "baseline_experiment_id": "qqqi_qqq_tqqq_vxn_leverage_v4_1",
        "challenger_experiment_id": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "prospective_start": "2026-08-01",
        "snapshot": str(SNAPSHOT),
        "maintenance_policy": str(POLICY),
        "rolling_notebook": True,
        "research_only": True,
        "trade_ready": False,
    }
    for key, expected in expected_metadata.items():
        if bundle.get(key) != expected:
            raise ValueError(
                f"rolling notebook metadata mismatch for {key}: "
                f"expected {expected!r}, found {bundle.get(key)!r}"
            )

    source = _notebook_source(rolling)
    required_terms = (
        "run_bridge_allocation_comparison",
        "rotation_vxn_leverage_v4_1_75",
        "rotation_vxn_bridge_v4_2_50_50",
        "prospective_return_metrics",
        "signal_date",
        "execution_date",
        "QQQI",
        "QQQ",
        "TQQQ",
    )
    missing_terms = [term for term in required_terms if term not in source]
    if missing_terms:
        raise ValueError(
            f"rolling notebook is missing required analysis terms: {missing_terms}"
        )

    errors = _error_outputs(rolling)
    if errors:
        raise ValueError(f"rolling notebook contains error outputs: {errors}")
    if require_executed:
        code_cells = [cell for cell in rolling.cells if cell.cell_type == "code"]
        if any(cell.get("execution_count") is None for cell in code_cells):
            raise ValueError("rolling notebook is not fully executed")
        if not any(cell.get("outputs") for cell in code_cells):
            raise ValueError("rolling notebook has no saved outputs")

    ledger = (root / LEDGER).read_text(encoding="utf-8")
    for term in (
        "Confidence bridge v4.2",
        "qqqi_qqq_tqqq_vxn_leverage_v4_1",
        "qqqi_qqq_tqqq_vxn_bridge_v4_2",
        "2026-08-01",
    ):
        if term not in ledger:
            raise ValueError(f"experiment ledger is missing required term: {term}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-executed",
        action="store_true",
        help="Require saved outputs and execution counts in the rolling notebook.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    validate_bundle(root, require_executed=args.require_executed)
    print(
        "validated QQQI/QQQ/TQQQ research bundle"
        + (" with executed notebook" if args.require_executed else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
