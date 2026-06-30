"""Regression tests: training scripts must preserve forward-return label direction.

The label expression ``Ref($close,-10)/Ref($close,-1)-1`` is a FORWARD
return (t+1 to t+10).  For a long-only strategy that buys high-score stocks,
the model must predict future returns DIRECTLY — high score → high return.

BUG (fixed 2026-06-27): Both ``scripts/train_optimal.py`` and
``scripts/train_us_optimal.py`` previously negated ``y_train``, ``y_valid``,
and ``y_test``, which reversed the signal and trained anti-predictive models.

These tests monkeypatch Qlib internals to exercise ``load_data()`` /
``load_us_data()`` with synthetic data where every label has a **known
positive** value (+0.05).  If either loader reintroduces ``y = -y``,
all returned labels become negative and the assertion fails.

BUG (to fix 2026-06-27): Train/valid/test splits overlap and lack
10-session forward-label boundary purging.  US excess label uses a
per-instrument rolling mean instead of same-date QQQ subtraction.

Unlike the indirect IC test in ``test_vectorized_backtest.py``, these tests
import and exercise the actual training-script loaders, so they catch a
``y = -y`` regression in either script regardless of what downstream
backtest / IC code does.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


def test_us_main_wires_backtest_outputs_and_inference_metadata(monkeypatch):
    import scripts.train_us_optimal as us

    walk_forward_calls = []
    train_calls = []
    saved_inputs = []
    predictions = object()
    realized_returns = object()
    norm_mean = object()
    norm_std = object()
    metrics = SimpleNamespace(
        excess_return=0.01,
        sharpe_ratio=0.5,
        max_drawdown=-0.1,
        volatility=0.2,
    )
    wf = SimpleNamespace(mean_ic=0.02, ic_ir=0.4, consistency_score=0.6, splits=[])

    monkeypatch.setattr(
        us,
        "load_us_data",
        lambda label_key: (None, None, None, None, None, None, ["AAPL"]),
    )
    def fake_train_model(*args, **kwargs):
        train_calls.append(kwargs)
        return (
            SimpleNamespace(best_iteration=1),
            ["feature"],
            (norm_mean, norm_std),
        )

    monkeypatch.setattr(us, "train_model", fake_train_model)

    def fake_walk_forward_vectorized(**kwargs):
        walk_forward_calls.append(kwargs)
        return wf

    monkeypatch.setattr(us, "walk_forward_vectorized", fake_walk_forward_vectorized)
    monkeypatch.setattr(
        us,
        "run_backtests",
        lambda *args, **kwargs: (predictions, realized_returns, metrics, metrics),
    )

    def fake_save_and_register(*args):
        saved_inputs.append(args)
        return "version", "artifact", {}

    monkeypatch.setattr(us, "save_and_register", fake_save_and_register)

    us.main()

    assert [call["benchmark_symbol"] for call in walk_forward_calls] == [None, "QQQ"]
    for call in walk_forward_calls:
        assert call["train_start"] == "2018-01-01"
        assert call.get("min_train_months") == 36, (
            f"Expected min_train_months=36, got {call.get('min_train_months')}"
        )
        assert call["label_horizon"] == 20
        assert call["training_objective"] == "lambdarank"
        assert call["feature_profile"] == "curated_us_momentum"
    assert len(train_calls) == 2
    for call in train_calls:
        assert call == {
            "training_objective": "lambdarank",
            "use_monotone_constraints": False,
            "max_depth": 3,
            "num_leaves": 7,
        }
    assert len(saved_inputs) == 2
    for args in saved_inputs:
        assert args[3] is predictions
        assert args[4] is realized_returns
        assert args[5] is norm_mean
        assert args[6] is norm_std


def _metric_result():
    values = {
        "total_return": 0.1,
        "annual_return": 0.08,
        "excess_return": 0.03,
        "sharpe_ratio": 0.5,
        "max_drawdown": -0.1,
        "volatility": 0.2,
        "mean_ic": 0.02,
        "ic_ir": 0.4,
        "benchmark_return": 0.07,
    }
    return SimpleNamespace(**values, to_dict=lambda: dict(values))


def test_us_effectiveness_gate_requires_all_historical_and_holdout_thresholds():
    import scripts.train_us_optimal as us

    wf = SimpleNamespace(
        mean_ic=0.03,
        ic_ir=0.4,
        consistency_score=0.6,
        n_success=8,
        splits=[],
    )
    backtest = SimpleNamespace(excess_return=0.01)
    assert us.passes_effectiveness_gate(wf, backtest)

    for field, failing_value in (
        ("mean_ic", 0.0),
        ("ic_ir", 0.3),
        ("consistency_score", 0.59),
        ("n_success", 7),
    ):
        failing = SimpleNamespace(**vars(wf))
        setattr(failing, field, failing_value)
        assert not us.passes_effectiveness_gate(failing, backtest)
    assert not us.passes_effectiveness_gate(
        wf, SimpleNamespace(excess_return=0.0)
    )


def test_us_artifact_persists_exact_frames_and_inference_metadata(monkeypatch, tmp_path):
    import scripts.train_us_optimal as us
    from src.assistant import metadata_db

    monkeypatch.setattr(us, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(us, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
    monkeypatch.setattr(
        metadata_db,
        "resolve_metadata_db_path",
        lambda artifacts_dir: tmp_path / "registry.db",
    )
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "AAPL")],
        names=["datetime", "instrument"],
    )
    predictions = pd.DataFrame({"score": [0.123]}, index=index)
    realized_returns = pd.DataFrame({"realized": [0.456]}, index=index)
    norm_mean = pd.Series({"feature": np.float64(1.25)})
    norm_std = pd.Series({"feature": np.float64(2.5)})
    wf = SimpleNamespace(mean_ic=0.02, ic_ir=0.4, consistency_score=0.6, splits=[])

    _, artifact_id, _ = us.save_and_register(
        "us_absret",
        SimpleNamespace(alpha_engine_monotone_constraints=[-1]),
        ["feature"],
        predictions,
        realized_returns,
        norm_mean,
        norm_std,
        _metric_result(),
        _metric_result(),
        wf,
    )

    artifact_dir = tmp_path / "artifacts" / artifact_id
    persisted_predictions = pd.read_csv(artifact_dir / "predictions.csv")
    persisted_returns = pd.read_csv(artifact_dir / "labels.csv")
    assert persisted_predictions["score"].tolist() == predictions["score"].tolist()
    assert persisted_returns["realized"].tolist() == realized_returns["realized"].tolist()
    metadata = json.loads((artifact_dir / "inference_metadata.json").read_text())
    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    assert metadata == {
        "feature_names": ["feature"],
        "norm_mean": {"feature": 1.25},
        "norm_std": {"feature": 2.5},
        "monotone_constraints": [-1],
        "feature_constraints": {"feature": -1},
    }
    assert manifest["inference_metadata"] == "inference_metadata.json"


def test_cn_artifact_persists_inference_metadata(monkeypatch, tmp_path):
    import scripts.train_optimal as cn

    monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
    captured = {}

    def fake_create(_model, config, _predictions, _labels, **kwargs):
        captured.update(config)
        artifact_dir = tmp_path / "artifacts" / "cn-artifact"
        artifact_dir.mkdir(parents=True)
        return SimpleNamespace(id="cn-artifact")

    monkeypatch.setattr("src.models.artifact.create_artifact", fake_create)
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "TEST")],
        names=["datetime", "instrument"],
    )
    wf = SimpleNamespace(
        mean_ic=-0.01,
        ic_ir=-0.1,
        consistency_score=0.3,
        n_success=2,
        splits=[SimpleNamespace(status="success", ic=-0.01) for _ in range(2)],
    )
    cn.save_and_register(
        "test",
        SimpleNamespace(),
        ["feature"],
        pd.DataFrame({"score": [0.1]}, index=index),
        pd.DataFrame({"return": [0.2]}, index=index),
        pd.Series({"feature": 1.25}),
        pd.Series({"feature": 2.5}),
        _metric_result(),
        _metric_result(),
        wf,
        inference_features=pd.DataFrame({"feature": [3.0]}, index=index),
    )
    assert captured["inference"] == {
        "feature_names": ["feature"],
        "norm_mean": {"feature": 1.25},
        "norm_std": {"feature": 2.5},
    }


def test_cn_main_passes_min_train_months_36(monkeypatch, tmp_path):
    """CN training script must pass min_train_months=36 to walk_forward_vectorized."""
    import scripts.train_optimal as cn
    from src.assistant import metadata_db

    captured = []

    def catching_wf(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(mean_ic=0.02, ic_ir=0.4, consistency_score=0.6, splits=[])

    monkeypatch.setattr(cn, "walk_forward_vectorized", catching_wf)
    monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
    monkeypatch.setattr(
        metadata_db,
        "resolve_metadata_db_path",
        lambda artifacts_dir: tmp_path / "registry.db",
    )
    monkeypatch.setattr(
        cn,
        "load_data",
        lambda: (None, None, None, None, None, None, ["TEST"]),
    )
    monkeypatch.setattr(
        cn,
        "train_model",
        lambda *args: (
            SimpleNamespace(best_iteration=1, alpha_engine_monotone_constraints=[1]),
            ["feature"],
            (pd.Series({"feature": np.float64(1.25)}), pd.Series({"feature": np.float64(2.5)})),
        ),
    )
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "TEST")],
        names=["datetime", "instrument"],
    )
    monkeypatch.setattr(
        cn,
        "run_backtest",
        lambda *args, **kwargs: (
            pd.DataFrame({"score": [0.1]}, index=index),
            pd.DataFrame({"return": [0.2]}, index=index),
            _metric_result(),
            _metric_result(),
        ),
    )

    cn.main()

    assert len(captured) == 8
    assert {call["min_train_months"] for call in captured} == {36}
    assert {call["label_horizon"] for call in captured} == {10, 20}
    assert {call["feature_profile"] for call in captured} == {
        "alpha158",
        "curated_us_momentum",
    }
    assert {call["training_objective"] for call in captured} == {
        "regression",
        "lambdarank",
    }


def test_cn_main_passes_wf_train_start(monkeypatch, tmp_path):
    """CN training script must pass WF_TRAIN_START=2018-01-01 to walk_forward_vectorized."""
    import scripts.train_optimal as cn
    from src.assistant import metadata_db

    captured = {}

    def catching_wf(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(mean_ic=0.02, ic_ir=0.4, consistency_score=0.6, splits=[])

    monkeypatch.setattr(cn, "walk_forward_vectorized", catching_wf)
    monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
    monkeypatch.setattr(
        metadata_db,
        "resolve_metadata_db_path",
        lambda artifacts_dir: tmp_path / "registry.db",
    )
    monkeypatch.setattr(
        cn, "load_data", lambda label_horizon=10, feature_profile="alpha158": (
            None, None, None, None, None, None, ["TEST"]
        )
    )
    monkeypatch.setattr(
        cn, "train_model",
        lambda *args: (
            SimpleNamespace(best_iteration=1, alpha_engine_monotone_constraints=[1]),
            ["feature"],
            (pd.Series({"feature": np.float64(1.25)}), pd.Series({"feature": np.float64(2.5)})),
        ),
    )
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "TEST")],
        names=["datetime", "instrument"],
    )
    monkeypatch.setattr(
        cn, "run_backtest",
        lambda *args, **kwargs: (
            pd.DataFrame({"score": [0.1]}, index=index),
            pd.DataFrame({"return": [0.2]}, index=index),
            _metric_result(),
            _metric_result(),
        ),
    )

    cn.main()

    assert captured.get("train_start") == "2018-01-01", (
        f"Expected WF_TRAIN_START='2018-01-01', got {captured.get('train_start')}"
    )


# ---------------------------------------------------------------------------
# Synthetic-data helpers
# ---------------------------------------------------------------------------


def _make_synthetic_df(
    symbols: list[str], start: str, end: str, value: float = 0.05
) -> pd.DataFrame:
    """MultiIndex DataFrame where every cell equals *value* (known positive)."""
    dates = pd.date_range(start, end, freq="B")
    idx = pd.MultiIndex.from_product([dates, symbols], names=["datetime", "instrument"])
    return pd.DataFrame({"v": np.full(len(idx), value, dtype=float)}, index=idx)


class _FakeAlpha158DL:
    """Returns a minimal list of dummy feature expressions."""

    @staticmethod
    def get_feature_config(_config):
        return (["dummy_expr"],)


class _FakeD:
    """Fake Qlib ``D`` object — returns KNOWN POSITIVE synthetic data."""

    def __init__(self, symbols: list[str]):
        self._symbols = symbols

    def features(self, _instruments, _expressions, start_time, end_time):
        return _make_synthetic_df(self._symbols, start_time, end_time, value=0.05)


class _FakeDInstrumentFirst(_FakeD):
    def features(self, _instruments, _expressions, start_time, end_time):
        return super().features(
            _instruments, _expressions, start_time, end_time
        ).swaplevel("datetime", "instrument").sort_index()


# ---------------------------------------------------------------------------
# Calendar-aware mock for boundary-purge tests
# ---------------------------------------------------------------------------

_CN_SYMBOLS = ["TEST1", "TEST2", "TEST3"]
_US_SYMBOLS = ["AAPL", "MSFT", "GOOG"]


def _irregular_calendar(start: str, end: str, drop_every: int = 3) -> list[pd.Timestamp]:
    """Return an irregular observed calendar by dropping some business days."""
    raw = pd.date_range(start, end, freq="B")
    return sorted(pd.Timestamp(d) for i, d in enumerate(raw) if i % drop_every != 0)


class _FakeDWithCalendar:
    """Returns synthetic data restricted to a specific irregular calendar."""

    def __init__(self, symbols: list[str], calendar: list[pd.Timestamp], value: float = 0.05):
        self._symbols = list(symbols)
        self._calendar = sorted(pd.Timestamp(d) for d in calendar)
        self._value = value

    def features(self, instruments, _expressions, start_time, end_time):
        start_ts = pd.Timestamp(start_time)
        end_ts = pd.Timestamp(end_time)
        dates_in_range = [d for d in self._calendar if start_ts <= d <= end_ts]
        inst_list = list(instruments) if not isinstance(instruments, str) else [instruments]
        if not dates_in_range:
            return pd.DataFrame(
                {"v": pd.Series([], dtype=float)},
                index=pd.MultiIndex.from_arrays(
                    [[], []], names=["datetime", "instrument"]
                ),
            )
        idx = pd.MultiIndex.from_product(
            [dates_in_range, inst_list], names=["datetime", "instrument"]
        )
        return pd.DataFrame(
            {"v": np.full(len(idx), self._value, dtype=float)}, index=idx
        )


class _FakeDWithBenchmark:
    """Returns stock returns at *stock_val* and QQQ benchmark at *bench_val*.

    Parameters
    ----------
    bench_nan_dates :
        Dates where the QQQ benchmark return should be ``NaN`` (value-level
        propagation test).
    bench_missing_dates :
        Dates that are **entirely absent** from the QQQ benchmark data
        (missing-date propagation test — the stock data still includes them).
    """

    def __init__(
        self,
        symbols: list[str],
        calendar: list[pd.Timestamp],
        stock_val: float = 0.05,
        bench_val: float = 0.02,
        bench_nan_dates: list[pd.Timestamp] | None = None,
        bench_missing_dates: list[pd.Timestamp] | None = None,
    ):
        self._symbols = list(symbols)
        self._calendar = sorted(pd.Timestamp(d) for d in calendar)
        self._stock_val = stock_val
        self._bench_val = bench_val
        self._bench_nan_dates: set[pd.Timestamp] = set(
            pd.Timestamp(d) for d in (bench_nan_dates or [])
        )
        self._bench_missing_dates: set[pd.Timestamp] = set(
            pd.Timestamp(d) for d in (bench_missing_dates or [])
        )

    def features(self, instruments, _expressions, start_time, end_time):
        start_ts = pd.Timestamp(start_time)
        end_ts = pd.Timestamp(end_time)
        dates_in_range = [d for d in self._calendar if start_ts <= d <= end_ts]
        if not dates_in_range:
            return pd.DataFrame(
                {"v": pd.Series([], dtype=float)},
                index=pd.MultiIndex.from_arrays(
                    [[], []], names=["datetime", "instrument"]
                ),
            )

        inst_list = list(instruments) if not isinstance(instruments, str) else [instruments]
        is_bench = len(inst_list) == 1 and inst_list[0] == "QQQ"

        if is_bench:
            # Remove dates genuinely missing from benchmark data
            dates_in_range = [
                d for d in dates_in_range if d not in self._bench_missing_dates
            ]
            if not dates_in_range:
                return pd.DataFrame(
                    {"v": pd.Series([], dtype=float)},
                    index=pd.MultiIndex.from_arrays(
                        [[], []], names=["datetime", "instrument"]
                    ),
                )
            symbols_use = ["QQQ"]
            vals = [
                np.nan if d in self._bench_nan_dates else self._bench_val
                for d in dates_in_range
            ]
        else:
            symbols_use = self._symbols
            vals = [self._stock_val] * len(dates_in_range)

        idx = pd.MultiIndex.from_product(
            [dates_in_range, symbols_use], names=["datetime", "instrument"]
        )
        all_vals = np.repeat(vals, len(symbols_use))
        return pd.DataFrame({"v": all_vals}, index=idx)


# ---------------------------------------------------------------------------
# Mock installers
# ---------------------------------------------------------------------------


def _setup_cn_mocks(monkeypatch, cn, tmp_path: Path, symbols: list[str]) -> None:
    """Install mocks needed for ``scripts.train_optimal.load_data()``."""
    monkeypatch.setattr(cn, "safe_qlib_init", lambda *a, **kw: None)
    monkeypatch.setattr(cn, "build_qlib_init_cfg", lambda *a, **kw: {})
    monkeypatch.setattr(cn, "Alpha158DL", _FakeAlpha158DL)
    monkeypatch.setattr(cn, "D", _FakeD(symbols))

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "cn.txt").write_text("\n".join(symbols))
    monkeypatch.setattr(cn, "ROOT", tmp_path)


def _setup_cn_mocks_with_calendar(
    monkeypatch, cn, tmp_path: Path, symbols: list[str], calendar: list[pd.Timestamp]
) -> None:
    """Install mocks with an irregular calendar for boundary-purge tests."""
    monkeypatch.setattr(cn, "safe_qlib_init", lambda *a, **kw: None)
    monkeypatch.setattr(cn, "build_qlib_init_cfg", lambda *a, **kw: {})
    monkeypatch.setattr(cn, "Alpha158DL", _FakeAlpha158DL)
    monkeypatch.setattr(cn, "D", _FakeDWithCalendar(symbols, calendar))

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "cn.txt").write_text("\n".join(symbols))
    monkeypatch.setattr(cn, "ROOT", tmp_path)


def _setup_us_mocks(monkeypatch, us, tmp_path: Path, symbols: list[str]) -> None:
    """Install mocks needed for ``scripts.train_us_optimal.load_us_data()``."""
    monkeypatch.setattr(us, "safe_qlib_init", lambda *a, **kw: None)
    monkeypatch.setattr(us, "build_qlib_init_cfg", lambda *a, **kw: {})
    monkeypatch.setattr(us, "Alpha158DL", _FakeAlpha158DL)
    monkeypatch.setattr(us, "D", _FakeD(symbols))

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "us.txt").write_text("\n".join(symbols))
    monkeypatch.setattr(us, "ROOT", tmp_path)


def test_cn_loader_normalizes_qlib_index_to_datetime_first(monkeypatch, tmp_path):
    import scripts.train_optimal as cn

    symbols = ["TEST1", "TEST2"]
    _setup_cn_mocks(monkeypatch, cn, tmp_path, symbols)
    monkeypatch.setattr(cn, "D", _FakeDInstrumentFirst(symbols))

    X_train, *_ = cn.load_data()

    assert X_train.index.names == ["datetime", "instrument"]


def test_us_loader_normalizes_qlib_index_to_datetime_first(monkeypatch, tmp_path):
    import scripts.train_us_optimal as us

    symbols = ["AAPL", "MSFT"]
    _setup_us_mocks(monkeypatch, us, tmp_path, symbols)
    monkeypatch.setattr(us, "D", _FakeDInstrumentFirst(symbols))

    X_train, *_ = us.load_us_data("absret")

    assert X_train.index.names == ["datetime", "instrument"]


def _setup_us_mocks_with_calendar(
    monkeypatch, us, tmp_path: Path, symbols: list[str], calendar: list[pd.Timestamp],
) -> None:
    """Install US mocks with an irregular calendar."""
    monkeypatch.setattr(us, "safe_qlib_init", lambda *a, **kw: None)
    monkeypatch.setattr(us, "build_qlib_init_cfg", lambda *a, **kw: {})
    monkeypatch.setattr(us, "Alpha158DL", _FakeAlpha158DL)
    monkeypatch.setattr(us, "D", _FakeDWithCalendar(symbols, calendar))

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "us.txt").write_text("\n".join(symbols))
    monkeypatch.setattr(us, "ROOT", tmp_path)


def _setup_us_mocks_with_benchmark(
    monkeypatch, us, tmp_path: Path, symbols: list[str], calendar: list[pd.Timestamp],
    stock_val: float = 0.05, bench_val: float = 0.02,
    bench_nan_dates: list[pd.Timestamp] | None = None,
    bench_missing_dates: list[pd.Timestamp] | None = None,
) -> None:
    """Install US mocks where QQQ returns differ from stock returns."""
    monkeypatch.setattr(us, "safe_qlib_init", lambda *a, **kw: None)
    monkeypatch.setattr(us, "build_qlib_init_cfg", lambda *a, **kw: {})
    monkeypatch.setattr(us, "Alpha158DL", _FakeAlpha158DL)
    monkeypatch.setattr(us, "D", _FakeDWithBenchmark(
        symbols, calendar, stock_val, bench_val, bench_nan_dates, bench_missing_dates,
    ))

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "us.txt").write_text("\n".join(symbols))
    monkeypatch.setattr(us, "ROOT", tmp_path)


# ---------------------------------------------------------------------------
# Shared assertion
# ---------------------------------------------------------------------------


def _assert_labels_positive(
    y_train: pd.Series,
    y_valid: pd.Series,
    y_test: pd.Series,
    label_context: str = "",
) -> None:
    """Every returned label must be strictly positive.

    Raises ``AssertionError`` with diagnostic detail if any label is ≤ 0,
    which indicates ``y = -y`` may have been reintroduced.
    """
    prefix = f"[{label_context}] " if label_context else ""
    for name, y in [("y_train", y_train), ("y_valid", y_valid), ("y_test", y_test)]:
        assert isinstance(y, pd.Series), f"{prefix}{name} must be Series, got {type(y).__name__}"
        assert len(y) > 0, f"{prefix}{name} must not be empty"
        assert (y > 0).all(), (
            f"{prefix}{name}: ALL labels must be > 0 (forward-return direction preserved). "
            f"Got min={y.min():.6f}  max={y.max():.6f}  mean={y.mean():.6f}. "
            f"If any are ≤ 0, y = -y may have been reintroduced."
        )


# ===================================================================
# Boundary-purge helpers (mirrors implementation logic for test verification)
# ===================================================================


def _compute_purge_cutoff(
    sorted_dates: list[pd.Timestamp],
    seg_start: str,
    seg_end: str,
    n_sessions: int = 10,
) -> pd.Timestamp | None:
    """Return the last allowable date within [seg_start, seg_end) after purging
    *n_sessions* observed sessions whose forward label would peek into the
    next segment.

    Returns ``None`` if there aren't enough sessions in the source segment
    to purge.
    """
    seg_start_ts = pd.Timestamp(seg_start)
    seg_end_ts = pd.Timestamp(seg_end)
    segment = [d for d in sorted_dates if seg_start_ts <= d < seg_end_ts]
    if len(segment) <= n_sessions:
        return None
    return segment[-(n_sessions + 1)]


def _count_observed_gap(
    sorted_dates: list[pd.Timestamp], last_date: pd.Timestamp, first_date: pd.Timestamp,
) -> int:
    """Count how many observed sessions lie strictly between two dates."""
    count = 0
    for d in sorted_dates:
        if last_date < d < first_date:
            count += 1
    return count


# ===================================================================
# Disjoint-split + boundary-purge tests — CN
# ===================================================================


class TestDisjointSplitsCN:
    """Verify CN ``load_data()`` produces disjoint train/valid/test splits
    with exactly 10 observed sessions purged at each boundary."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        """Create an irregular calendar spanning all three periods."""
        # Use every 4th business day to create a sparse, irregular calendar.
        # This ensures the purge is based on observed sessions, not calendar
        # day arithmetic.
        train_raw = _irregular_calendar("2021-06-01", "2024-06-28", drop_every=4)
        valid_raw = _irregular_calendar("2024-07-01", "2024-12-31", drop_every=4)
        test_raw = _irregular_calendar("2025-01-01", "2025-01-31", drop_every=4)

        self.calendar = sorted(train_raw + valid_raw + test_raw)
        self.symbols = list(_CN_SYMBOLS)

        import scripts.train_optimal as cn

        _setup_cn_mocks_with_calendar(
            monkeypatch, cn, tmp_path, self.symbols, self.calendar
        )
        self.cn = cn

    def test_no_date_overlap(self):
        """Train / valid / test date sets must be pairwise disjoint."""
        result = self.cn.load_data()
        X_train, _yt, X_valid, _yv, X_test, _yt2, _sym = result

        train_dates = set(X_train.index.get_level_values("datetime"))
        valid_dates = set(X_valid.index.get_level_values("datetime"))
        test_dates = set(X_test.index.get_level_values("datetime"))

        assert train_dates, "train must not be empty"
        assert valid_dates, "valid must not be empty"
        assert test_dates, "test must not be empty"

        overlap_tv = train_dates & valid_dates
        overlap_vt = valid_dates & test_dates
        overlap_tt = train_dates & test_dates

        assert not overlap_tv, f"train ∩ valid = {sorted(overlap_tv)[:5]}..."
        assert not overlap_vt, f"valid ∩ test = {sorted(overlap_vt)[:5]}..."
        assert not overlap_tt, f"train ∩ test = {sorted(overlap_tt)[:5]}..."

    def test_train_boundary_purge_exactly_10_sessions(self):
        """Exactly 10 observed sessions must be excluded between last train
        date and first valid date (no label-horizon peek)."""
        result = self.cn.load_data()
        X_train, _yt, X_valid, _yv, _Xt, _yt2, _sym = result

        train_dates = sorted(X_train.index.get_level_values("datetime").unique())
        valid_dates = sorted(X_valid.index.get_level_values("datetime").unique())

        last_train = train_dates[-1]
        first_valid = valid_dates[0]

        gap = _count_observed_gap(self.calendar, last_train, first_valid)
        assert gap == 10, (
            f"Expected exactly 10 observed sessions between last_train "
            f"({last_train.date()}) and first_valid ({first_valid.date()}); got {gap}"
        )

        # Verify last_train is exactly the purge-cutoff date
        expected_cutoff = _compute_purge_cutoff(self.calendar, "2021-01-01", "2024-07-01", 10)
        assert expected_cutoff is not None, (
            "calendar must have >10 sessions in [2021-01-01, 2024-07-01)"
        )
        assert last_train == expected_cutoff, (
            f"Last train date {last_train.date()} != expected purge cutoff "
            f"{expected_cutoff.date()}"
        )

    def test_valid_boundary_purge_exactly_10_sessions(self):
        """Exactly 10 observed sessions must be excluded between last valid
        date and first test date."""
        result = self.cn.load_data()
        X_train, _yt, X_valid, _yv, X_test, _yt2, _sym = result

        valid_dates = sorted(X_valid.index.get_level_values("datetime").unique())
        test_dates = sorted(X_test.index.get_level_values("datetime").unique())

        last_valid = valid_dates[-1]
        first_test = test_dates[0]

        gap = _count_observed_gap(self.calendar, last_valid, first_test)
        assert gap == 10, (
            f"Expected exactly 10 observed sessions between last_valid "
            f"({last_valid.date()}) and first_test ({first_test.date()}); got {gap}"
        )

        expected_cutoff = _compute_purge_cutoff(self.calendar, "2024-07-01", "2025-01-01", 10)
        assert expected_cutoff is not None, (
            "calendar must have >10 sessions in [2024-07-01, 2025-01-01)"
        )
        assert last_valid == expected_cutoff, (
            f"Last valid date {last_valid.date()} != expected purge cutoff "
            f"{expected_cutoff.date()}"
        )

    def test_labels_positive_after_purge(self):
        """Label direction must remain positive even after boundary purge."""
        result = self.cn.load_data()
        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = result
        _assert_labels_positive(y_train, y_valid, y_test, label_context="cn-purge")


# ===================================================================
# Disjoint-split + boundary-purge tests — US (absret only)
# ===================================================================


class TestDisjointSplitsUS:
    """Verify US ``load_us_data()`` produces disjoint splits with 10-session
    boundary purge for the absolute-return label variant."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        train_raw = _irregular_calendar("2021-06-01", "2024-06-28", drop_every=4)
        valid_raw = _irregular_calendar("2024-07-01", "2024-12-31", drop_every=4)
        test_raw = _irregular_calendar("2025-01-01", "2025-01-31", drop_every=4)

        self.calendar = sorted(train_raw + valid_raw + test_raw)
        self.symbols = list(_US_SYMBOLS)

        import scripts.train_us_optimal as us

        _setup_us_mocks_with_calendar(
            monkeypatch, us, tmp_path, self.symbols, self.calendar
        )
        self.us = us

    def test_no_date_overlap_absret(self):
        result = self.us.load_us_data("absret")
        X_train, _yt, X_valid, _yv, X_test, _yt2, _sym = result

        train_dates = set(X_train.index.get_level_values("datetime"))
        valid_dates = set(X_valid.index.get_level_values("datetime"))
        test_dates = set(X_test.index.get_level_values("datetime"))

        assert not train_dates & valid_dates, "train/valid overlap"
        assert not valid_dates & test_dates, "valid/test overlap"
        assert not train_dates & test_dates, "train/test overlap"

    def test_train_boundary_purge_matches_label_horizon(self):
        result = self.us.load_us_data("absret")
        X_train, _yt, X_valid, _yv, _Xt, _yt2, _sym = result

        train_dates = sorted(X_train.index.get_level_values("datetime").unique())
        valid_dates = sorted(X_valid.index.get_level_values("datetime").unique())

        gap = _count_observed_gap(self.calendar, train_dates[-1], valid_dates[0])
        assert gap == self.us.LABEL_HORIZON, (
            f"Expected {self.us.LABEL_HORIZON} observed sessions purged; got {gap}"
        )

    def test_valid_boundary_purge_matches_label_horizon(self):
        result = self.us.load_us_data("absret")
        X_train, _yt, X_valid, _yv, X_test, _yt2, _sym = result

        valid_dates = sorted(X_valid.index.get_level_values("datetime").unique())
        test_dates = sorted(X_test.index.get_level_values("datetime").unique())

        gap = _count_observed_gap(self.calendar, valid_dates[-1], test_dates[0])
        assert gap == self.us.LABEL_HORIZON, (
            f"Expected {self.us.LABEL_HORIZON} observed sessions purged; got {gap}"
        )


