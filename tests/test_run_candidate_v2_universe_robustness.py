"""Market-provider contracts for the candidate_v2 US evidence runner."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.run_candidate_v2_universe_robustness import (
    _evaluate_window,
    _exclude_benchmark_symbols,
    _load_us_provider_symbols,
    _slice_evaluation_frames,
    _verify_us_provider,
)
from src.research.rolling_windows import RollingResearchWindow
from src.data.market_provider import write_provider_manifest


def _build_provider(
    provider: Path,
    *,
    market: str = "us",
    write_manifest: bool = True,
) -> None:
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text(
        "2025-01-02\n2025-01-03\n2025-01-06\n",
        encoding="utf-8",
    )
    (provider / "instruments").mkdir()
    (provider / "instruments" / f"{market}.txt").write_text(
        "AAPL\t2025-01-02\t2025-01-06\n"
        "MSFT\t2025-01-02\t2025-01-06\n"
        "QQQ\t2025-01-02\t2025-01-06\n",
        encoding="utf-8",
    )
    (provider / "features").mkdir()
    if write_manifest:
        write_provider_manifest(
            provider,
            market=market,
            source_csv_files=[],
        )


def test_loads_symbols_only_from_market_specific_us_provider(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider)

    assert _load_us_provider_symbols(tmp_path) == ["AAPL", "MSFT"]


def test_never_falls_back_to_mixed_watchlist_provider(tmp_path: Path) -> None:
    watchlist = tmp_path / "data" / "watchlist" / "instruments"
    watchlist.mkdir(parents=True)
    (watchlist / "us.txt").write_text(
        "OLD\t2025-01-02\t2025-01-06\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="instrument metadata not found"):
        _load_us_provider_symbols(tmp_path)
    with pytest.raises(FileNotFoundError, match="provider manifest"):
        _verify_us_provider(tmp_path)


def test_valid_us_provider_manifest_passes(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider)

    manifest = _verify_us_provider(tmp_path)

    assert manifest["market"] == "us"
    assert manifest["calendar"]["session_count"] == 3
    assert manifest["provider_identity_sha256"]


def test_wrong_market_manifest_fails_closed(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider, market="cn")

    with pytest.raises(ValueError, match="market mismatch"):
        _verify_us_provider(tmp_path)


def test_provider_file_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider)
    (provider / "calendars" / "day.txt").write_text(
        "2025-01-02\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="calendar hash mismatch"):
        _verify_us_provider(tmp_path)


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    provider = tmp_path / "data" / "providers" / "us"
    _build_provider(provider, write_manifest=False)

    with pytest.raises(FileNotFoundError, match="provider manifest"):
        _verify_us_provider(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# Shared evaluator backward-compatibility and test-symbol restriction
# ══════════════════════════════════════════════════════════════════════════════


def test_evaluate_window_defaults_are_backward_compatible() -> None:
    """Calling _evaluate_window without train_symbols behaves identically."""
    # Verify the function accepts the new keyword-only params with defaults
    import inspect

    sig = inspect.signature(_evaluate_window)
    params = sig.parameters
    assert "train_symbols" in params
    assert params["train_symbols"].default is None
    assert "asof_membership_snapshot" in params
    assert params["asof_membership_snapshot"].default is None
    assert "asof_provider_symbols" in params
    assert params["asof_provider_symbols"].default is None


def test_evaluate_window_accepts_train_symbols_keyword() -> None:
    """_evaluate_window accepts train_symbols via keyword without error."""
    # Verify the parameter is keyword-only (after *)
    import inspect

    sig = inspect.signature(_evaluate_window)
    params = list(sig.parameters.items())
    # Find the position of '*'
    kw_only_params = [n for n, p in params if p.kind == inspect.Parameter.KEYWORD_ONLY]
    assert "train_symbols" in kw_only_params, (
        "train_symbols must be keyword-only to preserve backward compatibility"
    )


def test_exclude_benchmark_symbols_removes_qqq_spy() -> None:
    """_exclude_benchmark_symbols strips benchmark tickers."""
    symbols = ("AAPL", "QQQ", "MSFT", "SPY", "GOOGL", "SPX", "NDX")
    result = _exclude_benchmark_symbols(symbols)
    assert result == ("AAPL", "MSFT", "GOOGL")
    assert "QQQ" not in result
    assert "SPY" not in result


def test_slice_evaluation_frames_separates_train_and_test_symbols() -> None:
    """No train-only instrument can enter OOS prediction/economic rows."""
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2023-12-29"), "TRAIN"),
            (pd.Timestamp("2023-12-29"), "TEST"),
            (pd.Timestamp("2024-01-03"), "TRAIN"),
            (pd.Timestamp("2024-01-03"), "TEST"),
            (pd.Timestamp("2024-01-03"), "OTHER"),
        ],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"feature": range(len(index))}, index=index)
    returns = pd.DataFrame({"return": range(len(index))}, index=index)
    window = RollingResearchWindow(
        label="2024H1",
        train_start="2023-01-01",
        train_end="2023-12-31",
        test_start="2024-01-01",
        test_end="2024-06-30",
    )

    train_x, train_y, test_x, test_y = _slice_evaluation_frames(
        features,
        returns,
        window,
        train_symbols=["TRAIN"],
        test_symbols=["TEST"],
    )

    assert set(train_x.index.get_level_values("instrument")) == {"TRAIN"}
    assert train_x.index.equals(train_y.index)
    assert set(test_x.index.get_level_values("instrument")) == {"TEST"}
    assert test_x.index.equals(test_y.index)
