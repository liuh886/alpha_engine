"""
Natural Language → StrategySpec → Qlib Workflow compiler.

Parses a natural language strategy description into a strategy_profile.json,
then compiles it into a Qlib workflow YAML via profile_compiler.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.common.logging import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def _extract_rebalance_frequency(text: str) -> str:
    """Extract rebalance frequency from NL text."""
    t = text.lower()
    # Check biweekly FIRST (before weekly, since "biweekly" contains "weekly")
    if any(w in t for w in ["biweekly", "bi-weekly", "every two weeks", "两周", "双周"]):
        return "biweekly"
    if any(w in t for w in ["weekly", "every week", "1w", "一周"]):
        return "weekly"
    if any(w in t for w in ["monthly", "every month", "1m", "一月", "月度"]):
        return "monthly"
    # Default
    return "biweekly"


def _extract_topk(text: str) -> int:
    """Extract top-K portfolio size from NL text."""
    t = text.lower()
    # "top 5", "top-5", "top5", "持有5只", "hold 5"
    m = re.search(r"(?:top|hold|持有|选|pick)\s*-?\s*(\d+)", t)
    if m:
        return int(m.group(1))
    # "5 stocks", "5 positions", "5只"
    m = re.search(r"(\d+)\s*(?:stocks?|positions?|只|个)", t)
    if m:
        return int(m.group(1))
    return 5


def _extract_sell_ma(text: str) -> int | None:
    """Extract sell moving average window from NL text."""
    t = text.lower()
    # "sell below ma20", "sell when price < ma(60)", "跌破20日均线卖出"
    m = re.search(r"(?:ma|均线|moving\s*average)\s*[\(]?\s*(\d+)", t)
    if m:
        return int(m.group(1))
    # "20-day ma", "20日均线"
    m = re.search(r"(\d+)\s*(?:-\s*day|日)\s*(?:ma|均线|moving)", t)
    if m:
        return int(m.group(1))
    return None


def _extract_min_hold_days(text: str) -> int | None:
    """Extract minimum holding days from NL text."""
    t = text.lower()
    m = re.search(r"(?:hold|持有|min)\s*(?:at\s*least\s*)?(\d+)\s*(?:days?|天|trading)", t)
    if m:
        return int(m.group(1))
    return None


def _extract_sell_rank_threshold(text: str) -> int | None:
    """Extract sell rank threshold from NL text."""
    t = text.lower()
    m = re.search(r"(?:sell|卖出).*?(?:rank|排名).*?(\d+)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(?:rank|排名).*?(\d+).*?(?:sell|卖出)", t)
    if m:
        return int(m.group(1))
    return None


def _extract_buy_rule(text: str) -> str | None:
    """Extract buy rule from NL text."""
    t = text.lower()
    if any(w in t for w in ["positive score", "score > 0", "正分", "得分大于0"]):
        return "score > 0"
    if any(w in t for w in ["top ranked", "highest score", "最高分"]):
        return "score > 0"
    # Look for explicit threshold
    m = re.search(r"(?:score|得分)\s*>\s*(-?\d+\.?\d*)", t)
    if m:
        return f"score > {m.group(1)}"
    return None


def _extract_sell_rule(text: str) -> str | None:
    """Extract sell rule from NL text."""
    t = text.lower()
    if any(w in t for w in ["negative score", "score < 0", "负分", "得分小于0"]):
        return "score < 0"
    m = re.search(r"(?:score|得分)\s*<\s*(-?\d+\.?\d*)", t)
    if m:
        return f"score < {m.group(1)}"
    return None


def _extract_capital(text: str) -> int | None:
    """Extract starting capital from NL text."""
    t = text.lower()
    # Handle Chinese units: 万=10000, 亿=100000000
    m = re.search(r"(?:capital|资金|本金|start\s*with)\s*[\$￥]?\s*(\d[\d,]*)\s*万", t)
    if m:
        return int(m.group(1).replace(",", "")) * 10000
    m = re.search(r"(?:capital|资金|本金|start\s*with)\s*[\$￥]?\s*(\d[\d,]*)\s*亿", t)
    if m:
        return int(m.group(1).replace(",", "")) * 100000000
    # Standard number
    m = re.search(r"(?:capital|资金|本金|start\s*with)\s*[\$￥]?\s*(\d[\d,]*)", t)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _extract_market(text: str) -> str:
    """Extract market from NL text."""
    t = text.lower()
    if any(w in t for w in ["us", "美股", "nasdaq", "s&p", "qqq", "american"]):
        return "us"
    if any(w in t for w in ["cn", "china", "中国", "a股", "沪深", "csi"]):
        return "cn"
    return "us"


def parse_natural_language(text: str) -> dict[str, Any]:
    """
    Parse natural language strategy description into a strategy_profile.json dict.
    """
    market = _extract_market(text)
    rebalance = _extract_rebalance_frequency(text)
    topk = _extract_topk(text)
    sell_ma = _extract_sell_ma(text)
    min_hold = _extract_min_hold_days(text)
    sell_rank = _extract_sell_rank_threshold(text)
    buy_rule = _extract_buy_rule(text)
    sell_rule = _extract_sell_rule(text)
    capital = _extract_capital(text)

    benchmark = "QQQ" if market == "us" else "000300"

    profile: dict[str, Any] = {
        "meta": {
            "name": "NL_Generated",
            "description": f"Auto-generated from: {text[:100]}",
            "market": market,
            "benchmark": benchmark,
            "benchmark_by_market": {"cn": "000300", "us": "QQQ"},
        },
        "universe": {
            "type": "watchlist",
            "filters": {"min_liquidity": 1000000},
            "custom_list": [],
        },
        "model": {
            "class": "LGBModel",
            "feature_pack": "alpha158",
            "features": ["alpha158"],
            "extra_features": [
                "$close/Ref($close, 5)-1",
                "$close/Ref($close, 10)-1",
                "$close/Ref($close, 20)-1",
                "Std($close, 10)",
                "$volume/Ref($volume, 10)-1",
            ],
            "label": ["Ref($close, -10) / Ref($close, -1) - 1"],
            "train_window": {
                "train": ["2021-01-01", "2024-12-31"],
                "valid": ["2025-01-01", "2025-12-31"],
                # Test window uses dynamic end — override per run
                "test": ["2026-01-01", "USE_default_end_date"],
            },
            "kwargs": {
                "learning_rate": 0.05,
                "lambda_l1": 1.0,
                "lambda_l2": 1.0,
                "max_depth": 10,
                "num_leaves": 128,
            },
        },
        "strategy": {
            "rebalance_frequency": rebalance,
            "min_hold_days": min_hold or 10,
            "sell_on_ma": sell_ma or 60,
            "sell_rank_threshold": sell_rank or 20,
            "position_rule": {"topk": topk, "n_drop": topk},
            "capital": capital or 10000,
            "costs_bps": 10,
            "backtest_window": ["2026-01-01", "2026-06-18"],
        },
    }

    if buy_rule:
        profile["strategy"]["buy_rule"] = buy_rule
    if sell_rule:
        profile["strategy"]["sell_rule"] = sell_rule

    return profile


class StrategyCompilerService:
    def __init__(self, project_root: str | Path):
        self._project_root = Path(project_root)

    def compile_from_nl(self, text: str, market: str | None = None) -> dict[str, Any]:
        """
        Parse NL text → generate StrategySpec.json → compile to Qlib YAML.
        Returns the compiled profile dict and the path to the YAML.
        """
        profile = parse_natural_language(text)
        if market:
            profile["meta"]["market"] = market.lower()
            profile["meta"]["benchmark"] = "QQQ" if market.lower() == "us" else "000300"

        # Save profile
        profile_path = self._project_root / "configs" / "strategy_profile_generated.json"
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)

        # Compile to YAML
        from src.workflows.profile_compiler import compile_strategy_profile

        yaml_path = compile_strategy_profile(
            market=profile["meta"]["market"],
            profile_path="configs/strategy_profile_generated.json",
            dry_run=False,
        )

        return {
            "profile": profile,
            "profile_path": str(profile_path),
            "yaml_path": str(yaml_path),
            "market": profile["meta"]["market"],
            "summary": {
                "rebalance": profile["strategy"]["rebalance_frequency"],
                "topk": profile["strategy"]["position_rule"]["topk"],
                "sell_ma": profile["strategy"]["sell_on_ma"],
                "min_hold_days": profile["strategy"]["min_hold_days"],
                "buy_rule": profile["strategy"].get("buy_rule", "default"),
                "sell_rule": profile["strategy"].get("sell_rule", "default"),
            },
        }
