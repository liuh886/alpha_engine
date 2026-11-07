"""E5 rejects false parity and uses genuinely older signals / mature IC labels."""
import numpy as np
import pandas as pd
import pytest

from src.research.e5_execution_review import compare_e4, latency_scores, rank_ic, score_diagnostics
from src.research.portfolio_ledger import replay_ledger, summarize_ledger


def data():
    days = pd.bdate_range("2026-01-02", periods=12).strftime("%Y-%m-%d").tolist()
    prices = pd.DataFrame({"A": np.arange(12.)+10, "B": np.arange(12.)*.1+20,
                           "C": 30-np.arange(12.)*.2}, index=days)
    scores = pd.DataFrame(np.tile([3.,2.,1.],(12,1)), index=days, columns=prices.columns)
    return days, prices, scores


def test_latency_uses_previous_session_information_even_across_weekend():
    days, prices, scores = data()
    scores.loc[days[0]] = [0.,2.,3.]
    shifted, mapping = latency_scores(scores, days[1:], days)
    assert mapping[days[1]] == days[0]
    assert shifted.loc[days[1]].tolist() == [0.,2.,3.]
    assert all(mapping[fill] < fill for fill in mapping)
    daily, _ = replay_ledger(scores=shifted, prices=prices, qqq=prices["A"],
        sessions=days[1:], top_k=1, mode="delayed_close_1session",signal_sessions=mapping)
    assert daily["gross"].iloc[0] == pytest.approx(prices["C"].iloc[2]/prices["C"].iloc[1]-1)
    with pytest.raises(ValueError,match="earlier information"):
        latency_scores(scores, days, days)


def test_five_day_ic_excludes_unmatured_fold_tail_and_future_data():
    days, prices, scores = data()
    oos = days[:10]
    result = rank_ic(scores, prices, oos)
    assert result["rank_ic_5d"]["mature_oos_labels"] == 5
    assert result["rank_ic_5d"]["immature_excluded"] == 5
    assert result["rank_ic_5d"]["mean"] == pytest.approx(1.)
    prices.loc[days[10:]] *= 100
    assert rank_ic(scores, prices, oos) == result


def test_parity_rejects_daily_and_aggregate_difference():
    days, prices, scores = data()
    daily, assets = replay_ledger(scores=scores,prices=prices,qqq=prices["A"],sessions=days,top_k=1)
    summary = summarize_ledger(daily, assets)
    record = {"daily_trace": daily[["date","gross","net","turnover","qqq"]].to_dict("records")}
    for a,b in (("net_return","net_cumulative_return"),("qqq_return","qqq_cumulative_return"),
                ("net_excess","net_excess_return"),("max_drawdown","max_drawdown"),("turnover","total_turnover")):
        record[b] = summary[a]
    assert compare_e4(daily,summary,record)["status"].endswith("PASS")
    record["net_cumulative_return"] += .001
    with pytest.raises(ValueError,match="aggregate parity"):
        compare_e4(daily,summary,record)
    record["daily_trace"][0]["turnover"] += .001
    with pytest.raises(ValueError,match="turnover"):
        compare_e4(daily,summary,record)


def test_signal_strings_cannot_replace_actual_engine_tie_holdings():
    symbols = list("ABCDEFG")
    dates = ["2026-01-02", "2026-01-05", "2026-01-06"]
    scores = pd.DataFrame(1.0, index=dates, columns=symbols)
    assets = pd.DataFrame([{"date":d,"symbol":s,"simulated_held_weight":.2 if s in "CDEFG" else 0.0}
                           for d in dates[1:] for s in symbols])
    record = {"top5_score_signals_not_executed_trades": [
        {"date":d,"top5_signal_symbols":list("ABCDE")} for d in dates[1:]]}
    result = score_diagnostics(scores,dates,assets,record)
    assert result["top5_cutoff_tied_decisions"] == 2
    assert result["published_signal_set_differs_from_engine_holdings_dates"] == 2
