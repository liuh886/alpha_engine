from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.data.adapters.yfinance_adapter import _get_yahoo_ticker  # noqa: E402


def test_hk_ticker_normalization_strips_one_leading_zero_for_5_digit_code():
    assert _get_yahoo_ticker("00700.HK", "hk") == "0700.HK"
    assert _get_yahoo_ticker("01810.HK", "hk") == "1810.HK"


def test_hk_ticker_normalization_preserves_4_digit_code():
    assert _get_yahoo_ticker("0700.HK", "hk") == "0700.HK"
    assert _get_yahoo_ticker("700", "hk") == "700.HK"


def test_us_sp500_index_maps_to_the_real_index_never_a_tracking_etf():
    assert _get_yahoo_ticker("SPX", "us") == "^GSPC"
    # The canonical provider alias resolves to itself, and no ETF spelling is
    # silently added for the index.
    assert _get_yahoo_ticker("^GSPC", "us") == "^GSPC"
    for tracking_etf in ("SPY", "VOO", "IVV"):
        assert _get_yahoo_ticker(tracking_etf, "us") == tracking_etf


def test_existing_us_cn_and_hk_mappings_are_unchanged():
    assert _get_yahoo_ticker("AAPL", "us") == "AAPL"
    assert _get_yahoo_ticker("^VIX", "us") == "^VIX"
    assert _get_yahoo_ticker("600519", "cn") == "600519.SS"
    assert _get_yahoo_ticker("000001", "cn") == "000001.SZ"
    assert _get_yahoo_ticker("000300", "cn") == "000300.SS"
    assert _get_yahoo_ticker("300750", "cn") == "300750.SZ"
    assert _get_yahoo_ticker("0700.HK", "hk") == "0700.HK"
