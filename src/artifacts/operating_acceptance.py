"""Derive session acceptance from existing diagnostic observations and reviews."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.research.market_session_clock import completed_market_date, exchange_sessions


def validate_final_actions_metadata(row: dict[str, Any], metadata: dict[str, Any]) -> None:
    run = metadata["run"]
    if any(run.get(key) != value for key, value in {"id": row["run_id"], "run_attempt": row["run_attempt"], "head_sha": row["head_sha"], "conclusion": "success", "status": "completed", "path": ".github/workflows/formal-backtest-refresh.yml"}.items()) or not metadata.get("jobs") or any(job.get("status") != "completed" for job in metadata["jobs"]):
        raise ValueError(f"final Actions metadata mismatch: {row['run_id']}:{row['run_attempt']}")


def prepare_operating_review(
    observation_root: Path, *, metadata: dict[str, Any], repository_root: Path,
    output_root: Path, now_utc: datetime,
) -> dict[str, Any]:
    """Assemble actual current evidence; leave independent review undeclared."""
    from src.artifacts.formal_bundle_reader import load_formal_run
    from src.artifacts.strategy_operations import build_operations_payload
    from src.artifacts.strategy_signal_ledger import _delivery_receipts, _validate_correction, read_latest_evaluation
    from src.governance.active_strategy_catalog import load_active_strategy_catalog

    output_root.mkdir(parents=True, exist_ok=True)

    def save(name: str, value: Any) -> dict[str, str]:
        path = output_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return bind(path)

    def bind(path: Path) -> dict[str, str]:
        return {"path": path.resolve().relative_to(output_root.resolve()).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def copy(name: str, source: Path) -> dict[str, str]:
        target = output_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return bind(target)

    row = json.loads((observation_root / "operating-observation.json").read_text())
    if row.get("schema_version") != "operating_observation_v1" or row.get("research_only") is not True or row.get("trade_ready") is not False:
        raise ValueError("invalid operating observation")
    final_binding = save("final-actions-metadata.json", metadata)
    blockers = list(row.get("collection_blockers", []))
    try:
        validate_final_actions_metadata(row, metadata)
    except (ValueError, KeyError) as exc:
        blockers.append(str(exc))
    operations: dict[str, Any] = build_operations_payload(formal_catalog=repository_root / "data/research/formal_model_runs/catalog.json", ledger_root=repository_root / "data/research/strategy_signal_ledgers", generated_at=now_utc.isoformat(), strategy_catalog=repository_root / "configs/strategies/registry.json", repository_root=repository_root)
    ops_binding = save("operations-snapshot.json", operations)
    inputs: dict[str, Any] = {"providers": {}}
    for name, relative in (("plan", "plan/plan.json"), ("fan_in", "strategy-fan-in-receipt.json"), ("us", "provider-us/artifacts/selected_pool_price_refresh_manifest.json"), ("cn", "provider-cn/artifacts/selected_pool_price_refresh_manifest.json")):
        path = observation_root / relative
        if path.is_file():
            binding = bind(path)
            if name in {"us", "cn"}:
                inputs["providers"][name] = binding
            else:
                inputs[name] = binding
    active = load_active_strategy_catalog(repository_root / "configs/strategies/registry.json")
    checks, evidence = [], []
    records = {record["strategy_id"]: record for record in operations["records"]}
    expected_ids = {strategy.strategy_id for strategy in active.strategies}
    if set(row.get("active_strategy_ids", [])) != expected_ids or set(row.get("formal_identities", {})) != expected_ids:
        blockers.append("observation active strategies differ from current registry")
    for strategy_id, formal in row.get("formal_identities", {}).items():
        item: dict[str, Any] = {"strategy_id": strategy_id}
        evidence.append(item)
        try:
            strategy = active.by_model_version_id[formal["model_version_id"]]
            ledger = repository_root / strategy.signal_ledger
            latest = read_latest_evaluation(ledger, model_version_id=strategy.model_version_id)
            if latest is None:
                raise ValueError("sealed decision is missing")
            item["decision"] = copy(f"evidence/{strategy_id}/decision.json", ledger / "latest.json")
            deliveries = _delivery_receipts(ledger, decision=latest)
            if not deliveries:
                raise ValueError("decision delivery receipt is missing")
            delivery, _ = max(deliveries, key=lambda pair: (str(pair[1].get("created_at_utc", "")), str(pair[1].get("workflow", {}).get("run_id", ""))))
            item["delivery"] = copy(f"evidence/{strategy_id}/delivery.json", delivery)
            previous = sorted(path for path in (ledger / "records").glob("*.json") if path.stem < latest["signal_date"])
            if previous:
                previous_path = previous[-1]
                correction = ledger / "corrections" / previous_path.name
                if correction.is_file():
                    _validate_correction(ledger, correction, model_version_id=strategy.model_version_id)
                    item["previous_original_decision"] = copy(f"evidence/{strategy_id}/previous-original.json", previous_path)
                    previous_path = correction
                item["previous_decision"] = copy(f"evidence/{strategy_id}/previous-decision.json", previous_path)
            run = load_formal_run(repository_root, strategy.model_version_id)
            item["formal_manifest"] = copy(f"evidence/{strategy_id}/manifest.json", run.manifest_path)
            item["formal_lineage"] = copy(f"evidence/{strategy_id}/lineage.json", run.manifest_path.parent / "lineage.json")
            single = {**row, "active_strategy_ids": [strategy_id], "formal_identities": {strategy_id: formal}}
            snapshot = save(f"evidence/{strategy_id}/operations.json", {**operations, "records": [records[strategy_id]]})
            due = _review_strategies(single, {"operations_snapshot": snapshot, "decision_delivery_evidence": [item], "operating_inputs": inputs}, output_root)
            checks.append({"strategy_id": strategy_id, "mechanically_verified": True, "due_cycle_strategy_ids": due, "retained_target_strategy_ids": single["verified_retained_target_strategy_ids"]})
        except (ValueError, KeyError, OSError) as exc:
            checks.append({"strategy_id": strategy_id, "mechanically_verified": False, "blocker": str(exc)})
    identity = f"{row['run_id']}:{row['run_attempt']}"
    draft = {"observation_sha256": bind(observation_root / "operating-observation.json")["sha256"], "manual_interventions": None, "reviewed_by": None, "cadence_and_freshness_verified": False, "final_actions_metadata": final_binding, "operations_snapshot": ops_binding, "operating_inputs": inputs, "decision_delivery_evidence": evidence}
    save("review-draft.json", {identity: draft})
    mechanically_ready = bool(checks) and not blockers and all(check["mechanically_verified"] for check in checks)
    report = {"schema_version": "operating_review_readiness_v1", "run_id": row["run_id"], "run_attempt": row["run_attempt"], "captured_at_utc": now_utc.isoformat(), "mechanically_ready": mechanically_ready, "qualification_status": "awaiting_independent_review" if mechanically_ready else "blocked", "manual_interventions": None, "review_required": True, "blockers": blockers, "strategy_checks": checks, "research_only": True, "trade_ready": False}
    save("readiness.json", report)
    return report


def collect_operating_review(
    repository: str, *, input_root: Path, repository_root: Path, now_utc: datetime,
    archive_repository: str | None = None,
) -> dict[str, Any]:
    """Collect the latest completed attempt, never choose an older green run."""
    import io
    import os
    import re
    import subprocess
    import zipfile
    from pathlib import PurePosixPath

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid operating evidence repository")
    input_root.mkdir(parents=True, exist_ok=True)

    def api(path: str, *, binary: bool = False) -> Any:
        try:
            result = subprocess.run(["gh", "api", f"repos/{repository}/{path}"], check=True, capture_output=True, timeout=90)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(f"operating evidence retrieval failed: {type(exc).__name__}") from None
        return result.stdout if binary else json.loads(result.stdout)

    # The remote status filter can transiently omit completed runs. Keep the
    # lookup bounded and select the latest completed run regardless of outcome.
    runs = api("actions/workflows/formal-backtest-refresh.yml/runs?branch=main&per_page=10")["workflow_runs"]
    completed = next((run for run in runs if run.get("status") == "completed"), None)
    if completed is None:
        raise ValueError("no completed formal refresh observation available in latest 10 runs")
    run_id, attempt = completed["id"], completed["run_attempt"]
    metadata = {"run": api(f"actions/runs/{run_id}/attempts/{attempt}"), "jobs": []}
    page = 1
    while True:
        jobs = api(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
        metadata["jobs"].extend(jobs["jobs"])
        if len(metadata["jobs"]) >= jobs["total_count"]:
            break
        if not jobs["jobs"] or page >= 10:
            raise ValueError("incomplete final Actions job metadata")
        page += 1
    run = metadata["run"]
    if run.get("head_branch") != "main" or run.get("event") not in {"push", "schedule", "workflow_dispatch"} or run.get("repository", {}).get("full_name") != repository or run.get("path") != ".github/workflows/formal-backtest-refresh.yml":
        raise ValueError("formal operating observation workflow identity mismatch")
    (input_root / "final-actions-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    name = f"formal-backtest-refresh-{run_id}-attempt-{attempt}"
    artifacts = api(f"actions/runs/{run_id}/artifacts?per_page=100")
    if artifacts["total_count"] > 100:
        raise ValueError("formal artifact listing exceeds bounded collection scope")
    matching = [value for value in artifacts["artifacts"] if value["name"] == name and not value.get("expired")]
    if len(matching) != 1:
        readiness = {"schema_version": "operating_review_readiness_v1", "run_id": run_id, "run_attempt": attempt, "mechanically_ready": False, "qualification_status": "blocked", "blockers": ["latest formal attempt observation artifact is missing or expired"], "manual_interventions": None, "review_required": True, "research_only": True, "trade_ready": False}
    else:
        artifact = matching[0]
        if artifact["size_in_bytes"] > 16 * 1024 * 1024:
            raise ValueError("operating observation archive exceeds collection size limit")
        raw = api(f"actions/artifacts/{artifact['id']}/zip", binary=True)
        if len(raw) != artifact["size_in_bytes"] or artifact.get("digest") != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise ValueError("operating observation archive hash or size mismatch")
        source = input_root / "source"
        source.mkdir(exist_ok=True)
        wanted = {"operating-observation.json", "plan/plan.json", "strategy-fan-in-receipt.json", "provider-us/artifacts/selected_pool_price_refresh_manifest.json", "provider-cn/artifacts/selected_pool_price_refresh_manifest.json"}
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 1000 or sum(member.file_size for member in members) > 32 * 1024 * 1024:
                raise ValueError("operating observation archive exceeds extraction limits")
            names = [member.filename for member in members]
            if len(names) != len(set(names)) or any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name for name in names):
                raise ValueError("unsafe operating observation archive member")
            if "operating-observation.json" not in names:
                raise ValueError("latest formal attempt has no operating observation")
            for name in wanted & set(names):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
        row = json.loads((source / "operating-observation.json").read_text())
        if row.get("run_id") != run_id or row.get("run_attempt") != attempt or row.get("head_sha") != run["head_sha"]:
            raise ValueError("operating observation does not bind the selected final attempt")
        readiness = prepare_operating_review(source, metadata=metadata, repository_root=repository_root, output_root=input_root, now_utc=now_utc)
        readiness["artifact_identity"] = {key: artifact[key] for key in ("id", "name", "digest", "size_in_bytes")}
    readiness["observation_scope"] = "latest_completed_formal_attempt_only; historical packets remain separate evidence"
    (input_root / "readiness.json").write_text(json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if archive_repository:
        from src.data.governed_actions_artifact import retain_private_archive

        key = os.environ.get("GOVERNED_SOURCE_ARCHIVE_WRITE_SSH_KEY", "")
        if not key:
            raise ValueError("private operating evidence archive key unavailable")
        capture = os.environ.get("GITHUB_RUN_ID", now_utc.strftime("%Y%m%d%H%M%S%f")) + "-" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
        if not re.fullmatch(r"[0-9]+-[0-9]+", capture):
            raise ValueError("invalid operating evidence capture identity")
        archive_path = input_root.parent / f"operating-review-{run_id}-{attempt}-{capture}.zip"
        packed_paths = sorted(path for path in input_root.rglob("*.json") if path.name != "archive-binding.json")
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            index = []
            for path in packed_paths:
                member = path.relative_to(input_root).as_posix()
                archive.write(path, member)
                index.append({"path": member, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "byte_size": path.stat().st_size})
            archive.writestr("archive-index.json", json.dumps({"research_only": True, "trade_ready": False, "members": index}) + "\n")
        binding = retain_private_archive(repository=archive_repository, member=f"archives/{archive_path.name}", archive_path=archive_path, ssh_key=key)
        (input_root / "archive-binding.json").write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
        readiness["durable_archive"] = binding
    return readiness


def _frozen_cadence(record: dict[str, Any], market: str) -> tuple[str, int | None]:
    import yaml
    from src.governance.active_strategy_catalog import load_active_strategy_catalog

    repository = Path(__file__).resolve().parents[2]
    strategy = load_active_strategy_catalog(repository / "configs/strategies/registry.json").by_model_version_id.get(str(record.get("model_version_id", "")))
    if strategy is None or strategy.market != market:
        return "", None
    contract = yaml.safe_load((repository / strategy.model_contract).read_text(encoding="utf-8"))
    section = {"us_ranker": "strategy", "cn_ranker": "execution", "cn_27_rotation": "portfolio"}.get(strategy.model_family_id)
    cadence = contract.get(section, {}).get("rebalance_sessions") if section else 1
    return strategy.model_family_id, cadence if type(cadence) is int and cadence >= 1 else None


def _due_cycle_verified(record: dict[str, Any], decision: dict[str, Any], previous: dict[str, Any] | None, *, market: str, cutoff: str) -> bool:
    """Daily observation is not evidence of a periodic rebalance evaluation."""
    family, cadence = _frozen_cadence(record, market)
    schedule = record.get("decision_schedule", {})
    if cadence is None or schedule.get("cadence_sessions") != cadence:
        return False
    signal = decision["signal"]
    if cadence == 1:
        return decision.get("latest_data_date") == cutoff
    if previous is None:
        return False
    if family == "cn_27_rotation":
        anchor = signal.get("diagnostics", {}).get("last_rebalance_date")
        old_anchor = previous["signal"].get("diagnostics", {}).get("last_rebalance_date")
    else:
        anchor, old_anchor = decision.get("signal_date"), previous.get("signal_date")
    if anchor != cutoff or anchor != schedule.get("signal_date") or not isinstance(old_anchor, str) or old_anchor >= anchor or previous.get("latest_data_date", cutoff) >= cutoff:
        return False
    sessions = exchange_sessions(market, old_anchor, anchor)
    return bool(sessions) and sessions[0] == old_anchor and sessions[-1] == anchor and len(sessions) - 1 >= cadence


def _retained_target_within_cadence(record: dict[str, Any], decision: dict[str, Any], *, market: str, cutoff: str) -> bool:
    family, cadence = _frozen_cadence(record, market)
    schedule, stale = record.get("decision_schedule", {}), record.get("staleness", {})
    anchor = decision["signal"].get("diagnostics", {}).get("last_rebalance_date") if family == "cn_27_rotation" else decision.get("signal_date")
    if cadence is None or cadence <= 1 or schedule.get("cadence_sessions") != cadence or schedule.get("signal_date") != anchor or schedule.get("completed_through") != cutoff or schedule.get("state") != "within_cadence" or not isinstance(anchor, str) or anchor > cutoff:
        return False
    sessions = exchange_sessions(market, anchor, cutoff)
    latest = decision["latest_data_date"]
    if not sessions or sessions[0] != anchor or sessions[-1] != cutoff or not 0 < len(sessions) - 1 < cadence or not anchor <= latest < cutoff:
        return False
    age = len(exchange_sessions(market, latest, cutoff)) - 1
    return (
        record.get("latest_completed_session") == latest
        and record.get("status") in {"current_no_change", "target_pending_execution", "execution_observed"}
        and record.get("state_detail") == "degraded_delayed"
        and record.get("data_freshness") == "stale" and record.get("factor_freshness") == "stale"
        and record.get("signal_data_freshness") == "current"
        and stale.get("as_of") == latest and stale.get("expected_cutoff") == cutoff
        and stale.get("sessions_behind") == age and stale.get("stale") is True
        and decision["signal"].get("data_freshness_ok") is True
        and decision["signal"].get("factor_freshness_ok") is True
    )


def _review_strategies(row: dict[str, Any], review: dict[str, Any], root: Path) -> list[str]:
    from src.artifacts.strategy_operations import validate_operations_payload
    from src.artifacts.strategy_signal_ledger import _validate_decision_record

    def read(binding: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
        path = (root / binding["path"]).resolve()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != binding["sha256"]:
            raise ValueError("strategy review evidence hash mismatch")
        return path, json.loads(path.read_text())

    def settled_ranker(task: dict[str, Any], fan: dict[str, Any], formal: dict[str, Any], item: dict[str, Any]) -> bool:
        """A completed formal catch-up is distinct from a new rebalance decision."""
        from src.artifacts.model_run_bundle_v2 import validate_manifest

        receipts = [value for value in fan.get("receipts", []) if value.get("strategy_id") == task["strategy_id"]]
        if len(receipts) != 1 or not all(isinstance(item.get(key), dict) for key in ("formal_manifest", "formal_lineage")):
            return False
        receipt = receipts[0]
        if formal["evidence_cutoff"] != task["planned_provider_cutoff"]:
            return False
        if task.get("market") != formal["market"] or any(receipt.get(key) != task.get(key) for key in ("strategy_id", "model_version_id", "market", "formal_refresh_required", "planned_provider_cutoff")) or receipt.get("schema_version") != "formal_strategy_refresh_receipt_v2" or receipt.get("execution_status") != "refreshed" or receipt.get("candidate_evidence_cutoff") != formal["evidence_cutoff"] or receipt.get("publication_input") != "native_bundle_v2" or receipt.get("research_only") is not True or receipt.get("trade_ready") is not False:
            return False
        _, manifest = read(item["formal_manifest"])
        validate_manifest(manifest)
        lineage_path, lineage = read(item["formal_lineage"])
        if any(manifest.get(key) != formal.get(key) for key in ("bundle_id", "run_id", "model_version_id", "evidence_cutoff")) or manifest.get("publication_channel") != "formal" or manifest.get("publication_status") != "accepted_formal_baseline" or manifest.get("model_kind") != "cross_sectional_ranker" or manifest["comparability_key"]["market"] != formal["market"] or manifest["model_family_id"] != receipt.get("model_family_id"):
            return False
        sections = [value for value in manifest["sections"] if value["section_id"] == "lineage"]
        if len(sections) != 1 or sections[0].get("availability_status") != "available" or sections[0].get("sha256") != item["formal_lineage"]["sha256"] or sections[0].get("byte_size") != lineage_path.stat().st_size:
            return False
        candidate = receipt.get("candidate_bundle_id")
        if not isinstance(candidate, str) or len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate) or lineage.get("source_preview_bundle_id") != candidate or lineage.get("publication_contract") != "native_formal_bundle_v2" or lineage.get("model_selection_reopened") is not False or lineage.get("research_only") is not True or lineage.get("trade_ready") is not False:
            return False
        verdict = receipt.get("replay_verdict")
        if manifest["model_family_id"] == "us_ranker":
            return bool(verdict == "deterministic_native_bundle_rebuild")
        if manifest["model_family_id"] != "cn_ranker" or not isinstance(verdict, dict):
            return False
        digest, prefix = verdict.get("duplicate_score_ledger_sha256"), verdict.get("frozen_prefix_rows", {})
        source_evidence = lineage.get("source_evidence", {})
        if not isinstance(prefix, dict) or not isinstance(source_evidence, dict):
            return False
        return verdict.get("model_selection_reopened") is False and isinstance(digest, str) and len(digest) == 64 and all(character in "0123456789abcdef" for character in digest) and all(type(prefix.get(key)) is int and prefix[key] > 0 for key in ("report", "positions", "trades")) and source_evidence.get("duplicate_score_ledger_sha256") == digest and all(source_evidence.get(key) is True for key in ("exact_score_reproduction", "exact_portfolio_reproduction")) and source_evidence.get("model_selection_reopened") is False

    _, operations = read(review["operations_snapshot"])
    validate_operations_payload(operations)
    expected = row.get("formal_identities", {})
    if not expected or set(expected) != set(row.get("active_strategy_ids", [])):
        raise ValueError("operating observation lacks active formal identities")
    records = {record["strategy_id"]: record for record in operations["records"]}
    evidence = {item["strategy_id"]: item for item in review["decision_delivery_evidence"]}
    if set(records) != set(expected) or set(evidence) != set(expected) or len(evidence) != len(review["decision_delivery_evidence"]):
        raise ValueError("strategy decision/delivery review must cover every active strategy")
    verified_due = []
    row["verified_retained_target_strategy_ids"] = []
    for strategy_id, formal in expected.items():
        record = records[strategy_id]
        source = record.get("source_identity", {})
        if any(source.get(key) != formal.get(field) for key, field in {
            "formal_bundle_id": "bundle_id", "formal_run_id": "run_id", "formal_evidence_cutoff": "evidence_cutoff",
        }.items()) or record.get("model_version_id") != formal.get("model_version_id"):
            raise ValueError("strategy review formal identity mismatch")
        market = formal["market"]
        decision_path, decision = read(evidence[strategy_id]["decision"])
        _validate_decision_record(decision, path=decision_path, model_version_id=formal["model_version_id"])
        current = record.get("latest_completed_session") == row["actual_cutoffs"][market] and all(record.get(field) == "current" for field in ("data_freshness", "factor_freshness", "signal_data_freshness")) and record.get("decision_schedule", {}).get("state") == "within_cadence" and record.get("state_detail") == "current" and record.get("staleness", {}).get("stale") is False
        if not current:
            if not _retained_target_within_cadence(record, decision, market=market, cutoff=row["actual_cutoffs"][market]):
                raise ValueError("strategy review cadence or freshness is not current")
            inputs = review.get("operating_inputs", {})
            bindings = {
                "plan/plan.json": inputs.get("plan"),
                "strategy-fan-in-receipt.json": inputs.get("fan_in"),
                f"provider-{market}/artifacts/selected_pool_price_refresh_manifest.json": inputs.get("providers", {}).get(market),
            }
            verified = {}
            for member, binding in bindings.items():
                if not isinstance(binding, dict) or row.get("receipt_sha256", {}).get(member) != binding.get("sha256"):
                    raise ValueError("retained target lacks observation-bound operating inputs")
                _, verified[member] = read(binding)
            plan, fan, provider = verified.values()
            tasks = [task for task in plan.get("tasks", []) if task.get("strategy_id") == strategy_id]
            from src.artifacts.formal_refresh import market_provider_cutoff
            if any(item.get("research_only") is not True or item.get("trade_ready") is not False for item in (plan, fan, provider)) or len(tasks) != 1 or tasks[0].get("model_version_id") != formal["model_version_id"] or tasks[0].get("planned_provider_cutoff") != row["actual_cutoffs"][market] or fan.get("status") != "complete" or fan.get("retained_strategy_ids") or provider.get("all_sources_ready") is not True or provider.get("failure_count") != 0 or provider.get("unresolved_stale_symbols") or market_provider_cutoff(provider, market=market) != row["actual_cutoffs"][market]:
                raise ValueError("retained target operating inputs are blocked or not current")
            if tasks[0].get("formal_refresh_required") is not False and (tasks[0].get("formal_refresh_required") is not True or not settled_ranker(tasks[0], fan, formal, evidence[strategy_id])):
                raise ValueError("retained target formal settlement lacks verified publication evidence")
            row["verified_retained_target_strategy_ids"].append(strategy_id)
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
        previous = None
        if evidence[strategy_id].get("previous_decision"):
            previous_path, previous = read(evidence[strategy_id]["previous_decision"])
            _validate_decision_record(previous, path=previous_path, model_version_id=formal["model_version_id"])
        if _due_cycle_verified(record, decision, previous, market=market, cutoff=row["actual_cutoffs"][market]):
            verified_due.append(strategy_id)
    return verified_due


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
            validate_final_actions_metadata(row, metadata)
            row["verified_due_cycle_strategy_ids"] = _review_strategies(row, review, declarations.parent)  # type: ignore[union-attr]
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
        reviewed_window = [row for row in dated if row["review_verified"] and not row.get("collection_blockers") and row.get("actual_cutoffs", {}).get(market) == row["expected_cutoffs"][market] and row["expected_cutoffs"][market] in window]
        required_due = {strategy for row in reviewed_window for strategy in row.get("active_strategy_ids", [])}
        covered_due = {strategy for row in reviewed_window for strategy in row.get("verified_due_cycle_strategy_ids", [])}
        markets[market] = {"through": end, "observed_sessions": sum(bool(row["observed_attempts"]) for row in records), "qualified_sessions": sum(row["status"] == "qualified" for row in records), "consecutive_qualified_sessions": consecutive, "missing_due_cycle_strategy_ids": sorted(required_due - covered_due), "twenty_session_evidence_complete": consecutive >= 20 and bool(required_due) and required_due <= covered_due, "sessions": records}
    return {
        "schema_version": "operating_acceptance_report_v1", "scope": "existing_strategy_operating_evidence",
        "observation_count": len(observations), "markets": markets,
        "qualification_scope": "whole_operating_loop_all_active_strategies; calendar_counts_are_market_specific",
        "run_evidence": [{key: row.get(key) for key in ("run_id", "run_attempt", "observation_sha256", "verified_retained_target_strategy_ids", "verified_due_cycle_strategy_ids", "collection_blockers", "stages", "final_stages", "publication")} for row in observations],
        "manual_interventions": {f"{row['run_id']}:{row['run_attempt']}": row["manual_interventions"] for row in observations},
        "limitations": ["Missing and cancelled sessions cannot be skipped to construct a continuous pass.", "Repeated runs are attempts of one exchange session, not additional sessions.", "Collection alone does not verify decision freshness, cadence or delivery; independent hash-bound review is required.", "Captured publish-job duration is incomplete until final Actions metadata is retained."],
        "research_only": True, "trade_ready": False,
    }
