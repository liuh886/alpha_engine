from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.repository_research_store import (
    DEFAULT_CATALOG,
    RepositoryResearchStoreError,
    export_repository_research_data,
)
from src.data.model_data_bundle import build_model_data_bundle


def test_repository_export_publishes_named_models_without_metadata_db(tmp_path: Path) -> None:
    output = tmp_path / "site" / "data"

    manifest = export_repository_research_data(output, catalog_path=DEFAULT_CATALOG)

    models = json.loads((output / "models.json").read_text(encoding="utf-8"))
    assert [model["id"] for model in models] == [
        "cn_x1_0",
        "us_x1_0",
        "us_x1_1",
    ]
    assert all(model["params"]["research_only"] is True for model in models)
    assert all(model["params"]["trade_ready"] is False for model in models)
    assert all(model["snapshot_id"] for model in models)
    assert all(model["metrics"] for model in models)
    assert all(model["path"].startswith("docs/models/") for model in models)
    assert manifest["source"] == "repository_research_store"
    assert manifest["catalog_path"] == "data/repository-catalog.json"
    assert manifest["stats"]["total_models"] == 3
    assert "metadata_db_missing" not in manifest.get("blocked_gates", [])
    assert (output / "repository-catalog.json").is_file()
    assert (output.parent / "docs" / "models" / "us_x1_1.yaml").is_file()
    assert (output.parent / "docs" / "models" / "us_x1_0.yaml").is_file()
    assert (output.parent / "docs" / "models" / "cn_x1_0.yaml").is_file()


def test_repository_export_copies_declared_reports(tmp_path: Path) -> None:
    output = tmp_path / "site" / "data"

    manifest = export_repository_research_data(output, catalog_path=DEFAULT_CATALOG)

    reports = json.loads((output / "reports.json").read_text(encoding="utf-8"))
    assert manifest["stats"]["total_reports"] == len(reports) == 2
    for report in reports:
        assert report["static_path"] == report["static_html_path"]
        assert (output.parent / report["static_path"]).is_file()


def test_repository_catalog_rejects_invalid_boundary(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "research_only": False,
                "trade_ready": False,
                "published_models": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RepositoryResearchStoreError, match="invalid research boundary"):
        export_repository_research_data(tmp_path / "site" / "data", catalog_path=catalog)


def test_repository_export_publishes_verified_model_data_indexes(tmp_path: Path) -> None:
    model_data_root = tmp_path / "model-data"
    built = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=Path("configs/data_contracts/model_data_bundle_v1.yaml"),
        component_specs=[],
        output_root=model_data_root,
        evidence_cutoff="2026-07-31",
    )
    output = tmp_path / "site" / "data"

    manifest = export_repository_research_data(
        output,
        catalog_path=DEFAULT_CATALOG,
        model_data_root=model_data_root,
    )

    for name in (
        "model-data-readiness.json",
        "data-components.json",
        "training-profiles.json",
    ):
        assert (output / name).is_file()
    readiness = json.loads(
        (output / "model-data-readiness.json").read_text(encoding="utf-8")
    )
    assert readiness["bundle_id"] == built["bundle_id"]
    assert manifest["stats"]["model_data_components"] == 0
    assert "model_data_readiness_not_published" not in manifest["blocked_gates"]
