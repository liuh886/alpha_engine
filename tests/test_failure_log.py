import sys
import os
import json
from pathlib import Path

# 确保能 import src 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.reliability.events import ReliabilityEvent
from src.reliability.failure_log import append_failure_event, resolve_failure_event

def test_append_failure_event_keeps_valid_bounded_json():
    path = Path("tests/failure_log_test.json")
    if path.exists():
        path.unlink()
        
    e1 = ReliabilityEvent("ERR_1", "cat", "high", True, "comp", "op", summary="1")
    e2 = ReliabilityEvent("ERR_2", "cat", "high", True, "comp", "op", summary="2")
    e3 = ReliabilityEvent("ERR_3", "cat", "high", True, "comp", "op", summary="3")
    
    append_failure_event(e1, path=path, max_events=2)
    append_failure_event(e2, path=path, max_events=2)
    append_failure_event(e3, path=path, max_events=2)
    
    with open(path, "r") as f:
        data = json.load(f)
    
    # 应该只有 2 个事件，且 ERR_3 在最前面
    assert len(data["events"]) == 2
    assert data["events"][0]["code"] == "ERR_3"
    assert data["events"][1]["code"] == "ERR_2"
    
    # 验证 resolve
    eid = data["events"][0]["event_id"]
    resolve_failure_event(eid, resolution={"notes": "fixed"}, path=path)
    
    with open(path, "r") as f:
        data2 = json.load(f)
        assert data2["events"][0]["status"] == "resolved"
        assert data2["events"][0]["governance_action"]["notes"] == "fixed"

    path.unlink()
    print("Test Task 2: Failure Shadow Log PASS")

if __name__ == "__main__":
    test_append_failure_event_keeps_valid_bounded_json()
