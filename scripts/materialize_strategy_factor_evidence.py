#!/usr/bin/env python3
"""Attach cutoff-bound canonical factor evidence to one governed signal JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.factors.strategy_snapshot import build_strategy_factor_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-family-id", required=True)
    parser.add_argument("--signal-json", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.signal_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("signal JSON root must be an object")

    factor_evidence = build_strategy_factor_snapshot(
        model_family_id=args.model_family_id,
        signal=payload,
    )
    payload["factor_evidence"] = factor_evidence
    payload["factor_freshness_ok"] = factor_evidence["freshness"] == "current"
    args.signal_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(
                "factor_freshness_ok="
                + ("true" if payload["factor_freshness_ok"] else "false")
                + "\n"
            )
            handle.write(f"factor_count={factor_evidence['factor_count']}\n")
    print(args.signal_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
