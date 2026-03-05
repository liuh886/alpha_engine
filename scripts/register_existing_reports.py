import sqlite3
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
db_path = project_root / "artifacts" / "metadata" / "metadata.db"
reports_dir = project_root / "reports"

def register_reports():
    if not db_path.exists():
        print("DB not found.")
        return
        
    conn = sqlite3.connect(db_path)
    
    # We want to find all .html files in reports/ and its subdirectories
    html_files = list(reports_dir.rglob("*.html"))
    print(f"Found {len(html_files)} HTML reports.")
    
    for p in html_files:
        rel_path = p.relative_to(project_root)
        filename = p.name
        
        # Determine type
        rtype = "backtest"
        if "arena" in filename.lower(): rtype = "arena_daily"
        
        # Determine ref_id (best effort)
        # Try to find a 32-char hex string (UUID/MLflow ID)
        ref_id = "manual_discovery"
        import re
        match = re.search(r"[0-9a-f]{32}", str(rel_path))
        if match:
            ref_id = match.group(0)
        
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
        
        # Check if exists
        exists = conn.execute("SELECT 1 FROM reports WHERE paths_json LIKE ?", (f"%{rel_path}%",)).fetchone()
        if not exists:
            import json
            import uuid
            report_id = uuid.uuid4().hex
            paths = {"html": str(rel_path).replace("\\", "/")}
            conn.execute(
                "INSERT INTO reports (id, type, ref_id, date, paths_json, created_ts) VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, rtype, ref_id, mtime, json.dumps(paths), p.stat().st_mtime)
            )
            print(f"Registered: {rel_path}")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    register_reports()
