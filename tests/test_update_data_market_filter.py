import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_update_data_can_filter_regions_by_market():
    g = runpy.run_path(str(ROOT / "scripts" / "update_data.py"), run_name="not_main")
    fn = g.get("filter_regions_for_market")
    if fn is None:
        pytest.fail("update_data.py missing filter_regions_for_market helper")

    regions = {
        "cn": ["600519"],
        "us": ["NVDA", "AAPL"],
        "hk": ["0700"],
    }

    assert fn(regions, "us") == {"cn": [], "us": ["NVDA", "AAPL"], "hk": []}
    assert fn(regions, "all") == regions
