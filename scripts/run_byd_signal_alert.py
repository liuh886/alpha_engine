#!/usr/bin/env python3
"""Generate the formal BYD v1.3 next-open signal decision card."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.factors.strategy_snapshot import build_strategy_factor_snapshot
from src.research.byd_signal_alerts import (
    MODEL_ID,
    _render_markdown,
    _render_telegram,
    build_byd_signal_alert,
)
from src.research.byd_signal_evidence import (
    bind_final_signal_identity,
    bind_manifest_observation_identity,
    close_evidence_is_current,
)

MODEL_FAMILY_ID = "byd_allocation"


def _latest_observation(store_dir: Path) -> dict[str, Any] | None:
    files = sorted((store_dir / "observations").glob("*.json"))
    if not files:
        return None
    raw = files[-1].read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"observation root must be an object: {files[-1]}")
    manifest = json.loads((store_dir / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("BYD source manifest root must be an object")
    return bind_manifest_observation_identity(
        value,
        observation_sha256=hashlib.sha256(raw).hexdigest(),
        manifest=manifest,
    )


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
    (path / "signal_alert.md").write_text(str(alert["markdown"]), encoding="utf-8")
    (path / "signal_alert_telegram.txt").write_text(str(alert["telegram_text"]), encoding="utf-8")


def _github_outputs(path: Path, alert: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"should_alert={str(bool(alert['should_alert'])).lower()}\n")
        handle.write(f"data_freshness_ok={str(bool(alert['data_freshness_ok'])).lower()}\n")
        handle.write(f"factor_freshness_ok={str(bool(alert['factor_freshness_ok'])).lower()}\n")
        handle.write(
            f"open_research_eligible={str(bool(alert['open_research_eligible'])).lower()}\n"
        )
        handle.write(f"fingerprint={alert['fingerprint']}\n")
        handle.write(f"signal_date={alert['signal_date']}\n")
        handle.write(f"title={alert['title']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-store", type=Path, required=True)
    parser.add_argument(
        "--state-store",
        type=Path,
        default=Path(
            "data/research/strategy_signal_ledgers/byd_v1_3_recovery_event_low_vol_confirmation_v1"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/signals/byd_v1_3"),
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    observation = _latest_observation(args.source_store)
    if observation is None:
        raise RuntimeError("missing BYD v1.3 governed source observation")

    alert = build_byd_signal_alert(
        observation,
        previous_alert=_previous_alert(args.state_store),
    )
    alert["data_freshness_ok"] = close_evidence_is_current(observation)
    alert["execution_gate_status"] = (
        "latest_open_confirmed"
        if alert["open_research_eligible"]
        else "awaiting_next_independently_confirmed_open"
    )
    alert["should_alert"] = bool(
        alert["transition_type"] in {"initialize", "rebalance"} and alert["data_freshness_ok"]
    )

    alert["data_provenance"] = {
        "v1_3_source_manifest_sha256": _manifest_sha256(args.source_store),
        "source_observation_sha256": hashlib.sha256(
            json.dumps(
                observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
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

    bind_final_signal_identity(alert)
    alert["markdown"] = _render_markdown(alert)
    alert["telegram_text"] = _render_telegram(alert)

    _write_outputs(args.output_dir, alert)
    if args.github_output is not None:
        _github_outputs(args.github_output, alert)
    print(json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
