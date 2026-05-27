from src.assistant.services.asset_inspection_service import AssetInspectionService


def test_infer_market_symbol_handles_cn_suffixes():
    assert AssetInspectionService.infer_market_symbol("600519.SH") == ("cn", "600519")
    assert AssetInspectionService.infer_market_symbol("000001.SZ") == ("cn", "000001")
    assert AssetInspectionService.infer_market_symbol("nvda") == ("us", "NVDA")


def test_calculate_guardrails_marks_extreme_volatility_before_high():
    prices = [100.0, 220.0, 80.0, 260.0, 90.0, 280.0, 95.0, 300.0, 100.0, 320.0, 110.0]
    ohlcv = [
        {"time": f"2026-01-{idx + 1:02d}", "close": price, "value": 100_000.0}
        for idx, price in enumerate(prices)
    ]

    guardrails = AssetInspectionService.calculate_guardrails(ohlcv)
    by_label = {row["label"]: row for row in guardrails}

    assert by_label["Volatility"]["status"] == "EXTREME"
    assert by_label["Liquidity"]["status"] == "PASS"
    assert by_label["Data Quality"]["status"] == "REAL"


def test_calculate_guardrails_marks_low_liquidity():
    ohlcv = [
        {"time": f"2026-01-{idx + 1:02d}", "close": 10.0 + idx, "value": 100.0}
        for idx in range(12)
    ]

    guardrails = AssetInspectionService.calculate_guardrails(ohlcv)
    by_label = {row["label"]: row for row in guardrails}

    assert by_label["Liquidity"]["status"] == "LOW"
