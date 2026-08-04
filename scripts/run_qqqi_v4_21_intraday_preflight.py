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
from src.research.v4_21_state2_intraday_preflight import (
    audit_phase0,
    fetch_intraday_bars,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_state2_intraday_meta_label_v4_21_research.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/qqqi_state2_intraday_meta_label_v4_21_research"
)
BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"


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
    authorized: bool,
) -> None:
    files = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": yaml.safe_load(
            contract_path.read_text(encoding="utf-8")
        )["experiment_id"],
        "phase": 0,
        "contract_path": str(contract_path),
        "contract_sha256": _sha256(contract_path),
        "bridge_contract_path": str(bridge_path),
        "bridge_contract_sha256": _sha256(bridge_path),
        "decision": decision,
        "outcome_calculation_authorized": authorized,
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
            symbols=[str(value) for value in contract["required_daily_symbols"]],
            start=str(contract["daily_data"]["start_date"]),
            end=str(contract["daily_data"]["end_date"]),
            adapter=YFinanceOpenCloseResearchAdapter(),
        )
        daily_coverage["open_close_only_research"] = True
        daily_coverage["synthetic_high_low_used_for_range_features"] = False
        _, actual_results, _, _ = run_bridge_allocation_comparison(
            daily_bars, bridge_contract
        )
        _, proxy_results, _, _ = run_bridge_allocation_comparison(
            alias_qqqi_to_qqq(daily_bars), bridge_contract
        )
        intraday_bars, source_coverage = fetch_intraday_bars(contract)
        result = audit_phase0(
            intraday_bars,
            source_coverage,
            proxy_results[BASELINE_KEY].daily,
            actual_results[BASELINE_KEY].daily,
            contract,
        )
        decision = (
            "intraday_phase0_passed_outcomes_authorized"
            if result.gate["passed"]
            else "intraday_phase0_failed_no_outcomes_authorized"
        )
        daily_coverage.to_csv(output / "daily_source_coverage.csv", index=False)
        result.source_coverage.to_csv(
            output / "intraday_source_coverage.csv", index=False
        )
        result.opening_alignment.reset_index().to_csv(
            output / "opening_alignment.csv", index=False
        )
        result.state2_population.to_csv(
            output / "state2_population.csv", index=False
        )
        diagnostics = {
            "research_only": True,
            "trade_ready": False,
            "phase": 0,
            "decision": decision,
            "phase0_gate": result.gate,
            "outcome_calculation_authorized": bool(result.gate["passed"]),
            "strategy_calculation_performed": False,
            "daily_source_scope": {
                "adapter": "yfinance_open_close_research",
                "provider_adjusted_open_close_preserved": True,
                "high_low_synthetic_envelope_only": True,
                "range_features_authorized": False,
            },
            "v4_2_unchanged": True,
            "telegram_unchanged": True,
            "issue_348_unchanged": True,
        }
        _write_json(output / "diagnostics.json", diagnostics)
        _write_manifest(
            output,
            contract_path=args.contract,
            bridge_path=bridge_path,
            decision=decision,
            authorized=bool(result.gate["passed"]),
        )
        print(
            json.dumps(
                _safe(
                    {
                        "decision": decision,
                        "phase0_gate": result.gate,
                        "output_dir": str(output),
                    }
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        decision = "intraday_phase0_runtime_failure_no_outcomes_authorized"
        failure = {
            "research_only": True,
            "trade_ready": False,
            "phase": 0,
            "decision": decision,
            "outcome_calculation_authorized": False,
            "strategy_calculation_performed": False,
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
            authorized=False,
        )
        print(json.dumps(_safe(failure), ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
