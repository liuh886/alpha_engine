import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "research_baselines" / "us_top3_blend_v1" / "manifest.json"


def test_us_top3_blend_v1_manifest_is_conservative() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["baseline_id"] == "us_top3_blend_v1"
    assert manifest["baseline_definition"]["market"] == "us"
    assert manifest["baseline_definition"]["benchmark"] == "QQQ"
    assert manifest["baseline_definition"]["horizon"] == "raw_forward_10d_return"
    assert manifest["baseline_definition"]["cost_bps"] == 20

    evidence = manifest["evidence_summary"]
    assert evidence["positive_excess_windows"] == 4
    assert evidence["total_oos_windows"] == 4
    assert evidence["worst_window_drawdown"] == -0.17

    gates = manifest["risk_gates"]
    assert gates["max_drawdown_gate"] == -0.15
    assert gates["max_drawdown_passed"] is False
    assert gates["overall_passed"] is False
    assert evidence["worst_window_drawdown"] < gates["max_drawdown_gate"]

    decision = manifest["decision"]
    assert decision["research_candidate"] is True
    assert decision["trade_ready"] is False
    assert "drawdown" in decision["trade_ready_reason"].lower()
