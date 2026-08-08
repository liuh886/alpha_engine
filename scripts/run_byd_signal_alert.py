#!/usr/bin/env python3
"""Generate the formal BYD v1.2 next-open signal decision card."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.factors.strategy_snapshot import build_strategy_factor_snapshot
from src.research.byd_signal_alerts import MODEL_ID, build_byd_signal_alert

MODEL_FAMILY_ID = "byd_allocation"


def _latest_observation(store_dir: Path) -> dict[str, Any] | None:
    files = sorted((store_dir / "observations").glob("*.json"))
    if not files:
        return None
    value = json.loads(files[-1].read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"observation root must be an object: {files[-1]}")
    return value


def _previous_alert(state_store: Path) -> dict[str, Any] | None:
    path = state_store / "latest.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("BYD signal latest record must be an object")
    if value.get("model_version_id") != MODEL_ID:
        raise ValueError("BYD signal latest record has the wrong model identity")
    signal = value.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("BYD signal latest record has no governed signal payload")
    return signal


def _manifest_sha256(store_dir: Path) -> str:
    path = store_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing prospective store manifest: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_outputs(path: Path, alert: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "signal_alert.json").write_text(
        json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (path / "signal_alert.md").write_text(
        str(alert["markdown"]),
        encoding="utf-8",
    )
    (path / "signal_alert_telegram.txt").write_text(
        str(alert["telegram_text"]),
        encoding="utf-8",
    )


def _github_outputs(path: Path, alert: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"should_alert={str(bool(alert['should_alert'])).lower()}\n")
        handle.write(
            f"data_freshness_ok={str(bool(alert['data_freshness_ok'])).lower()}\n"
        )
        handle.write(
            f"factor_freshness_ok={str(bool(alert['factor_freshness_ok'])).lower()}\n"
        )
        handle.write(
            f"open_research_eligible={str(bool(alert['open_research_eligible'])).lower()}\n"
        )
        handle.write(f"fingerprint={alert['fingerprint']}\n")
        handle.write(f"signal_date={alert['signal_date']}\n")
        handle.write(f"title={alert['title']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shadow-store", type=Path, required=True)
    parser.add_argument("--paired-store", type=Path, required=True)
    parser.add_argument("--expansion-store", type=Path, required=True)
    parser.add_argument(
        "--state-store",
        type=Path,
        default=Path(
            "data/research/strategy_signal_ledgers/"
            "byd_v1_2_convex_momentum_budget_v1"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/signals/byd_v1_2"),
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    shadow = _latest_observation(args.shadow_store)
    paired = _latest_observation(args.paired_store)
    expansion = _latest_observation(args.expansion_store)
    if shadow is None or paired is None or expansion is None:
        missing = [
            name
            for name, value in (
                ("shadow", shadow),
                ("paired", paired),
                ("expansion", expansion),
            )
            if value is None
        ]
        raise RuntimeError(f"missing BYD signal source observations: {missing}")

    dates = {
        str(shadow.get("signal_date", "")),
        str(paired.get("signal_date", "")),
        str(expansion.get("signal_date", "")),
    }
    if len(dates) != 1 or "" in dates:
        raise RuntimeError(f"BYD signal source date mismatch: {sorted(dates)}")

    alert = build_byd_signal_alert(
        shadow,
        paired,
        expansion,
        previous_alert=_previous_alert(args.state_store),
    )
    alert["data_provenance"] = {
        "shadow_manifest_sha256": _manifest_sha256(args.shadow_store),
        "paired_manifest_sha256": _manifest_sha256(args.paired_store),
        "expansion_manifest_sha256": _manifest_sha256(args.expansion_store),
        "source_workflow": "byd-daily-signal-alert",
    }
    factor_evidence = build_strategy_factor_snapshot(
        model_family_id=MODEL_FAMILY_ID,
        signal=alert,
    )
    alert["factor_evidence"] = factor_evidence
    alert["factor_freshness_ok"] = factor_evidence["freshness"] == "current"
    if not alert["factor_freshness_ok"]:
        alert["should_alert"] = False

    _write_outputs(args.output_dir, alert)
    if args.github_output is not None:
        _github_outputs(args.github_output, alert)
    print(json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
