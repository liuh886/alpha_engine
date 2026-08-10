"""Translate a trading-session embargo onto the frozen non-overlapping grid."""

from __future__ import annotations

import math

import pandas as pd


def embargo_train_end(
    index: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    declared_train_end: pd.Timestamp,
    embargo_sessions: int,
    sample_every_sessions: int = 10,
) -> pd.Timestamp:
    if embargo_sessions < 0:
        raise ValueError("embargo_sessions must be non-negative")
    if sample_every_sessions <= 0:
        raise ValueError("sample_every_sessions must be positive")
    location = int(index.searchsorted(test_start, side="left"))
    # A ten-session label begins after its decision close. With a decision every
    # ten sessions, the immediately preceding group is not admissible. The next
    # earlier group leaves nineteen intervening sessions, satisfying the frozen
    # ten-session embargo without accidentally removing ten complete groups.
    embargo_groups = int(math.ceil((embargo_sessions + 1) / sample_every_sessions))
    location = max(location - embargo_groups, 0)
    return min(declared_train_end, pd.Timestamp(index[location]))
