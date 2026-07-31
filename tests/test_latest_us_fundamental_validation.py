from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

import src.research.latest_us_fundamental_validation as live


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def test_frozen_client_never_uses_bulk_ticker_endpoint() -> None:
    class Delegate:
        def ticker_mapping(self) -> Mapping[str, Any]:
            raise AssertionError("bulk ticker endpoint must not be called")

        def companyfacts(self, cik10: str) -> Mapping[str, Any]:
            return {"cik": cik10, "facts": {}}

    client = live.FrozenPoolSecClient(
        delegate=Delegate(),  # type: ignore[arg-type]
        mapping={"AAPL": "0000320193", "MSFT": "0000789019"},
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


def test_live_wrapper_binds_source_and_validation(monkeypatch, tmp_path: Path) -> None:
    prices = _patch_snapshot(monkeypatch, tmp_path)

    def fake_sec(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "fundamentals.csv").write_text(
            "symbol,fiscal_period_end,filed_date,revenue,gross_profit,currency,form_type,accession_id\n",
            encoding="utf-8",
        )
        _write_json(output / "evidence_manifest.json", {"identity": "sec"})
        return {
            "decision": "sec_companyfacts_source_ready",
            "candidate_count": 23,
            "factor_ready_count": 23,
            "trade_ready": False,
        }

    def fake_validation(**kwargs):
        assert Path(kwargs["prices_csv"]) == prices
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
    assert result["source_grade"] == "current_sec_companyfacts_reconstruction_with_filed_dates"
    assert result["trade_ready"] is False
    assert len(result["run_identity_sha256"]) == 64
    assert len(result["inputs"]["frozen_cik_mapping_sha256"]) == 64
    manifest = tmp_path / "live" / "2026-07-31" / "latest_run_manifest.json"
    assert manifest.is_file()


def test_incomplete_sec_coverage_fails_closed(monkeypatch, tmp_path: Path) -> None:
    _patch_snapshot(monkeypatch, tmp_path)

    def fake_sec(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        return {
            "decision": "sec_companyfacts_source_ready_with_partial_coverage",
            "candidate_count": 23,
            "factor_ready_count": 22,
            "trade_ready": False,
        }

    monkeypatch.setattr(live, "build_sec_companyfacts_fundamentals", fake_sec)

    with pytest.raises(ValueError, match="do not cover every frozen candidate"):
        live.run_latest_us_fundamental_validation(
            output_root=tmp_path / "live",
            snapshot_root=tmp_path / "snapshot",
            registry_db=tmp_path / "registry.db",
        )

    blocked = tmp_path / "live" / "2026-07-31" / "blocked.json"
    payload = json.loads(blocked.read_text(encoding="utf-8"))
    assert payload["decision"] == "live_fundamental_validation_blocked"
    assert payload["factor_ready_count"] == 22
    assert payload["trade_ready"] is False
