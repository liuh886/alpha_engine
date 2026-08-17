#!/usr/bin/env python3
"""Deliver pending active-strategy decisions from the canonical signal ledgers."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.strategy_signal_ledger import (
    TERMINAL_DELIVERY_STATUSES,
    read_latest_evaluation,
    record_signal_delivery,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog

AMBIGUOUS_ERRORS = {
    "ambiguous_external_delivery_state",
    "telegram_transport_ambiguous",
}


@dataclass(frozen=True)
class DeliveryResult:
    strategy_id: str
    model_version_id: str
    signal_date: str | None
    status: str
    github_issue_number: int | None = None
    telegram_message_id: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "model_version_id": self.model_version_id,
            "signal_date": self.signal_date,
            "status": self.status,
            "github_issue_number": self.github_issue_number,
            "telegram_message_id": self.telegram_message_id,
            "error": self.error,
        }


def _weights(value: object) -> str:
    if not isinstance(value, Mapping) or not value:
        return "—"
    rows = []
    for asset, weight in sorted(value.items()):
        try:
            rows.append(f"{asset} {float(weight):.1%}")
        except (TypeError, ValueError):
            continue
    return ", ".join(rows) or "—"


def _message(model: str, signal: Mapping[str, Any]) -> tuple[str, str, str]:
    signal_date = str(signal.get("signal_date") or "")
    fingerprint = str(signal.get("fingerprint") or "")
    marker = f"<!-- signal-decision:{model}:{signal_date}:{fingerprint} -->"
    title = str(signal.get("title") or f"[策略信号] {model} {signal_date}")
    action = str(
        signal.get("action")
        or signal.get("transition_type")
        or signal.get("signal_state")
        or "UPDATE"
    )
    reason = str(
        signal.get("reason_code")
        or signal.get("decision_reason_label")
        or signal.get("transition_label")
        or "Canonical strategy decision changed."
    )
    execution = str(signal.get("execution_time") or "next eligible open")
    current = _weights(signal.get("current_weights"))
    target = _weights(signal.get("target_weights"))
    text = (
        f"{title}\n"
        f"动作：{action}\n"
        f"信号日：{signal_date}\n"
        f"当前：{current}\n"
        f"目标：{target}\n"
        f"执行：{execution}\n"
        f"原因：{reason}\n\n"
        "Research only; not trade ready."
    )
    body = f"{marker}\n\n{text}"
    return title, body, text


def _existing_issue(repository: str, marker: str) -> int | None:
    completed = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repository}/issues?state=all&per_page=100",
            "--jq",
            f'.[] | select(.pull_request == null) | select((.body // "") | contains("{marker}")) | .number',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    first = completed.stdout.strip().splitlines()
    return int(first[0]) if first else None


def _create_issue(repository: str, title: str, body: str) -> int:
    completed = subprocess.run(
        ["gh", "issue", "create", "--repo", repository, "--title", title, "--body", body],
        check=True,
        capture_output=True,
        text=True,
    )
    url = completed.stdout.strip()
    if not url:
        raise RuntimeError("GitHub issue creation returned no URL")
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _send_telegram(token: str, chat_id: str, text: str) -> int:
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("telegram_api_rejected") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("telegram_transport_ambiguous") from exc
    if payload.get("ok") is not True:
        raise RuntimeError("telegram_api_rejected")
    return int(payload["result"]["message_id"])


def _record(
    *,
    ledger: Path,
    model: str,
    signal: Mapping[str, Any],
    status: str,
    workflow_run_id: str,
    commit_sha: str,
    created_at_utc: str,
    issue: int | None = None,
    message: int | None = None,
    error: str | None = None,
) -> None:
    record_signal_delivery(
        ledger_root=ledger,
        model_version_id=model,
        signal=signal,
        delivery_status=status,
        github_issue_number=issue,
        telegram_message_id=message,
        delivery_error=error,
        workflow_run_id=workflow_run_id,
        commit_sha=commit_sha,
        created_at_utc=created_at_utc,
    )


def drain_outbox(
    *,
    repository: str,
    workflow_run_id: str,
    commit_sha: str,
    created_at_utc: str,
    telegram_token: str | None,
    telegram_chat_id: str | None,
) -> list[DeliveryResult]:
    results: list[DeliveryResult] = []
    for strategy in load_active_strategy_catalog().strategies:
        ledger = Path(strategy.signal_ledger)
        record = read_latest_evaluation(
            ledger,
            model_version_id=strategy.model_version_id,
        )
        if record is None:
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=None,
                    status="no_decision",
                )
            )
            continue
        signal = record.get("signal")
        if not isinstance(signal, Mapping):
            raise ValueError(f"canonical signal is missing: {strategy.model_version_id}")
        delivery = record.get("delivery")
        prior = delivery if isinstance(delivery, Mapping) else {}
        prior_status = str(prior.get("status") or "pending")
        signal_date = str(record.get("signal_date") or signal.get("signal_date") or "")
        if prior_status in TERMINAL_DELIVERY_STATUSES:
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=signal_date,
                    status=prior_status,
                    github_issue_number=prior.get("github_issue_number"),
                    telegram_message_id=prior.get("telegram_message_id"),
                    error=prior.get("error"),
                )
            )
            continue
        prior_error = str(prior.get("error") or "")
        if prior_error in AMBIGUOUS_ERRORS:
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=signal_date,
                    status="failed",
                    github_issue_number=prior.get("github_issue_number"),
                    error=prior_error,
                )
            )
            continue
        if signal.get("should_alert") is not True:
            _record(
                ledger=ledger,
                model=strategy.model_version_id,
                signal=signal,
                status="not_required",
                workflow_run_id=workflow_run_id,
                commit_sha=commit_sha,
                created_at_utc=created_at_utc,
            )
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=signal_date,
                    status="not_required",
                )
            )
            continue

        title, body, telegram_text = _message(strategy.model_version_id, signal)
        marker = body.split("\n", 1)[0]
        issue = _existing_issue(repository, marker)
        if issue is not None and prior_status == "pending":
            error = "ambiguous_external_delivery_state"
            _record(
                ledger=ledger,
                model=strategy.model_version_id,
                signal=signal,
                status="failed",
                issue=issue,
                error=error,
                workflow_run_id=workflow_run_id,
                commit_sha=commit_sha,
                created_at_utc=created_at_utc,
            )
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=signal_date,
                    status="failed",
                    github_issue_number=issue,
                    error=error,
                )
            )
            continue
        if issue is None:
            try:
                issue = _create_issue(repository, title, body)
            except (subprocess.CalledProcessError, RuntimeError):
                error = "github_issue_delivery_failed"
                _record(
                    ledger=ledger,
                    model=strategy.model_version_id,
                    signal=signal,
                    status="failed",
                    error=error,
                    workflow_run_id=workflow_run_id,
                    commit_sha=commit_sha,
                    created_at_utc=created_at_utc,
                )
                results.append(
                    DeliveryResult(
                        strategy_id=strategy.strategy_id,
                        model_version_id=strategy.model_version_id,
                        signal_date=signal_date,
                        status="failed",
                        error=error,
                    )
                )
                continue

        if not telegram_token or not telegram_chat_id:
            _record(
                ledger=ledger,
                model=strategy.model_version_id,
                signal=signal,
                status="skipped_not_configured",
                issue=issue,
                workflow_run_id=workflow_run_id,
                commit_sha=commit_sha,
                created_at_utc=created_at_utc,
            )
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=signal_date,
                    status="skipped_not_configured",
                    github_issue_number=issue,
                )
            )
            continue

        try:
            message = _send_telegram(telegram_token, telegram_chat_id, telegram_text)
        except RuntimeError as exc:
            error = str(exc)
            _record(
                ledger=ledger,
                model=strategy.model_version_id,
                signal=signal,
                status="failed",
                issue=issue,
                error=error,
                workflow_run_id=workflow_run_id,
                commit_sha=commit_sha,
                created_at_utc=created_at_utc,
            )
            results.append(
                DeliveryResult(
                    strategy_id=strategy.strategy_id,
                    model_version_id=strategy.model_version_id,
                    signal_date=signal_date,
                    status="failed",
                    github_issue_number=issue,
                    error=error,
                )
            )
            continue

        _record(
            ledger=ledger,
            model=strategy.model_version_id,
            signal=signal,
            status="sent",
            issue=issue,
            message=message,
            workflow_run_id=workflow_run_id,
            commit_sha=commit_sha,
            created_at_utc=created_at_utc,
        )
        results.append(
            DeliveryResult(
                strategy_id=strategy.strategy_id,
                model_version_id=strategy.model_version_id,
                signal_date=signal_date,
                status="sent",
                github_issue_number=issue,
                telegram_message_id=message,
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--created-at-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    results = drain_outbox(
        repository=args.repository,
        workflow_run_id=args.workflow_run_id,
        commit_sha=args.commit_sha,
        created_at_utc=args.created_at_utc,
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
    )
    payload = {
        "schema_version": "strategy_delivery_outbox_v1",
        "results": [result.to_dict() for result in results],
        "research_only": True,
        "trade_ready": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
