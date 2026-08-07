#!/usr/bin/env python3
"""Persist one governed formal-strategy signal evaluation into the shared ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.strategy_signal_ledger import (
    append_signal_evaluation,
    parse_optional_int,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-version-id", required=True)
    parser.add_argument("--signal-json", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--delivery-status", required=True)
    parser.add_argument("--github-issue-number", default="")
    parser.add_argument("--telegram-message-id", default="")
    parser.add_argument("--delivery-error", default="")
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--created-at-utc", required=True)
    args = parser.parse_args()

    payload = json.loads(args.signal_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("signal JSON root must be an object")

    record_path = append_signal_evaluation(
        ledger_root=args.ledger_dir,
        model_version_id=args.model_version_id,
        signal=payload,
        delivery_status=args.delivery_status,
        github_issue_number=parse_optional_int(
            args.github_issue_number, label="github_issue_number"
        ),
        telegram_message_id=parse_optional_int(
            args.telegram_message_id, label="telegram_message_id"
        ),
        delivery_error=args.delivery_error or None,
        workflow_run_id=args.workflow_run_id,
        commit_sha=args.commit_sha,
        created_at_utc=args.created_at_utc,
    )
    print(record_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
