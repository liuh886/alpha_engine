from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts.data.build_model_data_bundle import _component_spec
from src.data.model_data_bundle import (
    ComponentSpec,
    ModelDataBundleError,
    build_model_data_bundle,
    verify_model_data_bundle,
)
from src.data.selected_pool_price_publication import (
    write_selected_pool_price_publication_manifest,
)
from tests.selected_pool_price_fixtures import selected_pool_price_source

CONTRACT = Path("configs/data_contracts/model_data_bundle_v1.yaml")


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _price_manifest(
    tmp_path: Path,
    *,
    market: str,
    pool_id: str,
    candidate_count: int,
    cutoff: str = "2026-06-18",
) -> Path:
    symbols = [f"{market.upper()}{index:03d}" for index in range(candidate_count)]
    return _write_json(
        tmp_path / f"{market}-prices.json",
        {
            "market": market,
            "pool_id": pool_id,
            "candidate_count": candidate_count,
            "status": "selected_pool_price_refresh_ready",
            "promotion_eligible": True,
            "evidence_cutoff": cutoff,
            "records": [
                {
                    "symbol": symbol,
                    "provider": "tiingo" if market == "us" else "tushare",
                    "first_date": "2021-01-04",
                    "last_date": cutoff,
                }
                for symbol in symbols
            ],
            "failures": [],
            "selected_providers": {
                symbol: "tiingo" if market == "us" else "tushare"
                for symbol in symbols
            },
            "quarantined_symbols": [],
            "research_only": True,
            "trade_ready": False,
        },
    )


def _etf_manifest(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "etf-bundle.json",
        {
            "bundle_id": "qqqi_qqq_tqqq_reference_bundle_v1",
            "symbols": ["QQQ", "QQQI", "TQQQ"],
            "strategy_data_ready": True,
            "professional_source_ready": True,
            "selected_providers": {
                "QQQ": "tiingo",
                "QQQI": "tiingo",
                "TQQQ": "tiingo",
            },
            "reconciliation_status": {
                "QQQ": "consensus",
                "QQQI": "consensus",
                "TQQQ": "consensus",
            },
            "common_history_start": "2024-01-30",
            "common_history_end": "2026-07-31",
            "evidence_cutoff": "2026-07-31",
            "research_only": True,
            "trade_ready": False,
        },
    )


def _generic_component(
    tmp_path: Path,
    *,
    component_id: str,
    kind: str,
    market: str,
    pool_id: str,
    status: str,
    expected: int,
    ready: int,
) -> Path:
    return _write_json(
        tmp_path / f"{component_id.replace('.', '-')}.json",
        {
            "component_id": component_id,
            "component_kind": kind,
            "status": status,
            "market": market,
            "pool_id": pool_id,
            "evidence_cutoff": "2026-06-18",
            "expected_symbol_count": expected,
            "ready_symbol_count": ready,
            "coverage_ratio": ready / expected,
            "missing_symbols": [],
            "invalid_symbols": [],
            "quarantined_symbols": [],
            "providers": ["fixture"],
            "research_only": True,
            "trade_ready": False,
        },
    )


def test_price_and_etf_profiles_are_ready_while_missing_inputs_block_others(
    tmp_path: Path,
) -> None:
    us_prices = _price_manifest(
        tmp_path,
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
    )
    cn_prices = _price_manifest(
        tmp_path,
        market="cn",
        pool_id="cn_selected_equities_v3",
        candidate_count=130,
    )
    etf = _etf_manifest(tmp_path)

    output = tmp_path / "output"
    frontend = tmp_path / "site" / "data"
    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                us_prices,
                "us",
            ),
            ComponentSpec(
                "prices.cn_selected_equities_v3",
                "selected_pool_prices",
                cn_prices,
                "cn",
            ),
            ComponentSpec(
                "references.qqqi_qqq_tqqq_reference_bundle_v1",
                "etf_reference_bundle",
                etf,
                "us",
            ),
        ],
        output_root=output,
        evidence_cutoff="2026-07-31",
        frontend_data_dir=frontend,
    )

    statuses = {
        row["profile_id"]: row["status"]
        for row in manifest["training_profiles"]
    }
    assert statuses["us_selected_price_only_v1"] == "ready"
    assert statuses["cn_selected_price_only_v1"] == "ready"
    assert statuses["qqqi_qqq_tqqq_rotation_v1"] == "ready"
    assert statuses["us_selected_price_plus_fundamentals_v1"] == "blocked"
    assert statuses["cn_selected_price_plus_fundamentals_v1"] == "blocked"
    assert sorted(verify_model_data_bundle(output)) == [
        "data-components.json",
        "model-data-readiness.json",
        "training-profiles.json",
    ]
    for path in output.glob("*.json"):
        assert b"\r\n" not in path.read_bytes()
    assert (frontend / "model-data-readiness.json").is_file()
    assert (frontend / "data-components.json").is_file()
    assert (frontend / "training-profiles.json").is_file()


