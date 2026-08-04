from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.etf_515180_canonical import build_515180_bundle


def make_raw(rows: int = 1600) -> pd.DataFrame:
    dates = pd.date_range("2019-11-26", periods=rows, freq="B")
    close = 1.0 + np.arange(rows) * 0.0002
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.full(rows, 1_000_000.0),
        }
    )


def test_etf_bundle_has_independent_schema_and_eligibility() -> None:
    raw = make_raw()
    cutoff = raw["date"].iloc[-1].strftime("%Y-%m-%d")
    adjusted_close = raw[["date", "close"]].rename(columns={"close": "adjusted_close"})
    bundle, quality = build_515180_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted_close,
        corporate_actions=pd.DataFrame(
            columns=["date", "dividend", "stock_split", "event_source"]
        ),
        raw_secondary=raw.copy(),
        secondary_provider="synthetic_secondary",
        provider_parameters={"test": True},
        cutoff=cutoff,
    )
    assert bundle.manifest["schema_version"] == "cn_etf_canonical_total_return_v1"
    assert bundle.manifest["symbol"] == "515180.SH"
    assert bundle.manifest["cross_provider_stitching"] is False
    assert quality.passed
    assert bundle.session_audit["open_research_eligible"].all()


def test_secondary_disagreement_quarantines_open_without_substitution() -> None:
    raw = make_raw()
    secondary = raw.copy()
    secondary.loc[100, "open"] *= 1.05
    secondary.loc[100, "high"] = secondary.loc[100, "open"] * 1.001
    cutoff = raw["date"].iloc[-1].strftime("%Y-%m-%d")
    adjusted_close = raw[["date", "close"]].rename(columns={"close": "adjusted_close"})
    bundle, _ = build_515180_bundle(
        raw_primary=raw,
        provider_adjusted_close=adjusted_close,
        corporate_actions=pd.DataFrame(
            columns=["date", "dividend", "stock_split", "event_source"]
        ),
        raw_secondary=secondary,
        secondary_provider="synthetic_secondary",
        provider_parameters={"test": True},
        cutoff=cutoff,
    )
    date = raw.loc[100, "date"]
    audit = bundle.session_audit.set_index("date")
    assert not bool(audit.loc[date, "open_research_eligible"])
    assert bundle.raw_bars.loc[100, "open"] == raw.loc[100, "open"]
