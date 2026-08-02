#!/usr/bin/env python3
"""Update rolling notebook role labels after v4.2 baseline promotion."""

from __future__ import annotations

import argparse
from pathlib import Path

import nbformat

DEFAULT_NOTEBOOK = Path(
    "notebooks/17_qqqi_qqq_tqqq_vxn_current_strategy_review.ipynb"
)

INTRO = """# QQQI / QQQ / TQQQ current strategy review

This is the rolling comparison notebook for the current v4.2 50/50 research baseline and the immutable v4.1 historical signal comparator.

- Current research baseline: `qqqi_qqq_tqqq_vxn_bridge_v4_2`
- Historical signal comparator: `qqqi_qqq_tqqq_vxn_leverage_v4_1`
- Prospective boundary: 2026-08-01
- Status: research-only; the baseline is not trade-ready.

The notebook is refreshed with `scripts/refresh_qqqi_vxn_current_notebook.py`. It displays the durable published snapshot first, then recomputes the current live-data comparison using the frozen contracts. v4.2 baseline status reflects lower turnover and stronger net metrics under the unchanged 10 bps cost convention; it does not claim a superior signal trace.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=DEFAULT_NOTEBOOK)
    args = parser.parse_args()

    notebook = nbformat.read(args.notebook, as_version=4)
    if not notebook.cells or notebook.cells[0].cell_type != "markdown":
        raise ValueError("rolling notebook must begin with a markdown introduction")
    notebook.cells[0].source = INTRO
    bundle = notebook.metadata.setdefault("alpha_engine_research_bundle", {})
    bundle.update(
        {
            "current_research_baseline": "qqqi_qqq_tqqq_vxn_bridge_v4_2",
            "historical_signal_comparator": "qqqi_qqq_tqqq_vxn_leverage_v4_1",
            "baseline_effective_date": "2026-08-02",
            "promotion_scope": "research_baseline_only",
            "transaction_cost_bps_per_turnover_unit": 10.0,
            "research_only": True,
            "trade_ready": False,
        }
    )
    bundle.pop("baseline", None)
    bundle.pop("challenger", None)
    nbformat.write(notebook, args.notebook)
    print(f"updated notebook roles: {args.notebook}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
