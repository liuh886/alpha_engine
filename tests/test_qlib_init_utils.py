import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_build_qlib_init_cfg_sets_region_and_windows_defaults():
    import unittest.mock

    from src.common.qlib_init import build_qlib_init_cfg

    with unittest.mock.patch("os.name", "nt"):
        cfg = build_qlib_init_cfg({}, market="cn")
    assert cfg["region"] == "cn"
    assert cfg["provider_uri"] == "data/watchlist"
    assert cfg["kernels"] == 1
    assert cfg["joblib_backend"] == "threading"


def test_build_qlib_init_cfg_respects_existing_values():
    from src.common.qlib_init import build_qlib_init_cfg

    cfg = build_qlib_init_cfg({"region": "us", "provider_uri": "X", "kernels": 9}, market="cn")
    assert cfg["region"] == "us"
    assert cfg["provider_uri"] == "X"
    assert cfg["kernels"] == 9
