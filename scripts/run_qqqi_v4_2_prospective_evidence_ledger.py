#!/usr/bin/env python3
"""Create and update durable v4.2 prospective evidence records."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.v4_2_prospective_evidence_ledger import (
    build_candidate_event_records,
    build_monthly_summary,
    compute_event_observation,
    recovery_precursor_boolean,
    render_event_issue_body,
    render_monthly_summary,
    render_observation_comment,
    validate_event_record,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _event_title(record: dict[str, Any]) -> str:
    if record["event_type"] == "state_change":
        return (
            f"[前瞻证据] {record['signal_date']} "
            f"v4.2 状态 {record['current_state']}→{record['target_state']}"
        )
    return f"[前瞻证据] {record['signal_date']} v4.2 恢复前置信号"


def _is_current_active_precursor(
    record: dict[str, Any],
    latest_status: str,
    current_precursor: bool,
) -> bool:
    return bool(
        current_precursor
        and record.get("event_type") == "recovery_precursor"
        and latest_status == "active_precursor"
    )


def _stabilise_precursor_status(
    observation: dict[str, Any],
    record: dict[str, Any],
    latest_status: str,
    current_active: bool,
) -> dict[str, Any]:
    if record.get("event_type") != "recovery_precursor":
        return observation
    if 40 in observation["completed_horizons"]:
        return observation
    if current_active:
        observation["status"] = "active_precursor"
    elif latest_status in {"active_precursor", "precursor_closed"}:
        observation["status"] = "precursor_closed"
    observation["status_changed"] = observation["status"] != latest_status
    observation["has_material_update"] = bool(
        observation["new_horizons"] or observation["status_changed"]
    )
    return observation


def _observe_item(
    item: dict[str, Any],
    daily: pd.DataFrame,
    *,
    current_precursor: bool,
    latest_data_date: str,
) -> dict[str, Any] | None:
    record = item.get("record", item)
    if not isinstance(record, dict):
        return None
    latest_status = str(item.get("latest_status") or record.get("status") or "")
    current_active = _is_current_active_precursor(
        record,
        latest_status,
        current_precursor,
    )
    observation = compute_event_observation(
        record,
        daily,
        current_precursor_boolean=current_active,
        latest_data_date=latest_data_date,
        posted_horizons=item.get("posted_horizons", []),
        latest_status=latest_status,
    )
    return _stabilise_precursor_status(
        observation,
        record,
        latest_status,
        current_active,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_prospective_evidence_ledger.yaml"
        ),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_vxn_bridge_v4_2_prospective_monitor/"
            "prospective_summary.json"
        ),
    )
    parser.add_argument(
        "--alert",
        type=Path,
        default=Path(
            "artifacts/signals/qqqi_qqq_tqqq_vxn_bridge_v4_2/signal_alert.json"
        ),
    )
    parser.add_argument(
        "--daily",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_vxn_bridge_v4_2_prospective_monitor/"
            "prospective_daily_rotation_vxn_bridge_v4_2_50_50.csv"
        ),
    )
    parser.add_argument(
        "--existing-events",
        type=Path,
        default=Path("artifacts/evidence/prospective_ledger_existing_events.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/qqqi_qqq_tqqq_v4_2_prospective_evidence_ledger"
        ),
    )
    parser.add_argument("--month", default=None)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    summary = _load_json(args.summary)
    alert = _load_json(args.alert)
    existing = _load_json(args.existing_events) if args.existing_events.exists() else []
    if not isinstance(existing, list):
        raise ValueError("existing-events input must be a list")
    daily = pd.read_csv(args.daily)

    candidates = build_candidate_event_records(summary, alert, existing)
    new_events: list[dict[str, Any]] = []
    for record in candidates:
        validate_event_record(record)
        body = render_event_issue_body(record)
        new_events.append(
            {
                "event_id": record["event_id"],
                "title": _event_title(record),
                "record": record,
                "body": body,
            }
        )

    current_precursor = recovery_precursor_boolean(summary)
    latest_data_date = str(summary["latest_data_date"])
    updates: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = [*existing]
    for item in existing:
        observation = _observe_item(
            item,
            daily,
            current_precursor=current_precursor,
            latest_data_date=latest_data_date,
        )
        if observation is None or not observation["has_material_update"]:
            continue
        record = item.get("record", item)
        updates.append(
            {
                "issue_number": item.get("issue_number"),
                "event_id": record["event_id"],
                "observation": observation,
                "comment": render_observation_comment(observation),
            }
        )

    for item in new_events:
        all_items.append(
            {
                "issue_number": None,
                "record": item["record"],
                "posted_horizons": [],
                "latest_status": item["record"]["status"],
            }
        )

    observations: list[dict[str, Any]] = []
    for item in all_items:
        observation = _observe_item(
            item,
            daily,
            current_precursor=current_precursor,
            latest_data_date=latest_data_date,
        )
        if observation is not None:
            observations.append(observation)

    month = args.month or latest_data_date[:7]
    monthly = build_monthly_summary(all_items, observations, month)
    monthly_markdown = render_monthly_summary(monthly)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "new_events.json", new_events)
    _write_json(output / "event_updates.json", updates)
    _write_json(output / "all_observations.json", observations)
    _write_json(output / "monthly_summary.json", monthly)
    (output / "monthly_summary.md").write_text(
        monthly_markdown,
        encoding="utf-8",
    )

    run_summary = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "research_only": True,
        "trade_ready": False,
        "latest_data_date": latest_data_date,
        "current_recovery_precursor_boolean": current_precursor,
        "existing_event_count": len(existing),
        "new_event_count": len(new_events),
        "material_update_count": len(updates),
        "monthly_summary_month": month,
        "model_change_authorized": False,
    }
    _write_json(output / "ledger_run_summary.json", run_summary)

    files = sorted(path for path in output.iterdir() if path.is_file())
    manifest = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "inputs": {
            "summary": {"path": str(args.summary), "sha256": _sha256(args.summary)},
            "alert": {"path": str(args.alert), "sha256": _sha256(args.alert)},
            "daily": {"path": str(args.daily), "sha256": _sha256(args.daily)},
            "existing_events": (
                {
                    "path": str(args.existing_events),
                    "sha256": _sha256(args.existing_events),
                }
                if args.existing_events.exists()
                else None
            ),
        },
        "outputs": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "evidence_manifest.json", manifest)
    print(json.dumps(run_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
