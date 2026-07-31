from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

import src.research.latest_us_fundamental_validation as live

READY_FIVE_BASKETS = {
    "ALAB",
    "AMD",
    "AAOI",
    "CRDO",
    "AAPL",
    "MSFT",
    "KO",
    "WMT",
    "HIMS",
    "TSLA",
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _pool_symbols() -> list[str]:
    pool = yaml.safe_load(live.POOL.read_text(encoding="utf-8"))
    return sorted(
        str(symbol)
        for metadata in pool["baskets"].values()
        for symbol in metadata["symbols"]
    )


def _patch_snapshot(monkeypatch, tmp_path: Path) -> Path:
    prices = tmp_path / "snapshot" / "2026-07-31" / "prices.csv"
    prices.parent.mkdir(parents=True)
    prices.write_text("date,symbol,open,close\n2026-07-31,QQQ,100,101\n", encoding="utf-8")

    def fake_snapshot(**kwargs):
        assert kwargs["start_date"] == "2020-01-01"
        return {
            "resolved_as_of_date": "2026-07-31",
            "prices_csv": str(prices),
            "trade_ready": False,
        }

    monkeypatch.setattr(live, "build_us_pool_price_snapshot", fake_snapshot)
    return prices


def _write_source_fixture(output: Path, ready_symbols: set[str]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    columns = [
        "symbol",
        "fiscal_period_end",
        "filed_date",
        "revenue",
        "gross_profit",
        "currency",
        "form_type",
        "accession_id",
    ]
    with (output / "fundamentals.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for symbol in sorted(ready_symbols):
            writer.writerow(
                {
                    "symbol": symbol,
                    "fiscal_period_end": "2025-12-31",
                    "filed_date": "2026-02-01",
                    "revenue": 100,
                    "gross_profit": 40,
                    "currency": "USD",
                    "form_type": "10-Q",
                    "accession_id": f"{symbol}-fixture",
                }
            )
    coverage_rows = [
        {
            "symbol": symbol,
            "factor_ready": symbol in ready_symbols,
            "reason_codes": [] if symbol in ready_symbols else ["INSUFFICIENT_QUARTER_COVERAGE"],
        }
        for symbol in _pool_symbols()
    ]
    _write_json(output / "coverage_report.json", {"rows": coverage_rows})
    _write_json(output / "evidence_manifest.json", {"identity": "sec"})
    return {
        "decision": "sec_companyfacts_source_ready_with_partial_coverage",
        "candidate_count": len(_pool_symbols()),
        "factor_ready_count": len(ready_symbols),
        "source_run_completed": True,
        "trade_ready": False,
    }


def test_frozen_cik_mapping_exactly_matches_pool() -> None:
    mapping = live.load_frozen_cik_mapping()

    assert len(mapping) == 23
    assert mapping["AAPL"] == "0000320193"
    assert mapping["IREN"] == "0001878848"
    assert mapping["TIGO"] == "0000912958"
    assert all(len(cik) == 10 and cik.isdigit() for cik in mapping.values())


def test_compressed_sec_client_decodes_gzip(monkeypatch) -> None:
    expected = {"cik": 320193, "facts": {"us-gaap": {}}}
    compressed = gzip.compress(json.dumps(expected).encode("utf-8"))

    class Response:
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return compressed

    monkeypatch.setattr(live.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    client = live.CompressedSecHttpClient(
        user_agent="AlphaEngine test contact@example.com",
        ticker_mapping_url="https://example.invalid/tickers.json",
        companyfacts_url_template="https://example.invalid/CIK{cik10}.json",
        minimum_interval_seconds=0,
        timeout_seconds=1,
    )

    assert client.companyfacts("0000320193") == expected


def test_standardises_quarter_label_and_derives_gross_profit() -> None:
    contract = yaml.safe_load(live.SEC_CONTRACT.read_text(encoding="utf-8"))
    common = {
        "start": "2024-01-01",
        "end": "2024-03-31",
        "filed": "2024-05-01",
        "accn": "fixture",
        "form": "6-K",
        "fy": 2024,
        "fp": None,
        "frame": "CY2024Q1",
    }
    payload = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [{**common, "val": 100.0}]}
                },
                "CostOfRevenue": {"units": {"USD": [{**common, "val": 65.0}]}},
            }
        }
    }

    result = live.standardise_companyfacts(payload, contract=contract)
    facts = result["facts"]["us-gaap"]
    revenue = facts["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"][0]
    gross = facts["DerivedGrossProfitFromRevenueMinusCost"]["units"]["USD"][0]

    assert revenue["fp"] == "Q1"
    assert gross["fp"] == "Q1"
    assert gross["val"] == pytest.approx(35.0)
    assert "DerivedGrossProfitFromRevenueMinusCost" not in payload["facts"]["us-gaap"]


