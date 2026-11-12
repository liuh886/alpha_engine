"""Synthetic chronological tests; no test record is real forward evidence."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from src.research import e7_source
from src.research.e5_score_reconstruction import sha
from src.research.e7_paper_daily import initialize, run, MissedPrediction, load
from src.research.study_workspace import save_receipt_exclusive

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "configs/research_experiments/e7_rules_paper_20261110_v1.json"
)
REGISTERED = datetime(2026, 11, 7, 14, tzinfo=timezone.utc)


def collector(root, cfg, day):
    dates = e7_source.sessions(day, 121)
    rows = []
    factor = 0.5 if day >= "2026-11-11" else 1.0
    for i, s in enumerate([*cfg["symbols"], "QQQ"]):
        for d in dates:
            value = (100.0 + i + pd.Timestamp(d).toordinal() * 0.001) * factor
            rows.append(
                {
                    "date": d,
                    "symbol": s,
                    "close": value,
                    "raw_close": value,
                    "volume": 100000.0,
                    "dividend": 0.0,
                    "split": 0.0,
                }
            )
    frame = pd.DataFrame(rows)
    e7_source.validate_panel(frame, cfg, day)
    path = root / f"{day}-synthetic.parquet"
    frame.to_parquet(path, index=False)
    meta = {
        "session": day,
        "available_at_utc": day + "T21:05:00+00:00",
        "frame_path": path.name,
        "frame_sha256": sha(path),
        "rows": len(frame),
        "source_symbols": 74,
        "synthetic_test_only": True,
    }
    save_receipt_exclusive(root / "market" / f"{day}.json", meta)
    return meta


def new_root(tmp_path):
    root = tmp_path / "episode"
    initialize(root, CONTRACT, REGISTERED)
    return root


def test_warmup_is_real_time_capture_but_never_a_backfilled_prediction(tmp_path):
    root = new_root(tmp_path)
    result = run(root, clock=lambda: REGISTERED, collector=collector)
    assert result["session"] == "2026-11-06"
    assert result["status"] == "WARMUP_ONLY_NO_FORWARD_PREDICTION"
    assert not (root / "predictions").exists() and not (root / "fills").exists()


def test_full_sequence_and_same_cutoff_idempotency_with_revision_bridge(tmp_path):
    root = new_root(tmp_path)
    for day in (10, 11, 12):
        result = run(
            root,
            clock=lambda d=day: datetime(2026, 11, d, 22, tzinfo=timezone.utc),
            collector=collector,
        )
    fill = json.loads((root / "fills/2026-11-11.json").read_bytes())
    prediction = root / "predictions/2026-11-10.json"
    for row in fill["strategies"].values():
        assert row["prediction_sha256"] == sha(prediction)
        assert row["pending_fee_return"] == 0.0008
        assert row["actual_fill_observed"] is False
    paper = result["paper"]
    assert paper["observed_return_intervals"] == 1 and paper["terminal_liquidation"] is False
    for row in paper["summaries"].values():
        # A 50% provider revision across vintages must not become a fake 50% loss.
        assert abs(row["net_return"]) < 0.01
    bridge = pd.read_parquet(root / "paper/2026-11-12/source-adjustment-bridge.parquet")
    assert bridge["previous_mark_revision_ratio"].min() == pytest.approx(0.5)
    hashes = {str(p.relative_to(root)): sha(p) for p in (root / "predictions").glob("*.json")}
    again = run(
        root,
        clock=lambda: datetime(2026, 11, 12, 23, tzinfo=timezone.utc),
        collector=lambda *a: pytest.fail("same cutoff fetched again"),
    )
    assert again == result
    assert hashes == {
        str(p.relative_to(root)): sha(p) for p in (root / "predictions").glob("*.json")
    }


def test_missed_first_deadline_halts_episode_and_never_backfills(tmp_path):
    root = new_root(tmp_path)
    with pytest.raises(MissedPrediction):
        run(
            root,
            clock=lambda: datetime(2026, 11, 11, 15, tzinfo=timezone.utc),
            collector=lambda *a: pytest.fail("late start fetched"),
        )
    assert (root / "HALTED.json").exists() and not (root / "predictions").exists()
    assert len(list((root / "failures").glob("*.json"))) == 1
    with pytest.raises(MissedPrediction):
        run(
            root, clock=lambda: datetime(2026, 11, 12, 22, tzinfo=timezone.utc), collector=collector
        )
    assert len(list((root / "failures").glob("*.json"))) == 2


def test_source_failures_are_retained_and_can_retry_before_deadline(tmp_path):
    root = new_root(tmp_path)

    def bad(*args):
        raise RuntimeError("source unavailable")

    with pytest.raises(RuntimeError, match="source unavailable"):
        run(root, clock=lambda: datetime(2026, 11, 10, 22, tzinfo=timezone.utc), collector=bad)
    assert not (root / "HALTED.json").exists()
    assert not (root / "predictions").exists()
    run(root, clock=lambda: datetime(2026, 11, 10, 23, tzinfo=timezone.utc), collector=collector)
    assert (root / "predictions/2026-11-10.json").exists()


def test_frozen_episode_rejects_late_initialization_and_contract_changes(tmp_path):
    with pytest.raises(MissedPrediction):
        initialize(tmp_path / "late", CONTRACT, datetime(2026, 11, 10, 15, tzinfo=timezone.utc))
    root = new_root(tmp_path)
    cfg = json.loads((root / "contract.json").read_bytes())
    cfg["strategies"]["rule_momentum60"] = 20
    (root / "contract.json").write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="identity changed"):
        load(root)


def test_transient_fetch_error_is_retried_without_inflating_evidence():
    from src.data.adapters.base import DataFetchError

    calls = []
    sleeps = []

    def fetch():
        calls.append(1)
        if len(calls) < 3:
            raise DataFetchError("empty data for AXON")
        return "observed"

    result = e7_source._fetch_with_retry(
        fetch,
        attempts=3,
        backoff=(2.0, 8.0),
        sleep=sleeps.append,
    )

    assert result == "observed"
    assert len(calls) == 3
    assert sleeps == [2.0, 8.0]


def test_history_start_unreachable_is_not_retried():
    from src.data.adapters.base import HistoryStartUnreachable

    calls = []

    def fetch():
        calls.append(1)
        raise HistoryStartUnreachable(
            "history start unreachable",
            provider_symbol="AXON",
            requested_start="2026-05-15",
            available_start="2026-06-01",
        )

    with pytest.raises(HistoryStartUnreachable):
        e7_source._fetch_with_retry(
            fetch,
            attempts=3,
            backoff=(2.0, 8.0),
            sleep=lambda _: None,
        )

    assert len(calls) == 1


def test_exhausted_retries_raise_the_provider_error():
    from src.data.adapters.base import DataFetchError

    calls = []

    def fetch():
        calls.append(1)
        raise DataFetchError("empty data for AAOI")

    with pytest.raises(DataFetchError, match="empty data for AAOI"):
        e7_source._fetch_with_retry(
            fetch,
            attempts=3,
            backoff=(2.0, 8.0),
            sleep=lambda _: None,
        )

    assert len(calls) == 3


def test_retry_contract_requires_a_backoff_for_every_retry():
    with pytest.raises(ValueError, match="invalid E7 fetch retry contract"):
        e7_source._retry_settings(
            {"source": {"fetch_retry": {"attempts": 3, "backoff_seconds": [1.0]}}}
        )
    assert e7_source._retry_settings({"source": {}}) == (3, (2.0, 8.0))
