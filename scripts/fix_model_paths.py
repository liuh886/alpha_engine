import os
from pathlib import Path

import yaml


def fix_paths(data):
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "path" and isinstance(v, str) and ":/" in v:
                # Fix Windows path
                parts = v.replace("\\", "/").split("zhihaol/")
                if len(parts) > 1:
                    # Try to find it under /mnt/zhihaol
                    new_path = "/mnt/zhihaol/" + parts[1]
                    if os.path.exists(new_path):
                        data[k] = new_path
                        print(f"Fixed path: {v} -> {new_path}")
                    else:
                        # Try relative to project root
                        parts2 = v.replace("\\", "/").split("2601_Trading/")
                        if len(parts2) > 1:
                            new_path2 = "/mnt/GitHub/alpha_engine/" + parts2[1]
                            if os.path.exists(new_path2):
                                data[k] = new_path2
                                print(f"Fixed path: {v} -> {new_path2}")
            else:
                fix_paths(v)
    elif isinstance(data, list):
        for item in data:
            fix_paths(item)


yaml_path = Path("/mnt/GitHub/alpha_engine/artifacts/models/model_list.yaml")
if yaml_path.exists():
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    fix_paths(data)

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)
    print("model_list.yaml updated.")
else:
    print("model_list.yaml not found.")
