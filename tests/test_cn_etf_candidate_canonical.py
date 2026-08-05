from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.cn_etf_candidate_canonical import (
    SCHEMA_VERSION,
    ETFSpec,
    build_candidate_bundle,
)


def make_raw(rows: int = 1600) -> pd.DataFrame:
    dates = pd.date_range("2019-01-01", periods=rows, freq="B")
    close = 10.0 + np.arange(rows) * 0.002
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


def build(raw: pd.DataFrame, secondary: pd.DataFrame | None = None):
    cutoff = raw["date"].iloc[-1].strftime("%Y-%m-%d")
    return build_candidate_bundle(
        spec=ETFSpec(
            symbol="512890.SH",
            provider_symbol="512890.SS",
            cutoff=cutoff,
        ),
        raw_primary=raw,
        provider_adjusted_close=raw[["date", "close"]].rename(
            columns={"close": "adjusted_close"}
        ),
        corporate_actions=pd.DataFrame(
            columns=["date", "dividend", "stock_split", "event_source"]
        ),
        raw_secondary=raw.copy() if secondary is None else secondary,
        secondary_provider="synthetic_secondary",
        provider_parameters={"test": True},
    )


def test_candidate_bundle_preserves_symbol_and_quality_contract() -> None:
    raw = make_raw()
    bundle, quality = build(raw)
    assert bundle.manifest["schema_version"] == SCHEMA_VERSION
    assert bundle.manifest["symbol"] == "512890.SH"
    assert bundle.manifest["provider_symbol"] == "512890.SS"
    assert bundle.manifest["cross_provider_stitching"] is False
    assert quality.passed
    assert bundle.session_audit["open_research_eligible"].all()


def test_secondary_disagreement_quarantines_without_substitution() -> None:
    raw = make_raw()
    secondary = raw.copy()
    secondary.loc[100, "open"] *= 1.05
    secondary.loc[100, "high"] = secondary.loc[100, "open"] * 1.001
    bundle, quality = build(raw, secondary)
    date = raw.loc[100, "date"]
    audit = bundle.session_audit.set_index("date")
    assert not bool(audit.loc[date, "open_research_eligible"])
    assert bundle.raw_bars.loc[100, "open"] == raw.loc[100, "open"]
    assert not quality.passed
    assert not quality.gates["open_return_correlation"]
