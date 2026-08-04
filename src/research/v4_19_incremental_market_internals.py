"""Phase 0/1 validation for incremental market-internal factor families.

The module deliberately does not construct a portfolio.  It first audits source
admissibility, then compares each complete family block with the frozen v4.16
29-input Ridge comparator on exactly the same chronological samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.research.etf_rotation_experiment import _normalise_bars
from src.research.v4_16_action_advantage_runtime import (
    build_action_advantage_frame,
)

ACTION_KEYS = (
    "cash_defense",
    "broad_equity",
    "nasdaq_core",
    "nasdaq_acceleration",
)


@dataclass(frozen=True)
class FamilyEvaluation:
    family: str
    admissible: bool
    rejection_reason: str | None
    feature_names: tuple[str, ...]
    feature_frame: pd.DataFrame
    predictions: pd.DataFrame
    action_metrics: pd.DataFrame
    action_state_metrics: pd.DataFrame
    fold_metrics: pd.DataFrame
    fold_coefficients: pd.DataFrame
    coefficient_cosines: pd.DataFrame
    source_fold_coverage: pd.DataFrame
    raw_pvalue: float
    qvalue: float
    gate: dict[str, Any]


@dataclass(frozen=True)
class MarketInternalResearchResult:
    source_audit: pd.DataFrame
    family_source_audit: pd.DataFrame
    base_frame: pd.DataFrame
    base_feature_names: tuple[str, ...]
    target_names: tuple[str, ...]
    family_results: dict[str, FamilyEvaluation]
    fdr_table: pd.DataFrame
    admitted_families: tuple[str, ...]
    final_gate: dict[str, Any]


def _close_series(bars: Mapping[str, pd.DataFrame], symbol: str) -> pd.Series:
    return _normalise_bars(bars[symbol], symbol)["close"].rename(symbol)


def _rolling_zscore(series: pd.Series, window: int = 63) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def _rolling_percentile(series: pd.Series, window: int = 252) -> pd.Series:
    """Rank the current value against the last N observed values.

    Sparse source-calendar gaps remain missing on their own dates, but do not
    invalidate the following N exchange sessions.  This is observation-window
    arithmetic, not synthetic price backfilling.
    """

    def _last_rank(values: np.ndarray) -> float:
        if len(values) == 0 or not np.isfinite(values[-1]):
            return np.nan
        return float(np.mean(values <= values[-1]))

    observed = series.dropna()
    ranked = observed.rolling(window, min_periods=window).apply(
        _last_rank, raw=True
    )
    return ranked.reindex(series.index)


def _sessions_since_change(flag: pd.Series) -> pd.Series:
    clean = flag.fillna(False).astype(bool)
    changed = clean.ne(clean.shift(1))
    group = changed.cumsum()
    return clean.groupby(group).cumcount().astype(float)


def _ratio_distance_ma20(left: pd.Series, right: pd.Series) -> pd.Series:
    ratio = left / right.replace(0.0, np.nan)
    ma20 = ratio.rolling(20, min_periods=20).mean()
    return ratio / ma20 - 1.0


def _reference_gap(
    dates: pd.DatetimeIndex, reference: pd.DatetimeIndex
) -> int:
    if len(dates) < 2:
        return 0
    locations = reference.get_indexer(dates)
    locations = locations[locations >= 0]
    if len(locations) < 2:
        return 0
    return int(np.maximum(np.diff(locations) - 1, 0).max())


def audit_source_admissibility(
    bars: Mapping[str, pd.DataFrame],
    coverage: pd.DataFrame,
    fetch_errors: Mapping[str, str],
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Audit every source before any outcome calculation."""

    candidate_symbols: set[str] = set()
    for symbols in contract["data"]["candidate_symbols"].values():
        candidate_symbols.update(str(value).upper() for value in symbols)
    existing = {
        str(value).upper()
        for value in contract["data"]["existing_required_symbols"]
    }
    all_symbols = sorted(existing | candidate_symbols)
    coverage_by_symbol = (
        coverage.assign(symbol=coverage["symbol"].astype(str).str.upper())
        .set_index("symbol")
        if not coverage.empty
        else pd.DataFrame()
    )
    qqq = _normalise_bars(bars["QQQ"], "QQQ")
    reference = qqq.index
    maximum_missing = float(
        contract["data"]["coverage"]["maximum_missing_session_rate"]
    )
    maximum_gap = int(
        contract["data"]["coverage"][
            "maximum_unexplained_gap_trading_sessions"
        ]
    )
    rows: list[dict[str, Any]] = []
    for symbol in all_symbols:
        if symbol not in bars:
            rows.append(
                {
                    "symbol": symbol,
                    "provider": None,
                    "provider_symbol": None,
                    "first_date": None,
                    "last_date": None,
                    "rows": 0,
                    "duplicate_dates": None,
                    "positive_finite_prices": False,
                    "missing_session_rate": 1.0,
                    "maximum_unexplained_gap_sessions": None,
                    "fetch_error": fetch_errors.get(symbol, "missing bars"),
                    "admissible": False,
                    "rejection_reason": "fetch_failed",
                }
            )
            continue
        raw = bars[symbol].copy()
        duplicate_dates = bool(
            pd.to_datetime(raw["date"], errors="coerce")
            .dt.tz_localize(None)
            .dt.normalize()
            .duplicated()
            .any()
        )
        try:
            normalised = _normalise_bars(raw, symbol)
        except Exception as exc:
            rows.append(
                {
                    "symbol": symbol,
                    "provider": None,
                    "provider_symbol": None,
                    "first_date": None,
                    "last_date": None,
                    "rows": 0,
                    "duplicate_dates": duplicate_dates,
                    "positive_finite_prices": False,
                    "missing_session_rate": 1.0,
                    "maximum_unexplained_gap_sessions": None,
                    "fetch_error": str(exc),
                    "admissible": False,
                    "rejection_reason": "invalid_bars",
                }
            )
            continue
        first = normalised.index.min()
        last = normalised.index.max()
        relevant_reference = reference[
            (reference >= first) & (reference <= last)
        ]
        observed = normalised.index.intersection(relevant_reference)
        missing_rate = (
            1.0 - len(observed) / len(relevant_reference)
            if len(relevant_reference)
            else 1.0
        )
        maximum_observed_gap = _reference_gap(observed, relevant_reference)
        finite_positive = bool(
            np.isfinite(normalised[["open", "close"]].to_numpy()).all()
            and normalised[["open", "close"]].gt(0.0).all().all()
        )
        reasons: list[str] = []
        if duplicate_dates:
            reasons.append("duplicate_dates")
        if not finite_positive:
            reasons.append("non_positive_or_non_finite_price")
        if missing_rate > maximum_missing:
            reasons.append("missing_session_rate")
        if maximum_observed_gap > maximum_gap:
            reasons.append("unexplained_gap")
        provider = None
        provider_symbol = None
        if not coverage_by_symbol.empty and symbol in coverage_by_symbol.index:
            record = coverage_by_symbol.loc[symbol]
            provider = record.get("provider")
            provider_symbol = record.get("provider_symbol")
        rows.append(
            {
                "symbol": symbol,
                "provider": provider,
                "provider_symbol": provider_symbol,
                "first_date": first.date().isoformat(),
                "last_date": last.date().isoformat(),
                "rows": int(len(normalised)),
                "duplicate_dates": duplicate_dates,
                "positive_finite_prices": finite_positive,
                "missing_session_rate": float(missing_rate),
                "maximum_unexplained_gap_sessions": maximum_observed_gap,
                "fetch_error": fetch_errors.get(symbol),
                "admissible": not reasons,
                "rejection_reason": ",".join(reasons) if reasons else None,
            }
        )
    source_audit = pd.DataFrame(rows).sort_values("symbol").reset_index(
        drop=True
    )
    audit_lookup = source_audit.set_index("symbol")
    family_rows: list[dict[str, Any]] = []
    for family, specification in contract["families"].items():
        required = [
            str(value).upper() for value in specification["required_symbols"]
        ]
        unavailable = [
            symbol
            for symbol in required
            if symbol not in audit_lookup.index
            or not bool(audit_lookup.loc[symbol, "admissible"])
        ]
        family_rows.append(
            {
                "family": family,
                "required_symbols": ",".join(required),
                "unavailable_symbols": ",".join(unavailable),
                "admissible": not unavailable,
                "rejection_reason": (
                    f"inadmissible_sources:{','.join(unavailable)}"
                    if unavailable
                    else None
                ),
            }
        )
    return source_audit, pd.DataFrame(family_rows)


