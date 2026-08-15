from __future__ import annotations

import json
from pathlib import Path

from scripts.data.refresh_selected_pool_prices_v2 import (
    FORMAL_MARKET_AUXILIARIES,
    _decorate_manifest,
    build_hardened_router,
)


def test_hardened_cn_router_uses_independent_sources_before_yahoo(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    router = build_hardened_router("cn")
    assert router.providers_for_market("cn") == [
        "akshare_sina",
        "akshare",
        "baostock",
        "efinance",
        "tencent_qfq_history",
        "yfinance",
    ]


def test_selected_pool_router_does_not_circuit_break_across_symbols(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    router = build_hardened_router("cn")
    assert router.provider_health_snapshot() == {
        "failure_threshold": None,
        "source_family_failures": {},
        "open_source_families": [],
    }


def test_hardened_cn_router_enables_tushare_only_with_token(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    router = build_hardened_router("cn")
    assert router.providers_for_market("cn") == [
        "tushare",
        "akshare_sina",
        "akshare",
        "baostock",
        "efinance",
        "tencent_qfq_history",
        "yfinance",
    ]


def test_hardened_us_router_reserves_tiingo_for_professional_etf_bundle(monkeypatch):
    monkeypatch.setenv("TIINGO_API_TOKEN", "test-token")
    router = build_hardened_router("us")
    assert router.providers_for_market("us") == ["yfinance"]


def test_formal_auxiliary_universe_preserves_legacy_tygo_without_substitution():
    assert "TYGO" in FORMAL_MARKET_AUXILIARIES["us"]
    assert "TIGO" not in FORMAL_MARKET_AUXILIARIES["us"]
    assert set(FORMAL_MARKET_AUXILIARIES["us"]) == {"QQQI", "TQQQ", "SGOV", "TYGO"}
    assert FORMAL_MARKET_AUXILIARIES["cn"] == ("515180",)


def test_manifest_does_not_count_two_eastmoney_transports_as_independent(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "cn",
                "status": "selected_pool_price_refresh_ready",
                "records": [
                    {
                        "symbol": "000001",
                        "action": "fetched_full_refresh",
                        "provider": "akshare",
                        "attempts": [
                            {
                                "provider": "akshare",
                                "ok": True,
                                "provider_symbol": "000001",
                            }
                        ],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("cn"))
    assert payload["provider_architecture"]["independent_provider_order"] == [
        "akshare_sina",
        "akshare",
        "baostock",
        "tencent_qfq_history",
        "yfinance",
    ]
    assert payload["promotion_eligible"] is True
    attempt = payload["records"][0]["attempts"][0]
    assert attempt["provider_contract"]["source_family"] == "eastmoney"


def test_cn_yahoo_only_source_is_quarantined(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "cn",
                "status": "selected_pool_price_refresh_ready",
                "records": [
                    {
                        "symbol": "000063",
                        "action": "fetched_full_refresh",
                        "provider": "yfinance",
                        "attempts": [],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("cn"))
    assert payload["promotion_eligible"] is False
    assert payload["quarantined_symbols"] == ["000063"]
    assert payload["formal_auxiliary_fallback_symbols"] == []
    assert payload["promotion_blocker"] == "CN symbols rely on Yahoo-only adjusted data"


def test_cn_formal_auxiliary_allows_proven_last_resort_yahoo_fallback(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "cn",
                "status": "selected_pool_price_refresh_ready",
                "records": [
                    {
                        "symbol": "515180",
                        "action": "fetched_full_refresh",
                        "provider": "yfinance",
                        "attempts": [
                            {"provider": "akshare_sina", "ok": False},
                            {"provider": "akshare", "ok": False},
                            {"provider": "baostock", "ok": False},
                            {"provider": "efinance", "ok": False},
                            {"provider": "tencent_qfq_history", "ok": False},
                            {
                                "provider": "yfinance",
                                "ok": True,
                                "provider_symbol": "515180.SS",
                            },
                        ],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("cn"))
    record = payload["records"][0]
    assert payload["promotion_eligible"] is True
    assert payload["quarantined_symbols"] == []
    assert payload["formal_auxiliary_fallback_symbols"] == ["515180"]
    assert payload["promotion_blocker"] is None
    assert record["promotion_status"] == "formal_auxiliary_governed_yahoo_fallback"


def test_cn_formal_auxiliary_does_not_bypass_missing_preferred_attempts(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "cn",
                "status": "selected_pool_price_refresh_ready",
                "records": [
                    {
                        "symbol": "515180",
                        "action": "fetched_full_refresh",
                        "provider": "yfinance",
                        "attempts": [
                            {"provider": "akshare_sina", "ok": False},
                            {"provider": "akshare", "ok": False},
                            {
                                "provider": "yfinance",
                                "ok": True,
                                "provider_symbol": "515180.SS",
                            },
                        ],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("cn"))
    assert payload["promotion_eligible"] is False
    assert payload["quarantined_symbols"] == ["515180"]
    assert payload["formal_auxiliary_fallback_symbols"] == []
