import pickle
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_rebacktest_logs_data_snapshot_id_and_end_date(tmp_path: Path, monkeypatch):
    from src.orchestrator import Orchestrator

    # Minimal cwd layout for universe file lookup.
    (tmp_path / "data" / "watchlist" / "instruments").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "watchlist" / "instruments" / "us.txt").write_text(
        "AAPL\nMSFT\n", encoding="utf-8"
    )

    import unittest.mock

    mock_model = unittest.mock.MagicMock()
    mock_model.predict.return_value = pd.Series(dtype=float)

    monkeypatch.setattr(pickle, "load", lambda _f: mock_model)
    model_pkl = tmp_path / "model.pkl"
    model_pkl.write_text("dummy")

    calls: list[dict] = []

    class FakeRecorder:
        def __init__(self, path: Path):
            self._path = path

        def get_local_dir(self):
            return str(self._path)

    def fake_get_recorder():
        return FakeRecorder(tmp_path / "mlruns" / "0" / "fake_run")

    class FakeR:
        @staticmethod
        @contextmanager
        def start(*_args, **_kwargs):
            yield

        @staticmethod
        def get_recorder():
            return fake_get_recorder()

        @staticmethod
        def log_params(**kwargs):
            calls.append(dict(kwargs))

        @staticmethod
        def save_objects(**kwargs):
            pass

    def fake_subprocess_run(*_args, **_kwargs):
        class R:
            returncode = 0

        return R()

    # Fake Qlib data access.
    def fake_calendar():
        return pd.to_datetime(["2026-02-03", "2026-02-04"])

    def fake_features(instruments, fields, start_time=None, end_time=None):
        dates = pd.to_datetime([start_time or "2026-02-03"])
        idx = pd.MultiIndex.from_product([instruments, dates], names=["instrument", "datetime"])
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        for f in fields:
            if str(f).endswith("volume"):
                df[f] = 20000.0
            else:
                df[f] = 100.0
        return df

    monkeypatch.chdir(tmp_path)
    import qlib.workflow

    import src.orchestrator

    monkeypatch.setattr(src.orchestrator.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(src.orchestrator.qlib, "init", lambda **_cfg: None)

    monkeypatch.setattr(qlib.workflow, "R", FakeR)
    import src.research.backtest
    import src.research.service
    import src.research.training
    import src.workflows.hooks

    monkeypatch.setattr(src.research.service, "R", FakeR, raising=False)
    monkeypatch.setattr(src.research.backtest, "R", FakeR, raising=False)
    monkeypatch.setattr(src.research.training, "R", FakeR, raising=False)
    monkeypatch.setattr(src.workflows.hooks, "R", FakeR, raising=False)
    monkeypatch.setattr(src.orchestrator, "R", FakeR, raising=False)
    monkeypatch.setattr("qlib.data.D.calendar", fake_calendar, raising=False)
    monkeypatch.setattr("qlib.data.D.features", fake_features, raising=False)

    # Stop after params logging
    def stop_at_backtest(*_args, **_kwargs):
        raise RuntimeError("stop_at_backtest")

    import qlib.utils

    mock_dataset = unittest.mock.MagicMock()
    mock_dataset.prepare.return_value = pd.DataFrame()
    monkeypatch.setattr(qlib.utils, "init_instance_by_config", lambda cfg, **_k: mock_dataset)
    # Patch the actual backtest runner to stop there
    import qlib.workflow.record_temp

    monkeypatch.setattr(qlib.workflow.record_temp.PortAnaRecord, "generate", stop_at_backtest)

    orch = Orchestrator()
    with pytest.raises(RuntimeError, match="stop_at_backtest"):
        orch.rebacktest(
            market="us",
            model_path=str(model_pkl),
            model_type="lgbm",
            profile="configs/strategy_profile.json",
            start="2025-01-01",
            end="latest",
            update_data=False,
            refresh_dashboard_db=False,
        )

    merged = {}
    for c in calls:
        merged.update(c)

    assert "data_snapshot_id" in merged
    assert merged["data_snapshot_id"] == "watchlist-day-2026-02-04"
    assert merged.get("data_end_date") == "2026-02-04"
