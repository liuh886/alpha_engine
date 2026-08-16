#!/usr/bin/env python3
"""Build or query the canonical agent-facing factor research index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.factors.research_index import build_factor_research_index, query_factor_research_index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--registry", type=Path, default=Path("configs/factor_catalog.yaml"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--mechanism", default=None)
    parser.add_argument("--market", choices=["us", "cn"], default=None)
    parser.add_argument("--status", default=None)
    args = parser.parse_args()

    index = build_factor_research_index(root=args.root, registry_path=args.registry)
    if any((args.category, args.mechanism, args.market, args.status)):
        payload = {
            "schema_version": index["schema_version"],
            "index_sha256": index["index_sha256"],
            "query": {
                "category": args.category,
                "mechanism": args.mechanism,
                "market": args.market,
                "status": args.status,
            },
            "factors": query_factor_research_index(
                index,
                category=args.category,
                mechanism=args.mechanism,
                market=args.market,
                status=args.status,
            ),
        }
    else:
        payload = index
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output is not None:
        output = args.output
        if not output.is_absolute():
            output = args.root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
