from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_DB = PROJECT_ROOT / "artifacts" / "metadata" / "metadata.db"


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cur.fetchone() is not None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_blocked_empty_export(market: str, output_dir: Path) -> None:
    """Write a truthful, bundle-compatible export when Pages has no research DB.

    This path is deliberately opt-in. It publishes no model or performance evidence
    and marks promotion as blocked instead of manufacturing demo results.
    """

    _write_json(output_dir / "models.json", [])
    _write_json(output_dir / "arena.json", {"arena_name": "N/A", "leaderboard": []})
    _write_json(output_dir / "reports.json", [])
    (output_dir / "curves").mkdir(parents=True, exist_ok=True)
    _write_json(
        output_dir / "manifest.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evidence_cutoff": None,
            "snapshot_id": None,
            "market": market,
            "stats": {"total_models": 0, "total_reports": 0},
            "warnings": [
                "The published Pages build has no repository-backed metadata database.",
                "Open a verified local Alpha Engine bundle to review research evidence.",
            ],
            "blocked_gates": ["metadata_db_missing", "published_evidence_unavailable"],
            "promotion_decision": "blocked",
        },
    )


def export_data(
    market: str,
    output_dir: Path,
    *,
    db_path: Path = DEFAULT_METADATA_DB,
    allow_empty: bool = False,
) -> bool:
    output_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        if not allow_empty:
            print(f"Error: Metadata DB not found at {db_path}")
            return False
        print("Metadata DB is unavailable; writing an explicitly blocked empty export.")
        _write_blocked_empty_export(market, output_dir)
        return True

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # 1. Export Models
        print("Exporting models...")
        models: list[dict[str, Any]] = []
        if table_exists(conn, "model_versions"):
            m_filter = f"WHERE lower(market) = '{market}'" if market != "all" else ""
            models = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM model_versions {m_filter} ORDER BY created_ts DESC"
                ).fetchall()
            ]
            for model in models:
                for key in ["params_json", "metrics_json", "feature_importance_json"]:
                    if model.get(key):
                        try:
                            model[key.replace("_json", "")] = json.loads(model[key])
                        except Exception:
                            model[key.replace("_json", "")] = {}

        _write_json(output_dir / "models.json", models)

        # 2. Export Arena
        print("Exporting arena...")
        arena_data: dict[str, Any] = {"arena_name": "N/A", "leaderboard": []}
        if table_exists(conn, "arenas") and table_exists(conn, "arena_daily_pnl"):
            arena_name = "Global Arena" if market == "all" else f"{market.upper()} Arena"
            arena = conn.execute("SELECT * FROM arenas WHERE name = ?", (arena_name,)).fetchone()
            if arena:
                leaderboard = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM arena_daily_pnl WHERE arena_id = ? ORDER BY date DESC, rank ASC",
                        (arena["id"],),
                    ).fetchall()
                ]
                arena_data = {"arena_name": arena_name, "leaderboard": leaderboard}

        _write_json(output_dir / "arena.json", arena_data)

        # 3. Export Reports
        print("Exporting reports index & files...")
        reports: list[dict[str, Any]] = []
        reports_site_dir = output_dir.parent / "reports"
        reports_site_dir.mkdir(parents=True, exist_ok=True)

        if table_exists(conn, "reports"):
            reports = [
                dict(r) for r in conn.execute("SELECT * FROM reports ORDER BY date DESC").fetchall()
            ]
            for report in reports:
                if report.get("paths_json"):
                    paths = json.loads(report["paths_json"])
                    report["paths"] = paths
                    html_rel = paths.get("html")
                    if html_rel:
                        src_path = PROJECT_ROOT / html_rel
                        if src_path.exists():
                            flat_name = html_rel.replace("/", "_").replace("\\", "_")
                            dest_path = reports_site_dir / flat_name
                            try:
                                shutil.copy(src_path, dest_path)
                                report["static_html_path"] = f"reports/{flat_name}"
                            except Exception:
                                pass

        _write_json(output_dir / "reports.json", reports)

        # 4. Export Curves
        print("Exporting equity curves...")
        curves_dir = output_dir / "curves"
        curves_dir.mkdir(parents=True, exist_ok=True)
        if table_exists(conn, "backtest_equity_curve"):
            for model in models:
                run_id = model.get("run_id")
                if not run_id:
                    continue
                points = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT date, nav, drawdown FROM backtest_equity_curve WHERE backtest_run_id = ? ORDER BY date ASC",
                        (run_id,),
                    ).fetchall()
                ]
                if points:
                    _write_json(curves_dir / f"{run_id}.json", {"run_id": run_id, "points": points})

        # 5. Export Manifest
        print("Exporting manifest...")
        _write_json(
            output_dir / "manifest.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_id": "latest",
                "market": market,
                "stats": {"total_models": len(models), "total_reports": len(reports)},
            },
        )
        return True
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Alpha Engine data for the static site.")
    parser.add_argument("--market", type=str, default="all", choices=["cn", "us", "all"])
    parser.add_argument("--output", type=str, default="artifacts/site/data")
    parser.add_argument(
        "--metadata-db",
        type=Path,
        default=DEFAULT_METADATA_DB,
        help="Metadata SQLite database used for the published evidence export.",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Write a blocked empty export when the metadata DB is unavailable.",
    )
    args = parser.parse_args()

    ok = export_data(
        args.market,
        Path(args.output),
        db_path=args.metadata_db,
        allow_empty=args.allow_empty,
    )
    if not ok:
        sys.exit(1)
    print(f"Done. Data exported to {args.output}")


if __name__ == "__main__":
    main()
