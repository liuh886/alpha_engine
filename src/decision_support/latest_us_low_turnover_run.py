"""Refresh the frozen US pool and run the latest complete decision cycle."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.data.us_pool_price_snapshot import (
    DailyBarsAdapter,
    build_us_pool_price_snapshot,
)
from src.decision_support.us_low_turnover_decision_pipeline import (
    run_us_low_turnover_decision_pipeline,
)
from src.research.sec_companyfacts_fundamentals import SecClientProtocol


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode(
        "utf-8"
    )
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"immutable latest-run manifest conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def run_latest_us_low_turnover_decision(
    *,
    registry_db: str | Path,
    ledger_dir: str | Path,
    workspace_dir: str | Path,
    snapshot_root: str | Path,
    requested_through: str | None = None,
    start_date: str = "2024-01-01",
    fundamentals_csv: str | Path | None = None,
    price_adapter: DailyBarsAdapter | None = None,
    sec_client: SecClientProtocol | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Refresh prices, resolve the common session, and generate one ticket."""

    snapshot_decision = build_us_pool_price_snapshot(
        output_root=snapshot_root,
        requested_through=requested_through,
        start_date=start_date,
        adapter=price_adapter,
        now_utc=now_utc,
    )
    if snapshot_decision.get("trade_ready") is not False:
        raise ValueError("price snapshot must remain trade_ready=false")
    as_of = str(snapshot_decision["resolved_as_of_date"])
    prices_path = Path(str(snapshot_decision["prices_csv"])).resolve()
    snapshot_dir = prices_path.parent
    snapshot_manifest = _load_json(snapshot_dir / "evidence_manifest.json")
    if snapshot_manifest.get("outputs", {}).get("prices.csv") != _sha256_file(prices_path):
        raise ValueError("US price snapshot hash mismatch before decision run")

    pipeline_manifest = run_us_low_turnover_decision_pipeline(
        as_of_date=as_of,
        prices_csv=prices_path,
        fundamentals_csv=fundamentals_csv,
        registry_db=registry_db,
        ledger_dir=ledger_dir,
        workspace_dir=workspace_dir,
        sec_client=sec_client,
    )
    if pipeline_manifest.get("trade_ready") is not False:
        raise ValueError("latest US decision pipeline must remain trade_ready=false")

    wrapper: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": "latest_us_low_turnover_decision_v1",
        "market": "us",
        "as_of_date": as_of,
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "automatic_order_routing": False,
        "performance_evaluated": False,
        "inputs": {
            "requested_through": snapshot_decision["requested_through"],
            "snapshot_manifest_identity_sha256": snapshot_manifest["manifest_identity_sha256"],
            "snapshot_manifest_sha256": _sha256_file(snapshot_dir / "evidence_manifest.json"),
            "prices_sha256": _sha256_file(prices_path),
            "fundamentals_sha256": (
                None if fundamentals_csv is None else _sha256_file(Path(fundamentals_csv).resolve())
            ),
        },
        "outputs": {
            "pipeline_run_identity_sha256": pipeline_manifest["pipeline_run_identity_sha256"],
            "ticket_identity_sha256": pipeline_manifest["outputs"]["ticket_identity_sha256"],
        },
    }
    wrapper["latest_run_identity_sha256"] = _canonical_hash(wrapper)
    output = (
        Path(workspace_dir).resolve()
        / "latest_us_low_turnover_decision"
        / as_of
        / "latest_run_manifest.json"
    )
    _write_immutable_json(output, wrapper)
    return wrapper
