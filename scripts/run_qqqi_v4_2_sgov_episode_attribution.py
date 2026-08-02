#!/usr/bin/env python3
"""Run drawdown and recovery attribution for the frozen blended SGOV profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_sgov_defense_experiment import run_sgov_defense_comparison
from src.research.v4_2_sgov_episode_attribution import attribute_sgov_drawdown_episodes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _phase_state_summary(episodes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scope, sample in (
        ("all_episodes", episodes),
        ("major_episodes", episodes.loc[episodes["major_episode"]]),
    ):
        for phase in ("stress", "recovery", "lag"):
            for state in (0, 1, 2):
                column = f"{phase}_state_{state}_log_relative"
                rows.append(
                    {
                        "scope": scope,
                        "phase": phase,
                        "position_state": state,
                        "episode_count": int(len(sample)),
                        "total_log_relative": float(sample[column].sum()),
                        "mean_log_relative": float(sample[column].mean()),
                    }
                )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_sgov_episode_attribution.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/qqqi_qqq_tqqq_v4_2_sgov_episode_attribution"
        ),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    baseline_path = Path(contract["boundaries"]["baseline_contract"])
    sgov_path = Path(contract["boundaries"]["sgov_contract"])
    baseline_contract = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    sgov_contract = yaml.safe_load(sgov_path.read_text(encoding="utf-8"))

    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(contract["data"]["required_symbols"])),
        start=contract["data"]["start_date"],
        end=args.end_date or contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    headline, results, chronological, inherited = run_sgov_defense_comparison(
        bars, baseline_contract, sgov_contract
    )
    baseline_key = contract["boundaries"]["baseline_variant"]
    challenger_key = contract["boundaries"]["challenger_variant"]
    episodes, gate = attribute_sgov_drawdown_episodes(
        results[baseline_key], results[challenger_key], contract
    )
    phase_state = _phase_state_summary(episodes)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    headline.to_csv(output / "headline_metrics.csv")
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    episodes.to_csv(output / "drawdown_episode_attribution.csv", index=False)
    episodes.loc[episodes["major_episode"]].sort_values("severity_rank").to_csv(
        output / "major_drawdown_episodes.csv", index=False
    )
    phase_state.to_csv(output / "phase_state_log_relative_contribution.csv", index=False)

    summary = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "parent_experiment_id": contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contracts": {
            "attribution": {"path": str(args.contract), "sha256": _sha256(args.contract)},
            "baseline": {"path": str(baseline_path), "sha256": _sha256(baseline_path)},
            "sgov": {"path": str(sgov_path), "sha256": _sha256(sgov_path)},
        },
        "headline_metrics": headline.reset_index().to_dict(orient="records"),
        "inherited_sgov_diagnostics": inherited,
        "episode_count": int(len(episodes)),
        "major_episode_count": int(episodes["major_episode"].sum()),
        "major_episodes": episodes.loc[episodes["major_episode"]]
        .sort_values("severity_rank")
        .to_dict(orient="records"),
        "phase_state_contribution": phase_state.to_dict(orient="records"),
        "prospective_monitor_gate": gate,
        "decision": gate["decision"],
    }
    summary_path = output / "experiment_summary.json"
    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "outputs": {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
        },
    }
    (output / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