def test_frozen_client_never_uses_bulk_ticker_endpoint() -> None:
    contract = yaml.safe_load(live.SEC_CONTRACT.read_text(encoding="utf-8"))

    class Delegate:
        def ticker_mapping(self) -> Mapping[str, Any]:
            raise AssertionError("bulk ticker endpoint must not be called")

        def companyfacts(self, cik10: str) -> Mapping[str, Any]:
            return {"cik": cik10, "facts": {}}

    client = live.FrozenPoolSecClient(
        delegate=Delegate(),
        mapping={"AAPL": "0000320193", "MSFT": "0000789019"},
        contract=contract,
    )

    ticker_rows = client.ticker_mapping()
    assert {row["ticker"] for row in ticker_rows.values()} == {"AAPL", "MSFT"}
    assert client.companyfacts("0000320193")["cik"] == "0000320193"


def test_default_client_uses_frozen_mapping(monkeypatch) -> None:
    class FakeHttpClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def ticker_mapping(self) -> Mapping[str, Any]:
            raise AssertionError("bulk ticker endpoint must not be called")

        def companyfacts(self, cik10: str) -> Mapping[str, Any]:
            return {"cik": cik10, "facts": {}}

    monkeypatch.setenv("SEC_USER_AGENT", "AlphaEngine test contact@example.com")
    monkeypatch.setattr(live, "CompressedSecHttpClient", FakeHttpClient)

    client = live._default_sec_client()

    assert client is not None
    rows = client.ticker_mapping()
    by_symbol = {row["ticker"]: str(row["cik_str"]).zfill(10) for row in rows.values()}
    assert by_symbol["IREN"] == "0001878848"
    assert by_symbol["TIGO"] == "0000912958"


def test_partial_source_coverage_runs_with_frozen_applicability(
    monkeypatch, tmp_path: Path
) -> None:
    prices = _patch_snapshot(monkeypatch, tmp_path)

    def fake_sec(**kwargs):
        return _write_source_fixture(Path(kwargs["output_dir"]), READY_FIVE_BASKETS)

    def fake_validation(**kwargs):
        assert Path(kwargs["prices_csv"]) == prices
        with Path(kwargs["fundamentals_csv"]).open(encoding="utf-8") as handle:
            observed = {row["symbol"] for row in csv.DictReader(handle)}
        assert observed == READY_FIVE_BASKETS
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        _write_json(
            output / "decision.json",
            {"decision": "simple_fundamental_factor_not_supported"},
        )
        _write_json(output / "evidence_manifest.json", {"identity": "validation"})
        return {
            "decision": "simple_fundamental_factor_not_supported",
            "trade_ready": False,
        }

    monkeypatch.setattr(live, "build_sec_companyfacts_fundamentals", fake_sec)
    monkeypatch.setattr(live, "run_minimal_fundamental_validation", fake_validation)

    result = live.run_latest_us_fundamental_validation(
        output_root=tmp_path / "live",
        snapshot_root=tmp_path / "snapshot",
        registry_db=tmp_path / "registry.db",
    )

    assert result["outputs"]["validation_decision"] == "simple_fundamental_factor_not_supported"
    assert result["factor_eligible_count"] == 10
    assert result["active_basket_count"] == 5
    assert result["pool_membership_unchanged"] is True
    assert result["trade_ready"] is False
    applicability = json.loads(
        (
            tmp_path
            / "live"
            / "2026-07-31"
            / "sec_companyfacts"
            / "factor_applicability.json"
        ).read_text(encoding="utf-8")
    )
    assert applicability["membership_unchanged"] is True
    assert applicability["performance_based_selection"] is False


def test_insufficient_active_baskets_fails_closed(monkeypatch, tmp_path: Path) -> None:
    _patch_snapshot(monkeypatch, tmp_path)
    four_baskets = READY_FIVE_BASKETS - {"HIMS", "TSLA"}

    def fake_sec(**kwargs):
        return _write_source_fixture(Path(kwargs["output_dir"]), four_baskets)

    monkeypatch.setattr(live, "build_sec_companyfacts_fundamentals", fake_sec)

    with pytest.raises(ValueError, match="insufficient active baskets"):
        live.run_latest_us_fundamental_validation(
            output_root=tmp_path / "live",
            snapshot_root=tmp_path / "snapshot",
            registry_db=tmp_path / "registry.db",
        )

    blocked = tmp_path / "live" / "2026-07-31" / "blocked.json"
    payload = json.loads(blocked.read_text(encoding="utf-8"))
    assert payload["decision"] == "live_fundamental_validation_blocked"
    assert payload["factor_applicability"]["active_basket_count"] == 4
    assert payload["trade_ready"] is False