def build_market_internal_feature_blocks(
    bars: Mapping[str, pd.DataFrame],
    base_index: pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    """Build the four frozen complete feature blocks using close data only."""

    close = {
        symbol: _close_series(bars, symbol).reindex(base_index)
        for symbol in bars
    }
    blocks: dict[str, pd.DataFrame] = {}

    if {"^VIX9D", "^VIX", "^VIX3M", "^VVIX"}.issubset(close):
        vix9d = close["^VIX9D"]
        vix = close["^VIX"]
        vix3m = close["^VIX3M"]
        vvix = close["^VVIX"]
        front_ratio = vix9d / vix.replace(0.0, np.nan)
        three_month_ratio = vix / vix3m.replace(0.0, np.nan)
        inverted = three_month_ratio.gt(1.0)
        block = pd.DataFrame(index=base_index)
        block["vix9d_vix_ratio"] = front_ratio
        block["vix9d_vix_ratio_z63"] = _rolling_zscore(front_ratio)
        block["vix_vix3m_ratio"] = three_month_ratio
        block["vix_vix3m_ratio_z63"] = _rolling_zscore(three_month_ratio)
        block["volatility_curve_slope_front_three_month"] = (
            vix3m - vix9d
        ) / vix.replace(0.0, np.nan)
        block["vvix_percentile_252"] = _rolling_percentile(vvix)
        block["vvix_return_5d"] = vvix.pct_change(5)
        block["term_structure_inverted"] = inverted.astype(float)
        block["sessions_since_term_structure_inversion"] = (
            _sessions_since_change(inverted)
        )
        blocks["implied_volatility_term_structure"] = block

    if {"^VIX", "^VXN", "QQQ", "VOO"}.issubset(close):
        qqq_log = np.log(close["QQQ"]).diff()
        voo_log = np.log(close["VOO"]).diff()
        broad_realized = (
            voo_log.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252.0)
        )
        nasdaq_realized = (
            qqq_log.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252.0)
        )
        broad_implied = close["^VIX"] / 100.0
        nasdaq_implied = close["^VXN"] / 100.0
        broad_premium = broad_implied - broad_realized
        nasdaq_premium = nasdaq_implied - nasdaq_realized
        block = pd.DataFrame(index=base_index)
        block["broad_implied_minus_realized_vol_20d"] = broad_premium
        block["nasdaq_implied_minus_realized_vol_20d"] = nasdaq_premium
        block["broad_implied_realized_ratio_20d"] = (
            broad_implied / broad_realized.replace(0.0, np.nan)
        )
        block["nasdaq_implied_realized_ratio_20d"] = (
            nasdaq_implied / nasdaq_realized.replace(0.0, np.nan)
        )
        block["broad_volatility_risk_premium_return_5d"] = (
            broad_premium.diff(5)
        )
        block["nasdaq_volatility_risk_premium_return_5d"] = (
            nasdaq_premium.diff(5)
        )
        block["broad_volatility_risk_premium_percentile_252"] = (
            _rolling_percentile(broad_premium)
        )
        block["nasdaq_volatility_risk_premium_percentile_252"] = (
            _rolling_percentile(nasdaq_premium)
        )
        block["nasdaq_minus_broad_volatility_risk_premium"] = (
            nasdaq_premium - broad_premium
        )
        blocks["volatility_risk_premium"] = block

    if {"HYG", "LQD", "SHY", "IEF", "TLT"}.issubset(close):
        hyg_lqd = close["HYG"] / close["LQD"].replace(0.0, np.nan)
        hyg_shy = close["HYG"] / close["SHY"].replace(0.0, np.nan)
        lqd_ief = close["LQD"] / close["IEF"].replace(0.0, np.nan)
        tlt_shy = close["TLT"] / close["SHY"].replace(0.0, np.nan)
        credit_distance = _ratio_distance_ma20(close["HYG"], close["LQD"])
        duration_distance = _ratio_distance_ma20(close["TLT"], close["SHY"])
        block = pd.DataFrame(index=base_index)
        block["hyg_lqd_return_5d"] = hyg_lqd.pct_change(5)
        block["hyg_lqd_return_20d"] = hyg_lqd.pct_change(20)
        block["hyg_shy_return_20d"] = hyg_shy.pct_change(20)
        block["lqd_ief_return_20d"] = lqd_ief.pct_change(20)
        block["tlt_shy_return_20d"] = tlt_shy.pct_change(20)
        block["credit_risk_ratio_distance_ma20"] = credit_distance
        block["duration_risk_ratio_distance_ma20"] = duration_distance
        block["credit_duration_trend_agreement"] = (
            np.sign(credit_distance) == np.sign(duration_distance)
        ).astype(float)
        blocks["credit_duration_risk_appetite"] = block

    if {"SPY", "RSP", "IWM", "QQQ"}.issubset(close):
        rsp_spy = close["RSP"] / close["SPY"].replace(0.0, np.nan)
        iwm_spy = close["IWM"] / close["SPY"].replace(0.0, np.nan)
        rsp_distance = _ratio_distance_ma20(close["RSP"], close["SPY"])
        iwm_distance = _ratio_distance_ma20(close["IWM"], close["SPY"])
        qqq_trend = close["QQQ"].pct_change(20).gt(0.0)
        breadth_trend = rsp_spy.pct_change(20).gt(0.0)
        confirmation = qqq_trend.eq(breadth_trend)
        block = pd.DataFrame(index=base_index)
        block["rsp_spy_return_5d"] = rsp_spy.pct_change(5)
        block["rsp_spy_return_20d"] = rsp_spy.pct_change(20)
        block["iwm_spy_return_5d"] = iwm_spy.pct_change(5)
        block["iwm_spy_return_20d"] = iwm_spy.pct_change(20)
        block["rsp_spy_distance_ma20"] = rsp_distance
        block["iwm_spy_distance_ma20"] = iwm_distance
        block["breadth_size_trend_agreement"] = (
            np.sign(rsp_distance) == np.sign(iwm_distance)
        ).astype(float)
        block["breadth_confirmation_with_qqq"] = confirmation.astype(float)
        block["sessions_since_breadth_confirmation_change"] = (
            _sessions_since_change(confirmation)
        )
        blocks["breadth_size_participation"] = block

    return blocks


