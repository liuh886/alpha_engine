"""Derive a formal run's compounded excess return over its retained benchmark.

The value is computed only from an accepted Bundle v2 formal run's own retained
summary/performance/lineage sections. Sealed evidence and registry pins are
read-only; the deterministic result is written under ``data/research/``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.derived_formal_excess import (
    DEFAULT_ARTIFACT_PATH,
    DEFAULT_FORMAL_ROOT,
    derive_formal_benchmark_excess,
    write_derived_formal_excess,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--model-version-id", default="qqqi_qqq_tqqq_v4_3")
    parser.add_argument("--formal-root", type=Path, default=DEFAULT_FORMAL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_PATH)
    args = parser.parse_args()

    artifact = derive_formal_benchmark_excess(
        args.repository_root,
        args.model_version_id,
        relative_root=args.formal_root,
    )
    output = write_derived_formal_excess(
        artifact,
        args.output,
        repository_root=args.repository_root,
    )
    result = artifact["result"]
    print(
        json.dumps(
            {
                "status": "derived",
                "model_version_id": artifact["strategy"]["model_version_id"],
                "run_id": artifact["strategy"]["run_id"],
                "benchmark": artifact["benchmark"]["declared_identity"],
                "window": [
                    artifact["window"]["observed_start"],
                    artifact["window"]["observed_end"],
                ],
                "observation_count": artifact["window"]["observation_count"],
                "strategy_cumulative_return": result["strategy_cumulative_return"],
                "benchmark_cumulative_return": result["benchmark_cumulative_return"],
                "excess_return": result["excess_return"],
                "output": str(output),
                "research_only": True,
                "trade_ready": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
