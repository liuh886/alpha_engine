from __future__ import annotations

import pandas as pd

from scripts.data.resolve_formal_provider_cutoff import resolve_formal_provider_cutoff
from src.data.adapters.base import FetchResult
from src.data.router import RouterAttempt, RouterResponse


class FakeRouter:
    def __init__(self, frame: pd.DataFrame | None) -> None:
        self.frame = frame

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        del validate
        if self.frame is None:
            return RouterResponse(
                result=None,
                attempts=[
                    RouterAttempt(
                        provider="yfinance",
                        ok=False,
                        provider_symbol=symbol,
                        error="provider unavailable",
                    )
                ],
            )
        frame = self.frame.copy()
        return RouterResponse(
            result=FetchResult(
                provider="yfinance",
                symbol=symbol,
                market=market,
                start=start,
                end=end,
                df=frame,
                provider_symbol=symbol,
            ),
            attempts=[
                RouterAttempt(
                    provider="yfinance",
                    ok=True,
                    provider_symbol=symbol,
                    rows=len(frame),
                    first_date=str(frame["date"].iloc[0]),
                    last_date=str(frame["date"].iloc[-1]),
                )
            ],
        )


def _frame(*dates: str) -> pd.DataFrame:
    return pd.DataFrame({"date": list(dates)})


def test_resolver_marks_complete_requested_cutoff_current() -> None:
    payload = resolve_formal_provider_cutoff(
        market="us",
        requested_cutoff="2026-08-28",
        seed_cutoff="2026-08-27",
        router=FakeRouter(_frame("2026-08-27", "2026-08-28")),  # type: ignore[arg-type]
    )

    assert payload["status"] == "current"
    assert payload["effective_cutoff"] == "2026-08-28"
    assert payload["effective_seed_cutoff"] == "2026-08-27"
    assert payload["blocker"] is None


def test_resolver_marks_provider_wide_one_session_lag_delayed() -> None:
    payload = resolve_formal_provider_cutoff(
        market="us",
        requested_cutoff="2026-08-28",
        seed_cutoff="2026-08-27",
        router=FakeRouter(_frame("2026-08-27")),  # type: ignore[arg-type]
    )

    assert payload["status"] == "delayed"
    assert payload["observed_cutoff"] == "2026-08-27"
    assert payload["effective_cutoff"] == "2026-08-27"
    assert payload["effective_seed_cutoff"] == "2026-08-26"


def test_resolver_blocks_provider_failure() -> None:
    payload = resolve_formal_provider_cutoff(
        market="us",
        requested_cutoff="2026-08-28",
        seed_cutoff="2026-08-27",
        router=FakeRouter(None),  # type: ignore[arg-type]
    )

    assert payload["status"] == "blocked"
    assert payload["effective_cutoff"] is None
    assert payload["blocker"] == "benchmark provider fetch failed"


def test_resolver_blocks_regression_behind_governed_seed() -> None:
    payload = resolve_formal_provider_cutoff(
        market="us",
        requested_cutoff="2026-08-28",
        seed_cutoff="2026-08-27",
        router=FakeRouter(_frame("2026-08-26")),  # type: ignore[arg-type]
    )

    assert payload["status"] == "blocked"
    assert payload["observed_cutoff"] == "2026-08-26"
    assert payload["blocker"] == (
        "provider complete-session watermark regressed behind governed seed"
    )
