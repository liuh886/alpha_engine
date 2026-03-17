import sys
import os

# 确保能 import src 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.reliability.classifier import classify_failure
from src.reliability.error_codes import ERR_MODEL_MISSING, ERR_DATA_GAP

def test_classify_missing_model_file_returns_model_missing_code():
    event = classify_failure(
        component="orchestrator.rebacktest",
        exc=FileNotFoundError("missing us_model.pkl"),
        context={"model_path": "artifacts/models/us_model.pkl"},
    )
    assert event.code == "ERR_MODEL_MISSING"
    assert event.category == "model"
    assert event.severity == "high"

def test_classify_empty_universe_returns_data_gap():
    event = classify_failure(
        component="orchestrator.rebacktest",
        stderr="RuntimeError: No valid tickers found (empty universe)",
        context={"market": "cn"}
    )
    assert event.code == "ERR_DATA_GAP"
    assert event.market == "cn"
    assert event.governance_action["action"] == "refresh_data_then_retry"

if __name__ == "__main__":
    test_classify_missing_model_file_returns_model_missing_code()
    test_classify_empty_universe_returns_data_gap()
    print("Test Task 1: Reliability Domain Models PASS")
