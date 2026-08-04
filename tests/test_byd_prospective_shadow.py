from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.byd_prospective_shadow import (
    BASELINE_DATE,
    SHADOW_SCHEMA,
    audit_independent_raw,
    build_extended_inputs,
    chain_link_provider_history,
    make_signal_observations,
    persist_shadow_store,
)


def _baseline(periods: int = 320) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range(end=BASELINE_DATE, periods=periods)
    rng = np.random.default_rng(518)
    returns = rng.normal(0.0004, 0.018, periods)
    close = 30.0 * np.cumprod(1.0 + returns)
    open_ = close * (1.0 + rng.normal(0.0, 0.002, periods))
    high = np.maximum(open_, close) * 1.01
    low = np.minimum(open_, close) * 0.99
    adjusted = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
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


def _provider(baseline: pd.DataFrame, new_periods: int = 25) -> pd.DataFrame:
    anchor = baseline.iloc[-1]
    new_dates = pd.bdate_range(
        start=BASELINE_DATE + pd.Timedelta(days=1),
        periods=new_periods,
    )
    raw_close = float(anchor["close"]) * 3.0 * np.cumprod(
        np.full(new_periods, 1.002)
    )
    raw_open = raw_close * 0.998
    frame = pd.DataFrame(
        {
            "date": [BASELINE_DATE, *new_dates],
            "open": [float(anchor["open"]) * 3.0, *raw_open],
            "high": [float(anchor["high"]) * 3.0, *(raw_close * 1.01)],
            "low": [float(anchor["low"]) * 3.0, *(raw_open * 0.99)],
            "close": [float(anchor["close"]) * 3.0, *raw_close],
            "volume": [2_000_000.0, *np.full(new_periods, 2_500_000.0)],
        }
    )
    frame["adj_close"] = frame["close"] / 3.0
    return frame


def test_chain_link_matches_frozen_anchor_without_replacing_history() -> None:
    baseline, _ = _baseline()
    provider = _provider(baseline, 3)
    extension = chain_link_provider_history(baseline, provider)
    assert len(extension.adjusted_new) == 3
    assert extension.adjusted_new["date"].min() > BASELINE_DATE
    assert np.isclose(extension.chain_scale, 1.0)
    assert np.isclose(
        extension.anchor_canonical_adjusted_close,
        baseline.iloc[-1]["close"],
    )
    expected_first = provider.iloc[1]["adj_close"]
    assert np.isclose(extension.adjusted_new.iloc[0]["close"], expected_first)


def test_independent_audit_quarantines_disputed_open_without_replacement() -> None:
    baseline, _ = _baseline()
    extension = chain_link_provider_history(baseline, _provider(baseline, 2))
    secondary = extension.primary_raw_new.copy()
    secondary.loc[secondary.index[0], "open"] *= 1.05
    audit = audit_independent_raw(
        extension.primary_raw_new,
        secondary,
        secondary_provider="synthetic_independent_raw",
    )
    assert not bool(audit.row_audit.iloc[0]["open_research_eligible"])
    assert bool(audit.row_audit.iloc[1]["open_research_eligible"])
    assert np.isclose(
        audit.row_audit.iloc[0]["open_primary"],
        extension.primary_raw_new.iloc[0]["open"],
    )


def test_signal_records_are_append_only_and_idempotent(tmp_path: Path) -> None:
    baseline, sessions = _baseline()
    extension = chain_link_provider_history(baseline, _provider(baseline, 25))
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
    observations, dataset, shadow_decision = make_signal_observations(
        adjusted,
        extended_sessions,
        extension,
        audit,
        observed_at_utc="2026-08-04T10:00:00+00:00",
        primary_provider="synthetic_primary",
    )
    assert observations
    assert observations[0]["schema_version"] == SHADOW_SCHEMA

    first = persist_shadow_store(
        tmp_path,
        observations,
        dataset,
        shadow_decision,
    )
    second = persist_shadow_store(
        tmp_path,
        observations,
        dataset,
        shadow_decision,
    )
    assert first["ledger_sha256"] == second["ledger_sha256"]
    assert first["observation_count"] == 25
    assert first["outcome_count"] > 0

    changed = dict(observations[0])
    changed["base_target_position"] = 1.0 - changed["base_target_position"]
    with pytest.raises(RuntimeError, match="append-only record drift"):
        persist_shadow_store(
            tmp_path,
            [changed],
            dataset,
            shadow_decision,
        )


def test_manifest_references_individual_immutable_observations(tmp_path: Path) -> None:
    baseline, sessions = _baseline()
    extension = chain_link_provider_history(baseline, _provider(baseline, 3))
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
    observations, dataset, shadow_decision = make_signal_observations(
        adjusted,
        extended_sessions,
        extension,
        audit,
        observed_at_utc="2026-08-04T10:00:00+00:00",
    )
    persist_shadow_store(tmp_path, observations, dataset, shadow_decision)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["append_only"] is True
    assert manifest["observation_count"] == 3
    assert len(manifest["observation_sha256"]) == 3
    assert (tmp_path / "ledger.csv").exists()
