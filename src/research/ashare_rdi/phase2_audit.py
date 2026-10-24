"""Research entrypoint: fail closed when archived event coverage is absent.

This command never calls providers, trains a model or creates a trading signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.research.ashare_rdi.phase2 import CSI300_INCEPTION, read_price_csv

STUDY_HORIZONS = (7, 14, 28)


def source_readiness(price_path: Path) -> dict[str, object]:
    bars = read_price_csv(price_path, min_session=CSI300_INCEPTION)
    digest = hashlib.sha256(price_path.read_bytes()).hexdigest()
    return {
        "status": "blocked_event_pit_coverage",
        "benchmark": "CSI300 / 000300.SH",
        "benchmark_type": "nontraded_equity_index",
        "benchmark_source": price_path.as_posix(),
        "price_file_sha256": digest,
        "price_history_rows": len(bars),
        "first_observed_session": bars[0].session.isoformat(),
        "last_observed_session": bars[-1].session.isoformat(),
        "event_history_ready": False,
        "why_no_rdi_score": (
            "No verified PIT coverage-by-session archive for required event families. "
            "Missing events must not be scored as zero."
        ),
        "horizons_trading_sessions": list(STUDY_HORIZONS),
        "research_only": True,
        "trade_ready": False,
        "predictive_claim": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RDI phase2 governed input readiness audit")
    parser.add_argument("--benchmark-csv", default="data/csv_source/000300.csv")
    parser.add_argument("--output", default="", help="optional JSON output path")
    args = parser.parse_args()
    result = source_readiness(Path(args.benchmark_csv))
    formatted = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(formatted + "\n", encoding="utf-8")
    print(formatted)


if __name__ == "__main__":
    main()
