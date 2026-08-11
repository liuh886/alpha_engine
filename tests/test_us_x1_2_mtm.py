from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.artifacts.model_run_exporter import RunExportPlan, SectionPlan
from src.artifacts.us_x1_2_mtm import USX12MtmError, bind_us_x1_2_evidence_cutoff_mtm


def _plan(*, prospective: bool = True) -> RunExportPlan:
    targets = {f"S{i:02d}": 1 / 15 for i in range(15)}
    report = [
        {
            "date": "2026-07-16",
            "holding_end_date": "2026-07-30",
            "period_index": 61,
            "account": 2.0,
            "bench_qqq": 1.5,
            "drawdown": -0.1,
        }
    ]
    return RunExportPlan(
        model_family_id="us_ranker",
        model_version_id="us_x1_2",
        run_id="us_x1_2-through-2026_08_10",
        model_kind="cross_sectional_ranker",
        publication_channel="preview",
        publication_status="ci_validated_preview",
        generated_at="2026-08-11T00:00:00Z",
        evidence_cutoff="2026-08-10",
        comparability_key={
            "market": "us",
            "universe_id": "us_selected_equities_v2",
            "benchmark_id": "qqq",
            "start": "2024-01-02",
            "end": "2026-07-30",
            "trace_frequency": "non_overlapping_10_session",
            "horizon": "10_sessions",
            "rebalance_contract_id": "top15_sector4_10_sessions",
            "cost_contract_id": "cost_20_bps",
        },
        sections=(
            SectionPlan(
                "summary",
                "available",
                True,
                {
                    "metrics": [{"metric_id": "total_return", "value": 1.0}],
                    "research_only": True,
                    "trade_ready": False,
                },
            ),
            SectionPlan(
                "performance",
                "available",
                True,
                {
                    "report": report,
                    "date_range": {"start": "2024-01-02", "end": "2026-07-30"},
                    "performance_semantics": {
                        "signal_time": "adjusted_close_of_signal_date",
                    },
                    "research_only": True,
                    "trade_ready": False,
                },
            ),
            SectionPlan(
                "portfolio",
                "available",
                True,
                {
                    "latest_signal": {
                        "signal_date": "2026-07-30",
                        "signal_state": "prospective_unrealized" if prospective else "settled",
                        "target_weights": targets,
                        "turnover": 0.4,
                        "cost_bps": 20,
                    },
                    "research_only": True,
                    "trade_ready": False,
                },
            ),
            SectionPlan(
                "lineage",
                "available",
                True,
                {"research_only": True, "trade_ready": False},
            ),
        ),
    )


def _panel() -> pd.DataFrame:
    instruments = [*(f"S{i:02d}" for i in range(15)), "QQQ"]
    rows = []
    for date, stock_close, qqq_close in (
        ("2026-07-30", 100.0, 100.0),
        ("2026-08-10", 110.0, 105.0),
    ):
        for instrument in instruments:
            rows.append(
                {
                    "datetime": pd.Timestamp(date),
                    "instrument": instrument,
                    "close": qqq_close if instrument == "QQQ" else stock_close,
                }
            )
    return pd.DataFrame(rows).set_index(["datetime", "instrument"])


def _payload(plan: RunExportPlan, section_id: str) -> dict:
    section = next(row for row in plan.sections if row.section_id == section_id)
    assert isinstance(section.payload, dict)
    return section.payload


def test_us_x1_2_cutoff_mtm_extends_equity_observation_without_rewriting_settled_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class DummyRuntime:
        def __init__(self, provider_uri: Path) -> None:
            self.provider_uri = provider_uri

        def initialize(self, root: Path) -> None:
            self.root = root

    monkeypatch.setattr("src.artifacts.us_x1_2_mtm.QlibUSExecutionRuntime", DummyRuntime)
    monkeypatch.setattr("src.artifacts.us_x1_2_mtm._close_panel", lambda *args, **kwargs: _panel())

    builder = tmp_path / "builder.py"
    builder.write_text("builder\n", encoding="utf-8")
    result = bind_us_x1_2_evidence_cutoff_mtm(
        _plan(),
        root=tmp_path,
        provider_dir=tmp_path / "provider",
        publication_builder=builder,
    )

    performance = _payload(result, "performance")
    summary = _payload(result, "summary")
    lineage = _payload(result, "lineage")
    report = performance["report"]

    assert len(report) == 2
    assert report[0]["holding_end_date"] == "2026-07-30"
    assert report[-1]["holding_end_date"] == "2026-08-10"
    assert report[-1]["provisional_mtm"] is True
    assert report[-1]["settlement_status"] == "provisional_mtm"
    assert report[-1]["period_return"] == pytest.approx(0.0992)
    assert report[-1]["account"] == pytest.approx(2.1984)
    assert report[-1]["bench_qqq"] == pytest.approx(1.575)
    assert performance["date_range"]["end"] == "2026-08-10"
    assert performance["performance_semantics"]["performance_date_field"] == "holding_end_date"
    assert result.comparability_key["end"] == "2026-08-10"
    assert summary["settled_performance_end"] == "2026-07-30"
    assert summary["performance_observation_end"] == "2026-08-10"
    assert summary["performance_observation_status"] == "provisional_mtm"
    assert summary["metrics"] == [{"metric_id": "total_return", "value": 1.0}]
    assert len(lineage["publication_builder_source_sha256"]) == 64
    assert len(lineage["cutoff_mtm_source_sha256"]) == 64


def test_us_x1_2_cutoff_mtm_fails_closed_without_current_target(tmp_path: Path) -> None:
    builder = tmp_path / "builder.py"
    builder.write_text("builder\n", encoding="utf-8")
    with pytest.raises(USX12MtmError, match="no prospective target"):
        bind_us_x1_2_evidence_cutoff_mtm(
            _plan(prospective=False),
            root=tmp_path,
            provider_dir=tmp_path / "provider",
            publication_builder=builder,
        )
