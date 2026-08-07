from src.artifacts.strategy_operations import SUPPORTED_SIGNAL_MODELS


def test_v4_3_is_the_only_active_qqq_signal_identity() -> None:
    assert "qqqi_qqq_tqqq_v4_3" in SUPPORTED_SIGNAL_MODELS
    superseded = "qqqi_qqq_tqqq_" + "v4_2"
    assert superseded not in SUPPORTED_SIGNAL_MODELS
