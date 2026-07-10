"""Structured Factor Library.

Provides two complementary factor systems:

1. **Structured Factor Specs** — ``FactorSpec``, ``FactorGroup`` loaded
   from ``configs/factor_libraries/*.yaml`` with schema validation, globally
   unique ids, group selection that fails closed, and conversion to the
   existing ``RankerFeatureGroup`` type.  No Qlib dependency.

2. **Combinatorial Factor Library** (legacy) — loads factor expressions from
   ``configs/factor_pool.yaml`` by default, falling back to programmatic
   generation.  Suitable for ``scan_factor_pool`` in factor_scanner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from yaml import SafeLoader, MappingNode

if TYPE_CHECKING:
    from src.research.ranker_calibration_grid import RankerFeatureGroup

# ═══════════════════════════════════════════════════════════════════════════════
# Structured Factor Specs — no Qlib dependency
# ═══════════════════════════════════════════════════════════════════════════════

STRUCTURED_FACTOR_LIBRARY_SCHEMA = "1.0"


@dataclass(frozen=True)
class FactorSpec:
    """One factor definition with globally unique id."""

    id: str
    expression: str
    family: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("FactorSpec.id must be non-empty")
        if not self.expression:
            raise ValueError("FactorSpec.expression must be non-empty")
        if not self.family:
            raise ValueError("FactorSpec.family must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "expression": self.expression,
            "family": self.family,
            "description": self.description,
        }


@dataclass(frozen=True)
class FactorGroup:
    """Named collection of factor specs (factors nested within each group)."""

    name: str
    description: str
    factors: tuple[FactorSpec, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("FactorGroup.name must be non-empty")
        if not self.factors:
            raise ValueError(
                f"FactorGroup '{self.name}' must contain at least one factor"
            )

    @property
    def factor_ids(self) -> tuple[str, ...]:
        """Factor ids in this group, for backward compatibility."""
        return tuple(f.id for f in self.factors)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "factors": [f.to_dict() for f in self.factors],
        }


# ── Core public API ────────────────────────────────────────────────────────────


def _validate_factor_ids_unique(all_factors: list[FactorSpec]) -> None:
    """Raise ValueError if any factor id is duplicated across all groups."""
    seen: dict[str, str] = {}  # id → group_name
    for f in all_factors:
        if f.id in seen:
            raise ValueError(
                f"Duplicate factor id '{f.id}' (first seen in group '{seen[f.id]}')"
            )
        seen[f.id] = "detected"


def load_factor_library(path: str | Path) -> dict[str, FactorGroup]:
    """Load a structured factor library from a YAML file.

    The canonical schema (1.0) uses ``schema_version`` and a ``groups``
    mapping.  Each group has a ``description`` and a ``factors`` list
    where each factor has ``id``, ``expression``, ``family``, and
    optional ``description``.

    Parameters
    ----------
    path:
        Path to a YAML file following the ``configs/factor_libraries/`` schema.

    Returns
    -------
    dict[str, FactorGroup]
        Mapping from group name to ``FactorGroup``.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the schema version is unsupported, factor ids are duplicated
        globally, any expression is missing or empty, group names are
        duplicated, or a referenced factor id is unknown.
    """
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Factor library not found: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as fh:
        raw_text = fh.read()

    # First pass: detect duplicate group keys in the YAML node tree
    # before yaml.safe_load silently overwrites them.
    composed = yaml.compose(raw_text, Loader=SafeLoader)
    if isinstance(composed, MappingNode):
        for key_node, value_node in composed.value:
            if key_node.value == "groups" and isinstance(value_node, MappingNode):
                seen_group: set[str] = set()
                for gkey_node, _ in value_node.value:
                    if gkey_node.value in seen_group:
                        raise ValueError(
                            f"Duplicate group name '{gkey_node.value}' "
                            "in factor library YAML"
                        )
                    seen_group.add(gkey_node.value)

    # Second pass: actual data load
    data = yaml.safe_load(raw_text)

    if not isinstance(data, dict):
        raise ValueError("Factor library YAML must be a mapping")

    # ── Schema version ────────────────────────────────────────────────────
    sv = data.get("schema_version")
    if sv != STRUCTURED_FACTOR_LIBRARY_SCHEMA:
        raise ValueError(
            f"Unsupported factor library schema_version '{sv}' "
            f"(expected '{STRUCTURED_FACTOR_LIBRARY_SCHEMA}')"
        )

    # ── Groups mapping ────────────────────────────────────────────────────
    raw_groups: dict[str, Any] = data.get("groups", {})
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise ValueError("'groups' must be a non-empty mapping")

    seen_group_names: set[str] = set()
    library: dict[str, FactorGroup] = {}
    all_factor_ids: list[tuple[str, str]] = []  # (id, group_name) pairs

    for gname, gdata in raw_groups.items():
        gname_str = str(gname)
        if gname_str in seen_group_names:
            raise ValueError(f"Duplicate group name '{gname_str}'")
        seen_group_names.add(gname_str)

        if not isinstance(gdata, dict):
            raise ValueError(f"Group '{gname_str}' must be a mapping")

        description = str(gdata.get("description", ""))
        raw_factors: list[dict[str, Any]] = gdata.get("factors", [])
        if not isinstance(raw_factors, list) or not raw_factors:
            raise ValueError(
                f"Group '{gname_str}' must have a non-empty 'factors' list"
            )

        factors: list[FactorSpec] = []
        for item in raw_factors:
            fid = str(item.get("id", ""))
            expr = str(item.get("expression", ""))
            family = str(item.get("family", ""))
            desc = str(item.get("description", ""))

            if not fid:
                raise ValueError(
                    f"Factor in group '{gname_str}' has empty or missing 'id'"
                )
            if not expr:
                raise ValueError(
                    f"Factor '{fid}' in group '{gname_str}' has empty or missing 'expression'"
                )

            factors.append(FactorSpec(id=fid, expression=expr, family=family, description=desc))
            all_factor_ids.append((fid, gname_str))

        library[gname_str] = FactorGroup(
            name=gname_str,
            description=description,
            factors=tuple(factors),
        )

    # ── Validate global uniqueness ────────────────────────────────────────
    seen_ids: set[str] = set()
    for fid, gname in all_factor_ids:
        if fid in seen_ids:
            raise ValueError(
                f"Duplicate factor id '{fid}' across groups "
                f"(first occurrence in library)"
            )
        seen_ids.add(fid)

    return library


def select_factor_groups(
    library: dict[str, FactorGroup], group_names: list[str]
) -> list[FactorGroup]:
    """Select factor groups by name, failing closed if any is missing.

    Parameters
    ----------
    library:
        Mapping from group name to ``FactorGroup`` (from ``load_factor_library``).
    group_names:
        Ordered list of group names to select.

    Returns
    -------
    list[FactorGroup]
        The selected groups in the requested order.

    Raises
    ------
    ValueError
        If any *group_name* is not in *library*.
    """
    result: list[FactorGroup] = []
    available = sorted(library.keys())
    for name in group_names:
        if name not in library:
            raise ValueError(
                f"FactorGroup '{name}' not found. Available: {available}"
            )
        result.append(library[name])
    return result


def factor_groups_to_ranker_feature_groups(
    groups: list[FactorGroup],
) -> list[RankerFeatureGroup]:
    """Convert a list of ``FactorGroup`` to the existing ``RankerFeatureGroup`` type.

    Factor expressions within each group are ordered by factor id for determinism.
    Does not require a separate factors list — each group carries its own factors.
    """
    from src.research.ranker_calibration_grid import RankerFeatureGroup  # noqa: E402

    result: list[RankerFeatureGroup] = []
    for group in groups:
        expressions = tuple(
            f.expression for f in sorted(group.factors, key=lambda fs: fs.id)
        )
        result.append(RankerFeatureGroup(name=group.name, expressions=expressions))
    return result


def factor_library_manifest(groups: list[FactorGroup]) -> dict[str, object]:
    """Return a JSON-serializable manifest of the factor library groups.

    Parameters
    ----------
    groups:
        List of ``FactorGroup`` instances.

    Returns
    -------
    dict
        Manifest with ``schema_version``, ``n_groups``, ``group_names``,
        and per-group ``groups`` list.
    """
    all_factors: list[dict[str, str]] = []
    for g in groups:
        all_factors.extend(f.to_dict() for f in g.factors)

    return {
        "schema_version": STRUCTURED_FACTOR_LIBRARY_SCHEMA,
        "n_groups": len(groups),
        "n_factors": len(all_factors),
        "group_names": sorted(g.name for g in groups),
        "groups": [g.to_dict() for g in groups],
    }


def resolve_factor_expressions(
    factor_ids: list[str], library: dict[str, FactorGroup]
) -> list[str]:
    """Resolve a list of factor ids to their expressions.

    Searches across all groups in the library.

    Raises ValueError if any id is unknown (fail closed).
    """
    id_to_expr: dict[str, str] = {}
    for group in library.values():
        for f in group.factors:
            id_to_expr[f.id] = f.expression

    result: list[str] = []
    for fid in factor_ids:
        if fid not in id_to_expr:
            raise ValueError(f"Unknown factor id '{fid}'")
        result.append(id_to_expr[fid])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Compatibility wrappers — map old API to new
# ═══════════════════════════════════════════════════════════════════════════════


def load_structured_factor_library(
    path: str | Path,
) -> tuple[list[FactorSpec], list[FactorGroup]]:
    """Compatibility wrapper.  Use ``load_factor_library`` in new code.

    Returns the old ``(factors, groups)`` tuple format.
    """
    library = load_factor_library(path)
    # Build deduplicated factors list preserving first-occurrence order
    all_factors: list[FactorSpec] = []
    seen: set[str] = set()
    for g in library.values():
        for f in g.factors:
            if f.id not in seen:
                all_factors.append(f)
                seen.add(f.id)
    groups_list = list(library.values())
    return all_factors, groups_list


def select_factor_group(
    group_name: str, groups: list[FactorGroup], factors: list[FactorSpec]
) -> FactorGroup:
    """Compatibility wrapper for single-group selection.

    Prefer ``select_factor_groups(library, [group_name])[0]`` in new code.
    """
    # Build temp library from the flat list for fail-closed lookup
    temp_lib = {g.name: g for g in groups}
    return select_factor_groups(temp_lib, [group_name])[0]


def factor_group_to_ranker_feature_group(
    group: FactorGroup, factors: list[FactorSpec]
) -> RankerFeatureGroup:
    """Compatibility wrapper.  Prefer ``factor_groups_to_ranker_feature_groups``.

    The *factors* argument is ignored — the group carries its own factors.
    """
    result = factor_groups_to_ranker_feature_groups([group])
    return result[0]


# ═══════════════════════════════════════════════════════════════════════════════
# Combinatorial Factor Library (legacy — preserved for backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_FIELDS = ["$close", "$open", "$high", "$low", "$volume"]

LOOKBACK_WINDOWS: list[int] = [5, 10, 20, 60]

# Derived return expressions keyed by horizon
RETURN_EXPRESSIONS: dict[int, str] = {
    1: "$close/Ref($close,1)-1",
    5: "$close/Ref($close,5)-1",
    10: "$close/Ref($close,10)-1",
    20: "$close/Ref($close,20)-1",
    60: "$close/Ref($close,60)-1",
}

# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------


def _make_name(category: str, short_desc: str, window: int | None = None) -> str:
    """Build a factor name following ``{category}_{short_desc}_{window}`` convention."""
    if window is not None:
        return f"{category}_{short_desc}_{window}"
    return f"{category}_{short_desc}"


def _add(
    factors: list[dict],
    seen: set[str],
    category: str,
    name: str,
    expression: str,
) -> None:
    """Append a factor if its expression has not been seen yet."""
    if expression in seen:
        return
    seen.add(expression)
    factors.append({"name": name, "expression": expression, "category": category})


# ---------------------------------------------------------------------------
# Category generators
# ---------------------------------------------------------------------------


def _gen_momentum(factors: list[dict], seen: set[str]) -> None:
    """Momentum: price returns at multiple horizons, lagged returns, return accelerations."""
    cat = "momentum"

    # --- Raw returns at various horizons ---
    for horizon, expr in RETURN_EXPRESSIONS.items():
        _add(factors, seen, cat, _make_name(cat, "ret", horizon), expr)

    # --- Lagged returns: Ref(return, N) ---
    for horizon, ret_expr in RETURN_EXPRESSIONS.items():
        for lag in LOOKBACK_WINDOWS:
            expr = f"Ref({ret_expr},{lag})"
            _add(factors, seen, cat, _make_name(cat, f"lag_ret{horizon}", lag), expr)

    # --- Return acceleration: current return - lagged return ---
    for horizon in [1, 5]:
        ret_expr = RETURN_EXPRESSIONS[horizon]
        for lag in [5, 10, 20]:
            expr = f"{ret_expr}-Ref({ret_expr},{lag})"
            _add(factors, seen, cat, _make_name(cat, f"accel{horizon}", lag), expr)

    # --- Mean of returns ---
    for horizon, ret_expr in RETURN_EXPRESSIONS.items():
        for w in LOOKBACK_WINDOWS:
            expr = f"Mean({ret_expr},{w})"
            _add(factors, seen, cat, _make_name(cat, f"mean_ret{horizon}", w), expr)

    # --- Max of returns ---
    for horizon in [1, 5, 10]:
        ret_expr = RETURN_EXPRESSIONS[horizon]
        for w in [10, 20, 60]:
            expr = f"Max({ret_expr},{w})"
            _add(factors, seen, cat, _make_name(cat, f"max_ret{horizon}", w), expr)

    # --- Min of returns ---
    for horizon in [1, 5, 10]:
        ret_expr = RETURN_EXPRESSIONS[horizon]
        for w in [10, 20, 60]:
            expr = f"Min({ret_expr},{w})"
            _add(factors, seen, cat, _make_name(cat, f"min_ret{horizon}", w), expr)


def _gen_volatility(factors: list[dict], seen: set[str]) -> None:
    """Volatility: rolling std of returns, volatility ratios, high-low range."""
    cat = "volatility"
    daily_ret = RETURN_EXPRESSIONS[1]

    # --- Rolling std of daily returns ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Std({daily_ret},{w})"
        _add(factors, seen, cat, _make_name(cat, "std_ret", w), expr)

    # --- Rolling std of 5-day returns ---
    ret5 = RETURN_EXPRESSIONS[5]
    for w in [10, 20, 60]:
        expr = f"Std({ret5},{w})"
        _add(factors, seen, cat, _make_name(cat, "std_ret5", w), expr)

    # --- Volatility ratios: short-term vol / long-term vol ---
    for short_w, long_w in [(5, 20), (5, 60), (10, 20), (10, 60), (20, 60)]:
        expr = f"Std({daily_ret},{short_w})/Std({daily_ret},{long_w})"
        _add(factors, seen, cat, _make_name(cat, f"vol_ratio_{short_w}_{long_w}"), expr)

    # --- High-low range volatility ---
    for w in LOOKBACK_WINDOWS:
        # Average true range proxy
        expr = f"Mean(($high-$low)/$close,{w})"
        _add(factors, seen, cat, _make_name(cat, "atr", w), expr)

    # --- Rolling max-min spread of close ---
    for w in LOOKBACK_WINDOWS:
        expr = f"(Max($close,{w})-Min($close,{w}))/$close"
        _add(factors, seen, cat, _make_name(cat, "range_pct", w), expr)

    # --- Std of volume (volume volatility) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Std($volume,{w})/Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_of_vol", w), expr)


def _gen_volume(factors: list[dict], seen: set[str]) -> None:
    """Volume: volume moving averages, volume ratios, price-volume interaction."""
    cat = "volume"

    # --- Volume / MA(volume, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"$volume/Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_ma_ratio", w), expr)

    # --- MA(volume, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_ma", w), expr)

    # --- Delta(volume, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Delta($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_delta", w), expr)

    # --- Volume momentum: volume / Ref(volume, N) - 1 ---
    for w in LOOKBACK_WINDOWS:
        expr = f"$volume/Ref($volume,{w})-1"
        _add(factors, seen, cat, _make_name(cat, "vol_mom", w), expr)

    # --- Rolling std of volume ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Std($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_std", w), expr)

    # --- Volume-weighted price ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean($volume*$close,{w})/Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vwap", w), expr)

    # --- Max volume ratio ---
    for w in [10, 20, 60]:
        expr = f"$volume/Max($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_max_ratio", w), expr)

    # --- Min volume ratio ---
    for w in [10, 20, 60]:
        expr = f"$volume/Min($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_min_ratio", w), expr)


def _gen_mean_reversion(factors: list[dict], seen: set[str]) -> None:
    """Mean reversion: deviation from moving averages, Bollinger-band-like."""
    cat = "mean_reversion"

    # --- Price / MA(price, N) - 1 ---
    for w in LOOKBACK_WINDOWS:
        expr = f"$close/Mean($close,{w})-1"
        _add(factors, seen, cat, _make_name(cat, "ma_dev", w), expr)

    # --- Price / MA(price, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"$close/Mean($close,{w})"
        _add(factors, seen, cat, _make_name(cat, "price_ma_ratio", w), expr)

    # --- Bollinger band position: (close - MA) / Std ---
    for w in LOOKBACK_WINDOWS:
        expr = f"($close-Mean($close,{w}))/Std($close,{w})"
        _add(factors, seen, cat, _make_name(cat, "bb_pos", w), expr)

    # --- Price deviation from EMA proxy (short MA vs long MA) ---
    for short_w, long_w in [(5, 20), (5, 60), (10, 20), (10, 60), (20, 60)]:
        expr = f"Mean($close,{short_w})/Mean($close,{long_w})-1"
        _add(factors, seen, cat, _make_name(cat, f"ma_cross_{short_w}_{long_w}"), expr)

    # --- Price vs high/low ---
    for w in LOOKBACK_WINDOWS:
        expr = f"($close-Min($close,{w}))/(Max($close,{w})-Min($close,{w}))"
        _add(factors, seen, cat, _make_name(cat, "stoch_k", w), expr)

    # --- Mean reversion of returns ---
    for w in LOOKBACK_WINDOWS:
        daily_ret = RETURN_EXPRESSIONS[1]
        expr = f"Mean({daily_ret},{w})/Std({daily_ret},{w})"
        _add(factors, seen, cat, _make_name(cat, "ret_sharpe", w), expr)


def _gen_technical(factors: list[dict], seen: set[str]) -> None:
    """Technical: RSI-like, momentum rank, price patterns."""
    cat = "technical"
    daily_ret = RETURN_EXPRESSIONS[1]

    # --- RSI-like: average gain / (average gain + average loss) ---
    for w in LOOKBACK_WINDOWS:
        # Approximation: Mean of positive returns vs Mean of absolute returns
        expr = f"Mean(Greater({daily_ret},0)*{daily_ret},{w})/(Mean(Abs({daily_ret}),{w})+1e-10)"
        _add(factors, seen, cat, _make_name(cat, "rsi_proxy", w), expr)

    # --- Momentum strength: sum of positive returns ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Sum(Greater({daily_ret},0),{w})"
        _add(factors, seen, cat, _make_name(cat, "pos_ret_sum", w), expr)

    # --- Downside capture: sum of negative returns ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Sum(Less({daily_ret},0),{w})"
        _add(factors, seen, cat, _make_name(cat, "neg_ret_sum", w), expr)

    # --- Up-down ratio ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Sum(Greater({daily_ret},0),{w})/(Abs(Sum(Less({daily_ret},0),{w}))+1e-10)"
        _add(factors, seen, cat, _make_name(cat, "up_down_ratio", w), expr)

    # --- Price relative to N-day high ---
    for w in LOOKBACK_WINDOWS:
        expr = f"$close/Max($close,{w})"
        _add(factors, seen, cat, _make_name(cat, "price_high_ratio", w), expr)

    # --- Price relative to N-day low ---
    for w in LOOKBACK_WINDOWS:
        expr = f"$close/Min($close,{w})"
        _add(factors, seen, cat, _make_name(cat, "price_low_ratio", w), expr)

    # --- Close-to-open ratio (intraday pattern) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean($close/$open,{w})"
        _add(factors, seen, cat, _make_name(cat, "close_open_ma", w), expr)

    # --- High-close range (upper shadow proxy) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean(($high-$close)/$close,{w})"
        _add(factors, seen, cat, _make_name(cat, "upper_shadow", w), expr)

    # --- Close-low range (lower shadow proxy) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean(($close-$low)/$close,{w})"
        _add(factors, seen, cat, _make_name(cat, "lower_shadow", w), expr)

    # --- Delta of close ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Delta($close,{w})"
        _add(factors, seen, cat, _make_name(cat, "delta_close", w), expr)

    # --- Delta of close / close (normalized delta) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Delta($close,{w})/$close"
        _add(factors, seen, cat, _make_name(cat, "norm_delta", w), expr)


def _gen_cross_field(factors: list[dict], seen: set[str]) -> None:
    """Cross-field: correlations between price and volume, price-volume divergence."""
    cat = "cross_field"
    daily_ret = RETURN_EXPRESSIONS[1]

    # --- Correlation(close, volume, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Corr($close,$volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "corr_close_vol", w), expr)

    # --- Correlation(return, volume, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Corr({daily_ret},$volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "corr_ret_vol", w), expr)

    # --- Correlation(close, high, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Corr($close,$high,{w})"
        _add(factors, seen, cat, _make_name(cat, "corr_close_high", w), expr)

    # --- Correlation(close, low, N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Corr($close,$low,{w})"
        _add(factors, seen, cat, _make_name(cat, "corr_close_low", w), expr)

    # --- Correlation between short and long returns ---
    for short_h, long_h in [(1, 5), (1, 10), (5, 10), (5, 20), (10, 20)]:
        for w in [20, 60]:
            short_ret = RETURN_EXPRESSIONS[short_h]
            long_ret = RETURN_EXPRESSIONS[long_h]
            expr = f"Corr({short_ret},{long_ret},{w})"
            _add(
                factors,
                seen,
                cat,
                _make_name(cat, f"corr_ret{short_h}_ret{long_h}", w),
                expr,
            )

    # --- Price-volume divergence: price up but volume down (and vice versa) ---
    for w in LOOKBACK_WINDOWS:
        price_chg = f"Delta($close,{w})"
        vol_chg = f"Delta($volume,{w})"
        expr = f"Corr({price_chg},{vol_chg},{w})"
        _add(factors, seen, cat, _make_name(cat, "pv_divergence", w), expr)

    # --- Open-close vs volume correlation ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Corr($close-$open,$volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "corr_body_vol", w), expr)


def _gen_composite(factors: list[dict], seen: set[str]) -> None:
    """Composite factors combining multiple concepts."""
    cat = "composite"
    daily_ret = RETURN_EXPRESSIONS[1]

    # --- Volume-adjusted momentum ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean({daily_ret},{w})*($volume/Mean($volume,{w}))"
        _add(factors, seen, cat, _make_name(cat, "vol_adj_mom", w), expr)

    # --- Volatility-adjusted momentum (return Sharpe-like) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean({daily_ret},{w})/Std({daily_ret},{w})"
        _add(factors, seen, cat, _make_name(cat, "sharpe", w), expr)

    # --- Skewness proxy: Mean(ret^3) / Std(ret)^3 ---
    for w in [20, 60]:
        expr = f"Mean(Power({daily_ret},3),{w})/Power(Std({daily_ret},{w}),3)"
        _add(factors, seen, cat, _make_name(cat, "skew_proxy", w), expr)

    # --- Kurtosis proxy: Mean(ret^4) / Std(ret)^4 ---
    for w in [20, 60]:
        expr = f"Mean(Power({daily_ret},4),{w})/Power(Std({daily_ret},{w}),4)"
        _add(factors, seen, cat, _make_name(cat, "kurt_proxy", w), expr)

    # --- Volume-weighted return ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Mean({daily_ret}*$volume,{w})/Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vw_return", w), expr)

    # --- Price efficiency: net displacement / total path ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Abs(Delta($close,{w}))/(Sum(Abs(Delta($close,1)),{w})+1e-10)"
        _add(factors, seen, cat, _make_name(cat, "efficiency", w), expr)

    # --- Volume concentration: Max(vol,N) / Mean(vol,N) ---
    for w in LOOKBACK_WINDOWS:
        expr = f"Max($volume,{w})/Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_concentration", w), expr)

    # --- Mean reversion with volume confirmation ---
    for w in [10, 20, 60]:
        ma_dev = f"$close/Mean($close,{w})-1"
        vol_ratio = f"$volume/Mean($volume,{w})"
        expr = f"({ma_dev})*({vol_ratio})"
        _add(factors, seen, cat, _make_name(cat, "mr_vol_confirm", w), expr)

    # --- Trend strength: slope of close (using Rsquare as proxy) ---
    for w in [10, 20, 60]:
        expr = f"Slope($close,{w})/$close"
        _add(factors, seen, cat, _make_name(cat, "trend_slope", w), expr)

    # --- R-squared of price trend ---
    for w in [10, 20, 60]:
        expr = f"Rsquare($close,{w})"
        _add(factors, seen, cat, _make_name(cat, "trend_r2", w), expr)

    # --- Residual of price trend (mean reversion signal) ---
    for w in [10, 20, 60]:
        expr = f"Resi($close,{w})/$close"
        _add(factors, seen, cat, _make_name(cat, "trend_resid", w), expr)

    # --- Volume trend: slope of volume ---
    for w in [10, 20, 60]:
        expr = f"Slope($volume,{w})/Mean($volume,{w})"
        _add(factors, seen, cat, _make_name(cat, "vol_trend", w), expr)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


# Default path relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_YAML_PATH = _PROJECT_ROOT / "configs" / "factor_pool.yaml"


def load_factor_pool_from_yaml(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load factor pool from a YAML configuration file.

    The YAML must have a ``factor_pools`` key whose value is a mapping of
    category names to lists of factor dicts.  Each factor dict must have at
    least ``name`` and ``expression`` keys.

    Parameters
    ----------
    path:
        Path to the YAML file.  When ``None``, uses the default
        ``configs/factor_pool.yaml``.

    Returns
    -------
    list[dict[str, Any]]
        Flat list of factor dicts with ``{name, expression, category}`` keys.
    """
    yaml_path = Path(path) if path else _DEFAULT_YAML_PATH
    if not yaml_path.exists():
        raise FileNotFoundError(f"Factor pool YAML not found: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    factor_pools = data.get("factor_pools", {})
    factors: list[dict[str, Any]] = []
    seen: set[str] = set()

    for category, items in factor_pools.items():
        for item in items:
            expr = item["expression"]
            if expr in seen:
                continue
            seen.add(expr)
            factors.append(
                {
                    "name": item["name"],
                    "expression": expr,
                    "category": category,
                }
            )

    return factors


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------


def _generate_factor_library_python() -> list[dict[str, Any]]:
    """Generate a comprehensive factor library via combinatorial enumeration.

    Returns a list of dicts with ``{name, expression, category}`` suitable
    for ``scan_factor_pool``.  Target: 200+ unique factors.
    """
    factors: list[dict[str, Any]] = []
    seen: set[str] = set()

    _gen_momentum(factors, seen)
    _gen_volatility(factors, seen)
    _gen_volume(factors, seen)
    _gen_mean_reversion(factors, seen)
    _gen_technical(factors, seen)
    _gen_cross_field(factors, seen)
    _gen_composite(factors, seen)

    return factors


def generate_factor_library(
    yaml_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load the factor library, preferring YAML over Python generation.

    Parameters
    ----------
    yaml_path:
        Explicit path to a factor pool YAML.  When ``None`` (the default),
        the loader tries ``configs/factor_pool.yaml`` first and falls back
        to programmatic generation if that file does not exist.

    Returns
    -------
    list[dict[str, Any]]
        Flat list of factor dicts.
    """
    if yaml_path is not None:
        return load_factor_pool_from_yaml(yaml_path)

    try:
        return load_factor_pool_from_yaml(_DEFAULT_YAML_PATH)
    except FileNotFoundError:
        return _generate_factor_library_python()


# ---------------------------------------------------------------------------
# Pre-built library (module-level, importable)
# ---------------------------------------------------------------------------

FACTOR_LIBRARY: list[dict[str, Any]] = generate_factor_library()

# Category-specific convenience lists
MOMENTUM_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "momentum"]
VOLATILITY_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "volatility"]
VOLUME_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "volume"]
MEAN_REVERSION_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "mean_reversion"]
TECHNICAL_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "technical"]
CROSS_FIELD_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "cross_field"]
COMPOSITE_LIBRARY = [f for f in FACTOR_LIBRARY if f["category"] == "composite"]


def get_library_summary() -> dict[str, int]:
    """Return a summary of factor counts by category."""
    summary: dict[str, int] = {}
    for f in FACTOR_LIBRARY:
        cat = f["category"]
        summary[cat] = summary.get(cat, 0) + 1
    summary["total"] = len(FACTOR_LIBRARY)
    return summary


def get_factors_by_category(category: str) -> list[dict[str, Any]]:
    """Return factors filtered by category name."""
    return [f for f in FACTOR_LIBRARY if f["category"] == category]


def get_factor_library_json(category: str = "") -> str:
    """Return the factor library as a JSON string, optionally filtered by category."""
    if category:
        filtered = get_factors_by_category(category)
    else:
        filtered = FACTOR_LIBRARY
    return json.dumps(
        {
            "total": len(filtered),
            "summary": get_library_summary(),
            "factors": filtered,
        },
        indent=2,
    )


if __name__ == "__main__":
    summary = get_library_summary()
    print("Factor Library Summary:")
    for cat, count in sorted(summary.items()):
        print(f"  {cat}: {count}")
    print(f"\nTotal factors: {summary['total']}")
