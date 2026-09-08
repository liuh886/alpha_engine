from __future__ import annotations

import json

from src.research.cn27_v1_2 import run_v1_3_screen


if __name__ == "__main__":
    result = run_v1_3_screen(
        "configs/research_experiments/cn_27_v1_3_stability_discovery_v1.yaml"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
