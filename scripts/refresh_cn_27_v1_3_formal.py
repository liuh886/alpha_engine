#!/usr/bin/env python3
"""Refresh the accepted CN_27 V1.3 formal package append-only.

The frozen k2 recipe is rerun over lineage-pinned frozen bars extended with
new sessions from the verified provider. Every rebuilt row at or before the
prior evidence cutoff must reproduce bit-identically; any overlap mismatch,
missing symbol, cutoff drift or recipe-param drift fails closed. No model
selection is possible here: the recipe identity is checked against the
accepted package before anything is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from scripts.cn27_v1_3_formal_common import (
    FAILED_GATES,
    MODEL_ID,
    RECIPE_ID,
    Cn27V13FormalError as Cn27V13RefreshError,
    _object,
    _sha256,
    _write,
    build_attribution_payload,
    build_backtest_rows,
    build_window_summary,
    load_k2_context,
    run_k2_variant_battery,
)
from src.artifacts.formal_refresh import load_object
from src.artifacts.strategy_refresh_exit import (
    DataBlockedError,
    assert_shared_provider_coverage,
)
from src.research.cn27_v1_3 import contribution_attribution
from src.research.cn130_cross_sectional_ranking import load_provider_panel

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FROZEN_CONTRACT = Path(
    "configs/research_experiments/cn_27_v1_3_projected_concentration_discovery_v1.yaml"
)
OVERLAP_RTOL = 1e-6
SOURCE_FIELDS = ("open", "high", "low", "close", "volume")


def _resolve_provider_keys(provider_dir: Path, required: list[str]) -> dict[str, str]:
    lifecycle_path = provider_dir / "instruments" / "cn.txt"
    if not lifecycle_path.is_file():
        raise Cn27V13RefreshError(f"provider lifecycle is missing: {lifecycle_path}")
    available = {
        line.split("\t")[0].strip()
        for line in lifecycle_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    resolved: dict[str, str] = {}
    for symbol in required:
        candidates: list[str] = []
        for key in (symbol, symbol.zfill(6)):
            if key in available and key not in candidates:
                candidates.append(key)
        if len(candidates) != 1:
            raise Cn27V13RefreshError(
                f"provider key for {symbol} is missing or ambiguous: {candidates}"
            )
        resolved[symbol] = candidates[0]
    return resolved


def _check_provider_manifest(manifest_path: Path, cutoff: str) -> dict[str, Any]:
    manifest = _object(manifest_path)
    if str(manifest.get("cutoff") or "").strip() != cutoff:
        raise Cn27V13RefreshError(
            "provider manifest cutoff does not match the requested refresh cutoff"
        )
    return manifest


def _check_manifest_symbol_health(
    manifest: Mapping[str, Any], required: list[str]
) -> None:
    flagged: set[str] = set()
    for field in (
        "quarantined_symbols",
        "legacy_copied_symbols",
        "unresolved_stale_symbols",
    ):
        values = manifest.get(field)
        if isinstance(values, list):
            flagged.update(str(value).strip().upper() for value in values)
    bad = [
        symbol
        for symbol in required
        if symbol.upper() in flagged or symbol.zfill(6).upper() in flagged
    ]
    if bad:
        raise Cn27V13RefreshError(
            f"provider health flags touch required CN_27 symbols: {sorted(bad)}"
        )


def extend_bars(
    *,
    frozen_bars: pd.DataFrame,
    provider_dir: Path,
    cutoff: str,
) -> pd.DataFrame:
    """Append provider sessions after the frozen end, verifying the overlap."""

    cutoff_ts = pd.Timestamp(cutoff)
    frozen = frozen_bars.copy()
    frozen["date"] = pd.to_datetime(frozen["date"])
    frozen_end = frozen["date"].max()
    if cutoff_ts <= frozen_end:
        raise Cn27V13RefreshError("refresh cutoff must extend beyond the frozen bars")
    required = sorted(frozen["symbol"].astype(str).unique().tolist())
    assert_shared_provider_coverage(provider_dir, required, label="CN_27 V1.3")
    keys = _resolve_provider_keys(provider_dir, required)
    panel = load_provider_panel(provider_dir, list(keys.values()), fields=SOURCE_FIELDS)
    new_frames: list[pd.DataFrame] = []
    for symbol in required:
        key = keys[symbol]
        frame = pd.DataFrame(
            {field: panel.fields[field][key] for field in SOURCE_FIELDS}
        )
        frame.index = pd.DatetimeIndex(panel.calendar)
        frame = frame.loc[frame.index <= cutoff_ts]
        frame = frame.dropna(subset=["close"])
        if frame.empty:
            raise Cn27V13RefreshError(f"provider has no rows for {symbol}")
        old = frozen.loc[frozen["symbol"].astype(str).eq(symbol)].set_index("date")
        shared = old.index.intersection(frame.index)
        if shared.empty:
            raise Cn27V13RefreshError(f"provider has no overlap for {symbol}")
        for field in SOURCE_FIELDS:
            expected = old.loc[shared, field].astype(float).to_numpy()
            observed = frame.loc[shared, field].astype(float).to_numpy()
            both = ~(pd.isna(expected) | pd.isna(observed))
            if both.any() and not bool(
                (abs(expected[both] - observed[both]) <= OVERLAP_RTOL * abs(expected[both])).all()
            ):
                raise Cn27V13RefreshError(
                    f"provider restated frozen history for {symbol}.{field}"
                )
            only_frozen = pd.isna(observed) & ~pd.isna(expected)
            if bool(only_frozen.any()):
                raise Cn27V13RefreshError(
                    f"provider dropped frozen values for {symbol}.{field}"
                )
        fresh = frame.loc[frame.index > frozen_end].copy()
        fresh["symbol"] = symbol
        fresh = fresh.reset_index().rename(columns={"datetime": "date"})
        new_frames.append(fresh[["date", "symbol", *SOURCE_FIELDS]])
    if not new_frames:
        raise Cn27V13RefreshError("provider contributed no new sessions")
    combined = pd.concat([frozen, *new_frames], ignore_index=True)
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    latest = combined["date"].max()
    if latest > cutoff_ts:
        raise Cn27V13RefreshError("extended bars exceed the refresh cutoff")
    return combined


def _check_recipe_identity(recipe: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    contract = current.get("portfolio_contract")
    if not isinstance(contract, Mapping):
        raise Cn27V13RefreshError("current package portfolio contract is missing")
    if recipe.get("id") != RECIPE_ID:
        raise Cn27V13RefreshError("frozen k2 recipe identity drifted")
    for field in (
        "maximum_single_equity_sleeve_share",
        "maximum_sector_equity_sleeve_share",
        "minimum_effective_names",
    ):
        if float(recipe.get(field, 0.0)) != float(contract.get(field, -1.0)):
            raise Cn27V13RefreshError(f"frozen recipe param drifted: {field}")


def _check_prefix(
    current: Mapping[str, Any],
    report: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> dict[str, int]:
    from src.research.cn27_v1_3_replay import rows_close_enough

    observed: dict[str, int] = {}
    for field, fresh in (
        ("report", report),
        ("positions", positions),
        ("trades", trades),
    ):
        before = current.get(field)
        if not isinstance(before, list):
            raise Cn27V13RefreshError(f"CN_27 current {field} is missing")
        if len(fresh) < len(before) or not rows_close_enough(
            fresh[: len(before)], before
        ):
            raise Cn27V13RefreshError(
                f"CN_27 {field} changed before the reporting boundary"
            )
        observed[field] = len(before)
    return observed


def refresh_cn_27_v1_3(
    *,
    current_package: Path,
    provider_dir: Path,
    provider_manifest: Path,
    contract_path: Path = FROZEN_CONTRACT,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    current = load_object(current_package)
    if current.get("model_id") != MODEL_ID:
        raise Cn27V13RefreshError("CN_27 refresh requires the accepted CN_27 V1.3 package")
    prior_cutoff = str(current.get("evidence_cutoff") or "")
    if not prior_cutoff or not cutoff > prior_cutoff:
        raise Cn27V13RefreshError("refresh cutoff must extend beyond the current cutoff")
    manifest = _check_provider_manifest(provider_manifest, cutoff)
    frozen_prices_rel = str(
        (current.get("evidence") or {}).get("source_prices") or ""
    )
    frozen_prices_sha = str(
        (current.get("evidence") or {}).get("source_prices_sha256") or ""
    )
    if not frozen_prices_rel or not frozen_prices_sha:
        raise Cn27V13RefreshError("current package source price binding is missing")
    frozen_prices = (REPOSITORY_ROOT / frozen_prices_rel).resolve()
    if not frozen_prices.is_file() or _sha256(frozen_prices) != frozen_prices_sha:
        raise Cn27V13RefreshError("frozen CN_27 source prices are missing or revised")
    frozen_bars = pd.read_csv(
        frozen_prices, dtype={"symbol": str}, parse_dates=["date"]
    )
    try:
        _check_manifest_symbol_health(
            manifest,
            sorted(frozen_bars["symbol"].astype(str).unique().tolist()),
        )
        extended = extend_bars(
            frozen_bars=frozen_bars, provider_dir=provider_dir, cutoff=cutoff
        )
    except Cn27V13RefreshError as exc:
        # Provider-data stage (health flags, key resolution, overlap splice):
        # vendor gaps, lag or restatements block this strategy honestly but
        # must not melt the publish fan-in. Contract errors raised above and
        # below stay fatal.
        raise DataBlockedError(str(exc)) from exc

    context = load_k2_context(REPOSITORY_ROOT / contract_path)
    _check_recipe_identity(context.recipe, current)

    from src.research.cn27_v1_2 import compute_v1_2_features, score_v1_2_features
    from src.research.cn27_v1_3_projected import run_projected_recipe

    features = compute_v1_2_features(extended, context.contract)
    scoring_recipe = {**context.contract.spec["frozen_signal"], "id": "frozen_v1_2_signal"}
    scored, _ = score_v1_2_features(features, scoring_recipe, context.contract)
    result = run_projected_recipe(
        extended,
        features,
        context.contract,
        context.recipe,
        scored_features=scored,
    )
    report, positions, trades = build_backtest_rows(
        extended, context.contract, result
    )
    prefix = _check_prefix(current, report, positions, trades)
    attribution, _ = contribution_attribution(result.daily, extended, context.contract)
    attribution_payload = build_attribution_payload(attribution)
    battery = run_k2_variant_battery(
        bars=extended,
        features=features,
        scored=scored,
        contract=context.contract,
        recipe=context.recipe,
        base_result=result,
    )
    full = result.metrics_by_window["development"]
    dates = pd.DatetimeIndex(result.daily.index)
    from scripts.cn27_v1_3_formal_common import _benchmark_path

    benchmark_equity = (1.0 + _benchmark_path(extended, dates)).cumprod()
    benchmark_total = float(benchmark_equity.iloc[-1] - 1.0)
    total_return = float(full["total_return"])

    prior_evidence = current.get("evidence")
    if not isinstance(prior_evidence, Mapping):
        raise Cn27V13RefreshError("current package evidence block is missing")
    prior_freshness = current.get("freshness")
    evidence = {
        **{str(key): value for key, value in prior_evidence.items()},
        "refresh_of_evidence_cutoff": prior_cutoff,
        "refresh_provider_manifest": provider_manifest.resolve().as_posix(),
        "refresh_provider_manifest_sha256": _sha256(provider_manifest),
        "refresh_extended_bar_rows": int(len(extended)),
        "refresh_new_sessions": int(
            extended.loc[
                extended["date"] > pd.Timestamp(prior_cutoff)
            ]["date"].nunique()
        ),
        "historical_evidence_recomputed": True,
        "exact_historical_reproduction": True,
        "model_selection_reopened": False,
    }
    freshness = {
        **(
            dict(prior_freshness)
            if isinstance(prior_freshness, Mapping)
            else {}
        ),
        "latest_completed_session": cutoff,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    portfolio_contract = current.get("portfolio_contract")
    metrics = {
        "Total Return": total_return,
        "Annualized Return": float(full["cagr"]),
        "Benchmark Return": benchmark_total,
        "Compounded Relative Excess Return": (1.0 + total_return) / (1.0 + benchmark_total)
        - 1.0,
        "Annualized Volatility": float(full["annual_volatility"]),
        "Sharpe Ratio": float(full["sharpe_log_excess"]),
        "Max Drawdown": float(full["maximum_drawdown"]),
        "Turnover": float(full["annual_one_way_turnover"]),
        "Transaction Cost": float(full["transaction_cost_paid"]),
    }
    candidate = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": f"cn_27_v1_3-through-{cutoff.replace('-', '_')}",
        "model_id": MODEL_ID,
        "display_name": "CN_27 V1.3",
        "market": "cn",
        "benchmark": "000300",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": cutoff,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "daily_open_to_open",
        "date_range": {
            "start": dates.min().date().isoformat(),
            "end": dates.max().date().isoformat(),
        },
        "metrics": metrics,
        "portfolio_contract": portfolio_contract,
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution_payload,
        "window_summary": build_window_summary(
            result=result,
            phase_sharpes=battery["phase_sharpes"],
            delay_two_full_sharpe=battery["delay_two_full_sharpe"],
            parameter_rows=battery["parameter_rows"],
            sector_rows=battery["sector_rows"],
            bootstrap=battery["bootstrap"],
            bootstrap_policy=battery["bootstrap_policy"],
            failed_gates=list(FAILED_GATES),
        ),
        "evidence": evidence,
        "freshness": freshness,
        "interpretation_notes": list(current.get("interpretation_notes") or []),
    }
    _write(output, candidate)
    return {
        "candidate_backtest_id": candidate["backtest_id"],
        "candidate_evidence_cutoff": cutoff,
        "frozen_prefix_rows": prefix,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-package", type=Path, required=True)
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--provider-manifest", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=FROZEN_CONTRACT)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = refresh_cn_27_v1_3(
            current_package=args.current_package,
            provider_dir=args.provider_dir,
            provider_manifest=args.provider_manifest,
            contract_path=args.contract,
            cutoff=args.cutoff,
            generated_at=args.generated_at,
            output=args.output,
        )
    except DataBlockedError as exc:
        # Exit 10 = governed data block (retain, degraded). The strategy
        # runner maps it to data_blocked instead of execution_failed so one
        # strategy's missing data no longer melts the whole publish fan-in.
        print(json.dumps({"data_blocked": str(exc)}, ensure_ascii=False))
        return 10
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
