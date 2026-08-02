from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.artifacts.repository_run_store import (
    RepositoryRunStoreError,
    import_local_run,
)
from src.cli.main import main


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _seed_repo(root: Path) -> None:
    _write_json(
        root / "data" / "research" / "catalog.json",
        {
            "schema_version": "1.0.0",
            "published_at": "2026-08-02T00:00:00+00:00",
            "research_only": True,
            "trade_ready": False,
            "published_models": [
                {
                    "model_id": "us_x1_1",
                    "source": "configs/models/us_x1_1.yaml",
                }
            ],
            "published_runs": [],
        },
    )


def _seed_run(source: Path, *, run_id: str = "us-x1-1-2026h2-v1") -> None:
    _write_json(
        source / "run.json",
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "model_id": "us_x1_1",
            "run_type": "training_backtest",
            "market": "us",
            "benchmark": "QQQ",
            "universe_id": "us_selected_equities_v2",
            "data_snapshot_id": "sha256:provider-snapshot",
            "generated_at": "2026-08-02T08:30:00+00:00",
            "windows": {
                "train": ["2021-01-04", "2023-12-29"],
                "test": ["2024-01-02", "2025-12-31"],
            },
            "effective_parameters": {
                "family": "xgb",
                "objective": "rank:ndcg",
                "num_boost_round": 200,
                "seed": 42,
            },
            "costs": {"transaction_cost_bps": 20},
            "research_only": True,
            "trade_ready": False,
        },
    )
    _write_json(
        source / "metrics.json",
        {
            "Total Return": 1.1044,
            "Benchmark Return": 0.5520,
            "Excess Return": 0.5524,
            "Max Drawdown": -0.2715,
            "Sharpe Ratio": 1.42,
        },
    )
    _write_json(
        source / "equity_curve.json",
        {
            "run_id": run_id,
            "points": [
                {"date": "2024-01-02", "nav": 1.0, "drawdown": 0.0},
                {"date": "2024-01-03", "nav": 1.01, "drawdown": 0.0},
            ],
        },
    )


def test_import_run_writes_inventory_and_updates_catalog(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = tmp_path / "local-run"
    _seed_repo(root)
    _seed_run(source)

    result = import_local_run(
        source,
        root=root,
        publish=True,
        set_primary=True,
    )

    assert result["status"] == "imported"
    assert result["published"] is True
    destination = root / result["destination"]
    inventory = json.loads((destination / "inventory.json").read_text(encoding="utf-8"))
    records = {item["path"]: item for item in inventory["files"]}
    assert set(records) == {"run.json", "metrics.json", "equity_curve.json"}
    for name, record in records.items():
        path = destination / name
        assert record["byte_size"] == path.stat().st_size
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    catalog = json.loads(
        (root / "data" / "research" / "catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["published_runs"] == [
        {
            "run_id": "us-x1-1-2026h2-v1",
            "source": "data/research/runs/us-x1-1-2026h2-v1",
        }
    ]
    assert catalog["published_models"][0]["primary_run_id"] == "us-x1-1-2026h2-v1"


def test_import_run_is_idempotent_but_rejects_changed_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = tmp_path / "local-run"
    _seed_repo(root)
    _seed_run(source)

    first = import_local_run(source, root=root)
    second = import_local_run(source, root=root)
    assert first["status"] == "imported"
    assert second["status"] == "already_present"

    metrics = json.loads((source / "metrics.json").read_text(encoding="utf-8"))
    metrics["Total Return"] = 9.99
    _write_json(source / "metrics.json", metrics)
    with pytest.raises(RepositoryRunStoreError, match="different evidence"):
        import_local_run(source, root=root)


def test_import_run_rejects_unsafe_or_trade_ready_input(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = tmp_path / "local-run"
    _seed_repo(root)
    _seed_run(source)

    run = json.loads((source / "run.json").read_text(encoding="utf-8"))
    run["trade_ready"] = True
    _write_json(source / "run.json", run)
    with pytest.raises(RepositoryRunStoreError, match="research_only=true"):
        import_local_run(source, root=root)

    run["trade_ready"] = False
    _write_json(source / "run.json", run)
    (source / "unexpected.txt").write_text("not allowed", encoding="utf-8")
    with pytest.raises(RepositoryRunStoreError, match="unsupported run artifact"):
        import_local_run(source, root=root)


def test_import_run_cli_returns_blocked_payload_for_invalid_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    source = tmp_path / "missing-run"
    _seed_repo(root)

    code = main(
        [
            "--root",
            str(root),
            "research",
            "import-run",
            str(source),
        ]
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
