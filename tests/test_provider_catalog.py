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
        ["tushare", "akshare", "efinance", "baostock", "yfinance"]
    ) == ["tushare", "akshare", "baostock", "yfinance"]


def test_tushare_availability_depends_on_explicit_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    assert provider_capability("tushare").available is False
    monkeypatch.setenv("TUSHARE_TOKEN", "test-token")
    assert provider_capability("tushare").available is True


def test_yahoo_declares_synthetic_amount_and_research_boundary():
    yahoo = provider_capability("yfinance")
    assert yahoo.amount_unit == "synthetic_close_times_volume"
    assert yahoo.research_only is True
    assert yahoo.source_family == "yahoo_finance"
