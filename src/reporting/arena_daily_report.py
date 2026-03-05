from __future__ import annotations

import re
import time
from pathlib import Path

from src.assistant.arena_index import ArenaIndex
from src.assistant.report_index import ReportIndex

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str, *, max_len: int = 80) -> str:
    value = str(value or "").strip()
    value = _SLUG_RE.sub("-", value).strip("-")
    if not value:
        return "arena"
    if len(value) > max_len:
        value = value[:max_len].rstrip("-")
    return value


def _normalize_date_tag(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return "latest"
    # Common case: qlib/curve date with time suffix, e.g. 2026-02-27T00:00:00.000
    if "T" in s:
        s = s.split("T", 1)[0]
    elif " " in s:
        s = s.split(" ", 1)[0]
    # Filesystem-safe fallback.
    s = re.sub(r"[^0-9A-Za-z._-]+", "-", s).strip("-")
    return s or "latest"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "N/A"


def _format_num(value: float | None) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.4f}"
    except Exception:
        return "N/A"


def _render_arena_html(*, arena: dict, date: str, leaderboard: list[dict], report_rel_path: str, agent_thought: str = "") -> str:
    name = str(arena.get("name") or "Arena")
    market = str(arena.get("market") or "")
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")

    rows = ""
    for r in leaderboard:
        rows += (
            "<tr>"
            f"<td>{r.get('rank') or ''}</td>"
            f"<td>{r.get('participant_name') or ''}</td>"
            f"<td>{_format_num(r.get('nav'))}</td>"
            f"<td>{_format_pct(r.get('daily_return'))}</td>"
            f"<td>{_format_pct(r.get('drawdown'))}</td>"
            f"<td>{_format_num(r.get('turnover'))}</td>"
            "</tr>\n"
        )

    if not rows:
        rows = "<tr><td colspan='6'>No settled data for this date.</td></tr>"

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{name} • {date}</title>
    <style>
      :root {{
        --bg: #070a12;
        --panel: rgba(255,255,255,.06);
        --text: #e5e7eb;
        --muted: rgba(229,231,235,.72);
        --border: rgba(255,255,255,.10);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
      }}
      body {{ margin: 0; color: var(--text); background:
        radial-gradient(900px 600px at 10% 0%, rgba(34,197,94,.18), transparent 60%),
        radial-gradient(900px 600px at 90% 0%, rgba(59,130,246,.18), transparent 60%),
        var(--bg);
      }}
      .wrap {{ max-width: 1100px; margin: 32px auto; padding: 0 16px; }}
      h1 {{ font-size: 22px; margin: 0; }}
      .meta {{ margin-top: 8px; color: var(--muted); font-size: 13px; display: flex; gap: 10px; flex-wrap: wrap; }}
      .pill {{ display: inline-flex; gap: 6px; align-items: center; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); }}
      .card {{ margin-top: 14px; border: 1px solid var(--border); border-radius: 14px; background: var(--panel); overflow: hidden; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ padding: 10px 12px; font-size: 13px; border-bottom: 1px solid var(--border); }}
      th {{ color: var(--muted); text-align: left; font-weight: 600; background: rgba(255,255,255,.04); }}
      tr:last-child td {{ border-bottom: none; }}
      .footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>{name} • Daily Leaderboard</h1>
      <div class="meta">
        <span class="pill">market: {market or "unknown"}</span>
        <span class="pill">date: {date}</span>
        <span class="pill">generated: {generated_at}</span>
      </div>

      {f'''
      <div class="card" style="border-left: 4px solid #3b82f6; padding: 16px;">
        <h3 style="margin-top: 0; font-size: 16px;">🔮 Agentic Alpha Engine 洞察</h3>
        <p style="margin-bottom: 0; font-size: 14px; line-height: 1.6;"><em>"{agent_thought}"</em></p>
      </div>
      ''' if agent_thought else ''}

      <div class="card">
        <table>
          <thead>
            <tr>
              <th style="width: 80px;">Rank</th>
              <th>Participant</th>
              <th style="width: 120px;">NAV</th>
              <th style="width: 140px;">Daily Ret</th>
              <th style="width: 140px;">Drawdown</th>
              <th style="width: 120px;">Turnover</th>
            </tr>
          </thead>
          <tbody>
            {rows}
          </tbody>
        </table>
      </div>

      <div class="footer">
        This report is indexed in the local metadata DB and served via the dashboard server at: <code>{report_rel_path}</code>
      </div>
    </div>
  </body>
</html>
"""


def generate_arena_daily_report(
    *,
    arena_id: str | None = None,
    arena_name: str | None = None,
    date: str = "latest",
    project_root: str | Path,
    db_path: str | Path,
    reports_dir: str | Path | None = None,
    agent_thought: str = "",
) -> dict:
    project_root = Path(project_root)
    db_path = Path(db_path)
    reports_dir = Path(reports_dir) if reports_dir else project_root / "reports"

    arena = ArenaIndex(db_path=db_path)
    row = None
    if arena_id:
        row = arena.get_arena(str(arena_id))
    elif arena_name:
        row = arena.get_arena_by_name(str(arena_name))
    if not row:
        raise ValueError("arena not found (provide arena_id or arena_name)")

    resolved_date = str(date or "").strip() or "latest"
    if resolved_date.lower() == "latest":
        latest = arena.get_latest_settled_date(arena_id=str(row.get("id") or ""))
        if not latest:
            raise ValueError("arena has no settled data")
        resolved_date = latest

    leaderboard = arena.get_leaderboard(arena_id=str(row.get("id") or ""), date=resolved_date)

    market = str(row.get("market") or "unknown").lower() or "unknown"
    name = str(row.get("name") or "Arena")
    out_dir = reports_dir / "arena" / market / _slug(name) / _normalize_date_tag(resolved_date)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"

    report_rel_path = (
        str(out_path.relative_to(project_root)).replace("\\", "/") if out_path.is_relative_to(project_root) else str(out_path)
    )
    html = _render_arena_html(
        arena=row,
        date=resolved_date,
        leaderboard=leaderboard,
        report_rel_path=f"/{report_rel_path.lstrip('/')}",
        agent_thought=agent_thought,
    )
    out_path.write_text(html, encoding="utf-8")

    idx = ReportIndex(db_path=db_path)
    report_row = idx.upsert(
        report_type="arena_daily",
        ref_id=str(row.get("id") or ""),
        date=_normalize_date_tag(resolved_date),
        formats=["html"],
        paths={"html": report_rel_path},
        meta={"arena_name": name, "market": market, "participants": len(leaderboard)},
    )

    return {
        "ok": True,
        "report": report_row,
        "report_path": str(out_path),
        "report_rel_path": report_rel_path,
        "arena": {"id": str(row.get("id") or ""), "name": name, "market": market},
        "date": resolved_date,
        "participants": len(leaderboard),
    }
