import pickle
import runpy
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_compute_benchmark_returns_does_not_init_qlib():
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")

    calls = {"n": 0}

    def fake_init(*args, **kwargs):
        calls["n"] += 1

    def fake_features(instruments, fields, start_time=None, end_time=None):
        dates = pd.date_range(start_time, end_time, freq="D")
        idx = pd.MultiIndex.from_product([instruments, dates], names=["instrument", "datetime"])
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        # Simple increasing close so returns are defined
        for i, dt in enumerate(dates):
            df.loc[(instruments[0], dt), fields[0]] = float(i + 1)
        return df

    g["qlib"].init = fake_init
    g["D"].features = fake_features

    out = g["compute_benchmark_returns"](
        ["2025-01-01", "2025-01-02"], "QQQ", provider_uri="data/watchlist"
    )
    assert calls["n"] == 0
    assert set(out.keys()) == {"2025-01-01", "2025-01-02"}


def test_load_strategy_profile_for_run_prefers_artifact_snapshot(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")

    run_dir = tmp_path / "mlruns" / "0" / "run_1"
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts" / "strategy_profile.json").write_text(
        '{"meta":{"name":"S1","description":"d1"}}', encoding="utf-8"
    )

    out = g["load_strategy_profile_for_run"](
        run_dir, {"profile": "configs/ignored.json"}, project_root=tmp_path
    )
    assert out.get("meta", {}).get("name") == "S1"


def test_load_strategy_profile_for_run_falls_back_to_profile_param(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")

    run_dir = tmp_path / "mlruns" / "0" / "run_2"
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs" / "p.json").write_text('{"meta":{"name":"S2"}}', encoding="utf-8")

    out = g["load_strategy_profile_for_run"](
        run_dir, {"profile": "configs/p.json"}, project_root=tmp_path
    )
    assert out.get("meta", {}).get("name") == "S2"


def test_load_run_data_includes_sig_analysis_series(tmp_path: Path):
    g = runpy.run_path(str(ROOT / "scripts" / "build_dashboard_db.py"), run_name="not_main")

    def fake_features(instruments, fields, start_time=None, end_time=None):
        dates = pd.date_range(start_time, end_time, freq="D")
        idx = pd.MultiIndex.from_product([instruments, dates], names=["instrument", "datetime"])
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        for i, dt in enumerate(dates):
            df.loc[(instruments[0], dt), fields[0]] = float(i + 1)
        return df

    g["D"].features = fake_features

    run_dir = tmp_path / "artifacts" / "portfolio_analysis"
    run_dir.mkdir(parents=True, exist_ok=True)

    report_df = pd.DataFrame(
        {"account": [100.0, 101.0], "return": [0.0, 0.01]},
        index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
    )
    with open(run_dir / "report_normal_1day.pkl", "wb") as f:
        pickle.dump(report_df, f)

    sig_dir = tmp_path / "artifacts" / "sig_analysis"
    sig_dir.mkdir(parents=True, exist_ok=True)
    ic = pd.Series([0.1, 0.2], index=pd.to_datetime(["2025-01-01", "2025-01-02"]), name="ic")
    ric = pd.Series([0.01, -0.02], index=pd.to_datetime(["2025-01-01", "2025-01-02"]), name="ric")
    with open(sig_dir / "ic.pkl", "wb") as f:
        pickle.dump(ic, f)
    with open(sig_dir / "ric.pkl", "wb") as f:
        pickle.dump(ric, f)

    out = g["load_run_data"](run_dir)
    sig = (out or {}).get("sig_analysis") or {}
    assert isinstance(sig, dict)
    assert sig.get("ic", {}).get("2025-01-01") == 0.1
    assert sig.get("ric", {}).get("2025-01-02") == -0.02
