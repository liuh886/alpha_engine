import json
from pathlib import Path

db_path = Path("artifacts/dashboard/dashboard_db.json")
if not db_path.exists():
    print("dashboard_db.json does not exist.")
else:
    with open(db_path, encoding="utf-8") as f:
        db = json.load(f)

    models = db.get("models", [])
    print(f"Total models: {len(models)}")
    for m in models:
        rep = m.get("data", {}).get("report_normal", {})
        pos = m.get("data", {}).get("positions_normal", [])
        bench = m.get("data", {}).get("benchmarks", {})

        rep_len = len(rep.get("data", [])) if isinstance(rep, dict) else 0
        pos_len = len(pos) if isinstance(pos, list) else 0
        bench_keys = list(bench.keys())

        print(f"Model ID: {m.get('id')} | Market: {m.get('market')}")
        print(f"  - Report points: {rep_len}")
        print(f"  - Position records: {pos_len}")
        print(f"  - Benchmarks: {bench_keys}")
        if bench_keys:
            first_key = bench_keys[0]
            print(f"  - Benchmark '{first_key}' sample size: {len(bench[first_key])}")
