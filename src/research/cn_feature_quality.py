"""CN-specific feature-quality grid for fixed-10D research.

The US frozen blend did not transfer to CN in #90.  This module keeps the
existing rolling evidence and gate contracts, but provides a deliberately small
CN feature set for testing market-specific signal quality before any further
blend-weight work.
"""

from __future__ import annotations

from src.research.ranker_calibration_grid import RankerCalibration, RankerFeatureGroup, RankerGridCandidate


def cn_ranker_feature_groups() -> list[RankerFeatureGroup]:
    """Return compact CN-oriented feature groups.

    The groups intentionally use only common Qlib OHLCV fields.  They emphasize
    short-horizon reversal, volatility, price-volume pressure, and liquidity
    shocks because #90 showed the US momentum/blend structure is weak in CN.
    """

    dollar = chr(36)
    close = f"{dollar}close"
    high = f"{dollar}high"
    low = f"{dollar}low"
    volume = f"{dollar}volume"
    ret1 = f"{close}/Ref({close},1)-1"
    ret3 = f"{close}/Ref({close},3)-1"
    ret5 = f"{close}/Ref({close},5)-1"
    ret10 = f"{close}/Ref({close},10)-1"
    ret20 = f"{close}/Ref({close},20)-1"
    reversal = (
        f"Ref({close},1)/{close}-1",
        f"Ref({close},3)/{close}-1",
        f"Ref({close},5)/{close}-1",
    )
    mean_reversion = (
        f"{close}/Mean({close},5)-1",
        f"{close}/Mean({close},10)-1",
        f"{close}/Mean({close},20)-1",
    )
    volatility = (
        f"Std({ret1},5)",
        f"Std({ret1},10)",
        f"Std({ret1},20)",
        f"({high}-{low})/({close}+1e-12)",
    )
    liquidity = (
        f"{volume}/Mean({volume},5)-1",
        f"{volume}/Mean({volume},10)-1",
        f"{volume}/Mean({volume},20)-1",
    )
    pressure = (
        f"{ret1}*({volume}/Mean({volume},5)-1)",
        f"{ret5}*({volume}/Mean({volume},10)-1)",
        f"({high}/{low}-1)",
    )
    momentum = (ret3, ret5, ret10, ret20)
    risk_adjusted = (
        f"{ret5}/(Std({ret1},5)+1e-12)",
        f"{ret10}/(Std({ret1},10)+1e-12)",
        f"{ret20}/(Std({ret1},20)+1e-12)",
    )
    return [
        RankerFeatureGroup("cn_short_reversal_liquidity", reversal + mean_reversion + liquidity),
        RankerFeatureGroup("cn_volatility_reversal", reversal + volatility + risk_adjusted),
        RankerFeatureGroup("cn_price_volume_pressure", momentum + liquidity + pressure),
        RankerFeatureGroup("cn_balanced_ohlcv", momentum + reversal + volatility + liquidity),
    ]


def cn_ranker_calibrations() -> list[RankerCalibration]:
    """Return a small CN calibration grid.

    Keep this deliberately narrow: the next PR should test feature/factor
    quality, not open another broad parameter search.
    """

    return [
        RankerCalibration(n_gain_bins=3, num_boost_round=100, num_leaves=15, min_data_in_leaf=10),
        RankerCalibration(n_gain_bins=5, num_boost_round=100, num_leaves=31, min_data_in_leaf=20),
    ]


def build_cn_feature_quality_grid(
    feature_groups: list[RankerFeatureGroup] | None = None,
    calibrations: list[RankerCalibration] | None = None,
) -> list[RankerGridCandidate]:
    groups = feature_groups if feature_groups is not None else cn_ranker_feature_groups()
    settings = calibrations if calibrations is not None else cn_ranker_calibrations()
    return [RankerGridCandidate(group, calibration) for group in groups for calibration in settings]


def cn_factor_baseline_expressions() -> dict[str, str]:
    """Return simple CN factor baselines for direction diagnostics."""

    dollar = chr(36)
    close = f"{dollar}close"
    volume = f"{dollar}volume"
    ret1 = f"{close}/Ref({close},1)-1"
    return {
        "factor:cn_momentum_10d": f"{close}/Ref({close},10)-1",
        "factor:cn_reversal_5d": f"Ref({close},5)/{close}-1",
        "factor:cn_volatility_10d": f"Std({ret1},10)",
        "factor:cn_volume_shock_10d": f"{volume}/Mean({volume},10)-1",
    }


def cn_feature_grid_manifest(candidates: list[RankerGridCandidate]) -> dict[str, object]:
    names = [candidate.name for candidate in candidates]
    if len(names) != len(set(names)):
        raise ValueError("CN feature-quality candidate names must be unique")
    return {
        "schema_version": "1.0",
        "n_candidates": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
        "factor_baselines": cn_factor_baseline_expressions(),
    }
