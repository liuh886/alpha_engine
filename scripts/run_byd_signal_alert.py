#!/usr/bin/env python3
"""Generate a deduplicatable BYD v1.2 next-open signal decision card.

Reads the latest observations from the three BYD prospective stores, composes
the combined V1.0 + V1.2 target weights, and produces a signal alert card
suitable for GitHub Issue and Telegram delivery.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.research.byd_signal_alerts import build_byd_signal_alert


def _latest_observation(store_dir: Path) -> dict | None:
    """Return the latest observation JSON from a prospective store."""
    obs_dir = store_dir / "observations"
    if not obs_dir.exists():
        return None
    files = sorted(obs_dir.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def _latest_observation_date(store_dir: Path) -> str | None:
    files = sorted((store_dir / "observations").glob("*.json"))
    return files[-1].stem if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shadow-store", type=Path, required=True,
        help="Path to byd_prospective_shadow directory",
    )
    parser.add_argument(
        "--paired-store", type=Path, required=True,
        help="Path to byd_515180_prospective directory",
    )
    parser.add_argument(
        "--expansion-store", type=Path, required=True,
        help="Path to byd_v1_2_trend_expansion_prospective directory",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("artifacts/signals/byd_v1_2"),
    )
    parser.add_argument(
        "--github-output", type=Path, default=None,
        help="Optional GitHub Actions output file",
    )
    args = parser.parse_args()

    # Load latest observations from all three layers
    shadow_obs = _latest_observation(args.shadow_store)
    paired_obs = _latest_observation(args.paired_store)
    expansion_obs = _latest_observation(args.expansion_store)

    if shadow_obs is None:
        print("No BYD shadow observations available — skipping signal alert")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as h:
                h.write("should_alert=false\n")
                h.write("data_freshness_ok=false\n")
                h.write("reason=no_shadow_observations\n")
        return 0

    # Determine previous state from existing signal artifacts
    previous_state = None
    prev_alert_path = args.output_dir / "signal_alert.json"
    if prev_alert_path.exists():
        prev = json.loads(prev_alert_path.read_text(encoding="utf-8"))
        previous_state = prev.get("target_state")

    # Check data freshness: all three layers must agree on latest date
    shadow_date = _latest_observation_date(args.shadow_store)
    paired_date = _latest_observation_date(args.paired_store)
    expansion_date = _latest_observation_date(args.expansion_store)
    dates_agree = shadow_date == paired_date == expansion_date
    if not dates_agree and previous_state is not None:
        print(f"Data date mismatch: shadow={shadow_date} paired={paired_date} expansion={expansion_date}")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as h:
                h.write("should_alert=false\n")
                h.write("data_freshness_ok=false\n")
                h.write("reason=date_mismatch\n")
        return 0

    alert = build_byd_signal_alert(
        shadow_obs,
        paired_obs,
        expansion_obs,
        previous_state=previous_state,
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "signal_alert.json"
    md_path = output / "signal_alert.md"
    tg_path = output / "signal_alert_telegram.txt"

    json_path.write_text(
        json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(str(alert["markdown"]), encoding="utf-8")
    tg_path.write_text(str(alert["telegram_text"]), encoding="utf-8")

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"should_alert={str(bool(alert['should_alert'])).lower()}\n")
            handle.write(f"data_freshness_ok={str(bool(alert['data_freshness_ok'])).lower()}\n")
            handle.write(f"fingerprint={alert['fingerprint']}\n")
            handle.write(f"title={alert['title']}\n")
            handle.write(f"json_path={json_path}\n")
            handle.write(f"markdown_path={md_path}\n")
            handle.write(f"telegram_path={tg_path}\n")

    print(json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
