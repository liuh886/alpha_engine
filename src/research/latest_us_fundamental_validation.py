"""Build live source-bound inputs and run the minimal US fundamental validation."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.data.us_pool_price_snapshot import DailyBarsAdapter, build_us_pool_price_snapshot
from src.research.minimal_fundamental_validation import run_minimal_fundamental_validation
from src.research.sec_companyfacts_fundamentals import (
    SecClientProtocol,
    SecHttpClient,
    SecSourceError,
    build_sec_companyfacts_fundamentals,
)

SEC_CONTRACT = Path("configs/providers/sec_companyfacts_fundamentals_v1.yaml")
CIK_MAPPING = Path("configs/providers/us_small_pool_sec_cik_v1.yaml")
POOL = Path("configs/pools/us_small_pool_v1.yaml")
VALIDATION_CONTRACT = Path("configs/factors/us_fundamental_acceleration_v1.yaml")
_QUARTER_FRAME = re.compile(r"^CY\d{4}Q([1-4])$")


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


class CompressedSecHttpClient(SecHttpClient):
    """Decode SEC gzip/deflate responses before JSON parsing."""

    def _get_json(self, url: str) -> Mapping[str, Any]:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.minimum_interval_seconds:
            time.sleep(self.minimum_interval_seconds - elapsed)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                encoding = str(response.headers.get("Content-Encoding", "")).lower()
                if encoding == "gzip":
                    raw = gzip.decompress(raw)
                elif encoding == "deflate":
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                payload = json.loads(raw.decode("utf-8"))
        except (
            urllib.error.URLError,
            TimeoutError,
            UnicodeDecodeError,
            OSError,
            zlib.error,
            json.JSONDecodeError,
        ) as exc:
            raise SecSourceError(f"SEC request failed: {url}") from exc
        finally:
            self._last_request_at = time.monotonic()
        if not isinstance(payload, dict):
            raise SecSourceError(f"SEC response must be an object: {url}")
        return payload


def _fact_key(unit: str, entry: Mapping[str, Any]) -> tuple[str, ...] | None:
    values = (
        str(unit),
        str(entry.get("start", "")),
        str(entry.get("end", "")),
        str(entry.get("filed", "")),
        str(entry.get("accn", "")),
        str(entry.get("form", "")),
    )
    return values if all(values) else None


def _preferred_facts(
    namespace_facts: Mapping[str, Any], concepts: list[str]
) -> dict[tuple[str, ...], tuple[str, dict[str, Any]]]:
    selected: dict[tuple[str, ...], tuple[str, dict[str, Any]]] = {}
    for concept in concepts:
        payload = namespace_facts.get(concept)
        if not isinstance(payload, dict):
            continue
        units = payload.get("units")
        if not isinstance(units, dict):
            continue
        for unit, entries in units.items():
            if not isinstance(entries, list):
                continue
            for raw in entries:
                if not isinstance(raw, dict):
                    continue
                key = _fact_key(str(unit), raw)
                if key is not None:
                    selected.setdefault(key, (concept, raw))
    return selected


def _infer_standard_quarter_labels(namespace_facts: Mapping[str, Any]) -> None:
    for concept_payload in namespace_facts.values():
        if not isinstance(concept_payload, dict):
            continue
        units = concept_payload.get("units")
        if not isinstance(units, dict):
            continue
        for entries in units.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("fp", "")) not in {"", "None"}:
                    continue
                match = _QUARTER_FRAME.fullmatch(str(entry.get("frame", "")))
                if match:
                    entry["fp"] = f"Q{match.group(1)}"


def _derive_standard_gross_profit(
    namespace_facts: dict[str, Any],
    *,
    revenue_concepts: list[str],
    cost_concepts: list[str],
) -> None:
    revenue = _preferred_facts(namespace_facts, revenue_concepts)
    cost = _preferred_facts(namespace_facts, cost_concepts)
    native = _preferred_facts(namespace_facts, ["GrossProfit"])
    derived_units: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(set(revenue) & set(cost) - set(native)):
        _, revenue_entry = revenue[key]
        _, cost_entry = cost[key]
        try:
            gross_value = float(revenue_entry["val"]) - float(cost_entry["val"])
        except (KeyError, TypeError, ValueError):
            continue
        entry = dict(revenue_entry)
        entry["val"] = gross_value
        derived_units.setdefault(key[0], []).append(entry)
    if derived_units:
        namespace_facts["DerivedGrossProfitFromRevenueMinusCost"] = {
            "label": "Derived gross profit from standard revenue and cost facts",
            "description": "Revenue minus cost of revenue for an identical SEC fact identity",
            "units": derived_units,
        }


def standardise_companyfacts(
    payload: Mapping[str, Any], *, contract: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Apply only declared standard-taxonomy compatibility rules."""

    output = copy.deepcopy(dict(payload))
    facts = output.get("facts")
    if not isinstance(facts, dict):
        return output
    revenue_namespaces = contract["concepts"]["revenue"]["namespaces"]
    cost_namespaces = contract["concepts"]["cost_of_revenue"]["namespaces"]
    for namespace in sorted(set(revenue_namespaces) | set(cost_namespaces)):
        namespace_facts = facts.get(namespace)
        if not isinstance(namespace_facts, dict):
            continue
        _infer_standard_quarter_labels(namespace_facts)
        _derive_standard_gross_profit(
            namespace_facts,
            revenue_concepts=[str(value) for value in revenue_namespaces.get(namespace, [])],
            cost_concepts=[str(value) for value in cost_namespaces.get(namespace, [])],
        )
    return output


class FrozenPoolSecClient:
    """Serve frozen ticker identities and standardised official Company Facts."""

    def __init__(
        self,
        *,
        delegate: SecClientProtocol,
        mapping: Mapping[str, str],
        contract: Mapping[str, Any],
    ) -> None:
        self.delegate = delegate
        self.mapping = dict(mapping)
        self.contract = dict(contract)

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
        return standardise_companyfacts(
            self.delegate.companyfacts(cik10), contract=self.contract
        )


def _default_sec_client() -> FrozenPoolSecClient | None:
    """Build the live client without calling the SEC bulk ticker endpoint."""

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
        mapping=load_frozen_cik_mapping(),
        contract=contract,
    )


def _build_factor_applicability(sec_dir: Path) -> dict[str, Any]:
    coverage = json.loads(
        (sec_dir / "coverage_report.json").read_text(encoding="utf-8")
    )
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    factor_contract = yaml.safe_load(VALIDATION_CONTRACT.read_text(encoding="utf-8"))
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
    source_completed = sec_decision.get("source_run_completed") is True
    if candidate_count <= 0 or not source_completed:
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
        raise ValueError("SEC fundamentals source did not complete")

    applicability = _build_factor_applicability(sec_dir)
    if applicability["decision"] != "fundamental_factor_applicability_ready":
        blocker = {
            "schema_version": "1.0",
            "decision": "live_fundamental_validation_blocked",
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
        "run_id": "latest_us_fundamental_validation_v1",
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
            "validation_manifest_sha256": _sha(
                validation_dir / "evidence_manifest.json"
            ),
            "validation_decision_sha256": _sha(validation_dir / "decision.json"),
        },
    }
    wrapper["run_identity_sha256"] = _identity(wrapper)
    _write_immutable(run_root / "latest_run_manifest.json", wrapper)
    return wrapper
