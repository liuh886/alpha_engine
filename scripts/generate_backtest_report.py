import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.metadata_db import resolve_metadata_db_path
from src.reporting.backtest_report import generate_backtest_report, generate_latest_backtest_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an HTML backtest report and index it in SQLite."
    )
    parser.add_argument("--run-id", type=str, default="", help="Backtest run id (mlflow run_id).")
    parser.add_argument(
        "--market", type=str, default="", help="Market (us/cn). Used with --latest."
    )
    parser.add_argument(
        "--latest", action="store_true", help="Generate report for the latest run in --market."
    )
    parser.add_argument("--db-path", type=str, default="", help="Override SQLite metadata DB path.")
    args = parser.parse_args()

    db_path = (
        Path(args.db_path).expanduser()
        if str(args.db_path or "").strip()
        else resolve_metadata_db_path(PROJECT_ROOT)
    )

    if args.latest:
        if not str(args.market or "").strip():
            raise SystemExit("--market is required when using --latest")
        out = generate_latest_backtest_report(
            market=args.market, project_root=PROJECT_ROOT, db_path=db_path
        )
    else:
        run_id = str(args.run_id or "").strip()
        if not run_id:
            raise SystemExit("Provide --run-id or use --latest --market <us|cn>")
        out = generate_backtest_report(run_id=run_id, project_root=PROJECT_ROOT, db_path=db_path)

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
