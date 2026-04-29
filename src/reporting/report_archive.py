from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from src.assistant.report_index import ReportIndex


def _resolve_under_root(path_str: str, *, project_root: Path) -> Path | None:
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = project_root / p
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p.absolute()
    root = project_root.resolve()
    try:
        if not resolved.is_relative_to(root):  # py311+
            return None
    except AttributeError:
        if str(root).lower() not in str(resolved).lower():
            return None
    return resolved


def export_reports_zip(
    *,
    project_root: str | Path,
    db_path: str | Path,
    type_filter: str = "all",
    limit: int = 100,
    output_path: str | Path | None = None,
) -> dict:
    project_root = Path(project_root)
    db_path = Path(db_path)

    type_filter = str(type_filter or "all").strip() or "all"
    limit = int(limit) if limit is not None else 100
    if limit <= 0:
        limit = 100

    idx = ReportIndex(db_path=db_path)
    report_type = None if type_filter == "all" else type_filter
    raw_rows = idx.list_reports(limit=limit, report_type=report_type)

    reports = []
    for r in raw_rows:
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        full = idx.get_report(rid)
        if not full:
            continue
        paths = full.get("paths") or {}
        if not isinstance(paths, dict):
            continue
        html_rel = str(paths.get("html") or "").strip()
        if not html_rel:
            continue
        src_path = _resolve_under_root(html_rel, project_root=project_root)
        if src_path is None or not src_path.exists():
            continue
        reports.append(
            {
                "id": rid,
                "type": full.get("type"),
                "ref_id": full.get("ref_id"),
                "date": full.get("date"),
                "paths": {"html": html_rel},
                "meta": full.get("meta") if isinstance(full.get("meta"), dict) else {},
            }
        )

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = (
        Path(output_path)
        if output_path
        else project_root / "artifacts" / "archives" / "reports" / f"reports_export_{ts}.zip"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "project_root": str(project_root),
            "filter": {"type": type_filter, "limit": limit},
            "reports": reports,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        for rep in reports:
            rel = str((rep.get("paths") or {}).get("html") or "").strip()
            src_path = _resolve_under_root(rel, project_root=project_root)
            if src_path is None or not src_path.exists():
                continue
            arcname = rel.replace("\\", "/").lstrip("/")
            try:
                zf.write(src_path, arcname=arcname)
                written += 1
            except Exception:
                continue

    out_rel = (
        str(out_path.relative_to(project_root)).replace("\\", "/")
        if out_path.is_relative_to(project_root)
        else str(out_path)
    )

    # Index the archive as a report row so the dashboard can discover it.
    try:
        idx.upsert(
            report_type="archive",
            ref_id=f"reports:{type_filter}",
            date=time.strftime("%Y-%m-%d %H:%M:%S"),
            formats=["zip"],
            paths={"zip": out_rel},
            meta={"included_reports": written, "filter": {"type": type_filter, "limit": limit}},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "output_path": str(out_path),
        "output_rel_path": out_rel,
        "included_reports": written,
        "listed_reports": len(reports),
    }
