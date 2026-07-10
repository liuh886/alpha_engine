"""Compatibility entry point for the canonical US spec-bound Qlib runner.

The former implementation independently loaded session_config.json, assembled a
ranker grid, zero-filled features, chose Top-K, constructed rolling windows, and
wrote a separate evidence tree. Those semantics now belong to the US YAML
research contract and spec-bound execution pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_us_feature_quality_validation import run as _run_canonical

DEFAULT_SPEC = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")


def _reject_legacy_window_overrides(
    *,
    first_test_year: int | None,
    last_test_year: int | None,
) -> None:
    supplied = {
        "first_test_year": first_test_year,
        "last_test_year": last_test_year,
    }
    active = {name: value for name, value in supplied.items() if value is not None}
    if active:
        rendered = ", ".join(f"{name}={value!r}" for name, value in active.items())
        raise ValueError(
            "Legacy ranker-grid window overrides are no longer accepted. "
            "Select or edit a YAML research spec so the declared candidate and "
            f"split contracts remain identical: {rendered}"
        )


def run(
    root: Path,
    *,
    spec_path: str | Path = DEFAULT_SPEC,
    output_dir: str | Path | None = None,
    provider_uri: str | Path | None = None,
    first_test_year: int | None = None,
    last_test_year: int | None = None,
) -> dict[str, Any]:
    """Delegate to the canonical US runner without owning grid semantics."""

    _reject_legacy_window_overrides(
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    return _run_canonical(
        root,
        spec_path=spec_path,
        output_dir=output_dir,
        provider_uri=provider_uri,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--provider-uri", type=Path, default=None)
    parser.add_argument(
        "--first-test-year",
        type=int,
        default=None,
        help="Deprecated: use walk_forward.first_test_year in the YAML spec.",
    )
    parser.add_argument(
        "--last-test-year",
        type=int,
        default=None,
        help="Deprecated: use walk_forward.last_test_year in the YAML spec.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.root,
                spec_path=args.spec,
                output_dir=args.output_dir,
                provider_uri=args.provider_uri,
                first_test_year=args.first_test_year,
                last_test_year=args.last_test_year,
            ),
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
