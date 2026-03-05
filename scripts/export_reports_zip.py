import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.reporting.report_archive import export_reports_zip


def main() -> int:
    parser = argparse.ArgumentParser(description="Export indexed HTML reports into a zip archive.")
    parser.add_argument(
        "--type",
        type=str,
        default="all",
        help="Report type filter: all/backtest/arena_daily/archive (default: all).",
    )
    parser.add_argument("--limit", type=int, default=100, help="Max reports to include (default: 100).")
    parser.add_argument("--db-path", type=str, default="", help="Override SQLite metadata DB path.")
    parser.add_argument("--output", type=str, default="", help="Override output zip path.")
    args = parser.parse_args()

    type_filter = str(args.type or "all").strip()
    limit = int(args.limit) if args.limit is not None else 100
    if limit <= 0:
        limit = 100

    db_path = Path(args.db_path).expanduser() if str(args.db_path or "").strip() else resolve_metadata_db_path(PROJECT_ROOT)
    output_path = Path(args.output).expanduser() if str(args.output or "").strip() else None

    out = export_reports_zip(
        project_root=PROJECT_ROOT,
        db_path=db_path,
        type_filter=type_filter,
        limit=limit,
        output_path=output_path,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
