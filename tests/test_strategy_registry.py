"""Tests for the strategy plugin registry."""
from __future__ import annotations

import pytest

from src.strategies.registry import StrategyRegistry, _schema_from_constructor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure a fresh singleton for every test."""
    StrategyRegistry.reset()
    yield
    StrategyRegistry.reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubPlugin:
    """Minimal StrategyPlugin implementation for unit tests."""

    def __init__(self, name: str = "stub", version: str = "0.1.0"):
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return "A stub strategy for testing"

    @property
    def strategy_class(self) -> type:
        return type("StubStrategy", (), {})

    @property
    def default_params(self) -> dict:
        return {"topk": 5}

    @property
    def param_schema(self) -> dict:
        return {"type": "object", "properties": {"topk": {"type": "integer"}}, "required": ["topk"]}

    def create_instance(self, **params):
        return {"type": "stub_instance", "params": params}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_instance_returns_same_object(self):
        a = StrategyRegistry.get_instance()
        b = StrategyRegistry.get_instance()
        assert a is b

    def test_reset_creates_new_instance(self):
        a = StrategyRegistry.get_instance()
        StrategyRegistry.reset()
        b = StrategyRegistry.get_instance()
        assert a is not b


class TestRegister:
    def test_register_and_get(self):
        reg = StrategyRegistry.get_instance()
        plugin = _StubPlugin()
        reg.register(plugin)
        assert reg.get("stub") is plugin

    def test_get_unknown_returns_none(self):
        reg = StrategyRegistry.get_instance()
        assert reg.get("nonexistent") is None

    def test_overwrite_logs_warning(self):
        reg = StrategyRegistry.get_instance()
        reg.register(_StubPlugin(version="1.0"))
        reg.register(_StubPlugin(version="2.0"))
        assert reg.get("stub").version == "2.0"


class TestListStrategies:
    def test_returns_plugin_info_list(self):
        reg = StrategyRegistry.get_instance()
        reg.register(_StubPlugin("a", "1.0"))
        reg.register(_StubPlugin("b", "2.0"))
        infos = reg.list_strategies()
        assert len(infos) == 2
        names = {p.name for p in infos}
        assert names == {"a", "b"}

    def test_plugin_info_to_dict(self):
        reg = StrategyRegistry.get_instance()
        reg.register(_StubPlugin())
        info = reg.list_strategies()[0]
        d = info.to_dict()
        assert d["name"] == "stub"
        assert d["version"] == "0.1.0"
        assert "description" in d
        assert "strategy_class" in d
        assert "default_params" in d
        assert "param_schema" in d


class TestCreate:
    def test_create_instance(self):
        reg = StrategyRegistry.get_instance()
        reg.register(_StubPlugin())
        inst = reg.create("stub", topk=10)
        assert inst["type"] == "stub_instance"
        assert inst["params"]["topk"] == 10

    def test_create_unknown_raises(self):
        reg = StrategyRegistry.get_instance()
        with pytest.raises(KeyError, match="not found"):
            reg.create("nonexistent")


class TestAutoDiscover:
    def test_auto_discover_finds_builtins(self):
        reg = StrategyRegistry.get_instance()
        reg.auto_discover()
        names = {p.name for p in reg.list_strategies()}
        assert "biweekly_trend" in names
        assert "weekly_quant_rating" in names

    def test_builtin_plugin_metadata(self):
        reg = StrategyRegistry.get_instance()
        reg.auto_discover()
        bt = reg.get("biweekly_trend")
        assert bt is not None
        assert bt.version == "1.0.0"
        assert "trend" in bt.description.lower()

        wqr = reg.get("weekly_quant_rating")
        assert wqr is not None
        assert wqr.version == "1.0.0"

    def test_builtin_plugin_schema_not_empty(self):
        reg = StrategyRegistry.get_instance()
        reg.auto_discover()
        for name in ("biweekly_trend", "weekly_quant_rating"):
            plugin = reg.get(name)
            schema = plugin.param_schema
            assert "properties" in schema
            assert len(schema["properties"]) > 0, f"{name} schema should have properties"


class TestParamValidation:
    def test_schema_from_constructor(self):
        """Schema should include constructor params with correct types."""
        from src.strategies.biweekly_trend_strategy import BiweeklyTrendStrategy

        schema = _schema_from_constructor(BiweeklyTrendStrategy, exclude={"n_drop"})
        props = schema["properties"]

        assert "topk" in props
        assert props["topk"]["type"] == "integer"
        assert props["topk"]["default"] == 5

        assert "sell_ma_window" in props
        assert props["sell_ma_window"]["type"] == "integer"

        assert "buy_score_threshold" in props
        # Optional[float] should resolve to number
        assert props["buy_score_threshold"]["type"] == "number"

        assert "use_risk_manager" in props
        assert props["use_risk_manager"]["type"] == "boolean"

    def test_schema_excludes_self_and_kwargs(self):
        from src.strategies.biweekly_trend_strategy import BiweeklyTrendStrategy

        schema = _schema_from_constructor(BiweeklyTrendStrategy)
        props = schema["properties"]
        assert "self" not in props
        assert "kwargs" not in props

    def test_weekly_quant_rating_schema(self):
        from src.strategies.weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

        schema = _schema_from_constructor(WeeklyQuantRatingStrategy)
        props = schema["properties"]

        assert "universe_size" in props
        assert props["universe_size"]["type"] == "integer"

        assert "strongbuy_fraction" in props
        assert props["strongbuy_fraction"]["type"] == "number"

        assert "min_dollar_vol_20d" in props


class TestBackwardCompatibility:
    """Existing strategy classes must still be directly importable and instantiable."""

    def test_import_biweekly_trend(self):
        from src.strategies.biweekly_trend_strategy import BiweeklyTrendStrategy

        assert BiweeklyTrendStrategy is not None
        assert hasattr(BiweeklyTrendStrategy, "generate_trade_decision")

    def test_import_weekly_quant_rating(self):
        from src.strategies.weekly_quant_rating_strategy import WeeklyQuantRatingStrategy

        assert WeeklyQuantRatingStrategy is not None
        assert hasattr(WeeklyQuantRatingStrategy, "generate_trade_decision")

    def test_import_rules(self):
        from src.strategies.biweekly_trend_rules import can_sell, is_rebalance_day
        from src.strategies.weekly_quant_rating_rules import (
            is_last_trading_day_of_week,
            select_target,
            select_top_fraction,
            update_streaks,
        )

        assert callable(is_rebalance_day)
        assert callable(can_sell)
        assert callable(select_top_fraction)
        assert callable(update_streaks)
        assert callable(is_last_trading_day_of_week)
        assert callable(select_target)
