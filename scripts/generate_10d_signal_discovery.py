"""Generate the canonical fixed-10D signal-discovery evidence report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import qlib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.research.signal_discovery import (  # noqa: E402
    canonical_output_dir,
    run_signal_discovery_comparison,
)

RAW_RETURN_EXPRESSION = "Ref($close, -10) / $close - 1"
MOMENTUM_EXPRESSION = "$close / Ref($close, 10) - 1"


def _normalise_panel(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if not isinstance(frame.index, pd.MultiIndex):
        raise ValueError("Qlib panel must use a (datetime, instrument) MultiIndex")
    panel = frame.reorder_levels(["datetime", "instrument"]).sort_index()
    panel = panel.rename(columns={panel.columns[0]: column})[[column]]
    panel[column] = panel[column].replace([np.inf, -np.inf], np.nan)
    return panel.dropna(subset=[column])


def _load_predictions(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["datetime"])
    required = {"datetime", "instrument", "score"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Predictions file is missing columns: {sorted(missing)}")
    return frame.set_index(["datetime", "instrument"])[["score"]].sort_index()


def generate_report(
    predictions_path: Path,
    provider_uri: Path,
    output_dir: Path,
    benchmark: str = "QQQ",
) -> Path:
    """Load canonical 10D inputs and write one comparison report."""
    from qlib.data import D

    predictions = _load_predictions(predictions_path)
    dates = predictions.index.get_level_values("datetime")
    instruments = predictions.index.get_level_values("instrument").unique().tolist()
    start_time, end_time = str(dates.min().date()), str(dates.max().date())

    qlib.init(provider_uri=str(provider_uri), region="us")
    raw_returns = _normalise_panel(
        D.features(
            instruments,
            [RAW_RETURN_EXPRESSION],
            start_time=start_time,
            end_time=end_time,
        ),
        "return",
    )
    raw_returns.attrs.update(
        provenance="raw_forward_return",
        label_expression=RAW_RETURN_EXPRESSION,
        horizon=10,
    )
    factor_predictions = _normalise_panel(
        D.features(
            instruments,
            [MOMENTUM_EXPRESSION],
            start_time=start_time,
            end_time=end_time,
        ),
        "score",
    )

    benchmark_returns: pd.DataFrame | None = None
    try:
        benchmark_raw = D.features(
            [benchmark],
            [RAW_RETURN_EXPRESSION],
            start_time=start_time,
            end_time=end_time,
        )
        benchmark_returns = (
            benchmark_raw.droplevel("instrument")
            .rename(columns={benchmark_raw.columns[0]: "return"})[["return"]]
            .sort_index()
        )
    except Exception:
        benchmark_returns = None

    report = run_signal_discovery_comparison(
        market="us",
        lgbm_predictions=predictions,
        raw_returns=raw_returns,
        factor_baseline_predictions=factor_predictions,
        benchmark_returns=benchmark_returns,
        topk=15,
        rebalance_days=10,
        cost_bps=20,
        output_dir=output_dir,
    )
    report.summary["input_provenance"] = {
        "prediction_artifact_id": predictions_path.parent.name,
        "prediction_file": predictions_path.name,
        "raw_return_expression": RAW_RETURN_EXPRESSION,
        "factor_expression": MOMENTUM_EXPRESSION,
        "benchmark": benchmark,
    }
    report.write(output_dir)
    return output_dir / f"{report.market}_signal_discovery_report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--provider-uri", type=Path, default=PROJECT_ROOT / "data" / "watchlist")
    parser.add_argument("--output-dir", type=Path, default=canonical_output_dir(PROJECT_ROOT))
    parser.add_argument("--benchmark", default="QQQ")
    args = parser.parse_args()
    path = generate_report(args.predictions, args.provider_uri, args.output_dir, args.benchmark)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
