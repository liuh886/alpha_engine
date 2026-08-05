"""Materialize the authorized CN x1.1 formal baseline deterministically."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes
from src.research.cn_x1_1_formal_evidence import build_formal_evidence
from src.research.cn_x1_1_formal_freshness import (
    cn_x1_1_package_freshness,
    write_cn_x1_1_freshness,
)
from src.research.cn_x1_1_formal_publication import publish_formal_evidence


def _preserve_shared_catalog_timestamp(
    *,
    repository_root: Path,
    output_dir: Path,
    receipt: dict[str, object],
) -> None:
    source_path = repository_root / "data/research/formal_backtests/catalog.json"
    target_path = output_dir / "data/research/formal_backtests/catalog.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    target = json.loads(target_path.read_text(encoding="utf-8"))
    target["published_at"] = source["published_at"]
    target_path.write_bytes(canonical_json_bytes(target))
    generated_files = receipt.get("generated_files")
    if isinstance(generated_files, list):
        for item in generated_files:
            if not isinstance(item, dict):
                continue
            if item.get("path") != "data/research/formal_backtests/catalog.json":
                continue
            item["sha256"] = hashlib.sha256(target_path.read_bytes()).hexdigest()
            item["bytes"] = target_path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    args = parser.parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    repository_root = args.repository_root.resolve()
    evidence = build_formal_evidence(source_dir)
    evidence.package["freshness"] = cn_x1_1_package_freshness()
    receipt = publish_formal_evidence(
        evidence,
        source_dir=source_dir,
        repository_root=repository_root,
        output_root=output_dir,
    )
    _preserve_shared_catalog_timestamp(
        repository_root=repository_root,
        output_dir=output_dir,
        receipt=receipt,
    )
    receipt["freshness"] = write_cn_x1_1_freshness(
        repository_root=repository_root,
        output_root=output_dir,
    )
    (output_dir / "promotion-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
