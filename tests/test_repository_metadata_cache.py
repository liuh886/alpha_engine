from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from src.artifacts.repository_metadata_cache import rebuild_metadata_cache


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.name,
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "storage": "git",
    }


def test_rebuild_metadata_cache_uses_repository_as_one_way_source(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    model_path = root / "configs" / "models" / "us_x1_1.yaml"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(
        yaml.safe_dump(
            {
                "model_id": "us_x1_1",
                "display_name": "US x1.1",
                "release_date": "2026-08-02",
                "research_only": True,
                "trade_ready": False,
                "market": "us",
                "objective": "Repository cache test",
                "provider_binding": {
                    "canonical_evidence_provider_identity_sha256": "snapshot"
                },
                "model": {"family": "xgb"},
                "backtest_evidence": {
                    "development": {
                        "compounded_relative_excess_return": 0.5,
                        "worst_drawdown": -0.2,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    run_root = root / "data" / "research" / "runs" / "run-1"
    _write_json(
        run_root / "run.json",
        {
            "run_id": "run-1",
            "model_id": "us_x1_1",
            "market": "us",
            "benchmark": "QQQ",
            "data_snapshot_id": "snapshot",
            "generated_at": "2026-08-02T08:30:00+00:00",
            "research_only": True,
            "trade_ready": False,
        },
    )
    _write_json(
        run_root / "metrics.json",
        {"Total Return": 0.7, "Max Drawdown": -0.18},
    )
    _write_json(
        run_root / "equity_curve.json",
        {
            "run_id": "run-1",
            "points": [
                {
                    "date": "2026-01-02",
                    "nav": 1.0,
                    "drawdown": 0.0,
                    "turnover": 0.1,
                },
                {
                    "date": "2026-01-05",
                    "nav": 1.02,
                    "drawdown": 0.0,
                    "turnover": 0.0,
                },
            ],
        },
    )
    _write_json(
        run_root / "inventory.json",
        {
            "files": [
                _record(run_root / "run.json"),
                _record(run_root / "metrics.json"),
                _record(run_root / "equity_curve.json"),
            ]
        },
    )
    _write_json(
        root / "data" / "research" / "catalog.json",
        {
            "research_only": True,
            "trade_ready": False,
            "published_models": [
                {
                    "model_id": "us_x1_1",
                    "source": "configs/models/us_x1_1.yaml",
                    "primary_run_id": "run-1",
                }
            ],
            "published_runs": [
                {
                    "run_id": "run-1",
                    "source": "data/research/runs/run-1",
                }
            ],
        },
    )

    db_path = root / "artifacts" / "metadata" / "metadata.db"
    result = rebuild_metadata_cache(root=root, db_path=db_path)

    assert result["status"] == "rebuilt"
    assert result["source"] == "data/research"
    assert result["model_count"] == 1
    assert result["run_count"] == 1
    assert result["curve_point_count"] == 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        model = conn.execute("SELECT * FROM model_versions").fetchone()
        assert model is not None
        assert model["id"] == "us_x1_1"
        assert model["run_id"] == "run-1"
        assert json.loads(model["metrics_json"])["Total Return"] == 0.7
        points = conn.execute(
            "SELECT * FROM backtest_equity_curve ORDER BY date"
        ).fetchall()
        assert len(points) == 2
        assert points[-1]["nav"] == 1.02
        meta = {
            row["key"]: row["value"]
            for row in conn.execute("SELECT * FROM repository_cache_meta")
        }
        assert meta["source"] == "data/research"
        assert len(meta["catalog_sha256"]) == 64
    finally:
        conn.close()


def test_rebuild_metadata_cache_replaces_stale_database(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    model_path = root / "configs" / "models" / "model.yaml"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(
        yaml.safe_dump(
            {
                "model_id": "model",
                "research_only": True,
                "trade_ready": False,
                "market": "us",
                "provider_binding": {"provider_identity_sha256": "snapshot"},
                "model": {"family": "xgb"},
                "backtest_evidence": {"development": {"mean_icir": 0.1}},
            }
        ),
        encoding="utf-8",
    )
    _write_json(
        root / "data" / "research" / "catalog.json",
        {
            "research_only": True,
            "trade_ready": False,
            "published_models": [
                {"model_id": "model", "source": "configs/models/model.yaml"}
            ],
            "published_runs": [],
        },
    )
    db_path = root / "artifacts" / "metadata" / "metadata.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"stale-not-sqlite")

    rebuild_metadata_cache(root=root, db_path=db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM model_versions").fetchone()[0] == 1
    finally:
        conn.close()
