from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pytest
import yaml

from src.research.sec_companyfacts_fundamentals import (
    build_sec_companyfacts_fundamentals,
    extract_company_quarters,
    load_source_contract,
)

CONTRACT = Path("configs/providers/sec_companyfacts_fundamentals_v1.yaml")
POOL = Path("configs/pools/us_small_pool_v1.yaml")


def _symbols() -> list[str]:
    pool = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    return sorted(
        str(symbol)
        for basket in pool["baskets"].values()
        for symbol in basket["symbols"]
    )


def _fact(
    *,
    start: str,
    end: str,
    filed: str,
    value: float,
    accession: str,
    form: str,
    fy: int,
    fp: str,
    frame: str = "",
) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "filed": filed,
        "val": value,
        "accn": accession,
        "form": form,
        "fy": fy,
        "fp": fp,
        "frame": frame,
    }


def _companyfacts(*, missing_gross: bool = False, fallback_revenue: bool = False) -> dict:
    quarter_periods = [
        ("2024-01-01", "2024-03-31", "2024-05-01", 100.0, 40.0, "q1-2024", 2024, "Q1", "CY2024Q1"),
        ("2024-04-01", "2024-06-30", "2024-08-01", 110.0, 44.0, "q2-2024", 2024, "Q2", "CY2024Q2"),
        ("2024-07-01", "2024-09-30", "2024-11-01", 120.0, 48.0, "q3-2024", 2024, "Q3", "CY2024Q3"),
        ("2025-01-01", "2025-03-31", "2025-05-01", 130.0, 54.0, "q1-2025", 2025, "Q1", "CY2025Q1"),
        ("2025-04-01", "2025-06-30", "2025-08-01", 145.0, 62.0, "q2-2025", 2025, "Q2", "CY2025Q2"),
    ]
    revenue_entries = [
        _fact(
            start=start,
            end=end,
            filed=filed,
            value=revenue,
            accession=accession,
            form="10-Q",
            fy=fy,
            fp=fp,
            frame=frame,
        )
        for start, end, filed, revenue, _, accession, fy, fp, frame in quarter_periods
    ]
    gross_entries = [
        _fact(
            start=start,
            end=end,
            filed=filed,
            value=gross,
            accession=accession,
            form="10-Q",
            fy=fy,
            fp=fp,
            frame=frame,
        )
        for start, end, filed, _, gross, accession, fy, fp, frame in quarter_periods
    ]
    revenue_entries.append(
        _fact(
            start="2024-01-01",
            end="2024-12-31",
            filed="2025-02-15",
            value=460.0,
            accession="fy-2024",
            form="10-K",
            fy=2024,
            fp="FY",
            frame="CY2024",
        )
    )
    gross_entries.append(
        _fact(
            start="2024-01-01",
            end="2024-12-31",
            filed="2025-02-15",
            value=188.0,
            accession="fy-2024",
            form="10-K",
            fy=2024,
            fp="FY",
            frame="CY2024",
        )
    )
    revenue_concept = "Revenues" if fallback_revenue else "RevenueFromContractWithCustomerExcludingAssessedTax"
    facts = {
        "us-gaap": {
            revenue_concept: {"units": {"USD": revenue_entries}},
        }
    }
    if not missing_gross:
        facts["us-gaap"]["GrossProfit"] = {"units": {"USD": gross_entries}}
    return {"cik": 1, "entityName": "Test Company", "facts": facts}


class FakeSecClient:
    def __init__(self, *, missing_gross_symbol: str | None = None) -> None:
        self.symbols = _symbols()
        self.missing_gross_symbol = missing_gross_symbol
        self.cik_to_symbol = {
            str(index + 1).zfill(10): symbol
            for index, symbol in enumerate(self.symbols)
        }

    def ticker_mapping(self) -> Mapping[str, Any]:
        return {
            str(index): {
                "ticker": symbol,
                "cik_str": index + 1,
                "title": symbol,
            }
            for index, symbol in enumerate(self.symbols)
        }

    def companyfacts(self, cik10: str) -> Mapping[str, Any]:
        symbol = self.cik_to_symbol[cik10]
        return _companyfacts(missing_gross=symbol == self.missing_gross_symbol)


def test_extracts_direct_quarters_and_derives_q4() -> None:
    contract = load_source_contract(CONTRACT).payload
    quarters = extract_company_quarters(_companyfacts(), contract=contract)

    assert len(quarters) == 6
    q4 = quarters[quarters["fiscal_period"] == "Q4"].iloc[0]
    assert q4["revenue"] == pytest.approx(130.0)
    assert q4["gross_profit"] == pytest.approx(56.0)
    assert q4["filed_date"] == pd.Timestamp("2025-02-15")
    assert q4["derivation"] == "fy_minus_q1_q2_q3"


def test_revenue_concept_fallback_is_recorded() -> None:
    contract = load_source_contract(CONTRACT).payload
    quarters = extract_company_quarters(
        _companyfacts(fallback_revenue=True), contract=contract
    )

    assert not quarters.empty
    assert set(quarters["revenue_concept"]) == {"Revenues"}


def test_missing_user_agent_writes_blocked_decision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    decision = build_sec_companyfacts_fundamentals(
        contract_path=CONTRACT,
        output_dir=tmp_path,
    )

    assert decision["decision"] == "sec_companyfacts_source_blocked"
    assert decision["source_run_completed"] is False
    assert "SEC_USER_AGENT is missing" in decision["reason"]


def test_full_pool_fixture_builds_factor_ready_source(tmp_path: Path) -> None:
    decision = build_sec_companyfacts_fundamentals(
        contract_path=CONTRACT,
        output_dir=tmp_path,
        client=FakeSecClient(),
    )
    fundamentals = pd.read_csv(tmp_path / "fundamentals.csv")
    coverage = json.loads(
        (tmp_path / "coverage_report.json").read_text(encoding="utf-8")
    )

    assert decision["factor_ready_count"] == len(_symbols())
    assert decision["fundamental_row_count"] == len(_symbols()) * 6
    assert list(fundamentals.columns[:8]) == [
        "symbol",
        "fiscal_period_end",
        "filed_date",
        "revenue",
        "gross_profit",
        "currency",
        "form_type",
        "accession_id",
    ]
    assert coverage["blocked_count"] == 0
    manifest = json.loads(
        (tmp_path / "evidence_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["manifest_identity_sha256"]
    assert "user_agent" not in json.dumps(manifest).lower().replace("user_agent_present", "").replace("user_agent_sha256", "")


def test_missing_gross_profit_blocks_only_affected_symbol(tmp_path: Path) -> None:
    missing_symbol = _symbols()[0]
    decision = build_sec_companyfacts_fundamentals(
        contract_path=CONTRACT,
        output_dir=tmp_path,
        client=FakeSecClient(missing_gross_symbol=missing_symbol),
    )
    coverage = json.loads(
        (tmp_path / "coverage_report.json").read_text(encoding="utf-8")
    )
    rows = {row["symbol"]: row for row in coverage["rows"]}

    assert decision["factor_ready_count"] == len(_symbols()) - 1
    assert rows[missing_symbol]["factor_ready"] is False
    assert "GROSS_PROFIT_CONCEPT_NOT_FOUND" in rows[missing_symbol]["reason_codes"]
    assert all(
        row["factor_ready"]
        for symbol, row in rows.items()
        if symbol != missing_symbol
    )
