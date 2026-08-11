from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest
from src.artifacts.model_run_exporter import (
    ModelRunExportError,
    export_from_adapter,
    registered_adapters,
)

FIXTURE_ROOT = Path("tests/fixtures/model_run_bundle_v2/adapter_inputs")


def _export(tmp_path: Path, fixture: str, *, catalog: bool = True) -> Path:
    output = tmp_path / "model_runs" / "bundles"
    catalog_path = tmp_path / "model_runs" / "catalog.json" if catalog else None
    return export_from_adapter(
        adapter_id="declarative_json_v1",
        source=FIXTURE_ROOT / fixture,
        output_root=output,
        catalog_path=catalog_path,
    )


def test_registry_exposes_reference_adapter() -> None:
    assert registered_adapters() == ("declarative_json_v1",)


@pytest.mark.parametrize(
    ("fixture", "model_kind"),
    [
        ("rules_based_allocation.json", "rules_based_allocation"),
        ("cross_sectional_ranker.json", "cross_sectional_ranker"),
        ("forecast_model.json", "forecast_model"),
    ],
)
def test_each_model_kind_exports_through_generic_path(
    tmp_path: Path, fixture: str, model_kind: str
) -> None:
    manifest_path = _export(tmp_path, fixture)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    assert manifest["model_kind"] == model_kind
    assert manifest["research_only"] is True
    assert manifest["trade_ready"] is False
    catalog = json.loads(
        (tmp_path / "model_runs" / "catalog.json").read_text(encoding="utf-8")
    )
    validate_catalog(catalog)
    assert catalog["channel"] == "preview"
    assert catalog["records"][0]["bundle_id"] == manifest["bundle_id"]


def test_byte_identical_inputs_are_idempotent(tmp_path: Path) -> None:
    first = _export(tmp_path, "cross_sectional_ranker.json")
    before = {
        path.relative_to(first.parent): path.read_bytes()
        for path in first.parent.rglob("*")
        if path.is_file()
    }
    second = _export(tmp_path, "cross_sectional_ranker.json")
    after = {
        path.relative_to(second.parent): path.read_bytes()
        for path in second.parent.rglob("*")
        if path.is_file()
    }
    assert first == second
    assert before == after
    assert not list(first.parent.parent.glob(f".{first.parent.name}.*"))


def test_changed_content_cannot_reuse_immutable_run_identity(tmp_path: Path) -> None:
    source = json.loads(
        (FIXTURE_ROOT / "cross_sectional_ranker.json").read_text(encoding="utf-8")
    )
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    output = tmp_path / "bundles"
    export_from_adapter(
        adapter_id="declarative_json_v1",
        source=source_path,
        output_root=output,
    )
    source["sections"][0]["payload"]["metrics"][0]["value"] = 0.99
    source_path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ModelRunExportError, match="immutable run identity collision"):
        export_from_adapter(
            adapter_id="declarative_json_v1",
            source=source_path,
            output_root=output,
        )


def test_preview_catalog_rejects_formal_record(tmp_path: Path) -> None:
    source = json.loads(
        (FIXTURE_ROOT / "cross_sectional_ranker.json").read_text(encoding="utf-8")
    )
    source.update(
        publication_channel="formal",
        publication_status="accepted_formal_baseline",
    )
    source_path = tmp_path / "formal.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    output = tmp_path / "model_runs" / "bundles"
    manifest = export_from_adapter(
        adapter_id="declarative_json_v1",
        source=source_path,
        output_root=output,
    )
    with pytest.raises(ModelRunExportError, match="cannot contain formal bundle"):
        from src.artifacts.model_run_exporter import update_catalog

        update_catalog(
            [manifest],
            catalog_path=tmp_path / "model_runs" / "catalog.json",
            channel="preview",
        )


def test_required_unavailable_section_keeps_machine_blocker(tmp_path: Path) -> None:
    manifest_path = _export(tmp_path, "forecast_model.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    performance = next(
        row for row in manifest["sections"] if row["section_id"] == "performance"
    )
    assert performance["availability_status"] == "not_applicable"
    assert performance["reason"]
    assert performance["path"] is None
