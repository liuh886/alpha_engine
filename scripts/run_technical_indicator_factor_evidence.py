"""Generate close-only, cross-market 10D technical-factor evidence.

The runner evaluates three frozen historical factors on the already-observed
2024H1--2025H2 windows:

* Bollinger 20-session mean reversion;
* normalized MACD 12/26/9 acceleration; and
* 10-session RSI positive-magnitude share.

US evaluation reuses the repaired window-start NDX membership evidence.  CN
evaluation uses the versioned static curated universe and therefore retains an
explicit survivorship-bias warning.  Both markets use canonical raw forward
10-session returns from the exact provider-manifest CSV inputs.  Results are
diagnostic only and cannot make a factor or model trade-ready.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.research.notebook_experiment_api import run_10d_experiment
from src.research.notebook_lab_contracts import (
    CANONICAL_10D_RETURN_EXPR,
    ResearchSessionConfig,
)
from src.research.technical_indicator_factors import (
    TECHNICAL_INDICATOR_SPECS,
    compute_technical_indicator_scores,
)
from src.research.walk_forward_stability import (
    slice_multiindex_dates,
    summarize_walk_forward_reports,
)

SCHEMA_VERSION = "1.0"
WINDOW_LABELS = ("2024H1", "2024H2", "2025H1", "2025H2")
DEFAULT_US_WINDOW_SOURCE = Path(
    "artifacts/evidence/candidate_v2_ndx_window_start"
)
DEFAULT_CN_UNIVERSE = Path(
    "configs/research_universes/cn_curated_equities_v1.yaml"
)
DEFAULT_CN_READINESS = Path(
    "artifacts/evidence/cn_residual_trend_quality/readiness.json"
)
DEFAULT_OUTPUT_DIR = Path(
    "artifacts/evidence/technical_indicator_factor_quality"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must contain an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _persist_window_contract(
    report: dict[str, Any],
    *,
    window: dict[str, Any],
) -> None:
    """Attach the research-only window contract to memory and disk."""

    artifact_path = report.pop("artifact_path", None)
    if not artifact_path:
        raise ValueError("experiment report is missing artifact_path")
    report["window_contract"] = {
        "label": window["label"],
        "membership_mode": window["membership_mode"],
        "snapshot_date": window["snapshot_date"],
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
    }
    _write_json(Path(artifact_path), report)
    report["artifact_path"] = str(artifact_path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(provider_manifest: dict[str, Any]) -> dict[str, str]:
    entries = provider_manifest.get("source_csvs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("provider manifest must contain source_csvs")
    result: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("provider source_csvs entries must be objects")
        name = str(item.get("name", "")).strip()
        digest = str(item.get("sha256", "")).strip()
        if not name or len(digest) != 64:
            raise ValueError("provider source_csvs entry is incomplete")
        result[name] = digest
    return result


def _resolve_csv(
    symbol: str,
    *,
    csv_dirs: tuple[Path, ...],
    expected_hashes: dict[str, str],
) -> Path:
    filename = f"{symbol}.csv"
    expected = expected_hashes.get(filename)
    if expected is None:
        raise ValueError(f"provider manifest has no source hash for {filename}")
    mismatches: list[str] = []
    for directory in csv_dirs:
        candidates = (
            directory / filename,
            directory / filename.upper(),
            directory / filename.lower(),
        )
        for path in candidates:
            if not path.is_file():
                continue
            observed = _sha256(path)
            if observed == expected:
                return path
            mismatches.append(f"{path}={observed}")
    if mismatches:
        raise ValueError(
            f"source hash mismatch for {filename}: {', '.join(mismatches)}"
        )
    raise FileNotFoundError(
        f"manifest-pinned source CSV is unavailable for {symbol}"
    )


def _load_close_frame(
    symbols: list[str],
    *,
    csv_dirs: tuple[Path, ...],
    provider_manifest: dict[str, Any],
) -> pd.DataFrame:
    if not symbols:
        raise ValueError("symbols must not be empty")
    expected_hashes = _source_hashes(provider_manifest)
    pieces: list[pd.DataFrame] = []
    for symbol in symbols:
        path = _resolve_csv(
            symbol,
            csv_dirs=csv_dirs,
            expected_hashes=expected_hashes,
        )
        source = pd.read_csv(path, usecols=["date", "close"])
        source["date"] = pd.to_datetime(source["date"], errors="coerce")
        source["close"] = pd.to_numeric(source["close"], errors="coerce")
        source = source.dropna(subset=["date"]).sort_values("date")
        if source["date"].duplicated().any():
            raise ValueError(f"duplicate source dates for {symbol}")
        finite = source["close"].replace([np.inf, -np.inf], np.nan).dropna()
        if finite.empty or (finite <= 0.0).any():
            raise ValueError(f"non-positive or empty close history for {symbol}")
        ratios = finite.pct_change(fill_method=None) + 1.0
        if ((ratios < (1.0 / 3.0)) | (ratios > 3.0)).any():
            raise ValueError(
                f"split-like adjusted-close discontinuity remains for {symbol}"
            )
        index = pd.MultiIndex.from_arrays(
            [
                source["date"],
                np.repeat(symbol, len(source)),
            ],
            names=["datetime", "instrument"],
        )
        pieces.append(
            pd.DataFrame(
                {"close": source["close"].to_numpy(dtype=float)},
                index=index,
            )
        )
    return pd.concat(pieces).sort_index()


def _audit_provider_sources(
    *,
    market: str,
    csv_dirs: tuple[Path, ...],
    provider_manifest: dict[str, Any],
    survivorship_bias: bool,
) -> dict[str, Any]:
    """Audit manifest-pinned OHLCV sources without changing their values."""

    expected_hashes = _source_hashes(provider_manifest)
    required_columns = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "factor",
    }
    result: dict[str, Any] = {
        "market": market,
        "provider_identity_sha256": provider_manifest.get(
            "provider_identity_sha256"
        ),
        "n_source_files": len(expected_hashes),
        "n_rows": 0,
        "duplicate_date_rows": 0,
        "invalid_ohlc_rows": 0,
        "nonpositive_close_rows": 0,
        "nonpositive_volume_rows": 0,
        "split_like_close_jump_rows": 0,
        "non_unit_factor_rows": 0,
        "first_date": None,
        "last_date": None,
        "survivorship_bias": survivorship_bias,
    }
    first_dates: list[pd.Timestamp] = []
    last_dates: list[pd.Timestamp] = []
    for filename in sorted(expected_hashes):
        symbol = Path(filename).stem
        path = _resolve_csv(
            symbol,
            csv_dirs=csv_dirs,
            expected_hashes=expected_hashes,
        )
        source = pd.read_csv(path)
        missing = required_columns.difference(source.columns)
        if missing:
            raise ValueError(
                f"source CSV {filename} is missing columns: {sorted(missing)}"
            )
        dates = pd.to_datetime(source["date"], errors="coerce")
        numeric = source[
            ["open", "high", "low", "close", "volume", "factor"]
        ].apply(pd.to_numeric, errors="coerce")
        finite_ohlc = numeric[["open", "high", "low", "close"]].replace(
            [np.inf, -np.inf],
            np.nan,
        )
        ohlc_complete = finite_ohlc.notna().all(axis=1)
        scale = finite_ohlc.abs().max(axis=1).clip(lower=1.0)
        tolerance = 1e-12 + scale * 1e-10
        invalid_ohlc = ohlc_complete & (
            (
                finite_ohlc["high"] + tolerance
                < finite_ohlc[["open", "close"]].max(axis=1)
            )
            | (
                finite_ohlc["low"] - tolerance
                > finite_ohlc[["open", "close"]].min(axis=1)
            )
            | (finite_ohlc["high"] + tolerance < finite_ohlc["low"])
        )
        close = numeric["close"].replace([np.inf, -np.inf], np.nan)
        ratios = close.pct_change(fill_method=None) + 1.0
        valid_dates = dates.dropna()

        result["n_rows"] += len(source)
        result["duplicate_date_rows"] += int(dates.duplicated().sum())
        result["invalid_ohlc_rows"] += int(invalid_ohlc.sum())
        result["nonpositive_close_rows"] += int((close <= 0.0).sum())
        result["nonpositive_volume_rows"] += int(
            (numeric["volume"] <= 0.0).sum()
        )
        result["split_like_close_jump_rows"] += int(
            ((ratios < (1.0 / 3.0)) | (ratios > 3.0)).sum()
        )
        result["non_unit_factor_rows"] += int(
            (~np.isclose(numeric["factor"], 1.0, equal_nan=False)).sum()
        )
        if not valid_dates.empty:
            first_dates.append(valid_dates.min())
            last_dates.append(valid_dates.max())

    if first_dates:
        result["first_date"] = min(first_dates).date().isoformat()
        result["last_date"] = max(last_dates).date().isoformat()
    result["close_only_factor_evidence_eligible"] = (
        result["duplicate_date_rows"] == 0
        and result["nonpositive_close_rows"] == 0
        and result["split_like_close_jump_rows"] == 0
    )
    result["high_low_factor_evidence_eligible"] = (
        result["close_only_factor_evidence_eligible"]
        and result["invalid_ohlc_rows"] == 0
    )
    return result


def _raw_forward_returns(close: pd.DataFrame) -> pd.DataFrame:
    wide = close["close"].unstack(level="instrument")
    forward = wide.shift(-10) / wide - 1.0
    result = (
        forward.rename_axis(index="datetime", columns="instrument")
        .stack(future_stack=True)
        .rename("return")
        .to_frame()
        .sort_index()
    )
    result.attrs.update(
        {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        }
    )
    return result


def _benchmark_forward_returns(close: pd.DataFrame, symbol: str) -> pd.DataFrame:
    try:
        series = close.xs(symbol, level="instrument")["close"]
    except KeyError as exc:
        raise ValueError(f"benchmark close history is unavailable: {symbol}") from exc
    result = (series.shift(-10) / series - 1.0).rename("return").to_frame()
    result.index = pd.to_datetime(result.index)
    return result


def _us_windows(
    source_dir: Path,
    *,
    provider_identity: str,
) -> list[dict[str, Any]]:
    manifest = _read_json(source_dir / "evidence_manifest.json")
    if manifest.get("provider_identity_sha256") != provider_identity:
        raise ValueError("US window evidence provider identity mismatch")
    windows: list[dict[str, Any]] = []
    for label in WINDOW_LABELS:
        path = source_dir / "per_window" / f"ndx_window_start_{label}.json"
        payload = _read_json(path)
        if payload.get("skipped") is True:
            raise ValueError(f"US source window is skipped: {label}")
        window = payload.get("window")
        coverage = payload.get("coverage_meta")
        if not isinstance(window, dict) or not isinstance(coverage, dict):
            raise ValueError(f"US source window is incomplete: {label}")
        if window.get("label") != label:
            raise ValueError(f"US source window label mismatch: {label}")
        if coverage.get("oos_membership_point_in_time") is not True:
            raise ValueError("US OOS membership must be point-in-time")
        symbols = coverage.get("oos_test_symbols")
        if not isinstance(symbols, list) or len(symbols) < 50:
            raise ValueError(f"US source window has insufficient symbols: {label}")
        windows.append(
            {
                **window,
                "symbols": [str(item) for item in symbols],
                "snapshot_date": coverage.get("oos_snapshot_date"),
                "membership_mode": "window_start_point_in_time",
            }
        )
    return windows


def _cn_windows(
    universe_path: Path,
    readiness_path: Path,
    *,
    provider_identity: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    metadata = universe.get("metadata", {})
    requested = [str(item) for item in universe.get("cn", [])]
    readiness = _read_json(readiness_path)
    if readiness.get("provider_identity_sha256") != provider_identity:
        raise ValueError("CN readiness provider identity mismatch")
    if readiness.get("survivorship_bias") is not True:
        raise ValueError("CN static-universe survivorship bias must be explicit")
    unavailable = {str(item) for item in readiness.get("unavailable_symbols", [])}
    retained = [symbol for symbol in requested if symbol not in unavailable]
    if len(retained) != int(readiness.get("retained_symbols", -1)):
        raise ValueError("CN readiness retained-symbol count mismatch")
    windows = []
    for label in WINDOW_LABELS:
        year = int(label[:4])
        first_half = label.endswith("H1")
        windows.append(
            {
                "label": label,
                "train_start": "2021-01-01",
                "train_end": (
                    f"{year - 1}-12-31"
                    if first_half
                    else f"{year}-06-30"
                ),
                "test_start": (
                    f"{year}-01-01"
                    if first_half
                    else f"{year}-07-01"
                ),
                "test_end": (
                    f"{year}-06-30"
                    if first_half
                    else f"{year}-12-31"
                ),
                "symbols": retained,
                "snapshot_date": metadata.get("membership_as_of"),
                "membership_mode": metadata.get("membership_mode"),
            }
        )
    return windows, metadata


def _candidate_rows(
    reports: list[dict[str, Any]],
    *,
    orientation: str = "original",
) -> dict[str, list[dict[str, Any]]]:
    grouped = {spec.name: [] for spec in TECHNICAL_INDICATOR_SPECS}
    for report in reports:
        comparison = report["comparison_report"]
        for candidate in comparison["candidates"]:
            name = str(candidate.get("candidate_name", ""))
            if name in grouped and candidate.get("orientation") == orientation:
                grouped[name].append(candidate)
    return grouped


def _economic_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n_windows": 0,
            "positive_excess_ratio": 0.0,
            "compounded_portfolio_return": 0.0,
            "compounded_benchmark_return": 0.0,
            "compounded_relative_excess": 0.0,
        }
    portfolio = math.prod(1.0 + float(row["total_return"]) for row in rows) - 1.0
    benchmark = (
        math.prod(1.0 + float(row["benchmark_return"]) for row in rows) - 1.0
    )
    relative = (1.0 + portfolio) / (1.0 + benchmark) - 1.0
    return {
        "n_windows": len(rows),
        "positive_excess_ratio": (
            sum(float(row["excess_return"]) > 0.0 for row in rows) / len(rows)
        ),
        "compounded_portfolio_return": portfolio,
        "compounded_benchmark_return": benchmark,
        "compounded_relative_excess": relative,
    }


def _stability_rows(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in summary.get("candidates", []):
        label = str(row.get("candidate", ""))
        if not label.endswith("/original"):
            continue
        name = label.split("/", 1)[0]
        result[name] = row
    return result


def _cross_market_decisions(
    *,
    us_reports: list[dict[str, Any]],
    cn_reports: list[dict[str, Any]],
    us_stability: dict[str, Any],
    cn_stability: dict[str, Any],
) -> list[dict[str, Any]]:
    us_candidates = _candidate_rows(us_reports)
    cn_candidates = _candidate_rows(cn_reports)
    us_rows = _stability_rows(us_stability)
    cn_rows = _stability_rows(cn_stability)
    decisions: list[dict[str, Any]] = []
    for spec in TECHNICAL_INDICATOR_SPECS:
        us_economic = _economic_summary(us_candidates[spec.name])
        cn_economic = _economic_summary(cn_candidates[spec.name])
        us_stable = us_rows.get(spec.name, {})
        cn_stable = cn_rows.get(spec.name, {})
        supported = (
            us_stable.get("stable_research_candidate") is True
            and cn_stable.get("stable_research_candidate") is True
            and us_economic["positive_excess_ratio"] >= 0.60
            and cn_economic["positive_excess_ratio"] >= 0.60
            and us_economic["compounded_relative_excess"] > 0.0
            and cn_economic["compounded_relative_excess"] > 0.0
        )
        decisions.append(
            {
                "candidate": spec.name,
                "declared_orientation": spec.orientation,
                "us_stability": us_stable,
                "cn_stability": cn_stable,
                "us_economics": us_economic,
                "cn_economics": cn_economic,
                "cross_market_supported": supported,
                "eligible_for_active_library_review": supported,
                "trade_ready": False,
            }
        )
    return decisions


def _evaluate_market(
    *,
    market: str,
    benchmark: str,
    topk: int,
    windows: list[dict[str, Any]],
    close: pd.DataFrame,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scores = compute_technical_indicator_scores(close)
    raw_returns = _raw_forward_returns(close)
    benchmark_returns = _benchmark_forward_returns(close, benchmark)
    reports: list[dict[str, Any]] = []
    for window in windows:
        window_scores = {
            name: slice_multiindex_dates(
                frame,
                window["test_start"],
                window["test_end"],
            )
            for name, frame in scores.items()
        }
        window_returns = slice_multiindex_dates(
            raw_returns,
            window["test_start"],
            window["test_end"],
        )
        window_benchmark = benchmark_returns.loc[
            pd.Timestamp(window["test_start"]) : pd.Timestamp(window["test_end"])
        ].copy()
        config = ResearchSessionConfig(
            market=market,
            symbols=list(window["symbols"]),
            benchmark=benchmark,
            train_start=window["train_start"],
            train_end=window["train_end"],
            test_start=window["test_start"],
            test_end=window["test_end"],
            holding_days=10,
            rebalance_days=10,
            topk=topk,
            label_type="raw_10d_return",
            model_type="technical_factor_diagnostics",
            factor_expressions=[spec.name for spec in TECHNICAL_INDICATOR_SPECS],
            return_expression=CANONICAL_10D_RETURN_EXPR,
            experiment_id=f"{market}_{window['label']}_technical_indicators",
        )
        report = run_10d_experiment(
            config=config,
            candidates=window_scores,
            raw_returns=window_returns,
            benchmark_returns=window_benchmark,
            output_dir=output_dir / market / "per_window",
        )
        _persist_window_contract(report, window=window)
        reports.append(report)

    stability = summarize_walk_forward_reports(reports, min_windows=3)
    _write_json(output_dir / market / "walk_forward_stability.json", stability)
    return reports, stability


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate fixed Bollinger, MACD, and RSI factors on repaired US "
            "and isolated CN close histories."
        )
    )
    parser.add_argument(
        "--us-provider-root",
        type=Path,
        required=True,
        help=(
            "Root containing data/csv_source and "
            "data/providers/us/provider_manifest.json."
        ),
    )
    parser.add_argument(
        "--cn-provider-manifest",
        type=Path,
        required=True,
        help="Isolated CN provider_manifest.json.",
    )
    parser.add_argument(
        "--cn-csv-dir",
        type=Path,
        action="append",
        required=True,
        help="CN source CSV directory; repeat for fallback directories.",
    )
    parser.add_argument(
        "--us-window-source",
        type=Path,
        default=DEFAULT_US_WINDOW_SOURCE,
    )
    parser.add_argument(
        "--cn-universe",
        type=Path,
        default=DEFAULT_CN_UNIVERSE,
    )
    parser.add_argument(
        "--cn-readiness",
        type=Path,
        default=DEFAULT_CN_READINESS,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    us_manifest_path = (
        args.us_provider_root
        / "data"
        / "providers"
        / "us"
        / "provider_manifest.json"
    )
    us_csv_dir = args.us_provider_root / "data" / "csv_source"
    us_manifest = _read_json(us_manifest_path)
    cn_manifest = _read_json(args.cn_provider_manifest)
    us_identity = str(us_manifest.get("provider_identity_sha256", ""))
    cn_identity = str(cn_manifest.get("provider_identity_sha256", ""))
    if len(us_identity) != 64 or len(cn_identity) != 64:
        raise ValueError("provider identities must be pinned SHA-256 digests")

    us_windows = _us_windows(
        args.us_window_source,
        provider_identity=us_identity,
    )
    cn_windows, cn_metadata = _cn_windows(
        args.cn_universe,
        args.cn_readiness,
        provider_identity=cn_identity,
    )
    us_symbols = sorted(
        {symbol for window in us_windows for symbol in window["symbols"]}
        | {"QQQ"}
    )
    cn_symbols = sorted(set(cn_windows[0]["symbols"]) | {"000300"})
    us_close = _load_close_frame(
        us_symbols,
        csv_dirs=(us_csv_dir,),
        provider_manifest=us_manifest,
    )
    cn_close = _load_close_frame(
        cn_symbols,
        csv_dirs=tuple(args.cn_csv_dir),
        provider_manifest=cn_manifest,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    data_quality = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "manifest_pinned_source_data_quality",
        "us": _audit_provider_sources(
            market="us",
            csv_dirs=(us_csv_dir,),
            provider_manifest=us_manifest,
            survivorship_bias=False,
        ),
        "cn": _audit_provider_sources(
            market="cn",
            csv_dirs=tuple(args.cn_csv_dir),
            provider_manifest=cn_manifest,
            survivorship_bias=True,
        ),
        "scope": (
            "close-only indicators may proceed when close-only eligibility "
            "passes; high/low factors require separate repaired evidence"
        ),
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
    }
    _write_json(args.output_dir / "source_data_quality.json", data_quality)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cross_market_technical_indicator_factor_quality",
        "candidates": [
            {
                "candidate": spec.name,
                "declared_orientation": spec.orientation,
                "parameters": spec.parameters,
                "uses_future_returns": False,
                "parameter_search_performed": False,
            }
            for spec in TECHNICAL_INDICATOR_SPECS
        ],
        "raw_return_provenance": {
            "provenance": "raw_forward_return",
            "horizon": 10,
            "expression": CANONICAL_10D_RETURN_EXPR,
        },
        "us": {
            "provider_identity_sha256": us_identity,
            "provider_manifest_ref": "data/providers/us/provider_manifest.json",
            "provider_manifest_sha256": _sha256(us_manifest_path),
            "membership_mode": "window_start_point_in_time",
            "n_loaded_symbols_including_benchmark": len(us_symbols),
            "topk": 3,
        },
        "cn": {
            "provider_identity_sha256": cn_identity,
            "provider_manifest_ref": "data/providers/cn/provider_manifest.json",
            "provider_manifest_sha256": _sha256(args.cn_provider_manifest),
            "membership_mode": cn_metadata.get("membership_mode"),
            "membership_as_of": cn_metadata.get("membership_as_of"),
            "survivorship_bias": True,
            "n_loaded_symbols_including_benchmark": len(cn_symbols),
            "topk": 15,
        },
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
    }
    _write_json(args.output_dir / "candidate_manifest.json", manifest)

    us_reports, us_stability = _evaluate_market(
        market="us",
        benchmark="QQQ",
        topk=3,
        windows=us_windows,
        close=us_close,
        output_dir=args.output_dir,
    )
    cn_reports, cn_stability = _evaluate_market(
        market="cn",
        benchmark="000300",
        topk=15,
        windows=cn_windows,
        close=cn_close,
        output_dir=args.output_dir,
    )
    decisions = _cross_market_decisions(
        us_reports=us_reports,
        cn_reports=cn_reports,
        us_stability=us_stability,
        cn_stability=cn_stability,
    )
    conclusion = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": "cross_market_technical_indicator_decision",
        "decisions": decisions,
        "supported_candidates": [
            row["candidate"] for row in decisions if row["cross_market_supported"]
        ],
        "active_library_changed": False,
        "next_step": (
            "review_supported_factor_without_parameter_tuning"
            if any(row["cross_market_supported"] for row in decisions)
            else "stop_indicator_tuning_and_improve_information_set"
        ),
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
    }
    _write_json(args.output_dir / "cross_market_decision.json", conclusion)

    print(f"Evidence: {args.output_dir}")
    print(f"Supported candidates: {conclusion['supported_candidates']}")
    print("Trade ready: False")


if __name__ == "__main__":
    main()
