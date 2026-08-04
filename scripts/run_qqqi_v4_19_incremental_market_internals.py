from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars
from src.research.v4_19_incremental_market_internals import (
    run_market_internal_research,
)
from src.research.v4_2_qqq_proxy_long_history_experiment import alias_qqqi_to_qqq
from src.research.vxn_bridge_allocation_experiment import (
    run_bridge_allocation_comparison,
)

DEFAULT_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_market_internal_incremental_factors_v4_19_research.yaml"
)
DEFAULT_BASE_CONTRACT = Path(
    "configs/research_paradigms/"
    "qqqi_tqqq_sgov_voo_action_advantage_v4_16_research.yaml"
)
DEFAULT_BRIDGE_CONTRACT = Path(
    "configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evidence/"
    "qqqi_market_internal_incremental_factors_v4_19_research"
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


def _all_symbols(contract: dict[str, Any]) -> list[str]:
    symbols = {
        str(value).upper()
        for value in contract["data"]["existing_required_symbols"]
    }
    for values in contract["data"]["candidate_symbols"].values():
        symbols.update(str(value).upper() for value in values)
    return sorted(symbols)


def _fetch_individually(
    symbols: list[str],
    *,
    start: str,
    end: str | None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, str]]:
    bars: dict[str, pd.DataFrame] = {}
    coverage_parts: list[pd.DataFrame] = []
    errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            fetched, coverage = fetch_adjusted_daily_bars(
                symbols=[symbol], start=start, end=end
            )
            bars.update(fetched)
            coverage_parts.append(coverage)
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
    combined = (
        pd.concat(coverage_parts, ignore_index=True)
        if coverage_parts
        else pd.DataFrame(
            columns=[
                "symbol",
                "provider",
                "provider_symbol",
                "first_date",
                "last_date",
                "rows",
            ]
        )
    )
    return bars, combined, errors


def _decision(result: Any) -> str:
    if not result.final_gate["checks"]["phase_0_completed"]:
        return "market_internal_phase_0_incomplete"
    if not result.admitted_families:
        return "no_incremental_market_internal_family_admitted"
    return "incremental_families_admitted_to_separate_phase_2_only"


def _save_family(output: Path, family: str, evaluation: Any) -> None:
    prefix = output / family
    prefix.mkdir(parents=True, exist_ok=True)
    evaluation.feature_frame.reset_index(names="date").to_csv(
        prefix / "feature_frame.csv", index=False
    )
    evaluation.predictions.reset_index(names="date").to_csv(
        prefix / "oof_predictions.csv", index=False
    )
    evaluation.action_metrics.to_csv(prefix / "action_metrics.csv", index=False)
    evaluation.action_state_metrics.to_csv(
        prefix / "action_state_metrics.csv", index=False
    )
    evaluation.fold_metrics.to_csv(prefix / "fold_metrics.csv", index=False)
    evaluation.fold_coefficients.to_csv(
        prefix / "fold_coefficients.csv", index=False
    )
    evaluation.coefficient_cosines.to_csv(
        prefix / "coefficient_cosines.csv", index=False
    )
    evaluation.source_fold_coverage.to_csv(
        prefix / "source_fold_coverage.csv", index=False
    )
    _write_json(
        prefix / "gate.json",
        {
            "family": family,
            "admissible": evaluation.admissible,
            "rejection_reason": evaluation.rejection_reason,
            "feature_names": evaluation.feature_names,
            "raw_pvalue": evaluation.raw_pvalue,
            "qvalue": evaluation.qvalue,
            "gate": evaluation.gate,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--base-contract", type=Path, default=DEFAULT_BASE_CONTRACT
    )
    parser.add_argument(
        "--bridge-contract", type=Path, default=DEFAULT_BRIDGE_CONTRACT
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    base_contract = yaml.safe_load(
        args.base_contract.read_text(encoding="utf-8")
    )
    bridge_contract = yaml.safe_load(
        args.bridge_contract.read_text(encoding="utf-8")
    )
    symbols = _all_symbols(contract)
    bars, coverage, fetch_errors = _fetch_individually(
        symbols,
        start=str(contract["data"]["start_date"]),
        end=args.end_date or contract["data"].get("end_date"),
    )
    required = {
        str(value).upper()
        for value in contract["data"]["existing_required_symbols"]
    }
    missing_required = sorted(required - set(bars))
    if missing_required:
        details = {
            symbol: fetch_errors.get(symbol, "missing")
            for symbol in missing_required
        }
        raise RuntimeError(
            f"existing required sources unavailable: {details}"
        )

    _, proxy_results, _, _ = run_bridge_allocation_comparison(
        alias_qqqi_to_qqq(bars), bridge_contract
    )
    result = run_market_internal_research(
        bars,
        coverage,
        fetch_errors,
        proxy_results[BASELINE_KEY].daily,
        contract,
        base_contract,
    )
    decision = _decision(result)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    result.source_audit.to_csv(output / "source_audit.csv", index=False)
    result.family_source_audit.to_csv(
        output / "family_source_audit.csv", index=False
    )
    result.fdr_table.to_csv(output / "family_fdr.csv", index=False)
    result.base_frame.reset_index(names="date").to_csv(
        output / "base_feature_label_frame.csv", index=False
    )
    for family, evaluation in result.family_results.items():
        _save_family(output, family, evaluation)

    summary_rows = []
    for family, evaluation in result.family_results.items():
        metrics = evaluation.gate.get("metrics", {})
        summary_rows.append(
            {
                "family": family,
                "source_admissible": evaluation.admissible,
                "rejection_reason": evaluation.rejection_reason,
                "raw_pvalue": evaluation.raw_pvalue,
                "qvalue": evaluation.qvalue,
                "actions_ic_improvement": metrics.get(
                    "actions_ic_improvement"
                ),
                "actions_quintile_spread_improvement": metrics.get(
                    "actions_quintile_spread_improvement"
                ),
                "action_state_cells_ic_improvement": metrics.get(
                    "action_state_cells_ic_improvement"
                ),
                "coefficient_cosine_similarity_median": metrics.get(
                    "coefficient_cosine_similarity_median"
                ),
                "positive_outer_eras": metrics.get("positive_outer_eras"),
                "admitted": bool(evaluation.gate.get("passed", False)),
            }
        )
    pd.DataFrame(summary_rows).to_csv(
        output / "family_summary.csv", index=False
    )
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "phase": "phase_0_and_phase_1",
        "decision": decision,
        "admitted_families": result.admitted_families,
        "final_gate": result.final_gate,
        "family_gates": {
            family: evaluation.gate
            for family, evaluation in result.family_results.items()
        },
        "portfolio_policy_evaluated": False,
        "shadow_candidate_authorized": False,
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    _write_json(output / "diagnostics.json", diagnostics)

    files = sorted(
        path
        for path in output.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "phase": "phase_0_and_phase_1",
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "base_contract_path": str(args.base_contract),
        "base_contract_sha256": _sha256(args.base_contract),
        "bridge_contract_path": str(args.bridge_contract),
        "bridge_contract_sha256": _sha256(args.bridge_contract),
        "decision": decision,
        "admitted_families": result.admitted_families,
        "portfolio_policy_evaluated": False,
        "files": {
            str(path.relative_to(output)): _sha256(path) for path in files
        },
    }
    _write_json(output / "manifest.json", manifest)
    print(
        json.dumps(
            _safe(
                {
                    "decision": decision,
                    "admitted_families": result.admitted_families,
                    "final_gate": result.final_gate,
                    "source_errors": fetch_errors,
                    "output_dir": str(output),
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
