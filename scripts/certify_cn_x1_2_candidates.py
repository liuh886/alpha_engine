"""Corrected CN x1.2 candidate certification.

This runner intentionally replaces the invalid PR #765 Phase C shortcuts:
- canonical sector-hierarchical selection (no global Top-K fallback),
- transaction costs charged from actual weight turnover,
- the full CN x1.1 regime/fallback contract as incumbent control,
- a separate always-on diagnostic for the original c_lower_lr__sp_s3_n1 idea.

The run can nominate a research candidate. It cannot promote a formal or
trade-ready baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from src.research.cn130_cross_sectional_ranking import (
    build_feature_matrices,
    forward_returns,
    load_provider_panel,
    stack_return_frame,
)
from src.research.cn130_tail_factor_discovery import PortfolioVariant, run_portfolio
from src.research.cn_x1_1_regime_gated import build_regime_state, run_regime_portfolio
from src.research.daily_ranker import prepare_ranker_frame
from src.research.rolling_windows import purge_training_tail
from src.research.window_policy import (
    ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
    build_window_sampling_plan,
    horizon_eligible_dates_by_window,
)
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)

CONTRACT_PATH = Path("configs/research_experiments/cn_x1_2_corrected_certification_v1.yaml")
REVERSE_WINDOWS = ("2022H2", "2023H1", "2023H2")
DEVELOPMENT_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
REPORTING_WINDOWS = ("2026H1", "2026H2_PARTIAL")
HISTORICAL_WINDOWS = REVERSE_WINDOWS + DEVELOPMENT_WINDOWS
ALL_WINDOWS = HISTORICAL_WINDOWS + REPORTING_WINDOWS


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ledger_sha256(frame: pd.DataFrame) -> str:
    columns = ["window", "datetime", "instrument", "score", "execution_forward_return"]
    normalized = frame.loc[:, columns].copy()
    normalized["datetime"] = pd.to_datetime(normalized["datetime"]).dt.strftime("%Y-%m-%d")
    normalized = normalized.sort_values(
        ["window", "datetime", "instrument"], kind="mergesort"
    )
    return _sha256_text(normalized.to_csv(index=False, float_format="%.12g"))


def _load_contract(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / CONTRACT_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CN x1.2 certification contract must be a mapping")
    if payload.get("status") != "preregistered":
        raise ValueError("CN x1.2 certification contract is not preregistered")
    return payload


def _calibration(raw: Mapping[str, Any]) -> XGBNativeCalibration:
    fields = {
        "n_gain_bins",
        "num_boost_round",
        "max_leaves",
        "max_depth",
        "min_child_weight",
        "learning_rate",
        "subsample",
        "colsample_bytree",
        "reg_alpha",
        "reg_lambda",
        "seed",
    }
    return XGBNativeCalibration.from_dict({key: raw[key] for key in fields})


def _provider_identity(provider_dir: Path) -> dict[str, Any]:
    candidates = (
        provider_dir / "provider_manifest.json",
        provider_dir / "artifacts/selected_pool_price_refresh_manifest.json",
    )
    for path in candidates:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            identity = payload.get("provider_identity_sha256")
            cutoff = (
                payload.get("calendar", {}).get("last_day")
                if isinstance(payload.get("calendar"), dict)
                else payload.get("cutoff")
            )
            return {
                "manifest_path": str(path),
                "manifest_sha256": _sha256_file(path),
                "provider_identity_sha256": identity,
                "cutoff": cutoff,
            }
    return {
        "manifest_path": "",
        "manifest_sha256": "",
        "provider_identity_sha256": "",
        "cutoff": "",
    }


def _load_universe_and_classification(
    root: Path, contract: Mapping[str, Any]
) -> tuple[list[str], dict[str, dict[str, str]]]:
    universe_payload = yaml.safe_load(
        (root / str(contract["provider"]["universe"])).read_text(encoding="utf-8")
    )
    classification_payload = yaml.safe_load(
        (root / str(contract["provider"]["classification"])).read_text(encoding="utf-8")
    )
    symbols = [str(value).zfill(6) for value in universe_payload["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise ValueError("CN130 universe identity is not exact")
    raw = classification_payload["symbols"]
    classification = {
        str(symbol).zfill(6): {
            "entity": str(meta["entity"]),
            "sector": str(meta["sector"]),
            "industry": str(meta["industry"]),
        }
        for symbol, meta in raw.items()
    }
    if set(symbols) != set(classification):
        raise ValueError("CN130 classification does not match the selected universe")
    return symbols, classification


def _build_window_plan(
    calendar: pd.DatetimeIndex,
    *,
    cutoff: str,
) -> tuple[dict[str, Any], dict[str, pd.DatetimeIndex]]:
    plan = build_window_sampling_plan(
        calendar,
        "2021-01-01",
        cutoff,
        first_test_year=2022,
        last_test_year=2026,
        min_complete_windows=1,
        partial_window_policy=ALLOW_HORIZON_CONTAINED_PARTIAL_FINAL_WINDOW,
        min_partial_window_eligible_sessions=10,
        horizon_sessions=10,
        cadence_sessions=10,
    )
    eligible = horizon_eligible_dates_by_window(plan, calendar)
    windows: dict[str, Any] = {}
    dates: dict[str, pd.DatetimeIndex] = {}
    for window in plan.selected_windows:
        label = "2026H2_PARTIAL" if window.label == "2026H2" else window.label
        if label not in ALL_WINDOWS:
            continue
        windows[label] = window
        dates[label] = eligible[window.label]
    missing = sorted(set(ALL_WINDOWS) - set(windows))
    if missing:
        raise ValueError(f"certification windows unavailable: {missing}")
    return windows, dates


def _predict_scores(
    calibration: XGBNativeCalibration,
    train_features: pd.DataFrame,
    train_returns: pd.DataFrame,
    test_features: pd.DataFrame,
) -> pd.DataFrame:
    x_train, y_train, groups = prepare_ranker_frame(train_features, train_returns)
    fitted = fit_xgb_native_daily_ranker(
        x_train,
        y_train,
        groups,
        calibration=calibration,
    )
    finite = test_features.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        raise ValueError("no finite OOS feature rows")
    return predict_xgb_native_daily_ranker(fitted, finite)


def _ledger_for_scores(
    scores: pd.DataFrame,
    execution_returns: pd.DataFrame,
    classification: Mapping[str, Mapping[str, str]],
    *,
    window: str,
) -> pd.DataFrame:
    joined = scores.rename(columns={scores.columns[0]: "score"}).join(
        execution_returns.rename(
            columns={execution_returns.columns[0]: "execution_forward_return"}
        ),
        how="left",
    )
    joined = joined.reset_index()
    joined["instrument"] = joined["instrument"].astype(str).str.zfill(6)
    joined["window"] = window
    joined["entity"] = joined["instrument"].map(
        lambda symbol: classification[symbol]["entity"]
    )
    joined["sector"] = joined["instrument"].map(
        lambda symbol: classification[symbol]["sector"]
    )
    joined["industry"] = joined["instrument"].map(
        lambda symbol: classification[symbol]["industry"]
    )
    return joined.sort_values(
        ["datetime", "score", "instrument"],
        ascending=[True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _build_ranker_ledgers(
    panel: Any,
    symbols: Sequence[str],
    classification: Mapping[str, Mapping[str, str]],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    features, _ = build_feature_matrices(
        panel,
        symbols=symbols,
        benchmark=str(contract["benchmark"]),
    )
    feature_frame = features["current_cn_ohlcv"]
    if feature_frame.shape[1] != 14:
        raise ValueError("current_cn_ohlcv no longer contains 14 factors")

    close = panel.fields["close"].loc[:, list(symbols)]
    raw_returns = stack_return_frame(
        forward_returns(close, horizon=10, delay=0),
        "raw_forward_return",
    )
    execution_returns = stack_return_frame(
        forward_returns(close, horizon=10, delay=1),
        "execution_forward_return",
    )

    cutoff = str(contract["provider"]["cutoff"])
    windows, dates_by_window = _build_window_plan(panel.calendar, cutoff=cutoff)
    standard = _calibration(contract["rankers"]["incumbent_r0"])
    lower = _calibration(contract["rankers"]["lower_lr"])

    standard_parts: list[pd.DataFrame] = []
    lower_parts: list[pd.DataFrame] = []
    window_evidence: list[dict[str, Any]] = []

    all_dates = feature_frame.index.get_level_values("datetime")
    return_dates = raw_returns.index.get_level_values("datetime")
    for label in ALL_WINDOWS:
        window = windows[label]
        eval_dates = dates_by_window[label]
        train_mask = (
            (all_dates >= pd.Timestamp(window.train_start))
            & (all_dates <= pd.Timestamp(window.train_end))
        )
        return_mask = (
            (return_dates >= pd.Timestamp(window.train_start))
            & (return_dates <= pd.Timestamp(window.train_end))
        )
        train_features = feature_frame.loc[train_mask].copy()
        train_returns = raw_returns.loc[return_mask].copy()
        train_features, train_returns = purge_training_tail(
            train_features,
            train_returns,
            holding_days=10,
        )
        test_mask = all_dates.isin(eval_dates)
        test_features = feature_frame.loc[test_mask].copy()
        test_returns = execution_returns.loc[
            execution_returns.index.get_level_values("datetime").isin(eval_dates)
        ].copy()

        standard_scores = _predict_scores(
            standard,
            train_features,
            train_returns,
            test_features,
        )
        lower_scores = _predict_scores(
            lower,
            train_features,
            train_returns,
            test_features,
        )
        standard_parts.append(
            _ledger_for_scores(
                standard_scores,
                test_returns,
                classification,
                window=label,
            )
        )
        lower_parts.append(
            _ledger_for_scores(
                lower_scores,
                test_returns,
                classification,
                window=label,
            )
        )
        window_evidence.append(
            {
                "window": label,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "test_start": window.test_start,
                "test_end": window.test_end,
                "evaluation_dates": int(len(eval_dates)),
                "standard_score_rows": int(len(standard_scores)),
                "lower_lr_score_rows": int(len(lower_scores)),
            }
        )

    standard_ledger = pd.concat(standard_parts, ignore_index=True)
    lower_ledger = pd.concat(lower_parts, ignore_index=True)
    identity = {
        "standard_calibration": standard.identity_manifest(),
        "lower_lr_calibration": lower.identity_manifest(),
        "standard_ledger_sha256": _ledger_sha256(standard_ledger),
        "lower_lr_ledger_sha256": _ledger_sha256(lower_ledger),
        "windows": window_evidence,
    }
    return standard_ledger, lower_ledger, identity


def _summary_payload(
    summary: Mapping[str, Any], window_results: pd.DataFrame
) -> dict[str, Any]:
    return {
        **dict(summary),
        "window_results": window_results.to_dict(orient="records"),
    }


def _evaluate_regime_candidate(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    state: pd.DataFrame,
    *,
    rule: str,
    variant: PortfolioVariant,
    costs: Sequence[int],
) -> dict[str, Any]:
    scopes = {
        "reverse": REVERSE_WINDOWS,
        "development": DEVELOPMENT_WINDOWS,
        "historical": HISTORICAL_WINDOWS,
        "reporting": REPORTING_WINDOWS,
    }
    result: dict[str, Any] = {}
    for cost in costs:
        cost_payload: dict[str, Any] = {}
        for scope, windows in scopes.items():
            summary, _, _, window_results = run_regime_portfolio(
                ledger,
                benchmark_returns,
                state,
                windows=windows,
                variant=variant,
                rule=rule,
                rebalance_sessions=10,
                cost_bps=int(cost),
            )
            cost_payload[scope] = _summary_payload(summary, window_results)
        result[str(cost)] = cost_payload
    return result


def _evaluate_legacy_diagnostic(
    ledger: pd.DataFrame,
    benchmark_returns: pd.Series,
    costs: Sequence[int],
) -> dict[str, Any]:
    variant = PortfolioVariant(
        "legacy_corrected_sector_3x1",
        "sector_hierarchical",
        sectors=3,
        names_per_sector=1,
    )
    scopes = {
        "reverse": REVERSE_WINDOWS,
        "development": DEVELOPMENT_WINDOWS,
        "historical": HISTORICAL_WINDOWS,
        "reporting": REPORTING_WINDOWS,
    }
    result: dict[str, Any] = {}
    for cost in costs:
        cost_payload: dict[str, Any] = {}
        for scope, windows in scopes.items():
            summary, _, _ = run_portfolio(
                ledger,
                benchmark_returns,
                variant,
                int(cost),
                windows=windows,
            )
            cost_payload[scope] = summary
        result[str(cost)] = cost_payload
    return result


def _candidate_gates(
    result: Mapping[str, Any],
    incumbent: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, bool]:
    gates = contract["selection"]["hard_gates"]
    primary = str(contract["selection"]["primary_cost_bps"])
    pressure = str(contract["selection"]["pressure_cost_bps"])
    dev = result[primary]["development"]
    reverse = result[primary]["reverse"]
    historical = result[primary]["historical"]
    reporting = result[primary]["reporting"]
    incumbent_hist = incumbent[primary]["historical"]
    incumbent_reporting = incumbent[primary]["reporting"]
    historical_pressure = result[pressure]["historical"]
    return {
        "development_positive_windows": int(dev["positive_excess_windows"])
        >= int(gates["development_positive_windows_min"]),
        "reverse_positive_windows": int(reverse["positive_excess_windows"])
        >= int(gates["reverse_positive_windows_min"]),
        "historical_positive_windows": int(historical["positive_excess_windows"])
        >= int(gates["historical_positive_windows_min"]),
        "historical_drawdown_floor": float(historical["max_drawdown"])
        >= float(gates["historical_max_drawdown_floor"]),
        "historical_excess_improvement": float(historical["relative_excess"])
        >= float(incumbent_hist["relative_excess"])
        + float(gates["historical_relative_excess_min_improvement"]),
        "historical_drawdown_not_materially_worse": float(historical["max_drawdown"])
        >= float(incumbent_hist["max_drawdown"])
        - float(gates["historical_max_drawdown_max_degradation"]),
        "pressure_relative_excess_positive": float(historical_pressure["relative_excess"]) > 0.0,
        "name_concentration": float(historical["maximum_name_absolute_contribution_share"])
        <= float(gates["maximum_name_absolute_contribution_share"]),
        "sector_concentration": float(
            historical["maximum_sector_absolute_contribution_share"]
        )
        <= float(gates["maximum_sector_absolute_contribution_share"]),
        "reporting_absolute_floor": float(reporting["relative_excess"])
        >= float(gates["reporting_relative_excess_floor"]),
        "reporting_not_materially_worse": float(reporting["relative_excess"])
        >= float(incumbent_reporting["relative_excess"])
        - float(gates["reporting_relative_excess_max_degradation"]),
    }


def _compact_row(
    candidate: str,
    result: Mapping[str, Any],
    gates: Mapping[str, bool] | None,
) -> dict[str, Any]:
    primary = result["20"]
    pressure = result["60"]
    historical = primary["historical"]
    reporting = primary["reporting"]
    return {
        "candidate": candidate,
        "historical_relative_excess_20bps": historical["relative_excess"],
        "historical_relative_excess_60bps": pressure["historical"]["relative_excess"],
        "historical_max_drawdown_20bps": historical["max_drawdown"],
        "historical_positive_windows": historical["positive_excess_windows"],
        "historical_turnover": historical["turnover"],
        "maximum_name_absolute_contribution_share": historical[
            "maximum_name_absolute_contribution_share"
        ],
        "maximum_sector_absolute_contribution_share": historical[
            "maximum_sector_absolute_contribution_share"
        ],
        "reporting_relative_excess_20bps": reporting["relative_excess"],
        "reporting_max_drawdown_20bps": reporting["max_drawdown"],
        "all_gates_pass": bool(gates is not None and all(gates.values())),
    }


def _report_markdown(payload: Mapping[str, Any], summary: pd.DataFrame) -> str:
    decision = payload["decision"]
    lines = [
        "# CN x1.2 Corrected Certification",
        "",
        f"**Decision:** `{decision['status']}`",
        f"**Nomination:** `{decision.get('nominated_candidate') or 'none'}`",
        "",
        "## Corrected comparison",
        "",
        "| Candidate | Hist excess 20bps | Hist excess 60bps | Hist DD | Positive windows | Reporting excess | Gates |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.candidate} | {row.historical_relative_excess_20bps:.2%} | "
            f"{row.historical_relative_excess_60bps:.2%} | "
            f"{row.historical_max_drawdown_20bps:.2%} | "
            f"{int(row.historical_positive_windows)} | "
            f"{row.reporting_relative_excess_20bps:.2%} | "
            f"{'PASS' if row.all_gates_pass else '—'} |"
        )
    legacy = payload["legacy_diagnostic"]["20"]["development"]
    lines.extend(
        [
            "",
            "## #766 legacy idea, corrected",
            "",
            "`c_lower_lr__sp_s3_n1` is recomputed as a true sector-hierarchical 3x1 portfolio with actual turnover costs and is not selection-eligible.",
            f"Development relative excess @20bps: **{legacy['relative_excess']:.2%}**.",
            f"Development max drawdown @20bps: **{legacy['max_drawdown']:.2%}**.",
            "",
            "## Evidence boundary",
            "",
            "- 2024H1–2025H2 is consumed development evidence.",
            "- 2022H2–2023H2 and 2026 are validation/reporting evidence, but V3 itself was influenced by prior inspection; this run does not claim a pristine untouched formal holdout.",
            "- A nomination is research-only and does not change the active CN x1.1 formal baseline.",
            "",
        ]
    )
    return "\n".join(lines)


def run(root: Path, provider_dir: Path, output_dir: Path) -> dict[str, Any]:
    contract = _load_contract(root)
    symbols, classification = _load_universe_and_classification(root, contract)
    benchmark = str(contract["benchmark"])
    panel = load_provider_panel(
        provider_dir,
        [*symbols, benchmark],
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    standard_ledger, lower_ledger, ranker_identity = _build_ranker_ledgers(
        panel,
        symbols,
        classification,
        contract,
    )

    close = panel.fields["close"]
    benchmark_returns = forward_returns(
        close[[benchmark]],
        horizon=10,
        delay=1,
    )[benchmark]
    current_state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=benchmark,
        long_ma_sessions=200,
        momentum_sessions=60,
        breadth_ma_sessions=60,
        breadth_threshold=0.50,
    )
    v3_state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=benchmark,
        long_ma_sessions=200,
        momentum_sessions=40,
        breadth_ma_sessions=60,
        breadth_threshold=0.50,
    )
    incumbent_variant = PortfolioVariant(
        "sector_4x1",
        "sector_hierarchical",
        sectors=4,
        names_per_sector=1,
    )
    v3_variant = PortfolioVariant(
        "sector_2x1_v3",
        "sector_hierarchical",
        sectors=2,
        names_per_sector=1,
    )
    costs = tuple(int(value) for value in contract["execution"]["costs_bps"])

    results = {
        "D_incumbent": _evaluate_regime_candidate(
            standard_ledger,
            benchmark_returns,
            current_state,
            rule="two_of_three",
            variant=incumbent_variant,
            costs=costs,
        ),
        "A_lower_lr_current_regime": _evaluate_regime_candidate(
            lower_ledger,
            benchmark_returns,
            current_state,
            rule="two_of_three",
            variant=incumbent_variant,
            costs=costs,
        ),
        "B_incumbent_ranker_v3": _evaluate_regime_candidate(
            standard_ledger,
            benchmark_returns,
            v3_state,
            rule="momentum_and_breadth",
            variant=v3_variant,
            costs=costs,
        ),
        "C_lower_lr_v3": _evaluate_regime_candidate(
            lower_ledger,
            benchmark_returns,
            v3_state,
            rule="momentum_and_breadth",
            variant=v3_variant,
            costs=costs,
        ),
    }
    legacy = _evaluate_legacy_diagnostic(lower_ledger, benchmark_returns, costs)

    incumbent = results["D_incumbent"]
    reconstruction = contract["selection"]["incumbent_reconstruction"]
    incumbent_hist = incumbent["20"]["historical"]
    rel_delta = abs(
        float(incumbent_hist["relative_excess"])
        - float(reconstruction["formal_relative_excess"])
    )
    dd_delta = abs(
        float(incumbent_hist["max_drawdown"])
        - float(reconstruction["formal_max_drawdown"])
    )
    tolerance = float(reconstruction["absolute_tolerance"])
    reconstruction_pass = rel_delta <= tolerance and dd_delta <= tolerance

    candidate_gates = {
        name: _candidate_gates(result, incumbent, contract)
        for name, result in results.items()
        if name != "D_incumbent"
    }
    passing = [name for name, gates in candidate_gates.items() if all(gates.values())]
    passing.sort(
        key=lambda name: (
            float(results[name]["20"]["historical"]["relative_excess"]),
            float(results[name]["20"]["historical"]["max_drawdown"]),
            float(results[name]["60"]["historical"]["relative_excess"]),
        ),
        reverse=True,
    )
    nominated = passing[0] if reconstruction_pass and passing else None
    status = (
        "candidate_nominated_research_only"
        if nominated is not None
        else "no_candidate_authorized"
        if reconstruction_pass
        else "invalid_incumbent_reconstruction"
    )

    rows = [_compact_row("D_incumbent", incumbent, None)]
    rows.extend(
        _compact_row(name, results[name], candidate_gates[name])
        for name in (
            "A_lower_lr_current_regime",
            "B_incumbent_ranker_v3",
            "C_lower_lr_v3",
        )
    )
    summary = pd.DataFrame(rows)
    payload = {
        "schema_version": "cn_x1_2_corrected_certification_v1",
        "experiment_id": contract["experiment_id"],
        "provider": _provider_identity(provider_dir),
        "contract_sha256": _sha256_file(root / CONTRACT_PATH),
        "ranker_identity": ranker_identity,
        "incumbent_reconstruction": {
            "pass": reconstruction_pass,
            "relative_excess_delta": rel_delta,
            "max_drawdown_delta": dd_delta,
            "tolerance": tolerance,
            "reconstructed_relative_excess": incumbent_hist["relative_excess"],
            "reconstructed_max_drawdown": incumbent_hist["max_drawdown"],
        },
        "candidate_results": results,
        "candidate_gates": candidate_gates,
        "legacy_diagnostic": legacy,
        "decision": {
            "status": status,
            "nominated_candidate": nominated,
            "passing_candidates": passing,
            "research_only": True,
            "trade_ready": False,
            "formal_promotion": False,
            "automatic_promotion": False,
        },
        "known_limitations": [
            "Static CN130 membership carries survivorship bias.",
            "Candidate definitions were influenced by earlier experiments; this is not a pristine untouched formal holdout.",
            "A research nomination does not replace the active accepted formal CN x1.1 baseline.",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "certification.json", payload)
    _write_csv(output_dir / "candidate_summary.csv", summary)
    _write_csv(output_dir / "standard_score_ledger.csv.gz", standard_ledger)
    _write_csv(output_dir / "lower_lr_score_ledger.csv.gz", lower_ledger)
    (output_dir / "report.md").write_text(
        _report_markdown(payload, summary),
        encoding="utf-8",
    )

    print("CN_X1_2_CERTIFICATION_RESULT=" + json.dumps(_clean(payload["decision"]), sort_keys=True))
    print("CN_X1_2_INCUMBENT_RECONSTRUCTION=" + json.dumps(_clean(payload["incumbent_reconstruction"]), sort_keys=True))
    for row in rows:
        print("CN_X1_2_CANDIDATE=" + json.dumps(_clean(row), sort_keys=True))
    legacy_dev = legacy["20"]["development"]
    print(
        "CN_X1_2_LEGACY_CORRECTED="
        + json.dumps(
            _clean(
                {
                    "relative_excess_20bps": legacy_dev["relative_excess"],
                    "max_drawdown_20bps": legacy_dev["max_drawdown"],
                    "turnover": legacy_dev["turnover"],
                }
            ),
            sort_keys=True,
        )
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.root.resolve(),
        args.provider_dir.resolve(),
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
