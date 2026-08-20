from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.data.selected_pool_event_population as event_population
from src.data.corporate_actions.event_store import normalize_corporate_action
from src.data.fundamentals.event_store import normalize_event_record
from src.data.selected_pool_event_population import (
    MEMBER_PATHS,
    SelectedPoolEventPopulationError,
    SymbolPopulation,
    publish_selected_pool_event_bundle,
    verify_selected_pool_event_bundle,
)


def _fundamental(symbol: str, *, available_at: str = "2026-02-02T00:00:00+00:00"):
    return normalize_event_record(
        {
            "market": "us",
            "symbol": symbol,
            "exchange": "US",
            "entity_id": f"CIK:{symbol}",
            "fiscal_period_end": "2025-12-31",
            "fiscal_year": 2025,
            "fiscal_period": "FY",
            "reported_at": "2026-02-01T00:00:00+00:00",
            "available_at": available_at,
            "filing_type": "10-K",
            "source_provider": "sec_companyfacts",
            "source_document_id": f"filing:{symbol}",
            "source_endpoint": "companyfacts",
            "field": "revenue",
            "value": 100.0,
            "unit": "USD",
            "currency": "USD",
            "is_quarterly": False,
            "is_derived": False,
            "derivation_rule": "",
            "revision_sequence": 0,
            "supersedes_event_id": "",
            "retrieved_at": "2026-08-02T00:00:00+00:00",
            "source_hash": "a" * 64,
        }
    )


def _action(
    symbol: str,
    *,
    announced_at: str = "2026-03-01T00:00:00+00:00",
    effective_date: str = "2026-03-05",
):
    return normalize_corporate_action(
        {
            "market": "us",
            "symbol": symbol,
            "exchange": "US",
            "entity_id": f"CIK:{symbol}",
            "event_type": "cash_dividend",
            "announced_at": announced_at,
            "ex_date": effective_date,
            "record_date": "",
            "pay_date": "",
            "effective_date": effective_date,
            "cash_amount": 0.5,
            "currency": "USD",
            "split_ratio": None,
            "stock_dividend_ratio": None,
            "rights_ratio": None,
            "rights_price": None,
            "shares_before": None,
            "shares_after": None,
            "old_symbol": "",
            "new_symbol": "",
            "source_provider": "yfinance_actions",
            "source_document_id": f"action:{symbol}",
            "source_endpoint": "Ticker.actions",
            "retrieved_at": "2026-08-02T00:00:00+00:00",
            "source_hash": "b" * 64,
            "revision_sequence": 0,
            "supersedes_event_id": "",
            "confidence": 0.8,
            "reconciliation_status": "source_only",
        }
    )


def test_builds_direct_components_and_explicit_symbol_statuses(tmp_path: Path) -> None:
    symbols = ["AAA", "BBB"]
    fundamentals = {
        "AAA": SymbolPopulation("AAA", "ready", [_fundamental("AAA")], ["sec_companyfacts"]),
        "BBB": SymbolPopulation("BBB", "partial", [], ["sec_companyfacts"]),
    }
    actions = {
        "AAA": SymbolPopulation("AAA", "ready", [_action("AAA")], ["yfinance_actions"]),
        "BBB": SymbolPopulation("BBB", "no_event_observed", [], ["yfinance_actions"]),
    }
    manifest = publish_selected_pool_event_bundle(
        market="us",
        pool_id="fixture_pool",
        symbols=symbols,
        fundamentals=fundamentals,
        corporate_actions=actions,
        evidence_cutoff="2026-07-31",
        output_root=tmp_path,
        evidence_class="contract_fixture",
    )
    assert manifest["schema_version"] == "2.0"
    assert manifest["evidence_class"] == "contract_fixture"
    assert manifest["publication_eligible"] is False
    assert manifest["symbols"] == symbols
    assert [row["path"] for row in manifest["files"]] == list(MEMBER_PATHS)
    assert [row["component_kind"] for row in manifest["components"]] == [
        "corporate_action_coverage",
        "fundamental_coverage",
    ]
    assert "fundamental_component" not in manifest
    assert len(manifest["bundle_id"]) == 64
    assert manifest["expected_symbol_count"] == 2
    fundamental = json.loads(
        (tmp_path / "fundamentals/component_manifest.json").read_text(encoding="utf-8")
    )
    corporate = json.loads(
        (tmp_path / "corporate_actions/component_manifest.json").read_text(encoding="utf-8")
    )
    assert fundamental["status"] == "partial"
    assert fundamental["ready_symbol_count"] == 1
    assert corporate["status"] == "ready"
    assert corporate["ready_symbol_count"] == 2
    assert corporate["details"]["status_counts"]["no_event_observed"] == 1
    assert fundamental["details"]["events_path"] == "fundamentals/events.jsonl"
    assert fundamental["details"]["coverage_path"] == "fundamentals/coverage.json"
    assert (tmp_path / "fundamentals/events.jsonl").read_text().count("\n") == 1
    assert verify_selected_pool_event_bundle(
        tmp_path,
        expected_market="us",
        expected_pool_id="fixture_pool",
        expected_symbols=symbols,
        expected_cutoff="2026-07-31",
    ) == manifest


