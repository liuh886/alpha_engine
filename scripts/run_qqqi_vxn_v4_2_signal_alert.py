#!/usr/bin/env python3
"""Generate a deduplicatable v4.2 next-open signal decision card."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from src.research.strategy_signal_alerts import build_signal_alert


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_vxn_bridge_v4_2_prospective_monitor/"
            "prospective_summary.json"
        ),
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
        ),
    )
    parser.add_argument(
        "--baseline-policy",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_current_baseline.yaml"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/signals/qqqi_qqq_tqqq_vxn_bridge_v4_2"),
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="Optional GitHub Actions output file.",
    )
    args = parser.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    baseline_policy = yaml.safe_load(
        args.baseline_policy.read_text(encoding="utf-8")
    )
    alert = build_signal_alert(summary, contract, baseline_policy)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "signal_alert.json"
    markdown_path = output / "signal_alert.md"
    telegram_path = output / "signal_alert_telegram.txt"
    json_path.write_text(
        json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(str(alert["markdown"]), encoding="utf-8")
    telegram_path.write_text(str(alert["telegram_text"]), encoding="utf-8")

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(
                f"should_alert={str(bool(alert['should_alert'])).lower()}\n"
            )
            handle.write(
                "data_freshness_ok="
                f"{str(bool(alert['data_freshness_ok'])).lower()}\n"
            )
            handle.write(f"fingerprint={alert['fingerprint']}\n")
            handle.write(f"title={alert['title']}\n")
            handle.write(f"json_path={json_path}\n")
            handle.write(f"markdown_path={markdown_path}\n")
            handle.write(f"telegram_path={telegram_path}\n")

    print(json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