def _pipeline(alpha: float) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=alpha, fit_intercept=True)),
        ]
    )


def _embargo_train_end(
    index: pd.DatetimeIndex,
    test_start: pd.Timestamp,
    declared_train_end: pd.Timestamp,
    embargo_sessions: int,
) -> pd.Timestamp:
    location = int(index.searchsorted(test_start, side="left"))
    location = max(location - embargo_sessions - 1, 0)
    return min(declared_train_end, pd.Timestamp(index[location]))


def _quintile_spread(prediction: pd.Series, realized: pd.Series) -> float:
    table = pd.concat(
        [prediction.rename("prediction"), realized.rename("realized")], axis=1
    ).dropna()
    if len(table) < 10:
        return np.nan
    rank = table["prediction"].rank(pct=True, method="average")
    top = table.loc[rank.ge(0.80), "realized"]
    bottom = table.loc[rank.le(0.20), "realized"]
    if top.empty or bottom.empty:
        return np.nan
    return float(top.mean() - bottom.mean())


def _coefficient_frame(
    model: Pipeline,
    fold: str,
    model_name: str,
    features: Sequence[str],
    targets: Sequence[str],
) -> pd.DataFrame:
    ridge: Ridge = model.named_steps["model"]
    coefficients = np.asarray(ridge.coef_, dtype=float)
    rows: list[dict[str, Any]] = []
    for target_position, target in enumerate(targets):
        for feature_position, feature in enumerate(features):
            rows.append(
                {
                    "fold": fold,
                    "model": model_name,
                    "target": target,
                    "feature": feature,
                    "coefficient": float(
                        coefficients[target_position, feature_position]
                    ),
                }
            )
    return pd.DataFrame(rows)


