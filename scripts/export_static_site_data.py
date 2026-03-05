import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def table_exists(conn, table_name):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cur.fetchone() is not None

def export_data(market: str, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = PROJECT_ROOT / "artifacts" / "metadata" / "metadata.db"
    if not db_path.exists():
        print(f"Error: Metadata DB not found at {db_path}")
        return False

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    # 1. Export Models
    print("Exporting models...")
    models = []
    if table_exists(conn, "model_versions"):
        m_filter = f"WHERE lower(market) = '{market}'" if market != "all" else ""
        models = [dict(r) for r in conn.execute(f"SELECT * FROM model_versions {m_filter} ORDER BY created_ts DESC").fetchall()]
        for m in models:
            # Decode JSON columns
            for k in ["params_json", "metrics_json", "feature_importance_json"]:
                if m.get(k):
                    try:
                        m[k.replace("_json", "")] = json.loads(m[k])
                    except:
                        m[k.replace("_json", "")] = {}
    
    with open(output_dir / "models.json", "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)

    # 2. Export Arena
    print("Exporting arena...")
    arena_data = {"arena_name": "N/A", "leaderboard": []}
    if table_exists(conn, "arenas") and table_exists(conn, "arena_daily_pnl"):
        arena_name = "Global Arena" if market == "all" else f"{market.upper()} Arena"
        arena = conn.execute("SELECT * FROM arenas WHERE name = ?", (arena_name,)).fetchone()
        if arena:
            leaderboard = [dict(r) for r in conn.execute("SELECT * FROM arena_daily_pnl WHERE arena_id = ? ORDER BY date DESC, rank ASC", (arena["id"],)).fetchall()]
            arena_data = {
                "arena_name": arena_name,
                "leaderboard": leaderboard
            }
    
    with open(output_dir / "arena.json", "w", encoding="utf-8") as f:
        json.dump(arena_data, f, ensure_ascii=False, indent=2)

    # 3. Export Reports
    print("Exporting reports index & files...")
    reports = []
    reports_site_dir = output_dir.parent / "reports"
    reports_site_dir.mkdir(parents=True, exist_ok=True)
    
    if table_exists(conn, "reports"):
        reports = [dict(r) for r in conn.execute("SELECT * FROM reports ORDER BY date DESC").fetchall()]
        for r in reports:
            if r.get("paths_json"):
                paths = json.loads(r["paths_json"])
                r["paths"] = paths
                # Copy the HTML file to the site reports directory
                html_rel = paths.get("html")
                if html_rel:
                    src_path = PROJECT_ROOT / html_rel
                    if src_path.exists():
                        # Target name: flatten path to avoid depth issues in static site
                        flat_name = html_rel.replace("/", "_").replace("\\", "_")
                        dest_path = reports_site_dir / flat_name
                        try:
                            shutil.copy(src_path, dest_path)
                            # Update the path in the JSON to be relative to the site root
                            r["static_html_path"] = f"reports/{flat_name}"
                        except:
                            pass
    
    with open(output_dir / "reports.json", "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)

    # 4. Export Curves
    print("Exporting equity curves...")
    curves_dir = output_dir / "curves"
    curves_dir.mkdir(parents=True, exist_ok=True)
    if table_exists(conn, "backtest_equity_curve"):
        for m in models:
            run_id = m.get("run_id")
            if not run_id:
                continue
            points = [dict(r) for r in conn.execute("SELECT date, nav, drawdown FROM backtest_equity_curve WHERE backtest_run_id = ? ORDER BY date ASC", (run_id,)).fetchall()]
            if points:
                with open(curves_dir / f"{run_id}.json", "w", encoding="utf-8") as f:
                    json.dump({"run_id": run_id, "points": points}, f, ensure_ascii=False)

    # 5. Export Manifest
    print("Exporting manifest...")
    manifest = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot_id": "latest",
        "market": market,
        "stats": {
            "total_models": len(models),
            "total_reports": len(reports)
        }
    }
    with open(output_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    conn.close()
    return True

def main():
    parser = argparse.ArgumentParser(description="Export Trading Assistant data for static site.")
    parser.add_argument("--market", type=str, default="all", choices=["cn", "us", "all"])
    parser.add_argument("--output", type=str, default="artifacts/site/data")
    args = parser.parse_args()
    
    ok = export_data(args.market, Path(args.output))
    if not ok:
        sys.exit(1)
    print(f"Done. Data exported to {args.output}")

if __name__ == "__main__":
    main()