def test_fails_when_any_selected_symbol_has_no_explicit_status(tmp_path: Path) -> None:
    populations = {
        "AAA": SymbolPopulation("AAA", "partial", [], ["fixture"]),
    }
    with pytest.raises(SelectedPoolEventPopulationError, match="missing=\['BBB'\]"):
        publish_selected_pool_event_bundle(
            market="us",
            pool_id="fixture_pool",
            symbols=["AAA", "BBB"],
            fundamentals=populations,
            corporate_actions=populations,
            evidence_cutoff="2026-07-31",
            output_root=tmp_path,
            evidence_class="contract_fixture",
        )


def test_source_bound_publication_requires_exact_governance_bindings(tmp_path: Path) -> None:
    populations = {"AAA": SymbolPopulation("AAA", "partial", [], ["fixture"])}

    with pytest.raises(SelectedPoolEventPopulationError, match="requires exact governance"):
        publish_selected_pool_event_bundle(
            market="us",
            pool_id="fixture_pool",
            symbols=["AAA"],
            fundamentals=populations,
            corporate_actions=populations,
            evidence_cutoff="2026-07-31",
            output_root=tmp_path,
        )


def test_filters_events_by_knowledge_date_without_dropping_preannounced_action(
    tmp_path: Path,
) -> None:
    fundamentals = {
        "AAA": SymbolPopulation(
            "AAA",
            "ready",
            [_fundamental("AAA", available_at="2026-08-01T00:00:00+00:00")],
            ["sec_companyfacts"],
        )
    }
    actions = {
        "AAA": SymbolPopulation(
            "AAA",
            "ready",
            [
                _action(
                    "AAA",
                    announced_at="2026-07-24T00:00:00+00:00",
                    effective_date="2026-08-03",
                ),
                _action(
                    "AAA",
                    announced_at="2026-08-01T00:00:00+00:00",
                    effective_date="2026-08-07",
                ),
            ],
            ["yfinance_actions"],
        )
    }
    manifest = publish_selected_pool_event_bundle(
        market="us",
        pool_id="fixture_pool",
        symbols=["AAA"],
        fundamentals=fundamentals,
        corporate_actions=actions,
        evidence_cutoff="2026-07-31",
        output_root=tmp_path,
        evidence_class="contract_fixture",
    )

    assert manifest["cutoff_filter"] == {
        "availability_policy": (
            "fundamentals.available_at; corporate_actions.announced_at_or_effective_date"
        ),
        "fundamental_events_excluded": 1,
        "corporate_action_events_excluded": 1,
    }
    assert (tmp_path / "fundamentals/events.jsonl").read_text() == ""
    action_rows = [
        json.loads(line)
        for line in (tmp_path / "corporate_actions/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["effective_date"] for row in action_rows] == ["2026-08-03"]
    coverage = json.loads(
        (tmp_path / "corporate_actions/coverage.json").read_text(encoding="utf-8")
    )
    assert coverage[0]["latest_event_date"] == "2026-07-24"
    assert coverage[0]["latest_effective_date"] == "2026-08-03"
    assert coverage[0]["excluded_after_cutoff"] == 1


def _build_fixture_bundle(output: Path) -> dict[str, object]:
    fundamentals = {
        "AAA": SymbolPopulation("AAA", "ready", [_fundamental("AAA")], ["sec_companyfacts"]),
        "BBB": SymbolPopulation("BBB", "partial", [], ["sec_companyfacts"]),
    }
    actions = {
        "AAA": SymbolPopulation("AAA", "ready", [_action("AAA")], ["yfinance_actions"]),
        "BBB": SymbolPopulation("BBB", "no_event_observed", [], ["yfinance_actions"]),
    }
    return publish_selected_pool_event_bundle(
        market="us",
        pool_id="fixture_pool",
        symbols=["AAA", "BBB"],
        fundamentals=fundamentals,
        corporate_actions=actions,
        evidence_cutoff="2026-07-31",
        output_root=output,
        evidence_class="contract_fixture",
    )


@pytest.mark.parametrize("relative", MEMBER_PATHS)
def test_verifier_rejects_every_tampered_member(tmp_path: Path, relative: str) -> None:
    _build_fixture_bundle(tmp_path)
    member = tmp_path / relative
    member.write_bytes(member.read_bytes() + b" ")

    with pytest.raises(SelectedPoolEventPopulationError, match="member binding mismatch"):
        verify_selected_pool_event_bundle(tmp_path)


def test_verifier_rejects_missing_and_extra_bundle_members(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    _build_fixture_bundle(missing_root)
    (missing_root / "fundamentals/events.jsonl").unlink()
    with pytest.raises(SelectedPoolEventPopulationError, match="file closure mismatch"):
        verify_selected_pool_event_bundle(missing_root)

    extra_root = tmp_path / "extra"
    _build_fixture_bundle(extra_root)
    (extra_root / "undeclared.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SelectedPoolEventPopulationError, match="file closure mismatch"):
        verify_selected_pool_event_bundle(extra_root)


def test_verifier_rejects_root_identity_drift(tmp_path: Path) -> None:
    _build_fixture_bundle(tmp_path)
    manifest_path = tmp_path / "event_population_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["symbols"] = ["AAA"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SelectedPoolEventPopulationError, match="symbol count mismatch"):
        verify_selected_pool_event_bundle(tmp_path)


def test_verifier_rejects_semantic_drift_even_after_attacker_reseals_hashes(
    tmp_path: Path,
) -> None:
    _build_fixture_bundle(tmp_path)
    events_path = tmp_path / "fundamentals/events.jsonl"
    event = json.loads(events_path.read_text(encoding="utf-8"))
    event["market"] = "cn"
    events_path.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    component_path = tmp_path / "fundamentals/component_manifest.json"
    component = json.loads(component_path.read_text(encoding="utf-8"))
    component["details"]["events_sha256"] = event_population._sha256(events_path)
    component["details"]["events_byte_size"] = events_path.stat().st_size
    event_population._write_json(component_path, component)

    manifest_path = tmp_path / "event_population_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [event_population._file_record(tmp_path, path) for path in MEMBER_PATHS]
    for record in manifest["components"]:
        path = tmp_path / record["manifest_path"]
        record["manifest_sha256"] = event_population._sha256(path)
    manifest["bundle_id"] = event_population._bundle_id(manifest)
    event_population._write_json(manifest_path, manifest)

    with pytest.raises(SelectedPoolEventPopulationError, match="event market mismatch"):
        verify_selected_pool_event_bundle(tmp_path)


def test_failed_staging_build_preserves_previously_verified_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _build_fixture_bundle(tmp_path)
    accepted = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(event_population, "_write_jsonl", fail_write)
    with pytest.raises(OSError, match="simulated interrupted write"):
        _build_fixture_bundle(tmp_path)

    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == accepted
    verify_selected_pool_event_bundle(tmp_path)
    assert not list(tmp_path.parent.glob(f".{tmp_path.name}.stage-*"))


def test_publish_refuses_to_overwrite_existing_verified_evidence(tmp_path: Path) -> None:
    _build_fixture_bundle(tmp_path)
    accepted = (tmp_path / "event_population_manifest.json").read_bytes()

    with pytest.raises(SelectedPoolEventPopulationError, match="already contains evidence"):
        _build_fixture_bundle(tmp_path)

    assert (tmp_path / "event_population_manifest.json").read_bytes() == accepted
    verify_selected_pool_event_bundle(tmp_path)


def test_population_workflow_uses_core_verifier_and_uploads_only_complete_bundle() -> None:
    workflow = Path(".github/workflows/selected-pool-event-population-ci.yml").read_text(
        encoding="utf-8"
    )

    assert "--verify-only" in workflow
    assert 'uv run python - "artifacts/data/event_population/' not in workflow
    assert "if: success() && steps.selected.outputs.run == 'true'" in workflow
    assert "if-no-files-found: error" in workflow
