from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.adapters.yfinance_open_close_research_adapter import (
    YFinanceOpenCloseResearchAdapter,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.v4_25_new_information_phase0 import run_new_information_phase0

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/qqqi_xgb_new_information_v4_25_phase0.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_xgb_new_information_v4_25_phase0"
)


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_safe(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(result: Any) -> str:
    lines = [
        "# v4.25 XGBoost new-information Phase 0",
        "",
        f"Decision: `{result.decision}`",
        "",
        "This phase audits source identity, public-history continuity, publication timing, revision risk and licensing. It performs no outcome calculation, XGBoost fitting, action selection or portfolio construction.",
        "",
        "## Source audit",
        "",
        "| Source | Family | First | Last | Coverage | Max gap | Revision | Admissible | Rejection |",
        "|---|---|---|---|---:|---:|---|---|---|",
    ]
    for row in result.source_audit.itertuples(index=False):
        lines.append(
            f"| {row.source_id} | {row.family} | {row.first_observation_date or 'n/a'}"
            + f" | {row.last_observation_date or 'n/a'}"
            + f" | {float(row.decision_date_coverage):.2%}"
            + f" | {row.maximum_unexplained_gap_sessions if row.maximum_unexplained_gap_sessions is not None else 'n/a'}"
            + f" | {row.revision_classification} | {bool(row.admissible)}"
            + f" | {row.rejection_reason or ''} |"
        )
    lines.extend(
        [
            "",
            "## Family decisions",
            "",
            "| Family | Admissible | Rejected sources | Reason |",
            "|---|---|---|---|",
        ]
    )
    for row in result.family_audit.itertuples(index=False):
        lines.append(
            f"| {row.family} | {bool(row.admissible)} | {row.rejected_sources}"
            + f" | {row.rejection_reason or ''} |"
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            f"- admitted families: {list(result.admitted_families)};",
            "- outcome calculation authorized: false;",
            "- XGBoost training performed: false;",
            "- future returns and path utility present: false;",
            "- v4.2, Telegram and Issue #348 unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    bars, qqq_coverage = fetch_adjusted_daily_bars(
        symbols=[str(contract["qqq_calendar"]["symbol"])],
        start=str(contract["qqq_calendar"]["start_date"]),
        end=args.end_date or None,
        adapter=YFinanceOpenCloseResearchAdapter(),
    )
    qqq_calendar = pd.DatetimeIndex(pd.to_datetime(bars["QQQ"]["date"]))
    result = run_new_information_phase0(qqq_calendar, contract)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    qqq_coverage.to_csv(output / "qqq_calendar_coverage.csv", index=False)
    result.source_audit.to_csv(output / "source_audit.csv", index=False)
    result.family_audit.to_csv(output / "family_audit.csv", index=False)
    result.fold_coverage.to_csv(output / "fold_coverage.csv", index=False)
    result.normalized_availability.to_csv(
        output / "normalized_availability.csv", index=False
    )
    result.source_identity.to_csv(output / "source_identity.csv", index=False)
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "phase": 0,
        "decision": result.decision,
        "admitted_families": result.admitted_families,
        "outcome_calculation_authorized": False,
        "xgboost_training_performed": False,
        "future_returns_present": False,
        "path_utility_present": False,
        "action_selection_performed": False,
        "portfolio_constructed": False,
        "v4_2_unchanged": True,
        "telegram_unchanged": True,
        "issue_348_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)
    (output / "report.md").write_text(_report(result), encoding="utf-8")
    files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": contract["experiment_id"],
        "phase": 0,
        "research_only": True,
        "trade_ready": False,
        "outcome_calculation_authorized": False,
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "decision": result.decision,
        "admitted_families": result.admitted_families,
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)
    print(json.dumps(_safe(diagnostics), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
