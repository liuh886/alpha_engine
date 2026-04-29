import os
import re

files = [
    "src/api/routers/system.py",
    "src/api/routers/backtest.py",
    "src/api/routers/arena.py",
    "src/api/routers/models.py",
    "src/api/routers/data.py",
    "src/api/routers/reports.py",
]

for file_path in files:
    if not os.path.exists(file_path):
        continue
    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    # Replace @router.get("/api/xxx") with @router.get("/xxx")
    new_content = re.sub(r"(@router\.(get|post|delete|put)\(\")/api/", r"\1/", content)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Fixed: {file_path}")
