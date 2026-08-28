from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.data.refresh_selected_pool_prices_v2 import (
    FORMAL_MARKET_AUXILIARIES,
    MANIFEST_RELATIVE_PATH,
    _decorate_manifest,
    build_hardened_router,
    refresh_selected_pool_prices_v2,
)
from src.data.selected_pool_price_publication import (
    PUBLICATION_MANIFEST_NAME,
    load_selected_pool_price_publication_manifest,
)
from tests.selected_pool_price_fixtures import selected_pool_price_source


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


def test_formal_refresh_bounds_provider_process_without_threads_or_global_patches():
    workflow = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )

    assert "timeout --signal=TERM --kill-after=30s 30m" in workflow
    assert "refresh_selected_pool_prices_v2.py" in workflow


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


@pytest.mark.parametrize(
    "action",
    ["fetched_full_refresh", "fetched_incremental_update", "fetched_replacement"],
)
def test_cn_formal_auxiliary_allows_proven_last_resort_yahoo_fallback(
    tmp_path: Path,
    monkeypatch,
    action: str,
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
                        "action": action,
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


def test_stale_selected_pool_symbols_block_promotion(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "us",
                "status": "selected_pool_price_refresh_ready",
                "cutoff": "2026-08-19",
                "stale_symbols": ["FIX"],
                "records": [
                    {
                        "symbol": "FIX",
                        "action": "retained_stale_source",
                        "provider": "yfinance",
                        "attempts": [],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("us"))
    assert payload["promotion_eligible"] is False
    assert payload["unresolved_stale_symbols"] == ["FIX"]
    assert payload["promotion_blocker"] == (
        "stale selected-pool sources without an explicit lifecycle declaration"
    )


def test_terminal_listing_stale_symbol_does_not_block_promotion(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "us",
                "status": "selected_pool_price_refresh_ready",
                "cutoff": "2026-08-19",
                "stale_symbols": ["EA"],
                "records": [
                    {
                        "symbol": "EA",
                        "action": "retained_stale_source",
                        "provider": "yfinance",
                        "attempts": [],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("us"))
    assert payload["lifecycle_declared_terminal_symbols"] == ["EA"]
    assert payload["unresolved_stale_symbols"] == []
    assert payload["promotion_eligible"] is True
    assert payload["promotion_blocker"] is None
    assert payload["terminal_listing_evidence"]["EA"]["terminal_date"] == "2026-08-04"


def test_governed_terminal_history_is_explicitly_promotable(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "us",
                "status": "selected_pool_price_refresh_ready",
                "cutoff": "2026-08-19",
                "stale_symbols": ["EA"],
                "records": [
                    {
                        "symbol": "EA",
                        "action": "retained_governed_terminal_history",
                        "last_date": "2026-08-04",
                        "attempts": [],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )

    payload = _decorate_manifest(path, build_hardened_router("us"))

    assert payload["promotion_eligible"] is True
    assert payload["terminal_history_symbols"] == ["EA"]
    assert payload["records"][0]["promotion_status"] == "governed_terminal_history"


def test_mixed_terminal_and_unresolved_stale_symbols_remain_blocked(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "us",
                "status": "selected_pool_price_refresh_ready",
                "cutoff": "2026-08-19",
                "stale_symbols": ["EA", "FIX"],
                "records": [
                    {
                        "symbol": "EA",
                        "action": "retained_stale_source",
                        "provider": "yfinance",
                        "attempts": [],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("us"))
    assert payload["lifecycle_declared_terminal_symbols"] == ["EA"]
    assert payload["unresolved_stale_symbols"] == ["FIX"]
    assert payload["promotion_eligible"] is False


def test_current_selected_pool_remains_promotable_without_stale(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "us",
                "status": "selected_pool_price_refresh_ready",
                "stale_symbols": [],
                "records": [
                    {
                        "symbol": "AAPL",
                        "action": "fetched_incremental_update",
                        "provider": "yfinance",
                        "attempts": [],
                    }
                ],
                "failures": [],
            }
        ),
        encoding="utf-8",
    )
    payload = _decorate_manifest(path, build_hardened_router("us"))
    assert payload["promotion_eligible"] is True
    assert payload["unresolved_stale_symbols"] == []
    assert payload["promotion_blocker"] is None


def test_successful_refresh_writes_stable_publication_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    source_payload = selected_pool_price_source("cn")

    def fake_refresh(**kwargs):
        destination = Path(kwargs["output_root"])
        manifest_path = destination / "artifacts" / MANIFEST_RELATIVE_PATH.name
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(source_payload), encoding="utf-8")
        return source_payload

    monkeypatch.setattr(
        "scripts.data.refresh_selected_pool_prices_v2.refresh_selected_pool_prices",
        fake_refresh,
    )
    output = tmp_path / "provider-cn"
    result = refresh_selected_pool_prices_v2(
        root=Path.cwd(),
        market="cn",
        source_csv_dir=tmp_path / "unused",
        output_root=output,
        start="2021-01-01",
        cutoff="2026-08-21",
        router=build_hardened_router("cn"),
    )

    publication = load_selected_pool_price_publication_manifest(
        output / "artifacts" / PUBLICATION_MANIFEST_NAME
    )
    assert result["records"][-1]["attempts"][0]["error"]
    assert "attempts" not in publication["records"][-1]
    assert "action" not in publication["records"][-1]


def test_failed_refresh_removes_stale_publication_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    output = tmp_path / "provider-cn"
    publication_path = output / "artifacts" / PUBLICATION_MANIFEST_NAME
    publication_path.parent.mkdir(parents=True)
    publication_path.write_text("stale", encoding="utf-8")

    def failed_refresh(**kwargs):
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(
        "scripts.data.refresh_selected_pool_prices_v2.refresh_selected_pool_prices",
        failed_refresh,
    )
    with pytest.raises(RuntimeError, match="refresh failed"):
        refresh_selected_pool_prices_v2(
            root=Path.cwd(),
            market="cn",
            source_csv_dir=tmp_path / "unused",
            output_root=output,
            start="2021-01-01",
            cutoff="2026-08-21",
            router=build_hardened_router("cn"),
        )

    assert not publication_path.exists()
