from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.adapters.yfinance_open_close_research_adapter import (
    YFinanceOpenCloseResearchAdapter,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.v4_21_state2_intraday_preflight import fetch_intraday_bars
from src.research.v4_22_intraday_rank_pilot import run_intraday_rank_pilot
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/qqqi_state2_intraday_rank_pilot_v4_22_research.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_state2_intraday_rank_pilot_v4_22_research"
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


def _write_manifest(
    output: Path,
    *,
    contract_path: Path,
    bridge_path: Path,
    decision: str,
) -> None:
    files = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    manifest = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "pilot_only": True,
        "shadow_authorization_possible": False,
        "contract_path": str(contract_path),
        "contract_sha256": _sha256(contract_path),
        "bridge_contract_path": str(bridge_path),
        "bridge_contract_sha256": _sha256(bridge_path),
        "decision": decision,
        "files": {path.name: _sha256(path) for path in files},
    }
    _write_json(output / "manifest.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    bridge_path = Path(contract["daily_data"]["bridge_contract"])
    bridge_contract = yaml.safe_load(bridge_path.read_text(encoding="utf-8"))
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    try:
        daily_bars, daily_coverage = fetch_adjusted_daily_bars(
            symbols=[str(value) for value in contract["daily_data"]["required_symbols"]],
            start=str(contract["daily_data"]["start_date"]),
            end=str(contract["daily_data"]["end_date"]),
            adapter=YFinanceOpenCloseResearchAdapter(),
        )
        _, results, _, _ = run_bridge_allocation_comparison(
            daily_bars, bridge_contract
        )
        baseline = results[str(contract["daily_data"]["baseline_result_key"])]
        intraday_bars, intraday_coverage = fetch_intraday_bars(contract)
        if not bool(intraday_coverage["admissible"].fillna(False).all()):
            raise ValueError("one or more governed intraday sources are inadmissible")
        result = run_intraday_rank_pilot(
            intraday_bars,
            daily_bars,
            baseline.daily,
            contract,
        )

        daily_coverage.to_csv(output / "daily_source_coverage.csv", index=False)
        intraday_coverage.to_csv(
            output / "intraday_source_coverage.csv", index=False
        )
        result.frame.reset_index().to_csv(
            output / "feature_label_frame.csv", index=False
        )
        result.predictions.reset_index().to_csv(
            output / "oof_predictions.csv", index=False
        )
        result.fold_coverage.to_csv(output / "fold_coverage.csv", index=False)
        result.fold_coefficients.to_csv(
            output / "fold_coefficients.csv", index=False
        )
        result.coefficient_cosines.to_csv(
            output / "coefficient_cosines.csv", index=False
        )
        result.triggered_events.reset_index().to_csv(
            output / "triggered_events.csv", index=False
        )
        result.placebo_paths.to_csv(output / "placebo_paths.csv", index=False)
        result.strategy_metrics.to_csv(output / "strategy_metrics.csv")
        for name, daily in result.strategy_daily.items():
            daily.reset_index().to_csv(
                output / f"{name}_daily.csv", index=False
            )
        diagnostics = {
            "research_only": True,
            "trade_ready": False,
            "pilot_only": True,
            "shadow_authorization_possible": False,
            "decision": result.decision,
            "feature_names": list(result.feature_names),
            "score_metrics": result.score_metrics,
            "feasibility_gate": result.feasibility_gate,
            "tail_metrics": result.tail_metrics,
            "tail_and_path_gate": result.tail_and_path_gate,
            "v4_2_unchanged": True,
            "telegram_unchanged": True,
            "issue_348_unchanged": True,
        }
        _write_json(output / "diagnostics.json", diagnostics)
        _write_manifest(
            output,
            contract_path=args.contract,
            bridge_path=bridge_path,
            decision=result.decision,
        )
        print(json.dumps(_safe(diagnostics), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        decision = "intraday_rank_pilot_runtime_failure_no_claim_authorized"
        failure = {
            "research_only": True,
            "trade_ready": False,
            "pilot_only": True,
            "shadow_authorization_possible": False,
            "decision": decision,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "v4_2_unchanged": True,
            "telegram_unchanged": True,
            "issue_348_unchanged": True,
        }
        _write_json(output / "diagnostics.json", failure)
        (output / "failure_traceback.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        _write_manifest(
            output,
            contract_path=args.contract,
            bridge_path=bridge_path,
            decision=decision,
        )
        print(json.dumps(_safe(failure), ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
