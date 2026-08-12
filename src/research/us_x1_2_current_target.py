"""Governed current-target inference for the formal US x1.2 ranker."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

import scripts.run_us_x1_1_rank_aware_sector_cap as sector_cap
from src.data.market_provider import load_provider_manifest
from src.factors.model_contract import resolve_model_factor_inputs
from src.research.daily_ranker import prepare_ranker_frame
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.ranker_current_target import (
    _explanation_summary,
    _factor_summary,
    _signal_payload,
    load_previous_state,
)
from src.research.rolling_windows import purge_training_tail
from src.research.universe_robustness import validate_no_nan_inputs
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime
from src.research.xgb_native_calibration import (
    XGBNativeCalibration,
    fit_xgb_native_daily_ranker,
    predict_xgb_native_daily_ranker,
)
from src.research.xgb_ranker_explainability import (
    attach_factor_contributions,
    build_xgb_pred_contribs,
)

MODEL_ID = "us_x1_2"
MODEL_FAMILY_ID = "us_ranker"
MODEL_CONFIG = Path("configs/models/us_x1_2.yaml")
UNIVERSE_CONFIG = Path("configs/research_universes/us_selected_equities_v2.yaml")
CLASSIFICATION_CONFIG = Path("configs/research_classifications/us87_sector_industry_v1.yaml")
FACTOR_LIBRARY = Path("configs/factor_libraries/ohlcv.yaml")


class USX12CurrentTargetError(ValueError):
    """Raised when the formal US x1.2 target cannot be reproduced exactly."""


def _yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise USX12CurrentTargetError(f"expected YAML mapping: {path}")
    return value


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise USX12CurrentTargetError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _calibration(config: Mapping[str, Any]) -> XGBNativeCalibration:
    model = dict(config.get("model") or {})
    label = dict(config.get("label") or {})
    fields = {
        "n_gain_bins": label.get("gain_bins"),
        "num_boost_round": model.get("num_boost_round"),
        "max_leaves": model.get("max_leaves"),
        "max_depth": model.get("max_depth"),
        "min_child_weight": model.get("min_child_weight"),
        "learning_rate": model.get("learning_rate"),
        "subsample": model.get("subsample"),
        "colsample_bytree": model.get("colsample_bytree"),
        "reg_alpha": model.get("reg_alpha"),
        "reg_lambda": model.get("reg_lambda"),
        "seed": model.get("seed"),
    }
    if any(value is None for value in fields.values()):
        raise USX12CurrentTargetError("US x1.2 native XGBoost contract is incomplete")
    return XGBNativeCalibration.from_dict(fields)


def _symbols(
    root: Path,
    config: Mapping[str, Any],
    runtime: QlibUSExecutionRuntime,
) -> list[str]:
    universe = _yaml(root / UNIVERSE_CONFIG)
    requested = [str(value) for value in universe.get("symbols", [])]
    expected = int(universe.get("candidate_count", 0))
    declared = dict(config.get("universe") or {})
    if declared.get("universe_id") != universe.get("pool_id"):
        raise USX12CurrentTargetError("US x1.2 universe identity drifted")
    normalized = normalize_market_symbols(
        "us",
        requested,
        available_symbols=runtime.available_symbols(),
    )
    symbols = [value.normalized_symbol for value in normalized]
    if len(symbols) != expected or len(symbols) != len(set(symbols)):
        raise USX12CurrentTargetError("US x1.2 universe is incomplete")
    return symbols


def _sectors(root: Path, symbols: list[str]) -> dict[str, str]:
    payload = _yaml(root / CLASSIFICATION_CONFIG)
    records = payload.get("records")
    if not isinstance(records, dict):
        raise USX12CurrentTargetError("US x1.2 sector classification is invalid")
    sectors = {
        str(symbol): str(record["sector"])
        for symbol, record in records.items()
        if isinstance(record, dict) and record.get("sector")
    }
    missing = sorted(set(symbols) - set(sectors))
    if missing:
        raise USX12CurrentTargetError(f"US x1.2 sectors are incomplete: {missing}")
    return {symbol: sectors[symbol] for symbol in symbols}


def _factor_contract(
    root: Path,
    config: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    try:
        return resolve_model_factor_inputs(
            root=root,
            features=dict(config.get("features") or {}),
            expected_library=FACTOR_LIBRARY,
            expected_count=7,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise USX12CurrentTargetError(str(exc)) from exc


def _factor_columns(
    *,
    factor_ids: list[str],
    columns: list[str],
) -> dict[str, str]:
    if not factor_ids or len(factor_ids) != len(columns):
        raise USX12CurrentTargetError("US x1.2 factor identity is not one-to-one")
    if len(factor_ids) != len(set(factor_ids)):
        raise USX12CurrentTargetError("US x1.2 factor identity contains duplicates")
    return dict(zip(factor_ids, columns, strict=True))


def _formal_identity(
    *,
    manifest_path: Path,
    model_config_path: Path,
    provider_dir: Path,
) -> dict[str, Any]:
    manifest = _json(manifest_path)
    if (
        manifest.get("model_version_id") != MODEL_ID
        or manifest.get("publication_channel") != "formal"
        or manifest.get("publication_status") != "accepted_formal_baseline"
    ):
        raise USX12CurrentTargetError("US x1.2 formal manifest identity is invalid")
    provider = load_provider_manifest(
        provider_dir,
        expected_market="us",
        required=True,
        verify_files=True,
    )
    if provider is None:
        raise USX12CurrentTargetError("US provider manifest is unavailable")
    return {
        "formal_bundle_id": manifest.get("bundle_id"),
        "formal_run_id": manifest.get("run_id"),
        "formal_model_id": MODEL_ID,
        "formal_evidence_cutoff": manifest.get("evidence_cutoff"),
        "formal_manifest_sha256": _sha256(manifest_path),
        "model_config_path": MODEL_CONFIG.as_posix(),
        "model_config_sha256": _sha256(model_config_path),
        "provider_identity_sha256": provider["provider_identity_sha256"],
    }


def score_us_x1_2_current_target(
    *,
    provider_dir: Path,
    formal_manifest: Path,
    formal_portfolio: Path,
    ledger_dir: Path,
    signal_date: str,
    market_cutoff: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Refit the frozen sampled XGBoost contract and select Top-15 with sector cap."""

    root = repository_root.resolve()
    config_path = root / MODEL_CONFIG
    config = _yaml(config_path)
    if config.get("model_id") != MODEL_ID:
        raise USX12CurrentTargetError("US x1.2 model config identity changed")
    lineage = dict(config.get("lineage") or {})
    if lineage.get("selected_candidate") != "r11_sampled":
        raise USX12CurrentTargetError("US x1.2 selected candidate changed")
    strategy = dict(config.get("strategy") or {})
    if (
        int(strategy.get("holding_sessions", 0)) != 10
        or int(strategy.get("rebalance_sessions", 0)) != 10
        or int(strategy.get("top_n", 0)) != 15
        or int(strategy.get("maximum_names_per_sector", 0)) != 4
        or int(strategy.get("cost_bps", 0)) != 20
    ):
        raise USX12CurrentTargetError("US x1.2 portfolio contract changed")

    calibration = _calibration(config)
    factor_ids, expressions = _factor_contract(root, config)

    runtime = QlibUSExecutionRuntime(provider_uri=provider_dir)
    runtime.initialize(root)
    symbols = _symbols(root, config, runtime)
    sectors = _sectors(root, symbols)

    signal_ts = pd.Timestamp(signal_date)
    half_start = pd.Timestamp(f"{signal_ts.year}-{'01-01' if signal_ts.month <= 6 else '07-01'}")
    train_start = "2021-01-01"
    train_end = (half_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    features = normalize_qlib_frame_index(
        runtime.features(symbols, expressions, train_start, signal_date)
    ).replace([np.inf, -np.inf], np.nan)
    columns = [f"feature_{index}" for index in range(len(expressions))]
    features.columns = columns
    return_expression = str(dict(config.get("label") or {}).get("economic_return_expression") or "")
    if not return_expression:
        raise USX12CurrentTargetError("US x1.2 economic return expression is missing")
    returns = normalize_qlib_frame_index(
        runtime.features(symbols, [return_expression], train_start, train_end)
    )
    returns.columns = ["return"]

    dates = features.index.get_level_values("datetime")
    train_features, train_returns = purge_training_tail(
        features.loc[dates <= pd.Timestamp(train_end)].copy(),
        returns.copy(),
        holding_days=10,
    )
    valid, reason = validate_no_nan_inputs(
        train_features,
        context=f"US x1.2 current target/{signal_date}",
    )
    if not valid:
        raise USX12CurrentTargetError(reason)
    test_features = features.loc[dates == signal_ts].copy()
    if len(test_features) != len(symbols):
        raise USX12CurrentTargetError(
            f"US x1.2 current cross-section has {len(test_features)} rows; expected {len(symbols)}"
        )

    x_rank, y_rank, groups = prepare_ranker_frame(train_features, train_returns)
    fitted = fit_xgb_native_daily_ranker(
        x_rank,
        y_rank,
        groups,
        calibration=calibration,
    )
    scores = predict_xgb_native_daily_ranker(fitted, test_features)
    ranked = sector_cap._ranked_day(scores.reset_index(), signal_ts)
    selected, selection, _ = sector_cap._select_names(ranked, sectors, sector_cap=True)
    if len(selected) != 15:
        raise USX12CurrentTargetError("US x1.2 sector-cap selection did not fill 15 names")
    target = {instrument: 1.0 / 15.0 for instrument in selected}
    previous_date, previous = load_previous_state(
        formal_package=formal_portfolio,
        ledger_dir=ledger_dir,
    )

    factor_columns = _factor_columns(factor_ids=factor_ids, columns=columns)
    factor_evidence = _factor_summary(
        model_family_id=MODEL_FAMILY_ID,
        signal_date=signal_date,
        target_weights=target,
        features=test_features,
        factor_columns=factor_columns,
    )
    explanations = build_xgb_pred_contribs(
        model=fitted.model,
        features=test_features,
        scores=scores,
        column_to_factor_id={column: factor_id for factor_id, column in factor_columns.items()},
        instruments=selected,
        decision_role="selected_holding",
    )
    factor_evidence = attach_factor_contributions(factor_evidence, explanations)
    rank_by_name = selection.set_index("instrument")["rank"].to_dict()

    signal = _signal_payload(
        model_version_id=MODEL_ID,
        model_family_id=MODEL_FAMILY_ID,
        signal_date=signal_date,
        market_cutoff=market_cutoff,
        previous_weights=previous,
        target_weights=target,
        factor_evidence=factor_evidence,
        model_identity=_formal_identity(
            manifest_path=formal_manifest,
            model_config_path=config_path,
            provider_dir=provider_dir,
        ),
        reason_code="formal_us_x1_2_10_session_rebalance",
        diagnostics={
            "previous_signal_date": previous_date,
            "train_start": train_start,
            "train_end": train_end,
            "selected_candidate": "r11_sampled",
            "calibration_identity": fitted.identity_manifest,
            "top_n": 15,
            "maximum_names_per_sector": 4,
            "selected_ranks": {name: int(rank_by_name[name]) for name in selected},
            "model_explanations": _explanation_summary(explanations),
        },
    )
    return signal
