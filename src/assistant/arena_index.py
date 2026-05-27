from __future__ import annotations

import json
import time
import uuid

from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
from src.assistant.base_index import BaseIndex
from src.common.logging import get_logger

logger = get_logger(__name__)


def _safe_json(value) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except Exception:
        logger.debug("Failed to serialize value to JSON", exc_info=True)
        return "{}"


class ArenaIndex(BaseIndex):
    """
    Manage trading arenas, participants, and periodic leaderboard settlements.
    """

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
                    daily_pnl REAL,
                    daily_return REAL,
                    drawdown REAL,
                    turnover REAL,
                    PRIMARY KEY (arena_id, participant_id, date)
                )
                """
            )

    def create_arena(self, *, name: str, market: str = "us", config: dict | None = None) -> dict:
        name = str(name).strip()
        arena_id = uuid.uuid4().hex
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO arenas (id, name, market, config_json, created_ts) VALUES (?, ?, ?, ?, ?)",
                (arena_id, name, market, _safe_json(config), now),
            )
        return {"id": arena_id, "name": name, "market": market, "config": config or {}}

    def get_arena(self, arena_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM arenas WHERE id = ?", (arena_id,)).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        d["config"] = json.loads(d["config_json"]) if d.get("config_json") else {}
        return d

    def get_arena_by_name(self, name: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM arenas WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        d["config"] = json.loads(d["config_json"]) if d.get("config_json") else {}
        return d

    def list_arenas(self, *, market: str | None = None, limit: int = 100) -> list[dict]:
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
                    logger.debug("Failed to parse arena config_json", arena_id=d.get("id"), exc_info=True)
                    d["config"] = {}
            else:
                d["config"] = {}
            out.append(d)
        return out

    def add_participant(
        self, *, arena_id: str, name: str, run_id: str, model_version_id: str | None = None
    ) -> dict:
        arena_id = str(arena_id or "").strip()
        if not arena_id:
            raise ValueError("arena_id is required")
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        model_version_id = str(model_version_id or "").strip() or None
        name = str(name or run_id).strip() or run_id

        now = time.time()

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
        return {
            "id": participant_id,
            "arena_id": arena_id,
            "name": name,
            "run_id": run_id,
            "model_version_id": model_version_id,
        }

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
            settle_date = min(latest_dates)
        else:
            settle_date = date_s

        rows_upserted = 0
        with self._connect() as conn:
            for pid, curve in per_participant_curve.items():
                idx = next((i for i, p in enumerate(curve) if str(p["date"]) == settle_date), None)
                if idx is None:
                    continue

                point = curve[idx]
                prev_point = curve[idx - 1] if idx > 0 else None

                daily_return = 0.0
                if prev_point and prev_point.get("nav"):
                    daily_return = (point["nav"] - prev_point["nav"]) / prev_point["nav"]

                conn.execute(
                    """
                    INSERT OR REPLACE INTO arena_daily_pnl (arena_id, participant_id, date, nav, daily_pnl, daily_return, drawdown, turnover)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        arena_id,
                        pid,
                        settle_date,
                        point["nav"],
                        point["nav"] - (prev_point["nav"] if prev_point else point["nav"]),
                        daily_return,
                        point["drawdown"],
                        point["turnover"],
                    ),
                )
                rows_upserted += 1

        return {
            "ok": True,
            "date": settle_date,
            "rows_upserted": rows_upserted,
            "participants": len(per_participant_curve),
        }

    def get_leaderboard(self, *, arena_id: str | None = None, date: str = "latest") -> list[dict]:
        if not arena_id:
            return []

        date_s = str(date or "").strip()
        if not date_s or date_s.lower() == "latest":
            settle_date = self.get_latest_settled_date(arena_id)
        else:
            settle_date = date_s

        if not settle_date:
            return []

        sql = """
            SELECT p.name as participant_name, pnl.* 
            FROM arena_daily_pnl pnl
            JOIN arena_participants p ON pnl.participant_id = p.id
            WHERE pnl.arena_id = ? AND pnl.date = ?
            ORDER BY pnl.nav DESC
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (arena_id, settle_date)).fetchall()

        out = []
        for i, r in enumerate(rows):
            d = {k: r[k] for k in r.keys()}
            d["rank"] = i + 1
            out.append(d)
        return out

    def get_latest_settled_date(self, arena_id: str) -> str | None:
        sql = "SELECT MAX(date) FROM arena_daily_pnl WHERE arena_id = ?"
        with self._connect() as conn:
            row = conn.execute(sql, (arena_id,)).fetchone()
        return row[0] if row and row[0] else None

    def delete_participants_for_run(self, run_id: str) -> bool:
        run_id = str(run_id or "").strip()
        if not run_id:
            return False
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM arena_participants WHERE run_id = ?", (run_id,)
            ).fetchall()
            pids = [r["id"] for r in rows]
            if pids:
                placeholders = ",".join(["?"] * len(pids))
                conn.execute(
                    f"DELETE FROM arena_daily_pnl WHERE participant_id IN ({placeholders})",
                    tuple(pids),
                )
            cur = conn.execute("DELETE FROM arena_participants WHERE run_id = ?", (run_id,))
        return bool(cur.rowcount and cur.rowcount > 0)

    def delete_participant_by_run_id(self, *, arena_id: str, run_id: str) -> bool:
        arena_id = str(arena_id or "").strip()
        run_id = str(run_id or "").strip()
        if not arena_id or not run_id:
            return False
        with self._connect() as conn:
            p = conn.execute(
                "SELECT id FROM arena_participants WHERE arena_id = ? AND run_id = ?",
                (arena_id, run_id),
            ).fetchone()
            if p:
                pid = p["id"]
                conn.execute("DELETE FROM arena_daily_pnl WHERE participant_id = ?", (pid,))
            cur = conn.execute(
                "DELETE FROM arena_participants WHERE arena_id = ? AND run_id = ?",
                (arena_id, run_id),
            )
        return bool(cur.rowcount and cur.rowcount > 0)