def test_partial_fundamentals_can_pass_declared_minimum_coverage(
    tmp_path: Path,
) -> None:
    us_prices = _price_manifest(
        tmp_path,
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
    )
    fundamentals = _generic_component(
        tmp_path,
        component_id="fundamentals.us_selected_equities_v2",
        kind="fundamental_coverage",
        market="us",
        pool_id="us_selected_equities_v2",
        status="partial",
        expected=87,
        ready=70,
    )
    actions = _generic_component(
        tmp_path,
        component_id="corporate_actions.us_selected_equities_v2",
        kind="corporate_action_coverage",
        market="us",
        pool_id="us_selected_equities_v2",
        status="partial",
        expected=87,
        ready=87,
    )
    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                us_prices,
                "us",
            ),
            ComponentSpec(
                "fundamentals.us_selected_equities_v2",
                "fundamental_coverage",
                fundamentals,
                "us",
            ),
            ComponentSpec(
                "corporate_actions.us_selected_equities_v2",
                "corporate_action_coverage",
                actions,
                "us",
            ),
        ],
        output_root=tmp_path / "output",
        evidence_cutoff="2026-06-18",
    )
    profile = next(
        row
        for row in manifest["training_profiles"]
        if row["profile_id"] == "us_selected_price_plus_fundamentals_v1"
    )
    assert profile["status"] == "ready"
    assert profile["failed_gates"] == []


def test_profile_fails_on_post_cutoff_component(tmp_path: Path) -> None:
    prices = _price_manifest(
        tmp_path,
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
        cutoff="2026-07-01",
    )
    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                prices,
                "us",
            )
        ],
        output_root=tmp_path / "output",
        evidence_cutoff="2026-06-18",
    )
    profile = next(
        row
        for row in manifest["training_profiles"]
        if row["profile_id"] == "us_selected_price_only_v1"
    )
    assert profile["status"] == "blocked"
    assert any("exceeds" in gate for gate in profile["failed_gates"])


def test_selected_pool_uses_common_candidate_observation_cutoff(
    tmp_path: Path,
) -> None:
    prices = _price_manifest(
        tmp_path,
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
        cutoff="2026-06-18",
    )
    payload = json.loads(prices.read_text(encoding="utf-8"))
    payload["candidate_symbols"] = [row["symbol"] for row in payload["records"]]
    payload["cutoff"] = "2026-06-19"
    payload.pop("evidence_cutoff")
    payload["records"].append(
        {
            "symbol": "QQQ",
            "provider": "tiingo",
            "first_date": "2020-01-02",
            "last_date": "2026-06-19",
        }
    )
    _write_json(prices, payload)

    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                prices,
                "us",
            )
        ],
        output_root=tmp_path / "output",
        evidence_cutoff="2026-06-18",
    )

    component = manifest["components"][0]
    assert component["evidence_cutoff"] == "2026-06-18"
    assert component["first_date"] == "2021-01-04"
    assert component["last_date"] == "2026-06-18"
    assert component["details"]["requested_cutoff"] == "2026-06-19"
    assert component["details"]["candidate_observation_cutoff"] == "2026-06-18"
    profile = next(
        row
        for row in manifest["training_profiles"]
        if row["profile_id"] == "us_selected_price_only_v1"
    )
    assert profile["status"] == "ready"
    assert profile["failed_gates"] == []


