#!/usr/bin/env python3
"""Create, seal and verify manifest-bound formal provider caches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.formal_provider_cache import (
    build_provider_cache_contract,
    cache_key,
    load_contract,
    seal_provider_cache,
    verify_provider_cache,
    write_contract,
)


def _write_github_output(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    contract_parser = subparsers.add_parser("contract")
    contract_parser.add_argument("--root", type=Path, default=Path.cwd())
    contract_parser.add_argument("--market", choices=("us", "cn"), required=True)
    contract_parser.add_argument("--start", required=True)
    contract_parser.add_argument("--cutoff", required=True)
    contract_parser.add_argument("--output", type=Path, required=True)
    contract_parser.add_argument("--github-output", type=Path)

    for name in ("seal", "verify"):
        child = subparsers.add_parser(name)
        child.add_argument("--provider-root", type=Path, required=True)
        child.add_argument("--contract", type=Path, required=True)
        child.add_argument("--receipt", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "contract":
        contract = build_provider_cache_contract(
            repository_root=args.root,
            market=args.market,
            start=args.start,
            requested_cutoff=args.cutoff,
        )
        write_contract(args.output, contract)
        values = {
            "cache_key": cache_key(contract),
            "contract_sha256": str(contract["contract_sha256"]),
        }
        _write_github_output(args.github_output, values)
        result: dict[str, object] = {**values, "contract": contract}
    else:
        contract = load_contract(args.contract)
        if args.command == "seal":
            result = seal_provider_cache(
                provider_root=args.provider_root,
                contract=contract,
                receipt_path=args.receipt,
            )
        else:
            result = verify_provider_cache(
                provider_root=args.provider_root,
                contract=contract,
                receipt_path=args.receipt,
            )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
