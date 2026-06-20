"""Versioned metric contract for model evaluation results.

Provides a standardized schema for model metrics across the Alpha Engine
pipeline.  Raw metric dictionaries produced by different subsystems (backtest,
walk-forward, factor evaluation) often use inconsistent key names and treat
missing values differently (0 vs None).  This module normalises them into a
single, versioned contract.

Version history
---------------
v1 — Initial contract covering IC, return, risk, and execution metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from typing import Any

from src.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Field definition helpers
# ---------------------------------------------------------------------------

# Metric unit constants
UNIT_RATIO = "ratio"          # dimensionless ratio (e.g. Sharpe)
UNIT_RETURN = "return"        # annualised or period return
UNIT_FRACTION = "fraction"    # 0-1 fraction (e.g. coverage)
UNIT_COUNT = "count"          # integer count
UNIT_CURRENCY = "currency"    # monetary value
UNIT_DAYS = "days"            # calendar/trading days
UNIT_NONE = "none"            # no unit


@dataclass(frozen=True)
class FieldSpec:
    """Specification for a single metric field."""

    name: str
    unit: str
    description: str
    required: bool  # True = must be present after normalisation


# ---------------------------------------------------------------------------
# Contract versions
# ---------------------------------------------------------------------------

_CONTRACT_V1_FIELDS: list[FieldSpec] = [
    # --- IC / cross-sectional metrics ---
    FieldSpec("ic", UNIT_RATIO, "Pearson information coefficient", False),
    FieldSpec("rank_ic", UNIT_RATIO, "Spearman rank IC", False),
    FieldSpec("icir", UNIT_RATIO, "IC information ratio (IC / IC_std)", False),
    FieldSpec("consistency", UNIT_FRACTION, "Fraction of periods with positive IC", False),
    FieldSpec("sample_count", UNIT_COUNT, "Number of evaluation periods/samples", False),
    FieldSpec("coverage", UNIT_FRACTION, "Fraction of assets with non-null factor values", False),
    # --- Return metrics ---
    FieldSpec("annualized_return", UNIT_RETURN, "Annualised compound return", True),
    FieldSpec("total_return", UNIT_RETURN, "Total cumulative return over evaluation window", False),
    FieldSpec("benchmark_return", UNIT_RETURN, "Benchmark annualised return", False),
    FieldSpec("excess_return", UNIT_RETURN, "Strategy return minus benchmark return", False),
    # --- Risk metrics ---
    FieldSpec("volatility", UNIT_RATIO, "Annualised return volatility (std dev)", False),
    FieldSpec("sharpe", UNIT_RATIO, "Sharpe ratio (excess return / volatility)", False),
    FieldSpec("information_ratio", UNIT_RATIO, "Information ratio (excess return / tracking error)", False),
    FieldSpec("max_drawdown", UNIT_RETURN, "Maximum peak-to-trough drawdown (negative value)", True),
    # --- Execution / portfolio metrics ---
    FieldSpec("turnover", UNIT_FRACTION, "Average portfolio turnover per period", False),
    FieldSpec("costs", UNIT_RETURN, "Estimated transaction costs over evaluation window", False),
    FieldSpec("net_return", UNIT_RETURN, "Return after deducting transaction costs", False),
    # --- Meta ---
    FieldSpec("evaluation_window", UNIT_DAYS, "Number of trading days in evaluation window", False),
]

# Map of contract version -> ordered list of FieldSpec
_REGISTRY: dict[str, list[FieldSpec]] = {
    "v1": _CONTRACT_V1_FIELDS,
}

# Canonical alias map: common raw key -> canonical key in the contract.
# Helps normalise metrics from heterogeneous sources (Qlib backtest,
# walk-forward, factor evaluator, reporting module, etc.).
_ALIASES: dict[str, str | None] = {
    # Qlib / MetricsExtractor keys
    "Annualized Return": "annualized_return",
    "annualized_return": "annualized_return",
    "annual_return": "annualized_return",
    "Information Ratio": "information_ratio",
    "information_ratio": "information_ratio",
    "info_ratio": "information_ratio",
    "Max Drawdown": "max_drawdown",
    "max_drawdown": "max_drawdown",
    "max_dd": "max_drawdown",
    # Sharpe variants
    "Sharpe Ratio": "sharpe",
    "sharpe_ratio": "sharpe",
    "sharpe": "sharpe",
    # Return variants
    "Excess Return": "excess_return",
    "excess_return": "excess_return",
    "excess": "excess_return",
    "total_return": "total_return",
    "cumulative_return": "total_return",
    "benchmark_return": "benchmark_return",
    "bm_return": "benchmark_return",
    "net_return": "net_return",
    "net_ret": "net_return",
    # IC variants
    "ic": "ic",
    "IC": "ic",
    "pearson_ic": "ic",
    "rank_ic": "rank_ic",
    "Rank IC": "rank_ic",
    "spearman_ic": "rank_ic",
    "icir": "icir",
    "ICIR": "icir",
    "ic_ir": "icir",
    "IC_IR": "icir",
    "consistency": "consistency",
    "consistency_score": "consistency",
    "positive_ratio": "consistency",
    # Coverage / sample
    "coverage": "coverage",
    "sample_count": "sample_count",
    "n_periods": "sample_count",
    "n_samples": "sample_count",
    # Risk
    "volatility": "volatility",
    "vol": "volatility",
    "annualized_volatility": "volatility",
    "tracking_error": "volatility",
    # Execution
    "turnover": "turnover",
    "costs": "costs",
    "transaction_costs": "costs",
    # Evaluation window
    "evaluation_window": "evaluation_window",
    "eval_window": "evaluation_window",
    "n_days": "evaluation_window",
    # Win rate (not in contract, but common — map to None so it is silently dropped)
    "Win Rate": None,
    "win_rate": None,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class MetricContract:
    """Versioned metric schema definition.

    Parameters
    ----------
    version : str
        Contract version identifier (e.g. ``"v1"``).
    """

    version: str = "v1"
    _fields: list[FieldSpec] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.version not in _REGISTRY:
            raise ValueError(
                f"Unknown metric contract version {self.version!r}. "
                f"Known versions: {sorted(_REGISTRY)}"
            )
        self._fields = _REGISTRY[self.version]

    # -- introspection -------------------------------------------------------

    @property
    def fields(self) -> list[FieldSpec]:
        """Return the ordered list of field specifications."""
        return list(self._fields)

    @property
    def required_fields(self) -> list[str]:
        """Return names of required fields."""
        return [f.name for f in self._fields if f.required]

    @property
    def optional_fields(self) -> list[str]:
        """Return names of optional fields."""
        return [f.name for f in self._fields if not f.required]

    @property
    def all_fields(self) -> list[str]:
        """Return all field names in canonical order."""
        return [f.name for f in self._fields]

    def field_spec(self, name: str) -> FieldSpec | None:
        """Look up a field specification by canonical name."""
        for f in self._fields:
            if f.name == name:
                return f
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialise the contract to a plain dictionary."""
        return {
            "version": self.version,
            "fields": [
                {
                    "name": f.name,
                    "unit": f.unit,
                    "description": f.description,
                    "required": f.required,
                }
                for f in self._fields
            ],
        }


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _coerce_float(value: Any) -> float | None:
    """Attempt to convert *value* to ``float``; return ``None`` on failure."""
    if value is None:
        return None
    if isinstance(value, Real):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_metrics(raw_dict: dict[str, Any], version: str = "v1") -> dict[str, Any]:
    """Convert a raw metric dictionary to the standard schema.

    * Keys are resolved through the alias map to canonical names.
    * Values are coerced to ``float`` where possible; un-coercible values
      become ``None``.
    * Missing fields are set to ``None`` (not ``0``).
    * Extra keys not in the contract are silently dropped.

    Parameters
    ----------
    raw_dict : dict
        Raw metrics from any source.
    version : str
        Target contract version.

    Returns
    -------
    dict
        Normalised metrics conforming to the contract.  Keys are in the
        canonical field order.
    """
    contract = MetricContract(version)
    canonical_names = set(contract.all_fields)

    # First pass: resolve aliases and coerce values.
    resolved: dict[str, Any] = {}
    for raw_key, raw_value in (raw_dict or {}).items():
        canonical = _ALIASES.get(raw_key)
        if canonical is None:
            # Explicitly unmapped (e.g. "Win Rate") — skip.
            if raw_key not in _ALIASES:
                # Unknown key — try direct match against canonical names.
                if raw_key in canonical_names:
                    canonical = raw_key
                else:
                    logger.debug("Dropping unknown metric key", key=raw_key)
                    continue
            else:
                # Mapped to None — intentionally skipped.
                continue
        resolved[canonical] = _coerce_float(raw_value)

    # Second pass: build output in canonical order, filling missing with None.
    output: dict[str, Any] = {}
    for fs in contract.fields:
        output[fs.name] = resolved.get(fs.name)  # None if missing

    return output


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of a metric validation check."""

    ok: bool
    missing_required: list[str]
    version: str

    def __bool__(self) -> bool:
        return self.ok


def validate_metrics(metrics: dict[str, Any], version: str = "v1") -> ValidationResult:
    """Check that all required fields for *version* are present and non-None.

    Parameters
    ----------
    metrics : dict
        Metrics dictionary (typically output of :func:`normalize_metrics`).
    version : str
        Contract version to validate against.

    Returns
    -------
    ValidationResult
        ``.ok`` is ``True`` when every required field has a non-None value.
    """
    contract = MetricContract(version)
    missing: list[str] = []
    for fs in contract.fields:
        if fs.required:
            value = metrics.get(fs.name)
            if value is None:
                missing.append(fs.name)
    return ValidationResult(
        ok=len(missing) == 0,
        missing_required=missing,
        version=version,
    )
