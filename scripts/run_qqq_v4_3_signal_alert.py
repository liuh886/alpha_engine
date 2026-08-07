#!/usr/bin/env python3
"""Generate the formal QQQ Rotation v4.3 next-open signal card."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.qqq_v4_3_signal_alerts import build_v4_3_signal_alert


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/evidence/qqq_rotation_v4_3_current_monitor/current_summary.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/signals/qqq_rotation_v4_3"),
    )
    parser.add_argument("--github-output", type=Path, default=None)
    args = parser.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    alert = build_v4_3_signal_alert(summary)
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
            handle.write(f"should_alert={str(bool(alert['should_alert'])).lower()}\n")
            handle.write(
                "data_freshness_ok="
                f"{str(bool(alert['data_freshness_ok'])).lower()}\n"
            )
            handle.write(f"fingerprint={alert['fingerprint']}\n")
            handle.write(f"title={alert['title']}\n")
            handle.write(f"telegram_path={telegram_path}\n")
    print(json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
