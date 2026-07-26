"""Challenge the frozen residual-trend hypothesis on the independent CN market.

The signal contract is unchanged from the NDX diagnosis: 126 historical
sessions, a 10-session skip, benchmark-beta removal, and residual mean divided
by residual volatility.  CN market/portfolio semantics come from the canonical
CN spec, including CSI300 and Top-15.

The CN universe is static current membership and therefore survivorship-biased.
This runner is diagnostic only and can never promote a signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from scripts.run_candidate_v2_universe_robustness import (
    MAX_DRAWDOWN_GATE,
    _compute_score_diagnostics,
    _load_benchmark_returns,
    _load_benchmark_trend,
    _normalize_index,
)
from scripts.run_ndx_residual_trend_evidence import (
    CANDIDATE_ID,
    MIN_POSITIVE_EXCESS_WINDOWS,
    MIN_POSITIVE_TOP3_PERIOD_RATIO,
    MIN_SCORE_COVERAGE,
    ONE_DAY_RETURN_EXPR,
    _exposure_diagnostics,
    _load_residual_signal,
    _score_coverage,
)
from src.data.market_provider import (
    load_provider_manifest,
    market_provider_path,
)
from src.research.benchmark_residual_trend import (
    DEFAULT_LOOKBACK_SESSIONS,
    DEFAULT_SKIP_RECENT_SESSIONS,
)
from src.research.multi_market_readiness import (
    load_market_watchlist,
    normalize_market_symbols,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.paradigm import load_research_paradigm_spec
from src.research.risk_control_variants import (
    RiskVariantSpec,
    VARIANT_TOP3_BENCHMARK_TREND,
    evaluate_risk_control_variant,
)
from src.research.rolling_windows import half_year_rolling_windows
from src.research.selection_tail_diagnostics import (
    compute_selection_tail_diagnostics,
    summarize_window_diagnostics,
)

SCHEMA_VERSION = "1.0"
DEFAULT_SPEC = Path(
    "configs/research_paradigms/cn_10d_csi300_baseline.yaml"
)
DEFAULT_OUTPUT_DIR = Path("artifacts/evidence/cn_residual_trend_quality")
DEFAULT_COST_BPS = 20.0
DEFAULT_NEGATIVE_BENCHMARK_EXPOSURE = 0.5
REQUIRED_WINDOWS = 4


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


def _provider_symbols(provider_dir: Path) -> set[str]:
    path = provider_dir / "instruments" / "cn.txt"
    if not path.is_file():
        raise FileNotFoundError(f"CN instrument file missing: {path}")
    symbols = {
        line.split("\t", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if not symbols:
        raise ValueError("CN provider contains no instruments")
    return symbols


def _load_cn_contract(
    root: Path,
    *,
    data_root: Path,
    spec_path: Path,
) -> tuple[Any, dict[str, Any], list[str], Path]:
    spec_file = spec_path if spec_path.is_absolute() else root / spec_path
    spec = load_research_paradigm_spec(spec_file)
    if spec.market != "cn":
        raise ValueError("CN residual-trend runner requires a CN spec")
    if spec.universe.get("membership_mode") != "static_curated":
        raise ValueError("CN runner currently requires explicit static_curated scope")
    if spec.universe.get("survivorship_bias") is not True:
        raise ValueError("CN static universe must declare survivorship_bias=true")

    provider_dir = market_provider_path(data_root, "cn")
    provider_manifest = load_provider_manifest(
        provider_dir,
        expected_market="cn",
        required=True,
        verify_files=True,
    )
    if provider_manifest is None:
        raise ValueError("CN provider manifest is missing")
    available = _provider_symbols(provider_dir)

    universe_source = Path(str(spec.universe["source"]))
    if not universe_source.is_absolute():
        universe_source = root / universe_source
    raw_symbols = load_market_watchlist(
        "cn",
        watchlist_path=universe_source,
    )
    normalized = normalize_market_symbols(
        "cn",
        raw_symbols,
        available_symbols=available,
    )
    benchmark = str(spec.benchmark)
    retained = [
        item.normalized_symbol
        for item in normalized
        if item.normalized_symbol in available
        and item.normalized_symbol != benchmark
    ]
    retained = list(dict.fromkeys(retained))
    minimum = int(spec.universe["min_symbols"])
    if len(retained) < minimum:
        raise ValueError(
            f"CN provider retained {len(retained)} symbols below minimum {minimum}"
        )
    if benchmark not in available:
        raise ValueError(f"CN provider is missing benchmark {benchmark}")
    readiness = {
        "requested_symbols": len(raw_symbols),
        "normalized_symbols": len(normalized),
        "retained_symbols": len(retained),
        "minimum_symbols": minimum,
        "unavailable_symbols": [
            item.normalized_symbol
            for item in normalized
            if item.normalized_symbol not in available
        ],
        "benchmark": benchmark,
        "benchmark_available": True,
        "membership_mode": spec.universe["membership_mode"],
        "membership_as_of": spec.universe["membership_as_of"],
        "survivorship_bias": True,
        "provider_identity_sha256": provider_manifest[
            "provider_identity_sha256"
        ],
        "provider_calendar": provider_manifest["calendar"],
        "universe_source": str(universe_source),
        "universe_source_sha256": _sha256_file(universe_source),
    }
    return spec, readiness, retained, provider_dir


def _evaluate_cn_window(
    window: Any,
    *,
    symbols: list[str],
    benchmark: str,
    top_n: int,
    history_start: str,
) -> dict[str, Any]:
    from qlib.data import D

    signal = _load_residual_signal(
        symbols,
        history_start=history_start,
        test_start=window.test_start,
        test_end=window.test_end,
        benchmark=benchmark,
    )
    raw_returns = D.features(
        symbols,
        [CANONICAL_10D_RETURN_EXPR],
        start_time=window.test_start,
        end_time=window.test_end,
    )
    raw_returns = _normalize_index(raw_returns)
    raw_returns.columns = ["return"]
    raw_returns.attrs["provenance"] = "raw_forward_return"
    raw_returns.attrs["horizon"] = 10
    raw_returns.attrs["expression"] = CANONICAL_10D_RETURN_EXPR

    benchmark_returns = _load_benchmark_returns(
        benchmark,
        window.test_start,
        window.test_end,
    )
    benchmark_trend = _load_benchmark_trend(
        benchmark,
        window.test_start,
        window.test_end,
    )
    spec = RiskVariantSpec(
        variant_id=VARIANT_TOP3_BENCHMARK_TREND,
        top_n=top_n,
        construction="equal_weight_with_benchmark_trend_filter",
        negative_benchmark_trend_exposure=(
            DEFAULT_NEGATIVE_BENCHMARK_EXPOSURE
        ),
    )
    portfolio_report = evaluate_risk_control_variant(
        signal.score,
        raw_returns,
        benchmark_returns,
        spec=spec,
        benchmark_trend=benchmark_trend,
        rebalance_days=10,
        cost_bps=DEFAULT_COST_BPS,
    )
    tail = compute_selection_tail_diagnostics(
        signal.score,
        raw_returns,
        portfolio_report,
        top_n=top_n,
    )
    tail["window_label"] = window.label
    rebalance_dates = [
        str(item["date"]) for item in tail.get("periods", [])
    ]
    coverage = _score_coverage(
        signal.score,
        rebalance_dates=rebalance_dates,
        n_symbols=len(symbols),
    )
    if not coverage["all_rebalance_dates_pass"]:
        raise ValueError(f"{window.label} CN score coverage failed")

    portfolio = portfolio_report.to_dict()
    portfolio.pop("period_details", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cn_residual_trend_quality_window",
        "independent_market_challenge": True,
        "research_only": True,
        "diagnostic_only": True,
        "survivorship_bias": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "window": window.to_dict(),
        "candidate": CANDIDATE_ID,
        "signal_contract": {
            "benchmark": benchmark,
            "one_day_return_expression": ONE_DAY_RETURN_EXPR,
            "lookback_sessions": DEFAULT_LOOKBACK_SESSIONS,
            "skip_recent_sessions": DEFAULT_SKIP_RECENT_SESSIONS,
            "orientation": "higher_residual_trend_quality_is_better",
            "parameter_search_performed": False,
            "uses_future_returns": False,
        },
        "score_coverage": coverage,
        "score_diagnostics": _compute_score_diagnostics(
            signal.score,
            raw_returns,
        ),
        "selection_tail_diagnostics": tail,
        "risk_exposure_diagnostics": _exposure_diagnostics(signal, tail),
        "portfolio": portfolio,
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
    }


def _compound(values: list[float]) -> float:
    return float(np.prod([1.0 + value for value in values]) - 1.0)


def aggregate_cn_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if len(reports) != REQUIRED_WINDOWS:
        raise ValueError(f"CN aggregate requires {REQUIRED_WINDOWS} windows")
    labels = [str(item["window"]["label"]) for item in reports]
    if len(labels) != len(set(labels)):
        raise ValueError("CN window labels must be unique")

    candidate_total = _compound(
        [float(item["portfolio"]["total_return"]) for item in reports]
    )
    benchmark_total = _compound(
        [float(item["portfolio"]["benchmark_return"]) for item in reports]
    )
    compounded_relative_excess = (
        (1.0 + candidate_total) / (1.0 + benchmark_total) - 1.0
    )
    positive_excess_windows = sum(
        float(item["portfolio"]["relative_excess_return"]) > 0.0
        for item in reports
    )
    worst_drawdown = min(
        float(item["portfolio"]["max_drawdown"]) for item in reports
    )
    tail = summarize_window_diagnostics(
        [item["selection_tail_diagnostics"] for item in reports]
    )
    minimum_score_coverage = min(
        float(item["score_coverage"]["minimum_observed_ratio"])
        for item in reports
    )

    def mean(path: tuple[str, ...]) -> float:
        values = []
        for item in reports:
            value: Any = item
            for key in path:
                value = value[key]
            values.append(float(value))
        if not all(np.isfinite(values)):
            raise ValueError(f"CN aggregate contains non-finite {path}")
        return float(np.mean(values))

    checks = {
        "exactly_four_complete_windows": len(reports) == REQUIRED_WINDOWS,
        "score_coverage": minimum_score_coverage >= MIN_SCORE_COVERAGE,
        "positive_excess_windows": (
            positive_excess_windows >= MIN_POSITIVE_EXCESS_WINDOWS
        ),
        "positive_compounded_relative_excess": (
            compounded_relative_excess > 0.0
        ),
        "drawdown_floor": worst_drawdown >= MAX_DRAWDOWN_GATE,
        "positive_top15_spread": float(tail["mean_spread"]) > 0.0,
        "top15_period_consistency": (
            float(tail["mean_positive_spread_ratio"])
            >= MIN_POSITIVE_TOP3_PERIOD_RATIO
        ),
    }
    supported = all(checks.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cn_residual_trend_quality_aggregate",
        "independent_market_challenge": True,
        "research_only": True,
        "diagnostic_only": True,
        "survivorship_bias": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "candidate": CANDIDATE_ID,
        "n_windows": len(reports),
        "compounded_total_return": candidate_total,
        "compounded_benchmark_return": benchmark_total,
        "compounded_relative_excess_return": compounded_relative_excess,
        "positive_excess_windows": positive_excess_windows,
        "mean_sharpe": mean(("portfolio", "sharpe_ratio")),
        "worst_drawdown": worst_drawdown,
        "mean_icir": mean(("score_diagnostics", "ic_ir")),
        "mean_rank_icir": mean(("score_diagnostics", "rank_ic_ir")),
        "mean_daily_quintile_spread": mean(
            ("score_diagnostics", "top_bottom_spread_mean")
        ),
        "selection_tail_diagnostics": tail,
        "minimum_score_coverage": minimum_score_coverage,
        "predeclared_checks": checks,
        "failed_checks": [
            key for key, passed in checks.items() if not passed
        ],
        "hypothesis_supported_on_independent_market": supported,
        "decision": (
            "cn_residual_trend_quality_supported_for_future_validation"
            if supported
            else "cn_residual_trend_quality_not_supported"
        ),
    }


def run(
    root: Path,
    *,
    data_root: Path,
    spec_path: Path = DEFAULT_SPEC,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    root = root.resolve()
    data_root = data_root.resolve()
    output_dir = (
        output_dir if output_dir.is_absolute() else root / output_dir
    )
    spec, readiness, symbols, provider_dir = _load_cn_contract(
        root,
        data_root=data_root,
        spec_path=spec_path,
    )

    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    safe_qlib_init(
        build_qlib_init_cfg(
            None,
            market="cn",
            provider_uri_default=str(provider_dir),
        )
    )
    windows = half_year_rolling_windows(
        start_year=2021,
        first_test_year=2024,
        last_test_year=2025,
    )
    if len(windows) != REQUIRED_WINDOWS:
        raise ValueError("canonical CN challenge must contain four windows")

    top_n = int(spec.strategy["top_n"])
    if top_n != 15:
        raise ValueError("canonical CN residual-trend challenge requires Top-15")
    per_window_dir = output_dir / "per_window"
    per_window_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for window in windows:
        report = _evaluate_cn_window(
            window,
            symbols=symbols,
            benchmark=spec.benchmark,
            top_n=top_n,
            history_start=str(spec.walk_forward["requested_train_start"]),
        )
        reports.append(report)
        _write_json(per_window_dir / f"{window.label}.json", report)
        print(
            f"{window.label}: rel_excess="
            f"{report['portfolio']['relative_excess_return']:.4f} "
            f"drawdown={report['portfolio']['max_drawdown']:.4f} "
            f"top15_spread="
            f"{report['selection_tail_diagnostics']['aggregate']['mean_spread']:.4f}"
        )

    aggregate = aggregate_cn_reports(reports)
    aggregate_path = output_dir / "aggregate.json"
    _write_json(aggregate_path, aggregate)
    readiness_path = output_dir / "readiness.json"
    _write_json(readiness_path, readiness)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cn_residual_trend_quality",
        "independent_market_challenge": True,
        "research_only": True,
        "diagnostic_only": True,
        "survivorship_bias": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "candidate": CANDIDATE_ID,
        "parameter_grid_searched": False,
        "orientation_selected_after_evaluation": False,
        "spec_path": str(spec.spec_path),
        "spec_experiment_id": spec.experiment_id,
        "provider_uri": str(provider_dir),
        "provider_identity_sha256": readiness[
            "provider_identity_sha256"
        ],
        "universe_source_sha256": readiness["universe_source_sha256"],
        "signal_contract": {
            "benchmark": spec.benchmark,
            "one_day_return_expression": ONE_DAY_RETURN_EXPR,
            "lookback_sessions": DEFAULT_LOOKBACK_SESSIONS,
            "skip_recent_sessions": DEFAULT_SKIP_RECENT_SESSIONS,
            "orientation": "higher_residual_trend_quality_is_better",
            "uses_future_returns": False,
        },
        "portfolio_contract": {
            "top_n": top_n,
            "cost_bps": DEFAULT_COST_BPS,
            "negative_benchmark_trend_exposure": (
                DEFAULT_NEGATIVE_BENCHMARK_EXPOSURE
            ),
            "rebalance_sessions": 10,
        },
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
        "artifacts": {
            "readiness": readiness_path.name,
            "aggregate": aggregate_path.name,
            "per_window": [
                f"per_window/{item['window']['label']}.json"
                for item in reports
            ],
        },
        "decision": aggregate["decision"],
    }
    manifest_path = output_dir / "evidence_manifest.json"
    _write_json(manifest_path, manifest)
    print(f"aggregate: {aggregate_path}")
    print(f"manifest: {manifest_path}")
    print(f"decision: {aggregate['decision']}")
    print("promotion_eligible=false")
    print("trade_ready=false")
    return {
        "readiness": readiness,
        "aggregate": aggregate,
        "manifest": manifest,
        "aggregate_path": str(aggregate_path),
        "manifest_path": str(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="Isolated root containing data/providers/cn",
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(
        args.root,
        data_root=args.data_root,
        spec_path=args.spec,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
