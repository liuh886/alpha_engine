"""Build and catalog the governed US x1.2 research-preview bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.artifacts.model_run_exporter import export_model_run, update_catalog
from src.artifacts.us_x1_2_preview import build_plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research/model_runs"),
    )
    args = parser.parse_args()
    manifest = export_model_run(
        build_plan(
            args.root,
            provider_dir=args.provider_dir,
            generated_at=args.generated_at,
        ),
        output_root=args.output_root,
    )
    catalog = update_catalog(
        [manifest],
        catalog_path=args.output_root / "catalog.json",
        channel="preview",
    )
    print(json.dumps(catalog, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
