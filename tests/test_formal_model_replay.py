from __future__ import annotations

import json
from pathlib import Path

from src.cli import main as cli
from src.research import formal_model_replay as replay
from src.research.replay_comparison import compare_package_sections


def _package(value: float) -> dict:
    return {
        "portfolio_contract": {"cost_bps": 10},
        "report": [
            {
                "date": "2026-08-07",
                "period_return": value,
                "turnover": 0.5,
            }
        ],
        "positions": [
            {
                "date": "2026-08-07",
                "instrument": "QQQ",
                "weight": 1.0,
                "price": 100.0,
            }
        ],
        "trades": [
            {
                "date": "2026-08-07",
                "instrument": "QQQ",
                "previous_weight": 0.0,
                "target_weight": 1.0,
            }
        ],
    }


def test_trace_comparison_accepts_machine_precision_noise() -> None:
    expected = _package(0.01)
    observed = _package(0.01 + 5e-13)

    result = compare_package_sections(expected, observed)

    assert result["exact"] is True
    assert result["sections"]["report"]["first_mismatch"] is None


def test_trace_comparison_rejects_economic_drift() -> None:
    expected = _package(0.01)
    observed = _package(0.011)

    result = compare_package_sections(expected, observed)

    assert result["exact"] is False
    mismatch = result["sections"]["report"]["first_mismatch"]
    assert mismatch["field"] == "period_return"


def test_all_replay_requires_every_model_to_match(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        replay,
        "replay_qqq_v4_3",
        lambda **kwargs: {"decision": "exact_replay"},
    )
    monkeypatch.setattr(
        replay,
        "replay_byd_v1_3",
        lambda **kwargs: {"decision": "invalid_evidence"},
    )

    result = replay.replay_formal_models("all", root=tmp_path)

    assert result["status"] == "blocked"
    assert result["decision"] == "replay_failed"
    assert result["promotion_authorized"] is False


def test_cli_replay_returns_nonzero_when_exact_replay_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(
        cli,
        "replay_formal_models",
        lambda *args, **kwargs: {
            "status": "blocked",
            "decision": "replay_failed",
            "results": [],
            "research_only": True,
            "trade_ready": False,
        },
    )

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "research",
            "replay",
            replay.QQQ_REPLAY_ID,
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["decision"] == "replay_failed"


def test_cli_replay_returns_zero_on_exact_replay(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(
        cli,
        "replay_formal_models",
        lambda *args, **kwargs: {
            "status": "completed",
            "decision": "exact_replay",
            "results": [],
            "research_only": True,
            "trade_ready": False,
        },
    )

    exit_code = cli.main(
        [
            "--root",
            str(tmp_path),
            "research",
            "replay",
            replay.BYD_REPLAY_ID,
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["decision"] == "exact_replay"


def test_committed_byd_v1_3_replays_exactly() -> None:
    result = replay.replay_byd_v1_3(root=Path.cwd())

    assert result["decision"] == "exact_replay", json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
