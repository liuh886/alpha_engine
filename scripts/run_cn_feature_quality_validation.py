"""Run the canonical CN fixed-10D spec through the spec-bound Qlib adapter.

This script is intentionally a thin CLI. Research semantics live in the YAML
contract and in ``src.research.cn_qlib_execution_adapter``.
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path
from typing import Any

from src.research.cn_qlib_execution_adapter import (
    QlibCNExecutionRuntime,
    execute_cn_qlib_plan,
)
from src.research.paradigm import dry_run_paradigm, load_research_paradigm_spec
from src.research.spec_bound_execution import execute_spec_bound_research

DEFAULT_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")


def run(
    root: Path,
    *,
    spec_path: str | Path = DEFAULT_SPEC,
    output_dir: str | Path | None = None,
    provider_uri: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare and execute one CN research spec without CLI-owned semantics."""

    spec_file = Path(spec_path)
    if not spec_file.is_absolute():
        spec_file = root / spec_file
    spec = load_research_paradigm_spec(spec_file)
    if spec.market != "cn":
        raise ValueError("run_cn_feature_quality_validation requires a CN spec")

    # Materialize the stable preparation artifacts before execution. Execution
    # then overwrites run_status only after the declared/effective identity gate.
    dry_run_paradigm(spec, root=root, output_dir=output_dir)
    runtime = QlibCNExecutionRuntime(provider_uri=provider_uri)
    executor = partial(execute_cn_qlib_plan, runtime=runtime)
    return execute_spec_bound_research(
        spec,
        executor,
        root=root,
        output_dir=output_dir,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional parent directory for the experiment run directory.",
    )
    parser.add_argument(
        "--provider-uri",
        type=Path,
        default=None,
        help="Optional Qlib provider URI. Defaults to <root>/data/watchlist.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.root,
                spec_path=args.spec,
                output_dir=args.output_dir,
                provider_uri=args.provider_uri,
            ),
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
