from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.refresh_ranker_formal import (
    RankerRefreshError,
    _date_identity,
    _latest_realized_holding_end,
    _update_common_metadata,
)


def test_date_identity_normalizes_pandas_timestamp() -> None:
    assert _date_identity(pd.Timestamp("2026-07-15")) == "2026-07-15"
    assert _date_identity("2026-07-15 00:00:00") == "2026-07-15"
    accepted_dates = {_date_identity("2026-07-15")}
    assert _date_identity(pd.Timestamp("2026-07-15")) in accepted_dates


def test_date_identity_rejects_missing_value() -> None:
    with pytest.raises(RankerRefreshError, match="invalid date identity"):
        _date_identity(None)


def test_latest_realized_holding_end_preserves_accepted_receipt() -> None:
    package = {
        "freshness": {"latest_realized_holding_end": "2026-07-29"},
        "report": [{"date": "2026-07-15"}],
        "positions": [],
        "trades": [],
    }

    assert _latest_realized_holding_end(package) == "2026-07-29"


def test_common_metadata_keeps_realized_end_when_no_new_period_exists(
    tmp_path: Path,
) -> None:
    provider_manifest = tmp_path / "provider.json"
    provider_manifest.write_text(json.dumps({"cutoff": "2026-08-07"}))
    package = {
        "date_range": {"start": "2022-07-01", "end": "2026-08-03"},
        "freshness": {"latest_realized_holding_end": "2026-07-29"},
        "report": [{"date": "2026-07-15"}],
        "positions": [],
        "trades": [],
        "evidence": {},
    }

    _update_common_metadata(
        package,
        cutoff="2026-08-07",
        generated_at="2026-08-09T04:16:42Z",
        provider_manifest=provider_manifest,
        evidence={},
    )

    assert package["evidence_cutoff"] == "2026-08-07"
    assert package["freshness"]["latest_completed_session"] == "2026-08-07"
    assert package["freshness"]["latest_realized_holding_end"] == "2026-07-29"
    assert package["research_only"] is True
    assert package["trade_ready"] is False
