"""Run the live US fundamental validation on the active selected pool only."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.selected_us_pool_price_snapshot import (
    DailyBarsAdapter,
    build_selected_us_pool_price_snapshot,
)
from src.research.latest_us_fundamental_validation import (
    CompressedSecHttpClient,
    FrozenPoolSecClient,
    _identity,
    _sha,
    _write_immutable,
    load_frozen_cik_mapping,
)
from src.research.minimal_fundamental_validation import run_minimal_fundamental_validation
from src.research.sec_companyfacts_fundamentals import (
    SecClientProtocol,
    build_sec_companyfacts_fundamentals,
)

SEC_CONTRACT = Path("configs/providers/sec_companyfacts_fundamentals_v2.yaml")
CIK_MAPPING = Path("configs/providers/us_small_pool_sec_cik_v2.yaml")
POOL = Path("configs/pools/us_small_pool_v2.yaml")
VALIDATION_CONTRACT = Path("configs/factors/us_fundamental_acceleration_v2.yaml")


def _default_sec_client() -> FrozenPoolSecClient | None:
    contract = yaml.safe_load(SEC_CONTRACT.read_text(encoding="utf-8"))
    user_agent_env = str(contract["http"]["user_agent_env"])
    user_agent = os.environ.get(user_agent_env, "").strip()
    if not user_agent:
        return None
    http = contract["http"]
    delegate = CompressedSecHttpClient(
        user_agent=user_agent,
        ticker_mapping_url=str(http["ticker_mapping_url"]),
        companyfacts_url_template=str(http["companyfacts_url_template"]),
        minimum_interval_seconds=float(http["minimum_request_interval_seconds"]),
        timeout_seconds=int(http["timeout_seconds"]),
    )
    return FrozenPoolSecClient(
        delegate=delegate,
        mapping=load_frozen_cik_mapping(
            mapping_path=CIK_MAPPING,
            pool_path=POOL,
        ),
        contract=contract,
    )


def _build_factor_applicability(sec_dir: Path) -> dict[str, Any]:
    coverage = json.loads(
        (sec_dir / "coverage_report.json").read_text(encoding="utf-8")
    )
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    factor_contract = yaml.safe_load(
        VALIDATION_CONTRACT.read_text(encoding="utf-8")
    )
    policy = factor_contract["applicability"]
    ready = {
        str(row["symbol"]).upper()
        for row in coverage.get("rows", [])
        if row.get("factor_ready") is True
    }
    minimum_per_basket = int(policy["minimum_ready_symbols_per_active_basket"])
    baskets: dict[str, Any] = {}
    eligible: set[str] = set()
    for basket, metadata in pool["baskets"].items():
        members = [str(symbol).upper() for symbol in metadata["symbols"]]
        ready_members = sorted(set(members) & ready)
        active = len(ready_members) >= minimum_per_basket
        if active:
            eligible.update(ready_members)
        baskets[str(basket)] = {
            "members": members,
            "factor_ready_symbols": ready_members,
            "active_for_factor": active,
            "reason": None if active else "INSUFFICIENT_FACTOR_READY_PEERS",
        }
    active_baskets = sorted(
        basket for basket, row in baskets.items() if row["active_for_factor"]
    )
    minimum_active = int(policy["minimum_active_baskets"])
    all_members = {
        str(symbol).upper()
        for metadata in pool["baskets"].values()
        for symbol in metadata["symbols"]
    }
    result = {
        "schema_version": "1.0",
        "decision": (
            "fundamental_factor_applicability_ready"
            if len(active_baskets) >= minimum_active
            else "fundamental_factor_applicability_blocked"
        ),
        "research_only": True,
        "trade_ready": False,
        "pool_id": pool["pool_id"],
        "membership_unchanged": True,
        "performance_based_selection": False,
        "source_factor_ready_symbols": sorted(ready),
        "factor_eligible_symbols": sorted(eligible),
        "factor_not_applicable_symbols": sorted(all_members - eligible),
        "active_baskets": active_baskets,
        "active_basket_count": len(active_baskets),
        "minimum_active_baskets": minimum_active,
        "minimum_ready_symbols_per_active_basket": minimum_per_basket,
        "baskets": baskets,
    }
    _write_immutable(sec_dir / "factor_applicability.json", result)
    return result


def _write_factor_eligible_fundamentals(
    sec_dir: Path, eligible_symbols: set[str]
) -> Path:
    source = pd.read_csv(sec_dir / "fundamentals.csv", dtype={"symbol": "string"})
    source["symbol"] = source["symbol"].astype(str).str.upper()
    eligible = source[source["symbol"].isin(eligible_symbols)].copy()
    if eligible.empty:
        raise ValueError("factor applicability produced no eligible fundamentals")
    path = sec_dir / "factor_eligible_fundamentals.csv"
    eligible.to_csv(path, index=False)
    return path


def run_selected_us_fundamental_validation(
    *,
    output_root: str | Path,
    snapshot_root: str | Path,
    registry_db: str | Path,
    requested_through: str | None = None,
    start_date: str = "2020-01-01",
    price_adapter: DailyBarsAdapter | None = None,
    sec_client: SecClientProtocol | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    output = Path(output_root).resolve()
    snapshot = build_selected_us_pool_price_snapshot(
        output_root=snapshot_root,
        requested_through=requested_through,
        start_date=start_date,
        adapter=price_adapter,
        now_utc=now_utc,
    )
    if snapshot.get("pool_id") != "us_small_pool_v2":
        raise ValueError("fundamental validation requires us_small_pool_v2")
    if snapshot.get("trade_ready") is not False:
        raise ValueError("price snapshot must remain trade_ready=false")

    as_of = str(snapshot["resolved_as_of_date"])
    prices_path = Path(str(snapshot["prices_csv"])).resolve()
    run_root = output / as_of
    sec_dir = run_root / "sec_companyfacts"
    effective_client = sec_client or _default_sec_client()
    sec_decision = build_sec_companyfacts_fundamentals(
        contract_path=SEC_CONTRACT,
        output_dir=sec_dir,
        client=effective_client,
    )
    candidate_count = int(sec_decision.get("candidate_count", 0))
    ready_count = int(sec_decision.get("factor_ready_count", 0))
    source_completed = sec_decision.get("source_run_completed") is True
    if candidate_count <= 0 or not source_completed:
        blocker = {
            "schema_version": "1.0",
            "decision": "selected_pool_fundamental_validation_blocked",
            "as_of_date": as_of,
            "research_only": True,
            "trade_ready": False,
            "candidate_count": candidate_count,
            "factor_ready_count": ready_count,
            "sec_decision": sec_decision,
        }
        _write_immutable(run_root / "blocked.json", blocker)
        raise ValueError("SEC fundamentals source did not complete")

    applicability = _build_factor_applicability(sec_dir)
    if applicability["decision"] != "fundamental_factor_applicability_ready":
        blocker = {
            "schema_version": "1.0",
            "decision": "selected_pool_fundamental_validation_blocked",
            "as_of_date": as_of,
            "research_only": True,
            "trade_ready": False,
            "candidate_count": candidate_count,
            "factor_ready_count": ready_count,
            "sec_decision": sec_decision,
            "factor_applicability": applicability,
        }
        _write_immutable(run_root / "blocked.json", blocker)
        raise ValueError("insufficient active baskets for the fundamental factor")

    eligible_symbols = set(applicability["factor_eligible_symbols"])
    fundamentals_path = _write_factor_eligible_fundamentals(sec_dir, eligible_symbols)
    validation_dir = run_root / "validation"
    decision = run_minimal_fundamental_validation(
        contract_path=VALIDATION_CONTRACT,
        fundamentals_csv=fundamentals_path,
        prices_csv=prices_path,
        output_dir=validation_dir,
        registry_db=registry_db,
    )
    wrapper: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": "selected_us_fundamental_validation_v2",
        "pool_id": "us_small_pool_v2",
        "as_of_date": as_of,
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "source_grade": "current_sec_companyfacts_reconstruction_with_filed_dates",
        "pool_membership_unchanged": True,
        "factor_eligible_count": len(eligible_symbols),
        "active_basket_count": applicability["active_basket_count"],
        "inputs": {
            "prices_sha256": _sha(prices_path),
            "raw_fundamentals_sha256": _sha(sec_dir / "fundamentals.csv"),
            "factor_eligible_fundamentals_sha256": _sha(fundamentals_path),
            "factor_applicability_sha256": _sha(sec_dir / "factor_applicability.json"),
            "sec_manifest_sha256": _sha(sec_dir / "evidence_manifest.json"),
            "frozen_cik_mapping_sha256": _sha(CIK_MAPPING.resolve()),
            "validation_contract_sha256": _sha(VALIDATION_CONTRACT.resolve()),
        },
        "outputs": {
            "validation_decision": decision["decision"],
            "validation_manifest_sha256": _sha(validation_dir / "evidence_manifest.json"),
            "validation_decision_sha256": _sha(validation_dir / "decision.json"),
        },
    }
    wrapper["run_identity_sha256"] = _identity(wrapper)
    _write_immutable(run_root / "latest_run_manifest.json", wrapper)
    return wrapper
