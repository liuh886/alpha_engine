from __future__ import annotations

import json
import math
import time
from pathlib import Path

from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
from src.assistant.report_index import ReportIndex
from src.assistant.run_index import RunIndex


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def _compute_metrics_from_curve(curve: list[dict]) -> dict:
    curve = [r for r in curve if isinstance(r, dict) and r.get("nav") is not None and r.get("date")]
    curve.sort(key=lambda r: str(r.get("date")))
    if len(curve) < 2:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "annualized_vol": 0.0,
            "sharpe": 0.0,
            "days": int(len(curve)),
        }

    navs = [float(r["nav"]) for r in curve]
    rets = []
    for i in range(1, len(navs)):
        prev = navs[i - 1]
        cur = navs[i]
        if prev and prev != 0:
            rets.append(cur / prev - 1.0)
        else:
            rets.append(0.0)

    total_return = navs[-1] / navs[0] - 1.0 if navs[0] else 0.0
    days = max(len(rets), 1)
    annualized_return = 0.0
    try:
        annualized_return = (1.0 + total_return) ** (252.0 / float(days)) - 1.0
    except Exception:
        annualized_return = 0.0

    # Vol / Sharpe (rf=0 for now)
    mean_ret = sum(rets) / float(len(rets)) if rets else 0.0
    var = sum((r - mean_ret) ** 2 for r in rets) / float(len(rets)) if rets else 0.0
    vol = math.sqrt(var) * math.sqrt(252.0)
    sharpe = (mean_ret * 252.0) / vol if vol else 0.0

    max_dd = 0.0
    for r in curve:
        dd = _to_float(r.get("drawdown"))
        if dd is None:
            continue
        if float(dd) > max_dd:
            max_dd = float(dd)

    return {
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "max_drawdown": float(max_dd),
        "annualized_vol": float(vol),
        "sharpe": float(sharpe),
        "days": int(days),
    }


def _format_pct(value: float) -> str:
    try:
        return f"{value * 100:.2f}%"
    except Exception:
        return "N/A"


def _format_num(value: float) -> str:
    try:
        return f"{value:.3f}"
    except Exception:
        return "N/A"


