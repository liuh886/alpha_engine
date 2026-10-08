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


def test_default_recorder_uses_isolated_artifact_root(tmp_path):
    from src.common.qlib_init import build_qlib_init_cfg
    from src.common.paths import MLRUNS_DIR

    # The module's imported directory must be patched as well as paths.MLRUNS_DIR.
    cfg = build_qlib_init_cfg({}, market="us")
    expected = "sqlite:///" + (MLRUNS_DIR.parent / "mlflow.db").resolve().as_posix()
    assert cfg["exp_manager"]["kwargs"]["uri"] == expected
    assert MLRUNS_DIR.parent == tmp_path / "artifacts"
