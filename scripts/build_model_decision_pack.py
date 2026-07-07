"""Build a 10D model decision pack from a walk-forward stability summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.model_decision_pack import build_model_decision_pack, render_model_decision_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("artifacts/evidence/stable_signal_blend/walk_forward_stability.json"),
        help="Path to a walk_forward_stability.json file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/model_decision_pack"),
    )
    args = parser.parse_args()

    summary = json.loads(args.input.read_text(encoding="utf-8"))
    pack = build_model_decision_pack(summary)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "model_decision_pack.json"
    md_path = args.output_dir / "model_decision_pack.md"
    json_path.write_text(json.dumps(pack, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_model_decision_markdown(pack), encoding="utf-8")
    print(json.dumps({"json_path": str(json_path), "markdown_path": str(md_path), "decision": pack["decision"]}, indent=2))


if __name__ == "__main__":
    main()
