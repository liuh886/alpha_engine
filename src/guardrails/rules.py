import numpy as np
import pandas as pd


def check_extension(price: float, ma20: float, threshold: float = 0.20) -> dict:
    """
    Block if |price - ma20| / ma20 > threshold
    """
    if ma20 == 0 or np.isnan(ma20):
        return {"passed": False, "reason": "No MA20 data"}

    deviation = abs(price - ma20) / ma20
    passed = deviation <= threshold
    return {
        "passed": passed,
        "reason": f"Extension {deviation:.2%} > {threshold:.0%}" if not passed else "OK",
        "metric": deviation,
    }


def check_volatility_regime(vol20: float, vol252: float, threshold: float = 2.0) -> dict:
    """
    Degrade/Block if ShortTerm Vol >> LongTerm Vol (Regime Shift)
    """
    if vol252 == 0 or np.isnan(vol252):
        return {"passed": True, "reason": "No Vol252 data"}  # Lenient fallback

    ratio = vol20 / vol252
    passed = ratio <= threshold
    return {
        "passed": passed,
        "reason": f"Vol Ratio {ratio:.2f} > {threshold}" if not passed else "OK",
        "metric": ratio,
    }


def check_liquidity(avg_amount: float, threshold: float = 1_000_000) -> dict:
    """
    Block if daily turnover < threshold (CNY/USD)
    """
    passed = avg_amount >= threshold
    return {
        "passed": passed,
        "reason": f"Liquidity {avg_amount:,.0f} < {threshold:,.0f}" if not passed else "OK",
        "metric": avg_amount,
    }


DEFAULT_CONFIG = {"extension_threshold": 0.20, "vol_threshold": 2.0, "min_liquidity": 1_000_000}


def apply_guardrails(row: pd.Series, config: dict = None) -> dict:
    """
    Apply all rules to a single row of data.
    Expected row keys: close, ma20, vol20, vol252, amount
    """
    if config is None:
        config = DEFAULT_CONFIG
    results = {}

    # 1. Extension
    if "extension_threshold" in config:
        results["extension"] = check_extension(
            row["close"], row["ma20"], config.get("extension_threshold", 0.20)
        )

    # 2. Volatility
    if "vol_threshold" in config:
        results["volatility"] = check_volatility_regime(
            row["vol20"], row["vol252"], config.get("vol_threshold", 2.0)
        )

    # 3. Liquidity
    if "min_liquidity" in config:
        results["liquidity"] = check_liquidity(row["amount"], config.get("min_liquidity", 1000000))

    # Aggregate
    all_passed = all(r["passed"] for r in results.values())
    return {"passed": all_passed, "details": results}
