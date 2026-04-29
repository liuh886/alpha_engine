import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_top_fraction_selects_expected_count():
    from src.strategies.weekly_quant_rating_rules import select_top_fraction

    items = [("A", 0.9), ("B", 0.8), ("C", 0.7), ("D", 0.6), ("E", 0.5)]
    top = select_top_fraction(items, 0.2)
    assert top == {"A"}


def test_streak_updates_and_resets():
    from src.strategies.weekly_quant_rating_rules import update_streaks

    streaks = {}
    strongbuy_today = {"A", "B"}
    streaks = update_streaks(streaks, strongbuy_today)
    assert streaks["A"] == 1
    assert streaks["B"] == 1

    strongbuy_today = {"A"}  # B drops out -> reset to 0 or removed
    streaks = update_streaks(streaks, strongbuy_today)
    assert streaks["A"] == 2
    assert streaks.get("B", 0) == 0


def test_last_trading_day_of_week_detection():
    from datetime import date

    from src.strategies.weekly_quant_rating_rules import is_last_trading_day_of_week

    assert not is_last_trading_day_of_week(date(2026, 1, 5), date(2026, 1, 6))  # Mon -> Tue
    assert is_last_trading_day_of_week(date(2026, 1, 9), date(2026, 1, 12))  # Fri -> next Mon
    assert is_last_trading_day_of_week(date(2026, 1, 9), None)  # end of data


def test_select_target_respects_streak_and_sorts_by_score():
    from src.strategies.weekly_quant_rating_rules import select_target

    scores = {"A": 0.9, "B": 0.8, "C": 0.7}
    streaks = {"A": 3, "B": 2, "C": 5}
    eligible = {"A": True, "B": True, "C": True}

    target = select_target(
        scores_by_instrument=scores,
        streaks=streaks,
        eligible_by_instrument=eligible,
        strongbuy_consecutive_days=3,
        universe_size=30,
    )
    assert target == ["A", "C"]


def test_strategy_compiler_emits_weekly_quant_rating_strategy():
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "meta": {"benchmark_by_market": {"us": "QQQ"}},
        "strategy": {
            "strategy_mode": "weekly_quant_rating",
            "universe_size": 30,
            "strongbuy_consecutive_days": 3,
            "strongbuy_fraction": 0.2,
            "min_dollar_vol_20d": 10_000_000,
            "price_cap": 10_000,
            "lookback_days": 20,
        },
    }
    base = {
        "task": {"dataset": {"kwargs": {"handler": {"kwargs": {}}}}},
        "port_analysis_config": {
            "strategy": {
                "class": "BiweeklyTrendStrategy",
                "module_path": "src.strategies.biweekly_trend_strategy",
                "kwargs": {
                    "topk": 5,
                    "n_drop": 5,
                    "rebalance_steps": 10,
                    "min_hold_days": 10,
                    "sell_ma_window": 60,
                    "sell_rank_threshold": 20,
                },
            }
        },
    }
    cfg = apply_profile_to_config(profile, base, "us")

    strat = cfg["port_analysis_config"]["strategy"]
    assert strat.get("class") == "WeeklyQuantRatingStrategy"
    assert strat.get("module_path") == "src.strategies.weekly_quant_rating_strategy"
    kwargs = strat.get("kwargs", {})
    assert kwargs.get("universe_size") == 30
    assert kwargs.get("strongbuy_consecutive_days") == 3
    assert "topk" not in kwargs
    assert "n_drop" not in kwargs
    assert "rebalance_steps" not in kwargs
    assert "min_hold_days" not in kwargs
    assert "sell_ma_window" not in kwargs
    assert "sell_rank_threshold" not in kwargs


def test_strategy_compiler_clears_weekly_quant_rating_kwargs_when_switching_to_trend():
    from src.workflows.profile_compiler import apply_profile_to_config

    profile = {
        "strategy": {
            "rebalance_frequency": "biweekly",
            "min_hold_days": 10,
            "sell_on_ma": 60,
            "sell_rank_threshold": 20,
            "position_rule": {"topk": 5, "n_drop": 5},
        }
    }
    base = {
        "task": {"dataset": {"kwargs": {"handler": {"kwargs": {}}}}},
        "port_analysis_config": {
            "strategy": {
                "class": "WeeklyQuantRatingStrategy",
                "module_path": "src.strategies.weekly_quant_rating_strategy",
                "kwargs": {
                    "signal": "<PRED>",
                    "universe_size": 30,
                    "strongbuy_consecutive_days": 3,
                    "strongbuy_fraction": 0.2,
                    "lookback_days": 20,
                    "min_dollar_vol_20d": 10_000_000,
                    "price_cap": 10_000,
                },
            }
        },
    }

    cfg = apply_profile_to_config(profile, base, "us")

    strat = cfg["port_analysis_config"]["strategy"]
    assert strat.get("class") == "BiweeklyTrendStrategy"
    assert strat.get("module_path") == "src.strategies.biweekly_trend_strategy"

    kwargs = strat.get("kwargs", {})
    assert kwargs.get("rebalance_steps") == 10
    assert kwargs.get("min_hold_days") == 10
    assert kwargs.get("sell_ma_window") == 60
    assert kwargs.get("sell_rank_threshold") == 20

    assert "universe_size" not in kwargs
    assert "strongbuy_consecutive_days" not in kwargs
    assert "strongbuy_fraction" not in kwargs
    assert "lookback_days" not in kwargs
    assert "min_dollar_vol_20d" not in kwargs
    assert "price_cap" not in kwargs


