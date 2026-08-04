from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from src.research.v4_25_new_information_phase0 import run_new_information_phase0

CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_new_information_v4_25_phase0.yaml"
)


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_contract_forbids_outcomes_and_model_training() -> None:
    contract = _contract()
    assert contract["phase"] == 0
    assert contract["outcome_calculation_authorized"] is False
    assert contract["boundaries"]["no_outcomes"] is True
    assert contract["boundaries"]["no_future_returns"] is True
    assert contract["boundaries"]["no_path_utility"] is True
    assert contract["boundaries"]["no_xgboost_training"] is True
    assert contract["boundaries"]["no_portfolio"] is True


def test_truncated_and_unresolved_sources_reject_all_families() -> None:
    contract = _contract()
    calendar = pd.bdate_range("2010-01-04", "2026-08-04")
    short = "DATE,BAMLH0A0HYM2\n2023-08-01,3.9\n2026-08-03,3.2\n".encode()
    corporate = "DATE,BAMLC0A0CM\n2023-08-01,1.2\n2026-08-03,0.9\n".encode()
    old_pc = (
        "DATE,CALL,PUT,TOTAL,P/C Ratio\n"
        "01/03/2011,100,90,190,0.9\n10/04/2019,120,110,230,0.92\n"
    ).encode()
    equity_pc = (
        "DATE,CALL,PUT,TOTAL,P/C Ratio\n"
        "01/03/2011,100,60,160,0.6\n10/04/2019,120,70,190,0.58\n"
    ).encode()

    def fetcher(url: str) -> bytes:
        if "BAMLH0A0HYM2" in url:
            return short
        if "BAMLC0A0CM" in url:
            return corporate
        if "totalpc.csv" in url:
            return old_pc
        if "equitypc.csv" in url:
            return equity_pc
        raise AssertionError(url)

    result = run_new_information_phase0(calendar, contract, fetcher=fetcher)
    assert result.decision == "new_information_phase0_no_family_admissible"
    assert result.admitted_families == ()
    assert result.outcome_calculation_authorized is False
    assert not result.family_audit["admissible"].any()
    assert set(result.normalized_availability.columns) == {
        "observation_date",
        "source_id",
        "family",
        "value_present",
        "published_at_class",
        "safe_lag_qqq_sessions",
        "safe_decision_date",
    }
    assert "value" not in result.normalized_availability.columns
    cboe = result.normalized_availability.loc[
        result.normalized_availability["source_id"].eq(
            "cboe_total_put_call_archive"
        )
    ]
    assert cboe["value_present"].all()
    audit = result.source_audit.set_index("source_id").loc[
        "cboe_total_put_call_archive"
    ]
    assert int(audit["usable_rows"]) == 2
    assert int(audit["maximum_unexplained_gap_sessions"]) > 5
    assert "insufficient_decision_date_coverage" in audit["rejection_reason"]


def test_after_close_observation_is_lagged_to_next_qqq_session() -> None:
    contract = _contract()
    calendar = pd.DatetimeIndex(["2011-01-03", "2011-01-04", "2011-01-05"])
    total = (
        "DATE,CALL,PUT,TOTAL,P/C Ratio\n"
        "01/03/2011,100,90,190,0.9\n"
    ).encode()
    equity = (
        "DATE,CALL,PUT,TOTAL,P/C Ratio\n"
        "01/03/2011,100,60,160,0.6\n"
    ).encode()
    fred_hy = "DATE,BAMLH0A0HYM2\n2011-01-03,4.0\n".encode()
    fred_ig = "DATE,BAMLC0A0CM\n2011-01-03,1.5\n".encode()

    def fetcher(url: str) -> bytes:
        if "totalpc.csv" in url:
            return total
        if "equitypc.csv" in url:
            return equity
        if "BAMLH0A0HYM2" in url:
            return fred_hy
        if "BAMLC0A0CM" in url:
            return fred_ig
        raise AssertionError(url)

    result = run_new_information_phase0(calendar, contract, fetcher=fetcher)
    total_row = result.normalized_availability.loc[
        result.normalized_availability["source_id"].eq("cboe_total_put_call_archive")
    ].iloc[0]
    assert bool(total_row["value_present"])
    assert pd.Timestamp(total_row["safe_decision_date"]) == pd.Timestamp("2011-01-04")
