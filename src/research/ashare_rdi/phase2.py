"""Chronological 7/14/28-session research evaluation, never a live trading signal."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from .contracts import RiskEvent, event_exposure_timeline
from .coverage import FamilyCoverage, audit_coverage, coverage_cells_ready
from .outcomes import PriceBar, forward_outcomes

CN_TZ = ZoneInfo("Asia/Shanghai")
CSI300_INCEPTION = date(2005, 4, 8)


def read_price_csv(path: str | Path, *, min_session: date = CSI300_INCEPTION) -> list[PriceBar]:
    """Read *validated* vendor OHLC only; output does not certify source quality."""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        data = list(csv.DictReader(handle))
    if not data:
        raise ValueError("no price bars")
    prices = [
        PriceBar(
            session=date.fromisoformat(row["date"][:10]),
            open=float(row["open"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in data
        if date.fromisoformat(row["date"][:10]) >= min_session
    ]
    if not prices or [p.session for p in prices] != sorted({p.session for p in prices}):
        raise ValueError("missing, duplicated or out-of-order price dates")
    return prices


def build_pit_panel(
    bars: Sequence[PriceBar],
    events: Sequence[RiskEvent],
    coverage: Sequence[FamilyCoverage],
    *,
    required_families: Sequence[str],
    horizon: int,
    validated_sessions: Sequence[date],
    sector_id: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Build only fully archived observations; no assumed event absence.

    The caller MUST pass official XSHG sessions from the existing market clock
    and provider-validated bar availability. Missing sessions are a hard block.
    """
    if horizon not in (7, 14, 28):
        raise ValueError("only frozen 7/14/28 trading-session horizons are allowed")
    dates = [p.session for p in bars]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ValueError("invalid bar ordering")
    if list(validated_sessions) != dates:
        raise ValueError("bars must exactly match verified XSHG exchange sessions")
    if any(d < CSI300_INCEPTION for d in dates):
        raise ValueError("index pre-inception synthetic history is not eligible")
    if not required_families:
        raise ValueError("event families must be declared, never inferred from event count")
    if any(e.available_at.tzinfo is None for e in events):
        raise ValueError("PIT timestamps must be timezone aware")
    audit = audit_coverage(coverage, dates, required_families)
    if audit["status"] != "ready":
        return [], {
            "history": audit,
            "eligible_label_rows": 0,
            "candidate_status": "blocked_incomplete_event_history",
            "feature_coverage_is_a_separate_gate": True,
        }
    cov = {(r.session, r.family): r for r in coverage}
    panel: list[dict[str, object]] = []
    for i in range(60, len(bars) - horizon):
        decision = dates[i]
        if not coverage_cells_ready(cov, decision, required_families):
            continue
        cutoff = datetime.combine(decision, time(16), tzinfo=CN_TZ)
        exposure = event_exposure_timeline(
            events, as_of=cutoff,
            future_sessions=dates[i + 1 : i + 1 + horizon],
            sector_id=sector_id,
        )
        labels = forward_outcomes(
            bars, decision_session=decision, horizons=(horizon,), instrument_kind="index"
        )[0]
        if labels["status"] != "observed":
            continue
        close_60 = [p.close for p in bars[i - 59 : i + 1]]
        prior_peak = max(close_60)
        avg_risk = sum(int(x["risk_stories"]) for x in exposure) / horizon
        avg_clearing = sum(int(x["clearing_stories"]) for x in exposure) / horizon
        panel.append(
            {
                "session": decision.isoformat(),
                "end_session": labels["exit_session"],
                "horizon_sessions": horizon,
                "risk_density": avg_risk,
                "clearing_density": avg_clearing,
                "bear_drawdown_60": close_60[-1] / prior_peak - 1.0,
                "forward_return": labels["forward_return"],
                "forward_worst_excursion": labels["worst_intrahorizon_return"],
                "down": int(float(labels["forward_return"]) < 0),
                "severe_loss_5pct": int(float(labels["forward_return"]) <= -0.05),
                "path_loss_5pct": int(float(labels["worst_intrahorizon_return"]) <= -0.05),
            }
        )
    coverage_gate = {
        "history": audit,
        "eligible_label_rows": len(panel),
        "candidate_status": "unvalidated",
        "feature_coverage_is_a_separate_gate": True,
    }
    return panel, coverage_gate


