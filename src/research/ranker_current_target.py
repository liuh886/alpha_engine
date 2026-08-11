"""Governed current-target inference for the formal US/CN 10-session rankers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.market_provider import load_provider_manifest
from src.factors.library import load_factor_library, normalize_expression
from src.factors.ranker_snapshot import build_ranker_factor_snapshot
from src.research.cn130_cross_sectional_ranking import (
    attach_classification,
    build_feature_matrices,
    fit_ranker,
    forward_returns,
    load_provider_panel,
    make_label,
    predict_ranker,
    stack_return_frame,
)
import src.research.cn130_ranking_pipeline as cn_core
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    read_latest_evaluation,
)
from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    regime_signal,
)
from src.research.daily_ranker import prepare_ranker_frame
from src.research.daily_ranker_model import (
    fit_xgb_daily_ranker,
    predict_xgb_daily_ranker,
)
from src.research.paradigm import ResearchParadigmSpec
from src.research.qlib_execution_common import (
    materialize_ranker_candidates,
    normalize_qlib_frame_index,
    sanitize_factor_name,
    validate_no_nan_inputs,
)
from src.research.rolling_windows import purge_training_tail
from src.research.spec_bound_execution import build_spec_bound_execution_plan
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.xgb_ranker_explainability import (
    attach_factor_contributions,
    build_xgb_pred_contribs,
)

US_MODEL_ID = "us_x1_1"
CN_MODEL_ID = "cn_x1_1"
US_FAMILY = "us_ranker"
CN_FAMILY = "cn_ranker"
REBALANCE_SESSIONS = 10
COST_BPS = 20
US_SPEC_LABEL = "configs/research_paradigms/us_x1_1_frozen_v1.yaml"
CN_CONFIG_LABEL = "configs/models/cn_x1_1.yaml"
CN_FACTOR_COLUMNS = {
    "ohlcv.momentum.ret_3d": "momentum_3",
    "ohlcv.momentum.ret_5d": "momentum_5",
    "ohlcv.momentum.ret_10d": "momentum_10",
    "ohlcv.momentum.ret_20d": "momentum_20",
    "ohlcv.reversal.inv_ret_1d": "reversal_1",
    "ohlcv.reversal.inv_ret_3d": "reversal_3",
    "ohlcv.reversal.inv_ret_5d": "reversal_5",
    "ohlcv.volatility.std_ret_5d": "volatility_5",
    "ohlcv.volatility.std_ret_10d": "volatility_10",
    "ohlcv.volatility.std_ret_20d": "volatility_20",
    "ohlcv.volatility.high_low_range_pct": "intraday_range",
    "ohlcv.liquidity.volume_vs_ma_5d": "volume_ratio_5",
    "ohlcv.liquidity.volume_vs_ma_10d": "volume_ratio_10",
    "ohlcv.liquidity.volume_vs_ma_20d": "volume_ratio_20",
}


class RankerCurrentTargetError(ValueError):
    """Raised when a current target cannot be proven from frozen semantics."""


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RankerCurrentTargetError(f"JSON root must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _latest_formal_weights(
    package: Mapping[str, Any],
) -> tuple[str, dict[str, float]]:
    positions = package.get("positions")
    if not isinstance(positions, list) or not positions:
        raise RankerCurrentTargetError("formal package has no positions")
    dates = sorted({str(row.get("date", "")) for row in positions if isinstance(row, dict)})
    if not dates or not dates[-1]:
        raise RankerCurrentTargetError("formal positions have no signal date")
    anchor = dates[-1]
    weights = {
        str(row["instrument"]): float(row["weight"])
        for row in positions
        if isinstance(row, dict) and str(row.get("date", "")) == anchor
    }
    if not weights or abs(sum(weights.values()) - 1.0) > 1e-6:
        raise RankerCurrentTargetError("latest formal weights are invalid")
    return anchor, dict(sorted(weights.items()))


def load_previous_state(*, formal_package: Path, ledger_dir: Path) -> tuple[str, dict[str, float]]:
    """Use the newest governed target, preferring the live append-only ledger."""

    formal_anchor, formal_weights = _latest_formal_weights(_json(formal_package))
    try:
        record = read_latest_evaluation(
            ledger_dir,
            model_version_id=ledger_dir.name,
        )
    except (OSError, json.JSONDecodeError, StrategySignalLedgerError) as exc:
        raise RankerCurrentTargetError("latest live ranker record is invalid") from exc
    if record is None:
        return formal_anchor, formal_weights
    signal = record.get("signal")
    if not isinstance(signal, dict):
        raise RankerCurrentTargetError("latest live ranker record is invalid")
    signal_date = str(signal.get("signal_date", ""))
    target = signal.get("target_weights")
    if not signal_date or not isinstance(target, dict) or not target:
        raise RankerCurrentTargetError("latest live ranker record is invalid")
    live_weights = {str(key): float(value) for key, value in target.items()}
    if abs(sum(live_weights.values()) - 1.0) > 1e-6:
        raise RankerCurrentTargetError("latest live target weights do not sum to one")
    if pd.Timestamp(signal_date) >= pd.Timestamp(formal_anchor):
        return signal_date, dict(sorted(live_weights.items()))
    return formal_anchor, formal_weights


def next_due_session(
    *,
    anchor: str,
    sessions: Sequence[pd.Timestamp],
    cadence: int = REBALANCE_SESSIONS,
) -> str | None:
    """Return exactly the cadence-th provider session after the last target."""

    dates = (
        pd.DatetimeIndex(pd.to_datetime(list(sessions)))
        .tz_localize(None)
        .normalize()
        .unique()
        .sort_values()
    )
    anchor_ts = pd.Timestamp(anchor).normalize()
    matches = np.flatnonzero(dates == anchor_ts)
    if len(matches) != 1:
        raise RankerCurrentTargetError(
            f"previous signal date {anchor} is not uniquely present in provider calendar"
        )
    due_index = int(matches[0]) + int(cadence)
    if due_index >= len(dates):
        return None
    return pd.Timestamp(dates[due_index]).strftime("%Y-%m-%d")


def _turnover(previous: Mapping[str, float], target: Mapping[str, float]) -> float:
    names = set(previous) | set(target)
    return 0.5 * sum(abs(target.get(name, 0.0) - previous.get(name, 0.0)) for name in names)


def _factor_summary(
    *,
    model_family_id: str,
    signal_date: str,
    target_weights: Mapping[str, float],
    features: pd.DataFrame,
    factor_columns: Mapping[str, str],
) -> dict[str, Any]:
    target_names = list(target_weights)
    instruments = features.index.get_level_values("instrument")
    selected = features.loc[instruments.isin(target_names)].copy()
    if selected.empty:
        raise RankerCurrentTargetError("factor reference basket has no rows")
    factor_values: dict[str, float] = {}
    references: dict[str, dict[str, Any]] = {}
    for factor_id, column in factor_columns.items():
        if column not in features.columns:
            raise RankerCurrentTargetError(f"missing current factor column: {column}")
        series = selected[column]
        weighted = 0.0
        used = 0.0
        for index, value in series.items():
            instrument = str(index[1]) if isinstance(index, tuple) else str(index)
            weight = float(target_weights.get(instrument, 0.0))
            if weight and pd.notna(value):
                weighted += weight * float(value)
                used += weight
        if used <= 0.0:
            raise RankerCurrentTargetError(f"factor {factor_id} has no reference observations")
        value = weighted / used
        factor_values[factor_id] = value
        references[factor_id] = {
            "reference_weighted_mean": value,
            "universe_mean": float(features[column].mean()),
            "reference_weight_covered": used,
        }
    return build_ranker_factor_snapshot(
        model_family_id=model_family_id,
        signal_date=signal_date,
        latest_data_date=signal_date,
        factor_values=factor_values,
        factor_references=references,
        data_freshness_ok=True,
    )


def _explanation_summary(explanations: Mapping[str, Any]) -> dict[str, Any]:
    rows = explanations.get("rows")
    if not isinstance(rows, list):
        raise RankerCurrentTargetError("ranker explanations have no rows")
    return {
        "method": explanations.get("method"),
        "score_reconciliation": explanations.get("score_reconciliation"),
        "decision_role": explanations.get("decision_role"),
        "rows": [
            {
                "instrument": row.get("instrument"),
                "decision_role": row.get("decision_role"),
                "score": row.get("score"),
                "bias": row.get("bias"),
                "top_positive": row.get("top_positive", []),
                "top_negative": row.get("top_negative", []),
            }
            for row in rows
            if isinstance(row, Mapping)
        ],
    }


def _model_identity(
    *,
    formal_package: Path,
    model_config: Path,
    model_config_label: str,
    provider_dir: Path,
    market: str,
) -> dict[str, Any]:
    formal = _json(formal_package)
    provider = load_provider_manifest(
        provider_dir,
        expected_market=market,
        required=True,
        verify_files=True,
    )
    if provider is None:
        raise RankerCurrentTargetError("provider manifest is unavailable")
    return {
        "formal_backtest_id": formal.get("backtest_id"),
        "formal_model_id": formal.get("model_id"),
        "formal_evidence_cutoff": formal.get("evidence_cutoff"),
        "formal_package_sha256": _sha256_file(formal_package),
        "model_config_path": model_config_label,
        "model_config_sha256": _sha256_file(model_config),
        "provider_identity_sha256": provider["provider_identity_sha256"],
    }


def _signal_payload(
    *,
    model_version_id: str,
    model_family_id: str,
    signal_date: str,
    market_cutoff: str,
    previous_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    factor_evidence: Mapping[str, Any],
    model_identity: Mapping[str, Any],
    reason_code: str,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    turnover = _turnover(previous_weights, target_weights)
    changed = turnover > 1e-12
    core: dict[str, Any] = {
        "model_version_id": model_version_id,
        "model_family_id": model_family_id,
        "model_identity": dict(model_identity),
        "signal_date": signal_date,
        "latest_data_date": signal_date,
        "market_cutoff": market_cutoff,
        "execution_time": "next_eligible_open",
        "current_weights": dict(sorted(previous_weights.items())),
        "target_weights": dict(sorted(target_weights.items())),
        "turnover_units": turnover,
        "estimated_transaction_cost": turnover * COST_BPS / 10000.0,
        "estimated_transaction_cost_bps": COST_BPS,
        "data_freshness_ok": True,
        "factor_evidence": dict(factor_evidence),
        "factor_freshness_ok": factor_evidence.get("freshness") == "current",
        "signal_state": "rebalance" if changed else "no_change",
        "action": "REBALANCE" if changed else "HOLD",
        "reason_code": reason_code,
        "diagnostics": dict(diagnostics),
        "research_only": True,
        "trade_ready": False,
    }
    core["fingerprint"] = _canonical_sha(core)
    core["should_alert"] = changed
    return core


def score_us_current_target(
    *,
    provider_dir: Path,
    formal_package: Path,
    ledger_dir: Path,
    signal_date: str,
    market_cutoff: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Refit the frozen H1/H2 US x1.1 ranker and score one rebalance date."""

    spec_path = repository_root / US_SPEC_LABEL
    spec = ResearchParadigmSpec.from_yaml(spec_path)
    plan = build_spec_bound_execution_plan(spec)
    candidates = materialize_ranker_candidates(plan)
    if len(candidates) != 1:
        raise RankerCurrentTargetError("US x1.1 must materialize exactly one ranker")
    candidate = candidates[0]
    if candidate.model_family != "xgb":
        raise RankerCurrentTargetError("US x1.1 current publisher requires frozen XGBoost ranker")
    symbols = [str(value) for value in plan.declared_contract["universe"]["requested_symbols"]]
    runtime = QlibUSExecutionRuntime(provider_uri=provider_dir)
    runtime.initialize(repository_root)
    available = runtime.available_symbols()
    missing = sorted(set(symbols) - available)
    if missing:
        raise RankerCurrentTargetError(f"US provider missing frozen universe symbols: {missing}")

    signal_ts = pd.Timestamp(signal_date)
    half_start = pd.Timestamp(f"{signal_ts.year}-{'01-01' if signal_ts.month <= 6 else '07-01'}")
    train_start = str(spec.walk_forward["requested_train_start"])
    train_end = (half_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    expressions = sorted(set(candidate.feature_group.expressions))
    expression_columns = {
        expression: sanitize_factor_name(expression) for expression in expressions
    }
    features_all = normalize_qlib_frame_index(
        runtime.features(symbols, expressions, train_start, signal_date)
    ).replace([np.inf, -np.inf], np.nan)
    features_all.columns = [expression_columns[expression] for expression in expressions]
    return_expression = str(spec.strategy["return_expression"])
    returns_all = normalize_qlib_frame_index(
        runtime.features(
            symbols,
            [return_expression],
            train_start,
            train_end,
        )
    )
    returns_all.columns = ["return"]
    dates = features_all.index.get_level_values("datetime")
    train_mask = (dates >= pd.Timestamp(train_start)) & (dates <= pd.Timestamp(train_end))
    test_mask = dates == signal_ts
    features_train_raw = features_all.loc[train_mask].copy()
    return_dates = returns_all.index.get_level_values("datetime")
    returns_train_raw = returns_all.loc[
        (return_dates >= pd.Timestamp(train_start)) & (return_dates <= pd.Timestamp(train_end))
    ].copy()
    features_train, returns_train = purge_training_tail(
        features_train_raw,
        returns_train_raw,
        holding_days=int(spec.strategy["holding_days"]),
    )
    valid, reason = validate_no_nan_inputs(
        features_train,
        context="US x1.1 current target",
    )
    if not valid:
        raise RankerCurrentTargetError(reason)
    features_test = features_all.loc[test_mask].copy()
    if len(features_test) < int(spec.universe["min_symbols"]):
        raise RankerCurrentTargetError("US current target has insufficient feature rows")
    columns = [expression_columns[item] for item in candidate.feature_group.expressions]
    x_rank, y_rank, groups = prepare_ranker_frame(features_train.loc[:, columns], returns_train)
    ranker_fit = fit_xgb_daily_ranker(
        x_rank,
        y_rank,
        groups,
        n_gain_bins=candidate.calibration.n_gain_bins,
        params=None,
        num_boost_round=candidate.calibration.num_boost_round,
    )
    scores = predict_xgb_daily_ranker(ranker_fit, features_test.loc[:, columns])
    day = scores.reset_index().sort_values(
        ["score", "instrument"],
        ascending=[False, True],
        kind="mergesort",
    )
    top_n = int(spec.strategy["top_n"])
    chosen = day.head(top_n)
    weight = 1.0 / top_n
    target = {str(symbol): weight for symbol in chosen["instrument"]}
    previous_date, previous = load_previous_state(
        formal_package=formal_package,
        ledger_dir=ledger_dir,
    )

    library = load_factor_library(repository_root / "configs/factor_libraries/ohlcv.yaml")
    expression_to_column = {
        normalize_expression(expression): expression_columns[expression]
        for expression in expressions
    }
    factor_columns: dict[str, str] = {}
    for definition in library.factors_for_groups(["momentum_volatility_volume"]):
        normalized = normalize_expression(definition.expression)
        column = expression_to_column.get(normalized)
        if column is None:
            raise RankerCurrentTargetError(
                f"frozen US ranker is missing canonical factor {definition.factor_id}"
            )
        factor_columns[definition.factor_id] = column
    factor_evidence = _factor_summary(
        model_family_id=US_FAMILY,
        signal_date=signal_date,
        target_weights=target,
        features=features_test,
        factor_columns=factor_columns,
    )
    explanations = build_xgb_pred_contribs(
        model=ranker_fit.model,
        features=features_test.loc[:, columns],
        scores=scores,
        column_to_factor_id={column: factor_id for factor_id, column in factor_columns.items()},
        instruments=list(target),
        decision_role="selected_holding",
    )
    factor_evidence = attach_factor_contributions(factor_evidence, explanations)
    return _signal_payload(
        model_version_id=US_MODEL_ID,
        model_family_id=US_FAMILY,
        signal_date=signal_date,
        market_cutoff=market_cutoff,
        previous_weights=previous,
        target_weights=target,
        factor_evidence=factor_evidence,
        model_identity=_model_identity(
            formal_package=formal_package,
            model_config=spec_path,
            model_config_label=US_SPEC_LABEL,
            provider_dir=provider_dir,
            market="us",
        ),
        reason_code="frozen_us_x1_1_10_session_rebalance",
        diagnostics={
            "previous_signal_date": previous_date,
            "train_start": train_start,
            "train_end": train_end,
            "ranker": candidate.name,
            "top_n": top_n,
            "model_explanations": _explanation_summary(explanations),
        },
    )


def _select_cn_sector_breadth(
    day: pd.DataFrame,
    *,
    sectors: int,
    names_per_sector: int,
) -> pd.DataFrame:
    ranked = day.dropna(subset=["score", "sector"]).copy()
    ranked = ranked.sort_values(
        ["score", "instrument"],
        ascending=[False, True],
        kind="mergesort",
    )
    ranked["score_pct"] = ranked["score"].rank(method="average", pct=True)
    sector_scores = ranked.groupby("sector", sort=True)["score_pct"].apply(
        lambda series: float(series.nlargest(min(3, len(series))).mean())
    )
    selected = list(
        sector_scores.sort_values(ascending=False, kind="mergesort").head(sectors).index
    )
    pieces = [ranked.loc[ranked["sector"] == sector].head(names_per_sector) for sector in selected]
    return pd.concat(pieces, ignore_index=False) if pieces else ranked.head(0)


def score_cn_current_target(
    *,
    provider_dir: Path,
    formal_package: Path,
    ledger_dir: Path,
    signal_date: str,
    market_cutoff: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Refit CN x1.1 and apply its certified regime/sector sleeve."""

    universe_path = repository_root / "configs/research_universes/cn_selected_equities_v3.yaml"
    classification_path = (
        repository_root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    )
    model_config_path = repository_root / CN_CONFIG_LABEL
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    classification = yaml.safe_load(classification_path.read_text(encoding="utf-8"))["symbols"]
    symbols = [str(value) for value in universe["symbols"]]
    panel = load_provider_panel(
        provider_dir,
        [*symbols, cn_core.BENCHMARK],
    )
    families, _ = build_feature_matrices(
        panel,
        symbols=symbols,
        benchmark=cn_core.BENCHMARK,
    )
    features = families["current_cn_ohlcv"]
    raw_returns = stack_return_frame(
        forward_returns(
            panel.fields["close"][symbols],
            horizon=REBALANCE_SESSIONS,
        ),
        "raw_forward_return",
    )
    signal_ts = pd.Timestamp(signal_date)
    half_start = pd.Timestamp(f"{signal_ts.year}-{'01-01' if signal_ts.month <= 6 else '07-01'}")
    train_dates = cn_core.purged_training_dates(panel.calendar, half_start)
    train_x = cn_core.slice_dates(features, train_dates)
    train_raw = cn_core.slice_dates(raw_returns, train_dates)
    benchmark_returns = forward_returns(
        panel.fields["close"][[cn_core.BENCHMARK]],
        horizon=REBALANCE_SESSIONS,
    )[cn_core.BENCHMARK]
    target_label = make_label(
        train_raw,
        mode="raw",
        benchmark_returns=benchmark_returns,
        classification=classification,
    )
    test_x = cn_core.slice_dates(
        features,
        pd.DatetimeIndex([signal_ts]),
    )
    if test_x.empty:
        raise RankerCurrentTargetError(f"CN provider has no factor rows on {signal_date}")
    cn_fit = fit_ranker(
        train_x,
        target_label,
        group_keys=cn_core.date_key(train_x.index),
        seed=42,
    )
    scores = predict_ranker(cn_fit, test_x)
    day = scores.join(attach_classification(scores.index, classification)).reset_index()
    gate = RegimeGateSpec()
    state = build_regime_state(
        panel.fields["close"],
        symbols=symbols,
        benchmark=cn_core.BENCHMARK,
        long_ma_sessions=gate.long_ma_sessions,
        momentum_sessions=gate.momentum_sessions,
        breadth_ma_sessions=gate.breadth_ma_sessions,
        breadth_threshold=gate.breadth_threshold,
    )
    risk_on = regime_signal(state, signal_ts, "two_of_three")
    if risk_on:
        chosen = _select_cn_sector_breadth(
            day,
            sectors=gate.sectors,
            names_per_sector=gate.names_per_sector,
        )
        expected = gate.sectors * gate.names_per_sector
        if len(chosen) != expected:
            raise RankerCurrentTargetError("CN sector-breadth target is incomplete")
        weight = 1.0 / len(chosen)
        target = {str(symbol): weight for symbol in chosen["instrument"]}
        factor_reference = target
        explanation_instruments = list(target)
        explanation_role = "selected_holding"
    else:
        target = {cn_core.BENCHMARK: 1.0}
        ranked_names = [str(value) for value in day["instrument"]]
        if not ranked_names:
            raise RankerCurrentTargetError(
                "CN risk-off decision has no cross-sectional factor rows"
            )
        reference_weight = 1.0 / len(ranked_names)
        factor_reference = {symbol: reference_weight for symbol in ranked_names}
        explanation_instruments = ranked_names[: gate.sectors * gate.names_per_sector]
        explanation_role = "ranker_reference_vetoed_by_regime"
    previous_date, previous = load_previous_state(
        formal_package=formal_package,
        ledger_dir=ledger_dir,
    )
    factor_evidence = _factor_summary(
        model_family_id=CN_FAMILY,
        signal_date=signal_date,
        target_weights=factor_reference,
        features=test_x,
        factor_columns=CN_FACTOR_COLUMNS,
    )
    explanations = build_xgb_pred_contribs(
        model=cn_fit.model,
        features=test_x.loc[:, list(cn_fit.feature_names)],
        scores=scores,
        column_to_factor_id={column: factor_id for factor_id, column in CN_FACTOR_COLUMNS.items()},
        instruments=explanation_instruments,
        decision_role=explanation_role,
    )
    factor_evidence = attach_factor_contributions(factor_evidence, explanations)
    state_row = state.loc[signal_ts]
    return _signal_payload(
        model_version_id=CN_MODEL_ID,
        model_family_id=CN_FAMILY,
        signal_date=signal_date,
        market_cutoff=market_cutoff,
        previous_weights=previous,
        target_weights=target,
        factor_evidence=factor_evidence,
        model_identity=_model_identity(
            formal_package=formal_package,
            model_config=model_config_path,
            model_config_label=CN_CONFIG_LABEL,
            provider_dir=provider_dir,
            market="cn",
        ),
        reason_code=("cn_x1_1_sector_breadth_risk_on" if risk_on else "cn_x1_1_csi300_risk_off"),
        diagnostics={
            "previous_signal_date": previous_date,
            "ranking_id": "r0_cn_x1_0_raw_return_rank",
            "feature_family": "current_cn_ohlcv",
            "risk_on": risk_on,
            "votes": int(state_row["votes"]),
            "long_trend": bool(state_row["long_trend"]),
            "medium_momentum": bool(state_row["medium_momentum"]),
            "cross_sectional_breadth": bool(state_row["cross_sectional_breadth"]),
            "breadth_value": float(state_row["breadth_value"]),
            "model_explanations": _explanation_summary(explanations),
        },
    )
