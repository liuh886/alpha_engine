"""Build live source-bound inputs and run the minimal US fundamental validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.data.us_pool_price_snapshot import DailyBarsAdapter, build_us_pool_price_snapshot
from src.research.minimal_fundamental_validation import run_minimal_fundamental_validation
from src.research.sec_companyfacts_fundamentals import (
    SecClientProtocol,
    build_sec_companyfacts_fundamentals,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True, default=str
    ).encode("utf-8")
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"immutable live validation conflict: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def run_latest_us_fundamental_validation(
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
    """Run the source pipeline and produce one observed-evidence decision."""

    output = Path(output_root).resolve()
    snapshot = build_us_pool_price_snapshot(
        output_root=snapshot_root,
        requested_through=requested_through,
        start_date=start_date,
        adapter=price_adapter,
        now_utc=now_utc,
    )
    if snapshot.get("trade_ready") is not False:
        raise ValueError("price snapshot must remain trade_ready=false")
    as_of = str(snapshot["resolved_as_of_date"])
    prices_path = Path(str(snapshot["prices_csv"])).resolve()
    run_root = output / as_of
    sec_dir = run_root / "sec_companyfacts"
    sec_decision = build_sec_companyfacts_fundamentals(
        contract_path="configs/providers/sec_companyfacts_fundamentals_v1.yaml",
        output_dir=sec_dir,
        client=sec_client,
    )
    candidate_count = int(sec_decision.get("candidate_count", 0))
    ready_count = int(sec_decision.get("factor_ready_count", 0))
    if candidate_count <= 0 or ready_count != candidate_count:
        blocker = {
            "schema_version": "1.0",
            "decision": "live_fundamental_validation_blocked",
            "as_of_date": as_of,
            "research_only": True,
            "trade_ready": False,
            "candidate_count": candidate_count,
            "factor_ready_count": ready_count,
            "sec_decision": sec_decision,
        }
        _write_immutable(run_root / "blocked.json", blocker)
        raise ValueError("SEC fundamentals do not cover every frozen candidate")

    fundamentals_path = sec_dir / "fundamentals.csv"
    validation_dir = run_root / "validation"
    decision = run_minimal_fundamental_validation(
        contract_path="configs/factors/us_fundamental_acceleration_v1.yaml",
        fundamentals_csv=fundamentals_path,
        prices_csv=prices_path,
        output_dir=validation_dir,
        registry_db=registry_db,
    )
    wrapper: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": "latest_us_fundamental_validation_v1",
        "as_of_date": as_of,
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "source_grade": "current_sec_companyfacts_reconstruction_with_filed_dates",
        "inputs": {
            "prices_sha256": _sha(prices_path),
            "fundamentals_sha256": _sha(fundamentals_path),
            "sec_manifest_sha256": _sha(sec_dir / "evidence_manifest.json"),
            "validation_contract_sha256": _sha(
                Path("configs/factors/us_fundamental_acceleration_v1.yaml").resolve()
            ),
        },
        "outputs": {
            "validation_decision": decision["decision"],
            "validation_manifest_sha256": _sha(
                validation_dir / "evidence_manifest.json"
            ),
            "validation_decision_sha256": _sha(validation_dir / "decision.json"),
        },
    }
    wrapper["run_identity_sha256"] = _identity(wrapper)
    _write_immutable(run_root / "latest_run_manifest.json", wrapper)
    return wrapper