def _render_backtest_html(
    *, title: str, run: dict, metrics: dict, curve: list[dict], report_rel_path: str
) -> str:
    run_id = str(run.get("id") or "")
    market = str(run.get("market") or "")
    backtest_start = str(run.get("backtest_start") or "")
    backtest_end = str(run.get("backtest_end") or "")
    snapshot_id = str(run.get("data_snapshot_id") or "")

    last_date = ""
    if curve:
        try:
            last_date = str(sorted([str(r.get("date")) for r in curve if r.get("date")])[-1])
        except Exception:
            last_date = ""

    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = "\n".join(
        [
            f"<tr><td>{r.get('date')}</td><td>{_format_num(float(r.get('nav') or 0.0))}</td><td>{_format_pct(float(r.get('drawdown') or 0.0))}</td></tr>"
            for r in curve[-60:]
        ]
    )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      :root {{
        --bg: #0b1220;
        --panel: #0f1a2e;
        --text: #e6eefc;
        --muted: #a9b8d6;
        --accent: #7c3aed;
        --border: rgba(255,255,255,.08);
        --good: #22c55e;
        --bad: #ef4444;
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
      }}
      body {{ background: radial-gradient(900px 600px at 15% 0%, rgba(124,58,237,.25), transparent 60%), var(--bg); color: var(--text); margin: 0; }}
      a {{ color: var(--text); text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,.25); }}
      a:hover {{ border-bottom-color: rgba(255,255,255,.55); }}
      .wrap {{ max-width: 980px; margin: 32px auto; padding: 0 16px; }}
      .header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }}
      h1 {{ font-size: 22px; margin: 0; letter-spacing: .2px; }}
      .meta {{ color: var(--muted); font-size: 13px; }}
      .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }}
      .card {{ background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03)); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }}
      .label {{ color: var(--muted); font-size: 12px; }}
      .value {{ font-size: 18px; font-weight: 700; margin-top: 6px; }}
      .table {{ width: 100%; border-collapse: collapse; margin-top: 14px; overflow: hidden; border-radius: 12px; border: 1px solid var(--border); }}
      .table th, .table td {{ padding: 10px 12px; font-size: 13px; border-bottom: 1px solid var(--border); }}
      .table th {{ text-align: left; color: var(--muted); font-weight: 600; background: rgba(255,255,255,.03); }}
      .table tr:last-child td {{ border-bottom: none; }}
      .pill {{ display: inline-flex; gap: 6px; align-items: center; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); font-size: 12px; }}
      .footer {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
      @media (max-width: 920px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="header">
        <div>
          <h1>{title}</h1>
          <div class="meta">
            <span class="pill">market: {market or "unknown"}</span>
            <span class="pill">run_id: <code>{run_id}</code></span>
            {f'<span class="pill">snapshot: {snapshot_id}</span>' if snapshot_id else ""}
          </div>
          <div class="meta" style="margin-top: 8px;">
            window: {backtest_start or "?"} → {backtest_end or last_date or "?"}
          </div>
        </div>
        <div class="meta">generated: {generated_at}</div>
      </div>

      <div class="grid">
        <div class="card">
          <div class="label">Annualized Return</div>
          <div class="value">{_format_pct(float(metrics.get("annualized_return") or 0.0))}</div>
        </div>
        <div class="card">
          <div class="label">Total Return</div>
          <div class="value">{_format_pct(float(metrics.get("total_return") or 0.0))}</div>
        </div>
        <div class="card">
          <div class="label">Max Drawdown</div>
          <div class="value">{_format_pct(float(metrics.get("max_drawdown") or 0.0))}</div>
        </div>
        <div class="card">
          <div class="label">Sharpe</div>
          <div class="value">{_format_num(float(metrics.get("sharpe") or 0.0))}</div>
        </div>
      </div>

      <div class="card" style="margin-top: 14px;">
        <div class="label">Recent NAV / Drawdown (last 60 days)</div>
        <table class="table">
          <thead>
            <tr><th>Date</th><th>NAV</th><th>Drawdown</th></tr>
          </thead>
          <tbody>
            {rows or '<tr><td colspan="3">No curve data.</td></tr>'}
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


def _find_run_in_dashboard_db(*, dashboard_db_path: Path, run_id: str) -> dict | None:
    if not dashboard_db_path.exists():
        return None
    try:
        payload = json.loads(dashboard_db_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    if not isinstance(models, list):
        return None
    for m in models:
        if isinstance(m, dict) and str(m.get("id") or "") == run_id:
            return m
    return None


def generate_backtest_report(
    *,
    run_id: str,
    project_root: str | Path,
    db_path: str | Path,
    reports_dir: str | Path | None = None,
    dashboard_db_path: str | Path | None = None,
) -> dict:
    run_id = str(run_id or "").strip()
    if not run_id:
        raise ValueError("run_id is required")

    project_root = Path(project_root)
    db_path = Path(db_path)
    reports_dir = Path(reports_dir) if reports_dir else project_root / "reports"
    dashboard_db_path = (
        Path(dashboard_db_path)
        if dashboard_db_path
        else project_root / "artifacts" / "dashboard" / "dashboard_db.json"
    )

    run_index = RunIndex(db_path=db_path)
    run = run_index.get_run(run_id) or {"id": run_id}

    # Prefer market/name from dashboard_db.json if missing.
    dash_row = _find_run_in_dashboard_db(dashboard_db_path=dashboard_db_path, run_id=run_id)
    if dash_row:
        run.setdefault("name", dash_row.get("name"))
        run.setdefault("market", dash_row.get("market"))
        params = dash_row.get("params") if isinstance(dash_row.get("params"), dict) else {}
        if params:
            run.setdefault("backtest_start", params.get("backtest_start"))
            run.setdefault("backtest_end", params.get("backtest_end"))
            meta = params.get("meta") if isinstance(params.get("meta"), dict) else {}
            if meta and meta.get("data_snapshot_id"):
                run.setdefault("data_snapshot_id", meta.get("data_snapshot_id"))

    market = str(run.get("market") or "unknown").lower() or "unknown"

    curve_index = BacktestEquityCurveIndex(db_path=db_path)
    curve = curve_index.list_curve(run_id)
    if not curve and dash_row:
        try:
            report_normal = (
                (dash_row.get("data") or {}) if isinstance(dash_row.get("data"), dict) else {}
            ).get("report_normal")
            curve_index.upsert_from_report_normal_json(run_id, report_normal)
            curve = curve_index.list_curve(run_id)
        except Exception:
            curve = []

    metrics = _compute_metrics_from_curve(curve)
    title = str(run.get("name") or f"Backtest {run_id[:8]}").strip() or f"Backtest {run_id[:8]}"

    out_dir = reports_dir / "backtests" / market / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"

    report_rel_path = (
        str(out_path.relative_to(project_root)).replace("\\", "/")
        if out_path.is_relative_to(project_root)
        else str(out_path)
    )
    html = _render_backtest_html(
        title=title,
        run=run,
        metrics=metrics,
        curve=curve,
        report_rel_path=f"/{report_rel_path.lstrip('/')}",
    )
    out_path.write_text(html, encoding="utf-8")

    date = None
    if curve:
        date = str(curve[-1].get("date") or "").strip() or None
    elif run.get("backtest_end"):
        date = str(run.get("backtest_end") or "").strip() or None

    idx = ReportIndex(db_path=db_path)
    row = idx.upsert(
        report_type="backtest",
        ref_id=run_id,
        date=date,
        formats=["html"],
        paths={"html": report_rel_path},
        meta={"market": market, "metrics": metrics},
    )

    return {
        "ok": True,
        "report": row,
        "report_path": str(out_path),
        "report_rel_path": report_rel_path,
        "metrics": metrics,
        "run": run,
    }


def generate_latest_backtest_report(
    *, market: str, project_root: str | Path, db_path: str | Path
) -> dict:
    market = str(market or "").strip().lower()
    if not market:
        raise ValueError("market is required")
    idx = RunIndex(db_path=db_path)
    runs = idx.list_runs(limit=1, market=market)
    if not runs:
        raise ValueError(f"no runs found for market={market}")
    run_id = str(runs[0].get("id") or "").strip()
    if not run_id:
        raise ValueError(f"latest run row has no id for market={market}")
    return generate_backtest_report(run_id=run_id, project_root=project_root, db_path=db_path)
