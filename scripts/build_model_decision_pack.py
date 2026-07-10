"""Render a legacy decision pack from one canonical PromotionDecision artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.research.model_decision_pack import render_model_decision_markdown
from src.research.promotion_consumers import (
    build_model_decision_pack_view,
    load_promotion_payload,
)

DEFAULT_INPUT = Path(
    "artifacts/research_runs/cn_10d_csi300_baseline/promotion_decision.json"
)


def render_decision_pack(
    input_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Render compatibility files without recomputing promotion gates."""

    promotion = load_promotion_payload(input_path)
    pack = build_model_decision_pack_view(promotion)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / "model_decision_pack.json"
    markdown_path = target_dir / "model_decision_pack.md"
    json_path.write_text(
        json.dumps(pack, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_model_decision_markdown(pack),
        encoding="utf-8",
    )
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "decision": dict(pack["decision"]),
        "decision_source": "promotion_decision",
        "may_recompute_decision": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to promotion_decision.json or its containing run directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory; defaults to the promotion artifact directory.",
    )
    args = parser.parse_args()
    input_path = args.input
    output_dir = args.output_dir or (
        input_path if input_path.is_dir() else input_path.parent
    )
    print(
        json.dumps(
            render_decision_pack(input_path, output_dir),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
