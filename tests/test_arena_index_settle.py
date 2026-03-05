import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_arena_settle_latest_common_date(tmp_path: Path):
    from src.assistant.arena_index import ArenaIndex
    from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex

    db_path = tmp_path / "artifacts" / "metadata" / "metadata.db"

    curves = BacktestEquityCurveIndex(db_path=db_path)
    curves.upsert_from_report_normal_json(
        "run_1",
        {
            "columns": ["account", "turnover"],
            "index": ["2025-01-01", "2025-01-02"],
            "data": [[100.0, 0.1], [110.0, 0.2]],
        },
    )
    curves.upsert_from_report_normal_json(
        "run_2",
        {
            "columns": ["account", "turnover"],
            "index": ["2025-01-01", "2025-01-02"],
            "data": [[100.0, 0.1], [120.0, 0.2]],
        },
    )

    arena = ArenaIndex(db_path=db_path)
    arena_row = arena.create_arena(name="US Arena", market="us")
    assert arena_row["name"] == "US Arena"

    p1 = arena.add_participant(arena_id=arena_row["id"], name="m1", run_id="run_1")
    p2 = arena.add_participant(arena_id=arena_row["id"], name="m2", run_id="run_2")
    assert p1 and p2

    settled = arena.settle(arena_id=arena_row["id"], date="latest")
    assert settled["date"] == "2025-01-02"
    assert settled["rows_upserted"] == 2

    leaderboard = arena.get_leaderboard(arena_id=arena_row["id"], date="2025-01-02")
    assert [r["participant_name"] for r in leaderboard] == ["m2", "m1"]
    assert leaderboard[0]["rank"] == 1
    assert leaderboard[1]["rank"] == 2

    assert leaderboard[0]["nav"] == pytest.approx(120.0)
    assert leaderboard[1]["nav"] == pytest.approx(110.0)
    assert leaderboard[0]["daily_return"] == pytest.approx(0.2)
    assert leaderboard[1]["daily_return"] == pytest.approx(0.1)