def evaluate_blocked_oos(
    panel: Sequence[Mapping[str, object]],
    *,
    horizon: int,
    min_train: int = 100,
    min_test: int = 40,
    train_fraction: float = 0.7,
    target: str = "down",
) -> dict[str, object]:
    """Fixed chronological train/test split; purge any overlapping forward label.

    Compare historical-mean probability, past-price drawdown and drawdown+RDI
    event density. This is a *diagnostic ablation*, not a calibrated RDI index.
    """
    if target not in {"down", "severe_loss_5pct", "path_loss_5pct"}:
        raise ValueError("target must be down, severe_loss_5pct or path_loss_5pct")
    ordered = sorted(
        (x for x in panel if int(x["horizon_sessions"]) == horizon),
        key=lambda row: str(row["session"]),
    )
    if not 0.5 <= train_fraction <= 0.85:
        raise ValueError("train_fraction must be 0.5..0.85")
    if len(ordered) < min_train + min_test + horizon:
        return {"status": "insufficient_samples", "horizon": horizon, "observations": len(ordered)}
    split = int(len(ordered) * train_fraction)
    if split >= len(ordered):
        return {"status": "insufficient_samples", "horizon": horizon}
    test_first = str(ordered[split]["session"])
    # Purge by actual label endpoint, not row-count position: gaps in source
    # coverage and nonconsecutive eligible signals would defeat row-based purge.
    train = [x for x in ordered[:split] if str(x["end_session"]) < test_first]
    test = ordered[split:]
    if len(train) < min_train or len(test) < min_test:
        return {"status": "insufficient_after_purge", "horizon": horizon,
                "train": len(train), "test": len(test)}
    y_train = np.asarray([int(x[target]) for x in train], dtype=int)
    y_test = np.asarray([int(x[target]) for x in test], dtype=int)
    if len(set(y_train)) != 2:
        return {"status": "one_class_train", "horizon": horizon}
    baseline_p = float(y_train.mean())
    baseline = np.full(len(test), baseline_p)
    baseline_brier = float(brier_score_loss(y_test, baseline))

    def score_model(features: tuple[str, ...]) -> dict[str, object]:
        xt = np.asarray([[float(row[f]) for f in features] for row in train])
        xv = np.asarray([[float(row[f]) for f in features] for row in test])
        scaler = StandardScaler().fit(xt)
        model = LogisticRegression(max_iter=500, random_state=0).fit(
            scaler.transform(xt), y_train
        )
        probabilities = model.predict_proba(scaler.transform(xv))[:, 1]
        auc = float(roc_auc_score(y_test, probabilities)) if len(set(y_test)) == 2 else None
        return {
            "features": list(features),
            "brier": float(brier_score_loss(y_test, probabilities)),
            "brier_delta_vs_constant": float(brier_score_loss(y_test, probabilities) - baseline_brier),
            "auc": auc,
            "test_mean_probability": float(probabilities.mean()),
        }

    baseline_model = score_model(("bear_drawdown_60",))
    event_has_variation = len({(float(r["risk_density"]), float(r["clearing_density"]))
                               for r in train}) > 1
    incremental = (
        score_model(("bear_drawdown_60", "risk_density", "clearing_density"))
        if event_has_variation else None
    )
    return {
        "status": "diagnostic_only" if incremental is not None else "event_signal_nonidentifiable",
        "horizon": horizon,
        "target": target,
        "train": len(train),
        "test": len(test),
        "train_last_label_end": str(max(str(x["end_session"]) for x in train)),
        "test_first_session": test_first,
        "baseline_down_rate": baseline_p,
        "test_down_rate": float(y_test.mean()),
        "constant_brier": baseline_brier,
        "price_regime_baseline": baseline_model,
        "incremental_event_model": incremental,
        "promoted": False,
    }
