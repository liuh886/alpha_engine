from src.guardrails import risk_monitor


def test_drawdown_guardrail_blocks_threshold_breach(monkeypatch):
    monkeypatch.setattr(risk_monitor, "MAX_DRAWDOWN_THRESHOLD", 0.15)

    assert risk_monitor.check_backtest_risk(
        "run-high-drawdown", {"max_drawdown": 0.16}
    ) is True


def test_drawdown_guardrail_accepts_within_threshold(monkeypatch):
    monkeypatch.setattr(risk_monitor, "MAX_DRAWDOWN_THRESHOLD", 0.15)

    assert risk_monitor.check_backtest_risk(
        "run-acceptable", {"max_drawdown": 0.15}
    ) is False
