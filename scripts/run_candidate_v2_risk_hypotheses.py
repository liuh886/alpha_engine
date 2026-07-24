"""Evaluate portfolio-risk overlay hypotheses for candidate_v2.

Uses the already-committed candidate_v2_universe_robustness evidence to
reconstruct four fixed portfolio variants from scratch — no re-training,
no parameter search, no gate changes.

Variants
--------
frozen_baseline
    Top-3 equal weight with 50% gross when QQQ 20D trend is negative.
    Must reproduce the existing evidence result exactly.
top3_max20pct_per_name
    Top-3 equal weight, then each name capped at 20 % of the portfolio's
    gross exposure (``weight = min(1/3, 0.20 * gross_exposure)``) *before*
    the benchmark-trend exposure rule is applied.
top3_positive_20d_return_only
    Keep baseline Top-3 equal weight only for names whose backward-looking
    20D return at the rebalance date is positive.  Excluded names get zero
    weight (no re-allocation to surviving names).
top3_inverse_vol20_normalized
    Weights proportional to 1 / historical 20D volatility, re-normalised
    so the sum equals the baseline gross exposure (1.0 or 0.5 depending
    on QQQ 20D trend).

All variants use the **exact same** selection (the frozen score's Top-3 at
each rebalance date) and the canonical raw 10D returns already recorded in
the evidence.  Only the weighting scheme changes.

Output
------
artifacts/evidence/candidate_v2_risk_hypotheses/
    per_window/           one compact JSON per cohort × window
    per_variant.json      variant-level aggregate with frozen gate
    cross_variant.json    cross-universe robustness decision
    evidence_manifest.json
"""  # noqa: E501

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.risk_control_variants import (
    RiskVariantReport,
    aggregate_variant_reports,
)

# ══════════════════════════════════════════════════════════════════════════════
# Constants — match the frozen run
# ══════════════════════════════════════════════════════════════════════════════

FROZEN_TOP_N = 3
FROZEN_COST_BPS = 20.0
FROZEN_EXPOSURE = 0.5
REBALANCE_DAYS = 10
REQUIRED_WINDOWS = 4
MIN_POSITIVE_EXCESS_WINDOWS = 3
MIN_COMPOUNDED_RELATIVE_EXCESS = 0.30
MAX_DRAWDOWN_GATE = -0.15

EVIDENCE_DIR = Path("artifacts/evidence/candidate_v2_universe_robustness")
PER_WINDOW_DIR = EVIDENCE_DIR / "per_window"

COHORT_NAMES = ("default_10_symbols", "expanded_50_symbols", "expanded_100_symbols")
WINDOW_LABELS = ("2024H1", "2024H2", "2025H1", "2025H2")

VARIANT_FROZEN = "frozen_baseline"
VARIANT_MAX20PCT = "top3_max20pct_per_name"
VARIANT_POS20D = "top3_positive_20d_return_only"
VARIANT_INV_VOL20 = "top3_inverse_vol20_normalized"
ALL_VARIANTS = (VARIANT_FROZEN, VARIANT_MAX20PCT, VARIANT_POS20D, VARIANT_INV_VOL20)

# ══════════════════════════════════════════════════════════════════════════════
# Evidence loader
# ══════════════════════════════════════════════════════════════════════════════


def load_per_window_evidence(
    cohort: str,
    window_label: str,
    *,
    evidence_root: Path = PER_WINDOW_DIR,
) -> dict[str, Any]:
    """Load one per-window evidence JSON from the committed artifacts."""
    path = evidence_root / f"{cohort}_{window_label}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Evidence file not found: {path}  "
            f"(re-run the universe-robustness experiment first)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_id() -> str:
    return (
        "blend:ranker_momentum:momentum_volatility_volume:"
        "gain5_round100_leaves31_leaf10_lr0.05:ranker0.5_momentum0.5"
    )


# ══════════════════════════════════════════════════════════════════════════════
# US trading calendar
# ══════════════════════════════════════════════════════════════════════════════


