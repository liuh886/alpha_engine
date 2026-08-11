from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from src.artifacts.formal_refresh import load_object
from src.research import rules_formal_replay_gate as replay_gate
from src.research.cn_x1_1_regime_gated import RegimeGateSpec, run_regime_portfolio
from src.research.rules_formal_replay_gate import (
    RulesFormalReplayError,
    assert_exact_formal_prefix,
    prepare_and_verify_active_rules_replay,
    verify_cn_frozen_prefix,
)


def _formal_package() -> dict:
    return {
        "portfolio_contract": {"cost_bps": 20},
        "report": [{"date": "2026-07-01", "period_return": 0.01}],
        "positions": [
            {
                "date": "2026-07-01",
                "instrument": "000300",
                "weight": 1.0,
            }
        ],
        "trades": [],
    }


def test_exact_prefix_allows_only_append_only_extension() -> None:
    expected = _formal_package()
    observed = copy.deepcopy(expected)
    observed["report"].append({"date": "2026-07-15", "period_return": 0.02})
    observed["positions"].append(
        {"date": "2026-07-15", "instrument": "000300", "weight": 1.0}
    )

    comparison = assert_exact_formal_prefix(expected, observed, label="fixture")

    assert comparison["exact"] is True


def test_exact_prefix_rejects_historical_mutation() -> None:
    expected = _formal_package()
    observed = copy.deepcopy(expected)
    observed["report"][0]["period_return"] = 0.02

    with pytest.raises(RulesFormalReplayError, match="exact replay mismatch"):
        assert_exact_formal_prefix(expected, observed, label="fixture")


def test_cn_regime_portfolio_respects_continuation_weights() -> None:
    date = pd.Timestamp("2026-07-01")
    ledger = pd.DataFrame(
        [
            {
                "window": "2026H2_PARTIAL",
                "datetime": date,
                "instrument": "000001",
            }
        ]
    )
    benchmark_returns = pd.Series([0.01], index=pd.DatetimeIndex([date]))
    state = pd.DataFrame(
        [
            {
                "long_trend": False,
                "medium_momentum": False,
                "breadth_value": 0.0,
                "cross_sectional_breadth": False,
                "votes": 0,
            }
        ],
        index=pd.DatetimeIndex([date]),
    )
    spec = RegimeGateSpec()

    _, periods, holdings, _ = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=("2026H2_PARTIAL",),
        variant=spec.variant(),
        cost_bps=20,
        initial_weights={"000300": 1.0},
    )

    assert periods.iloc[0]["turnover"] == 0.0
    assert periods.iloc[0]["cost"] == 0.0
    assert periods.iloc[0]["net_return"] == pytest.approx(0.01)
    assert holdings.iloc[0]["instrument"] == "000300"


def test_committed_cn_frozen_trace_is_exact_prefix_of_current_formal() -> None:
    package = load_object(Path("data/research/formal_backtests/cn_x1_1.json"))

    receipt = verify_cn_frozen_prefix(Path.cwd(), package)

    assert receipt["decision"] == "exact_replay"
    assert receipt["trace_reproduction"]["exact"] is True


def test_active_rules_replay_builds_governed_inputs_before_verification(
    monkeypatch,
    tmp_path: Path,
) -> None:
    formal = tmp_path / "formal"
    formal.mkdir()
    (formal / "qqqi_qqq_tqqq_v4_3.json").write_text(
        json.dumps(
            {
                "model_id": "qqqi_qqq_tqqq_v4_3",
                "evidence_cutoff": "2026-08-10",
            }
        ),
        encoding="utf-8",
    )
    (formal / "cn_x1_1.json").write_text(
        json.dumps({"model_id": "cn_x1_1"}),
        encoding="utf-8",
    )
    qqq_bundle = tmp_path / "qqq-bundle"
    cn_output = tmp_path / "cn-replay"
    cn_provider = tmp_path / "provider-cn"
    cn_provider.mkdir()
    calls: dict[str, object] = {}

    def fake_build_etf_reference_bundle(**kwargs):
        calls["qqq_end"] = kwargs["end"]
        Path(kwargs["output_root"]).mkdir(parents=True, exist_ok=True)
        return {
            "strategy_data_ready": True,
            "professional_source_ready": True,
        }

    def fake_run_cn(root, provider_dir, output_dir, window, batch):
        calls["cn_window"] = window
        calls["cn_batch"] = batch
        ledger = Path(output_dir) / "score_ledgers" / replay_gate.CN_REPLAY_LEDGER_NAME
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b"ledger")

    monkeypatch.setattr(
        replay_gate,
        "build_etf_reference_bundle",
        fake_build_etf_reference_bundle,
    )
    monkeypatch.setattr(replay_gate, "run_cn_ranking_batch", fake_run_cn)
    monkeypatch.setattr(
        replay_gate,
        "verify_qqq_professional_replay",
        lambda *args, **kwargs: {"decision": "exact_replay", "model_id": "qqq"},
    )
    monkeypatch.setattr(
        replay_gate,
        "verify_cn_current_allocation_replay",
        lambda *args, **kwargs: {"decision": "exact_replay", "model_id": "cn"},
    )

    receipt = prepare_and_verify_active_rules_replay(
        tmp_path,
        formal_root=formal,
        cn_provider_dir=cn_provider,
        qqq_bundle_dir=qqq_bundle,
        cn_replay_output_dir=cn_output,
    )

    assert receipt["decision"] == "exact_replay"
    assert calls == {
        "qqq_end": "2026-08-10",
        "cn_window": "2026H2_PARTIAL",
        "cn_batch": "r0r1",
    }
