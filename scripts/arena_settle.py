import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.arena_index import ArenaIndex
from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex


def get_or_create_arena(*, arena: ArenaIndex, name: str, market: str) -> dict:
    existing = arena.get_arena_by_name(name)
    if existing:
        return existing
    return arena.create_arena(name=name, market=market)


def seed_from_model_registry(*, arena: ArenaIndex, arena_id: str, db_path: Path, market: str, limit: int) -> int:
    idx = ModelRegistryIndex(db_path=db_path)
    # If market is "all", pass None to list_versions to get models from all markets
    m_filter = None if market == "all" else market
    versions = idx.list_versions(limit=limit, market=m_filter)
    n = 0
    for v in versions:
        run_id = str(v.get("run_id") or "").strip()
        if not run_id:
            continue
        name = str(v.get("tag") or v.get("name") or v.get("id") or run_id).strip() or run_id
        arena.add_participant(arena_id=arena_id, name=name, run_id=run_id)
        n += 1
    return n


def main():
    parser = argparse.ArgumentParser(description="Settle the local Arena leaderboard from backtest equity curves.")
    parser.add_argument("--market", type=str, default="us", help="Market key (us/cn). Default: us")
    parser.add_argument("--arena-name", type=str, default="", help="Arena name (default: '{MARKET} Arena')")
    parser.add_argument("--date", type=str, default="latest", help="Settlement date (YYYY-MM-DD) or 'latest' (default).")
    parser.add_argument("--seed-from-model-registry", action="store_true", help="Add participants from model registry.")
    parser.add_argument("--limit", type=int, default=50, help="Max model versions to seed (default: 50).")
    parser.add_argument("--no-report", action="store_true", help="Skip generating the HTML daily arena report.")
    args = parser.parse_args()

    market = str(args.market or "").strip().lower() or "us"
    arena_name = str(args.arena_name or "").strip() or f"{market.upper()} Arena"
    date = str(args.date or "").strip() or "latest"

    db_path = resolve_metadata_db_path(PROJECT_ROOT)
    arena = ArenaIndex(db_path=db_path)

    a = get_or_create_arena(arena=arena, name=arena_name, market=market)
    arena_id = str(a.get("id") or "")
    if not arena_id:
        raise RuntimeError("arena id missing")

    seeded = 0
    if bool(args.seed_from_model_registry):
        seeded = seed_from_model_registry(
            arena=arena,
            arena_id=arena_id,
            db_path=db_path,
            market=market,
            limit=max(int(args.limit), 0),
        )

    settled = arena.settle(arena_id=arena_id, date=date)
    report_rel_path = ""
    if not bool(args.no_report):
        try:
            from src.reporting.arena_daily_report import generate_arena_daily_report

            rep = generate_arena_daily_report(
                arena_id=arena_id,
                date=str(settled.get("date") or date),
                project_root=PROJECT_ROOT,
                db_path=db_path,
            )
            report_rel_path = str(rep.get("report_rel_path") or "")
        except Exception as e:
            print(f"Warning: Failed to generate arena report: {e}")
    print(
        f"Arena settled: name={arena_name} market={market} date={settled.get('date')} "
        f"rows={settled.get('rows_upserted')} seeded={seeded} report={report_rel_path or 'n/a'}"
    )


if __name__ == "__main__":
    main()
