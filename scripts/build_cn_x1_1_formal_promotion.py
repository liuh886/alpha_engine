"""Materialize the authorized CN x1.1 formal baseline deterministically."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.cn_x1_1_formal_evidence import build_formal_evidence
from src.research.cn_x1_1_formal_freshness import (
    cn_x1_1_package_freshness,
    write_cn_x1_1_freshness,
)
from src.research.cn_x1_1_formal_publication import publish_formal_evidence


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
