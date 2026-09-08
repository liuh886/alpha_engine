"""Run the canonical US fixed-10D spec through the spec-bound Qlib adapter.

This script is intentionally a thin CLI. Research semantics live in the YAML
contract and in ``src.research.us_qlib_execution_adapter``; the shared flow
lives in ``scripts.feature_quality_validation_common``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.feature_quality_validation_common import (
    record_unhandled_failure,
    run_feature_quality_validation,
)

DEFAULT_SPEC = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")


def _record_unhandled_failure(
    *,
    root: Path,
    output_dir: str | Path | None,
    experiment_id: str,
    exc: Exception,
) -> None:
    """Write an auditable failure unless a more specific gate already did so."""
    record_unhandled_failure(
        root=root,
        output_dir=output_dir,
        experiment_id=experiment_id,
        failed_stage="us_qlib_execution",
        exc=exc,
    )


def run(
    root: Path,
    *,
    spec_path: str | Path = DEFAULT_SPEC,
    output_dir: str | Path | None = None,
    provider_uri: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare and execute one US research spec without CLI-owned semantics."""
    return run_feature_quality_validation(
        root,
        market="us",
        script_name="run_us_feature_quality_validation",
        spec_path=spec_path,
        output_dir=output_dir,
        provider_uri=provider_uri,
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
