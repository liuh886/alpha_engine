"""Governed current-target inference for the accepted CN x1.2 ranker."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data.market_provider import load_provider_manifest
from src.research.cn130_cross_sectional_ranking import load_provider_panel
from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    clamped_active_share,
    regime_signal,
)
from src.research.cn_x1_2_prospective import (
    FROZEN_TRAIN_END,
    FROZEN_TRAIN_START,
    MODEL_ID,
    _load_frozen_contract,
)
from src.research.cn_ranker_exact_portfolio_replay import _portfolio_contract
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.ranker_current_target import (
    _factor_summary,
    _select_cn_sector_breadth,
    _signal_payload,
    load_previous_state,
)
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION as RETURN_EXPRESSION,
    benchmark_instrument,
    resolve_symbols,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import purge_training_tail
from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime

MODEL_FAMILY_ID = "cn_ranker"
MODEL_CONFIG = Path("configs/models/cn_x1_2.yaml")
BENCHMARK = "000300"
HOLDING_SESSIONS = 10


class CNX12CurrentTargetError(ValueError):
    """Raised when the frozen CN x1.2 target cannot be reproduced exactly."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _formal_identity(
    *,
    formal_manifest: Path,
    formal_portfolio: Path,
    provider_dir: Path,
    repository_root: Path,
) -> dict[str, Any]:
    import json

    manifest = json.loads(formal_manifest.read_text(encoding="utf-8"))
    if (
        manifest.get("model_version_id") != MODEL_ID
        or manifest.get("publication_channel") != "formal"
        or manifest.get("publication_status") != "accepted_formal_baseline"
    ):
        raise CNX12CurrentTargetError("CN x1.2 formal manifest identity is invalid")
    provider = load_provider_manifest(
        provider_dir,
        expected_market="cn",
        required=True,
        verify_files=True,
    )
    if provider is None:
        raise CNX12CurrentTargetError("CN provider manifest is unavailable")
    config_path = repository_root / MODEL_CONFIG
    return {
        "formal_bundle_id": manifest.get("bundle_id"),
        "formal_run_id": manifest.get("run_id"),
        "formal_model_id": MODEL_ID,
        "formal_evidence_cutoff": manifest.get("evidence_cutoff"),
        "formal_manifest_sha256": _sha256(formal_manifest),
        "formal_portfolio_sha256": _sha256(formal_portfolio),
        "model_config_path": MODEL_CONFIG.as_posix(),
        "model_config_sha256": _sha256(config_path),
        "provider_identity_sha256": provider["provider_identity_sha256"],
    }


def _classification_sector(
    classification: Mapping[str, Mapping[str, Any]], instrument: str
) -> str:
    key = str(instrument).zfill(6)
    row = classification.get(key)
    if not isinstance(row, Mapping) or not row.get("sector"):
        raise CNX12CurrentTargetError(f"CN x1.2 sector is missing for {instrument}")
    return str(row["sector"])


