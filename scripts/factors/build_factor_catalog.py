"""Build the versioned AlphaEngine factor catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.factors import FactorCatalog, load_factor_library
from src.factors.library import ALPHA158_SOURCE_PATH


def build_catalog() -> FactorCatalog:
    alpha158 = load_factor_library(ALPHA158_SOURCE_PATH)
    catalog = FactorCatalog(
        catalog_id="alpha_engine_factor_catalog",
        catalog_version="1.0",
    )
    catalog.extend(alpha158.catalog.definitions)
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/factor_catalog/factor_catalog_v1.json"),
    )
    args = parser.parse_args()

    catalog = build_catalog()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(catalog.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
