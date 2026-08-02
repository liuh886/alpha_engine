from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.artifacts import repository_research_store


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _inventory_record(path: Path) -> dict[str, object]:
    return {
        "path": path.name,
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "storage": "git",
    }


def test_exporter_validates_and_publishes_primary_repository_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    model_path = root / "configs" / "models" / "us_x1_1.yaml"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(
        yaml.safe_dump(
            {
                "model_id": "us_x1_1",
                "display_name": "US x1.1",
                "release_date": "2026-08-02",
                "status": "baseline_research_active",
                "research_only": True,
                "trade_ready": False,
                "market": "us",
                "benchmark": "QQQ",
                "objective": "Test model",
                "universe": {"universe_id": "us_selected_equities_v2"},
                "provider_binding": {
                    "canonical_evidence_provider_identity_sha256": "snapshot-1",
                    "cutoff": "2026-07-31",
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
    run = {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "model_id": "us_x1_1",
        "market": "us",
        "benchmark": "QQQ",
        "data_snapshot_id": "snapshot-1",
        "generated_at": "2026-08-02T08:30:00+00:00",
        "research_only": True,
        "trade_ready": False,
    }
    metrics = {"Total Return": 0.7, "Max Drawdown": -0.18}
    curve = {
        "run_id": "run-1",
        "points": [
            {"date": "2026-01-02", "nav": 1.0, "drawdown": 0.0},
            {"date": "2026-01-05", "nav": 1.02, "drawdown": 0.0},
        ],
    }
    _write_json(run_root / "run.json", run)
    _write_json(run_root / "metrics.json", metrics)
    _write_json(run_root / "equity_curve.json", curve)
    _write_json(
        run_root / "inventory.json",
        {
            "schema_version": "1.0.0",
            "files": [
                _inventory_record(run_root / "run.json"),
                _inventory_record(run_root / "metrics.json"),
                _inventory_record(run_root / "equity_curve.json"),
            ],
        },
    )

    catalog_path = root / "data" / "research" / "catalog.json"
    _write_json(
        catalog_path,
        {
            "schema_version": "1.0.0",
            "release_id": "test-release",
            "published_at": "2026-08-02T08:30:00+00:00",
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

    monkeypatch.setattr(repository_research_store, "PROJECT_ROOT", root)
    output = tmp_path / "site" / "data"
    manifest = repository_research_store.export_repository_research_data(
        output,
        catalog_path=catalog_path,
    )

    models = json.loads((output / "models.json").read_text(encoding="utf-8"))
    assert models[0]["run_id"] == "run-1"
    primary = models[0]["params"]["primary_repository_run"]
    assert primary["metrics"] == metrics
    assert primary["data_snapshot_id"] == "snapshot-1"
    assert (output / "runs" / "run-1" / "inventory.json").is_file()
    assert (output / "curves" / "run-1.json").is_file()
    assert manifest["stats"]["total_runs"] == 1
    assert manifest["blocked_gates"] == []


def test_exporter_rejects_tampered_published_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    run_root = root / "data" / "research" / "runs" / "run"
    _write_json(
        run_root / "run.json",
        {
            "run_id": "run",
            "model_id": "model",
            "market": "us",
            "benchmark": "QQQ",
            "data_snapshot_id": "snapshot",
            "generated_at": "2026-08-02T00:00:00+00:00",
            "research_only": True,
            "trade_ready": False,
        },
    )
    _write_json(run_root / "metrics.json", {"Total Return": 0.1})
    records = [
        _inventory_record(run_root / "run.json"),
        _inventory_record(run_root / "metrics.json"),
    ]
    _write_json(run_root / "inventory.json", {"files": records})
    _write_json(
        root / "data" / "research" / "catalog.json",
        {
            "research_only": True,
            "trade_ready": False,
            "published_models": [
                {
                    "model_id": "model",
                    "source": "configs/models/model.yaml",
                    "primary_run_id": "run",
                }
            ],
            "published_runs": [
                {"run_id": "run", "source": "data/research/runs/run"}
            ],
        },
    )
    (run_root / "metrics.json").write_text("{\"Total Return\": 999}\n", encoding="utf-8")

    monkeypatch.setattr(repository_research_store, "PROJECT_ROOT", root)
    try:
        repository_research_store.export_repository_research_data(
            tmp_path / "site" / "data",
            catalog_path=root / "data" / "research" / "catalog.json",
        )
    except repository_research_store.RepositoryResearchStoreError as exc:
        assert "hash mismatch" in str(exc) or "size mismatch" in str(exc)
    else:
        raise AssertionError("tampered run must be rejected")
