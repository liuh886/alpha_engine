from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml


class RepositoryMetadataCacheError(ValueError):
    """Raised when the repository store cannot produce a trustworthy local cache."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryMetadataCacheError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise RepositoryMetadataCacheError(f"JSON root must be an object: {path}")
    return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RepositoryMetadataCacheError(f"invalid YAML file: {path}") from exc
    if not isinstance(payload, dict):
        raise RepositoryMetadataCacheError(f"YAML root must be a mapping: {path}")
    return payload


def _safe_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise RepositoryMetadataCacheError(f"unsafe repository path: {value}")
    resolved = (root / relative).resolve()
    if root not in resolved.parents:
        raise RepositoryMetadataCacheError(f"path escapes repository: {value}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evaluation_window(model: dict[str, Any]) -> dict[str, Any]:
    evidence = model.get("backtest_evidence") or {}
    if not isinstance(evidence, dict):
        return {}
    for key in ("frozen_challenge", "consumed_reporting_window"):
        value = evidence.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _model_metrics(model: dict[str, Any]) -> dict[str, Any]:
    evidence = model.get("backtest_evidence") or {}
    if not isinstance(evidence, dict):
        return {}
    development = evidence.get("development") or {}
    evaluation = _evaluation_window(model)
    metrics: dict[str, Any] = {}
    mappings = {
        "Compounded Strategy Return": (development, "compounded_strategy_return"),
        "Compounded Benchmark Return": (development, "compounded_benchmark_return"),
        "Compounded Relative Excess Return": (
            development,
            "compounded_relative_excess_return",
        ),
        "Mean ICIR": (development, "mean_icir"),
        "Mean Rank IC": (development, "mean_rank_ic"),
        "Development Worst Drawdown": (development, "worst_drawdown"),
        "Total Return": (evaluation, "total_return"),
        "Benchmark Return": (evaluation, "benchmark_return"),
        "Excess Return": (evaluation, "simple_excess_return"),
        "ICIR": (evaluation, "icir"),
        "Rank IC": (evaluation, "rank_ic"),
        "Max Drawdown": (evaluation, "max_drawdown"),
        "Turnover": (evaluation, "turnover"),
    }
    for label, (source, key) in mappings.items():
        if isinstance(source, dict):
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics[label] = float(value)
    return metrics


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE model_versions (
            id TEXT PRIMARY KEY,
            tag TEXT,
            name TEXT,
            market TEXT,
            model_type TEXT,
            path TEXT,
            run_id TEXT,
            created_at TEXT,
            stage TEXT DEFAULT 'CANDIDATE',
            description TEXT,
            params_json TEXT,
            metrics_json TEXT,
            feature_importance_json TEXT,
            payload_json TEXT,
            created_ts REAL
        );
        CREATE INDEX idx_model_versions_run_id ON model_versions(run_id);
        CREATE INDEX idx_model_versions_market ON model_versions(market);
        CREATE INDEX idx_model_versions_created_at ON model_versions(created_at);

        CREATE TABLE backtest_equity_curve (
            backtest_run_id TEXT NOT NULL,
            date TEXT NOT NULL,
            nav REAL,
            drawdown REAL,
            turnover REAL,
            created_at REAL,
            PRIMARY KEY (backtest_run_id, date)
        );
        CREATE INDEX idx_bt_curve_run_date
            ON backtest_equity_curve(backtest_run_id, date);

        CREATE TABLE reports (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            date TEXT,
            formats_json TEXT,
            paths_json TEXT,
            meta_json TEXT,
            created_ts REAL,
            updated_ts REAL
        );
        CREATE INDEX idx_reports_type_date ON reports(type, date);
        CREATE INDEX idx_reports_ref_id ON reports(ref_id);

        CREATE TABLE repository_cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _published_runs(root: Path, catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = catalog.get("published_runs", [])
    if not isinstance(entries, list):
        raise RepositoryMetadataCacheError("catalog published_runs must be a list")
    runs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise RepositoryMetadataCacheError("published run entry must be an object")
        run_id = str(entry.get("run_id") or "")
        run_root = _safe_path(root, str(entry.get("source") or ""))
        run = _read_json(run_root / "run.json")
        metrics = _read_json(run_root / "metrics.json")
        inventory = _read_json(run_root / "inventory.json")
        if str(run.get("run_id") or "") != run_id:
            raise RepositoryMetadataCacheError(f"catalog/run ID mismatch: {run_id}")
        if run.get("research_only") is not True or run.get("trade_ready") is not False:
            raise RepositoryMetadataCacheError(f"invalid run boundary: {run_id}")
        for record in inventory.get("files", []):
            if not isinstance(record, dict):
                raise RepositoryMetadataCacheError(f"invalid inventory record: {run_id}")
            artifact = run_root / str(record.get("path") or "")
            if not artifact.is_file():
                raise RepositoryMetadataCacheError(
                    f"repository run artifact is missing: {run_id}/{artifact.name}"
                )
            if artifact.stat().st_size != int(record.get("byte_size", -1)):
                raise RepositoryMetadataCacheError(
                    f"repository run artifact size mismatch: {run_id}/{artifact.name}"
                )
            if _sha256(artifact) != str(record.get("sha256") or ""):
                raise RepositoryMetadataCacheError(
                    f"repository run artifact hash mismatch: {run_id}/{artifact.name}"
                )
        runs[run_id] = {
            "root": run_root,
            "run": run,
            "metrics": metrics,
        }
    return runs


def _insert_models(
    conn: sqlite3.Connection,
    *,
    root: Path,
    catalog: dict[str, Any],
    runs: dict[str, dict[str, Any]],
) -> int:
    entries = catalog.get("published_models")
    if not isinstance(entries, list) or not entries:
        raise RepositoryMetadataCacheError("catalog publishes no models")
    now = time.time()
    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise RepositoryMetadataCacheError("published model entry must be an object")
        model_id = str(entry.get("model_id") or "")
        source = str(entry.get("source") or "")
        model = _read_yaml(_safe_path(root, source))
        if str(model.get("model_id") or "") != model_id:
            raise RepositoryMetadataCacheError(f"catalog/model ID mismatch: {model_id}")
        if model.get("research_only") is not True or model.get("trade_ready") is not False:
            raise RepositoryMetadataCacheError(f"invalid model boundary: {model_id}")
        primary_run_id = str(entry.get("primary_run_id") or "")
        primary_run = runs.get(primary_run_id) if primary_run_id else None
        if primary_run_id and primary_run is None:
            raise RepositoryMetadataCacheError(
                f"primary run is not published for model {model_id}: {primary_run_id}"
            )
        if primary_run and str(primary_run["run"].get("model_id") or "") != model_id:
            raise RepositoryMetadataCacheError(
                f"primary run/model mismatch: {primary_run_id} != {model_id}"
            )
        evidence = model.get("evidence_identity") or {}
        run_id = primary_run_id or str(
            evidence.get("workflow_run_id") or evidence.get("artifact_id") or model_id
        )
        metrics = primary_run["metrics"] if primary_run else _model_metrics(model)
        runtime = model.get("model") or {}
        params = {
            "repository_source": source,
            "universe": model.get("universe") or {},
            "provider_binding": model.get("provider_binding") or {},
            "features": model.get("features") or {},
            "label": model.get("label") or {},
            "model": runtime,
            "strategy": model.get("strategy") or {},
            "primary_run_id": primary_run_id or None,
            "research_only": True,
            "trade_ready": False,
        }
        conn.execute(
            """
            INSERT INTO model_versions (
                id, tag, name, market, model_type, path, run_id, created_at,
                stage, description, params_json, metrics_json,
                feature_importance_json, payload_json, created_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_id,
                str(model.get("display_name") or model_id),
                str(model.get("display_name") or model_id),
                str(model.get("market") or ""),
                str(runtime.get("family") or ""),
                source,
                run_id,
                str(model.get("release_date") or ""),
                "CANDIDATE",
                str(model.get("objective") or ""),
                json.dumps(params, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False),
                "{}",
                json.dumps({"repository_model": model}, ensure_ascii=False),
                now,
            ),
        )
        count += 1
    return count


