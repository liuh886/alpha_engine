import json
from pathlib import Path

import yaml

from src.common.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def load_profile(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_region_for_market(market: str) -> str:
    market = (market or "").lower()
    if market in {"cn", "hk"}:
        return "cn"
    return "us"


def ensure_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def collect_profile_warnings(profile: dict, market: str) -> list[str]:
    warnings: list[str] = []
    meta = profile.get("meta", {}) if isinstance(profile, dict) else {}
    model = profile.get("model", {}) if isinstance(profile, dict) else {}
    strategy = profile.get("strategy", {}) if isinstance(profile, dict) else {}
    universe_val = profile.get("universe", {})
    universe = universe_val if isinstance(universe_val, dict) else {}

    if meta.get("market") and str(meta.get("market")).lower() != str(market).lower():
        warnings.append(
            "meta.market differs from --market; compilation uses --market (meta.market is informational)."
        )

    filters = universe.get("filters", {}) if isinstance(universe, dict) else {}
    if isinstance(filters, dict) and filters.get("min_liquidity") is not None:
        warnings.append(
            "universe.filters.min_liquidity is not enforced by the compiler; it is intended for runtime universe filtering."
        )

    if strategy.get("buy_rule") is not None:
        warnings.append("strategy.buy_rule is currently not used by compiler/strategies (ignored).")
    if strategy.get("sell_rule") is not None:
        warnings.append(
            "strategy.sell_rule is currently not used by compiler/strategies (ignored)."
        )

    feature_pack = (model.get("feature_pack") or "").lower()
    if feature_pack == "alpha158" and model.get("features"):
        warnings.append(
            "model.features is ignored when model.feature_pack=alpha158; use model.extra_features instead."
        )

    return warnings


def rebalance_steps_from_frequency(freq):
    if freq is None:
        return None
    if isinstance(freq, int):
        return freq
    if isinstance(freq, str):
        key = freq.strip().lower()
        if key.isdigit():
            return int(key)
        if key in {"biweekly", "bi-weekly", "2w", "2-week"}:
            return 10
        if key in {"weekly", "1w", "week"}:
            return 5
        if key in {"monthly", "1m", "month"}:
            return 21
    return None


def apply_profile_to_config(profile: dict, cfg: dict, market: str) -> dict:
    meta = profile.get("meta", {})
    model = profile.get("model", {})
    strategy = profile.get("strategy", {})
    train_window = model.get("train_window", {})

    cfg.setdefault("qlib_init", {})
    cfg["qlib_init"]["region"] = get_region_for_market(market)
    cfg["market"] = market
    benchmark_by_market = meta.get("benchmark_by_market", {})
    if isinstance(benchmark_by_market, dict) and benchmark_by_market.get(market):
        cfg["benchmark"] = benchmark_by_market.get(market)
    elif meta.get("benchmark"):
        cfg["benchmark"] = meta.get("benchmark")
    elif market == "cn":
        cfg["benchmark"] = "000300"
    else:
        cfg["benchmark"] = "QQQ"

    # Model
    cfg.setdefault("task", {}).setdefault("model", {})
    if model.get("class"):
        cfg["task"]["model"]["class"] = model.get("class")
    if model.get("kwargs"):
        cfg["task"]["model"].setdefault("kwargs", {}).update(model.get("kwargs", {}))

    # Dataset handler
    dataset = cfg.setdefault("task", {}).setdefault("dataset", {})
    kwargs = dataset.setdefault("kwargs", {})
    handler = kwargs.setdefault("handler", {})
    handler_kwargs = handler.setdefault("kwargs", {})

    train = train_window.get("train", [])
    valid = train_window.get("valid", [])
    test = train_window.get("test", [])
    if train or valid or test:
        if train and test:
            handler_kwargs["start_time"] = train[0]
            handler_kwargs["end_time"] = test[-1]
        kwargs["segments"] = {
            "train": ensure_list(train),
            "valid": ensure_list(valid),
            "test": ensure_list(test),
        }

    feature_pack = (model.get("feature_pack") or "").lower()
    if feature_pack == "alpha158":
        from qlib.contrib.data.loader import Alpha158DL

        handler["class"] = "DataHandlerLP"
        handler["module_path"] = "qlib.data.dataset.handler"
        handler_kwargs.pop("extra_features", None)
        handler_kwargs.pop("label", None)
        data_loader = handler_kwargs.setdefault("data_loader", {})
        data_loader["class"] = "QlibDataLoader"
        dl_kwargs = data_loader.setdefault("kwargs", {})
        dl_cfg = dl_kwargs.setdefault("config", {})
        alpha_features = Alpha158DL.get_feature_config(
            {
                "kbar": {},
                "price": {"windows": [0], "feature": ["OPEN", "HIGH", "LOW", "VWAP"]},
                "rolling": {},
            }
        )[0]
        extra_features = ensure_list(model.get("extra_features"))
        dl_cfg["feature"] = list(alpha_features) + extra_features
        if model.get("label"):
            dl_cfg["label"] = ensure_list(model.get("label"))
    else:
        data_loader = handler_kwargs.setdefault("data_loader", {})
        dl_kwargs = data_loader.setdefault("kwargs", {})
        dl_cfg = dl_kwargs.setdefault("config", {})
        if model.get("features"):
            dl_cfg["feature"] = ensure_list(model.get("features"))
        if model.get("label"):
            dl_cfg["label"] = ensure_list(model.get("label"))

    # Strategy/backtest
    port = cfg.setdefault("port_analysis_config", {}).setdefault("backtest", {})
    window = strategy.get("backtest_window", [])
    if window:
        port["start_time"] = window[0]
        port["end_time"] = window[-1]

    if strategy.get("capital") is not None:
        port["account"] = strategy.get("capital")

    costs_bps = strategy.get("costs_bps")
    if costs_bps is not None:
        cost = float(costs_bps) / 10000.0
        port.setdefault("exchange_kwargs", {})
        port["exchange_kwargs"]["open_cost"] = cost
        port["exchange_kwargs"]["close_cost"] = cost
        port["exchange_kwargs"]["min_cost"] = 0

    pos_rule = strategy.get("position_rule", {})
    strat = cfg.setdefault("port_analysis_config", {}).setdefault("strategy", {})
    strat_kwargs = strat.setdefault("kwargs", {})
    if pos_rule.get("topk") is not None:
        strat_kwargs["topk"] = pos_rule.get("topk")
    if pos_rule.get("n_drop") is not None:
        strat_kwargs["n_drop"] = pos_rule.get("n_drop")

    strategy_mode = (strategy.get("strategy_mode") or "").strip().lower()
    if strategy_mode in {"weekly_quant_rating", "quant_rating_weekly"}:
        strat["class"] = "WeeklyQuantRatingStrategy"
        strat["module_path"] = "src.strategies.weekly_quant_rating_strategy"
        strat_kwargs.pop("topk", None)
        strat_kwargs.pop("n_drop", None)
        strat_kwargs.pop("rebalance_steps", None)
        strat_kwargs.pop("min_hold_days", None)
        strat_kwargs.pop("sell_ma_window", None)
        strat_kwargs.pop("sell_rank_threshold", None)
        if strategy.get("universe_size") is not None:
            strat_kwargs["universe_size"] = int(strategy.get("universe_size"))
        if strategy.get("strongbuy_consecutive_days") is not None:
            strat_kwargs["strongbuy_consecutive_days"] = int(
                strategy.get("strongbuy_consecutive_days")
            )
        if strategy.get("strongbuy_fraction") is not None:
            strat_kwargs["strongbuy_fraction"] = float(strategy.get("strongbuy_fraction"))
        if strategy.get("lookback_days") is not None:
            strat_kwargs["lookback_days"] = int(strategy.get("lookback_days"))
        if strategy.get("min_dollar_vol_20d") is not None:
            strat_kwargs["min_dollar_vol_20d"] = float(strategy.get("min_dollar_vol_20d"))
        if strategy.get("price_cap") is not None:
            strat_kwargs["price_cap"] = float(strategy.get("price_cap"))
        return cfg

    rebalance_steps = rebalance_steps_from_frequency(strategy.get("rebalance_frequency"))
    min_hold_days = strategy.get("min_hold_days")
    sell_on_ma = strategy.get("sell_on_ma")
    sell_rank_threshold = strategy.get("sell_rank_threshold")
    if any(
        x is not None for x in [rebalance_steps, min_hold_days, sell_on_ma, sell_rank_threshold]
    ):
        strat["class"] = "BiweeklyTrendStrategy"
        strat["module_path"] = "src.strategies.biweekly_trend_strategy"
        strat_kwargs.pop("n_drop", None)
        for key in [
            "universe_size",
            "strongbuy_consecutive_days",
            "strongbuy_fraction",
            "lookback_days",
            "min_dollar_vol_20d",
            "price_cap",
        ]:
            strat_kwargs.pop(key, None)
        if rebalance_steps is not None:
            strat_kwargs["rebalance_steps"] = rebalance_steps
        if min_hold_days is not None:
            strat_kwargs["min_hold_days"] = min_hold_days
        if sell_on_ma is not None:
            strat_kwargs["sell_ma_window"] = sell_on_ma
        if sell_rank_threshold is not None:
            strat_kwargs["sell_rank_threshold"] = sell_rank_threshold

    return cfg


def maybe_update_watchlist(profile: dict, market: str):
    universe = profile.get("universe", {})
    if universe.get("type") != "custom_list":
        return
    custom_list = universe.get("custom_list", [])
    if not custom_list:
        return

    watchlist_path = ROOT / "configs" / "watchlist.yaml"
    if not watchlist_path.exists():
        return
    with open(watchlist_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault(market, [])
    data[market] = list(custom_list)
    with open(watchlist_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=False)


def compile_strategy_profile(
    *,
    market: str | None = None,
    profile_path: str = "configs/strategy_profile.json",
    dry_run: bool = False,
) -> Path:
    """
    核心编译逻辑：将策略 Profile JSON 编译为 Qlib 工作流 YAML。
    """
    p_path = ROOT / profile_path
    profile = load_profile(p_path)
    if not profile:
        raise ValueError(f"Profile not found at {p_path}")

    target_market = market or profile.get("meta", {}).get("market", "")
    if not target_market:
        raise ValueError("Market must be specified via argument or profile meta.")
    target_market = target_market.lower()

    # 收集并打印警告 (可以考虑集成到 ReliabilityEvent)
    for w in collect_profile_warnings(profile, market=target_market):
        logger.warning("Profile warning", message=w)

    model_class = (profile.get("model", {}).get("class") or "").lower()
    if "linear" in model_class:
        config_path = ROOT / "configs" / f"{target_market}_workflow.yaml"
    else:
        config_path = ROOT / "configs" / f"{target_market}_lgbm_workflow.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config template missing: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    cfg = apply_profile_to_config(profile, cfg, target_market)

    if dry_run:
        logger.info("Dry-run config output", config=yaml.safe_dump(cfg, sort_keys=False, allow_unicode=False))
        return config_path

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=False)

    maybe_update_watchlist(profile, target_market)
    logger.info("Successfully compiled profile", config_path=str(config_path))
    return config_path