def test_candidate_reference_overlap_fails_closed(tmp_path: Path) -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    contract["profiles"] = {
        "bad_overlap": {
            "market": "us",
            "candidate_pool_id": "fixture",
            "candidate_symbols": ["QQQ", "AAPL"],
            "references": ["QQQ"],
            "required_components": [
                {
                    "component_id": "fixture.ready",
                    "accepted_statuses": ["ready"],
                    "minimum_coverage_ratio": 1.0,
                }
            ],
        }
    }
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    component = _generic_component(
        tmp_path,
        component_id="fixture.ready",
        kind="factor_catalog",
        market="us",
        pool_id="fixture",
        status="ready",
        expected=2,
        ready=2,
    )
    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=contract_path,
        component_specs=[
            ComponentSpec("fixture.ready", "factor_catalog", component, "us")
        ],
        output_root=tmp_path / "output",
        evidence_cutoff="2026-06-18",
    )
    profile = manifest["training_profiles"][0]
    assert profile["status"] == "blocked"
    assert profile["failed_gates"] == ["candidate_reference_overlap:QQQ"]


def test_bundle_id_is_deterministic_for_identical_evidence(tmp_path: Path) -> None:
    prices = _price_manifest(
        tmp_path,
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
    )
    kwargs = {
        "root": Path.cwd(),
        "contract_path": CONTRACT,
        "component_specs": [
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                prices,
                "us",
            )
        ],
        "evidence_cutoff": "2026-06-18",
    }
    first = build_model_data_bundle(output_root=tmp_path / "first", **kwargs)
    second = build_model_data_bundle(output_root=tmp_path / "second", **kwargs)
    assert first["bundle_id"] == second["bundle_id"]


def test_verifier_rejects_modified_frontend_index(tmp_path: Path) -> None:
    prices = _price_manifest(
        tmp_path,
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
    )
    output = tmp_path / "output"
    build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                prices,
                "us",
            )
        ],
        output_root=output,
        evidence_cutoff="2026-06-18",
    )
    path = output / "data-components.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ModelDataBundleError, match="hash mismatch"):
        verify_model_data_bundle(output)


def test_model_data_consumes_self_verified_provider_publication(tmp_path: Path) -> None:
    source = selected_pool_price_source("cn")
    publication = tmp_path / "cn-selected-pool-prices.json"
    write_selected_pool_price_publication_manifest(publication, source)
    kwargs = {
        "root": Path.cwd(),
        "contract_path": CONTRACT,
        "component_specs": [
            ComponentSpec(
                "prices.cn_selected_equities_v3",
                "selected_pool_prices",
                publication,
                "cn",
            )
        ],
        "evidence_cutoff": "2026-08-21",
    }

    manifest = build_model_data_bundle(output_root=tmp_path / "valid", **kwargs)
    assert manifest["components"][0]["status"] == "ready"

    payload = json.loads(publication.read_text(encoding="utf-8"))
    payload["records"][0]["output_sha256"] = "0" * 64
    publication.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModelDataBundleError, match="identity mismatch"):
        build_model_data_bundle(output_root=tmp_path / "tampered", **kwargs)


def test_model_data_identity_ignores_provider_runtime_diagnostics(tmp_path: Path) -> None:
    source = selected_pool_price_source("cn")
    changed = copy.deepcopy(source)
    changed["records"][-1]["attempts"][0].update(
        error="different transient error", round=77, circuit_breaker_open=True
    )
    changed["records"][-1]["action"] = "fetched_full_refresh"
    publication = tmp_path / "cn-selected-pool-prices.json"
    write_selected_pool_price_publication_manifest(publication, source)
    stable_bytes = publication.read_bytes()

    def build(path: Path, output: Path) -> dict[str, object]:
        return build_model_data_bundle(
            root=Path.cwd(),
            contract_path=CONTRACT,
            component_specs=[
                ComponentSpec(
                    "prices.cn_selected_equities_v3",
                    "selected_pool_prices",
                    path,
                    "cn",
                )
            ],
            output_root=output,
            evidence_cutoff="2026-08-21",
        )

    first_bundle = build(publication, tmp_path / "first-bundle")
    write_selected_pool_price_publication_manifest(publication, changed)
    second_bundle = build(publication, tmp_path / "second-bundle")
    assert stable_bytes == publication.read_bytes()
    assert first_bundle["bundle_id"] == second_bundle["bundle_id"]

    semantic = copy.deepcopy(source)
    semantic["records"][0]["output_sha256"] = "0" * 64
    write_selected_pool_price_publication_manifest(publication, semantic)
    third_bundle = build(publication, tmp_path / "third-bundle")
    assert third_bundle["bundle_id"] != first_bundle["bundle_id"]


