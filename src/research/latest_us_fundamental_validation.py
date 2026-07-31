"""Build live source-bound inputs and run the minimal US fundamental validation."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.data.us_pool_price_snapshot import DailyBarsAdapter, build_us_pool_price_snapshot
from src.research.minimal_fundamental_validation import run_minimal_fundamental_validation
from src.research.sec_companyfacts_fundamentals import (
    SecClientProtocol,
    SecHttpClient,
    build_sec_companyfacts_fundamentals,
)

SEC_CONTRACT = Path("configs/providers/sec_companyfacts_fundamentals_v1.yaml")
CIK_MAPPING = Path("configs/providers/us_small_pool_sec_cik_v1.yaml")
POOL = Path("configs/pools/us_small_pool_v1.yaml")
VALIDATION_CONTRACT = Path("configs/factors/us_fundamental_acceleration_v1.yaml")


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


def load_frozen_cik_mapping(
    *,
    mapping_path: str | Path = CIK_MAPPING,
    pool_path: str | Path = POOL,
) -> dict[str, str]:
    """Load an exact, versioned mapping for the frozen pool candidates."""

    mapping_file = Path(mapping_path).resolve()
    pool_file = Path(pool_path).resolve()
    payload = yaml.safe_load(mapping_file.read_text(encoding="utf-8"))
    pool = yaml.safe_load(pool_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "frozen_source_identity":
        raise ValueError("SEC CIK mapping is not frozen")
    if not isinstance(pool, dict) or payload.get("pool_id") != pool.get("pool_id"):
        raise ValueError("SEC CIK mapping pool identity mismatch")
    raw = payload.get("symbols")
    if not isinstance(raw, dict):
        raise ValueError("SEC CIK mapping must contain symbols")
    expected = {
        str(symbol).upper()
        for basket in pool.get("baskets", {}).values()
        for symbol in basket.get("symbols", [])
    }
    observed = {str(symbol).upper() for symbol in raw}
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise ValueError(f"SEC CIK mapping coverage mismatch: missing={missing}, extra={extra}")
    mapping: dict[str, str] = {}
    for symbol, raw_cik in raw.items():
        cik = str(raw_cik).strip()
        if len(cik) != 10 or not cik.isdigit():
            raise ValueError(f"invalid frozen CIK for {symbol}: {raw_cik}")
        mapping[str(symbol).upper()] = cik
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("frozen SEC CIK mapping contains duplicate CIK identities")
    return dict(sorted(mapping.items()))


class FrozenPoolSecClient:
    """Serve frozen ticker identities locally and official Company Facts remotely."""

    def __init__(self, *, delegate: SecHttpClient, mapping: Mapping[str, str]) -> None:
        self.delegate = delegate
        self.mapping = dict(mapping)

    def ticker_mapping(self) -> Mapping[str, Any]:
        return {
            str(index): {
                "ticker": symbol,
                "cik_str": int(cik),
                "title": symbol,
            }
            for index, (symbol, cik) in enumerate(sorted(self.mapping.items()))
        }

    def companyfacts(self, cik10: str) -> Mapping[str, Any]:
        return self.delegate.companyfacts(cik10)


def _default_sec_client() -> FrozenPoolSecClient | None:
    """Build the live client without calling the SEC bulk ticker endpoint."""

    contract = yaml.safe_load(SEC_CONTRACT.read_text(encoding="utf-8"))
    user_agent_env = str(contract["http"]["user_agent_env"])
    user_agent = os.environ.get(user_agent_env, "").strip()
    if not user_agent:
        return None
    http = contract["http"]
    delegate = SecHttpClient(
        user_agent=user_agent,
        ticker_mapping_url=str(http["ticker_mapping_url"]),
        companyfacts_url_template=str(http["companyfacts_url_template"]),
        minimum_interval_seconds=float(http["minimum_request_interval_seconds"]),
        timeout_seconds=int(http["timeout_seconds"]),
    )
    return FrozenPoolSecClient(delegate=delegate, mapping=load_frozen_cik_mapping())


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
    effective_client = sec_client or _default_sec_client()
    sec_decision = build_sec_companyfacts_fundamentals(
        contract_path=SEC_CONTRACT,
        output_dir=sec_dir,
        client=effective_client,
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
        contract_path=VALIDATION_CONTRACT,
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
            "frozen_cik_mapping_sha256": _sha(CIK_MAPPING.resolve()),
            "validation_contract_sha256": _sha(VALIDATION_CONTRACT.resolve()),
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