def _load_us_calendar(
    data_root: Path,
    *,
    start: str | None = None,
    end: str | None = None,
) -> pd.DatetimeIndex:
    """Load US trading calendar from the verified market-specific provider.

    Reads the simple one-date-per-line ``day.txt`` file so Qlib initialisation
    is not required for the calendar alone.
    """
    from src.data.market_provider import market_provider_path

    provider_dir = market_provider_path(data_root, "us")
    cal_path = provider_dir / "calendars" / "day.txt"
    if not cal_path.exists():
        raise FileNotFoundError(f"US provider calendar not found: {cal_path}")
    dates: list[pd.Timestamp] = []
    for line in cal_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            dates.append(pd.Timestamp(stripped))
    calendar = pd.DatetimeIndex(sorted(set(dates)))
    if start is not None:
        calendar = calendar[calendar >= pd.Timestamp(start)]
    if end is not None:
        calendar = calendar[calendar <= pd.Timestamp(end)]
    if calendar.empty:
        raise ValueError(
            f"US calendar has no trading sessions in {start}..{end}"
        )
    return calendar


def _verify_us_provider(data_root: Path) -> dict[str, Any]:
    """Fail closed unless the market-specific US provider is intact."""
    from src.data.market_provider import load_provider_manifest, market_provider_path

    return load_provider_manifest(
        market_provider_path(data_root, "us"),
        expected_market="us",
        required=True,
        verify_files=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Backward-looking feature loader (requires Qlib)
# ══════════════════════════════════════════════════════════════════════════════


def _init_qlib(data_root: Path) -> None:
    """Initialise Qlib with the US market provider."""
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
    from src.data.market_provider import market_provider_path

    provider_uri = str(market_provider_path(data_root, "us"))
    safe_qlib_init(
        build_qlib_init_cfg(None, market="us", provider_uri_default=provider_uri)
    )


def _load_backward_20d_return(
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Load backward-looking 20D return for each symbol.

    Returns a DataFrame with MultiIndex (datetime, instrument) and a single
    'return_20d' column.  The value at date T is the return over the **prior**
    20 trading sessions: ``close(T) / close(T-20) - 1``.
    """
    from qlib.data import D

    dollar = chr(36)
    expr = f"{dollar}close/Ref({dollar}close,20)-1"
    raw = D.features(symbols, [expr], start_time=start, end_time=end)
    raw = raw.replace([np.inf, -np.inf], np.nan)
    if isinstance(raw.index, pd.MultiIndex) and raw.index.names == [
        "instrument",
        "datetime",
    ]:
        raw = raw.swaplevel().sort_index()
    raw.columns = ["return_20d"]
    return raw


def _load_vol20(
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    """Load 20-trading-session historical volatility for each symbol.

    Returns DataFrame with MultiIndex (datetime, instrument) and 'vol20'.
    Uses daily log-return standard deviation over the trailing 20 sessions.
    """
    from qlib.data import D

    dollar = chr(36)
    expr = f"Std({dollar}close/Ref({dollar}close,1)-1,20)"
    raw = D.features(symbols, [expr], start_time=start, end_time=end)
    raw = raw.replace([np.inf, -np.inf], np.nan)
    if isinstance(raw.index, pd.MultiIndex) and raw.index.names == [
        "instrument",
        "datetime",
    ]:
        raw = raw.swaplevel().sort_index()
    raw.columns = ["vol20"]
    return raw


# ══════════════════════════════════════════════════════════════════════════════
# Returns / benchmark reconstruction from evidence
# ══════════════════════════════════════════════════════════════════════════════


def _reconstruct_returns(
    evidence: dict[str, Any],
) -> pd.DataFrame:
    """Build the raw 10D returns DataFrame from evidence period data.

    Only returns for symbols that were *selected* at each rebalance date are
    included — that is sufficient because the four variants only redistribute
    or gate weights among the same Top-3 selection.
    """
    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    rows: list[dict[str, Any]] = []
    for period in periods:
        date = pd.Timestamp(period["date"])
        for holding in period.get("selected_holdings", []):
            rows.append(
                {
                    "datetime": date,
                    "instrument": holding["symbol"],
                    "return": holding["raw_return"],
                }
            )
    if not rows:
        raise ValueError("evidence contains no period data to reconstruct returns")
    df = pd.DataFrame(rows)
    df = df.set_index(["datetime", "instrument"]).sort_index()
    df.attrs["provenance"] = "raw_forward_return"
    df.attrs["horizon"] = 10
    return df


def _reconstruct_benchmark_returns(
    evidence: dict[str, Any],
) -> pd.DataFrame:
    """Build the benchmark 10D returns DataFrame from evidence period data."""
    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    rows: list[dict[str, Any]] = []
    for period in periods:
        rows.append(
            {
                "datetime": pd.Timestamp(period["date"]),
                "return": period["portfolio"]["benchmark_return"],
            }
        )
    if not rows:
        raise ValueError("evidence contains no period data for benchmark returns")
    df = pd.DataFrame(rows)
    df = df.set_index("datetime")
    df.attrs["provenance"] = "raw_forward_return"
    df.attrs["horizon"] = 10
    return df


# ══════════════════════════════════════════════════════════════════════════════
# Variant weight constructors
# ══════════════════════════════════════════════════════════════════════════════


def _variant_frozen_baseline(
    evidence: dict[str, Any],
) -> pd.DataFrame:
    """Reconstruct the exact target weights from the evidence period data.

    These weights must match what the frozen ``top3_benchmark_trend_filter``
    variant produced in the universe-robustness run.
    """
    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for period in periods:
        date = pd.Timestamp(period["date"])
        for holding in period.get("selected_holdings", []):
            # The evidence already stores the *final* weight (after benchmark
            # trend scaling) — use it directly.
            rows.append((date, holding["symbol"], holding["weight"]))
    index = pd.MultiIndex.from_tuples(
        [(d, s) for d, s, _ in rows], names=["datetime", "instrument"]
    )
    return pd.DataFrame({"target_weight": [w for _, _, w in rows]}, index=index)


def _variant_max20pct_per_name(
    evidence: dict[str, Any],
) -> pd.DataFrame:
    """Top-3 equal weight, each name capped at 20 % of gross exposure.

    weight = min(1/3, 0.20 * gross_exposure)

    The cap is applied *before* the benchmark-trend exposure rule, so
    ``gross_exposure`` here is the pre-trend baseline (1.0 always).
    """
    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for period in periods:
        date = pd.Timestamp(period["date"])
        gross_exposure = period["portfolio"]["gross_exposure"]
        holdings_list = period.get("selected_holdings", [])
        n_holdings = len(holdings_list)
        if n_holdings == 0:
            continue
        base_weight = 1.0 / n_holdings
        # Per-name cap at 20 % of *pre-trend* gross exposure (= 1.0).
        capped = min(base_weight, 0.20 * 1.0)
        # Then apply the actual benchmark-trend gross_exposure.
        for holding in holdings_list:
            rows.append((date, holding["symbol"], capped * gross_exposure))
    index = pd.MultiIndex.from_tuples(
        [(d, s) for d, s, _ in rows], names=["datetime", "instrument"]
    )
    return pd.DataFrame({"target_weight": [w for _, _, w in rows]}, index=index)


def _variant_positive_20d_return_only(
    evidence: dict[str, Any],
    *,
    ret20d: pd.DataFrame,
) -> pd.DataFrame:
    """Keep baseline Top-3 equal weight only for names with positive 20D return.

    A name whose backward-looking 20D return at the rebalance date is
    non-positive receives zero weight.  No weight is redistributed to other
    names.
    """
    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for period in periods:
        date = pd.Timestamp(period["date"])
        gross_exposure = period["portfolio"]["gross_exposure"]
        holdings_list = period.get("selected_holdings", [])
        n_holdings = len(holdings_list)
        if n_holdings == 0:
            continue
        base_weight = 1.0 / n_holdings
        for holding in holdings_list:
            symbol = holding["symbol"]
            try:
                val = float(ret20d.loc[(date, symbol), "return_20d"])
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"missing backward 20D return for {symbol} on {date.date()}"
                ) from exc
            if not np.isfinite(val):
                raise ValueError(
                    f"non-finite backward 20D return for {symbol} on {date.date()}"
                )
            weight = base_weight * gross_exposure if val > 0 else 0.0
            rows.append((date, symbol, weight))
    index = pd.MultiIndex.from_tuples(
        [(d, s) for d, s, _ in rows], names=["datetime", "instrument"]
    )
    return pd.DataFrame({"target_weight": [w for _, _, w in rows]}, index=index)


def _variant_inverse_vol20_normalized(
    evidence: dict[str, Any],
    *,
    vol20: pd.DataFrame,
) -> pd.DataFrame:
    """Inverse 20D volatility weights normalised to baseline gross exposure.

    For each rebalance date, weights are ``(1/vol_i) / sum(1/vol)`` then
    multiplied by the benchmark-trend gross exposure factor.
    """
    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for period in periods:
        date = pd.Timestamp(period["date"])
        gross_exposure = period["portfolio"]["gross_exposure"]
        holdings_list = period.get("selected_holdings", [])
        n_holdings = len(holdings_list)
        if n_holdings == 0:
            continue

        inv_vols: list[float] = []
        valid_symbols: list[str] = []
        for holding in holdings_list:
            symbol = holding["symbol"]
            try:
                val = float(vol20.loc[(date, symbol), "vol20"])
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"missing historical 20D volatility for {symbol} on {date.date()}"
                ) from exc
            if not np.isfinite(val) or val <= 1e-12:
                raise ValueError(
                    f"invalid historical 20D volatility for {symbol} on "
                    f"{date.date()}: {val}"
                )
            inv_vols.append(1.0 / val)
            valid_symbols.append(symbol)

        inv_sum = sum(inv_vols)
        for symbol, inv in zip(valid_symbols, inv_vols):
            weight = (inv / inv_sum) * gross_exposure
            rows.append((date, symbol, weight))
    index = pd.MultiIndex.from_tuples(
        [(d, s) for d, s, _ in rows], names=["datetime", "instrument"]
    )
    return pd.DataFrame({"target_weight": [w for _, _, w in rows]}, index=index)


# ══════════════════════════════════════════════════════════════════════════════
# Per-window × variant evaluation
# ══════════════════════════════════════════════════════════════════════════════


def evaluate_variant_on_window(
    evidence: dict[str, Any],
    *,
    variant_id: str,
    evaluation_dates: tuple[pd.Timestamp, ...],
    ret20d: pd.DataFrame | None = None,
    vol20_df: pd.DataFrame | None = None,
    cost_bps: float = FROZEN_COST_BPS,
) -> RiskVariantReport:
    """Evaluate one risk variant on one window using evidence data.

    Parameters
    ----------
    evidence : dict
        Parsed per-window evidence JSON.
    variant_id : str
        One of ``ALL_VARIANTS``.
    ret20d : pd.DataFrame or None
        Backward 20D returns (MultiIndex) — required for ``positive_20d``.
    vol20_df : pd.DataFrame or None
        20D volatility — required for ``inverse_vol20``.
    """
    returns = _reconstruct_returns(evidence)
    benchmark_returns = _reconstruct_benchmark_returns(evidence)

    if variant_id == VARIANT_FROZEN:
        target_weights = _variant_frozen_baseline(evidence)
    elif variant_id == VARIANT_MAX20PCT:
        target_weights = _variant_max20pct_per_name(evidence)
    elif variant_id == VARIANT_POS20D:
        if ret20d is None:
            raise ValueError("ret20d required for positive_20d_return_only variant")
        target_weights = _variant_positive_20d_return_only(evidence, ret20d=ret20d)
    elif variant_id == VARIANT_INV_VOL20:
        if vol20_df is None:
            raise ValueError("vol20_df required for inverse_vol20 variant")
        target_weights = _variant_inverse_vol20_normalized(evidence, vol20=vol20_df)
    else:
        raise ValueError(f"unknown variant: {variant_id}")

    from src.research.risk_control_variants import evaluate_variant_weights

    return evaluate_variant_weights(
        target_weights,
        returns,
        benchmark_returns,
        variant_id=variant_id,
        evaluation_dates=evaluation_dates,
        rebalance_days=REBALANCE_DAYS,
        cost_bps=cost_bps,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Calendar validation
# ══════════════════════════════════════════════════════════════════════════════


def assert_calendar_matches_evidence(
    calendar: pd.DatetimeIndex,
    evidence: dict[str, Any],
) -> tuple[pd.Timestamp, ...]:
    """Verify that sampling the US calendar matches the evidence period dates.

    The window's full US trading calendar is sampled every 10 sessions.  Each
    sampled date must appear in the evidence period records.  This guards
    against calendar-contamination bugs (CN/HK sessions in a US-only test).
    """
    window = evidence.get("window", {})
    test_start = window.get("test_start")
    test_end = window.get("test_end")
    if test_start is None or test_end is None:
        raise ValueError("evidence window is missing test_start/test_end")

    window_cal = calendar[
        (calendar >= pd.Timestamp(test_start))
        & (calendar <= pd.Timestamp(test_end))
    ]
    if window_cal.empty:
        raise ValueError(
            f"US calendar has no sessions in window {test_start}..{test_end}"
        )
    sampled = window_cal[::REBALANCE_DAYS]

    periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
    period_dates = sorted(set(pd.Timestamp(p["date"]) for p in periods))

    if list(sampled) != period_dates:
        raise AssertionError(
            "US-calendar sampled dates do not exactly match evidence periods: "
            f"sampled={[str(d.date()) for d in sampled]}, "
            f"evidence={[str(d.date()) for d in period_dates]}"
        )
    return tuple(pd.Timestamp(date) for date in window_cal)


# ══════════════════════════════════════════════════════════════════════════════
# Evidence manifest for risk hypotheses
# ══════════════════════════════════════════════════════════════════════════════


def _build_evidence_manifest(
    decision: dict[str, Any],
    provider_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build the evidence manifest JSON."""
    return {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_risk_hypotheses",
        "candidate": _candidate_id(),
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "n_variants": len(ALL_VARIANTS),
        "variants": list(ALL_VARIANTS),
        "n_cohorts": len(COHORT_NAMES),
        "cohorts": list(COHORT_NAMES),
        "n_windows_per_variant": REQUIRED_WINDOWS,
        "n_window_files": len(COHORT_NAMES) * REQUIRED_WINDOWS,
        "rebalance_days": REBALANCE_DAYS,
        "cost_bps": FROZEN_COST_BPS,
        "construction": {
            "top_n": FROZEN_TOP_N,
            "negative_benchmark_trend_exposure": FROZEN_EXPOSURE,
        },
        "turnover_model": "cash_inclusive_one_way",
        "provider_identity_sha256": provider_manifest["provider_identity_sha256"],
        "decision": decision.get("decision_status", "no_variant_passes_gate"),
        "candidate_v2_robust_overlay": decision.get(
            "candidate_v2_robust_overlay", False
        ),
        "non_trade_ready_warning": (
            "Portfolio-risk overlay evidence is diagnostic only. "
            "No variant in this experiment has been promoted, tested in "
            "a point-in-time universe, or approved for trading. "
            "Results use static current-member cohorts from the US provider "
            "snapshot, which introduces survivorship bias."
        ),
    }


def _assert_baseline_reconciles(
    report: RiskVariantReport,
    evidence: dict[str, Any],
    *,
    atol: float = 1e-12,
) -> None:
    """Prove the reconstructed frozen baseline matches its source evidence."""
    expected = evidence["candidate_v2"]
    checks = {
        "total_return": report.total_return,
        "benchmark_return": report.benchmark_return,
        "relative_excess_return": report.relative_excess_return,
        "max_drawdown": report.max_drawdown,
        "turnover": report.turnover,
        "costs": report.costs,
        "mean_gross_exposure": report.mean_gross_exposure,
    }
    for field, actual in checks.items():
        wanted = float(expected[field])
        if not np.isclose(actual, wanted, rtol=0.0, atol=atol):
            raise AssertionError(
                f"frozen baseline does not reconcile for {field}: "
                f"reconstructed={actual}, evidence={wanted}"
            )
    if report.n_periods != int(expected["n_periods"]):
        raise AssertionError(
            "frozen baseline period count does not reconcile: "
            f"reconstructed={report.n_periods}, evidence={expected['n_periods']}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Main run
# ══════════════════════════════════════════════════════════════════════════════


def run(
    *,
    data_root: Path,
    evidence_root: Path = EVIDENCE_DIR,
    output_root: Path | None = None,
    require_qlib: bool = True,
) -> dict[str, Any]:
    """Run the portfolio-risk hypothesis evaluation.

    Parameters
    ----------
    data_root : Path
        Read-only repository root containing ``data/providers/us``.
    evidence_root : Path
        Path to the committed evidence directory.  Defaults to
        ``artifacts/evidence/candidate_v2_universe_robustness``.
    output_root : Path or None
        Output directory.  Defaults to
        ``artifacts/evidence/candidate_v2_risk_hypotheses``.
    require_qlib : bool
        If True, initialise Qlib to load backward-looking features
        (20D return, 20D vol).  Set False in tests that provide these
        features directly.
    """
    if output_root is None:
        output_root = (
            Path("artifacts") / "evidence" / "candidate_v2_risk_hypotheses"
        )
    per_window_out = output_root / "per_window"
    per_window_out.mkdir(parents=True, exist_ok=True)
    for stale_path in per_window_out.glob("*.json"):
        stale_path.unlink()

    # ── Verified US-only provider and trading calendar ────────────────────
    provider_manifest = _verify_us_provider(data_root)
    calendar = _load_us_calendar(data_root)

    # ── Qlib initialisation for backward-looking features ──────────────────
    if require_qlib:
        _init_qlib(data_root)
        from qlib.data import D  # noqa: F401 — verify init is live

    # ── Evaluate each cohort × window × variant ────────────────────────────
    # results[variant_id][cohort_name] = per-window reports
    results: dict[str, dict[str, list[RiskVariantReport]]] = {
        v: {c: [] for c in COHORT_NAMES} for v in ALL_VARIANTS
    }

    for cohort in COHORT_NAMES:
        print(f"\n── {cohort} ──")
        for window_label in WINDOW_LABELS:
            evidence = load_per_window_evidence(
                cohort,
                window_label,
                evidence_root=evidence_root / "per_window",
            )

            if evidence.get("skipped", False):
                print(f"  {window_label}: SKIPPED ({evidence.get('skip_reason', 'unknown')})")
                continue

            # ── Calendar validation ────────────────────────────────────────
            evaluation_dates = assert_calendar_matches_evidence(calendar, evidence)

            # ── Load backward-looking features for this window ─────────────
            window = evidence.get("window", {})
            test_start = window.get("test_start")
            test_end = window.get("test_end")
            if test_start is None or test_end is None:
                print(f"  {window_label}: window dates missing, skipping")
                continue

            # Collect all selected symbols across all periods in this window.
            periods = evidence.get("selection_tail_diagnostics", {}).get("periods", [])
            cohort_symbols = sorted(
                set(
                    h["symbol"]
                    for p in periods
                    for h in p.get("selected_holdings", [])
                )
            )
            if not cohort_symbols:
                print(f"  {window_label}: no selected symbols, skipping")
                continue

            ret20d = _load_backward_20d_return(
                cohort_symbols, test_start, test_end
            )
            vol20_df = _load_vol20(cohort_symbols, test_start, test_end)

            window_reports: dict[str, Any] = {}
            for variant_id in ALL_VARIANTS:
                print(
                    f"  {window_label}  variant={variant_id}  "
                    f"symbols={len(cohort_symbols)}",
                    end="",
                )
                report = evaluate_variant_on_window(
                    evidence,
                    variant_id=variant_id,
                    evaluation_dates=evaluation_dates,
                    ret20d=ret20d if variant_id == VARIANT_POS20D else None,
                    vol20_df=vol20_df if variant_id == VARIANT_INV_VOL20 else None,
                )
                if variant_id == VARIANT_FROZEN:
                    _assert_baseline_reconciles(report, evidence)
                results[variant_id][cohort].append(report)

                print(
                    f"  rel_xs={report.relative_excess_return:.4f}  "
                    f"SR={report.sharpe_ratio:.2f}  "
                    f"MDD={report.max_drawdown:.4f}  "
                    f"gross={report.mean_gross_exposure:.2f}"
                )

                compact_report = report.to_dict()
                compact_report.pop("period_details", None)
                window_reports[variant_id] = compact_report

            out_path = per_window_out / f"{cohort}_{window_label}.json"
            out_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "evidence_type": "candidate_v2_risk_hypotheses_window",
                        "cohort": cohort,
                        "window": window,
                        "research_only": True,
                        "promotion_eligible": False,
                        "trade_ready": False,
                        "variants": window_reports,
                    },
                    sort_keys=True,
                    default=str,
                    allow_nan=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

    # ── Cross-variant decision ─────────────────────────────────────────────
    decision = _cross_variant_decision(results)
    per_variant = {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_risk_hypotheses_by_variant",
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "gate": decision["gate"],
        "variants": decision["variants"],
    }

    # ── Write outputs ─────────────────────────────────────────────────────
    per_variant_path = output_root / "per_variant.json"
    per_variant_path.write_text(
        json.dumps(
            per_variant,
            indent=2,
            sort_keys=True,
            default=str,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    cross_variant_path = output_root / "cross_variant.json"
    cross_variant_path.write_text(
        json.dumps(
            decision,
            indent=2,
            sort_keys=True,
            default=str,
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    manifest = _build_evidence_manifest(decision, provider_manifest)
    manifest_path = output_root / "evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )

    print(f"\n  output:      {output_root}")
    print(f"  per-window:  {per_window_out}")
    print(f"  per-variant: {per_variant_path}")
    print(f"  decision:    {cross_variant_path}")
    print(f"  manifest:    {manifest_path}")

    return {
        "per_variant": per_variant,
        "decision": decision,
        "manifest": manifest,
        "output_root": str(output_root),
        "per_window_out": str(per_window_out),
        "per_variant_path": str(per_variant_path),
        "cross_variant_path": str(cross_variant_path),
        "manifest_path": str(manifest_path),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Decision logic
# ══════════════════════════════════════════════════════════════════════════════


def _cross_variant_decision(
    results: dict[str, dict[str, list[RiskVariantReport]]],
) -> dict[str, Any]:
    """Apply the frozen gate across cohorts and variants.

    The frozen gate requires:

    - exactly 4 windows per cohort (all must be evaluated)
    - at least 3 positive-excess windows per cohort
    - compounded relative excess > 30% per cohort
    - worst drawdown >= -15% per cohort
    - all three cohorts pass

    A variant must pass on *all three* cohorts to be considered robust.
    """
    variant_decisions: dict[str, Any] = {}
    selected = None
    selected_score = -np.inf

    for variant_id in ALL_VARIANTS:
        # Evaluate per-cohort.
        cohort_verdicts: dict[str, Any] = {}
        cohort_all_pass = True
        degradation_notes: list[str] = []

        for cohort in COHORT_NAMES:
            cohort_reports = results[variant_id][cohort]
            if not cohort_reports:
                cohort_verdicts[cohort] = {
                    "status": "skipped",
                    "n_windows": 0,
                    "skip_reason": "no windows evaluated",
                }
                cohort_all_pass = False
                degradation_notes.append(f"{cohort}: no windows")
                continue

            cohort_agg = aggregate_variant_reports(
                {variant_id: cohort_reports},
                min_positive_excess_windows=MIN_POSITIVE_EXCESS_WINDOWS,
                min_relative_excess_return=MIN_COMPOUNDED_RELATIVE_EXCESS,
                max_drawdown_gate=MAX_DRAWDOWN_GATE,
            )

            cv2 = cohort_agg["variants"].get(variant_id, {})
            n_windows = int(cv2.get("n_windows", 0))
            passes = (
                n_windows == REQUIRED_WINDOWS
                and bool(cv2.get("passes_candidate_v2_gate", False))
            )
            cohort_verdicts[cohort] = {
                "status": "evaluated",
                "n_windows": n_windows,
                "positive_relative_excess_windows": cv2.get(
                    "positive_excess_windows", 0
                ),
                "compounded_relative_excess_return": cv2.get(
                    "compounded_relative_excess_return"
                ),
                "worst_drawdown": cv2.get("worst_drawdown"),
                "mean_sharpe": cv2.get("mean_window_sharpe"),
                "passes_gate": passes,
            }

            if not passes:
                cohort_all_pass = False
                reasons = []
                if n_windows != REQUIRED_WINDOWS:
                    reasons.append(f"{n_windows}/{REQUIRED_WINDOWS} windows")
                if cv2.get("positive_excess_windows", 0) < MIN_POSITIVE_EXCESS_WINDOWS:
                    reasons.append("insufficient positive excess windows")
                cre = cv2.get("compounded_relative_excess_return", 0.0)
                if cre is not None and cre <= MIN_COMPOUNDED_RELATIVE_EXCESS:
                    reasons.append("relative excess <= 30%")
                wdd = cv2.get("worst_drawdown", 0.0)
                if wdd is not None and wdd < MAX_DRAWDOWN_GATE:
                    reasons.append("drawdown below -15%")
                if reasons:
                    degradation_notes.append(f"{cohort}: {'; '.join(reasons)}")

        robust = cohort_all_pass
        if robust:
            # Pick the variant with highest compounded relative excess.
            total_rel = sum(
                v.get("compounded_relative_excess_return", 0.0) or 0.0
                for v in cohort_verdicts.values()
                if isinstance(v, dict) and v.get("compounded_relative_excess_return")
            )
            if total_rel > selected_score:
                selected = variant_id
                selected_score = total_rel

        variant_decisions[variant_id] = {
            "research_only": True,
            "trade_ready": False,
            "cohorts": cohort_verdicts,
            "robust_across_cohorts": robust,
            "degradation_note": "; ".join(degradation_notes) if degradation_notes else None,
        }

    decision_status = "candidate_v2_no_robust_overlay"
    if selected is not None:
        decision_status = f"candidate_v2_robust_overlay_{selected}"
    elif any(
        vd.get("robust_across_cohorts", False)
        for vd in variant_decisions.values()
    ):
        decision_status = "candidate_v2_robust_overlay"

    return {
        "schema_version": "1.0",
        "evidence_type": "candidate_v2_risk_hypotheses",
        "candidate": _candidate_id(),
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "gate": {
            "required_windows_per_cohort": REQUIRED_WINDOWS,
            "min_positive_excess_windows": MIN_POSITIVE_EXCESS_WINDOWS,
            "min_compounded_relative_excess": MIN_COMPOUNDED_RELATIVE_EXCESS,
            "max_drawdown": MAX_DRAWDOWN_GATE,
        },
        "survivorship_bias_documented": True,
        "survivorship_bias_note": (
            "Cohorts use static current-member Qlib instrument listings, "
            "introducing survivorship bias. Results are diagnostic."
        ),
        "variants": variant_decisions,
        "decision_status": decision_status,
        "candidate_v2_robust_overlay": selected is not None,
        "selected_variant": selected,
        "non_trade_ready_warning": (
            "No variant in this experiment has been promoted, tested in "
            "a point-in-time universe, or approved for trading."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help=(
            "Repository root containing data/providers/us. "
            "The US-market Qlib provider must have a valid "
            "provider_manifest.json at this location."
        ),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=EVIDENCE_DIR,
        help=(
            "Path to committed evidence directory. "
            f"Default: {EVIDENCE_DIR}"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Output directory for risk-hypothesis JSON artifacts. "
            "Default: artifacts/evidence/candidate_v2_risk_hypotheses"
        ),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(
        data_root=args.data_root,
        evidence_root=args.evidence_root,
        output_root=args.output_root,
    )


if __name__ == "__main__":
    main()
