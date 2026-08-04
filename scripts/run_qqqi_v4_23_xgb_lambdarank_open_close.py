"""Run v4.23 with the audited Yahoo adjusted-open/close research adapter."""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

import scripts.run_qqqi_v4_23_xgb_lambdarank_state_machine as runner
from src.data.adapters.yfinance_open_close_research_adapter import (
    YFinanceOpenCloseResearchAdapter,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars


def _fetch_open_close(
    *,
    symbols: Sequence[str],
    start: str,
    end: str | None = None,
    adapter: Any | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    del adapter
    bars, coverage = fetch_adjusted_daily_bars(
        symbols=symbols,
        start=start,
        end=end,
        adapter=YFinanceOpenCloseResearchAdapter(),
    )
    coverage["open_close_only_research"] = True
    coverage["provider_adjusted_open_close_preserved"] = True
    coverage["synthetic_high_low_used_for_range_features"] = False
    return bars, coverage


def main() -> int:
    runner.fetch_adjusted_daily_bars = _fetch_open_close
    return runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
