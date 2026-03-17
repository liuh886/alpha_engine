import json
import os
import datetime
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from .events import ReliabilityEvent

DEFAULT_LOG_PATH = Path("artifacts/governance/failure_log.json")

def append_failure_event(event: ReliabilityEvent, *, path: Optional[Path] = None, max_events: int = 500) -> None:
    """
    原子地将失败事件追加到 JSON 日志文件中，并限制记录数量。
    """
    path = path or DEFAULT_LOG_PATH
    os.makedirs(path.parent, exist_ok=True)
    
    # 读取现有数据
    data = {"version": 1, "updated_at": "", "project": "alpha_engine", "events": []}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, Exception):
            # 如果损坏，保留骨架
            pass

    # 插入新事件 (头部插入，保持最新在前面)
    data["events"].insert(0, event.to_dict())
    
    # 截断
    if len(data["events"]) > max_events:
        data["events"] = data["events"][:max_events]
    
    data["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    
    # 原子写入
    temp_path = path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    shutil.move(temp_path, path)

def resolve_failure_event(event_id: str, *, resolution: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """
    标记并更新特定事件的状态为 resolved。
    """
    path = path or DEFAULT_LOG_PATH
    if not path.exists():
        return False
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        found = False
        for event in data["events"]:
            if event.get("event_id") == event_id:
                event["status"] = "resolved"
                event["governance_action"]["status"] = "resolved"
                event["governance_action"].update(resolution)
                found = True
                break
        
        if found:
            temp_path = path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            shutil.move(temp_path, path)
            return True
    except Exception:
        pass
    return False
