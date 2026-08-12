from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.artifacts.formal_refresh import load_object
from src.research import qqq_authoritative_replay as qqq_replay
from src.research import rules_formal_replay_gate as replay_gate
from src.research.cn130_tail_factor_discovery import choose_holdings
from src.research.cn_x1_1_regime_gated import RegimeGateSpec, run_regime_portfolio
from src.research.qqq_authoritative_replay import (
    compare_qqq_authoritative_trace,
    prepare_and_verify_active_rules_replay,
)
from src.research.rules_formal_replay_gate import (
    RulesFormalReplayError,
    _compare_rows_at_accepted_precision,
    _load_cn_frozen_score_cross_sections,
    assert_exact_formal_prefix,
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


def _qqq_package() -> dict:
    report = {
        "date": "2026-08-06",
        "account": 1.2,
        "bench_qqq": 1.1,
        "bench_tqqq": 1.4,
        "bench": 0.01,
        "turnover": 0.0,
        "period_return": 0.02,
        "gross_return": 0.02,
        "transaction_cost": 0.0,
        "position_state": 1,
        "position_label": "balanced",
        "decision_state": 1,
        "decision_reason": "hold",
        "executed_reason": "hold",
        "drawdown": -0.01,
        "trace_frequency": "daily_open_to_open",
        "panic_repair_active": False,
        "slow_bear_defense_active": False,
        "weight_QQQI": 0.5,
        "weight_QQQ": 0.5,
        "weight_TQQQ": 0.0,
        "weight_SGOV": 0.0,
    }
    position = {
        "date": "2026-08-06",
        "instrument": "QQQ",
        "weight": 0.5,
        "price": 600.0,
        "position_state": 1,
        "position_label": "balanced",
        "executed_reason": "hold",
        "panic_repair_active": False,
        "slow_bear_defense_active": False,
    }
    return {
        "portfolio_contract": {"benchmark": "QQQ", "cost_bps": 10},
        "report": [report],
        "positions": [position],
        "trades": [
            {
                "date": "2026-08-06",
                "instrument": "QQQ",
                "action": "BUY",
                "previous_weight": 0.0,
                "target_weight": 0.5,
                "weight_delta": 0.5,
                "transaction_cost": 0.0,
                "reason": "hold",
                "position_state": 1,
                "position_label": "balanced",
                "vix_close": 15.0,
                "vix_regime": "normal",
                "vxn_close": 18.0,
                "vxn_regime": "normal",
            }
        ],
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


def test_cn_accepted_precision_accepts_same_published_decimal() -> None:
    comparison = _compare_rows_at_accepted_precision(
        [
            {
                "period_return": 0.01942118706,
                "benchmark_return": -0.02366060168,
                "breadth_value": 0.2846153846,
            }
        ],
        [
            {
                "period_return": 0.019421187062499998,
                "benchmark_return": -0.02366060168368111,
                "breadth_value": 0.2846153846153846,
            }
        ],
    )

    assert comparison["exact"] is True
    assert comparison["comparison_semantics"] == (
        "accepted_frozen_csv_serializer_or_full_precision"
    )


def test_cn_frozen_csv_serializer_reproduces_halfway_net_contribution() -> None:
    comparison = _compare_rows_at_accepted_precision(
        [{"net_contribution": -0.02729934647}],
        [{"net_contribution": -0.027299346475}],
    )

    assert format(-0.027299346475, ".10g") == "-0.02729934647"
    assert comparison["exact"] is True


def test_cn_accepted_precision_rejects_changed_published_decimal() -> None:
    comparison = _compare_rows_at_accepted_precision(
        [{"period_return": 0.01942118706}],
        [{"period_return": 0.01942118707}],
    )

    assert comparison["exact"] is False
    assert comparison["first_mismatch"]["field"] == "period_return"


def test_cn_full_precision_appended_value_remains_strict() -> None:
    comparison = _compare_rows_at_accepted_precision(
        [{"period_return": 0.019421187062499998}],
        [{"period_return": 0.01942118706}],
    )

    assert comparison["exact"] is False


def test_committed_cn_frozen_score_cross_sections_reproduce_sector_selection() -> None:
    universe = yaml.safe_load(
        Path("configs/research_universes/cn_selected_equities_v3.yaml").read_text(
            encoding="utf-8"
        )
    )
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    ledger, identity = _load_cn_frozen_score_cross_sections(
        Path.cwd(),
        symbols=symbols,
    )
    variant = RegimeGateSpec().variant()
    expected = {
        "2026-07-01": {"301666", "601600", "301291", "603392"},
        "2026-07-15": {"300408", "600184", "603260", "603259"},
    }

    assert len(ledger) == 260
    assert identity["source"]["source_sha256"] == (
        "8dbd8bc437f1092f5d3ae296892cd56c463d2c96b680fdf0601f6ef508eecdd5"
    )
    for date, instruments in expected.items():
        day = ledger.loc[ledger["datetime"].eq(pd.Timestamp(date))]
        chosen = choose_holdings(day, variant)
        assert set(chosen["instrument"].astype(str)) == instruments


def test_qqq_current_source_replay_ignores_restated_historical_observations() -> None:
    expected = _qqq_package()
    observed = copy.deepcopy(expected)
    observed["report"][0]["account"] = 1.1999998
    observed["report"][0]["period_return"] = 0.0199998
    observed["report"][0]["gross_return"] = 0.0199998
    observed["report"][0]["drawdown"] = -0.0100002
    observed["report"][0]["bench_tqqq"] = 9.9
    observed["positions"][0]["price"] = 600.00002
    observed["trades"][0]["vix_close"] = 15.0002
    observed["trades"][0]["vxn_close"] = 18.0002

    comparison = compare_qqq_authoritative_trace(expected, observed)

    assert comparison["exact"] is True
    assert comparison["authority"]["historical_economic_authority"] == (
        "accepted_formal_prefix"
    )
    assert comparison["authority"]["source_identity_bound_separately"] is True


def test_qqq_current_source_replay_rejects_decision_drift() -> None:
    expected = _qqq_package()
    observed = copy.deepcopy(expected)
    observed["report"][0]["weight_QQQ"] = 0.25

    comparison = compare_qqq_authoritative_trace(expected, observed)

    assert comparison["exact"] is False
    assert comparison["sections"]["report"]["first_mismatch"]["field"] == "weight_QQQ"


def test_qqq_appended_economics_still_require_exact_current_source() -> None:
    accepted = _qqq_package()
    candidate = copy.deepcopy(accepted)
    observed = copy.deepcopy(accepted)
    appended = copy.deepcopy(accepted["report"][0])
    appended["date"] = "2026-08-07"
    appended["period_return"] = 0.01
    appended["gross_return"] = 0.01
    appended["bench"] = 0.005
    candidate["report"].append(copy.deepcopy(appended))
    source = copy.deepcopy(appended)
    source["period_return"] = 0.011
    observed["report"].append(source)

    comparison = qqq_replay._appended_economic_replay(accepted, candidate, observed)

    assert comparison["exact"] is False
    assert comparison["first_mismatch"]["field"] == "period_return"


def test_qqq_appended_cumulative_path_must_continue_from_frozen_account() -> None:
    accepted = _qqq_package()
    candidate = copy.deepcopy(accepted)
    appended = copy.deepcopy(accepted["report"][0])
    appended.update(
        {
            "date": "2026-08-07",
            "period_return": 0.01,
            "bench": 0.02,
            "account": 1.2 * 1.01,
            "bench_qqq": 1.1 * 1.02,
            "drawdown": 0.0,
        }
    )
    candidate["report"].append(appended)

    comparison = qqq_replay._verify_cumulative_continuity(accepted, candidate)

    assert comparison["exact"] is True

    candidate["report"][-1]["account"] += 1e-6
    mismatch = qqq_replay._verify_cumulative_continuity(accepted, candidate)
    assert mismatch["exact"] is False
    assert mismatch["field"] == "account"


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
        qqq_replay,
        "build_etf_reference_bundle",
        fake_build_etf_reference_bundle,
    )
    monkeypatch.setattr(qqq_replay, "run_cn_ranking_batch", fake_run_cn)
    monkeypatch.setattr(
        qqq_replay,
        "verify_qqq_authoritative_replay",
        lambda *args, **kwargs: {"decision": "exact_replay", "model_id": "qqq"},
    )
    monkeypatch.setattr(
        qqq_replay,
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
