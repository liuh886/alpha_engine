from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.byd_canonical_bundle import (
    audit_adjustment_events,
    build_canonical_bundle,
    derive_adjustment_factors,
)


def _raw(periods: int = 40) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=periods)
    close = np.linspace(40.0, 60.0, periods)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.linspace(1_000_000, 2_000_000, periods),
        }
    )


def test_cutoff_anchored_adjustment_reconstructs_provider_close() -> None:
    raw = _raw()
    factor = np.ones(len(raw))
    factor[:20] = 0.9
    adjusted = pd.DataFrame(
        {"date": raw["date"], "adjusted_close": raw["close"] * factor}
    )
    factors = derive_adjustment_factors(
        raw, adjusted, cutoff=raw["date"].iloc[-1]
    )
    assert factors["factor"].iloc[-1] == pytest.approx(1.0)
    assert factors["factor"].iloc[0] == pytest.approx(0.9)

    bundle = build_canonical_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted,
        cutoff=raw["date"].iloc[-1].strftime("%Y-%m-%d"),
        primary_provider="test_primary",
    )
    np.testing.assert_allclose(
        bundle.adjusted_bars["close"], adjusted["adjusted_close"], rtol=1e-8
    )
    assert bundle.manifest["cross_provider_stitching"] is False


def test_secondary_provider_cannot_fill_primary_gap() -> None:
    raw = _raw()
    secondary = _raw(42)
    adjusted = pd.DataFrame(
        {"date": raw["date"], "adjusted_close": raw["close"]}
    )
    bundle = build_canonical_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted,
        cutoff=raw["date"].iloc[-1].strftime("%Y-%m-%d"),
        primary_provider="primary",
        raw_secondary=secondary,
        secondary_provider="secondary",
    )
    assert len(bundle.raw_bars) == len(raw)
    assert bundle.raw_bars["date"].iloc[-1] == raw["date"].iloc[-1]


def test_missing_same_provider_adjusted_close_fails_closed() -> None:
    raw = _raw()
    adjusted = pd.DataFrame(
        {"date": raw["date"].iloc[:-1], "adjusted_close": raw["close"].iloc[:-1]}
    )
    with pytest.raises(ValueError, match="adjusted close missing"):
        derive_adjustment_factors(raw, adjusted, cutoff=raw["date"].iloc[-1])


def test_declared_action_explains_factor_jump() -> None:
    raw = _raw()
    adjusted_factor = np.ones(len(raw))
    adjusted_factor[:20] = 0.95
    adjusted = pd.DataFrame(
        {
            "date": raw["date"],
            "adjusted_close": raw["close"] * adjusted_factor,
        }
    )
    factors = derive_adjustment_factors(
        raw, adjusted, cutoff=raw["date"].iloc[-1]
    )
    actions = pd.DataFrame(
        {
            "date": [raw["date"].iloc[20]],
            "dividend": [1.0],
            "stock_split": [0.0],
            "event_source": ["test"],
        }
    )
    audit = audit_adjustment_events(factors, actions)
    assert audit["factor_jump"].sum() == 1
    assert audit["unexplained_jump"].sum() == 0


def test_unexplained_factor_jump_is_preserved_as_evidence() -> None:
    raw = _raw()
    adjusted_factor = np.ones(len(raw))
    adjusted_factor[:20] = 0.95
    adjusted = pd.DataFrame(
        {
            "date": raw["date"],
            "adjusted_close": raw["close"] * adjusted_factor,
        }
    )
    bundle = build_canonical_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted,
        cutoff=raw["date"].iloc[-1].strftime("%Y-%m-%d"),
        primary_provider="test",
    )
    assert bundle.manifest["unexplained_factor_jumps"] == 1


def test_primary_history_must_end_at_exact_cutoff() -> None:
    raw = _raw()
    adjusted = pd.DataFrame(
        {"date": raw["date"], "adjusted_close": raw["close"]}
    )
    future_cutoff = (raw["date"].iloc[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    with pytest.raises(ValueError, match="end exactly"):
        build_canonical_bundle(
            raw_primary=raw,
            provider_adjusted_close=adjusted,
            cutoff=future_cutoff,
            primary_provider="test",
        )


def test_adjusted_prices_are_persisted_at_high_precision() -> None:
    raw = _raw()
    adjusted = pd.DataFrame(
        {
            "date": raw["date"],
            "adjusted_close": raw["close"] * 0.912345678901,
        }
    )
    bundle = build_canonical_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted,
        cutoff=raw["date"].iloc[-1].strftime("%Y-%m-%d"),
        primary_provider="test",
    )
    assert bundle.manifest["precision_decimals"] >= 8
    assert bundle.adjusted_bars["close"].iloc[0] == pytest.approx(
        round(raw["close"].iloc[0], 8)
    )
