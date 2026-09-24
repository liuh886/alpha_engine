from __future__ import annotations

import json

from src.research.cn27_v1_4 import run_v1_4_screen


if __name__ == "__main__":
    result = run_v1_4_screen(
        "configs/research_experiments/cn_27_v1_4_risk_overlay_discovery_v1.yaml"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
