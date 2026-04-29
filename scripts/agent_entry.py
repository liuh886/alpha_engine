#!/usr/bin/env python3
"""
Unified entrypoint to manage the project by agent identity.

Examples:
  python scripts/agent_entry.py --agent governance --market all
  python scripts/agent_entry.py --agent alpha --market us
  python scripts/agent_entry.py --agent risk --market us
  python scripts/agent_entry.py --agent developer --topic "architecture review"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.agent_router import AgentRouter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run project management flow as a chosen agent identity."
    )
    parser.add_argument(
        "--agent",
        required=True,
        choices=["alpha", "risk", "governance", "developer"],
        help="Agent identity to run.",
    )
    parser.add_argument(
        "--market",
        default="us",
        choices=["cn", "us", "all"],
        help="Target market for alpha/risk/governance agents.",
    )
    parser.add_argument(
        "--topic",
        default="project-management",
        help="Planning topic for developer agent.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser


def _run_by_agent(router: AgentRouter, *, agent: str, market: str, topic: str) -> Any:
    if agent == "developer":
        return router.route_task("developer", topic=topic)
    if agent == "governance":
        return router.route_task("governance", market=market)
    if agent == "alpha":
        return router.route_task("alpha", market=market)
    if agent == "risk":
        return router.route_task("risk", market=market)
    raise ValueError(f"Unsupported agent: {agent}")


def main() -> int:
    args = _build_parser().parse_args()
    router = AgentRouter()

    result = _run_by_agent(router, agent=args.agent, market=args.market, topic=args.topic)
    if args.json:
        print(
            json.dumps(
                {"ok": True, "agent": args.agent, "result": result}, ensure_ascii=False, default=str
            )
        )
    else:
        print(f"[agent-entry] agent={args.agent}")
        print(result if result is not None else "ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
