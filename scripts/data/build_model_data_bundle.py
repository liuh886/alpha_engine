#!/usr/bin/env python3
"""Build one unified model-training and frontend data-readiness bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.model_data_bundle import (
    ComponentSpec,
    ModelDataBundleError,
    build_model_data_bundle,
    verify_model_data_bundle,
)


def _component_spec(value: str) -> ComponentSpec:
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "component must be COMPONENT_ID:KIND:PATH[:MARKET]"
        )
    component_id, kind, remainder = parts
    path, separator, market = remainder.rpartition(":")
    if not separator or market.strip().lower() not in {"cn", "global", "us"}:
        path = remainder
        market = None
    if not component_id.strip() or not kind.strip() or not path.strip():
        raise argparse.ArgumentTypeError("component fields must be non-empty")
    return ComponentSpec(
        component_id=component_id.strip(),
        component_kind=kind.strip(),
        manifest_path=Path(path),
        market=market.strip().lower() if market else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/data_contracts/model_data_bundle_v1.yaml"),
    )
    parser.add_argument(
        "--component",
        type=_component_spec,
        action="append",
        default=[],
        help="COMPONENT_ID:KIND:PATH[:MARKET]; repeat for every available component",
    )
    parser.add_argument("--evidence-cutoff", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/data/model_data_bundle_v1"),
    )
    parser.add_argument(
        "--frontend-data-dir",
        type=Path,
        default=None,
        help="Optional static export data directory, for example artifacts/site/data",
    )
    parser.add_argument(
        "--source-receipt",
        type=Path,
        action="append",
        default=[],
        help="Verified governed-source receipt; repeat when multiple registries are used",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    contract = args.contract if args.contract.is_absolute() else root / args.contract
    specs = [
        ComponentSpec(
            component_id=spec.component_id,
            component_kind=spec.component_kind,
            manifest_path=(
                spec.manifest_path
                if spec.manifest_path.is_absolute()
                else root / spec.manifest_path
            ),
            market=spec.market,
        )
        for spec in args.component
    ]
    output = args.output_root if args.output_root.is_absolute() else root / args.output_root
    frontend = args.frontend_data_dir
    if frontend is not None and not frontend.is_absolute():
        frontend = root / frontend
    receipts = [path if path.is_absolute() else root / path for path in args.source_receipt]

    try:
        manifest = build_model_data_bundle(
            root=root,
            contract_path=contract,
            component_specs=specs,
            output_root=output,
            evidence_cutoff=args.evidence_cutoff,
            frontend_data_dir=frontend,
            source_receipts=receipts,
        )
        verified = verify_model_data_bundle(output)
    except ModelDataBundleError as exc:
        parser.error(str(exc))
        return 2

    print(
        json.dumps(
            {
                "bundle_id": manifest["bundle_id"],
                "summary": manifest["summary"],
                "verified_indexes": verified,
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
