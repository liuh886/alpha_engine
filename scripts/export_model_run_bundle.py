"""Export a governed Model Run Bundle v2 through a registered adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.model_run_exporter import (
    export_from_adapter,
    registered_adapters,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, choices=registered_adapters())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=None)
    args = parser.parse_args()
    manifest_path = export_from_adapter(
        adapter_id=args.adapter,
        source=args.source,
        output_root=args.output_root,
        catalog_path=args.catalog,
    )
    print(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "status": "exported",
                "adapter": args.adapter,
                "manifest_path": manifest_path.as_posix(),
                "research_only": True,
                "trade_ready": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
