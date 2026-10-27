"""A-Share RDI Macro/Policy Risk Event Study Module.

Governed under Track B (#1296), ADR-0005, and #1272 contract.
Evaluates realized forward 7/14/28-session outcomes for CSI300 (000300)
following documented PIT macro/policy events.

Strict Fail-Closed Provenance Rules:
- Verifies repository authoritative event archive readiness.
- As documented in docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json,
  historical_pit_event_coverage_complete is currently FALSE.
- Any unverified or synthetic event without an authoritative source archive
  MUST fail closed with 'blocked_event_pit_coverage'.
- Events available after cutoff (available_at > as_of_cutoff) are strictly blocked against lookahead.
- Realized outcomes are strictly descriptive; NEVER promoted to trading signals.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.data.research_slice import DataSliceRequest
from src.research.ashare_rdi.contracts import RiskEvent
from src.research.dual_consumer_reuse_experiment import run_rdi_event_horizon_readiness_experiment

if TYPE_CHECKING:
    from src.research.study_workspace import AShareRDIConfig

RDI_INPUT_READINESS_REL = Path("docs/evidence/ashare_rdi_phase2/csi300_input_readiness_2026-10-24.json")


def _get_git_commit(root: Path) -> str:
    import subprocess
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    try:
        repo_root = Path(__file__).resolve().parents[3]
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    raise RuntimeError(f"git_commit_unavailable: git rev-parse HEAD failed with code {res.returncode}")


def _get_code_source_sha256(root: Path) -> dict[str, str]:
    sources = {
        "rdi_study": Path(__file__).resolve(),
        "study_workspace": (Path(__file__).resolve().parents[1] / "study_workspace.py").resolve(),
        "research_data_slice": (Path(__file__).resolve().parents[2] / "data" / "research_slice.py").resolve(),
        "rdi_contracts": (Path(__file__).resolve().parents[1] / "ashare_rdi" / "contracts.py").resolve(),
        "rdi_outcomes": (Path(__file__).resolve().parents[1] / "ashare_rdi" / "outcomes.py").resolve(),
    }
    return {
        k: hashlib.sha256(p.read_bytes()).hexdigest()
        for k, p in sorted(sources.items())
        if p.exists()
    }


def _verify_event_source_provenance(event: RiskEvent, root: Path) -> tuple[bool, str]:
    """Verify event against repository authoritative evidence and source hashes (#1272)."""
    evidence_path = root / RDI_INPUT_READINESS_REL
    if not evidence_path.exists():
        return False, "missing_rdi_readiness_evidence_file"

    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"corrupted_rdi_readiness_evidence: {exc}"

    # Hard boundary: check if authoritative historical PIT event coverage is complete
    if not evidence.get("historical_pit_event_coverage_complete", False):
        # Unless an explicit verified event archive exists and binds this exact event_id and source_hash,
        # fail-closed with blocked_event_pit_coverage.
        verified_archives = evidence.get("verified_event_archives", {})
        if event.event_id not in verified_archives or verified_archives[event.event_id].get("source_hash") != event.source_hash:
            return False, (
                "blocked_event_pit_coverage: Event has no certified source provenance in repository archive (#1272). "
                "historical_pit_event_coverage_complete is false; unverified events cannot be scored as ready."
            )

    return True, "verified"


def run_ashare_rdi_study(
    cfg: AShareRDIConfig,
    root: Path,
    *,
    bypass_archive_check_for_test: bool = False,
) -> dict[str, Any]:
    """Execute A-share RDI macro/policy event forward outcome study."""
    git_commit = _get_git_commit(root)
    code_sources = _get_code_source_sha256(root)

    # 1. Missing event strictly fails closed
    if cfg.event is None:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": ["blocked_event_pit_coverage"],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "pool_id": cfg.pool_id,
            "symbols": list(cfg.symbols),
            "benchmark": cfg.benchmark,
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
            "pit_limitations": [
                "observation_cutoff_verified_not_revision_certified",
                "vendor_availability_timestamps_not_fully_certified",
            ],
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    ev = cfg.event
    try:
        announced_at = datetime.fromisoformat(ev["announced_at"])
        available_at = datetime.fromisoformat(ev["available_at"])
        if announced_at.tzinfo is None:
            announced_at = announced_at.replace(tzinfo=timezone.utc)
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=timezone.utc)

        event = RiskEvent(
            event_id=ev["event_id"],
            story_id=ev["story_id"],
            family=ev["family"],
            direction=ev["direction"],
            scope=ev["scope"],
            sector_id=ev.get("sector_id"),
            stage=ev["stage"],
            announced_at=announced_at,
            available_at=available_at,
            active_from=date.fromisoformat(ev["active_from"]),
            active_until=date.fromisoformat(ev["active_until"]),
            source_id=ev["source_id"],
            source_hash=ev["source_hash"],
        )
    except Exception as exc:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": [f"invalid_event_definition: {exc}"],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "pool_id": cfg.pool_id,
            "symbols": list(cfg.symbols),
            "benchmark": cfg.benchmark,
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    # 2. PIT lookahead check: available_at must not postdate cutoff
    event_avail_date = event.available_at.date().isoformat()
    if event_avail_date > cfg.as_of_cutoff:
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": ["lookahead_event_available_after_cutoff"],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "pool_id": cfg.pool_id,
            "symbols": list(cfg.symbols),
            "benchmark": cfg.benchmark,
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    # 3. Source archive check: verify event provenance against authoritative readiness facts
    if not bypass_archive_check_for_test:
        verified, prov_reason = _verify_event_source_provenance(event, root)
        if not verified:
            payload = {
                "schema_version": "1.0",
                "study_id": cfg.study_id,
                "status": "blocked",
                "blocked_reasons": ["blocked_event_pit_coverage"],
                "hypothesis_name": cfg.hypothesis_name,
                "market": cfg.market,
                "pool_id": cfg.pool_id,
                "symbols": list(cfg.symbols),
                "benchmark": cfg.benchmark,
                "code_source_sha256": code_sources,
                "experiment_receipt": cfg.to_dict(),
                "event_provenance_error": prov_reason,
                "research_only": True,
                "trade_ready": False,
                "git_commit": git_commit,
                "pit_certified": False,
                "pit_limitations": [
                    "observation_cutoff_verified_not_revision_certified",
                    "vendor_availability_timestamps_not_fully_certified",
                    "historical_pit_event_coverage_incomplete",
                ],
            }
            raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
            payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
            return payload

    # 4. Fetch data slice and evaluate forward outcomes
    req = DataSliceRequest(
        market=cfg.market,
        pool_id=cfg.pool_id,
        symbols=cfg.symbols,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        as_of_cutoff=cfg.as_of_cutoff,
        price_mode=cfg.price_mode,
        required_fields=("open", "high", "low", "close", "volume"),
    )
    res = run_rdi_event_horizon_readiness_experiment(
        req,
        event=event,
        decision_session=event.active_from.isoformat(),
        horizons=cfg.horizons,
        root=root,
    )

    if res.get("status") != "ready":
        reason = res.get("reason", "rdi_evaluation_blocked")
        blocked_code = "blocked_event_pit_coverage" if "blocked_event_pit_coverage" in reason else reason
        payload = {
            "schema_version": "1.0",
            "study_id": cfg.study_id,
            "status": "blocked",
            "blocked_reasons": [blocked_code],
            "hypothesis_name": cfg.hypothesis_name,
            "market": cfg.market,
            "pool_id": cfg.pool_id,
            "symbols": list(cfg.symbols),
            "benchmark": cfg.benchmark,
            "code_source_sha256": code_sources,
            "experiment_receipt": cfg.to_dict(),
            "research_only": True,
            "trade_ready": False,
            "git_commit": git_commit,
            "pit_certified": False,
        }
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
        payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        return payload

    outcomes_dict = {}
    for o in res.get("outcomes", []):
        h = o["horizon_sessions"]
        outcomes_dict[str(h)] = {
            "forward_return": round(float(o["forward_return"]), 6),
            "worst_intrahorizon_return": round(float(o["worst_intrahorizon_return"]), 6),
            "entry_session": o["entry_session"],
            "exit_session": o["exit_session"],
        }

    payload = {
        "schema_version": "1.0",
        "study_id": cfg.study_id,
        "status": "ready",
        "blocked_reasons": [],
        "hypothesis_name": cfg.hypothesis_name,
        "hypothesis_description": cfg.hypothesis_description,
        "market": cfg.market,
        "pool_id": cfg.pool_id,
        "symbols": list(cfg.symbols),
        "benchmark": cfg.benchmark,
        "code_source_sha256": code_sources,
        "experiment_receipt": cfg.to_dict(),
        "decision_session": res.get("decision_session"),
        "horizons": list(cfg.horizons),
        "event_provenance": res.get("event_provenance"),
        "outcomes": outcomes_dict,
        "data_hash": res.get("data_slice_receipt", {}).get("data_hash"),
        "research_only": True,
        "trade_ready": False,
        "git_commit": git_commit,
        "pit_certified": False,
        "pit_limitations": [
            "observation_cutoff_verified_not_revision_certified",
            "vendor_availability_timestamps_not_fully_certified",
        ],
    }
    raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["study_hash"] = hashlib.sha256(raw_bytes).hexdigest()
    payload["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return payload
