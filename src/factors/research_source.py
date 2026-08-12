"""Load canonical factor sources for governed research experiments."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.factors.catalog import FactorCatalog
from src.factors.library import (
    FACTOR_LIBRARY_SCHEMA_VERSION,
    FactorGroup,
    FactorLibrary,
    load_factor_library,
)
from src.factors.sets.qlib_alpha158 import load_alpha158_definitions


def load_research_factor_source(source_path: str | Path) -> FactorLibrary:
    """Load one declared canonical factor source; unknown source shapes fail closed."""

    path = Path(source_path).resolve()
    if path.suffix in {".yaml", ".yml"}:
        return load_factor_library(path)

    canonical_alpha158 = (Path(__file__).resolve().parent / "sets" / "qlib_alpha158.py").resolve()
    if path != canonical_alpha158 or not path.is_file():
        raise ValueError(f"unsupported canonical factor source: {path}")

    definitions = sorted(load_alpha158_definitions(), key=lambda row: row.factor_id)
    if len(definitions) != 158:
        raise ValueError(f"Alpha158 source must resolve exactly 158 factors: {len(definitions)}")
    catalog = FactorCatalog(catalog_id="qlib_alpha158", catalog_version="1.0")
    catalog.extend(definitions)
    factor_ids = tuple(row.factor_id for row in definitions)
    group = FactorGroup(
        name="qlib_alpha158_all",
        description="Exact installed Qlib Alpha158 catalog in stable factor-ID order",
        factor_ids=factor_ids,
        factors=tuple(definitions),
    )
    return FactorLibrary(
        schema_version=FACTOR_LIBRARY_SCHEMA_VERSION,
        source_path=path,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        catalog=catalog,
        groups={group.name: group},
    )
