"""Build the frozen CN x1.2 reporting-only score ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from src.artifacts.strategy_refresh_exit import (
    DATA_BLOCKED_EXIT_CODE,
    DataBlockedError,
    assert_shared_provider_coverage,
)
from src.research.cn_x1_2_prospective import build_cn_x1_2_prospective_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        universe = yaml.safe_load(
            (
                args.repository_root.resolve()
                / "configs/research_universes/cn_selected_equities_v3.yaml"
            ).read_text(encoding="utf-8")
        )
        symbols = [str(value).zfill(6) for value in universe.get("symbols", [])]
        assert_shared_provider_coverage(
            args.provider_dir.resolve(), symbols, label="CN x1.2 ledger"
        )
        result = build_cn_x1_2_prospective_ledger(
            repository_root=args.repository_root.resolve(),
            provider_dir=args.provider_dir.resolve(),
            cutoff=args.cutoff,
            output=args.output.resolve(),
        )
    except DataBlockedError as exc:
        print(json.dumps({"data_blocked": str(exc)}, ensure_ascii=False))
        return DATA_BLOCKED_EXIT_CODE
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
