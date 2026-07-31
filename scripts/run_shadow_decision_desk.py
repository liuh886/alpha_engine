"""Generate one immutable research-only shadow decision ticket."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.decision_support.shadow_decision_desk import build_shadow_decision_ticket


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a manifest-bound daily shadow ticket. This command does not "
            "send orders or claim trade readiness."
        )
    )
    parser.add_argument("--rotation-dir", type=Path, required=True)
    parser.add_argument("--registry-db", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--factor-scores", type=Path, default=None)
    parser.add_argument("--annual-turnover-budget", type=float, default=4.0)
    args = parser.parse_args()

    ticket = build_shadow_decision_ticket(
        rotation_dir=args.rotation_dir,
        registry_db=args.registry_db,
        ledger_dir=args.ledger_dir,
        market=args.market,
        as_of_date=args.as_of_date,
        factor_scores_path=args.factor_scores,
        annual_turnover_budget=args.annual_turnover_budget,
    )
    summary = {
        "ticket_identity_sha256": ticket["ticket_identity_sha256"],
        "market": ticket["market"],
        "as_of_date": ticket["as_of_date"],
        "mode": ticket["mode"],
        "trade_ready": ticket["trade_ready"],
        "security_count": len(ticket["securities"]),
        "ticket_turnover": ticket["turnover_budget"]["ticket_turnover"],
        "remaining_turnover_budget": ticket["turnover_budget"]["remaining"],
        "warnings": ticket["warnings"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
