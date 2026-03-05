from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
from src.assistant.metadata_db import connect


def _safe_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return "{}"


class ArenaIndex:
    """
    Minimal arena index for a local "sim-account leaderboard".

    This is intentionally small and derived from existing backtest curves.
    """

    def __init__(self, *, db_path: str | Path):
        self._db_path = Path(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return connect(self._db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS arenas (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE,
                    market TEXT,
                    config_json TEXT,
                    created_ts REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS arena_participants (
                    id TEXT PRIMARY KEY,
                    arena_id TEXT,
                    name TEXT,
                    run_id TEXT,
                    model_version_id TEXT,
                    created_ts REAL,
                    UNIQUE(arena_id, run_id, model_version_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS arena_daily_pnl (
                    arena_id TEXT,
                    participant_id TEXT,
                    date TEXT,
                    nav REAL,
                    daily_return REAL,
                    drawdown REAL,
                    turnover REAL,
                    rank INTEGER,
                    created_ts REAL,
                    PRIMARY KEY (arena_id, participant_id, date)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_arena_daily_pnl_date ON arena_daily_pnl(date)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_arena_daily_pnl_arena_date ON arena_daily_pnl(arena_id, date)"
            )

    def create_arena(self, *, name: str, market: str, config: dict | None = None) -> dict:
        name = str(name or "").strip()
        if not name:
            raise ValueError("name is required")
        market = str(market or "").strip().lower()
        if not market:
            raise ValueError("market is required")

        arena_id = uuid.uuid4().hex
        now = time.time()
        config_json = _safe_json(config or {})

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO arenas (id, name, market, config_json, created_ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (arena_id, name, market, config_json, now),
            )
        return {"id": arena_id, "name": name, "market": market, "config": config or {}}

    def get_arena_by_name(self, name: str) -> dict | None:
        name = str(name or "").strip()
        if not name:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM arenas WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        if out.get("config_json"):
            try:
                out["config"] = json.loads(out["config_json"])
            except Exception:
                out["config"] = {}
        else:
            out["config"] = {}
        return out

    def get_arena(self, arena_id: str) -> dict | None:
        arena_id = str(arena_id or "").strip()
        if not arena_id:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM arenas WHERE id = ?", (arena_id,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in row.keys()}
        if out.get("config_json"):
            try:
                out["config"] = json.loads(out["config_json"])
            except Exception:
                out["config"] = {}
        else:
            out["config"] = {}
        return out

    def list_arenas(self, *, limit: int = 100, market: str | None = None) -> list[dict]:
        limit = int(limit) if limit is not None else 100
        if limit <= 0:
            return []
        market_s = str(market).strip().lower() if market else ""
        if market_s:
            sql = "SELECT * FROM arenas WHERE lower(market) = ? ORDER BY created_ts DESC LIMIT ?"
            params = (market_s, limit)
        else:
            sql = "SELECT * FROM arenas ORDER BY created_ts DESC LIMIT ?"
            params = (limit,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            if d.get("config_json"):
                try:
                    d["config"] = json.loads(d["config_json"])
                except Exception:
                    d["config"] = {}
            else:
                d["config"] = {}
            out.append(d)
        return out

    def add_participant(self, *, arena_id: str, name: str, run_id: str, model_version_id: str | None = None) -> dict:
        arena_id = str(arena_id or "").strip()
        if not arena_id:
            raise ValueError("arena_id is required")
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        model_version_id = str(model_version_id or "").strip() or None
        name = str(name or run_id).strip() or run_id

        now = time.time()

        # Idempotent insert via UNIQUE(arena_id, run_id, model_version_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM arena_participants WHERE arena_id = ? AND run_id = ? AND (model_version_id = ? OR (model_version_id IS NULL AND ? IS NULL))",
                (arena_id, run_id, model_version_id, model_version_id),
            ).fetchone()
            if row is not None:
                return {k: row[k] for k in row.keys()}

            participant_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO arena_participants (id, arena_id, name, run_id, model_version_id, created_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (participant_id, arena_id, name, run_id, model_version_id, now),
            )
        return {"id": participant_id, "arena_id": arena_id, "name": name, "run_id": run_id, "model_version_id": model_version_id}

    def list_participants(self, *, arena_id: str) -> list[dict]:
        arena_id = str(arena_id or "").strip()
        if not arena_id:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM arena_participants WHERE arena_id = ? ORDER BY created_ts ASC",
                (arena_id,),
            ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def settle(self, *, arena_id: str, date: str = "latest") -> dict:
        """
        Settle arena PnL for a given date.

        - date="latest": settles on the latest *common* date across participants.
        """
        arena_id = str(arena_id or "").strip()
        if not arena_id:
            raise ValueError("arena_id is required")

        participants = self.list_participants(arena_id=arena_id)
        if not participants:
            return {"ok": True, "date": None, "rows_upserted": 0, "participants": 0}

        curves = BacktestEquityCurveIndex(db_path=self._db_path)

        per_participant_curve: dict[str, list[dict]] = {}
        latest_dates: list[str] = []
        for p in participants:
            run_id = str(p.get("run_id") or "").strip()
            if not run_id:
                continue
            rows = curves.list_curve(run_id)
            if not rows:
                continue
            per_participant_curve[str(p["id"])] = rows
            latest_dates.append(str(rows[-1]["date"]))

        if not per_participant_curve:
            return {"ok": True, "date": None, "rows_upserted": 0, "participants": 0}

        date_s = str(date or "").strip()
        if not date_s or date_s.lower() == "latest":
            # Latest common date across participants that have curve data.
            settle_date = min(latest_dates)
        else:
            settle_date = date_s

        results: list[dict] = []
        for p in participants:
            pid = str(p.get("id") or "")
            curve = per_participant_curve.get(pid)
            if not curve:
                continue
            # Curve is sorted by date ASC.
            idx_by_date = {str(r.get("date")): i for i, r in enumerate(curve)}
            i = idx_by_date.get(settle_date)
            if i is None:
                continue
            row = curve[i]
            nav = row.get("nav")
            if nav is None:
                continue
            prev_nav = None
            if i > 0:
                prev_nav = curve[i - 1].get("nav")
            daily_return = 0.0
            if prev_nav and float(prev_nav) != 0:
                daily_return = float(nav) / float(prev_nav) - 1.0

            results.append(
                {
                    "participant_id": pid,
                    "participant_name": str(p.get("name") or ""),
                    "nav": float(nav),
                    "daily_return": float(daily_return),
                    "drawdown": float(row.get("drawdown") or 0.0),
                    "turnover": float(row.get("turnover") or 0.0),
                }
            )

        results.sort(key=lambda r: float(r.get("nav") or 0.0), reverse=True)
        for rank, r in enumerate(results, start=1):
            r["rank"] = int(rank)

        now = time.time()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO arena_daily_pnl (
                    arena_id, participant_id, date,
                    nav, daily_return, drawdown, turnover, rank,
                    created_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(arena_id, participant_id, date) DO UPDATE SET
                    nav=excluded.nav,
                    daily_return=excluded.daily_return,
                    drawdown=excluded.drawdown,
                    turnover=excluded.turnover,
                    rank=excluded.rank
                """,
                [
                    (
                        arena_id,
                        r["participant_id"],
                        settle_date,
                        r["nav"],
                        r["daily_return"],
                        r["drawdown"],
                        r["turnover"],
                        r["rank"],
                        now,
                    )
                    for r in results
                ],
            )

        return {
            "ok": True,
            "date": settle_date,
            "rows_upserted": len(results),
            "participants": len(results),
        }

    def get_leaderboard(self, *, arena_id: str, date: str) -> list[dict]:
        arena_id = str(arena_id or "").strip()
        date = str(date or "").strip()
        if not arena_id or not date:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    pnl.arena_id,
                    pnl.participant_id,
                    p.name AS participant_name,
                    p.run_id,
                    p.model_version_id,
                    pnl.date,
                    pnl.nav,
                    pnl.daily_return,
                    pnl.drawdown,
                    pnl.turnover,
                    pnl.rank
                FROM arena_daily_pnl AS pnl
                JOIN arena_participants AS p
                  ON pnl.participant_id = p.id
                WHERE pnl.arena_id = ? AND pnl.date = ?
                ORDER BY pnl.rank ASC, pnl.nav DESC
                """,
                (arena_id, date),
            ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def get_latest_settled_date(self, *, arena_id: str) -> str | None:
        arena_id = str(arena_id or "").strip()
        if not arena_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(date) AS max_date FROM arena_daily_pnl WHERE arena_id = ?",
                (arena_id,),
            ).fetchone()
        if row is None:
            return None
        v = row["max_date"]
        return str(v) if v else None

    def delete_participants_for_run(self, run_id: str) -> bool:
        """
        Best-effort cleanup when a bound backtest run is hard-deleted.
        """
        run_id = str(run_id or "").strip()
        if not run_id:
            return False

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM arena_participants WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            participant_ids = [str(r["id"]) for r in rows if r is not None and r["id"] is not None]
            if not participant_ids:
                return False

            for pid in participant_ids:
                conn.execute("DELETE FROM arena_daily_pnl WHERE participant_id = ?", (pid,))
            cur = conn.execute("DELETE FROM arena_participants WHERE run_id = ?", (run_id,))
        return bool(cur.rowcount and cur.rowcount > 0)