def score_cn_x1_2_current_target(
    *,
    provider_dir: Path,
    formal_manifest: Path,
    formal_portfolio: Path,
    ledger_dir: Path,
    signal_date: str,
    market_cutoff: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Refit only the frozen training window and score one current CN130 cross-section."""

    root = repository_root.resolve()
    spec, candidate, factor_contract = _load_frozen_contract(root)
    runtime = QlibCNExecutionRuntime(provider_uri=provider_dir)
    runtime.initialize(root)

    symbols = [str(value).zfill(6) for value in resolve_symbols(spec, runtime)]
    benchmark = str(benchmark_instrument(spec, runtime)).zfill(6)
    if len(symbols) != 130 or len(set(symbols)) != 130 or benchmark != BENCHMARK:
        raise CNX12CurrentTargetError("CN x1.2 current universe or benchmark drifted")

    classification, classification_sha256 = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise CNX12CurrentTargetError("CN x1.2 current universe differs from classification")

    expressions = tuple(str(value) for value in factor_contract["expressions"])
    factor_ids = [str(value) for value in factor_contract["factor_ids"]]
    if len(expressions) != 17 or len(factor_ids) != 17:
        raise CNX12CurrentTargetError("CN x1.2 current target must retain exactly 17 factors")
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(expressions)
    }
    factor_columns = {
        factor_id: expression_columns[expression]
        for factor_id, expression in zip(factor_ids, expressions, strict=True)
    }

    signal_ts = pd.Timestamp(signal_date).normalize()
    if signal_ts <= pd.Timestamp(FROZEN_TRAIN_END):
        raise CNX12CurrentTargetError("CN x1.2 current signal must be after the frozen training boundary")

    features_all = normalize_qlib_frame_index(
        runtime.features(symbols, expressions, FROZEN_TRAIN_START, signal_date)
    ).replace([np.inf, -np.inf], np.nan)
    features_all.columns = [expression_columns[item] for item in expressions]
    returns_all = normalize_qlib_frame_index(
        runtime.features(symbols, [RETURN_EXPRESSION], FROZEN_TRAIN_START, FROZEN_TRAIN_END)
    ).replace([np.inf, -np.inf], np.nan)
    returns_all.columns = ["return"]

    feature_dates = features_all.index.get_level_values("datetime")
    train_mask = feature_dates <= pd.Timestamp(FROZEN_TRAIN_END)
    test_mask = feature_dates == signal_ts
    features_train, returns_train = purge_training_tail(
        features_all.loc[train_mask].copy(),
        returns_all.copy(),
        holding_days=HOLDING_SESSIONS,
    )
    features_test = features_all.loc[test_mask].copy()
    if len(features_test) != len(symbols):
        raise CNX12CurrentTargetError(
            f"CN x1.2 current cross-section has {len(features_test)} rows; expected {len(symbols)}"
        )

    scores = fit_predict_ranker_scores(
        expressions=expressions,
        expression_columns=expression_columns,
        features_train=features_train,
        returns_train=returns_train,
        features_test=features_test,
        calibration=candidate.calibration,
        context=f"CN x1.2 current target/{signal_date}",
    )
    day = scores.reset_index()
    day["instrument"] = day["instrument"].astype(str).str.zfill(6)
    day["sector"] = day["instrument"].map(
        lambda value: _classification_sector(classification, value)
    )

    panel = load_provider_panel(provider_dir, [*symbols, BENCHMARK], fields=("close",))
    gate = RegimeGateSpec()
    state = build_regime_state(
        panel.fields["close"],
        symbols=symbols,
        benchmark=BENCHMARK,
        long_ma_sessions=gate.long_ma_sessions,
        momentum_sessions=gate.momentum_sessions,
        breadth_ma_sessions=gate.breadth_ma_sessions,
        breadth_threshold=gate.breadth_threshold,
    )
    if signal_ts not in state.index:
        raise CNX12CurrentTargetError(f"CN x1.2 regime state is missing {signal_date}")
    state_row = state.loc[signal_ts]
    eligible = regime_signal(state, signal_ts, "two_of_three")
    active_share = (
        clamped_active_share(float(state_row["breadth_value"]), gate.breadth_threshold)
        if eligible
        else 0.0
    )

    chosen = _select_cn_sector_breadth(
        day,
        sectors=gate.sectors,
        names_per_sector=gate.names_per_sector,
    )
    expected = gate.sectors * gate.names_per_sector
    if len(chosen) != expected or not chosen["instrument"].is_unique:
        raise CNX12CurrentTargetError("CN x1.2 sector-breadth selection is incomplete")
    selected = [str(value).zfill(6) for value in chosen["instrument"]]

    target: dict[str, float] = {}
    if active_share > 0.0:
        name_weight = active_share / len(selected)
        target.update({symbol: name_weight for symbol in selected})
    benchmark_weight = 1.0 - active_share
    if benchmark_weight > 1e-12:
        target[BENCHMARK] = benchmark_weight
    if abs(sum(target.values()) - 1.0) > 1e-9:
        raise CNX12CurrentTargetError("CN x1.2 target weights do not sum to one")

    previous_date, previous = load_previous_state(
        formal_package=formal_portfolio,
        ledger_dir=ledger_dir,
    )
    reference_weight = 1.0 / len(selected)
    factor_reference = {symbol: reference_weight for symbol in selected}
    factor_evidence = _factor_summary(
        model_family_id=MODEL_FAMILY_ID,
        signal_date=signal_date,
        target_weights=factor_reference,
        features=features_test,
        factor_columns=factor_columns,
    )

    return _signal_payload(
        model_version_id=MODEL_ID,
        model_family_id=MODEL_FAMILY_ID,
        signal_date=signal_date,
        market_cutoff=market_cutoff,
        previous_weights=previous,
        target_weights=target,
        factor_evidence=factor_evidence,
        model_identity=_formal_identity(
            formal_manifest=formal_manifest,
            formal_portfolio=formal_portfolio,
            provider_dir=provider_dir,
            repository_root=root,
        ),
        reason_code=(
            "cn_x1_2_breadth_scaled_risk_on"
            if active_share > 0.0
            else "cn_x1_2_csi300_risk_off"
        ),
        diagnostics={
            "previous_signal_date": previous_date,
            "train_start": FROZEN_TRAIN_START,
            "train_end": FROZEN_TRAIN_END,
            "selected_candidate": "cn_x1_2_alpha158_breadth_scaled",
            "factor_count": len(factor_ids),
            "classification_sha256": classification_sha256,
            "risk_on_eligible": bool(eligible),
            "active_share": active_share,
            "benchmark_sleeve": benchmark_weight,
            "votes": int(state_row["votes"]),
            "long_trend": bool(state_row["long_trend"]),
            "medium_momentum": bool(state_row["medium_momentum"]),
            "cross_sectional_breadth": bool(state_row["cross_sectional_breadth"]),
            "breadth_value": float(state_row["breadth_value"]),
            "selected_names": selected,
            "model_selection_reopened": False,
        },
    )
