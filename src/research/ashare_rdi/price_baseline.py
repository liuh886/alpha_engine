"""Descriptive CSI300 price-only baseline. Not an RDI signal or OOS claim."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Sequence

from .outcomes import PriceBar
from .phase2 import read_price_csv


def descriptive_drawdown_comparison(
    bars: Sequence[PriceBar],
    *,
    lookback_sessions: int = 60,
    drawdown_threshold: float = -0.10,
    severe_loss_threshold: float = -0.05,
    horizons: tuple[int, ...] = (7, 14, 28),
) -> dict[str, object]:
    """Price-only fixed-rule *historical association* with overlapping labels.

    This does not estimate predictive significance or adjust for macro regimes.
    Close(t) -> close(t+h) is a price index directional outcome, not trade P&L.
    """
    dates = [b.session for b in bars]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("index bars must be ordered and unique")
    if not 0 < lookback_sessions < len(bars):
        raise ValueError("inadequate warmup")
    if not -1 < drawdown_threshold < 0 or not -1 < severe_loss_threshold < 0:
        raise ValueError("thresholds must be fractions strictly between -1 and 0")
    if not horizons or any(h <= 0 for h in horizons):
        raise ValueError("horizons must be positive")
    horizon_rows: list[dict[str, object]] = []
    for h in horizons:
        groups: dict[str, list[tuple[float, float]]] = {
            "drawdown_at_least_threshold": [],
            "other": [],
        }
        for i in range(lookback_sessions - 1, len(bars) - h):
            peak = max(b.close for b in bars[i - lookback_sessions + 1 : i + 1])
            dd = bars[i].close / peak - 1
            end_return = bars[i + h].close / bars[i].close - 1
            worst_excursion = min(b.low for b in bars[i + 1 : i + h + 1]) / bars[i].close - 1
            key = "drawdown_at_least_threshold" if dd <= drawdown_threshold else "other"
            groups[key].append((end_return, worst_excursion))

        def summary(values: list[tuple[float, float]]) -> dict[str, object]:
            n = len(values)
            if not n:
                return {"observations": 0, "mean_return": None, "p_down": None,
                        "p_severe_loss": None, "mean_worst_excursion": None}
            return {
                "observations": n,
                "mean_return": sum(x for x, _ in values) / n,
                "p_down": sum(x < 0 for x, _ in values) / n,
                "p_severe_loss": sum(x <= severe_loss_threshold for x, _ in values) / n,
                "mean_worst_excursion": sum(x for _, x in values) / n,
            }

        horizon_rows.append({
            "horizon_sessions": h,
            "drawdown_at_least_threshold": summary(groups["drawdown_at_least_threshold"]),
            "other": summary(groups["other"]),
        })
    return {
        "status": "price_only_descriptive_not_out_of_sample",
        "reference": "CSI300 / 000300.SH",
        "first_price_session": dates[0].isoformat(),
        "last_price_session": dates[-1].isoformat(),
        "rows": len(bars),
        "lookback_sessions": lookback_sessions,
        "drawdown_threshold": drawdown_threshold,
        "severe_loss_threshold": severe_loss_threshold,
        "results": horizon_rows,
        "event_rdi_evaluated": False,
        "predictive_skill_established": False,
        "research_only": True,
        "trade_ready": False,
        "limitations": [
            "overlapping forward labels, not independent observations",
            "no official calendar gap or independent provider quality certification in this diagnostic",
            "single descriptive sample, no purged out-of-sample test or confidence intervals",
            "no PIT archival event coverage; price-only association is not RDI validation",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Price-only index baseline (descriptive)")
    parser.add_argument("--prices", default="data/csv_source/000300.csv")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    result = descriptive_drawdown_comparison(read_price_csv(Path(args.prices)))
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        dest = Path(args.out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
