from src.data.provider_catalog import (
    independent_provider_names,
    provider_capability,
)


def test_eastmoney_transports_are_not_independent_sources():
    akshare = provider_capability("akshare")
    efinance = provider_capability("efinance")
    assert akshare.source_family == "eastmoney"
    assert efinance.source_family == "eastmoney"
    assert akshare.independent_group == efinance.independent_group
    assert independent_provider_names(
        [
            "tushare",
            "akshare_sina",
            "akshare",
            "efinance",
            "baostock",
            "yfinance",
        ]
    ) == ["tushare", "akshare_sina", "akshare", "baostock", "yfinance"]


def test_sina_is_independent_from_eastmoney():
    sina = provider_capability("akshare_sina")
    eastmoney = provider_capability("akshare")
    assert sina.source_family == "sina_finance"
    assert sina.independent_group != eastmoney.independent_group
    assert sina.volume_unit == "shares"
    assert sina.amount_unit == "CNY"


def test_tushare_availability_depends_on_explicit_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    assert provider_capability("tushare").available is False
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    assert provider_capability("tushare").available is True


def test_tiingo_is_independent_and_credential_gated(monkeypatch):
    monkeypatch.delenv("TIINGO_API_TOKEN", raising=False)
    tiingo = provider_capability("tiingo")
    yahoo = provider_capability("yfinance")
    assert tiingo.available is False
    assert tiingo.source_family == "tiingo_eod"
    assert tiingo.independent_group != yahoo.independent_group
    assert tiingo.corporate_actions is True
    monkeypatch.setenv("TIINGO_API_TOKEN", "test-token")
    assert provider_capability("tiingo").available is True


def test_yahoo_declares_synthetic_amount_and_research_boundary():
    yahoo = provider_capability("yfinance")
    assert yahoo.amount_unit == "synthetic_close_times_volume"
    assert yahoo.research_only is True
    assert yahoo.source_family == "yahoo_finance"
