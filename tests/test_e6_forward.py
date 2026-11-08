"""Synthetic future workflow tests, never represented as actual forward evidence."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from exchange_calendars import get_calendar

from src.research.e6_execution import CONTRACT_SHA
from src.research.e6_forward import (
    PRICE_BASIS,
    bind_model,
    evaluate,
    market,
    outcome,
    prediction,
    register,
    status,
)

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "configs/research_experiments/e6_us73_execution_policy_v1.json"
)
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


class Inputs:
    close = pd.DataFrame(columns=[f"S{i:02}" for i in range(73)])

    def doc(self, path):
        strategy = path.split("/")[1]
        return {
            "configuration": {"id": strategy},
            "train_end": "2026-06-22",
            "X_train_sha256": "a" * 64,
            "y_train_sha256": "b" * 64,
            "native_git_sha": "c" * 40,
            "source_history_sha256": "d" * 64,
        }


def initialized(tmp_path):
    root = tmp_path / "forward"
    inputs = Inputs()
    register(root, CONTRACT, inputs, NOW)
    return root, inputs


def file(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


def forecast(strategy, day, models=None):
    close = get_calendar("XNYS").session_close(day).to_pydatetime()
    return {
        "strategy": strategy,
        "signal_session": day,
        "generated_at_utc": (close + timedelta(minutes=5)).isoformat(),
        "source_available_at_utc": (close + timedelta(minutes=1)).isoformat(),
        "source_snapshot_sha256": "f" * 64,
        "contract_sha256": CONTRACT_SHA,
        "model_sha256": (models or {}).get(strategy),
        "scores": {s: float(i) for i, s in enumerate(Inputs.close.columns)},
    }


def packet(day):
    close = get_calendar("XNYS").session_close(day).to_pydatetime()
    return {
        "session": day,
        "source_available_at_utc": (close + timedelta(seconds=10)).isoformat(),
        "source_snapshot_sha256": "e" * 64,
        "price_basis_id": PRICE_BASIS,
        "adjustment_evidence_sha256": "a" * 64,
        "close_by_symbol": {
            s: 100.0 + i * 0.01 + int(day[-2:])
            for i, s in enumerate([*Inputs.close.columns, "QQQ"])
        },
    }


def test_rejects_late_backdated_predictions_and_prior_history(tmp_path):
    root, _ = initialized(tmp_path)
    doc = forecast("rule_momentum60", "2026-11-09")
    p = file(tmp_path, "forecast.json", doc)
    with pytest.raises(ValueError, match="before next open"):
        prediction(root, p, datetime(2026, 11, 10, 15, tzinfo=timezone.utc))
    doc["signal_session"] = "2026-11-06"
    p = file(tmp_path, "old.json", doc)
    with pytest.raises(ValueError, match="historical"):
        prediction(root, p, datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
    assert status(root, NOW)["missing_model_artifacts"] == ["xgb_p03", "lgb_p05"]
    assert status(root, NOW)["predictions_captured"] == 0


def test_rejects_missing_models_and_cannot_replace_committed_evidence(tmp_path):
    root, _ = initialized(tmp_path)
    doc = forecast("xgb_p03", "2026-11-09")
    with pytest.raises(FileNotFoundError):
        prediction(
            root, file(tmp_path, "tree.json", doc), datetime(2026, 11, 9, 22, tzinfo=timezone.utc)
        )
    doc = forecast("rule_momentum60", "2026-11-09")
    prediction(
        root, file(tmp_path, "first.json", doc), datetime(2026, 11, 9, 22, tzinfo=timezone.utc)
    )
    doc["scores"]["S00"] = 999
    with pytest.raises(ValueError, match="overwrite"):
        prediction(
            root,
            file(tmp_path, "changed.json", doc),
            datetime(2026, 11, 9, 22, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="not mature"):
        outcome(
            root, "rule_momentum60", "2026-11-09", datetime(2026, 11, 13, 22, tzinfo=timezone.utc)
        )


def test_market_requires_post_close_source_time_and_fixed_adjustment_basis(tmp_path):
    root, _ = initialized(tmp_path)
    doc = packet("2026-11-09")
    doc["price_basis_id"] = "raw_unadjusted"
    with pytest.raises(ValueError, match="source evidence"):
        market(
            root, file(tmp_path, "raw.json", doc), datetime(2026, 11, 9, 22, tzinfo=timezone.utc)
        )
    with pytest.raises(ValueError, match="future market"):
        market(root, file(tmp_path, "early.json", packet("2026-11-09")), NOW)


def test_synthetic_forward_labels_and_continuous_paper_ledger_without_forced_exit(tmp_path):
    root, inputs = initialized(tmp_path)
    models = {}
    for strategy in ("xgb_p03", "lgb_p05"):
        model = tmp_path / f"{strategy}.bin"
        model.write_bytes(b"synthetic model artifact fixture")
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        models[strategy] = digest
        receipt = {
            **inputs.doc(f"scores/{strategy}/f2026h2/score-receipt.json"),
            "model_sha256": digest,
        }
        bind_model(root, strategy, model, receipt, NOW)
    days = (
        get_calendar("XNYS")
        .sessions_in_range("2026-11-09", "2026-11-18")
        .strftime("%Y-%m-%d")
        .tolist()
    )
    for day in days:
        now = get_calendar("XNYS").session_close(day).to_pydatetime() + timedelta(hours=1)
        market(root, file(tmp_path, f"market-{day}.json", packet(day)), now)
        for strategy in ("xgb_p03", "lgb_p05", "rule_momentum60", "rule_momentum120"):
            prediction(
                root, file(tmp_path, f"{strategy}-{day}.json", forecast(strategy, day, models)), now
            )
    result = outcome(
        root, "rule_momentum60", days[0], datetime(2026, 11, 18, 22, tzinfo=timezone.utc)
    )
    assert result["label_end"] == "2026-11-16"
    report = evaluate(root, tmp_path / "paper-evaluation")
    assert report["model_fits"] == 0 and report["terminal_liquidation"] is False
    assert set(report["summaries"]) == {"xgb_p03", "lgb_p05", "rule_momentum60", "rule_momentum120"}
    daily = pd.read_parquet(tmp_path / "paper-evaluation/rule_momentum60-daily.parquet")
    assert daily["cash_weight_after_terminal"].iloc[-1] == 0
    assert report["trade_ready"] is False
