"""Build the versioned AlphaEngine factor catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.factors import FactorCatalog
from src.factors.sets.qlib_alpha158 import load_alpha158_definitions


def build_catalog() -> FactorCatalog:
    catalog = FactorCatalog(
        catalog_id="alpha_engine_factor_catalog",
        catalog_version="1.0",
    )
    catalog.extend(load_alpha158_definitions())
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
