"""Derive session acceptance from existing diagnostic observations and reviews."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.research.market_session_clock import completed_market_date, exchange_sessions


def _review_strategies(row: dict[str, Any], review: dict[str, Any], root: Path) -> None:
    from src.artifacts.strategy_operations import validate_operations_payload
    from src.artifacts.strategy_signal_ledger import _validate_decision_record

    def read(binding: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        path = (root / binding["path"]).resolve()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]:
            raise ValueError("strategy review evidence hash mismatch")
        return path, json.loads(path.read_text())

    _, operations = read(review["operations_snapshot"])
    validate_operations_payload(operations)
    expected = row.get("formal_identities", {})
    if not expected or set(expected) != set(row.get("active_strategy_ids", [])):
        raise ValueError("operating observation lacks active formal identities")
    records = {record["strategy_id"]: record for record in operations["records"]}
    evidence = {item["strategy_id"]: item for item in review["decision_delivery_evidence"]}
    if set(records) != set(expected) or set(evidence) != set(expected) or len(evidence) != len(review["decision_delivery_evidence"]):
        raise ValueError("strategy decision/delivery review must cover every active strategy")
    for strategy_id, formal in expected.items():
        record = records[strategy_id]
        source = record.get("source_identity", {})
        if any(source.get(key) != formal.get(field) for key, field in {
            "formal_bundle_id": "bundle_id", "formal_run_id": "run_id", "formal_evidence_cutoff": "evidence_cutoff",
        }.items()) or record.get("model_version_id") != formal.get("model_version_id"):
            raise ValueError("strategy review formal identity mismatch")
        market = formal["market"]
        if record.get("latest_completed_session") != row["actual_cutoffs"][market] or any(record.get(field) != "current" for field in ("data_freshness", "factor_freshness", "signal_data_freshness")) or record.get("decision_schedule", {}).get("state") != "within_cadence" or record.get("state_detail") != "current" or record.get("staleness", {}).get("stale") is not False:
            raise ValueError("strategy review cadence or freshness is not current")
        decision_path, decision = read(evidence[strategy_id]["decision"])
        _validate_decision_record(decision, path=decision_path, model_version_id=formal["model_version_id"])
        if decision.get("latest_data_date") != record.get("as_of") or decision["latest_data_date"] > row["actual_cutoffs"][market] or formal["evidence_cutoff"] > row["actual_cutoffs"][market]:
            raise ValueError("strategy review decision cutoff mismatch")
        _, delivery = read(evidence[strategy_id]["delivery"])
        if source.get("signal_sha256") != decision.get("signal_sha256") or source.get("ledger_fingerprint") != decision.get("fingerprint"):
            raise ValueError("operations snapshot does not bind the sealed decision")
        if delivery.get("schema_version") != "strategy_signal_delivery_v1" or any(delivery.get(key) != decision.get(key) for key in ("model_version_id", "signal_date", "fingerprint", "signal_sha256")) or delivery.get("research_only") is not True or delivery.get("trade_ready") is not False:
            raise ValueError("delivery receipt does not bind the sealed decision")
        status = delivery.get("delivery", {}).get("status")
        if status not in {"sent", "not_required"} or record.get("delivery_status") != status:
            raise ValueError("strategy delivery is not verified")
        if status == "not_required" and decision["signal"].get("should_alert") is not False:
            raise ValueError("required alert cannot be declared not required")


def build_acceptance_report(input_root: Path, *, declarations: Path | None = None, through: str | None = None) -> dict[str, Any]:
    reviews = json.loads(declarations.read_text(encoding="utf-8")) if declarations else {}
    observations = []
    identities = set()
    for path in sorted(input_root.rglob("operating-observation.json")):
        raw = path.read_bytes()
        row = json.loads(raw)
        if row.get("schema_version") != "operating_observation_v1" or row.get("research_only") is not True or row.get("trade_ready") is not False:
            raise ValueError(f"invalid operating observation: {path}")
        identity = f"{row['run_id']}:{row['run_attempt']}"
        if identity in identities:
            raise ValueError(f"duplicate run attempt: {identity}")
        identities.add(identity)
        digest = hashlib.sha256(raw).hexdigest()
        review = reviews.get(identity, {})
        manual = review.get("manual_interventions")
        review_valid = (
            review.get("observation_sha256") == digest
            and type(manual) is int and manual >= 0
            and bool(review.get("reviewed_by"))
            and bool(review.get("decision_delivery_evidence"))
            and review.get("cadence_and_freshness_verified") is True
            and isinstance(review.get("final_actions_metadata"), dict)
            and isinstance(review.get("operations_snapshot"), dict)
        )
        if review_valid:
            for evidence in [review["final_actions_metadata"]]:
                member = (declarations.parent / evidence["path"]).resolve()  # type: ignore[union-attr]
                if not member.is_file() or hashlib.sha256(member.read_bytes()).hexdigest() != evidence["sha256"]:
                    raise ValueError(f"review evidence hash mismatch: {identity}")
            metadata = json.loads((declarations.parent / review["final_actions_metadata"]["path"]).read_text())  # type: ignore[union-attr]
            run = metadata["run"]
            if any(run.get(key) != value for key, value in {"id": row["run_id"], "run_attempt": row["run_attempt"], "head_sha": row["head_sha"], "conclusion": "success", "status": "completed", "path": ".github/workflows/formal-backtest-refresh.yml"}.items()) or not metadata.get("jobs") or any(job.get("status") != "completed" for job in metadata["jobs"]):
                raise ValueError(f"final Actions metadata mismatch: {identity}")
            _review_strategies(row, review, declarations.parent)  # type: ignore[union-attr]
            row["final_stages"] = metadata["jobs"]
        observations.append({**row, "observation_sha256": digest, "review_verified": bool(review_valid), "manual_interventions": manual if review_valid else None})
    markets = {}
    for market in ("us", "cn"):
        dated = [row for row in observations if row.get("expected_cutoffs", {}).get(market)]
        dates = sorted({row["expected_cutoffs"][market] for row in dated})
        end = completed_market_date(market, through or datetime.now(timezone.utc).date().isoformat())
        if dates and dates[-1] > end:
            raise ValueError(f"observation exceeds requested completed cutoff: {market}")
        sessions = exchange_sessions(market, dates[0], end) if dates else []
        records = []
        for session in sessions:
            attempts = [row for row in dated if row["expected_cutoffs"][market] == session]
            qualified = [row for row in attempts if row["review_verified"] and not row.get("collection_blockers") and row.get("actual_cutoffs", {}).get(market) == session]
            records.append({
                "session": session, "observed_attempts": len(attempts),
                "status": "qualified" if qualified else "awaiting_review_or_blocked" if attempts else "missing",
                "run_attempts": [f"{row['run_id']}:{row['run_attempt']}" for row in attempts],
                "cutoff_lag_sessions": [len(exchange_sessions(market, row["actual_cutoffs"][market], session)) - 1 if row.get("actual_cutoffs", {}).get(market) and row["actual_cutoffs"][market] <= session else None for row in attempts],
            })
        consecutive = 0
        for row in reversed(records):
            if row["status"] != "qualified":
                break
            consecutive += 1
        window = {row["session"] for row in records[-20:]}
        reviewed_window = [row for row in dated if row["review_verified"] and not row.get("collection_blockers") and row["expected_cutoffs"][market] in window]
        required_due = {strategy for row in reviewed_window for strategy in row.get("active_strategy_ids", [])}
        covered_due = {strategy for row in reviewed_window for strategy in row.get("due_evaluated_strategy_ids", [])}
        markets[market] = {"through": end, "observed_sessions": sum(bool(row["observed_attempts"]) for row in records), "qualified_sessions": sum(row["status"] == "qualified" for row in records), "consecutive_qualified_sessions": consecutive, "missing_due_cycle_strategy_ids": sorted(required_due - covered_due), "twenty_session_evidence_complete": consecutive >= 20 and bool(required_due) and required_due <= covered_due, "sessions": records}
    return {
        "schema_version": "operating_acceptance_report_v1", "scope": "existing_strategy_operating_evidence",
        "observation_count": len(observations), "markets": markets,
        "qualification_scope": "whole_operating_loop_all_active_strategies; calendar_counts_are_market_specific",
        "run_evidence": [{key: row.get(key) for key in ("run_id", "run_attempt", "observation_sha256", "collection_blockers", "stages", "final_stages", "publication")} for row in observations],
        "manual_interventions": {f"{row['run_id']}:{row['run_attempt']}": row["manual_interventions"] for row in observations},
        "limitations": ["Missing and cancelled sessions cannot be skipped to construct a continuous pass.", "Repeated runs are attempts of one exchange session, not additional sessions.", "Collection alone does not verify decision freshness, cadence or delivery; independent hash-bound review is required.", "Captured publish-job duration is incomplete until final Actions metadata is retained."],
        "research_only": True, "trade_ready": False,
    }
