import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_filter_by_min_liquidity_keeps_only_eligible():
    from src.common.universe import filter_by_min_liquidity

    def fake_features(instruments, fields, start_time=None, end_time=None):
        idx = pd.MultiIndex.from_product([instruments, [pd.Timestamp(start_time)]], names=["instrument", "datetime"])
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        # A is liquid, B is not
        df.loc[("A", pd.Timestamp(start_time)), fields[0]] = 1.0
        df.loc[("A", pd.Timestamp(start_time)), fields[1]] = 2_000_000.0
        df.loc[("B", pd.Timestamp(start_time)), fields[0]] = 1.0
        df.loc[("B", pd.Timestamp(start_time)), fields[1]] = 500_000.0
        return df

    out = filter_by_min_liquidity(
        ["A", "B"],
        asof_time="2025-01-02",
        min_liquidity=1_000_000,
        fetch_features=fake_features,
    )
    assert out == ["A"]


def test_apply_profile_universe_filters_reads_min_liquidity():
    from src.common.universe import apply_profile_universe_filters

    def fake_features(instruments, fields, start_time=None, end_time=None):
        idx = pd.MultiIndex.from_product([instruments, [pd.Timestamp(start_time)]], names=["instrument", "datetime"])
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        df.loc[("A", pd.Timestamp(start_time)), fields[0]] = 1.0
        df.loc[("A", pd.Timestamp(start_time)), fields[1]] = 2_000_000.0
        df.loc[("B", pd.Timestamp(start_time)), fields[0]] = 1.0
        df.loc[("B", pd.Timestamp(start_time)), fields[1]] = 500_000.0
        return df

    profile = {"universe": {"filters": {"min_liquidity": 1_000_000}}}
    out = apply_profile_universe_filters(
        ["A", "B"],
        profile=profile,
        asof_time="2025-01-02",
        fetch_features=fake_features,
    )
    assert out == ["A"]
