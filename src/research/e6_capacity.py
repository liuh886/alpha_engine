"""Source-bound lagged dollar-volume admission screen, never a fill simulator."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

RAW_ARCHIVE_SHA = "124b929231fd2a23dd21cdd50855a20ca064134b877977bfe5a7d042ba415022"


def source_pairs(archive: Path, close: pd.DataFrame, volume: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RAW_ARCHIVE_SHA:
        raise ValueError("capacity source archive differs from the frozen v6 source")
    data, receipts = [], []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:
            raise ValueError("raw provider archive CRC failed")
        seen = set()
        for name in z.namelist():
            if not name.endswith("/request.json"):
                continue
            receipt = json.loads(z.read(name))
            symbol = receipt["symbol"]
            if symbol not in close.columns:
                continue
            if symbol in seen or receipt["request"]["auto_adjust"] is not False:
                raise ValueError("ambiguous provider symbol or adjustment request")
            seen.add(symbol)
            payload = z.read(name.rsplit("/",1)[0]+"/raw.parquet")
            if hashlib.sha256(payload).hexdigest() != receipt["raw_sha256"]:
                raise ValueError("provider raw frame hash mismatch")
            frame = pd.read_parquet(io.BytesIO(payload))
            frame.columns = frame.columns.get_level_values(0)
            frame.index = frame.index.strftime("%Y-%m-%d")
            frame = frame.loc[close.index]
            np.testing.assert_array_equal(frame["Volume"].to_numpy(),volume[symbol].to_numpy())
            # Check the link to E5 adjusted history, allowing only CSV float roundtrip.
            if not np.allclose(frame["Adj Close"],close[symbol],atol=1e-10,rtol=1e-13):
                raise ValueError("raw adjusted close does not reconcile to E5 source")
            if not np.isfinite(frame[["Close","Volume"]].to_numpy()).all() or (frame[["Close","Volume"]]<=0).any().any():
                raise ValueError("invalid raw price/volume pair")
            for day, price, shares in zip(frame.index,frame["Close"],frame["Volume"]):
                data.append({"date":day,"symbol":symbol,"raw_close":float(price),
                             "provider_volume":float(shares),"close_volume_proxy":float(price*shares)})
            receipts.append({"symbol":symbol,"raw_sha256":receipt["raw_sha256"],
                             "observed_snapshot_at_utc":receipt["retrieved_at_utc"]})
        if seen != set(close.columns):
            raise ValueError("capacity raw source missing selected symbols")
    return pd.DataFrame(data), {"source_archive_sha256":RAW_ARCHIVE_SHA,"symbols":receipts,
        "volume_units_certified":False,"historical_first_available_certified":False,
        "actual_capacity_gate":"BLOCKED_VOLUME_UNITS_AND_HISTORICAL_AVAILABILITY",
        "proxy":"raw_Close_times_provider_Volume_not_VWAP_or_exact_dollar_volume"}


def capacity_screen(daily: pd.DataFrame, assets: pd.DataFrame, pairs: pd.DataFrame,
                    prices: pd.DataFrame, *, window: int = 20, participation: float = .01
                    ) -> tuple[pd.DataFrame, dict]:
    """Bound research capital by prior-session ADV; reject real-fill claims."""
    if window < 1 or not 0 < participation <= 1:
        raise ValueError("invalid declared capacity scenario")
    calendar = list(prices.index)
    adv = pairs.pivot(index="date",columns="symbol",values="close_volume_proxy").reindex(prices.index).rolling(window).mean()
    vol = prices.pct_change(fill_method=None).rolling(window).std()*np.sqrt(252)
    days = daily.set_index("date")
    day_records = days.to_dict(orient="index")
    terminal_dates = set(daily.loc[daily["terminal_fill_session"].notna(),"date"])
    trading = assets.loc[(assets["trade_weight"].abs()>1e-14) |
                         (assets["date"].isin(terminal_dates) & (assets["drifted_weight"]>0))]
    events = []
    for row in trading.itertuples():
        day = day_records[row.date]
        legs = [(row.fill_session,abs(row.trade_weight)*day["nav_before"],"rebalance")]
        if day["terminal_fill_session"] is not None and pd.notna(day["terminal_fill_session"]):
            legs.append((row.date,row.drifted_weight*day["nav_before"]*(1+day["gross"]),"forced_fold_exit"))
        for fill, notional, leg in legs:
            if notional <= 1e-14:
                continue
            pos = calendar.index(fill)
            if pos < window:
                raise ValueError("insufficient strictly prior capacity history")
            information = calendar[pos-1]
            average = float(adv.loc[information,row.symbol])
            if not np.isfinite(average) or average <= 0:
                raise ValueError("unavailable lagged ADV proxy")
            ceiling = participation*average/notional
            events.append({"fill_session":fill,"information_through":information,
                "symbol":row.symbol,"leg":leg,"notional_per_initial_nav":float(notional),
                "lagged_close_volume_adv_proxy":average,
                "past20d_annualized_volatility":float(vol.loc[information,row.symbol]),
                "max_initial_capital_usd_proxy":ceiling,
                "scenario_1m_breaches":ceiling<1_000_000,
                "scenario_10m_breaches":ceiling<10_000_000,
                "actual_fill_observed":False,"capacity_certified":False})
    result = pd.DataFrame(events)
    if result.empty:
        raise ValueError("no capacity-screenable transactions")
    return result, {"proxy_events":len(result),"min_initial_capital_ceiling_proxy":float(result["max_initial_capital_usd_proxy"].min()),
        "scenario_1m_breaches":int(result["scenario_1m_breaches"].sum()),
        "scenario_10m_breaches":int(result["scenario_10m_breaches"].sum()),
        "forced_exit_proxy_events":int((result["leg"]=="forced_fold_exit").sum()),
        "actual_capacity_gate":"BLOCKED_VOLUME_UNITS_AND_HISTORICAL_AVAILABILITY",
        "unfilled_order_policy":"screen_rejects_capacity_claim_no_partial_fills_invented"}
