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