def _cosine_stability(coefficients: pd.DataFrame) -> pd.DataFrame:
    candidate = coefficients.loc[coefficients["model"].eq("candidate")]
    if candidate.empty:
        return pd.DataFrame(
            columns=["fold_left", "fold_right", "cosine"]
        )
    pivot = candidate.pivot_table(
        index="fold", columns=["target", "feature"], values="coefficient"
    ).sort_index(axis=1)
    rows: list[dict[str, Any]] = []
    for left, right in combinations(pivot.index, 2):
        a = pivot.loc[left].to_numpy(dtype=float)
        b = pivot.loc[right].to_numpy(dtype=float)
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        rows.append(
            {
                "fold_left": left,
                "fold_right": right,
                "cosine": (
                    float(np.dot(a, b) / denominator)
                    if denominator > 1e-18
                    else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def _evaluate_family(
    family: str,
    base_frame: pd.DataFrame,
    base_features: Sequence[str],
    targets: Sequence[str],
    family_block: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    features = list(family_block.columns)
    frame = base_frame.join(family_block, how="left")
    prediction_parts: list[pd.DataFrame] = []
    coefficient_parts: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    alpha = float(contract["base_comparator"]["alpha"])
    minimum_training = int(contract["training"]["minimum_training_samples"])
    for specification in contract["outer_folds"]:
        fold = str(specification["fold"])
        test_start = pd.Timestamp(specification["test_start"])
        test_end = pd.Timestamp(specification["test_end"])
        train_start = pd.Timestamp(specification["train_start"])
        train_end = _embargo_train_end(
            frame.index,
            test_start,
            pd.Timestamp(specification["train_end"]),
            int(contract["training"]["embargo_sessions"]),
        )
        training = frame.loc[train_start:train_end].copy()
        training = training.loc[
            training["global_training_sample"].astype(bool)
        ]
        shared_train = training.dropna(
            subset=list(targets) + list(base_features) + features
        )
        testing = frame.loc[test_start:test_end].copy()
        shared_test = testing.dropna(
            subset=list(targets) + list(base_features) + features
        )
        source_rows.append(
            {
                "family": family,
                "fold": fold,
                "training_start": (
                    shared_train.index.min()
                    if not shared_train.empty
                    else pd.NaT
                ),
                "training_end": (
                    shared_train.index.max()
                    if not shared_train.empty
                    else pd.NaT
                ),
                "training_samples": int(len(shared_train)),
                "test_start": (
                    shared_test.index.min()
                    if not shared_test.empty
                    else pd.NaT
                ),
                "test_end": (
                    shared_test.index.max()
                    if not shared_test.empty
                    else pd.NaT
                ),
                "test_samples": int(len(shared_test)),
            }
        )
        if len(shared_train) < minimum_training or shared_test.empty:
            raise ValueError(
                f"{family} {fold} has insufficient shared samples: "
                f"train={len(shared_train)} test={len(shared_test)}"
            )
        baseline_model = _pipeline(alpha)
        candidate_model = _pipeline(alpha)
        baseline_model.fit(
            shared_train[list(base_features)],
            shared_train[list(targets)],
        )
        candidate_features = list(base_features) + features
        candidate_model.fit(
            shared_train[candidate_features],
            shared_train[list(targets)],
        )
        baseline_prediction = np.asarray(
            baseline_model.predict(shared_test[list(base_features)]),
            dtype=float,
        )
        candidate_prediction = np.asarray(
            candidate_model.predict(shared_test[candidate_features]),
            dtype=float,
        )
        output = shared_test[list(targets)].copy()
        output["fold"] = fold
        if "v4_2_execution_state" in shared_test.columns:
            state = shared_test["v4_2_execution_state"]
        elif "position_state" in shared_test.columns:
            state = shared_test["position_state"]
        else:
            state = pd.Series(np.nan, index=shared_test.index)
        output["position_state"] = pd.to_numeric(state, errors="coerce")
        for position, action in enumerate(ACTION_KEYS):
            output[f"base_predicted_{action}"] = baseline_prediction[:, position]
            output[f"candidate_predicted_{action}"] = candidate_prediction[
                :, position
            ]
        prediction_parts.append(output)
        coefficient_parts.append(
            _coefficient_frame(
                baseline_model,
                fold,
                "base",
                base_features,
                targets,
            )
        )
        coefficient_parts.append(
            _coefficient_frame(
                candidate_model,
                fold,
                "candidate",
                candidate_features,
                targets,
            )
        )
        action_deltas: list[float] = []
        for action, target in zip(ACTION_KEYS, targets):
            base_ic = output[f"base_predicted_{action}"].corr(
                output[target], method="spearman"
            )
            candidate_ic = output[f"candidate_predicted_{action}"].corr(
                output[target], method="spearman"
            )
            action_deltas.append(float(candidate_ic - base_ic))
        fold_rows.append(
            {
                "family": family,
                "fold": fold,
                "mean_action_ic_improvement": float(
                    np.nanmean(action_deltas)
                ),
                "actions_with_positive_ic_improvement": int(
                    np.sum(np.asarray(action_deltas) > 0.0)
                ),
            }
        )
    return (
        pd.concat(prediction_parts).sort_index(),
        pd.concat(coefficient_parts, ignore_index=True),
        pd.DataFrame(fold_rows),
        pd.DataFrame(source_rows),
        frame,
    )


def _metric_tables(
    family: str,
    predictions: pd.DataFrame,
    targets: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    action_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    for action, target in zip(ACTION_KEYS, targets):
        realized = predictions[target]
        base_prediction = predictions[f"base_predicted_{action}"]
        candidate_prediction = predictions[f"candidate_predicted_{action}"]
        base_ic = base_prediction.corr(realized, method="spearman")
        candidate_ic = candidate_prediction.corr(realized, method="spearman")
        base_spread = _quintile_spread(base_prediction, realized)
        candidate_spread = _quintile_spread(candidate_prediction, realized)
        action_rows.append(
            {
                "family": family,
                "action": action,
                "observations": int(realized.notna().sum()),
                "base_spearman_ic": float(base_ic),
                "candidate_spearman_ic": float(candidate_ic),
                "ic_improvement": float(candidate_ic - base_ic),
                "base_top_bottom_quintile_spread": base_spread,
                "candidate_top_bottom_quintile_spread": candidate_spread,
                "quintile_spread_improvement": float(
                    candidate_spread - base_spread
                ),
                "base_mae": float(
                    mean_absolute_error(realized, base_prediction)
                ),
                "candidate_mae": float(
                    mean_absolute_error(realized, candidate_prediction)
                ),
                "incremental_mae_improvement": float(
                    mean_absolute_error(realized, base_prediction)
                    - mean_absolute_error(realized, candidate_prediction)
                ),
                "base_r_squared": float(r2_score(realized, base_prediction)),
                "candidate_r_squared": float(
                    r2_score(realized, candidate_prediction)
                ),
                "incremental_oof_r_squared": float(
                    r2_score(realized, candidate_prediction)
                    - r2_score(realized, base_prediction)
                ),
            }
        )
        for state in (0, 1, 2):
            cell = predictions.loc[
                predictions["position_state"].eq(state)
            ]
            if len(cell) < 10:
                base_cell_ic = np.nan
                candidate_cell_ic = np.nan
                base_cell_spread = np.nan
                candidate_cell_spread = np.nan
            else:
                base_cell_ic = cell[f"base_predicted_{action}"].corr(
                    cell[target], method="spearman"
                )
                candidate_cell_ic = cell[
                    f"candidate_predicted_{action}"
                ].corr(cell[target], method="spearman")
                base_cell_spread = _quintile_spread(
                    cell[f"base_predicted_{action}"], cell[target]
                )
                candidate_cell_spread = _quintile_spread(
                    cell[f"candidate_predicted_{action}"], cell[target]
                )
            state_rows.append(
                {
                    "family": family,
                    "action": action,
                    "state": state,
                    "observations": int(len(cell)),
                    "base_spearman_ic": base_cell_ic,
                    "candidate_spearman_ic": candidate_cell_ic,
                    "ic_improvement": (
                        float(candidate_cell_ic - base_cell_ic)
                        if np.isfinite(base_cell_ic)
                        and np.isfinite(candidate_cell_ic)
                        else np.nan
                    ),
                    "base_top_bottom_quintile_spread": base_cell_spread,
                    "candidate_top_bottom_quintile_spread": candidate_cell_spread,
                    "quintile_spread_improvement": (
                        float(candidate_cell_spread - base_cell_spread)
                        if np.isfinite(base_cell_spread)
                        and np.isfinite(candidate_cell_spread)
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame(action_rows), pd.DataFrame(state_rows)


def _raw_family_pvalue(
    predictions: pd.DataFrame, targets: Sequence[str]
) -> float:
    positive = 0
    total = 0
    for _, group in predictions.groupby("fold"):
        for action, target in zip(ACTION_KEYS, targets):
            base_ic = group[f"base_predicted_{action}"].corr(
                group[target], method="spearman"
            )
            candidate_ic = group[f"candidate_predicted_{action}"].corr(
                group[target], method="spearman"
            )
            if np.isfinite(base_ic) and np.isfinite(candidate_ic):
                total += 1
                positive += int(candidate_ic > base_ic)
    if total == 0:
        return 1.0
    return float(
        binomtest(positive, total, p=0.5, alternative="greater").pvalue
    )


def benjamini_hochberg(
    pvalues: Mapping[str, float]
) -> pd.DataFrame:
    rows = sorted(
        ((family, float(value)) for family, value in pvalues.items()),
        key=lambda item: item[1],
    )
    n = len(rows)
    adjusted = [1.0] * n
    running = 1.0
    for position in range(n - 1, -1, -1):
        rank = position + 1
        running = min(running, rows[position][1] * n / rank)
        adjusted[position] = min(running, 1.0)
    return pd.DataFrame(
        [
            {
                "family": family,
                "raw_pvalue": pvalue,
                "qvalue": adjusted[position],
                "rank": position + 1,
            }
            for position, (family, pvalue) in enumerate(rows)
        ]
    )


def _family_gate(
    action_metrics: pd.DataFrame,
    state_metrics: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    coefficient_cosines: pd.DataFrame,
    predictions: pd.DataFrame,
    targets: Sequence[str],
    qvalue: float,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    threshold = contract["validation"]["family_admission"]
    ic_threshold = float(threshold["action_ic_improvement_threshold"])
    actions_ic = int(
        action_metrics["ic_improvement"].ge(ic_threshold).sum()
    )
    actions_spread = int(
        action_metrics["quintile_spread_improvement"].gt(0.0).sum()
    )
    large = action_metrics.loc[
        action_metrics["observations"].ge(
            int(threshold["large_action_observations_min"])
        )
    ]
    no_large_degradation = bool(
        large.empty
        or large["ic_improvement"]
        .ge(float(threshold["maximum_large_action_ic_degradation"]))
        .all()
    )
    state_cells = int(
        state_metrics["ic_improvement"].ge(ic_threshold).sum()
    )
    cosine_median = (
        float(coefficient_cosines["cosine"].median())
        if not coefficient_cosines.empty
        else np.nan
    )
    positive_eras = int(
        fold_metrics["mean_action_ic_improvement"].gt(0.0).sum()
    )
    era_values = fold_metrics.set_index("fold")[
        "mean_action_ic_improvement"
    ]
    without_best = (
        float(era_values.drop(index=era_values.idxmax()).sum())
        if len(era_values) > 1
        else np.nan
    )
    positive_values = era_values.clip(lower=0.0)
    positive_total = float(positive_values.sum())
    largest_era_share = (
        float(positive_values.max() / positive_total)
        if positive_total > 0.0
        else 1.0
    )
    cluster = predictions.copy()
    cluster["macro_cluster"] = (
        (cluster.index - cluster.index.min()).days // 30
    )
    improvements: list[pd.Series] = []
    for action, target in zip(ACTION_KEYS, targets):
        improvements.append(
            (
                (
                    cluster[target]
                    - cluster[f"base_predicted_{action}"]
                ).abs()
                - (
                    cluster[target]
                    - cluster[f"candidate_predicted_{action}"]
                ).abs()
            ).rename(action)
        )
    cluster["incremental_error_reduction"] = pd.concat(
        improvements, axis=1
    ).sum(axis=1)
    cluster_positive = (
        cluster.groupby("macro_cluster")[
            "incremental_error_reduction"
        ]
        .sum()
        .clip(lower=0.0)
    )
    cluster_total = float(cluster_positive.sum())
    largest_cluster_share = (
        float(cluster_positive.max() / cluster_total)
        if cluster_total > 0.0
        else 1.0
    )
    checks = {
        "fdr": qvalue <= float(threshold["fdr_qvalue_max"]),
        "actions_ic_improvement": actions_ic
        >= int(threshold["actions_ic_improvement_min"]),
        "actions_quintile_spread_improvement": actions_spread
        >= int(threshold["actions_quintile_spread_improvement_min"]),
        "no_large_action_ic_degradation": no_large_degradation,
        "action_state_cells_ic_improvement": state_cells
        >= int(threshold["action_state_cells_ic_improvement_min"]),
        "coefficient_stability": np.isfinite(cosine_median)
        and cosine_median
        >= float(threshold["coefficient_cosine_similarity_median_min"]),
        "positive_outer_eras": positive_eras
        >= int(threshold["positive_outer_eras_min"]),
        "improvement_without_best_year": np.isfinite(without_best)
        and (
            not bool(
                threshold["improvement_without_best_year_nonnegative"]
            )
            or without_best >= 0.0
        ),
        "single_era_concentration": largest_era_share
        <= float(threshold["maximum_single_era_positive_share"]),
        "macro_cluster_concentration": largest_cluster_share
        <= float(threshold["maximum_single_macro_cluster_positive_share"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "qvalue": qvalue,
            "actions_ic_improvement": actions_ic,
            "actions_quintile_spread_improvement": actions_spread,
            "action_state_cells_ic_improvement": state_cells,
            "coefficient_cosine_similarity_median": cosine_median,
            "positive_outer_eras": positive_eras,
            "improvement_without_best_year": without_best,
            "largest_positive_era_share": largest_era_share,
            "largest_positive_macro_cluster_share": largest_cluster_share,
        },
        "passed": bool(all(checks.values())),
    }


def run_market_internal_research(
    bars: Mapping[str, pd.DataFrame],
    coverage: pd.DataFrame,
    fetch_errors: Mapping[str, str],
    proxy_baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
    base_contract: Mapping[str, Any],
) -> MarketInternalResearchResult:
    """Run Phase 0 and Phase 1 only; no portfolio policy is constructed."""

    source_audit, family_source_audit = audit_source_admissibility(
        bars, coverage, fetch_errors, contract
    )
    base_frame, base_features, targets = build_action_advantage_frame(
        bars, proxy_baseline_daily, base_contract
    )
    blocks = build_market_internal_feature_blocks(bars, base_frame.index)
    provisional: dict[str, dict[str, Any]] = {}
    pvalues: dict[str, float] = {}
    family_source_lookup = family_source_audit.set_index("family")
    for family, specification in contract["families"].items():
        expected_features = tuple(
            str(value) for value in specification["minimum_feature_block"]
        )
        source_ok = bool(
            family_source_lookup.loc[family, "admissible"]
        )
        if not source_ok or family not in blocks:
            reason = str(
                family_source_lookup.loc[family, "rejection_reason"]
                or "feature_block_unavailable"
            )
            provisional[family] = {
                "admissible": False,
                "reason": reason,
                "features": expected_features,
                "feature_frame": pd.DataFrame(index=base_frame.index),
            }
            pvalues[family] = 1.0
            continue
        block = blocks[family].loc[:, list(expected_features)].copy()
        try:
            (
                predictions,
                coefficients,
                fold_metrics,
                source_fold_coverage,
                joined,
            ) = _evaluate_family(
                family,
                base_frame,
                base_features,
                targets,
                block,
                contract,
            )
        except ValueError as exc:
            provisional[family] = {
                "admissible": False,
                "reason": str(exc),
                "features": expected_features,
                "feature_frame": block,
            }
            pvalues[family] = 1.0
            continue
        action_metrics, state_metrics = _metric_tables(
            family, predictions, targets
        )
        cosines = _cosine_stability(coefficients)
        raw_pvalue = _raw_family_pvalue(predictions, targets)
        provisional[family] = {
            "admissible": True,
            "reason": None,
            "features": expected_features,
            "feature_frame": joined.loc[:, list(expected_features)],
            "predictions": predictions,
            "coefficients": coefficients,
            "fold_metrics": fold_metrics,
            "source_fold_coverage": source_fold_coverage,
            "action_metrics": action_metrics,
            "state_metrics": state_metrics,
            "cosines": cosines,
            "raw_pvalue": raw_pvalue,
        }
        pvalues[family] = raw_pvalue
    fdr = benjamini_hochberg(pvalues)
    qvalues = fdr.set_index("family")["qvalue"].to_dict()
    results: dict[str, FamilyEvaluation] = {}
    admitted: list[str] = []
    for family in contract["families"]:
        item = provisional[family]
        qvalue = float(qvalues[family])
        if not item["admissible"]:
            gate = {
                "checks": {"source_admissibility": False},
                "metrics": {
                    "qvalue": qvalue,
                    "rejection_reason": item["reason"],
                },
                "passed": False,
            }
            evaluation = FamilyEvaluation(
                family=family,
                admissible=False,
                rejection_reason=item["reason"],
                feature_names=tuple(item["features"]),
                feature_frame=item["feature_frame"],
                predictions=pd.DataFrame(),
                action_metrics=pd.DataFrame(),
                action_state_metrics=pd.DataFrame(),
                fold_metrics=pd.DataFrame(),
                fold_coefficients=pd.DataFrame(),
                coefficient_cosines=pd.DataFrame(),
                source_fold_coverage=pd.DataFrame(),
                raw_pvalue=float(pvalues[family]),
                qvalue=qvalue,
                gate=gate,
            )
        else:
            gate = _family_gate(
                item["action_metrics"],
                item["state_metrics"],
                item["fold_metrics"],
                item["cosines"],
                item["predictions"],
                targets,
                qvalue,
                contract,
            )
            evaluation = FamilyEvaluation(
                family=family,
                admissible=True,
                rejection_reason=None,
                feature_names=tuple(item["features"]),
                feature_frame=item["feature_frame"],
                predictions=item["predictions"],
                action_metrics=item["action_metrics"],
                action_state_metrics=item["state_metrics"],
                fold_metrics=item["fold_metrics"],
                fold_coefficients=item["coefficients"],
                coefficient_cosines=item["cosines"],
                source_fold_coverage=item["source_fold_coverage"],
                raw_pvalue=float(item["raw_pvalue"]),
                qvalue=qvalue,
                gate=gate,
            )
            if gate["passed"]:
                admitted.append(family)
        results[family] = evaluation
    final_gate = {
        "checks": {
            "phase_0_completed": bool(
                not source_audit.empty and not family_source_audit.empty
            ),
            "at_least_one_family_admitted": bool(admitted),
            "no_portfolio_policy_evaluated": True,
        },
        "metrics": {
            "families_tested": len(contract["families"]),
            "source_admissible_families": int(
                family_source_audit["admissible"].sum()
            ),
            "admitted_families": admitted,
        },
        "passed": bool(admitted),
    }
    return MarketInternalResearchResult(
        source_audit=source_audit,
        family_source_audit=family_source_audit,
        base_frame=base_frame,
        base_feature_names=tuple(base_features),
        target_names=tuple(targets),
        family_results=results,
        fdr_table=fdr,
        admitted_families=tuple(admitted),
        final_gate=final_gate,
    )
