#!/usr/bin/env python3
"""Run the frozen research-only CN_27 V1.0 historical challenge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.research.all_weather_alpha_rotation import (
    fetch_all_weather_bars,
    load_all_weather_contract,
    materialize_all_weather_evidence,
    run_all_weather_backtest,
)


DEFAULT_SPEC = Path("configs/research_paradigms/cn_27_v1_0.yaml")
DEFAULT_OUTPUT = Path("artifacts/evidence/cn_27_v1_0")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prices-csv",
        type=Path,
        help="Reuse a complete governed long-form OHLCV file instead of refreshing providers.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-workers", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = load_all_weather_contract(DEFAULT_SPEC)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    provider_coverage = None
    if args.prices_csv is None:
        bars, provider_coverage = fetch_all_weather_bars(
            contract,
            max_workers=args.max_workers,
        )
        prices_path = output / "source_ohlcv.csv"
        bars.to_csv(prices_path, index=False, date_format="%Y-%m-%d")
    else:
        prices_path = args.prices_csv.resolve()
        bars = pd.read_csv(prices_path, dtype={"symbol": str})
    result = run_all_weather_backtest(bars, contract)
    decision = materialize_all_weather_evidence(
        output_dir=output,
        source_prices_path=prices_path,
        contract=contract,
        result=result,
        provider_coverage=provider_coverage,
    )
    print(json.dumps(decision, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