def test_bundle_keeps_embedded_component_paths_portable(tmp_path: Path) -> None:
    output = tmp_path / "output"
    prices = _price_manifest(
        output / "components",
        market="us",
        pool_id="us_selected_equities_v2",
        candidate_count=87,
    )

    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.us_selected_equities_v2",
                "selected_pool_prices",
                prices,
                "us",
            )
        ],
        output_root=output,
        evidence_cutoff="2026-06-18",
    )

    assert manifest["components"][0]["manifest_path"] == "components/us-prices.json"
    assert manifest["contract_path"] == CONTRACT.as_posix()
    assert verify_model_data_bundle(output) == [
        "data-components.json",
        "model-data-readiness.json",
        "training-profiles.json",
    ]


def test_component_cli_spec_accepts_windows_absolute_path() -> None:
    spec = _component_spec(
        "factors.qlib_alpha158.panel.cn.v1:factor_panel:"
        "C:/artifacts/alpha158/factor_panel_manifest.json:cn"
    )

    assert spec.component_id == "factors.qlib_alpha158.panel.cn.v1"
    assert spec.component_kind == "factor_panel"
    assert spec.manifest_path == Path(
        "C:/artifacts/alpha158/factor_panel_manifest.json"
    )
    assert spec.market == "cn"


def test_component_cli_spec_keeps_colon_path_without_known_market_suffix() -> None:
    spec = _component_spec(
        "fixture:factor_panel:C:/artifacts/global/factor_panel_manifest.json"
    )

    assert spec.manifest_path == Path(
        "C:/artifacts/global/factor_panel_manifest.json"
    )
    assert spec.market is None


def test_bundle_binds_portable_governed_source_receipt(tmp_path: Path) -> None:
    output = tmp_path / "output"
    prices = _price_manifest(
        output / "components",
        market="cn",
        pool_id="cn_selected_equities_v3",
        candidate_count=130,
    )
    receipt = _write_json(
        output / "sources/governed-source-receipt.json",
        {
            "schema_version": "1.0",
            "verification_policy": "exact_run_artifact_archive_and_component_hashes",
            "sources": [
                {
                    "source_id": "cn_events_2026_08_31",
                    "workflow_run_id": 33528559207,
                    "artifact_id": 9808822820,
                    "artifact_digest": "sha256:" + "1" * 64,
                    "head_sha": "2" * 40,
                    "research_only": True,
                    "trade_ready": False,
                }
            ],
            "research_only": True,
            "trade_ready": False,
        },
    )

    manifest = build_model_data_bundle(
        root=Path.cwd(),
        contract_path=CONTRACT,
        component_specs=[
            ComponentSpec(
                "prices.cn_selected_equities_v3",
                "selected_pool_prices",
                prices,
                "cn",
            )
        ],
        output_root=output,
        evidence_cutoff="2026-06-18",
        source_receipts=[receipt],
    )

    record = manifest["source_receipts"][0]
    assert record["path"] == "sources/governed-source-receipt.json"
    assert record["source_ids"] == ["cn_events_2026_08_31"]
    readiness = json.loads(
        (output / "model-data-readiness.json").read_text(encoding="utf-8")
    )
    assert readiness["source_receipts"] == manifest["source_receipts"]
    verify_model_data_bundle(output)

    receipt.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModelDataBundleError, match="source receipt hash mismatch"):
        verify_model_data_bundle(output)


def test_bundle_rejects_unbounded_source_receipt(tmp_path: Path) -> None:
    receipt = _write_json(
        tmp_path / "receipt.json",
        {"sources": [], "research_only": True, "trade_ready": False},
    )

    with pytest.raises(ModelDataBundleError, match="requires sources"):
        build_model_data_bundle(
            root=Path.cwd(),
            contract_path=CONTRACT,
            component_specs=[],
            output_root=tmp_path / "output",
            evidence_cutoff="2026-06-18",
            source_receipts=[receipt],
        )