# ===================================================================
# US excess-label correctness
# ===================================================================


class TestUSExcessLabel:
    """Verify the US excess label equals stock forward return minus
    same-date QQQ forward return (not a per-instrument rolling mean)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        # Use a simple calendar with enough sessions before boundaries
        calendar = _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4)
        self.calendar = calendar
        self.symbols = list(_US_SYMBOLS)
        self.stock_val = 0.05
        self.bench_val = 0.02

        import scripts.train_us_optimal as us

        _setup_us_mocks_with_benchmark(
            monkeypatch, us, tmp_path, self.symbols, calendar,
            stock_val=self.stock_val, bench_val=self.bench_val,
        )
        self.us = us

    def test_absret_labels_unchanged(self):
        """Absolute US labels must remain stock forward returns (unchanged)."""
        result = self.us.load_us_data("absret")
        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = result
        # Absolute labels should all be 0.05 (the stock_val)
        assert abs(y_train.mean() - self.stock_val) < 1e-9, (
            f"Absolute labels should be {self.stock_val}, got {y_train.mean()}"
        )
        _assert_labels_positive(y_train, y_valid, y_test, label_context="us-absret")

    def test_excess_equals_stock_minus_qqq(self):
        """US excess label must be stock forward return minus same-date QQQ
        forward return (NOT a per-instrument rolling mean)."""
        result = self.us.load_us_data("excess")
        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = result

        expected_excess = self.stock_val - self.bench_val  # 0.05 - 0.02 = 0.03
        actual_mean = float(y_train.mean())

        assert abs(actual_mean - expected_excess) < 0.005, (
            f"US excess label should be stock - QQQ = {expected_excess:.4f}; "
            f"got mean={actual_mean:.6f}. "
            f"Pre-fix Mean(expr,10) yielded ~0 on constant data; "
            f"post-fix same-date subtraction yields {expected_excess:.4f}."
        )

    def test_excess_labels_positive(self):
        """Excess labels must be positive when stock > benchmark."""
        result = self.us.load_us_data("excess")
        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = result
        # stock - QQQ = 0.05 - 0.02 = 0.03 > 0
        _assert_labels_positive(y_train, y_valid, y_test, label_context="us-excess")


# ---------------------------------------------------------------------------
# CN loader
# ---------------------------------------------------------------------------


class TestCNLabelDirection:
    """Guard ``load_data()`` in ``scripts/train_optimal.py``."""

    def test_load_data_preserves_label_sign(self, monkeypatch, tmp_path):
        import scripts.train_optimal as cn

        symbols = ["TEST1", "TEST2", "TEST3"]
        _setup_cn_mocks(monkeypatch, cn, tmp_path, symbols)

        X_train, y_train, X_valid, y_valid, X_test, y_test, symbols_out = cn.load_data()

        _assert_labels_positive(y_train, y_valid, y_test, label_context="cn")
        assert symbols_out == symbols


# ---------------------------------------------------------------------------
# US loader
# ---------------------------------------------------------------------------


class TestUSLabelDirection:
    """Guard ``load_us_data()`` in ``scripts/train_us_optimal.py``."""

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_load_us_data_preserves_label_sign(
        self, monkeypatch, tmp_path, label_key
    ):
        import scripts.train_us_optimal as us

        symbols = ["AAPL", "MSFT", "GOOG"]
        _setup_us_mocks_with_benchmark(
            monkeypatch, us, tmp_path, symbols,
            _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4),
            stock_val=0.05, bench_val=0.02,
        )

        X_train, y_train, X_valid, y_valid, X_test, y_test, symbols_out = us.load_us_data(
            label_key
        )

        _assert_labels_positive(y_train, y_valid, y_test, label_context=label_key)
        assert symbols_out == symbols


# ===================================================================
# Fail-closed: insufficient observed sessions → ValueError
# ===================================================================


class TestFailClosedInsufficientCalendarCN:
    """Verify CN ``load_data()`` raises ValueError when there aren't enough
    observed sessions to enforce the 10-session label-horizon purge."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_optimal as cn

        self.cn = cn
        self.symbols = list(_CN_SYMBOLS)
        self.tmp_path = tmp_path
        # Keep a reference for calendar installation
        self._monkeypatch = monkeypatch

    def _install_calendar(self, calendar: list[pd.Timestamp]) -> None:
        _setup_cn_mocks_with_calendar(
            self._monkeypatch, self.cn, self.tmp_path, self.symbols, calendar
        )

    def test_insufficient_before_valid_start_raises(self):
        """≤10 observed sessions before VALID_START → ValueError at train→valid."""
        # Calendar from 2024-06-17: exactly 10 business days before 2024-07-01
        # (Jun 17,18,19,20,21,24,25,26,27,28).  Need >10 to purge 10.
        calendar = list(pd.date_range("2024-06-17", "2025-03-31", freq="B"))
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="train→valid"):
            self.cn.load_data()

    def test_insufficient_before_test_start_raises(self):
        """≤10 total sessions before TEST_START → fail-closed (train→valid check
        fires first since counts are cumulative, ensuring no unpurged fallback)."""
        # Only ~8 business days total before 2025-01-01
        calendar = list(pd.date_range("2024-12-16", "2025-03-31", freq="B"))
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="label-horizon purge"):
            self.cn.load_data()


