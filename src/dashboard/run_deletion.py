from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

import yaml

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _is_safe_id(value: str) -> bool:
    value = str(value or "")
    if not _SAFE_ID_RE.match(value):
        return False
    if ".." in value:
        return False
    if "/" in value or "\\" in value:
        return False
    return True


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


def _safe_rmtree(path: Path, *, retries: int = 3, backoff_s: float = 0.2) -> None:
    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            raise

    for attempt in range(int(retries)):
        try:
            shutil.rmtree(path, ignore_errors=False, onerror=_onerror)
            return
        except Exception:
            if attempt >= int(retries) - 1:
                raise
            time.sleep(float(backoff_s) * float(attempt + 1))


def _delete_run_dirs(run_id: str, *, mlruns_root: Path) -> bool:
    deleted_any = False
    if not mlruns_root.exists():
        return False
    for exp_dir in mlruns_root.iterdir():
        if not exp_dir.is_dir():
            continue
        candidate = exp_dir / run_id
        if not candidate.exists():
            continue
        _safe_rmtree(candidate)
        deleted_any = True
    return deleted_any


def _remove_run_from_dashboard_json(run_id: str, *, dashboard_json_path: Path) -> bool:
    if not dashboard_json_path.exists():
        return False
    data = json.loads(dashboard_json_path.read_text(encoding="utf-8"))
    models = data.get("models", [])
    if not isinstance(models, list):
        return False
    before = len(models)
    models = [m for m in models if isinstance(m, dict) and str(m.get("id")) != str(run_id)]
    if len(models) == before:
        return False
    data["models"] = models
    dashboard_json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _remove_models_for_run(run_id: str, *, model_list_path: Path, project_root: Path) -> bool:
    if not model_list_path.exists():
        return False

    data = yaml.safe_load(model_list_path.read_text(encoding="utf-8")) or {}
    models = data.get("models", [])
    if not isinstance(models, list):
        return False

    kept: list[dict] = []
    deleted_any = False
    for entry in models:
        if not isinstance(entry, dict) or str(entry.get("run_id")) != str(run_id):
            kept.append(entry)
            continue

        deleted_any = True
        resolved = _resolve_under_root(str(entry.get("path") or ""), project_root=project_root)
        if resolved is None or not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved, ignore_errors=False)
        else:
            resolved.unlink(missing_ok=True)

    if len(kept) != len(models):
        data["models"] = kept
        model_list_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        deleted_any = True

    return deleted_any


def _remove_run_from_metadata_db(run_id: str, *, project_root: Path) -> bool:
    try:
        from src.assistant.arena_index import ArenaIndex
        from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
        from src.assistant.metadata_db import resolve_metadata_db_path
        from src.assistant.model_registry_index import ModelRegistryIndex
        from src.assistant.report_index import ReportIndex
        from src.assistant.run_index import RunIndex

        db_path = resolve_metadata_db_path(project_root)
        deleted_run = RunIndex(db_path=db_path).delete_run(run_id)
        deleted_curve = BacktestEquityCurveIndex(db_path=db_path).delete_curve(run_id)
        deleted_models = ModelRegistryIndex(db_path=db_path).delete_versions_for_run(run_id)
        deleted_arena = ArenaIndex(db_path=db_path).delete_participants_for_run(run_id)
        deleted_reports = (
            ReportIndex(db_path=db_path).delete_reports_for_ref(
                ref_id=run_id, report_type="backtest"
            )
            > 0
        )

        deleted_report_files = False
        try:
            reports_root = Path(project_root) / "reports" / "backtests"
            if reports_root.exists():
                for market_dir in reports_root.iterdir():
                    if not market_dir.is_dir():
                        continue
                    candidate = market_dir / run_id
                    if candidate.exists():
                        _safe_rmtree(candidate)
                        deleted_report_files = True
        except Exception:
            deleted_report_files = False

        return bool(
            deleted_run
            or deleted_curve
            or deleted_models
            or deleted_arena
            or deleted_reports
            or deleted_report_files
        )
    except Exception:
        return False


def delete_backtest_run(
    run_id: str,
    *,
    mlruns_root: Path,
    dashboard_json_path: Path,
    model_list_path: Path | None = None,
    project_root: Path | None = None,
) -> bool:
    """
    Hard-delete a backtest run from the local filesystem + dashboard index.

    - Deletes `mlruns/**/<run_id>/`
    - Removes the corresponding entry from the dashboard JSON (by matching `models[].id`)
    - Optionally removes matching models from `models/model_list.yaml` (by matching `models[].run_id`)
      and deletes the referenced model files.
    """
    run_id = str(run_id)
    if not _is_safe_id(run_id):
        return False

    deleted_dirs = _delete_run_dirs(run_id, mlruns_root=Path(mlruns_root))
    deleted_json = _remove_run_from_dashboard_json(
        run_id, dashboard_json_path=Path(dashboard_json_path)
    )
    deleted_models = False
    if model_list_path is not None:
        model_list_path = Path(model_list_path)
        if project_root is None:
            project_root = model_list_path.parent.parent
        deleted_models = _remove_models_for_run(
            run_id,
            model_list_path=model_list_path,
            project_root=Path(project_root),
        )
    deleted_db = False
    if project_root is not None:
        deleted_db = _remove_run_from_metadata_db(run_id, project_root=Path(project_root))
    return bool(deleted_dirs or deleted_json or deleted_models or deleted_db)