def _insert_runs(
    conn: sqlite3.Connection,
    runs: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    curve_points = 0
    reports = 0
    now = time.time()
    for run_id, evidence in runs.items():
        run_root = evidence["root"]
        curve_path = run_root / "equity_curve.json"
        if curve_path.is_file():
            curve = _read_json(curve_path)
            points = curve.get("points")
            if not isinstance(points, list):
                raise RepositoryMetadataCacheError(
                    f"equity curve points are invalid: {run_id}"
                )
            for point in points:
                if not isinstance(point, dict):
                    continue
                date = str(point.get("date") or "")
                nav = point.get("nav")
                if not date or not isinstance(nav, (int, float)):
                    continue
                conn.execute(
                    """
                    INSERT INTO backtest_equity_curve (
                        backtest_run_id, date, nav, drawdown, turnover, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        date,
                        float(nav),
                        float(point["drawdown"])
                        if isinstance(point.get("drawdown"), (int, float))
                        else None,
                        float(point["turnover"])
                        if isinstance(point.get("turnover"), (int, float))
                        else None,
                        now,
                    ),
                )
                curve_points += 1
        attribution_path = run_root / "attribution.json"
        if attribution_path.is_file():
            report_id = hashlib.sha1(f"attribution\n{run_id}".encode()).hexdigest()
            conn.execute(
                """
                INSERT INTO reports (
                    id, type, ref_id, date, formats_json, paths_json,
                    meta_json, created_ts, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    "attribution",
                    run_id,
                    str(evidence["run"].get("generated_at") or "")[:10],
                    '["json"]',
                    json.dumps(
                        {
                            "json": str(
                                attribution_path.relative_to(run_root.parents[3]).as_posix()
                            )
                        }
                    ),
                    json.dumps({"source": "repository_research_store"}),
                    now,
                    now,
                ),
            )
            reports += 1
    return curve_points, reports


def rebuild_metadata_cache(
    *,
    root: Path,
    db_path: Path,
) -> dict[str, Any]:
    """Atomically rebuild the local SQLite query cache from Git-tracked evidence."""

    root = root.resolve()
    catalog_path = root / "data" / "research" / "catalog.json"
    catalog = _read_json(catalog_path)
    if catalog.get("research_only") is not True or catalog.get("trade_ready") is not False:
        raise RepositoryMetadataCacheError("repository catalog has an invalid boundary")
    runs = _published_runs(root, catalog)

    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{db_path.name}.",
        suffix=".tmp",
        dir=db_path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        conn = sqlite3.connect(temporary)
        try:
            _ensure_schema(conn)
            model_count = _insert_models(conn, root=root, catalog=catalog, runs=runs)
            curve_count, report_count = _insert_runs(conn, runs)
            conn.execute(
                "INSERT INTO repository_cache_meta (key, value) VALUES (?, ?)",
                ("catalog_sha256", _sha256(catalog_path)),
            )
            conn.execute(
                "INSERT INTO repository_cache_meta (key, value) VALUES (?, ?)",
                ("source", "data/research"),
            )
            conn.execute(
                "INSERT INTO repository_cache_meta (key, value) VALUES (?, ?)",
                ("rebuilt_at", str(time.time())),
            )
            conn.commit()
        finally:
            conn.close()
        os.replace(temporary, db_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "status": "rebuilt",
        "source": "data/research",
        "db_path": str(db_path),
        "model_count": model_count,
        "run_count": len(runs),
        "curve_point_count": curve_count,
        "report_count": report_count,
        "research_only": True,
        "trade_ready": False,
    }