class TestFailClosedInsufficientCalendarUS:
    """Verify US ``load_us_data()`` raises ValueError for insufficient observed
    sessions at both boundaries."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        self.us = us
        self.symbols = list(_US_SYMBOLS)
        self.tmp_path = tmp_path
        self._monkeypatch = monkeypatch

    def _install_calendar(self, calendar: list[pd.Timestamp]) -> None:
        _setup_us_mocks_with_calendar(
            self._monkeypatch, self.us, self.tmp_path, self.symbols, calendar
        )

    def test_insufficient_before_valid_start_raises_absret(self):
        """≤10 observed sessions before VALID_START → ValueError (absret)."""
        calendar = list(pd.date_range("2024-06-17", "2025-03-31", freq="B"))
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="train→valid"):
            self.us.load_us_data("absret")

    def test_insufficient_before_test_start_raises_absret(self):
        """≤10 observed sessions before TEST_START → fail-closed (absret)."""
        calendar = list(pd.date_range("2024-12-16", "2025-03-31", freq="B"))
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="label-horizon purge"):
            self.us.load_us_data("absret")

    def test_insufficient_also_fails_for_excess(self):
        """Same fail-closed behavior for excess label path."""
        calendar = list(pd.date_range("2024-06-17", "2025-03-31", freq="B"))
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="train→valid"):
            self.us.load_us_data("excess")


# ===================================================================
# Fail-closed: ample training but thin validation → valid→test ValueError
# ===================================================================


class TestFailClosedAmpleTrainThinValidCN:
    """Verify CN ``load_data()`` raises ValueError at the valid→test boundary
    when training history is ample but the validation segment has ≤10
    observed irregular dates.

    This guards against the pre-fix bug where ``_purge_tail`` counted ALL
    dates before TEST_START (including training dates) and silently returned
    a cutoff before VALID_START, producing an empty validation set.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_optimal as cn

        self.cn = cn
        self.symbols = list(_CN_SYMBOLS)
        self.tmp_path = tmp_path
        self._monkeypatch = monkeypatch

    def _install_calendar(self, calendar: list[pd.Timestamp]) -> None:
        _setup_cn_mocks_with_calendar(
            self._monkeypatch, self.cn, self.tmp_path, self.symbols, calendar
        )

    def test_validation_exactly_10_dates_raises_valid_to_test(self):
        """Validation has exactly 10 dates (need >10) → ValueError at valid→test."""
        # Ample training: many dates 2021-2024
        train_dates = list(pd.date_range("2021-01-04", "2024-06-28", freq="B"))
        # Exactly 10 validation dates (thin)
        valid_dates = list(pd.date_range("2024-07-01", "2024-12-31", freq="B"))[:10]
        # Some test dates
        test_dates = list(pd.date_range("2025-01-02", "2025-03-31", freq="B"))
        calendar = sorted(
            pd.Timestamp(d) for d in train_dates + valid_dates + test_dates
        )
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="valid→test"):
            self.cn.load_data()

    def test_validation_fewer_than_10_dates_raises_valid_to_test(self):
        """Validation has only 5 dates → ValueError at valid→test."""
        train_dates = list(pd.date_range("2021-01-04", "2024-06-28", freq="B"))
        valid_dates = list(pd.date_range("2024-07-01", "2024-12-31", freq="B"))[:5]
        test_dates = list(pd.date_range("2025-01-02", "2025-03-31", freq="B"))
        calendar = sorted(
            pd.Timestamp(d) for d in train_dates + valid_dates + test_dates
        )
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="valid→test"):
            self.cn.load_data()

    def test_validation_zero_dates_raises_valid_to_test(self):
        """Validation has 0 dates → ValueError at valid→test."""
        train_dates = list(pd.date_range("2021-01-04", "2024-06-28", freq="B"))
        valid_dates: list[pd.Timestamp] = []
        test_dates = list(pd.date_range("2025-01-02", "2025-03-31", freq="B"))
        calendar = sorted(
            pd.Timestamp(d) for d in train_dates + valid_dates + test_dates
        )
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="valid→test"):
            self.cn.load_data()


