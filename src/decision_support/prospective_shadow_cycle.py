"""Governed end-to-end runner for prospective shadow decision cycles."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.decision_support.shadow_decision_desk import build_shadow_decision_ticket
from src.research.hierarchical_pool_rotation import run_hierarchical_pool_rotation

ACKNOWLEDGEMENT = "REPURPOSE_2026H2_FOR_PROSPECTIVE_SHADOW_NO_INDEPENDENT_CLAIM"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def load_cutover_contract(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cutover contract must be a YAML mapping")
    if payload.get("status") != "active_forward_shadow":
        raise ValueError("cutover contract is not active")
    truth = payload.get("truth_boundary", {})
    required_truth = {
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "automatic_order_routing": False,
        "personalized_trade_instruction": False,
    }
    if truth != required_truth:
        raise ValueError("cutover truth boundary is invalid")
    disposition = payload.get("reserved_evidence_disposition", {})
    if disposition.get("repurposed_for_forward_shadow_use") is not True:
        raise ValueError("reserved evidence has not been repurposed for shadow use")
    if disposition.get("independent_validation_claim_prohibited_for_existing_families") is not True:
        raise ValueError("independent-validation claim prohibition is missing")
    if payload.get("acknowledgement", {}).get("recorded") is not True:
        raise ValueError("cutover acknowledgement is not recorded")
    if payload.get("acknowledgement", {}).get("exact_value") != ACKNOWLEDGEMENT:
        raise ValueError("cutover acknowledgement value is invalid")
    if (
        payload.get("future_multifactor_validation", {}).get(
            "requires_new_reserved_window_after_factor_and_portfolio_freeze"
        )
        is not True
    ):
        raise ValueError("future multifactor reserved-window requirement is missing")
    return payload


def _validate_market_contract(
    contract: Mapping[str, Any],
    *,
    market: str,
    spec_path: Path,
) -> dict[str, Any]:
    markets = contract.get("markets", {})
    market_contract = markets.get(market)
    if not isinstance(market_contract, dict):
        raise ValueError(f"market is absent from cutover contract: {market}")
    if market_contract.get("enabled") is not True:
        blocker = market_contract.get("blocked_by", "not enabled")
        raise ValueError(f"market shadow cycle is blocked: {blocker}")
    declared_spec = str(market_contract.get("rotation_spec", ""))
    repository_root = Path(__file__).resolve().parents[2]
    declared_path = (repository_root / declared_spec).resolve()
    if declared_path != spec_path.resolve():
        raise ValueError("requested rotation spec does not match cutover contract")
    return market_contract


def _validate_price_dates(
    prices_path: Path,
    *,
    as_of: date,
    require_as_of: bool,
) -> dict[str, Any]:
    frame = pd.read_csv(prices_path, usecols=["date"], dtype={"date": "string"})
    if frame.empty:
        raise ValueError("prices CSV is empty")
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any():
        raise ValueError("prices CSV contains invalid dates")
    first = dates.min().date()
    last = dates.max().date()
    if last > as_of:
        raise ValueError(f"prices CSV contains future date {last} beyond {as_of}")
    if require_as_of and last != as_of:
        raise ValueError(f"prices CSV last date {last} does not match as-of {as_of}")
    return {
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "row_count": int(len(frame)),
    }


def run_prospective_shadow_cycle(
    *,
    market: str,
    as_of_date: str,
    prices_csv: str | Path,
    spec_path: str | Path,
    registry_db: str | Path,
    ledger_dir: str | Path,
    workspace_dir: str | Path,
    cutover_contract: str | Path,
    factor_scores_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run rotation and persist one immutable prospective shadow ticket."""

    as_of = date.fromisoformat(as_of_date)
    prices_path = Path(prices_csv).resolve()
    spec = Path(spec_path).resolve()
    registry = Path(registry_db).resolve()
    ledger = Path(ledger_dir).resolve()
    workspace = Path(workspace_dir).resolve()
    cutover_path = Path(cutover_contract).resolve()
    score_path = None if factor_scores_path is None else Path(factor_scores_path).resolve()
    for label, path in (
        ("prices CSV", prices_path),
        ("rotation spec", spec),
        ("factor registry", registry),
        ("cutover contract", cutover_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    if score_path is not None and not score_path.is_file():
        raise FileNotFoundError(f"factor score artifact not found: {score_path}")

    contract = load_cutover_contract(cutover_path)
    effective = date.fromisoformat(str(contract["effective_as_of_date"]))
    if as_of < effective:
        raise ValueError(f"as-of date precedes cutover effective date {effective}")
    market_contract = _validate_market_contract(contract, market=market, spec_path=spec)
    run_contract = contract.get("run_contract", {})
    price_summary = _validate_price_dates(
        prices_path,
        as_of=as_of,
        require_as_of=bool(run_contract.get("current_prices_must_include_as_of_date")),
    )

    input_identity = {
        "market": market,
        "as_of_date": as_of.isoformat(),
        "prices_sha256": _sha256_file(prices_path),
        "spec_sha256": _sha256_file(spec),
        "registry_sha256": _sha256_file(registry),
        "cutover_sha256": _sha256_file(cutover_path),
        "factor_scores_sha256": None if score_path is None else _sha256_file(score_path),
        "acknowledgement": ACKNOWLEDGEMENT,
    }
    run_identity = _canonical_hash(input_identity)
    run_dir = workspace / market / as_of.isoformat() / run_identity
    rotation_dir = run_dir / "rotation"
    run_dir.mkdir(parents=True, exist_ok=True)

    rotation_decision = run_hierarchical_pool_rotation(
        spec_path=spec,
        prices_csv=prices_path,
        output_dir=rotation_dir,
        authoritative_mode=False,
    )
    if rotation_decision.get("trade_ready") is not False:
        raise ValueError("rotation output violated trade-ready boundary")
    if rotation_decision.get("performance_evaluated") is not False:
        raise ValueError("rotation output unexpectedly evaluated performance")

    ticket = build_shadow_decision_ticket(
        rotation_dir=rotation_dir,
        registry_db=registry,
        ledger_dir=ledger,
        market=market,
        as_of_date=as_of.isoformat(),
        factor_scores_path=score_path,
        annual_turnover_budget=float(run_contract.get("annual_turnover_budget", 4.0)),
    )
    manifest = {
        "schema_version": "1.0",
        "run_identity_sha256": run_identity,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "as_of_date": as_of.isoformat(),
        "mode": "diagnostic_only",
        "research_only": True,
        "trade_ready": False,
        "automatic_order_routing": False,
        "performance_evaluated": False,
        "independent_validation_claim_allowed": False,
        "market_contract": market_contract,
        "price_summary": price_summary,
        "inputs": input_identity,
        "rotation_manifest_sha256": _sha256_file(rotation_dir / "evidence_manifest.json"),
        "ticket_identity_sha256": ticket["ticket_identity_sha256"],
        "ledger_ticket_path": str(ledger / market / f"{as_of.isoformat()}.json"),
    }
    manifest_path = run_dir / "run_manifest.json"
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("run_identity_sha256") != run_identity:
            raise ValueError("prospective run manifest identity conflict")
    else:
        manifest_path.write_text(rendered, encoding="utf-8")
    return manifest
