import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_collect_profile_warnings_flags_unimplemented_fields():
    from src.workflows.profile_compiler import collect_profile_warnings

    profile = {
        "meta": {"benchmark_by_market": {"us": "QQQ"}},
        "universe": {
            "type": "watchlist",
            "filters": {"min_liquidity": 1_000_000},
            "custom_list": [],
        },
        "strategy": {"buy_rule": "score > 0", "sell_rule": "score < 0"},
        "model": {},
    }
    warnings = collect_profile_warnings(profile, market="us")
    joined = "\n".join(warnings).lower()
    assert "min_liquidity" in joined
    # buy_rule and sell_rule are now parsed and wired into strategy kwargs
    # via _parse_score_threshold(), so they no longer generate warnings
