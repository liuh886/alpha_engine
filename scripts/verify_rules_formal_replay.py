#!/usr/bin/env python3
"""Fail closed unless accepted QQQ/CN rules economics are exactly replayable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from src.research.rules_formal_replay_gate import (
    RulesFormalReplayError,
    verify_cn_current_allocation_replay,
    verify_qqq_professional_replay,
)


def _write(path: Path | None, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--receipt", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="model", required=True)

    qqq = subparsers.add_parser("qqq")
    qqq.add_argument("--package", type=Path, required=True)
    qqq.add_argument("--bundle-dir", type=Path, required=True)

    cn = subparsers.add_parser("cn")
    cn.add_argument("--package", type=Path, required=True)
    cn.add_argument("--provider-dir", type=Path, required=True)
    cn.add_argument("--ledger", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.model == "qqq":
            payload = verify_qqq_professional_replay(
                args.root,
                package_path=args.package,
                bundle_dir=args.bundle_dir,
            )
        else:
            payload = verify_cn_current_allocation_replay(
                args.root,
                package_path=args.package,
                provider_dir=args.provider_dir,
                ledger_path=args.ledger,
            )
    except (RulesFormalReplayError, FileNotFoundError, OSError, ValueError) as exc:
        payload = {
            "schema_version": "1.0",
            "status": "blocked",
            "decision": "invalid_evidence",
            "model": args.model,
            "reason": str(exc),
            "research_only": True,
            "trade_ready": False,
            "promotion_authorized": False,
        }
        _write(args.receipt, payload)
        return 2

    _write(args.receipt, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
