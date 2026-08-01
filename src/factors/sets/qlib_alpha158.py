"""Exact Qlib Alpha158 catalog sourced from the installed pyqlib package."""

from __future__ import annotations

import re
from importlib.metadata import version

from qlib.contrib.data.loader import Alpha158DL

from src.factors.definition import FactorDefinition

NAMESPACE = "qlib_alpha158"
SOURCE_REFERENCE = (
    "https://github.com/microsoft/qlib/blob/"
    "79633dd9506ea689e5400dea0197717b5b3d74b7/qlib/contrib/data/loader.py"
)
ALPHA158_CONFIG = {
    "kbar": {},
    "price": {
        "windows": [0],
        "feature": ["OPEN", "HIGH", "LOW", "VWAP"],
    },
    "rolling": {},
}
_REQUIRED_FIELDS = ("open", "high", "low", "close", "vwap", "volume")
_TRAILING_WINDOW = re.compile(r"(\d+)$")


def _minimum_lookback(name: str) -> int:
    match = _TRAILING_WINDOW.search(name)
    if match is None:
        return 0
    return int(match.group(1))


def load_alpha158_definitions() -> list[FactorDefinition]:
    """Return Qlib's exact default Alpha158 fields in canonical order."""

    fields, names = Alpha158DL.get_feature_config(ALPHA158_CONFIG)
    if len(fields) != 158 or len(names) != 158:
        raise ValueError(
            "installed pyqlib Alpha158 contract drifted from 158 features: "
            f"fields={len(fields)}, names={len(names)}"
        )
    if len(set(names)) != 158:
        raise ValueError("installed pyqlib Alpha158 names are not unique")

    source_version = version("pyqlib")
    definitions: list[FactorDefinition] = []
    for expression, name in zip(fields, names, strict=True):
        normalized_name = str(name).strip().lower()
        definitions.append(
            FactorDefinition.create(
                factor_id=f"{NAMESPACE}.{normalized_name}",
                factor_version="1.0",
                display_name=str(name),
                namespace=NAMESPACE,
                information_family="technical_ohlcv",
                expression=str(expression),
                source_name="Qlib Alpha158DL",
                source_version=source_version,
                source_reference=SOURCE_REFERENCE,
                required_fields=_REQUIRED_FIELDS,
                markets=("us", "cn"),
                minimum_lookback=_minimum_lookback(str(name)),
                availability_lag_sessions=0,
                adjustment_requirement="adjusted",
                status="unvalidated_formula",
            )
        )
    return definitions
