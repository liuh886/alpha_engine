"""Parse natural language research goals into structured tasks.

Uses deterministic keyword matching (no LLM dependency) to extract
market, factor categories, direction, and quality thresholds from a
free-text research goal string.

Examples
--------
>>> parse_research_goal("帮我找A股低波策略")
ResearchGoal(market='cn', categories=['volatility'], direction='long', ...)
>>> parse_research_goal("Find US momentum factors with high IC")
ResearchGoal(market='us', categories=['momentum'], direction='long', ...)
>>> parse_research_goal("扫描所有市场的价值因子")
ResearchGoal(market='all', categories=['mean_reversion'], direction='long', ...)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Keyword maps — each entry maps a set of keywords to a canonical value.
# ---------------------------------------------------------------------------

_MARKET_KEYWORDS: dict[str, list[str]] = {
    "cn": ["a股", "cn", "中国", "china", "a-shares", "沪深"],
    "us": ["美股", "us", "美国", "america", "s&p", "sp500", "spx"],
    "all": ["所有市场", "all", "全部", "global", "every"],
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "momentum": ["动量", "momentum", "趋势", "trend"],
    "volatility": ["低波", "低波动", "volatility", "波动率", "low vol"],
    "mean_reversion": ["价值", "均值回归", "mean_reversion", "value", "估值"],
    "volume": ["量价", "成交量", "volume", "换手", "turnover"],
    "technical": ["技术", "technical", "k线", "形态"],
}

_DIRECTION_KEYWORDS: dict[str, list[str]] = {
    "long": ["做多", "long", "多头", "买入", "看多"],
    "short": ["做空", "short", "空头", "卖空", "看空"],
}

# Threshold hints — keywords that tweak numeric targets.
_QUALITY_KEYWORDS: list[tuple[str, str, float]] = [
    # (keyword, constraint_key, value)
    ("高ic", "min_icir", 1.0),
    ("high ic", "min_icir", 1.0),
    ("高icir", "min_icir", 1.0),
    ("稳健", "target_sharpe", 0.8),
    ("robust", "target_sharpe", 0.8),
    ("激进", "target_sharpe", 0.5),
    ("aggressive", "target_sharpe", 0.5),
    ("保守", "target_sharpe", 1.0),
    ("conservative", "target_sharpe", 1.0),
]


# ---------------------------------------------------------------------------
# ResearchGoal dataclass
# ---------------------------------------------------------------------------


@dataclass
class ResearchGoal:
    """Structured representation of a research objective."""

    market: str = "us"  # "us", "cn", "all"
    categories: list[str] = field(default_factory=list)  # e.g. ["momentum", "volatility"]
    direction: str = "long"  # "long", "short", "neutral"
    target_sharpe: float = 0.8  # minimum acceptable Sharpe ratio
    max_iterations: int = 3  # max research cycles to run
    description: str = ""  # original natural language description
    constraints: dict = field(default_factory=dict)  # additional constraints (min_icir, max_factors, etc.)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "categories": self.categories,
            "direction": self.direction,
            "target_sharpe": self.target_sharpe,
            "max_iterations": self.max_iterations,
            "description": self.description,
            "constraints": self.constraints,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _match_keywords(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    """Return all canonical values whose keywords appear in *text*."""
    hits: list[str] = []
    for canonical, keywords in keyword_map.items():
        for kw in keywords:
            if kw in text:
                hits.append(canonical)
                break  # one hit per canonical value is enough
    return hits


def _extract_int(text: str, pattern: str, default: int) -> int:
    """Try to extract an integer matching *pattern* from *text*."""
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            pass
    return default


def parse_research_goal(text: str) -> ResearchGoal:
    """Parse a natural language research goal into a structured :class:`ResearchGoal`.

    Parameters
    ----------
    text:
        Free-text description of the research objective.  Supports both
        Chinese and English keywords.

    Returns
    -------
    ResearchGoal
        Parsed goal with defaults filled in for any unspecified dimensions.
    """
    if not text or not text.strip():
        return ResearchGoal(description="")

    normalised = text.lower().strip()

    # --- Market ---
    market_hits = _match_keywords(normalised, _MARKET_KEYWORDS)
    if "all" in market_hits:
        market = "all"
    elif "cn" in market_hits:
        market = "cn"
    elif "us" in market_hits:
        market = "us"
    else:
        market = "us"  # default

    # --- Categories ---
    categories = _match_keywords(normalised, _CATEGORY_KEYWORDS)
    if not categories:
        categories = ["all"]  # scan everything by default

    # --- Direction ---
    direction_hits = _match_keywords(normalised, _DIRECTION_KEYWORDS)
    if "short" in direction_hits:
        direction = "short"
    elif "long" in direction_hits:
        direction = "long"
    else:
        direction = "long"  # default

    # --- Quality thresholds from keyword hints ---
    target_sharpe = 0.8
    constraints: dict = {}

    for keyword, key, value in _QUALITY_KEYWORDS:
        if keyword in normalised:
            if key == "target_sharpe":
                target_sharpe = value
            else:
                constraints[key] = value

    # --- Max iterations (look for patterns like "最多5轮", "5 iterations", "max 3") ---
    max_iterations = _extract_int(normalised, r"(?:最多|最大|max(?:imum)?)\s*(\d+)", 0)
    if max_iterations <= 0:
        max_iterations = _extract_int(normalised, r"(\d+)\s*(?:轮|次|iterations?|cycles?)", 0)
    if max_iterations <= 0:
        max_iterations = 3  # default

    return ResearchGoal(
        market=market,
        categories=categories,
        direction=direction,
        target_sharpe=target_sharpe,
        max_iterations=max_iterations,
        description=text.strip(),
        constraints=constraints,
    )
