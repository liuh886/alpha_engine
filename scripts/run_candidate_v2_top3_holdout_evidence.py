"""Run one predeclared Top-3-aligned ranker on untouched 2026H1 NDX data.

The structural hypothesis was fixed before this holdout was evaluated:

* control: frozen gain5 LambdaRank with LightGBM default truncation 30;
* variant: exact daily Top-3 binary relevance, ``label_gain=[0, 1]``,
  ``eval_at=[3]``, and ``lambdarank_truncation_level=6``;
* unchanged: features, tree calibration, rounds, 50/50 inverted-momentum
  blend, Top-3 portfolio, QQQ trend exposure, 20 bps costs, and 10D embargo.

The runner derives the last horizon-contained signal date from the verified
provider.  It requires complete official 2026-01-02 NDX coverage and at least
100 OOS sessions.  This is one partial-half-year falsification window only:
even a successful result remains research-only and cannot be promoted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_candidate_v2_ndx_window_start_evidence import (
    MIN_WINDOW_SYMBOLS,
    _evaluate_ndx_window,
    _load_provider_lineage,
)
from scripts.run_candidate_v2_universe_robustness import (
    FROZEN_FEATURE_GROUP,
    RANKER_MODE_FROZEN_GAIN5,
    RANKER_MODE_TOP3_ALIGNED,
    _exclude_benchmark_symbols,
    _load_session,
    _load_us_provider_symbols,
    _normalize_index,
    _verify_us_provider,
)
from src.research.ndx_window_start_universe import (
    DEFAULT_SNAPSHOT_PATH,
    get_snapshot_by_date,
    intersect_with_provider,
    load_snapshot,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.notebook_research_api import sanitize_factor_name
from src.research.rolling_windows import RollingResearchWindow

SCHEMA_VERSION = "1.0"
HOLDOUT_LABEL = "2026H1_partial"
HOLDOUT_SNAPSHOT_DATE = "2026-01-02"
REQUESTED_TEST_END = "2026-06-30"
MIN_HOLDOUT_SYMBOLS = 100
MIN_HOLDOUT_SESSIONS = 100
MIN_HOLDOUT_REBALANCE_PERIODS = 10
MAX_DRAWDOWN_DEGRADATION = 0.02
ABSOLUTE_DRAWDOWN_FLOOR = -0.15
DEFAULT_OUTPUT_DIR = Path(
    "artifacts/evidence/candidate_v2_top3_holdout"
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_complete_forward_return_date(
    raw_returns: pd.DataFrame,
    *,
    required_symbols: list[str],
) -> pd.Timestamp:
    """Return the latest date with finite returns for every required symbol."""

    if not isinstance(raw_returns.index, pd.MultiIndex):
        raise ValueError("raw_returns must use a MultiIndex")
    if set(raw_returns.index.names) != {"datetime", "instrument"}:
        raise ValueError(
            "raw_returns index levels must be datetime and instrument"
        )
    if raw_returns.shape[1] != 1:
        raise ValueError("raw_returns must contain exactly one return column")
    if len(required_symbols) != len(set(required_symbols)):
        raise ValueError("required_symbols must be unique")
    if not required_symbols:
        raise ValueError("required_symbols must not be empty")

    required = set(required_symbols)
    instruments = set(
        str(value)
        for value in raw_returns.index.get_level_values("instrument")
    )
    missing = sorted(required - instruments)
    if missing:
        raise ValueError(f"provider return frame is missing symbols: {missing}")

    values = raw_returns.iloc[:, 0].astype(float).replace(
        [np.inf, -np.inf],
        np.nan,
    )
    frame = values.rename("return").reset_index()
    frame = frame.loc[frame["instrument"].astype(str).isin(required)]
    finite = frame["return"].notna()
    counts = frame.loc[finite].groupby("datetime")["instrument"].nunique()
    complete = counts[counts == len(required)]
    if complete.empty:
        raise ValueError(
            "no date has finite forward returns for every required symbol"
        )
    return pd.Timestamp(complete.index.max()).normalize()


def _candidate_summary(payload: dict[str, Any]) -> dict[str, Any]:
    portfolio = payload["candidate_v2"]
    score = payload["score_diagnostics"]
    tail = payload["selection_tail_diagnostics"]["aggregate"]
    return {
        "candidate": payload["candidate"],
        "ranker_contract": payload["ranker_contract"],
        "total_return": portfolio["total_return"],
        "benchmark_return": portfolio["benchmark_return"],
        "relative_excess_return": portfolio["relative_excess_return"],
        "sharpe_ratio": portfolio["sharpe_ratio"],
        "max_drawdown": portfolio["max_drawdown"],
        "turnover": portfolio["turnover"],
        "costs": portfolio["costs"],
        "mean_ic": score["ic_mean"],
        "icir": score["ic_ir"],
        "mean_rank_ic": score["rank_ic_mean"],
        "rank_icir": score["rank_ic_ir"],
        "daily_quintile_spread": score["top_bottom_spread_mean"],
        "rebalance_periods": tail["n_periods"],
        "rebalance_top3_spread": tail["mean_spread"],
        "positive_top3_spread_ratio": tail["positive_spread_ratio"],
        "mean_selected_realized_percentile": tail[
            "mean_selected_realized_percentile"
        ],
    }


def build_holdout_comparison(
    frozen_payload: dict[str, Any],
    aligned_payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply the predeclared single-window falsification checks."""

    frozen = _candidate_summary(frozen_payload)
    aligned = _candidate_summary(aligned_payload)
    if frozen["rebalance_periods"] < MIN_HOLDOUT_REBALANCE_PERIODS:
        raise ValueError("frozen holdout has too few rebalance periods")
    if aligned["rebalance_periods"] != frozen["rebalance_periods"]:
        raise ValueError("holdout candidates must use identical rebalance periods")

    checks = {
        "relative_excess_improved_vs_frozen": (
            aligned["relative_excess_return"]
            > frozen["relative_excess_return"]
        ),
        "positive_relative_excess_vs_qqq": (
            aligned["relative_excess_return"] > 0.0
        ),
        "top3_spread_improved_vs_frozen": (
            aligned["rebalance_top3_spread"]
            > frozen["rebalance_top3_spread"]
        ),
        "positive_top3_spread": aligned["rebalance_top3_spread"] > 0.0,
        "majority_positive_top3_periods": (
            aligned["positive_top3_spread_ratio"] > 0.5
        ),
        "drawdown_not_materially_worse_than_frozen": (
            aligned["max_drawdown"]
            >= frozen["max_drawdown"] - MAX_DRAWDOWN_DEGRADATION
        ),
        "absolute_drawdown_floor": (
            aligned["max_drawdown"] >= ABSOLUTE_DRAWDOWN_FLOOR
        ),
    }
    supported = all(checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "candidate_v2_top3_objective_holdout_comparison",
        "holdout_label": HOLDOUT_LABEL,
        "single_window_only": True,
        "falsification_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "frozen": frozen,
        "top3_aligned": aligned,
        "deltas_top3_aligned_minus_frozen": {
            key: aligned[key] - frozen[key]
            for key in (
                "total_return",
                "relative_excess_return",
                "sharpe_ratio",
                "max_drawdown",
                "icir",
                "rank_icir",
                "daily_quintile_spread",
                "rebalance_top3_spread",
                "positive_top3_spread_ratio",
                "mean_selected_realized_percentile",
            )
        },
        "predeclared_thresholds": {
            "min_rebalance_periods": MIN_HOLDOUT_REBALANCE_PERIODS,
            "max_drawdown_degradation": MAX_DRAWDOWN_DEGRADATION,
            "absolute_drawdown_floor": ABSOLUTE_DRAWDOWN_FLOOR,
            "require_positive_relative_excess": True,
            "require_positive_top3_spread": True,
            "require_majority_positive_top3_periods": True,
        },
        "checks": checks,
        "failed_checks": [
            name for name, passed in checks.items() if not passed
        ],
        "hypothesis_supported_on_single_holdout": supported,
        "decision": (
            "top3_alignment_supported_on_single_holdout_not_promotable"
            if supported
            else "top3_alignment_not_supported_on_holdout"
        ),
    }


