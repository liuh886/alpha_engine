from __future__ import annotations

import json

from src.research.cn27_v1_2_evidence import run_cn27_v1_2_evidence


if __name__ == "__main__":
    result = run_cn27_v1_2_evidence("configs/research_paradigms/cn_27_v1_2.yaml")
    print(json.dumps(result, ensure_ascii=False, indent=2))
