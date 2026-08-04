from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.byd_prospective_evidence_v2 import (
    SHADOW_SCHEMA_V2,
    enrich_observations,
    mature_outcomes_from_observations,
    persist_shadow_store_v2,
)
from src.research.byd_prospective_shadow import (
    BASELINE_DATE,
    audit_independent_raw,
    build_extended_inputs,
    chain_link_provider_history,
    make_signal_observations,
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


def _observations(periods: int = 30) -> list[dict[str, object]]:
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
    base, _, _ = make_signal_observations(
        adjusted,
        extended_sessions,
        extension,
        audit,
        observed_at_utc="2026-08-04T10:00:00+00:00",
        primary_provider="synthetic_primary",
    )
    return enrich_observations(
        base,
        extension,
        audit,
        provider,
        primary_provider="synthetic_primary",
    )


def test_v2_observation_seals_prices_actions_and_audit() -> None:
    observations = _observations(3)
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
    observations = _observations(30)
    outcomes = mature_outcomes_from_observations(observations)
    assert outcomes
    first = outcomes[0]
    assert first["settlement_source"] == "immutable_daily_observations_only"
    assert set(first["cost_scenarios_bps"]) == {"20", "40"}

    changed = json.loads(json.dumps(observations))
    changed[-1]["chain_linked_adjusted_ohlcv"]["open"] *= 1.25
    changed_outcomes = mature_outcomes_from_observations(changed)
    assert changed_outcomes != outcomes

    restored = mature_outcomes_from_observations(observations)
    assert restored == outcomes


def test_store_rejects_changed_existing_observation(tmp_path: Path) -> None:
    observations = _observations(30)
    first = persist_shadow_store_v2(tmp_path, observations)
    second = persist_shadow_store_v2(tmp_path, observations)
    assert first["ledger_sha256"] == second["ledger_sha256"]
    assert first["cost_scenarios_bps"] == [20, 40]
    assert first["outcome_settlement"] == "immutable_daily_observations_only"

    changed = json.loads(json.dumps(observations[0]))
    changed["primary_raw_ohlcv"]["close"] *= 1.01
    with pytest.raises(RuntimeError, match="append-only record drift"):
        persist_shadow_store_v2(tmp_path, [changed])


def test_catch_up_record_is_not_counted_as_prospective() -> None:
    observations = _observations(2)
    observations[0]["observed_at_utc"] = "2026-08-08T10:00:00+00:00"
    baseline, sessions = _baseline()
    provider = _provider(baseline, 2)
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
    base, _, _ = make_signal_observations(
        adjusted,
        extended_sessions,
        extension,
        audit,
        observed_at_utc="2026-08-08T10:00:00+00:00",
    )
    enriched = enrich_observations(
        base,
        extension,
        audit,
        provider,
        primary_provider="synthetic_primary",
    )
    assert enriched[0]["observation_mode"] == "catch_up_backfill"
    assert enriched[0]["prospective_eligible"] is False