def run(
    root: Path,
    *,
    data_root: Path | None = None,
    snapshot_path: Path | str = DEFAULT_SNAPSHOT_PATH,
    provider_lineage_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Execute the frozen-vs-Top3-aligned 2026H1 holdout."""

    root = root.resolve()
    effective_data_root = (
        data_root.resolve() if data_root is not None else root
    )
    output_dir = output_dir if output_dir.is_absolute() else root / output_dir
    resolved_snapshot_path = Path(snapshot_path)
    if not resolved_snapshot_path.is_absolute():
        resolved_snapshot_path = root / resolved_snapshot_path

    session = _load_session(root)
    benchmark = str(session["benchmark"])
    provider_manifest = _verify_us_provider(effective_data_root)
    provider_identity = str(provider_manifest["provider_identity_sha256"])
    lineage: dict[str, Any] | None = None
    resolved_lineage_path: Path | None = None
    if provider_lineage_path is not None:
        resolved_lineage_path = provider_lineage_path
        if not resolved_lineage_path.is_absolute():
            resolved_lineage_path = root / resolved_lineage_path
        lineage = _load_provider_lineage(
            resolved_lineage_path,
            expected_provider_identity=provider_identity,
        )

    snapshot = load_snapshot(
        resolved_snapshot_path,
        validate_hashes=True,
        validate_source=True,
    )
    holdout_snapshot = get_snapshot_by_date(
        snapshot,
        HOLDOUT_SNAPSHOT_DATE,
    )
    provider_symbols = set(_load_us_provider_symbols(effective_data_root))
    coverage = intersect_with_provider(holdout_snapshot, provider_symbols)
    tradable_symbols = list(
        _exclude_benchmark_symbols(tuple(coverage["retained"]))
    )
    if not coverage["complete"]:
        raise ValueError(
            "holdout requires complete official NDX provider coverage; "
            f"missing={coverage['missing']}"
        )
    if len(tradable_symbols) < max(MIN_HOLDOUT_SYMBOLS, MIN_WINDOW_SYMBOLS):
        raise ValueError(
            f"holdout retained {len(tradable_symbols)} symbols; "
            f"minimum is {MIN_HOLDOUT_SYMBOLS}"
        )

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    from src.data.market_provider import market_provider_path

    provider_uri = str(market_provider_path(effective_data_root, "us"))
    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market="us",
            provider_uri_default=provider_uri,
        )
    )
    from qlib.data import D

    calendar = pd.DatetimeIndex(
        D.calendar(
            start_time=HOLDOUT_SNAPSHOT_DATE,
            end_time=REQUESTED_TEST_END,
            freq="day",
        )
    )
    if calendar.empty:
        raise ValueError("provider has no 2026H1 calendar")
    provider_calendar_end = calendar.max().normalize()
    return_frame = D.features(
        [*tradable_symbols, benchmark],
        [CANONICAL_10D_RETURN_EXPR],
        start_time=HOLDOUT_SNAPSHOT_DATE,
        end_time=provider_calendar_end.strftime("%Y-%m-%d"),
    )
    return_frame = _normalize_index(return_frame)
    return_frame.columns = ["return"]
    safe_test_end = latest_complete_forward_return_date(
        return_frame,
        required_symbols=[*tradable_symbols, benchmark],
    )
    eligible_sessions = calendar[
        (calendar >= pd.Timestamp(HOLDOUT_SNAPSHOT_DATE))
        & (calendar <= safe_test_end)
    ]
    if len(eligible_sessions) < MIN_HOLDOUT_SESSIONS:
        raise ValueError(
            f"holdout has only {len(eligible_sessions)} horizon-contained "
            f"sessions; minimum is {MIN_HOLDOUT_SESSIONS}"
        )

    window = RollingResearchWindow(
        label=HOLDOUT_LABEL,
        train_start=str(session["train_start"]),
        train_end="2025-12-31",
        test_start=HOLDOUT_SNAPSHOT_DATE,
        test_end=safe_test_end.strftime("%Y-%m-%d"),
    )
    feature_exprs = list(FROZEN_FEATURE_GROUP.expressions)
    expression_columns = {
        expr: sanitize_factor_name(expr) for expr in feature_exprs
    }
    baseline_expr = "$close/Ref($close,10)-1"

    payloads: dict[str, dict[str, Any]] = {}
    for ranker_mode in (
        RANKER_MODE_FROZEN_GAIN5,
        RANKER_MODE_TOP3_ALIGNED,
    ):
        payload = _evaluate_ndx_window(
            window,
            benchmark,
            expression_columns,
            feature_exprs,
            baseline_expr,
            snapshot,
            provider_symbols,
            oos_snapshot_date=HOLDOUT_SNAPSHOT_DATE,
            ranker_mode=ranker_mode,
        )
        if payload is None or payload.get("skipped") is True:
            reason = None if payload is None else payload.get("skip_reason")
            raise ValueError(f"{ranker_mode} holdout evaluation failed: {reason}")
        payloads[ranker_mode] = payload

    frozen_payload = payloads[RANKER_MODE_FROZEN_GAIN5]
    aligned_payload = payloads[RANKER_MODE_TOP3_ALIGNED]
    if (
        frozen_payload["coverage_meta"]["oos_test_symbols"]
        != aligned_payload["coverage_meta"]["oos_test_symbols"]
    ):
        raise ValueError("holdout candidates used different OOS symbols")
    if (
        frozen_payload["coverage_meta"]["training_symbols"]
        != aligned_payload["coverage_meta"]["training_symbols"]
    ):
        raise ValueError("holdout candidates used different training symbols")

    comparison = build_holdout_comparison(
        frozen_payload,
        aligned_payload,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_path = output_dir / "frozen_gain5.json"
    aligned_path = output_dir / "top3_binary_trunc6.json"
    comparison_path = output_dir / "comparison.json"
    _write_json(frozen_path, frozen_payload)
    _write_json(aligned_path, aligned_payload)
    _write_json(comparison_path, comparison)

    artifacts = [frozen_path, aligned_path, comparison_path]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "candidate_v2_top3_objective_holdout",
        "holdout_label": HOLDOUT_LABEL,
        "holdout_predeclared_before_evaluation": True,
        "single_window_only": True,
        "falsification_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "parameter_grid_searched": False,
        "ranker_modes": [
            RANKER_MODE_FROZEN_GAIN5,
            RANKER_MODE_TOP3_ALIGNED,
        ],
        "unchanged_components": [
            "feature_set",
            "tree_calibration",
            "num_boost_round",
            "blend_weight",
            "inverted_momentum_component",
            "portfolio_top_k",
            "qqq_trend_exposure",
            "cost_bps",
            "holding_period",
            "training_embargo",
        ],
        "window": window.to_dict(),
        "requested_test_end": REQUESTED_TEST_END,
        "provider_calendar_end": provider_calendar_end.strftime("%Y-%m-%d"),
        "horizon_contained_test_end": safe_test_end.strftime("%Y-%m-%d"),
        "n_horizon_contained_sessions": len(eligible_sessions),
        "snapshot": {
            "path": str(resolved_snapshot_path),
            "date": holdout_snapshot.date,
            "count": holdout_snapshot.count,
            "sha256_membership_hash": (
                holdout_snapshot.sha256_membership_hash
            ),
            "coverage_complete": coverage["complete"],
            "retained": coverage["n_retained"],
            "missing": coverage["missing"],
        },
        "provider": {
            "uri": provider_uri,
            "identity_sha256": provider_identity,
            "lineage_present": lineage is not None,
            "lineage_path": (
                str(resolved_lineage_path)
                if resolved_lineage_path is not None
                else None
            ),
            "lineage_sha256": (
                _sha256_file(resolved_lineage_path)
                if resolved_lineage_path is not None
                else None
            ),
        },
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
        "decision": comparison["decision"],
        "hypothesis_supported_on_single_holdout": comparison[
            "hypothesis_supported_on_single_holdout"
        ],
        "artifacts": {
            path.name: _sha256_file(path) for path in artifacts
        },
    }
    manifest_path = output_dir / "evidence_manifest.json"
    _write_json(manifest_path, manifest)

    print(
        f"holdout={HOLDOUT_LABEL} sessions={len(eligible_sessions)} "
        f"symbols={coverage['n_retained']}/{coverage['n_requested']} "
        f"safe_end={safe_test_end.date()}"
    )
    for name, summary in (
        ("frozen", comparison["frozen"]),
        ("top3_aligned", comparison["top3_aligned"]),
    ):
        print(
            f"{name}: relative_excess={summary['relative_excess_return']:.4f} "
            f"top3_spread={summary['rebalance_top3_spread']:.4f} "
            f"positive_top3={summary['positive_top3_spread_ratio']:.3f} "
            f"mdd={summary['max_drawdown']:.4f}"
        )
    print(f"decision={comparison['decision']}")
    print("promotion_eligible=false")
    print("trade_ready=false")
    print(f"manifest={manifest_path}")

    return {
        "manifest_path": str(manifest_path),
        "comparison_path": str(comparison_path),
        "manifest": manifest,
        "comparison": comparison,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Read-only data root containing data/providers/us",
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=DEFAULT_SNAPSHOT_PATH,
        help="Committed NDX membership snapshot",
    )
    parser.add_argument(
        "--provider-lineage-path",
        type=Path,
        default=None,
        help="Optional provider lineage bound to provider identity",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Holdout evidence output directory",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(
        args.root,
        data_root=args.data_root,
        snapshot_path=args.snapshot_path,
        provider_lineage_path=args.provider_lineage_path,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
