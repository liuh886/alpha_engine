"""Bind v4.2 ledger records and observations to one hash-verified signal run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.research.v4_2_prospective_evidence_ledger import (
    render_event_issue_body,
    render_observation_comment,
    validate_event_record,
)


class LedgerSourceBindingError(ValueError):
    """Raised when a ledger input does not match its source signal receipt."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(
    *,
    output_root: Path,
    source_receipt_path: Path,
    bundle_manifest_path: Path,
    monitor_summary_path: Path,
    signal_alert_path: Path,
) -> dict[str, Any]:
    receipt = _load(source_receipt_path)
    alert = _load(signal_alert_path)
    expected = {
        "bundle_manifest_sha256": _sha256(bundle_manifest_path),
        "monitor_summary_sha256": _sha256(monitor_summary_path),
        "signal_alert_sha256": _sha256(signal_alert_path),
    }
    for key, observed in expected.items():
        if receipt.get(key) != observed:
            raise LedgerSourceBindingError(
                f"source signal receipt mismatch for {key}: {receipt.get(key)!r} != {observed!r}"
            )
    if receipt.get("fingerprint") != alert.get("fingerprint"):
        raise LedgerSourceBindingError("source signal fingerprint mismatch")
    if not receipt.get("workflow_run_id") or not receipt.get("commit_sha"):
        raise LedgerSourceBindingError("source workflow identity is incomplete")

    source = {
        "workflow_run_id": str(receipt["workflow_run_id"]),
        "commit_sha": str(receipt["commit_sha"]),
        "fingerprint": str(receipt["fingerprint"]),
        "data_bundle_id": receipt.get("data_bundle_id"),
        **expected,
    }

    new_events_path = output_root / "new_events.json"
    new_events = _load(new_events_path)
    for item in new_events:
        record = item["record"]
        record["source_signal_context"] = source
        validate_event_record(record)
        item["body"] = render_event_issue_body(record)
    _write(new_events_path, new_events)

    updates_path = output_root / "event_updates.json"
    updates = _load(updates_path)
    for item in updates:
        observation = item["observation"]
        observation["source_signal_context"] = source
        item["comment"] = render_observation_comment(observation)
    _write(updates_path, updates)

    run_summary_path = output_root / "ledger_run_summary.json"
    run_summary = _load(run_summary_path)
    run_summary["source_signal_context"] = source
    _write(run_summary_path, run_summary)

    manifest_path = output_root / "evidence_manifest.json"
    manifest = _load(manifest_path)
    manifest["source_signal_context"] = source
    manifest["outputs"] = {
        path.name: _sha256(path)
        for path in sorted(output_root.iterdir())
        if path.is_file() and path.name != "evidence_manifest.json"
    }
    _write(manifest_path, manifest)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--bundle-manifest", type=Path, required=True)
    parser.add_argument("--monitor-summary", type=Path, required=True)
    parser.add_argument("--signal-alert", type=Path, required=True)
    args = parser.parse_args()
    source = bind(
        output_root=args.output_root,
        source_receipt_path=args.source_receipt,
        bundle_manifest_path=args.bundle_manifest,
        monitor_summary_path=args.monitor_summary,
        signal_alert_path=args.signal_alert,
    )
    print(json.dumps(source, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
