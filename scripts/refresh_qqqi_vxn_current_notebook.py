#!/usr/bin/env python3
"""Execute and stamp the rolling QQQI/QQQ/TQQQ strategy notebook."""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nbformat
from nbclient import NotebookClient
from nbformat import NotebookNode

DEFAULT_NOTEBOOK = Path(
    "notebooks/17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb"
)
DEFAULT_SNAPSHOT = Path(
    "docs/research/snapshots/qqqi_vxn_v4_1_v4_2_2026-07-31.json"
)
DEFAULT_CONTRACTS = (
    Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_leverage_v4_1.yaml"),
    Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def validate_executed_notebook(notebook: NotebookNode) -> None:
    """Fail when the rolling notebook lacks executed outputs or contains errors."""

    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    if not code_cells:
        raise ValueError("rolling notebook contains no code cells")
    if any(cell.get("execution_count") is None for cell in code_cells):
        raise ValueError("rolling notebook contains unexecuted code cells")
    errors = _error_outputs(notebook)
    if errors:
        raise ValueError(f"rolling notebook contains error outputs: {errors}")
    if not any(cell.get("outputs") for cell in code_cells):
        raise ValueError("rolling notebook contains no saved outputs")


def _stamp_metadata(
    notebook: NotebookNode,
    *,
    root: Path,
    notebook_path: Path,
    snapshot_path: Path,
    end_date: str | None,
) -> None:
    bundle = notebook.metadata.setdefault("alpha_engine_research_bundle", {})
    bundle.update(
        {
            "executed_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "execution_end_date": end_date,
            "notebook_path": str(notebook_path.relative_to(root)),
            "snapshot": str(snapshot_path.relative_to(root)),
            "snapshot_sha256": _sha256(snapshot_path),
            "contract_sha256": {
                str(path.relative_to(root)): _sha256(path)
                for path in DEFAULT_CONTRACTS
            },
            "git_sha": os.getenv("GITHUB_SHA"),
            "research_only": True,
            "trade_ready": False,
        }
    )


def refresh_notebook(
    *,
    root: Path,
    notebook_path: Path,
    snapshot_path: Path,
    timeout: int,
    end_date: str | None,
) -> NotebookNode:
    """Execute the notebook in a clean kernel, validate it and write atomically."""

    if end_date:
        os.environ["QQQI_VXN_NOTEBOOK_END_DATE"] = end_date
    notebook = nbformat.read(notebook_path, as_version=4)
    executed = NotebookClient(
        notebook,
        timeout=timeout,
        kernel_name="python3",
        allow_errors=False,
    ).execute(cwd=str(root))
    validate_executed_notebook(executed)
    _stamp_metadata(
        executed,
        root=root,
        notebook_path=notebook_path,
        snapshot_path=snapshot_path,
        end_date=end_date,
    )
    temporary = notebook_path.with_suffix(".executed.tmp.ipynb")
    nbformat.write(executed, temporary)
    temporary.replace(notebook_path)
    return executed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=DEFAULT_NOTEBOOK)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--end-date",
        default=os.getenv("QQQI_VXN_NOTEBOOK_END_DATE"),
        help="Optional exclusive market-data end date.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate the committed notebook without executing it.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    notebook_path = (root / args.notebook).resolve()
    snapshot_path = (root / args.snapshot).resolve()
    missing = [
        path
        for path in (notebook_path, snapshot_path, *DEFAULT_CONTRACTS)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(f"missing research bundle files: {missing}")

    if args.check_only:
        notebook = nbformat.read(notebook_path, as_version=4)
        validate_executed_notebook(notebook)
        print(f"validated executed notebook: {notebook_path}")
        return 0

    executed = refresh_notebook(
        root=root,
        notebook_path=notebook_path,
        snapshot_path=snapshot_path,
        timeout=args.timeout,
        end_date=args.end_date,
    )
    print(
        "refreshed rolling notebook: "
        f"{notebook_path} ({len(executed.cells)} cells)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