def test_strategy_class_loadable():
    from src.strategies.weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

    assert WeeklyQuantRatingStrategy is not None


def test_strategy_normalize_signal_handles_multiindex_without_names():
    import pandas as pd

    from src.strategies.weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2025-01-02", "2025-01-03"]), ["A", "B"]],
        names=[None, None],
    )
    ser = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)
    out = WeeklyQuantRatingStrategy(signal=pd.Series(dtype=float))._normalize_signal(ser)
    assert list(out.index) == ["A", "B"]
    assert out.loc["A"] == 3.0
    assert out.loc["B"] == 4.0


def test_strategy_trades_only_on_week_last_day(monkeypatch):
    import pandas as pd

    from src.strategies.weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

    class FakeSignal:
        def __init__(self, scores_by_date):
            self.scores_by_date = scores_by_date

        def get_signal(self, start_time=None, end_time=None):
            key = pd.Timestamp(end_time).strftime("%Y-%m-%d")
            return self.scores_by_date[key]

    class FakeTradeCalendar:
        def __init__(self, dates, trade_step):
            self.dates = [pd.Timestamp(d) for d in dates]
            self._trade_step = trade_step

        def get_trade_step(self):
            return self._trade_step

        def get_step_time(self, trade_step=None, shift=0):
            base_step = self._trade_step if trade_step is None else trade_step
            idx = base_step
            if shift == 1:
                idx = base_step - 1
            elif shift == -1:
                idx = base_step + 1
            if idx < 0 or idx >= len(self.dates):
                raise IndexError("step out of range")
            t = self.dates[idx]
            return t, t

    class FakePosition:
        def __init__(self, cash):
            self._cash = float(cash)
            self._holdings = {}

        def get_cash(self):
            return self._cash

        def set_cash(self, cash):
            self._cash = float(cash)

        def get_stock_list(self):
            return list(self._holdings.keys())

        def get_stock_amount(self, code):
            return float(self._holdings.get(code, 0.0))

        def set_stock_amount(self, code, amount):
            if amount <= 0:
                self._holdings.pop(code, None)
            else:
                self._holdings[code] = float(amount)

    class FakeExchange:
        def is_stock_tradable(self, **kwargs):
            return True

        def get_deal_price(self, **kwargs):
            return 100.0

        def get_factor(self, **kwargs):
            return 1.0

        def round_amount_by_trade_unit(self, amount, factor):
            return float(amount)

        def check_order(self, order):
            return True

        def deal_order(self, order, position):
            price = 100.0
            amt = float(order.amount)
            if order.direction.name == "SELL":
                position.set_stock_amount(order.stock_id, 0.0)
                trade_val = amt * price
                position.set_cash(position.get_cash() + trade_val)
                return trade_val, 0.0, None
            position.set_stock_amount(
                order.stock_id, position.get_stock_amount(order.stock_id) + amt
            )
            trade_val = amt * price
            position.set_cash(position.get_cash() - trade_val)
            return trade_val, 0.0, None

    # Patch qlib D.features to always pass tradability filters
    def fake_features(instruments, fields, start_time=None, end_time=None):
        idx = pd.MultiIndex.from_product(
            [instruments, [pd.Timestamp(end_time)]], names=["instrument", "datetime"]
        )
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        for f in fields:
            if "$close" in f:
                df[f] = 100.0
            elif "Mean($money" in f:
                df[f] = 20_000_000.0
            elif "Min($volume" in f:
                df[f] = 1.0
            else:
                df[f] = 1.0
        return df

    import qlib.data

    monkeypatch.setattr(qlib.data.D, "features", fake_features, raising=False)

    scores = pd.Series({"A": 0.9, "B": 0.1})
    signal = FakeSignal({"2026-01-08": scores})

    class TradeAccount:
        def __init__(self, position):
            self.current_position = position

    position = FakePosition(cash=10_000)
    exchange = FakeExchange()
    calendar = FakeTradeCalendar(
        ["2026-01-08", "2026-01-09", "2026-01-12"], trade_step=1
    )  # Fri is last of week

    strat = WeeklyQuantRatingStrategy(
        signal=pd.Series(dtype=float),
        universe_size=30,
        strongbuy_consecutive_days=1,
        strongbuy_fraction=0.5,
        lookback_days=20,
        min_dollar_vol_20d=10_000_000,
        price_cap=10_000,
        common_infra={"trade_account": TradeAccount(position), "trade_exchange": exchange},
        level_infra={"trade_calendar": calendar},
    )
    strat.signal = signal

    decision = strat.generate_trade_decision()
    assert len(decision.order_list) == 1
    assert decision.order_list[0].stock_id == "A"


