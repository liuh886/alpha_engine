"""Source-bound SEC Company Facts fundamentals for the frozen US pool."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd
import yaml

from src.data.sec_transport import SecTransport, SecTransportError, read_sec_json_response

REQUIRED_OUTPUT_COLUMNS = (
    "symbol",
    "fiscal_period_end",
    "filed_date",
    "revenue",
    "gross_profit",
    "currency",
    "form_type",
    "accession_id",
)
DIAGNOSTIC_COLUMNS = (
    "cik",
    "fiscal_year",
    "fiscal_period",
    "frame",
    "revenue_concept",
    "gross_profit_concept",
    "derivation",
    "source_url",
)


class SecSourceError(RuntimeError):
    """SEC source request or response failure."""


class SecClientProtocol(Protocol):
    def ticker_mapping(self) -> Mapping[str, Any]: ...
    def companyfacts(self, cik10: str) -> Mapping[str, Any]: ...


class SecHttpClient:
    """Fair-access HTTP adapter with a required declared user agent."""

    def __init__(
        self,
        *,
        user_agent: str,
        ticker_mapping_url: str,
        companyfacts_url_template: str,
        minimum_interval_seconds: float,
        timeout_seconds: int,
        transport: SecTransport | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC_USER_AGENT is required")
        self.user_agent = user_agent.strip()
        self.ticker_mapping_url = ticker_mapping_url
        self.companyfacts_url_template = companyfacts_url_template
        self.minimum_interval_seconds = max(0.0, float(minimum_interval_seconds))
        self.timeout_seconds = int(timeout_seconds)
        self._last_request_at = 0.0
        self.transport = transport or SecTransport.from_env()

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
            with self.transport.open(request, timeout=self.timeout_seconds) as response:
                payload = read_sec_json_response(response)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            zlib.error,
            SecTransportError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise SecSourceError(
                f"SEC request failed for approved endpoint: {type(exc).__name__}"
            ) from None
        finally:
            self._last_request_at = time.monotonic()
        if not isinstance(payload, dict):
            raise SecSourceError(f"SEC response must be an object: {url}")
        return payload

    def ticker_mapping(self) -> Mapping[str, Any]:
        return self._get_json(self.ticker_mapping_url)

    def companyfacts(self, cik10: str) -> Mapping[str, Any]:
        return self._get_json(self.companyfacts_url_template.format(cik10=cik10))


@dataclass(frozen=True)
class SourceContract:
    payload: dict[str, Any]
    path: Path
    pool: dict[str, Any]
    pool_path: Path


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return _sha256_bytes(encoded)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _repository_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise ValueError(f"unable to resolve repository root from {path}")


def load_source_contract(path: str | Path) -> SourceContract:
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SEC source contract must be a YAML mapping")
    if payload.get("status") != "frozen_source_contract":
        raise ValueError("SEC source contract is not frozen")
    truth = payload.get("truth_boundary", {})
    if truth.get("research_only") is not True or truth.get("trade_ready") is not False:
        raise ValueError("SEC source truth boundary is invalid")
    if truth.get("pristine_historical_api_vintage_claim") is not False:
        raise ValueError("SEC source must not claim pristine historical API vintages")
    root = _repository_root(resolved)
    pool_path = root / str(payload["pool_spec"])
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict) or pool.get("pool_id") != "us_small_pool_v1":
        raise ValueError("SEC source requires frozen us_small_pool_v1")
    return SourceContract(payload=payload, path=resolved, pool=pool, pool_path=pool_path)


def _candidate_symbols(pool: Mapping[str, Any]) -> list[str]:
    symbols = [
        str(symbol).upper()
        for basket in pool.get("baskets", {}).values()
        for symbol in basket.get("symbols", [])
    ]
    if len(symbols) != len(set(symbols)):
        raise ValueError("US pool contains duplicate candidate symbols")
    return sorted(symbols)


def _ticker_map(payload: Mapping[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for raw in payload.values():
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker", "")).strip().upper()
        cik = raw.get("cik_str")
        if not ticker or cik in (None, ""):
            continue
        output[ticker] = str(int(cik)).zfill(10)
    if not output:
        raise SecSourceError("SEC ticker mapping contains no usable rows")
    return output


def _concept_candidates(contract: Mapping[str, Any], field: str) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    priority = 0
    namespaces = contract["concepts"][field]["namespaces"]
    for namespace, concepts in namespaces.items():
        for concept in concepts:
            rows.append((str(namespace), str(concept), priority))
            priority += 1
    return rows


def _normalise_fact_rows(
    companyfacts: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    field: str,
) -> pd.DataFrame:
    facts = companyfacts.get("facts")
    if not isinstance(facts, dict):
        return pd.DataFrame()
    accepted_forms = {str(value) for value in contract["forms"]["accepted"]}
    accepted_units = {str(value) for value in contract["unit_contract"]["accepted_currency_units"]}
    rows: list[dict[str, Any]] = []
    for namespace, concept, priority in _concept_candidates(contract, field):
        namespace_facts = facts.get(namespace)
        if not isinstance(namespace_facts, dict):
            continue
        concept_payload = namespace_facts.get(concept)
        if not isinstance(concept_payload, dict):
            continue
        units = concept_payload.get("units")
        if not isinstance(units, dict):
            continue
        for unit, entries in units.items():
            if str(unit) not in accepted_units or not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                form = str(entry.get("form", ""))
                if form not in accepted_forms:
                    continue
                start = pd.to_datetime(entry.get("start"), errors="coerce")
                end = pd.to_datetime(entry.get("end"), errors="coerce")
                filed = pd.to_datetime(entry.get("filed"), errors="coerce")
                value = pd.to_numeric(entry.get("val"), errors="coerce")
                accession = str(entry.get("accn", "")).strip()
                if pd.isna(start) or pd.isna(end) or pd.isna(filed) or pd.isna(value):
                    continue
                if not accession or filed < end:
                    continue
                duration_days = int((end - start).days) + 1
                rows.append(
                    {
                        "field": field,
                        "namespace": namespace,
                        "concept": concept,
                        "concept_priority": priority,
                        "unit": str(unit),
                        "start": start.normalize(),
                        "end": end.normalize(),
                        "filed": filed.normalize(),
                        "value": float(value),
                        "accn": accession,
                        "form": form,
                        "fy": entry.get("fy"),
                        "fp": str(entry.get("fp", "")),
                        "frame": str(entry.get("frame", "")),
                        "duration_days": duration_days,
                    }
                )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["fy"] = pd.to_numeric(frame["fy"], errors="coerce").astype("Int64")
    return frame.sort_values(["end", "filed", "accn", "concept_priority"]).reset_index(drop=True)


def _direct_quarters(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    quarter = frame[
        frame["duration_days"].between(70, 120) & frame["fp"].isin({"Q1", "Q2", "Q3", "Q4"})
    ].copy()
    if quarter.empty:
        return quarter
    quarter = quarter.sort_values(
        ["field", "end", "filed", "accn", "concept_priority"]
    ).drop_duplicates(["field", "end", "filed", "accn", "unit"], keep="first")
    return quarter.reset_index(drop=True)


def _annual_facts(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    annual = frame[frame["duration_days"].between(300, 400) & frame["fp"].isin({"FY", "Q4"})].copy()
    if annual.empty:
        return annual
    annual = annual.sort_values(
        ["field", "end", "filed", "accn", "concept_priority"]
    ).drop_duplicates(["field", "end", "filed", "accn", "unit"], keep="first")
    return annual.reset_index(drop=True)


def _pair_direct_quarters(revenue: pd.DataFrame, gross: pd.DataFrame) -> pd.DataFrame:
    if revenue.empty or gross.empty:
        return pd.DataFrame()
    keys = ["end", "filed", "accn", "form", "fy", "fp", "unit"]
    paired = revenue.merge(
        gross,
        on=keys,
        suffixes=("_revenue", "_gross"),
        how="inner",
        validate="many_to_many",
    )
    if paired.empty:
        return paired
    paired = paired.sort_values(
        ["end", "filed", "accn", "concept_priority_revenue", "concept_priority_gross"]
    ).drop_duplicates(keys, keep="first")
    return pd.DataFrame(
        {
            "fiscal_period_end": paired["end"],
            "filed_date": paired["filed"],
            "revenue": paired["value_revenue"],
            "gross_profit": paired["value_gross"],
            "currency": paired["unit"],
            "form_type": paired["form"],
            "accession_id": paired["accn"],
            "fiscal_year": paired["fy"],
            "fiscal_period": paired["fp"],
            "frame": paired["frame_revenue"].where(
                paired["frame_revenue"] != "", paired["frame_gross"]
            ),
            "revenue_concept": paired["concept_revenue"],
            "gross_profit_concept": paired["concept_gross"],
            "derivation": "direct_quarter",
        }
    )


def _latest_quarter_before(
    direct: pd.DataFrame,
    *,
    field: str,
    fiscal_year: int,
    fiscal_period: str,
    filed: pd.Timestamp,
    unit: str,
) -> pd.Series | None:
    subset = direct[
        direct["fy"].eq(fiscal_year)
        & direct["fp"].eq(fiscal_period)
        & direct["filed"].le(filed)
        & direct["unit"].eq(unit)
    ]
    if subset.empty:
        return None
    return subset.sort_values(["filed", "accn", "concept_priority"]).iloc[-1]


def _derive_q4(
    revenue_all: pd.DataFrame,
    gross_all: pd.DataFrame,
) -> pd.DataFrame:
    revenue_annual = _annual_facts(revenue_all)
    gross_annual = _annual_facts(gross_all)
    revenue_direct = _direct_quarters(revenue_all)
    gross_direct = _direct_quarters(gross_all)
    if revenue_annual.empty or gross_annual.empty:
        return pd.DataFrame()
    keys = ["end", "filed", "accn", "form", "fy", "unit"]
    annual = revenue_annual.merge(
        gross_annual,
        on=keys,
        suffixes=("_revenue", "_gross"),
        how="inner",
        validate="many_to_many",
    )
    if annual.empty:
        return pd.DataFrame()
    annual = annual.sort_values(
        ["end", "filed", "accn", "concept_priority_revenue", "concept_priority_gross"]
    ).drop_duplicates(keys, keep="first")
    rows: list[dict[str, Any]] = []
    for record in annual.to_dict(orient="records"):
        fiscal_year = record.get("fy")
        if pd.isna(fiscal_year):
            continue
        fy = int(fiscal_year)
        filed = pd.Timestamp(record["filed"])
        unit = str(record["unit"])
        revenue_parts = [
            _latest_quarter_before(
                revenue_direct,
                field="revenue",
                fiscal_year=fy,
                fiscal_period=period,
                filed=filed,
                unit=unit,
            )
            for period in ("Q1", "Q2", "Q3")
        ]
        gross_parts = [
            _latest_quarter_before(
                gross_direct,
                field="gross_profit",
                fiscal_year=fy,
                fiscal_period=period,
                filed=filed,
                unit=unit,
            )
            for period in ("Q1", "Q2", "Q3")
        ]
        if any(part is None for part in revenue_parts + gross_parts):
            continue
        revenue_q4 = float(record["value_revenue"]) - sum(
            float(part["value"]) for part in revenue_parts if part is not None
        )
        gross_q4 = float(record["value_gross"]) - sum(
            float(part["value"]) for part in gross_parts if part is not None
        )
        if revenue_q4 <= 0:
            continue
        rows.append(
            {
                "fiscal_period_end": record["end"],
                "filed_date": record["filed"],
                "revenue": revenue_q4,
                "gross_profit": gross_q4,
                "currency": unit,
                "form_type": record["form"],
                "accession_id": record["accn"],
                "fiscal_year": fy,
                "fiscal_period": "Q4",
                "frame": record.get("frame_revenue") or record.get("frame_gross") or "",
                "revenue_concept": record["concept_revenue"],
                "gross_profit_concept": record["concept_gross"],
                "derivation": "fy_minus_q1_q2_q3",
            }
        )
    return pd.DataFrame(rows)


def extract_company_quarters(
    companyfacts: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    revenue_all = _normalise_fact_rows(companyfacts, contract=contract, field="revenue")
    gross_all = _normalise_fact_rows(companyfacts, contract=contract, field="gross_profit")
    direct = _pair_direct_quarters(_direct_quarters(revenue_all), _direct_quarters(gross_all))
    derived = _derive_q4(revenue_all, gross_all)
    frames = [frame for frame in (direct, derived) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=[*REQUIRED_OUTPUT_COLUMNS[1:], *DIAGNOSTIC_COLUMNS[1:-1]])
    output = pd.concat(frames, ignore_index=True)
    output = output.sort_values(
        ["fiscal_period_end", "filed_date", "accession_id", "derivation"]
    ).drop_duplicates(
        ["fiscal_period_end", "filed_date", "accession_id", "currency"],
        keep="first",
    )
    return output.reset_index(drop=True)


def _coverage_row(
    symbol: str,
    cik: str | None,
    quarters: pd.DataFrame,
    *,
    minimum_quarters: int,
    blocker: str | None = None,
) -> dict[str, Any]:
    quarter_count = int(len(quarters))
    direct_count = 0 if quarters.empty else int((quarters["derivation"] == "direct_quarter").sum())
    derived_count = (
        0 if quarters.empty else int((quarters["derivation"] == "fy_minus_q1_q2_q3").sum())
    )
    reasons: list[str] = []
    if blocker:
        reasons.append(blocker)
    if quarter_count < minimum_quarters:
        reasons.append("INSUFFICIENT_QUARTER_COVERAGE")
    return {
        "symbol": symbol,
        "cik": cik,
        "quarter_count": quarter_count,
        "direct_quarter_count": direct_count,
        "derived_q4_count": derived_count,
        "first_fiscal_period_end": (
            None if quarters.empty else quarters["fiscal_period_end"].min().date().isoformat()
        ),
        "last_fiscal_period_end": (
            None if quarters.empty else quarters["fiscal_period_end"].max().date().isoformat()
        ),
        "factor_ready": not reasons,
        "reason_codes": reasons,
    }


def build_sec_companyfacts_fundamentals(
    *,
    contract_path: str | Path,
    output_dir: str | Path,
    client: SecClientProtocol | None = None,
) -> dict[str, Any]:
    """Build the source CSV and coverage artifacts for the frozen US pool."""

    source = load_source_contract(contract_path)
    contract = source.payload
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    user_agent_env = str(contract["http"]["user_agent_env"])
    user_agent = os.environ.get(user_agent_env, "").strip()
    if client is None:
        if not user_agent:
            decision = {
                "schema_version": "1.0",
                "decision": "sec_companyfacts_source_blocked",
                "reason": f"{user_agent_env} is missing",
                "research_only": True,
                "trade_ready": False,
                "source_run_completed": False,
            }
            _write_json(output / "decision.json", decision)
            return decision
        client = SecHttpClient(
            user_agent=user_agent,
            ticker_mapping_url=str(contract["http"]["ticker_mapping_url"]),
            companyfacts_url_template=str(contract["http"]["companyfacts_url_template"]),
            minimum_interval_seconds=float(contract["http"]["minimum_request_interval_seconds"]),
            timeout_seconds=int(contract["http"]["timeout_seconds"]),
        )
    ticker_payload = client.ticker_mapping()
    ticker_map = _ticker_map(ticker_payload)
    symbols = _candidate_symbols(source.pool)
    minimum_quarters = int(contract["coverage"]["minimum_quarters_per_symbol_for_factor"])
    rows: list[pd.DataFrame] = []
    coverage: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {"ticker_mapping": _canonical_hash(ticker_payload)}
    for symbol in symbols:
        cik = ticker_map.get(symbol)
        if cik is None:
            coverage.append(
                _coverage_row(
                    symbol,
                    None,
                    pd.DataFrame(),
                    minimum_quarters=minimum_quarters,
                    blocker="TICKER_CIK_NOT_RESOLVED",
                )
            )
            continue
        try:
            companyfacts = client.companyfacts(cik)
        except Exception as exc:
            coverage.append(
                _coverage_row(
                    symbol,
                    cik,
                    pd.DataFrame(),
                    minimum_quarters=minimum_quarters,
                    blocker=f"COMPANYFACTS_FETCH_FAILED:{type(exc).__name__}",
                )
            )
            continue
        source_hashes[symbol] = _canonical_hash(companyfacts)
        quarters = extract_company_quarters(companyfacts, contract=contract)
        source_url = str(contract["http"]["companyfacts_url_template"]).format(cik10=cik)
        if not quarters.empty:
            quarters = quarters.copy()
            quarters.insert(0, "symbol", symbol)
            quarters["cik"] = cik
            quarters["source_url"] = source_url
            rows.append(quarters)
        blocker = None
        facts = companyfacts.get("facts")
        if isinstance(facts, dict):
            gross_found = any(
                isinstance(facts.get(namespace), dict)
                and any(concept in facts[namespace] for concept in concepts)
                for namespace, concepts in contract["concepts"]["gross_profit"][
                    "namespaces"
                ].items()
            )
            if not gross_found:
                blocker = "GROSS_PROFIT_CONCEPT_NOT_FOUND"
        coverage.append(
            _coverage_row(
                symbol,
                cik,
                quarters,
                minimum_quarters=minimum_quarters,
                blocker=blocker,
            )
        )

    columns = [*REQUIRED_OUTPUT_COLUMNS, *DIAGNOSTIC_COLUMNS]
    fundamentals = (
        pd.concat(rows, ignore_index=True)[columns] if rows else pd.DataFrame(columns=columns)
    )
    if not fundamentals.empty:
        fundamentals = fundamentals.sort_values(
            ["symbol", "fiscal_period_end", "filed_date", "accession_id"]
        ).reset_index(drop=True)
    fundamentals_path = output / "fundamentals.csv"
    fundamentals.to_csv(fundamentals_path, index=False)
    coverage_payload = {
        "schema_version": "1.0",
        "source_contract_id": contract["source_contract_id"],
        "research_only": True,
        "trade_ready": False,
        "candidate_count": len(symbols),
        "factor_ready_count": sum(bool(row["factor_ready"]) for row in coverage),
        "blocked_count": sum(not bool(row["factor_ready"]) for row in coverage),
        "rows": coverage,
    }
    _write_json(output / "coverage_report.json", coverage_payload)
    ready_count = int(coverage_payload["factor_ready_count"])
    decision = {
        "schema_version": "1.0",
        "decision": (
            "sec_companyfacts_source_ready_with_partial_coverage"
            if ready_count > 0
            else "sec_companyfacts_source_blocked_no_factor_ready_symbols"
        ),
        "source_contract_id": contract["source_contract_id"],
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "pristine_historical_api_vintage_claim": False,
        "source_run_completed": True,
        "candidate_count": len(symbols),
        "factor_ready_count": ready_count,
        "fundamental_row_count": len(fundamentals),
        "user_agent_present": bool(user_agent) if client is None else True,
        "user_agent_sha256": (
            None if not user_agent else _sha256_bytes(user_agent.encode("utf-8"))
        ),
    }
    _write_json(output / "decision.json", decision)
    outputs = {
        name: _sha256_file(output / name)
        for name in ("fundamentals.csv", "coverage_report.json", "decision.json")
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "source_contract_id": contract["source_contract_id"],
        "inputs": {
            "contract_sha256": _sha256_file(source.path),
            "pool_sha256": _sha256_file(source.pool_path),
            "source_payload_hashes": source_hashes,
            "user_agent_present": bool(user_agent) if client is None else True,
            "user_agent_sha256": (
                None if not user_agent else _sha256_bytes(user_agent.encode("utf-8"))
            ),
        },
        "outputs": outputs,
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(output / "evidence_manifest.json", manifest)
    return decision
