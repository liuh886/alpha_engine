"""Deterministic prospective score ledger for the accepted CN x1.2 model.

The adapter replays the exact promoted 17-factor signal and frozen XGBoost
calibration.  Training is permanently capped at the original 2026-06-30
development boundary; sessions from 2026-07-01 onward are reporting-only and
can never enter model selection or parameter fitting.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.cn130_cross_sectional_ranking import (
    forward_returns,
    load_provider_panel,
    stack_return_frame,
)
from src.research.cn_ranker_exact_portfolio_replay import (
    BENCHMARK,
    _candidate_factor_contracts,
    _frame_hash,
    _ledger,
    _portfolio_contract,
)
from src.research.cn_x1_2_breadth_scaled_development import (
    CHALLENGER_EXPOSURE_POLICY,
    CHALLENGER_RULE,
    DEVELOPMENT_HARD_STOP,
    DEVELOPMENT_RUNNER_ID,
    POOL_SIZE,
)
from src.research.cross_sectional_experiment_runner import (
    CrossSectionalExperimentSpec,
    load_cross_sectional_experiment_spec,
)
from src.research.qlib_execution_common import ExecutionRuntime, normalize_qlib_frame_index
from src.research.ranker_execution import (
    TEN_SESSION_RETURN_EXPRESSION as RETURN_EXPRESSION,
    benchmark_instrument,
    resolve_symbols,
)
from src.research.ranker_training import fit_predict_ranker_scores
from src.research.rolling_windows import RollingResearchWindow, purge_training_tail

MODEL_ID = "cn_x1_2"
CANDIDATE_ID = "cn_x1_2_alpha158_breadth_scaled"
SPEC_PATH = Path("configs/research_experiments/cn_x1_2_alpha158_breadth_scaled_v1.yaml")
REPORTING_WINDOW = "2026H2_PARTIAL"
REPORTING_START = pd.Timestamp("2026-07-01")
HOLDING_SESSIONS = 10
EXECUTION_DELAY_SESSIONS = 1
FROZEN_TRAIN_START = "2021-01-01"
FROZEN_TRAIN_END = "2026-06-30"
FROZEN_BENCHMARK = "000300"
FROZEN_POOL_SIZE = 130
FROZEN_CONTRACT_SHA256 = "a2d3a327e5fc02e62e884642f61dbbedbe27274c7f8804d542bbef9d8ef87e82"


def _validate_frozen_signal_identity(
    *,
    factor_contract: dict[str, Any],
    calibration_identity: dict[str, Any],
    train_start: str,
    regime_rule: str,
    exposure_policy: str,
) -> None:
    payload = {
        "candidate_id": CANDIDATE_ID,
        "train_start": train_start,
        "train_end": FROZEN_TRAIN_END,
        "factor_contract": {
            "factor_ids": list(factor_contract["factor_ids"]),
            "expressions": list(factor_contract["expressions"]),
            "implementation_hashes": dict(factor_contract["implementation_hashes"]),
            "library_sources": list(factor_contract["library_sources"]),
        },
        "calibration": calibration_identity,
        "regime_rule": regime_rule,
        "exposure_policy": exposure_policy,
        "holding_sessions": HOLDING_SESSIONS,
        "execution_delay_sessions": EXECUTION_DELAY_SESSIONS,
    }
    observed = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if observed != FROZEN_CONTRACT_SHA256:
        raise ValueError("CN x1.2 frozen factor, calibration or training identity drifted")


def _load_frozen_contract(
    repository_root: Path,
) -> tuple[CrossSectionalExperimentSpec, Any, dict[str, Any]]:
    if repository_root.resolve() != PROJECT_ROOT.resolve():
        raise ValueError("CN x1.2 prospective adapter must run from its repository root")
    spec = load_cross_sectional_experiment_spec(repository_root / SPEC_PATH)
    if (
        spec.market != "cn"
        or str(spec.raw.get("development_runner") or "") != DEVELOPMENT_RUNNER_ID
        or spec.raw.get("research_only") is not True
        or spec.raw.get("trade_ready") is not False
    ):
        raise ValueError("CN x1.2 frozen research contract identity drifted")
    candidates = [candidate for candidate in spec.candidates if candidate.candidate_id == CANDIDATE_ID]
    if len(candidates) != 1:
        raise ValueError("CN x1.2 promoted candidate identity is ambiguous")
    raw_candidates = {
        str(row.get("candidate_id")): row
        for row in spec.raw.get("candidates", [])
        if isinstance(row, dict)
    }
    raw = raw_candidates.get(CANDIDATE_ID, {})
    if (
        CHALLENGER_RULE != "two_of_three"
        or CHALLENGER_EXPOSURE_POLICY != "breadth_scaled"
        or DEVELOPMENT_HARD_STOP != pd.Timestamp(FROZEN_TRAIN_END)
        or POOL_SIZE != FROZEN_POOL_SIZE
        or BENCHMARK != FROZEN_BENCHMARK
        or raw.get("regime_rule") != CHALLENGER_RULE
        or raw.get("exposure_policy") != CHALLENGER_EXPOSURE_POLICY
    ):
        raise ValueError("CN x1.2 promoted portfolio policy drifted")
    factor_contract = _candidate_factor_contracts(spec)[CANDIDATE_ID]
    _validate_frozen_signal_identity(
        factor_contract=factor_contract,
        calibration_identity=candidates[0].calibration.identity_manifest(),
        train_start=str(spec.parent.walk_forward["requested_train_start"]),
        regime_rule=str(raw["regime_rule"]),
        exposure_policy=str(raw["exposure_policy"]),
    )
    return spec, candidates[0], factor_contract


def _reporting_dates(runtime: ExecutionRuntime, cutoff: str) -> pd.DatetimeIndex:
    cutoff_at = pd.Timestamp(cutoff)
    if cutoff_at < REPORTING_START:
        raise ValueError("CN x1.2 prospective cutoff precedes the reporting boundary")
    calendar = pd.DatetimeIndex(
        runtime.calendar(REPORTING_START.strftime("%Y-%m-%d"), cutoff_at.strftime("%Y-%m-%d"))
    ).normalize()
    calendar = pd.DatetimeIndex(sorted(set(calendar)))
    required_tail = HOLDING_SESSIONS + EXECUTION_DELAY_SESSIONS
    if len(calendar) <= required_tail:
        raise ValueError("CN x1.2 reporting range has no realized 10-session horizon")
    dates = calendar[:-required_tail]
    if dates.empty:
        raise ValueError("CN x1.2 reporting evaluation dates are empty")
    return dates


def build_cn_x1_2_prospective_ledger(
    *,
    repository_root: Path,
    provider_dir: Path,
    cutoff: str,
    output: Path,
    runtime: ExecutionRuntime | None = None,
) -> dict[str, Any]:
    """Build one exact, reporting-only CN x1.2 score and return ledger."""

    spec, candidate, factor_contract = _load_frozen_contract(repository_root)
    if runtime is None:
        from src.research.cn_qlib_execution_adapter import QlibCNExecutionRuntime

        runtime = QlibCNExecutionRuntime(provider_uri=provider_dir)
    runtime.initialize(repository_root)

    symbols = [str(value).zfill(6) for value in resolve_symbols(spec, runtime)]
    if len(symbols) != FROZEN_POOL_SIZE or len(set(symbols)) != FROZEN_POOL_SIZE:
        raise ValueError("CN x1.2 prospective universe must be exact CN130")
    benchmark = str(benchmark_instrument(spec, runtime)).zfill(6)
    if benchmark != FROZEN_BENCHMARK:
        raise ValueError(f"CN x1.2 benchmark drifted: {benchmark}")
    classification, classification_sha256 = _portfolio_contract(spec)
    if set(symbols) != set(classification):
        raise ValueError("CN x1.2 universe differs from the governed classification")

    expressions = tuple(str(value) for value in factor_contract["expressions"])
    if len(expressions) != 17:
        raise ValueError("CN x1.2 prospective signal must retain exactly 17 factors")
    expression_columns = {
        expression: f"feature_{index}" for index, expression in enumerate(expressions)
    }
    evaluation_dates = _reporting_dates(runtime, cutoff)
    window = RollingResearchWindow(
        label=REPORTING_WINDOW,
        train_start=str(spec.parent.walk_forward["requested_train_start"]),
        train_end=FROZEN_TRAIN_END,
        test_start=REPORTING_START.strftime("%Y-%m-%d"),
        test_end=pd.Timestamp(cutoff).strftime("%Y-%m-%d"),
    )

    features_all = normalize_qlib_frame_index(
        runtime.features(symbols, expressions, window.train_start, window.test_end)
    ).replace([np.inf, -np.inf], np.nan)
    features_all.columns = [expression_columns[item] for item in expressions]
    returns_all = normalize_qlib_frame_index(
        runtime.features(symbols, [RETURN_EXPRESSION], window.train_start, window.test_end)
    ).replace([np.inf, -np.inf], np.nan)
    returns_all.columns = ["return"]
    returns_all.attrs.update(
        {
            "provenance": "raw_forward_return",
            "horizon": HOLDING_SESSIONS,
            "expression": RETURN_EXPRESSION,
        }
    )
    all_dates = features_all.index.get_level_values("datetime")
    train_mask = (all_dates >= pd.Timestamp(window.train_start)) & (
        all_dates <= pd.Timestamp(FROZEN_TRAIN_END)
    )
    test_mask = all_dates.isin(evaluation_dates)
    features_train, returns_train = purge_training_tail(
        features_all.loc[train_mask].copy(),
        returns_all.loc[train_mask].copy(),
        holding_days=HOLDING_SESSIONS,
    )
    features_test = features_all.loc[test_mask].copy()
    if features_test.empty:
        raise ValueError("CN x1.2 reporting features are empty")

    scores = fit_predict_ranker_scores(
        expressions=expressions,
        expression_columns=expression_columns,
        features_train=features_train,
        returns_train=returns_train,
        features_test=features_test,
        calibration=candidate.calibration,
        context="CN x1.2 prospective reporting-only frozen signal",
    )
    panel = load_provider_panel(provider_dir, symbols, fields=("close",))
    execution_wide = forward_returns(
        panel.fields["close"],
        horizon=HOLDING_SESSIONS,
        delay=EXECUTION_DELAY_SESSIONS,
    )
    execution_all = normalize_qlib_frame_index(
        stack_return_frame(execution_wide, name="execution_forward_return")
    )
    execution_test = execution_all.loc[
        execution_all.index.get_level_values("datetime").isin(evaluation_dates)
    ]
    ledger = _ledger(scores, execution_test, classification, REPORTING_WINDOW)
    if ledger["execution_forward_return"].isna().any():
        raise ValueError("CN x1.2 reporting ledger contains unrealized execution returns")
    output.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(
        output,
        index=False,
        compression={"method": "gzip", "mtime": 0},
        float_format="%.17g",
    )
    return {
        "schema_version": "1.0",
        "model_id": MODEL_ID,
        "candidate_id": CANDIDATE_ID,
        "window": REPORTING_WINDOW,
        "train_end": window.train_end,
        "reporting_start": window.test_start,
        "reporting_cutoff": window.test_end,
        "evaluation_dates": int(ledger["datetime"].nunique()),
        "rows": int(len(ledger)),
        "factor_count": len(expressions),
        "classification_sha256": classification_sha256,
        "ledger_sha256": _frame_hash(
            ledger, ["window", "datetime", "instrument", "score"]
        ),
        "research_only": True,
        "trade_ready": False,
        "model_selection_reopened": False,
    }