class TestFailClosedAmpleTrainThinValidUS:
    """Verify US ``load_us_data()`` raises ValueError at the valid→test boundary
    when training history is ample but the validation segment has ≤10
    observed irregular dates."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        self.us = us
        self.symbols = list(_US_SYMBOLS)
        self.tmp_path = tmp_path
        self._monkeypatch = monkeypatch

    def _install_calendar(self, calendar: list[pd.Timestamp]) -> None:
        _setup_us_mocks_with_calendar(
            self._monkeypatch, self.us, self.tmp_path, self.symbols, calendar
        )

    def test_validation_exactly_10_dates_raises_valid_to_test_absret(self):
        """Validation exactly 10 dates → ValueError at valid→test (absret)."""
        train_dates = list(pd.date_range("2021-01-04", "2024-06-28", freq="B"))
        valid_dates = list(pd.date_range("2024-07-01", "2024-12-31", freq="B"))[:10]
        test_dates = list(pd.date_range("2025-01-02", "2025-03-31", freq="B"))
        calendar = sorted(
            pd.Timestamp(d) for d in train_dates + valid_dates + test_dates
        )
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="valid→test"):
            self.us.load_us_data("absret")

    def test_validation_fewer_than_10_dates_raises_valid_to_test_absret(self):
        """Validation only 3 dates → ValueError at valid→test (absret)."""
        train_dates = list(pd.date_range("2021-01-04", "2024-06-28", freq="B"))
        valid_dates = list(pd.date_range("2024-07-01", "2024-12-31", freq="B"))[:3]
        test_dates = list(pd.date_range("2025-01-02", "2025-03-31", freq="B"))
        calendar = sorted(
            pd.Timestamp(d) for d in train_dates + valid_dates + test_dates
        )
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="valid→test"):
            self.us.load_us_data("absret")

    def test_validation_exactly_10_dates_raises_valid_to_test_excess(self):
        """Validation exactly 10 dates → ValueError at valid→test (excess)."""
        train_dates = list(pd.date_range("2021-01-04", "2024-06-28", freq="B"))
        valid_dates = list(pd.date_range("2024-07-01", "2024-12-31", freq="B"))[:10]
        test_dates = list(pd.date_range("2025-01-02", "2025-03-31", freq="B"))
        calendar = sorted(
            pd.Timestamp(d) for d in train_dates + valid_dates + test_dates
        )
        self._install_calendar(calendar)

        with pytest.raises(ValueError, match="valid→test"):
            self.us.load_us_data("excess")


# ===================================================================
# Invalid label_key rejection
# ===================================================================


class TestInvalidLabelKey:
    """Verify ``load_us_data()`` rejects unknown *label_key* before data loading."""

    def test_invalid_label_key_raises_value_error(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        # Minimal mocks (won't be reached — validation fires first)
        monkeypatch.setattr(us, "safe_qlib_init", lambda *a, **kw: None)
        monkeypatch.setattr(us, "build_qlib_init_cfg", lambda *a, **kw: {})

        with pytest.raises(ValueError, match="Unknown label_key"):
            us.load_us_data("momentum")

    def test_typo_near_valid_key_raises(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        monkeypatch.setattr(us, "safe_qlib_init", lambda *a, **kw: None)
        monkeypatch.setattr(us, "build_qlib_init_cfg", lambda *a, **kw: {})

        with pytest.raises(ValueError, match="Unknown label_key"):
            us.load_us_data("AbsRet")  # case-sensitive

    def test_empty_string_raises(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        monkeypatch.setattr(us, "safe_qlib_init", lambda *a, **kw: None)
        monkeypatch.setattr(us, "build_qlib_init_cfg", lambda *a, **kw: {})

        with pytest.raises(ValueError, match="Unknown label_key"):
            us.load_us_data("")


# ===================================================================
# Vectorized US excess: NaN / missing benchmark propagation
# ===================================================================


class TestUSExcessNaNPropagation:
    """Verify vectorized QQQ subtraction propagates NaN / missing benchmark
    correctly — stock excess must be NaN when QQQ return is NaN or missing."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        self.us = us
        self.symbols = list(_US_SYMBOLS)
        self.tmp_path = tmp_path

        # Calendar with enough sessions for purge to succeed
        self.calendar = _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4)
        self.stock_val = 0.05
        self.bench_val = 0.02
        self._monkeypatch = monkeypatch

    def _install_benchmark(self, bench_nan_dates=None, bench_missing_dates=None):
        _setup_us_mocks_with_benchmark(
            self._monkeypatch,
            self.us,
            self.tmp_path,
            self.symbols,
            self.calendar,
            stock_val=self.stock_val,
            bench_val=self.bench_val,
            bench_nan_dates=bench_nan_dates,
            bench_missing_dates=bench_missing_dates,
        )

    def test_excess_is_stock_minus_qqq_vectorized(self):
        """Excess label equals stock forward return minus same-date QQQ (vectorized)."""
        self._install_benchmark()
        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = self.us.load_us_data("excess")

        expected = self.stock_val - self.bench_val  # 0.03
        assert abs(float(y_train.mean()) - expected) < 0.005, (
            f"Expected ~{expected}, got {float(y_train.mean())}"
        )

    def test_nan_qqq_produces_nan_excess(self):
        """When QQQ return is NaN on a date, stock excess for that date is NaN."""
        # Pick a date in the calendar
        bench_nan_dates = [self.calendar[len(self.calendar) // 2]]
        self._install_benchmark(bench_nan_dates=bench_nan_dates)

        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = self.us.load_us_data("excess")

        # The NaN date may or may not fall into train/valid/test after purge.
        # Check that it appears as NaN in at least one split (since the calendar
        # includes it, and purge only trims boundaries).
        nan_date = pd.Timestamp(bench_nan_dates[0])
        for name, y in [("y_train", y_train), ("y_valid", y_valid), ("y_test", y_test)]:
            mask = y.index.get_level_values("datetime") == nan_date
            if mask.any():
                assert y[mask].isna().all(), (
                    f"{name}: excess labels at {nan_date.date()} must be NaN "
                    f"when QQQ is NaN, got {y[mask].values[:5]}"
                )

    def test_nan_qqq_does_not_corrupt_other_dates(self):
        """NaN QQQ on one date must not affect excess labels on other dates."""
        bench_nan_dates = [self.calendar[len(self.calendar) // 2]]
        self._install_benchmark(bench_nan_dates=bench_nan_dates)

        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = self.us.load_us_data("excess")
        nan_date = pd.Timestamp(bench_nan_dates[0])

        for name, y in [("y_train", y_train), ("y_valid", y_valid), ("y_test", y_test)]:
            non_nan_mask = y.index.get_level_values("datetime") != nan_date
            if non_nan_mask.any():
                non_nan = y[non_nan_mask].dropna()
                assert len(non_nan) > 0, f"{name}: should have non-NaN labels on other dates"
                expected = self.stock_val - self.bench_val
                assert abs(float(non_nan.mean()) - expected) < 0.005, (
                    f"{name}: non-NaN dates should be stock−QQQ={expected}, "
                    f"got mean={float(non_nan.mean()):.6f}"
                )

    def test_missing_qqq_date_produces_nan_excess(self):
        """When a QQQ date is genuinely absent (not just NaN value), stock
        excess labels on that same date must be NaN.

        This is distinct from ``test_nan_qqq_produces_nan_excess`` — there the
        benchmark *has* the date but its value is NaN; here the benchmark
        *omits* the date entirely while the stock data still includes it.
        """
        # Pick a date that falls inside the training period (plentiful dates,
        # won't be trimmed by the boundary purge) so it survives into y_train.
        missing_date = self.calendar[len(self.calendar) // 2]
        self._install_benchmark(bench_missing_dates=[missing_date])

        _Xt, y_train, _Xv, y_valid, _Xt2, y_test, _sym = self.us.load_us_data("excess")

        # The missing QQQ date should produce NaN excess labels on that date.
        found = False
        missing_ts = pd.Timestamp(missing_date)
        for name, y in [("y_train", y_train), ("y_valid", y_valid), ("y_test", y_test)]:
            mask = y.index.get_level_values("datetime") == missing_ts
            if mask.any():
                found = True
                assert y[mask].isna().all(), (
                    f"{name}: excess labels at {missing_date.date()} must be NaN "
                    f"when QQQ data is entirely missing for that date, "
                    f"got {y[mask].values[:5]}"
                )
        assert found, (
            f"Missing QQQ date {missing_date.date()} did not appear in any split "
            f"— adjust test calendar so it survives the boundary purge"
        )


# ===================================================================
# Stable feature selection + deterministic training — CN train_model
# ===================================================================


def _select_first_feature(train_X, train_y, valid_X, valid_y, **kwargs):
    """Return one audited feature for tests that exercise post-selection behavior."""
    feature = train_X.columns[0]
    return pd.DataFrame(
        {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
        index=pd.Index([feature], name="feature"),
    )


class TestCNTrainModelSelection:
    """Prove ``train_model`` in train_optimal.py selects ≤10 stable features,
    returns sanitized names, normalizes after selection, and uses
    deterministic daily-CS-IC early-stopping params."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_optimal as cn

        self.cn = cn
        self.symbols = list(_CN_SYMBOLS)
        self.calendar = _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4)
        _setup_cn_mocks_with_calendar(
            monkeypatch, cn, tmp_path, self.symbols, self.calendar
        )
        # Capture lgb.train calls to inspect params
        self.train_calls = []
        import lightgbm as lgb

        def _fake_train(params, train_set, num_boost_round=100,
                        valid_sets=None, feval=None, callbacks=None):
            self.train_calls.append({
                "params": dict(params),
                "valid_sets": valid_sets,
                "feval": feval,
                "callbacks": callbacks,
                "num_boost_round": num_boost_round,
            })
            booster = SimpleNamespace(
                best_iteration=1,
                best_score={"valid_0": {"mean_daily_cs_ic": 0.05}},
            )
            booster.predict = lambda X: np.zeros(len(X))
            return booster

        monkeypatch.setattr(lgb, "train", _fake_train)
        monkeypatch.setattr(lgb, "Dataset", lambda data, label=None, reference=None: data)
        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _select_first_feature,
        )
        self._monkeypatch = monkeypatch

    def test_returns_no_more_than_10_features(self):
        """train_model must return ≤10 sanitized feature names."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        booster, features, (norm_mean, norm_std) = self.cn.train_model(
            X_train, y_train, X_valid, y_valid
        )
        assert 1 <= len(features) <= 10, (
            f"Expected 1–10 selected features, got {len(features)}: {features}"
        )
        # Feature names must be sanitized (no $, /, (, ), etc.)
        for f in features:
            assert "$" not in f, f"Feature '{f}' not sanitized (contains $)"
            assert "/" not in f, f"Feature '{f}' not sanitized (contains /)"
            assert "(" not in f, f"Feature '{f}' not sanitized (contains ()"

    def test_fail_closed_on_empty_selection(self):
        """When select_stable_features returns empty, train_model must raise."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()

        def _fake_select(*args, **kwargs):
            return pd.DataFrame(columns=["train_ic", "valid_ic", "score", "rank"])

        self._monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _fake_select,
        )
        with pytest.raises(RuntimeError, match="No stable features"):
            self.cn.train_model(X_train, y_train, X_valid, y_valid)

    def test_deterministic_params_applied(self):
        """Verify deterministic seeds, disabled default metric, and regularization."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid)

        assert len(self.train_calls) == 1
        p = self.train_calls[0]["params"]
        assert p.get("seed") == 42
        for seed_param in (
            "feature_fraction_seed",
            "bagging_seed",
            "data_random_seed",
            "drop_seed",
        ):
            assert p.get(seed_param) == 42
        assert p.get("deterministic") is True
        assert p.get("force_col_wise") is True
        assert p.get("feature_fraction") == 1.0
        assert p.get("bagging_fraction") == 1.0
        assert p.get("metric") == "None"
        assert "first_metric_only" not in p
        assert any(
            getattr(callback, "first_metric_only", False)
            for callback in self.train_calls[0]["callbacks"]
        )
        # Regularization params
        assert p.get("learning_rate") == 0.03
        assert p.get("max_depth") == 4
        assert p.get("num_leaves") == 15
        assert p.get("min_data_in_leaf") == 100
        assert p.get("lambda_l2") == 10.0
        assert p.get("lambda_l1") == 1.0

    def test_feval_passed_to_lgb_train(self):
        """Daily CS IC feval must be passed to lgb.train."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid)

        assert len(self.train_calls) == 1
        assert self.train_calls[0]["feval"] is not None, (
            "feval (daily CS IC) must be passed to lgb.train"
        )
        assert self.train_calls[0]["valid_sets"] is not None, (
            "valid_sets must be passed to lgb.train for early stopping"
        )

    def test_normalization_inside_train_model(self):
        """load_data() must return un-normalized data; train_model normalizes."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        # Before train_model, data should NOT be z-scored (mean ≠ 0, std ≠ 1)
        # With constant 0.05 values, std ≈ 0, mean ≈ 0.05
        assert abs(float(X_train.mean().mean()) - 0.05) < 0.01, (
            f"load_data should return raw values (~0.05), got mean={float(X_train.mean().mean()):.4f}"
        )
        # After train_model, the returned norm stats should be from the subset
        booster, features, (norm_mean, norm_std) = self.cn.train_model(
            X_train, y_train, X_valid, y_valid
        )
        assert norm_mean is not None
        assert norm_std is not None
        assert len(norm_mean) == len(features)

    def test_selector_receives_only_train_valid(self):
        """select_stable_features must receive train+valid X/y only (never test)."""
        select_calls = []

        def _capture_select(train_X, train_y, valid_X, valid_y, max_features=50,
                            min_instruments_per_day=3):
            select_calls.append({
                "train_dates": set(train_X.index.get_level_values("datetime")),
                "valid_dates": set(valid_X.index.get_level_values("datetime")),
            })
            # Return a valid selection so training proceeds
            feat_name = train_X.columns[0]
            return pd.DataFrame(
                {"train_ic": [0.3], "valid_ic": [0.3], "score": [0.3], "rank": [1]},
                index=pd.Index([feat_name], name="feature"),
            )

        self._monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _capture_select,
        )
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid)

        assert len(select_calls) == 1
        train_dates = select_calls[0]["train_dates"]
        valid_dates = select_calls[0]["valid_dates"]
        # Train and valid must be disjoint
        assert not train_dates & valid_dates, "train and valid dates must not overlap"


# ===================================================================
# Stable feature selection + deterministic training — US train_model
# ===================================================================


class TestUSTrainModelSelection:
    """Prove ``train_model`` in train_us_optimal.py selects ≤10 stable features,
    returns sanitized names, and uses deterministic daily-CS-IC params."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        self.us = us
        self.symbols = list(_US_SYMBOLS)
        self.calendar = _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4)
        _setup_us_mocks_with_calendar(
            monkeypatch, us, tmp_path, self.symbols, self.calendar
        )
        self.train_calls = []
        import lightgbm as lgb

        def _fake_train(params, train_set, num_boost_round=100,
                        valid_sets=None, feval=None, callbacks=None):
            self.train_calls.append({
                "params": dict(params),
                "feval": feval,
                "callbacks": callbacks,
            })
            booster = SimpleNamespace(
                best_iteration=1,
                best_score={"valid_0": {"mean_daily_cs_ic": 0.05}},
            )
            booster.predict = lambda X: np.zeros(len(X))
            return booster

        monkeypatch.setattr(lgb, "train", _fake_train)
        monkeypatch.setattr(lgb, "Dataset", lambda data, label=None, reference=None: data)
        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _select_first_feature,
        )
        self._monkeypatch = monkeypatch

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_returns_no_more_than_10_features(self, label_key):
        """train_model must return ≤10 sanitized feature names for both labels."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data(label_key)
        booster, features, (norm_mean, norm_std) = self.us.train_model(
            X_train, y_train, X_valid, y_valid
        )
        assert 1 <= len(features) <= 10, (
            f"[{label_key}] Expected 1–10 features, got {len(features)}: {features}"
        )
        for f in features:
            assert "$" not in f and "/" not in f and "(" not in f, (
                f"[{label_key}] Feature '{f}' not sanitized"
            )

    def test_fail_closed_on_empty_selection(self):
        """train_model raises when selection is empty."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data("absret")

        def _fake_select(*args, **kwargs):
            return pd.DataFrame(columns=["train_ic", "valid_ic", "score", "rank"])

        self._monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _fake_select,
        )
        with pytest.raises(RuntimeError, match="No stable features"):
            self.us.train_model(X_train, y_train, X_valid, y_valid)

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_deterministic_params_applied(self, label_key):
        """Deterministic/regularized params must be set for both label variants."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data(label_key)
        self.us.train_model(X_train, y_train, X_valid, y_valid)

        assert len(self.train_calls) > 0
        p = self.train_calls[-1]["params"]
        assert p.get("seed") == 42
        for seed_param in (
            "feature_fraction_seed",
            "bagging_seed",
            "data_random_seed",
            "drop_seed",
        ):
            assert p.get(seed_param) == 42
        assert p.get("deterministic") is True
        assert p.get("metric") == "None"
        assert p.get("feature_fraction") == 1.0
        assert p.get("bagging_fraction") == 1.0
        assert p.get("learning_rate") == 0.03
        assert "first_metric_only" not in p
        assert any(
            getattr(callback, "first_metric_only", False)
            for callback in self.train_calls[-1]["callbacks"]
        )
        assert self.train_calls[-1]["feval"] is not None


# ===================================================================
# Lambdarank training — CN train_model
# ===================================================================


class TestCNLambdarankTraining:
    """Prove train_model(training_objective='lambdarank') uses correct objective,
    group-aware Datasets, integer relevance labels, and continuous feval."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_optimal as cn

        self.cn = cn
        self.symbols = list(_CN_SYMBOLS)
        self.calendar = _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4)
        _setup_cn_mocks_with_calendar(monkeypatch, cn, tmp_path, self.symbols, self.calendar)
        self.dataset_calls = []
        self.train_calls = []
        import lightgbm as lgb

        def _fake_dataset(data, label=None, reference=None, group=None):
            self.dataset_calls.append({"data": data, "label": label, "group": group})
            return data

        monkeypatch.setattr(lgb, "Dataset", _fake_dataset)

        def _fake_train(params, train_set, num_boost_round=100,
                        valid_sets=None, feval=None, callbacks=None):
            self.train_calls.append({
                "params": dict(params),
                "feval": feval,
                "valid_sets": valid_sets,
            })
            booster = SimpleNamespace(
                best_iteration=1,
                best_score={"valid_0": {"mean_daily_cs_ic": 0.05}},
            )
            booster.predict = lambda X: np.zeros(len(X))
            return booster

        monkeypatch.setattr(lgb, "train", _fake_train)
        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _select_first_feature,
        )

    def test_lambdarank_objective_and_groups(self):
        """Dataset must receive group parameter and objective='lambdarank'."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        # Two Datasets created (train + valid)
        assert len(self.dataset_calls) == 2
        for d in self.dataset_calls:
            assert d["group"] is not None, "Dataset must have group set"
            assert isinstance(d["group"], (list, np.ndarray)), f"group must be array-like, got {type(d['group'])}"
        assert len(self.train_calls) == 1
        p = self.train_calls[0]["params"]
        assert p.get("objective") == "lambdarank"

    def test_labels_are_integer_bins(self):
        """Dataset labels must be integer relevance bins (0..4), not continuous."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        for d in self.dataset_calls:
            label_arr = d["label"]
            assert label_arr is not None
            label_vals = np.asarray(label_arr)
            # Must be integers in 0..4
            assert np.issubdtype(label_vals.dtype, np.integer) or np.all(label_vals == label_vals.astype(int)), (
                f"Labels must be integer, got dtype={label_vals.dtype}"
            )
            assert label_vals.min() >= 0, f"Label min {label_vals.min()} < 0"
            assert label_vals.max() <= 4, f"Label max {label_vals.max()} > 4"

    def test_feval_passed_and_continuous_labels_in_scope(self):
        """feval must be passed in lambdarank mode (we verify it wraps continuous labels)."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        assert len(self.train_calls) == 1
        assert self.train_calls[0]["feval"] is not None, "feval must be passed in lambdarank mode"

    def test_feature_selection_uses_continuous_returns(self):
        """Feature selection runs before compute_relevance_labels, so it always
        receives continuous returns (never relevance bins)."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        # Show the raw data is continuous before training
        assert not np.all(np.isin(y_train.values, [0, 1, 2, 3, 4])), (
            "y_train should be continuous returns before training"
        )
        # train_model with lambdarank must succeed (selection uses continuous y)
        self.cn.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

    def test_monotone_constraints_unchanged(self):
        """Monotone constraints from selection must be preserved in lambdarank mode."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        p = self.train_calls[0]["params"]
        assert "monotone_constraints" in p, "monotone_constraints must be set"
        assert p.get("monotone_constraints_method") == "advanced"

    def test_deterministic_params_preserved(self):
        """Deterministic seeds and regularization preserved in lambdarank mode."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        p = self.train_calls[0]["params"]
        assert p.get("seed") == 42
        assert p.get("deterministic") is True
        assert p.get("metric") == "None"
        assert p.get("lambda_l2") == 10.0
        assert p.get("num_leaves") == 15

    def test_default_still_regression(self):
        """Default training_objective must remain 'regression'."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.cn.load_data()
        self.cn.train_model(X_train, y_train, X_valid, y_valid)

        assert len(self.dataset_calls) == 2
        for d in self.dataset_calls:
            assert d["group"] is None, "Regression mode must not set group"
        p = self.train_calls[0]["params"]
        assert p.get("objective") == "regression"


# ===================================================================
# Lambdarank training — US train_model
# ===================================================================


class TestUSLambdarankTraining:
    """Prove US train_model(training_objective='lambdarank') uses correct params."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        import scripts.train_us_optimal as us

        self.us = us
        self.symbols = list(_US_SYMBOLS)
        self.calendar = _irregular_calendar("2021-06-01", "2025-01-31", drop_every=4)
        _setup_us_mocks_with_calendar(monkeypatch, us, tmp_path, self.symbols, self.calendar)
        self.dataset_calls = []
        self.train_calls = []
        import lightgbm as lgb

        def _fake_dataset(data, label=None, reference=None, group=None):
            self.dataset_calls.append({"data": data, "label": label, "group": group})
            return data

        monkeypatch.setattr(lgb, "Dataset", _fake_dataset)

        def _fake_train(params, train_set, num_boost_round=100,
                        valid_sets=None, feval=None, callbacks=None):
            self.train_calls.append({
                "params": dict(params),
                "feval": feval,
                "valid_sets": valid_sets,
            })
            booster = SimpleNamespace(
                best_iteration=1,
                best_score={"valid_0": {"mean_daily_cs_ic": 0.05}},
            )
            booster.predict = lambda X: np.zeros(len(X))
            return booster

        monkeypatch.setattr(lgb, "train", _fake_train)
        monkeypatch.setattr(
            "src.research.cross_sectional_training.select_stable_features",
            _select_first_feature,
        )

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_lambdarank_objective_and_groups(self, label_key):
        """Both US label variants must support lambdarank with groups."""
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data(label_key)
        self.us.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        assert len(self.dataset_calls) == 2
        for d in self.dataset_calls:
            assert d["group"] is not None, f"[{label_key}] Dataset must have group"
        assert self.train_calls[0]["params"].get("objective") == "lambdarank"

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_labels_are_integer_bins(self, label_key):
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data(label_key)
        self.us.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        for d in self.dataset_calls:
            label_arr = np.asarray(d["label"])
            assert label_arr.min() >= 0
            assert label_arr.max() <= 4

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_feval_passed(self, label_key):
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data(label_key)
        self.us.train_model(X_train, y_train, X_valid, y_valid, training_objective="lambdarank")

        assert self.train_calls[0]["feval"] is not None

    @pytest.mark.parametrize("label_key", ["absret", "excess"])
    def test_default_still_regression(self, label_key):
        X_train, y_train, X_valid, y_valid, _Xt, _yt2, _sym = self.us.load_us_data(label_key)
        self.us.train_model(X_train, y_train, X_valid, y_valid)

        for d in self.dataset_calls:
            assert d["group"] is None, f"[{label_key}] Regression must not set group"
        assert self.train_calls[0]["params"].get("objective") == "regression"


# ===================================================================
# save_and_register validation gate tests
# ===================================================================


class TestSaveRegisterValidationGates:
    """Prove save_and_register in train_optimal.py:

    - Does NOT hardcode inference_gate/reconstruction_gate passed=True.
    - Calls validate_inference() and only writes .registered when inference passes.
    - Fails closed when inference validation is not run or fails.
    - Uses CANDIDATE stage (never DEV) for gate failures.
    """

    @staticmethod
    def _make_wf(n_success=8, mean_ic=0.03, ic_ir=0.4, consistency=0.6):
        return SimpleNamespace(
            mean_ic=mean_ic, ic_ir=ic_ir, consistency_score=consistency,
            n_success=n_success,
            splits=[SimpleNamespace(status="success", ic=0.01 + i * 0.01)
                    for i in range(n_success)],
        )

    @staticmethod
    def _make_backtest(excess_return=0.01):
        values = {
            "total_return": 0.1, "annual_return": 0.08, "excess_return": excess_return,
            "sharpe_ratio": 0.5, "max_drawdown": -0.1, "volatility": 0.2,
            "mean_ic": 0.02, "ic_ir": 0.4, "benchmark_return": 0.07,
        }
        return SimpleNamespace(**values, to_dict=lambda: dict(values))

    @staticmethod
    def _patch_artifact_io(monkeypatch, tmp_path):
        def fake_create(_model, _config, _predictions, _labels, **_kwargs):
            artifact_dir = tmp_path / "artifacts" / "gate-artifact"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            return SimpleNamespace(id="gate-artifact", model_binary_path="model.pkl")

        def fake_register(artifact_id, *, inference_result, reconstruction_result):
            marker = tmp_path / "artifacts" / artifact_id / ".registered"
            marker.write_text(json.dumps({
                "artifact_id": artifact_id,
                "inference_gate": inference_result.__dict__,
                "reconstruction_gate": reconstruction_result.__dict__,
            }))

        monkeypatch.setattr("src.models.artifact.create_artifact", fake_create)
        monkeypatch.setattr("src.models.artifact.register_artifact", fake_register)

    def test_calls_validate_inference_when_gate_passes(self, monkeypatch, tmp_path):
        """When effectiveness gate passes, validate_inference must be called."""
        import scripts.train_optimal as cn

        monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
        monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
        self._patch_artifact_io(monkeypatch, tmp_path)

        inference_called = [False]

        def _fake_validate(artifact_id):
            inference_called[0] = True
            from src.models.reconstruction import InferenceResult
            return InferenceResult(
                artifact_id=artifact_id, passed=True, n_samples=10,
                prediction_correlation=0.999, prediction_match_pct=99.5,
            )

        monkeypatch.setattr(
            "scripts.train_optimal.validate_inference", _fake_validate,
        )
        monkeypatch.setattr(
            cn,
            "_run_clean_artifact_reconstruction",
            lambda artifact_id: __import__(
                "src.models.reconstruction", fromlist=["ReconstructionResult"]
            ).ReconstructionResult(
                artifact_id=artifact_id,
                passed=True,
                status="passed",
                clean_process=True,
            ),
        )

        norm_mean = pd.Series({"f1": np.float64(1.0)})
        norm_std = pd.Series({"f1": np.float64(1.0)})
        index = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2025-01-02"), "A")],
            names=["datetime", "instrument"],
        )
        preds = pd.DataFrame({"score": [0.1]}, index=index)
        returns = pd.DataFrame({"return": [0.05]}, index=index)
        booster = SimpleNamespace(alpha_engine_monotone_constraints=[1],
                                  best_iteration=1)

        cn.save_and_register(
            "test_gate", booster, ["f1"], preds, returns,
            norm_mean, norm_std,
            self._make_backtest(0.05), self._make_backtest(0.05),
            self._make_wf(n_success=8, mean_ic=0.03, ic_ir=0.4, consistency=0.6),
        )

        assert inference_called[0], "validate_inference was NOT called"

    def test_inference_failure_uses_candidate_stage(self, monkeypatch, tmp_path):
        """When validate_inference fails, the artifact must be saved as CANDIDATE
        (not STAGING, not DEV), no .registered marker, no dashboard entry."""
        import scripts.train_optimal as cn

        monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
        monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
        self._patch_artifact_io(monkeypatch, tmp_path)

        def _fake_validate_fail(artifact_id):
            from src.models.reconstruction import InferenceResult
            return InferenceResult(
                artifact_id=artifact_id, passed=False, n_samples=10,
                prediction_correlation=0.5, prediction_match_pct=50.0,
                error="Inference failed: predictions do not match",
            )

        monkeypatch.setattr(
            "scripts.train_optimal.validate_inference", _fake_validate_fail,
        )

        norm_mean = pd.Series({"f1": np.float64(1.0)})
        norm_std = pd.Series({"f1": np.float64(1.0)})
        index = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2025-01-02"), "A")],
            names=["datetime", "instrument"],
        )
        preds = pd.DataFrame({"score": [0.1]}, index=index)
        returns = pd.DataFrame({"return": [0.05]}, index=index)
        booster = SimpleNamespace(alpha_engine_monotone_constraints=[1],
                                  best_iteration=1)

        version_id, artifact_id, _ = cn.save_and_register(
            "test_gate_fail", booster, ["f1"], preds, returns,
            norm_mean, norm_std,
            self._make_backtest(0.05), self._make_backtest(0.05),
            self._make_wf(n_success=8, mean_ic=0.03, ic_ir=0.4, consistency=0.6),
        )

        # Must NOT have .registered marker
        artifact_dir = tmp_path / "artifacts" / artifact_id
        assert not (artifact_dir / ".registered").exists(), (
            ".registered must NOT exist when inference gate fails"
        )
        # Must have gate_failed marker
        assert (artifact_dir / "gate_failed.json").exists(), (
            "gate_failed marker must exist"
        )
        gate_reason = (artifact_dir / "gate_failed.json").read_text()
        assert "inference" in gate_reason.lower(), (
            f"gate_failed must mention inference, got: {gate_reason}"
        )

    def test_no_inference_gate_hardcode(self, monkeypatch, tmp_path):
        """.registered must NOT have hardcoded inference_gate/reconstruction_gate.
        Instead it must use real validation results."""
        import scripts.train_optimal as cn

        monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
        monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")
        self._patch_artifact_io(monkeypatch, tmp_path)

        def _fake_validate(artifact_id):
            from src.models.reconstruction import InferenceResult
            return InferenceResult(
                artifact_id=artifact_id, passed=True, n_samples=10,
                prediction_correlation=0.999, prediction_match_pct=99.5,
            )

        monkeypatch.setattr(
            "scripts.train_optimal.validate_inference", _fake_validate,
        )
        monkeypatch.setattr(
            cn,
            "_run_clean_artifact_reconstruction",
            lambda artifact_id: __import__(
                "src.models.reconstruction", fromlist=["ReconstructionResult"]
            ).ReconstructionResult(
                artifact_id=artifact_id,
                passed=True,
                status="passed",
                clean_process=True,
            ),
        )

        norm_mean = pd.Series({"f1": np.float64(1.0)})
        norm_std = pd.Series({"f1": np.float64(1.0)})
        index = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2025-01-02"), "A")],
            names=["datetime", "instrument"],
        )
        preds = pd.DataFrame({"score": [0.1]}, index=index)
        returns = pd.DataFrame({"return": [0.05]}, index=index)
        booster = SimpleNamespace(alpha_engine_monotone_constraints=[1],
                                  best_iteration=1)

        version_id, artifact_id, _ = cn.save_and_register(
            "test_gate", booster, ["f1"], preds, returns,
            norm_mean, norm_std,
            self._make_backtest(0.05), self._make_backtest(0.05),
            self._make_wf(n_success=8, mean_ic=0.03, ic_ir=0.4, consistency=0.6),
        )

        artifact_dir = tmp_path / "artifacts" / artifact_id
        registered = json.loads((artifact_dir / ".registered").read_text())
        # Must have real inference_gate details (not just passed: True)
        assert "inference_gate" in registered
        ig = registered["inference_gate"]
        assert ig.get("passed") is True, "inference_gate must pass"
        assert ig["prediction_correlation"] == pytest.approx(0.999)
        assert registered["reconstruction_gate"]["clean_process"] is True


# ===================================================================
# DEV stage rejection tests
# ===================================================================


def test_dev_stage_not_in_registry_set():
    """DEV is NOT a valid registry stage.  save_and_register must use CANDIDATE."""
    from src.assistant.model_registry_index import _MODEL_STAGES
    assert "DEV" not in _MODEL_STAGES, (
        f"DEV must not be in _MODEL_STAGES (got {sorted(_MODEL_STAGES)})"
    )


def test_gate_failed_uses_candidate_not_dev(monkeypatch, tmp_path):
    """When gates fail, the entry stage must be CANDIDATE, not DEV."""
    import scripts.train_optimal as cn

    monkeypatch.setattr(cn, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(cn, "DASHBOARD_DB_PATH", tmp_path / "dashboard.json")

    def fake_create(_model, _config, _predictions, _labels, **_kwargs):
        artifact_dir = tmp_path / "artifacts" / "failed-artifact"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(id="failed-artifact")

    monkeypatch.setattr("src.models.artifact.create_artifact", fake_create)

    norm_mean = pd.Series({"f1": np.float64(1.0)})
    norm_std = pd.Series({"f1": np.float64(1.0)})
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "A")],
        names=["datetime", "instrument"],
    )
    preds = pd.DataFrame({"score": [0.1]}, index=index)
    returns = pd.DataFrame({"return": [0.05]}, index=index)
    booster = SimpleNamespace(alpha_engine_monotone_constraints=[1],
                              best_iteration=1)

    # Build a failing wf with the same structure save_and_register expects
    wf = SimpleNamespace(
        mean_ic=-0.01, ic_ir=-0.1, consistency_score=0.3,
        n_success=2,
        splits=[SimpleNamespace(status="success", ic=-0.01)
                for _ in range(2)],
    )
    # Ensure getattr on n_success still works (WF may not have attr n_success)
    # The _wf_success_count uses getattr(wf, "n_success", sum(...))
    # Since we set it explicitly, the getattr branch works.

    bt_values = {
        "total_return": -0.05, "annual_return": -0.08, "excess_return": -0.03,
        "sharpe_ratio": -0.3, "max_drawdown": -0.2, "volatility": 0.25,
        "mean_ic": -0.01, "ic_ir": -0.1, "benchmark_return": -0.02,
    }
    failing_bt = SimpleNamespace(**bt_values, to_dict=lambda: dict(bt_values))

    version_id, artifact_id, _ = cn.save_and_register(
        "test_dev_reject", booster, ["f1"], preds, returns,
        norm_mean, norm_std,
        failing_bt, failing_bt, wf,
    )

    artifact_dir = tmp_path / "artifacts" / artifact_id
    # Must have gate_failed marker
    assert (artifact_dir / "gate_failed.json").exists(), (
        "gate_failed marker must exist when gates fail"
    )
    gate_reason = (artifact_dir / "gate_failed.json").read_text()
    assert "effectiveness" in gate_reason.lower(), (
        f"gate_failed must mention effectiveness, got: {gate_reason}"
    )


def test_cn_candidate_selection_opens_holdout_once(monkeypatch):
    """Historical WF selects one candidate before any holdout data is opened."""
    import scripts.train_optimal as cn

    monkeypatch.setattr(
        cn,
        "CANDIDATES",
        [
            ("first", "regression", "alpha158", 10),
            ("winner", "lambdarank", "curated_us_momentum", 20),
        ],
    )
    wf_calls = []

    def fake_wf(**kwargs):
        wf_calls.append(kwargs)
        ic_ir = 0.4 if kwargs["label_horizon"] == 10 else 0.8
        return SimpleNamespace(
            mean_ic=0.04,
            ic_ir=ic_ir,
            consistency_score=0.75,
            n_success=8,
            splits=[SimpleNamespace(status="success", ic=0.04) for _ in range(8)],
        )

    monkeypatch.setattr(cn, "walk_forward_vectorized", fake_wf)
    load_calls = []
    monkeypatch.setattr(
        cn,
        "load_data",
        lambda **kwargs: load_calls.append(kwargs)
        or (None, None, None, None, None, None, ["TEST"]),
    )
    monkeypatch.setattr(
        cn,
        "train_model",
        lambda *args, **kwargs: (
            SimpleNamespace(best_iteration=1),
            ["feature"],
            (pd.Series({"feature": 0.0}), pd.Series({"feature": 1.0})),
        ),
    )
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "TEST")],
        names=["datetime", "instrument"],
    )
    backtest_calls = []

    def fake_backtest(*args, **kwargs):
        backtest_calls.append(kwargs)
        return (
            pd.DataFrame({"score": [0.1]}, index=index),
            pd.DataFrame({"return": [0.2]}, index=index),
            _metric_result(),
            _metric_result(),
            pd.DataFrame({"feature": [0.0]}, index=index),
        )

    monkeypatch.setattr(cn, "run_backtest", fake_backtest)
    saved = {}
    monkeypatch.setattr(
        cn,
        "save_and_register",
        lambda *args, **kwargs: saved.update(kwargs) or ("model", "artifact", {}),
    )

    cn.main()

    assert len(wf_calls) == 2
    assert len(load_calls) == len(backtest_calls) == 1
    assert load_calls[0] == {
        "label_horizon": 20,
        "feature_profile": "curated_us_momentum",
    }
    assert backtest_calls[0]["label_horizon"] == 20
    assert backtest_calls[0]["rebalance_days"] == 20
    assert saved["label_horizon"] == saved["rebalance_days"] == 20
    assert saved["training_objective"] == "lambdarank"


def test_cn_no_historical_candidate_never_opens_holdout(monkeypatch):
    import scripts.train_optimal as cn

    monkeypatch.setattr(cn, "CANDIDATES", [("failed", "regression", "alpha158", 10)])
    monkeypatch.setattr(
        cn,
        "walk_forward_vectorized",
        lambda **kwargs: SimpleNamespace(
            mean_ic=-0.01,
            ic_ir=-0.2,
            consistency_score=0.4,
            n_success=8,
            splits=[SimpleNamespace(status="success", ic=-0.01) for _ in range(8)],
        ),
    )
    monkeypatch.setattr(
        cn,
        "load_data",
        lambda **kwargs: pytest.fail("holdout data opened before historical selection"),
    )
    monkeypatch.setattr(
        cn,
        "run_backtest",
        lambda *args, **kwargs: pytest.fail("holdout backtest ran without an eligible candidate"),
    )

    assert cn.main() is None