def test_strategy_sells_names_not_in_target_on_rebalance(monkeypatch):
    import pandas as pd

    from src.strategies.weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

    class FakeSignal:
        def __init__(self, scores_by_date):
            self.scores_by_date = scores_by_date

        def get_signal(self, start_time=None, end_time=None):
            key = pd.Timestamp(end_time).strftime("%Y-%m-%d")
            return self.scores_by_date[key]

    class FakeTradeCalendar:
        def __init__(self, dates, trade_step):
            self.dates = [pd.Timestamp(d) for d in dates]
            self._trade_step = trade_step

        def get_trade_step(self):
            return self._trade_step

        def get_step_time(self, trade_step=None, shift=0):
            base_step = self._trade_step if trade_step is None else trade_step
            idx = base_step
            if shift == 1:
                idx = base_step - 1
            elif shift == -1:
                idx = base_step + 1
            if idx < 0 or idx >= len(self.dates):
                raise IndexError("step out of range")
            t = self.dates[idx]
            return t, t

    class FakePosition:
        def __init__(self, cash):
            self._cash = float(cash)
            self._holdings = {}

        def get_cash(self):
            return self._cash

        def set_cash(self, cash):
            self._cash = float(cash)

        def get_stock_list(self):
            return list(self._holdings.keys())

        def get_stock_amount(self, code):
            return float(self._holdings.get(code, 0.0))

        def set_stock_amount(self, code, amount):
            if amount <= 0:
                self._holdings.pop(code, None)
            else:
                self._holdings[code] = float(amount)

    class FakeExchange:
        def is_stock_tradable(self, **kwargs):
            return True

        def get_deal_price(self, **kwargs):
            return 100.0

        def get_factor(self, **kwargs):
            return 1.0

        def round_amount_by_trade_unit(self, amount, factor):
            return float(amount)

        def check_order(self, order):
            return True

    def fake_features(instruments, fields, start_time=None, end_time=None):
        idx = pd.MultiIndex.from_product(
            [instruments, [pd.Timestamp(end_time)]], names=["instrument", "datetime"]
        )
        df = pd.DataFrame(index=idx, columns=fields, dtype=float)
        for f in fields:
            if "$close" in f:
                df[f] = 100.0
            elif "Mean($money" in f:
                df[f] = 20_000_000.0
            elif "Min($volume" in f:
                df[f] = 1.0
            else:
                df[f] = 1.0
        return df

    import qlib.data

    monkeypatch.setattr(qlib.data.D, "features", fake_features, raising=False)

    scores = pd.Series({"A": 0.9, "B": 0.1})
    signal = FakeSignal({"2026-01-08": scores})

    class TradeAccount:
        def __init__(self, position):
            self.current_position = position

    position = FakePosition(cash=10_000)
    position.set_stock_amount("B", 10.0)  # holding name that will be dropped
    exchange = FakeExchange()
    calendar = FakeTradeCalendar(["2026-01-08", "2026-01-09", "2026-01-12"], trade_step=1)

    strat = WeeklyQuantRatingStrategy(
        signal=pd.Series(dtype=float),
        universe_size=30,
        strongbuy_consecutive_days=1,
        strongbuy_fraction=0.5,
        lookback_days=20,
        min_dollar_vol_20d=10_000_000,
        price_cap=10_000,
        common_infra={"trade_account": TradeAccount(position), "trade_exchange": exchange},
        level_infra={"trade_calendar": calendar},
    )
    strat.signal = signal

    decision = strat.generate_trade_decision()
    dirs = {(o.stock_id, o.direction.name) for o in decision.order_list}
    assert ("B", "SELL") in dirs
    assert ("A", "BUY") in dirs
