"""Run the frozen S/S, S/P, P/S, P/P static-to-PIT decomposition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.static_to_pit_execution import (
    DEFAULT_OUTPUT,
    DEFAULT_PIT_SPEC,
    DEFAULT_STATIC_SPEC,
    run_static_to_pit_decomposition,
)
from src.research.static_to_pit_provider_lock import (
    DECOMPOSITION_PROVIDER_IDENTITY,
    STATIC_REFERENCE_PROVIDER_IDENTITY,
    validate_authoritative_provider_pair,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--static-spec", type=Path, default=DEFAULT_STATIC_SPEC)
    parser.add_argument("--pit-spec", type=Path, default=DEFAULT_PIT_SPEC)
    parser.add_argument(
        "--static-reference-provider-uri",
        type=Path,
        required=True,
        help=(
            "Original manifest-bound provider used by the published #183 S/S "
            f"run; required identity={STATIC_REFERENCE_PROVIDER_IDENTITY}."
        ),
    )
    parser.add_argument(
        "--decomposition-provider-uri",
        type=Path,
        required=True,
        help=(
            "Repaired manifest-bound provider used for the controlled S/S, S/P, "
            "P/S and P/P matrix; required identity="
            f"{DECOMPOSITION_PROVIDER_IDENTITY}."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    validated_providers = validate_authoritative_provider_pair(
        args.static_reference_provider_uri,
        args.decomposition_provider_uri,
    )
    payload = run_static_to_pit_decomposition(
        args.root,
        static_spec_path=args.static_spec,
        pit_spec_path=args.pit_spec,
        static_reference_provider_uri=args.static_reference_provider_uri,
        decomposition_provider_uri=args.decomposition_provider_uri,
        output_dir=args.output_dir,
    )
    payload["validated_provider_pair"] = validated_providers
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
