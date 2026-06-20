from __future__ import annotations

import json
import sqlite3

from src.research.evidence import EvidenceLedger


def test_research_run_bundle_reads_existing_artifact(tmp_path):
    run_id = "rr_test"
    runs_dir = tmp_path / "research_runs"
    runs_dir.mkdir()
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "market": "us",
                "goal": "smoke",
                "status": "completed",
                "recommendation": "promote",
                "created_at": "2026-06-19T10:00:00",
                "completed_at": "2026-06-19T10:01:00",
                "total_duration_seconds": 60,
                "steps": [
                    {
                        "name": "factor_scan",
                        "status": "completed",
                        "output": {"active_factors": 2},
                    }
                ],
                "n_steps": 1,
                "n_completed": 1,
                "n_failed": 0,
            }
        ),
        encoding="utf-8",
    )

    ledger = EvidenceLedger(artifacts_dir=tmp_path)
    bundle = ledger.from_research_run(run_id)

    assert bundle.subject_type == "research_run"
    assert bundle.subject_id == run_id
    assert bundle.sources[0].status.value == "found"
    assert bundle.metrics["status"] == "completed"
    assert bundle.metrics["market"] == "us"
    assert bundle.decision == "promote"
    assert bundle.warnings == []
    assert bundle.completeness_score == 1.0
    json.dumps(bundle.to_dict())
    json.dumps(ledger.to_dict())


def test_research_run_bundle_handles_missing_artifact(tmp_path):
    ledger = EvidenceLedger(artifacts_dir=tmp_path)

    bundle = ledger.build_bundle("research_run", "missing_run")

    assert bundle.subject_type == "research_run"
    assert bundle.sources[0].status.value == "missing"
    assert bundle.metrics == {}
    assert bundle.decision == "missing_artifact"
    assert "not found" in bundle.warnings[0]
    assert bundle.completeness_score == 0.0
    json.dumps(bundle.to_dict())


# ---------------------------------------------------------------------------
# H5: Runtime observability — evidence/provenance tracing
# ---------------------------------------------------------------------------


def test_research_run_bundle_has_provenance_fields(tmp_path):
    """Evidence bundle must expose subject_type, subject_id, and generated_at for tracing."""
    run_id = "rr_provenance"
    runs_dir = tmp_path / "research_runs"
    runs_dir.mkdir()
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps({
            "run_id": run_id,
            "market": "cn",
            "goal": "provenance test",
            "status": "completed",
            "recommendation": "deploy",
            "created_at": "2026-06-19T10:00:00",
            "completed_at": "2026-06-19T10:05:00",
            "total_duration_seconds": 300,
            "steps": [
                {"name": "train", "status": "completed", "output": {"ic": 0.05}},
                {"name": "walk_forward", "status": "completed", "output": {"mean_ic": 0.04}},
            ],
            "n_steps": 2,
            "n_completed": 2,
            "n_failed": 0,
        }),
        encoding="utf-8",
    )

    ledger = EvidenceLedger(artifacts_dir=tmp_path)
    bundle = ledger.from_research_run(run_id)

    # Provenance fields must exist
    assert bundle.subject_type == "research_run"
    assert bundle.subject_id == run_id
    assert bundle.generated_at  # non-empty timestamp

    # Must trace back to the artifact
    assert any(s.name == "research_run_artifact" and s.status.value == "found" for s in bundle.sources)

    # Must include step metrics
    assert bundle.metrics.get("n_steps") == 2
    assert bundle.decision == "deploy"


def test_missing_evidence_returns_explicit_status(tmp_path):
    """Missing evidence must return explicit missing status, not crash."""
    ledger = EvidenceLedger(artifacts_dir=tmp_path)
    bundle = ledger.build_bundle("model", "nonexistent_model_123")

    assert bundle.subject_type == "model"
    assert bundle.subject_id == "nonexistent_model_123"
    assert bundle.completeness_score == 0.0
    assert bundle.decision == "missing_artifact"
    assert len(bundle.warnings) > 0
    assert any("not found" in w.lower() for w in bundle.warnings)


def test_factor_bundle_reads_registry_and_warns_missing_artifact(tmp_path):
    db_path = tmp_path / "factor_registry.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE factors (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                expression TEXT NOT NULL,
                category TEXT,
                direction TEXT,
                lookback_days INTEGER,
                thesis TEXT,
                stage TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE factor_validations (
                id INTEGER PRIMARY KEY,
                factor_id INTEGER NOT NULL,
                market TEXT NOT NULL,
                ic REAL,
                rank_ic REAL,
                icir REAL,
                t_stat REAL,
                positive_ratio REAL,
                mean_decay_1d REAL,
                mean_decay_5d REAL,
                quintile_spread REAL,
                passed INTEGER,
                validated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE factor_usage (
                id INTEGER PRIMARY KEY,
                factor_id INTEGER NOT NULL,
                strategy_config TEXT,
                weight REAL,
                added_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO factors
                (id, name, expression, category, direction, lookback_days, thesis, stage, created_at, updated_at)
            VALUES
                (1, 'momentum_10d', 'Ref($close, -10) / $close - 1', 'momentum', 'long', 10,
                 '10 day momentum', 'Validated', '2026-06-19T10:00:00', '2026-06-19T10:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO factor_validations
                (id, factor_id, market, ic, rank_ic, icir, t_stat, positive_ratio,
                 mean_decay_1d, mean_decay_5d, quintile_spread, passed, validated_at)
            VALUES
                (1, 1, 'us', 0.03, 0.04, 0.8, 2.1, 0.62, 0.03, 0.02, 0.004, 1,
                 '2026-06-19T10:02:00')
            """
        )

    ledger = EvidenceLedger(artifacts_dir=tmp_path, factor_db_path=db_path)
    bundle = ledger.from_factor("momentum_10d", market="us")

    assert bundle.subject_type == "factor"
    assert bundle.metrics["factor"]["name"] == "momentum_10d"
    assert bundle.metrics["latest_validation"]["passed"] == 1
    assert bundle.decision == "Validated"
    assert any("Factor artifact not found" in warning for warning in bundle.warnings)
    assert json.loads(json.dumps(bundle.to_dict()))["sources"][0]["status"] == "missing"


def test_model_bundle_reads_model_registry_yaml(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "model_list.yaml").write_text(
        """
models:
  - id: model_v1
    market: us
    stage: RECOMMENDED
    run_id: run_123
    walk_forward:
      gate_passed: true
""",
        encoding="utf-8",
    )

    ledger = EvidenceLedger(artifacts_dir=tmp_path)
    bundle = ledger.build_bundle("model", "model_v1")

    assert bundle.subject_type == "model"
    assert bundle.subject_id == "model_v1"
    assert bundle.sources[0].name == "model_registry"
    assert bundle.sources[0].status.value == "found"
    assert bundle.metrics["model"]["market"] == "us"
    assert bundle.decision == "RECOMMENDED"
    json.dumps(bundle.to_dict())
