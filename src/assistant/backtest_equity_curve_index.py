from __future__ import annotations

import contextlib
import time
from pathlib import Path

from src.assistant.metadata_db import connect


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def _extract_curve_points(report_normal) -> list[dict]:
    if not report_normal:
        return []

    # 1) Pandas `to_json(orient="split")` format: {columns, index, data}
    if (
        isinstance(report_normal, dict)
        and report_normal.get("columns")
        and report_normal.get("index")
        and report_normal.get("data")
    ):
        columns = report_normal.get("columns") or []
        index = report_normal.get("index") or []
        data = report_normal.get("data") or []
        if (
            not isinstance(columns, list)
            or not isinstance(index, list)
            or not isinstance(data, list)
        ):
            return []

        col_to_idx = {str(c).lower(): i for i, c in enumerate(columns)}
        account_idx = col_to_idx.get("account")
        if account_idx is None:
            return []
        turnover_idx = col_to_idx.get("turnover")

        points: list[dict] = []
        for i, idx in enumerate(index):
            if i >= len(data):
                break
            row = data[i]
            if not isinstance(row, list):
                continue
            nav = _to_float(row[account_idx] if account_idx < len(row) else None)
            if nav is None:
                continue
            turnover = _to_float(
                row[turnover_idx] if turnover_idx is not None and turnover_idx < len(row) else None
            )
            points.append({"date": str(idx), "nav": nav, "turnover": turnover})
        return points

    # 2) Records format: [{"date": "...", "account": ..., "turnover": ...}, ...]
    if isinstance(report_normal, list):
        points = []
        for row in report_normal:
            if not isinstance(row, dict):
                continue
            date = row.get("date")
            nav = _to_float(row.get("account"))
            if not date or nav is None:
                continue
            turnover = _to_float(row.get("turnover"))
            points.append({"date": str(date), "nav": nav, "turnover": turnover})
        return points

    return []


def _compute_drawdowns(points: list[dict]) -> list[dict]:
    points = [
        p for p in points if isinstance(p, dict) and p.get("date") and p.get("nav") is not None
    ]
    points.sort(key=lambda p: str(p.get("date")))

    peak = None
    out: list[dict] = []
    for p in points:
        nav = float(p["nav"])
        if peak is None or nav > peak:
            peak = nav
        dd = 0.0
        if peak and peak > 0:
            dd = (peak - nav) / peak
        out.append(
            {
                "date": str(p["date"]),
                "nav": nav,
                "turnover": p.get("turnover"),
                "drawdown": dd,
            }
        )
    return out


class BacktestEquityCurveIndex:
    """
    Persist per-run equity curves (NAV/drawdown/turnover) to the local metadata DB.

    This is derived data; the source of truth remains the MLflow artifacts.
    """

    def __init__(self, *, db_path: str | Path):
        self._db_path = Path(db_path)
        self._ensure_schema()

    @contextlib.contextmanager
    def _connect(self):
        conn = connect(self._db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_equity_curve (
                    backtest_run_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    nav REAL,
                    drawdown REAL,
                    turnover REAL,
                    created_at REAL,
                    PRIMARY KEY (backtest_run_id, date)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bt_curve_run_date ON backtest_equity_curve(backtest_run_id, date)"
            )

    def upsert_from_report_normal_json(self, run_id: str, report_normal) -> int:
        run_id = str(run_id or "").strip()
        if not run_id:
            return 0

        points = _compute_drawdowns(_extract_curve_points(report_normal))
        if not points:
            return 0

        now = time.time()
        rows = [
            (
                run_id,
                p["date"],
                float(p["nav"]) if p.get("nav") is not None else None,
                float(p["drawdown"]) if p.get("drawdown") is not None else None,
                float(p["turnover"]) if p.get("turnover") is not None else None,
                now,
            )
            for p in points
        ]

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO backtest_equity_curve (
                    backtest_run_id, date, nav, drawdown, turnover, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(backtest_run_id, date) DO UPDATE SET
                    nav=excluded.nav,
                    drawdown=excluded.drawdown,
                    turnover=excluded.turnover
                """,
                rows,
            )
        return len(rows)

    def list_curve(self, run_id: str, *, limit: int | None = None) -> list[dict]:
        run_id = str(run_id or "").strip()
        if not run_id:
            return []

        limit_i = None
        if limit is not None:
            try:
                limit_i = int(limit)
            except Exception:
                limit_i = None
            if limit_i is not None and limit_i <= 0:
                return []

        if limit_i is None:
            sql = "SELECT * FROM backtest_equity_curve WHERE backtest_run_id = ? ORDER BY date ASC"
            params = (run_id,)
        else:
            sql = "SELECT * FROM backtest_equity_curve WHERE backtest_run_id = ? ORDER BY date ASC LIMIT ?"
            params = (run_id, limit_i)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def delete_curve(self, run_id: str) -> bool:
        run_id = str(run_id or "").strip()
        if not run_id:
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM backtest_equity_curve WHERE backtest_run_id = ?", (run_id,)
            )
        return bool(cur.rowcount and cur.rowcount > 0)
