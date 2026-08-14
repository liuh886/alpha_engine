from __future__ import annotations

from pathlib import Path

import pytest

import scripts.build_us_x1_3_preview as preview
from src.artifacts.model_run_exporter import RunExportPlan, SectionPlan


def _plan(*, current_weight: float = 1.0) -> RunExportPlan:
    realized = {
        "signal_date": "2026-07-16",
        "holding_end_date": "2026-07-30",
        "window": "2026H2_PARTIAL",
        "window_role": "prospective_partial",
        "target_weights": {"A": 1.0},
    }
    current = {
        "signal_date": "2026-07-30",
        "holding_end_date": None,
        "window": "current_target",
        "window_role": "prospective_unrealized",
        "target_weights": {"C": current_weight},
        "turnover": 0.5,
    }
    return RunExportPlan(
        model_family_id="us_ranker",
        model_version_id="us_x1_3",
        run_id="us_x1_3-through-2026_08_12",
        model_kind="cross_sectional_ranker",
        publication_channel="preview",
        publication_status="ci_validated_preview",
        generated_at="2026-08-12T23:30:00Z",
        evidence_cutoff="2026-08-12",
        comparability_key={"market": "us"},
        sections=(
            SectionPlan(
                section_id="summary",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "latest_realized_signal": realized,
                    "latest_signal": current,
                    "trade_analytics": {
                        "rebalance_event_count": 2,
                        "normalized_notional": 1.5,
                    },
                },
            ),
            SectionPlan(
                section_id="performance",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "report": [
                        {
                            "date": "2026-07-16",
                            "holding_end_date": "2026-07-30",
                            "turnover": 0.1,
                            "account": 1.0,
                        },
                        {
                            "date": "2026-08-12",
                            "signal_date": "2026-07-30",
                            "holding_end_date": "2026-08-12",
                            "turnover": 0.5,
                            "provisional_mtm": True,
                            "settlement_status": "provisional_mtm",
                            "account": 1.1,
                        },
                    ],
                    "date_range": {"start": "2026-07-16", "end": "2026-08-12"},
                },
            ),
            SectionPlan(
                section_id="portfolio",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "positions": [
                        {
                            "date": "2026-07-16",
                            "instrument": "A",
                            "weight": 1.0,
                            "window_role": "prospective_partial",
                        },
                        {
                            "date": "2026-07-30",
                            "instrument": "C",
                            "weight": current_weight,
                            "window_role": "prospective_unrealized",
                        },
                    ],
                    "signals": [realized, current],
                    "latest_realized_signal": realized,
                    "latest_signal": current,
                },
            ),
            SectionPlan(
                section_id="trades",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "records": [
                        {
                            "date": "2026-07-16",
                            "instrument": "A",
                            "weight_delta": 1.0,
                            "window_role": "prospective_partial",
                        },
                        {
                            "date": "2026-07-30",
                            "instrument": "C",
                            "weight_delta": 0.5,
                            "window_role": "prospective_unrealized",
                        },
                    ],
                    "analytics": {
                        "rebalance_event_count": 2,
                        "normalized_notional": 1.5,
                    },
                },
            ),
        ),
    )


def _payload(plan: RunExportPlan, section_id: str):
    return next(section.payload for section in plan.sections if section.section_id == section_id)


def test_preview_strips_unsealed_forward_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preview, "read_latest_evaluation", lambda *_args, **_kwargs: None)

    projected = preview.project_forward_state(_plan(), Path("/repo"))

    performance = _payload(projected, "performance")
    portfolio = _payload(projected, "portfolio")
    trades = _payload(projected, "trades")
    summary = _payload(projected, "summary")
    assert len(performance["report"]) == 1
    assert performance["date_range"]["end"] == "2026-07-30"
    assert [row["date"] for row in portfolio["positions"]] == ["2026-07-16"]
    assert portfolio["latest_signal"]["signal_date"] == "2026-07-16"
    assert len(trades["records"]) == 1
    assert trades["analytics"]["rebalance_event_count"] == 1
    assert trades["analytics"]["normalized_notional"] == 1.0
    assert summary["latest_signal"]["signal_date"] == "2026-07-16"


def test_preview_projects_exact_sealed_forward_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preview,
        "read_latest_evaluation",
        lambda *_args, **_kwargs: {
            "signal": {
                "signal_date": "2026-07-30",
                "target_weights": {"C": 1.0},
                "turnover_units": 0.5,
            }
        },
    )
    plan = _plan()

    projected = preview.project_forward_state(plan, Path("/repo"))

    assert projected == plan


def test_preview_rejects_state_that_differs_from_sealed_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preview,
        "read_latest_evaluation",
        lambda *_args, **_kwargs: {
            "signal": {
                "signal_date": "2026-07-30",
                "target_weights": {"D": 1.0},
                "turnover_units": 0.5,
            }
        },
    )

    with pytest.raises(
        preview.USX13ForwardProjectionError,
        match="preview target differs from sealed ledger target",
    ):
        preview.project_forward_state(_plan(), Path("/repo"))
