from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.research.cn_live_evidence_sources import (
    _cutoff_anchored_adjusted,
    build_cn_live_evidence_sources,
)

CONTRACT = Path("configs/providers/cn_small_pool_v1_provider_contract.yaml")
CANDIDATES = [
    "688008.SH", "002156.SZ", "000021.SZ", "688525.SH", "300782.SZ",
    "002463.SZ", "002281.SZ", "300548.SZ", "600522.SH", "688676.SH",
    "002837.SZ", "002709.SZ", "601012.SH", "600426.SH", "601899.SH",
    "601600.SH", "600026.SH", "601872.SH", "002594.SZ", "300408.SZ",
    "600150.SH",
]


def _canonical(code: str) -> str:
    exchange, six_digit = code.split(".")
    return f"{six_digit}.{'SH' if exchange == 'sh' else 'SZ'}"


class FakeBaoStock:
    def login(self) -> None:
        return None

    def logout(self) -> None:
        return None

    def history(
        self,
        code: str,
        *,
        start_date: str,
        end_date: str,
        adjustflag: str,
        fields: list[str],
    ) -> pd.DataFrame:
        symbol = _canonical(code)
        rows = []
        for day, raw_close in [("2026-06-29", 10.0), ("2026-06-30", 11.0)]:
            factor = 0.5 if adjustflag == "2" else 1.0
            values: dict[str, Any] = {
                "date": day,
                "code": code,
                "open": raw_close * factor,
                "high": (raw_close + 1.0) * factor,
                "low": (raw_close - 1.0) * factor,
                "close": raw_close * factor,
                "volume": 1000,
                "amount": 10000,
                "tradestatus": "1",
                "isST": "0",
            }
            rows.append([values[field] for field in fields])
        return pd.DataFrame(rows, columns=fields)

    def trade_dates(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "calendar_date": ["2026-06-29", "2026-06-30"],
                "is_trading_day": ["1", "1"],
            }
        )

    def stock_basic(self, code: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "code": [code],
                "code_name": [code],
                "ipoDate": ["2020-01-01"],
                "outDate": [""],
                "type": ["1"],
                "status": ["1"],
            }
        )


class FakeTushare:
    def query(
        self,
        api_name: str,
        *,
        params: Mapping[str, Any],
        fields: list[str],
    ) -> pd.DataFrame:
        if api_name == "trade_cal":
            return pd.DataFrame(
                [
                    ["SSE", "20260629", "1", "20260626"],
                    ["SSE", "20260630", "1", "20260629"],
                ],
                columns=fields,
            )
        if api_name == "stock_basic":
            if params.get("list_status") != "L":
                return pd.DataFrame(columns=fields)
            rows = []
            for symbol in CANDIDATES:
                code, exchange = symbol.split(".")
                values = {
                    "ts_code": symbol,
                    "symbol": code,
                    "name": symbol,
                    "exchange": "SSE" if exchange == "SH" else "SZSE",
                    "list_status": "L",
                    "list_date": "20200101",
                    "delist_date": "",
                }
                rows.append([values[field] for field in fields])
            return pd.DataFrame(rows, columns=fields)
        if api_name == "stk_limit":
            symbol = str(params["ts_code"])
            rows = []
            for day, pre_close in [("20260629", 9.5), ("20260630", 10.0)]:
                values = {
                    "trade_date": day,
                    "ts_code": symbol,
                    "pre_close": pre_close,
                    "up_limit": 20.0,
                    "down_limit": 5.0,
                }
                rows.append([values[field] for field in fields])
            return pd.DataFrame(rows, columns=fields)
        raise AssertionError(api_name)


def test_missing_tushare_token_emits_blocked_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    decision = build_cn_live_evidence_sources(
        contract_path=CONTRACT,
        output_dir=tmp_path,
        start_date="2026-06-29",
        end_date="2026-06-30",
    )

    assert decision["decision"] == "cn_provider_contract_blocked"
    assert decision["live_provider_run_completed"] is False
    assert decision["authoritative_provider_artifact"] is False
    serialized = json.dumps(decision)
    assert "TUSHARE_TOKEN is missing" in serialized


def test_cutoff_anchor_removes_moving_qfq_scale() -> None:
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-29", "2026-06-30"]),
            "symbol": ["AAA.SH", "AAA.SH"],
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.0, 11.0],
            "volume": [1, 1],
            "amount": [1, 1],
            "tradestatus": [1, 1],
            "isst": [0, 0],
        }
    )
    qfq_a = raw.copy()
    qfq_a[["open", "high", "low", "close"]] *= 0.5
    qfq_b = raw.copy()
    qfq_b[["open", "high", "low", "close"]] *= 0.25

    anchored_a = _cutoff_anchored_adjusted(raw, qfq_a)
    anchored_b = _cutoff_anchored_adjusted(raw, qfq_b)
    pd.testing.assert_series_equal(anchored_a["close"], anchored_b["close"])
    assert anchored_a.iloc[-1]["close"] == 11.0


def test_complete_fixture_builds_contract_but_never_authoritative(tmp_path: Path) -> None:
    decision = build_cn_live_evidence_sources(
        contract_path=CONTRACT,
        output_dir=tmp_path,
        start_date="2026-06-29",
        end_date="2026-06-30",
        tushare_client=FakeTushare(),
        baostock_client=FakeBaoStock(),
        fixture_mode=True,
    )

    assert decision["provider_contract_passed"] is True
    assert decision["live_provider_run_completed"] is False
    assert decision["source_attestation_verified"] is False
    assert decision["authoritative_provider_artifact"] is False
    assert (tmp_path / "staging" / "source_manifest.json").exists()
    assert (tmp_path / "cn_pool_bars.csv").exists()
