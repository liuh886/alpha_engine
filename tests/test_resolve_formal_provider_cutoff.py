from __future__ import annotations

import pandas as pd

from scripts.data.resolve_formal_provider_cutoff import resolve_formal_provider_cutoff
from src.data.adapters.base import FetchResult
from src.data.router import RouterAttempt, RouterResponse


class FakeRouter:
    def __init__(self, frame: pd.DataFrame | None) -> None:
        self.frame = frame
        self.last_request: dict[str, object] | None = None
        self.requests: list[dict[str, object]] = []

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        self.last_request = {
            "symbol": symbol,
            "market": market,
            "start": start,
            "end": end,
            "validate": validate,
        }
        self.requests.append(dict(self.last_request))
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


def test_cn_resolver_uses_benchmark_watermark_before_admitting_cutoff(
    monkeypatch,
) -> None:
    import scripts.data.resolve_formal_provider_cutoff as module

    monkeypatch.setattr(module, "PROBE_DELAY_SECONDS", 0.0)
    router = FakeRouter(_frame("2026-08-31"))
    payload = resolve_formal_provider_cutoff(
        market="cn",
        requested_cutoff="2026-09-01",
        seed_cutoff="2026-08-31",
        router=router,  # type: ignore[arg-type]
    )

    assert router.requests[0] == {
        "symbol": "000300",
        "market": "cn",
        "start": "2026-08-31",
        "end": "2026-09-01",
        "validate": True,
    }
    assert payload["benchmark"] == "000300"
    assert payload["status"] == "delayed"
    assert payload["observed_cutoff"] == "2026-08-31"
    assert payload["effective_cutoff"] == "2026-08-31"
    assert payload["effective_seed_cutoff"] == "2026-08-28"


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


class LagRouter(FakeRouter):
    """Benchmark is current but one strategy symbol lags (vendor EOD delay)."""

    def fetch_daily_bars(self, *, symbol: str, **kwargs):
        if symbol == "002156":
            frame = _frame("2026-08-27", "2026-08-30")
        else:
            frame = _frame("2026-08-27", "2026-08-31")
        self.frame = frame
        return super().fetch_daily_bars(symbol=symbol, **kwargs)


def test_cn_probe_lowers_cutoff_when_strategy_symbol_lags(
    monkeypatch,
) -> None:
    import scripts.data.resolve_formal_provider_cutoff as module

    monkeypatch.setattr(module, "PROBE_DELAY_SECONDS", 0.0)
    router = LagRouter(_frame("2026-08-31"))
    payload = resolve_formal_provider_cutoff(
        market="cn",
        requested_cutoff="2026-09-01",
        seed_cutoff="2026-08-31",
        router=router,  # type: ignore[arg-type]
    )

    assert payload["status"] == "delayed"
    assert payload["observed_cutoff"] == "2026-08-31"
    assert payload["member_watermarks"]["002156"] == "2026-08-30"
    assert payload["effective_cutoff"] == "2026-08-30"
    assert payload["blocker"] is None


def test_cn_probe_blocks_when_strategy_symbol_unavailable(
    monkeypatch,
) -> None:
    import scripts.data.resolve_formal_provider_cutoff as module

    monkeypatch.setattr(module, "PROBE_DELAY_SECONDS", 0.0)

    class DeadRouter(FakeRouter):
        def fetch_daily_bars(self, *, symbol: str, **kwargs):
            if symbol == "002156":
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
            return super().fetch_daily_bars(symbol=symbol, **kwargs)

    router = DeadRouter(_frame("2026-08-31"))
    payload = resolve_formal_provider_cutoff(
        market="cn",
        requested_cutoff="2026-09-01",
        seed_cutoff="2026-08-31",
        router=router,  # type: ignore[arg-type]
    )

    assert payload["status"] == "blocked"
    assert payload["effective_cutoff"] is None
    assert "002156" in str(payload["blocker"])


def test_us_probe_stays_benchmark_only(monkeypatch) -> None:
    import scripts.data.resolve_formal_provider_cutoff as module

    monkeypatch.setattr(module, "PROBE_DELAY_SECONDS", 0.0)
    router = FakeRouter(_frame("2026-08-27", "2026-08-28"))
    payload = resolve_formal_provider_cutoff(
        market="us",
        requested_cutoff="2026-08-28",
        seed_cutoff="2026-08-27",
        router=router,  # type: ignore[arg-type]
    )

    assert payload["effective_cutoff"] == "2026-08-28"
    assert payload["member_watermarks"] == {}
    assert [request["symbol"] for request in router.requests] == ["QQQ"]
