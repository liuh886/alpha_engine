from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.byd_prospective_evidence_v2 import (
    SHADOW_SCHEMA_V2,
    enrich_observations,
)
from src.research.byd_prospective_shadow import (
    BASELINE_DATE,
    audit_independent_raw,
    build_extended_inputs,
    chain_link_provider_history,
    make_signal_observations,
)
from src.research.byd_prospective_store import (
    apply_immutable_shadow_schedule,
    mature_outcomes_from_immutable_observations,
    persist_immutable_shadow_store,
)


def _baseline(periods: int = 320) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range(end=BASELINE_DATE, periods=periods)
    rng = np.random.default_rng(519)
    returns = rng.normal(0.0004, 0.018, periods)
    close = 30.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.002, periods))
    adjusted = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, periods).astype(float),
        }
    )
    sessions = pd.DataFrame(
        {
            "date": dates,
            "open_research_eligible": True,
            "volume": adjusted["volume"],
        }
    )
    return adjusted, sessions


def _provider(baseline: pd.DataFrame, periods: int = 30) -> pd.DataFrame:
    anchor = baseline.iloc[-1]
    dates = pd.bdate_range(
        start=BASELINE_DATE + pd.Timedelta(days=1),
        periods=periods,
    )
    raw_close = float(anchor["close"]) * 3.0 * np.cumprod(
        np.full(periods, 1.002)
    )
    raw_open = raw_close * 0.998
    frame = pd.DataFrame(
        {
            "date": [BASELINE_DATE, *dates],
            "open": [float(anchor["open"]) * 3.0, *raw_open],
            "high": [float(anchor["high"]) * 3.0, *(raw_close * 1.01)],
            "low": [float(anchor["low"]) * 3.0, *(raw_open * 0.99)],
            "close": [float(anchor["close"]) * 3.0, *raw_close],
            "volume": [2_000_000.0, *np.full(periods, 2_500_000.0)],
        }
    )
    frame["adj_close"] = frame["close"] / 3.0
    frame["dividends"] = 0.0
    frame["stock_splits"] = 0.0
    frame.loc[frame.index[-1], "dividends"] = 0.10
    return frame


def _context(
    periods: int = 30,
    observed_at: str = "2026-08-04T10:00:00+00:00",
) -> tuple[list[dict[str, object]], pd.DataFrame]:
    baseline, sessions = _baseline()
    provider = _provider(baseline, periods)
    extension = chain_link_provider_history(baseline, provider)
    audit = audit_independent_raw(
        extension.primary_raw_new,
        extension.primary_raw_new.copy(),
        secondary_provider="synthetic_independent_raw",
    )
    adjusted, extended_sessions = build_extended_inputs(
        baseline,
        sessions,
        extension,
        audit,
    )
    base, dataset, _ = make_signal_observations(
        adjusted,
        extended_sessions,
        extension,
        audit,
        observed_at_utc=observed_at,
        primary_provider="synthetic_primary",
    )
    enriched = enrich_observations(
        base,
        extension,
        audit,
        provider,
        primary_provider="synthetic_primary",
    )
    final = apply_immutable_shadow_schedule(enriched, [], dataset)
    return final, dataset


def test_v2_observation_seals_prices_actions_and_audit() -> None:
    observations, _ = _context(3)
    first = observations[0]
    assert first["schema_version"] == SHADOW_SCHEMA_V2
    assert first["observation_mode"] == "same_session_post_close"
    assert first["prospective_eligible"] is True
    assert set(first["primary_raw_ohlcv"]) == {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert set(first["chain_linked_adjusted_ohlcv"]) == {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert first["independent_audit"]["confirmed"] is True
    assert "dividend" in first["company_actions"]


def test_outcomes_use_only_sealed_observation_prices() -> None:
    observations, _ = _context(30)
    outcomes = mature_outcomes_from_immutable_observations(observations)
    assert outcomes
    first = outcomes[0]
    assert first["settlement_source"] == "immutable_daily_observations_only"
    assert len(first["settlement_input_sha256"]) == 64
    assert set(first["cost_scenarios_bps"]) == {"20", "40"}

    changed = json.loads(json.dumps(observations))
    changed[-1]["chain_linked_adjusted_ohlcv"]["open"] *= 1.25
    changed_outcomes = mature_outcomes_from_immutable_observations(changed)
    assert changed_outcomes != outcomes
    assert mature_outcomes_from_immutable_observations(observations) == outcomes


def test_store_is_idempotent_and_rejects_changed_record(tmp_path: Path) -> None:
    observations, _ = _context(30)
    first = persist_immutable_shadow_store(tmp_path, observations)
    second = persist_immutable_shadow_store(tmp_path, observations)
    assert first == second
    assert first["cost_scenarios_bps"] == [20, 40]
    assert first["outcome_settlement"] == "immutable_daily_observations_only"

    changed = json.loads(json.dumps(observations[0]))
    changed["primary_raw_ohlcv"]["close"] *= 1.01
    with pytest.raises(RuntimeError, match="append-only record drift"):
        persist_immutable_shadow_store(tmp_path, [changed])


def test_existing_shadow_state_cannot_be_rewritten() -> None:
    observations, dataset = _context(8)
    existing = observations[:5]
    candidate = observations[5:]
    continued = apply_immutable_shadow_schedule(candidate, existing, dataset)
    assert len(continued) == 3

    changed = json.loads(json.dumps(existing))
    changed[0]["shadow_target_position"] = (
        1.0 if changed[0]["shadow_target_position"] == 0.75 else 0.75
    )
    with pytest.raises(RuntimeError, match="immutable shadow target drift"):
        apply_immutable_shadow_schedule(candidate, changed, dataset)


def test_catch_up_record_is_not_counted_as_prospective() -> None:
    observations, _ = _context(
        2,
        observed_at="2026-08-08T10:00:00+00:00",
    )
    assert observations[0]["observation_mode"] == "catch_up_backfill"
    assert observations[0]["prospective_eligible"] is False
