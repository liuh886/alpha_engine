import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.reporting.arena_daily_report import generate_arena_daily_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an HTML daily Arena report and index it in SQLite."
    )
    parser.add_argument("--arena-id", type=str, default="", help="Arena id (preferred when known).")
    parser.add_argument("--arena-name", type=str, default="", help="Arena name (fallback).")
    parser.add_argument(
        "--date", type=str, default="latest", help="YYYY-MM-DD or 'latest' (default)."
    )
    parser.add_argument("--db-path", type=str, default="", help="Override SQLite metadata DB path.")
    args = parser.parse_args()

    db_path = (
        Path(args.db_path).expanduser()
        if str(args.db_path or "").strip()
        else resolve_metadata_db_path(PROJECT_ROOT)
    )
    arena_id = str(args.arena_id or "").strip() or None
    arena_name = str(args.arena_name or "").strip() or None
    if not arena_id and not arena_name:
        raise SystemExit("Provide --arena-id or --arena-name")

    out = generate_arena_daily_report(
        arena_id=arena_id,
        arena_name=arena_name,
        date=str(args.date or "latest"),
        project_root=PROJECT_ROOT,
        db_path=db_path,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
