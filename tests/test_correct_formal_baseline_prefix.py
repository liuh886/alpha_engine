from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from scripts.correct_formal_baseline_prefix import (
    FormalBaselineCorrectionError,
    correct_formal_baseline_prefix,
)
from scripts.sync_formal_bundle_v2 import sync
from src.artifacts.model_run_bundle_v2 import (
    canonical_json_bytes,
    compute_bundle_id,
    sha256_bytes,
    validate_catalog,
    validate_manifest,
)

MODEL_VERSION_ID = "test_model_v1"
MODEL_FAMILY_ID = "test_family"
RUN_ID = "test_model_v1-through-2026_11_13"
POLICY_ID = "qqq_v4_3_vix_session_correction_v1"
AUTHORIZATION = (
    'Owner approved on 2026-11-15 "option 1": re-freeze the QQQ v4.3 historical '
    "prefix from the session-calendar-controlled ^VIX series, recording the four "
    "changed reason labels and the provider vintage in lineage."
)
CORRECTIONS = [
    ("2024-01-02", "decision_reason", "hold", "defensive_price_or_vix_stress"),
    ("2024-01-03", "executed_reason", "hold", "defensive_price_or_vix_stress"),
    ("2024-01-04", "decision_reason", "defensive_price_or_vix_stress", "hold"),
    ("2024-01-05", "executed_reason", "defensive_price_or_vix_stress", "hold"),
]
REAL_CORRECTIONS = [
    ("2026-01-20", "decision_reason", "hold", "defensive_price_or_vix_stress"),
    ("2026-01-21", "executed_reason", "hold", "defensive_price_or_vix_stress"),
    ("2026-03-02", "decision_reason", "defensive_price_or_vix_stress", "hold"),
    ("2026-03-03", "executed_reason", "defensive_price_or_vix_stress", "hold"),
]


def _write_section(run_dir: Path, section_id: str, payload: dict) -> dict:
    encoded = canonical_json_bytes(payload)
    (run_dir / f"{section_id}.json").write_bytes(encoded)
    return {
        "section_id": section_id,
        "availability_status": "available",
        "required_for_model_kind": True,
        "reason": None,
        "path": f"{section_id}.json",
        "sha256": sha256_bytes(encoded),
        "byte_size": len(encoded),
        "media_type": "application/json",
    }


def _base_rows() -> list[dict]:
    rows = []
    for index, (date, field, before, _after) in enumerate(CORRECTIONS):
        rows.append(
            {
                "date": date,
                "account": 1.0 + index / 100.0,
                "bench_qqq": 1.0,
                "bench": 0.0,
                "turnover": 0.0,
                "period_return": 0.0,
                "gross_return": 0.0,
                "transaction_cost": 0.0,
                "position_state": 0,
                "position_label": "defensive",
                "decision_state": 0,
                "decision_reason": before if field == "decision_reason" else "hold",
                "executed_reason": before if field == "executed_reason" else "hold",
                "drawdown": 0.0,
                "trace_frequency": "daily_open_to_open",
                "panic_repair_active": False,
                "slow_bear_defense_active": False,
                "weight_QQQ": 0.0,
                "weight_QQQI": 1.0,
            }
        )
    return rows


def _performance(rows: list[dict]) -> dict:
    return {
        "schema_version": "2.0.0",
        "report": rows,
        "date_range": {"start": rows[0]["date"], "end": rows[-1]["date"]},
        "benchmark": "QQQ",
        "trace_frequency": "daily_open_to_open",
        "performance_semantics": {"schema_version": "formal_performance_semantics_v1"},
        "source_field": "report",
        "research_only": True,
        "trade_ready": False,
    }


def _portfolio(rows: list[dict]) -> dict:
    return {
        "schema_version": "2.0.0",
        "portfolio_contract": {"symbols": ["QQQI"]},
        "positions": [
            {
                "date": row["date"],
                "instrument": "QQQI",
                "weight": 1.0,
                "price": 100.0 + index,
                "position_state": 0,
                "position_label": "defensive",
                "executed_reason": row["executed_reason"],
                "panic_repair_active": False,
                "slow_bear_defense_active": False,
            }
            for index, row in enumerate(rows)
        ],
        "source_fields": ["portfolio_contract", "positions"],
        "research_only": True,
        "trade_ready": False,
    }


def _replay(rows: list[dict], *, with_filter: bool = False) -> dict:
    replay_rows = copy.deepcopy(rows)
    for date, field, _before, after in CORRECTIONS:
        row = next(item for item in replay_rows if item["date"] == date)
        row[field] = after
    payload = _performance(replay_rows)
    if with_filter:
        payload["data_identity"] = {
            "mode": "governed_strategy_data_bundle",
            "bundle_id": "test_strategy_data_v1",
            "component_id": "strategy.test_v1",
            "manifest_sha256": "f" * 64,
            "common_history_start": "2024-01-02",
            "common_history_end": "2026-11-13",
            "selected_providers": {"^VIX": "yfinance"},
            "symbols": ["^VIX"],
            "roles": {"^VIX": "signal_reference"},
        }
        payload["signal_reference_session_filter"] = {
            "policy_id": "us_equity_session_only_v1",
            "authority_symbol": "QQQ",
            "authority_session_count": 4,
            "symbols": {
                "^VIX": {
                    "removed_dates": ["2024-11-28", "2025-01-09"],
                    "removed_count": 2,
                    "input_rows": 6,
                    "retained_rows": 4,
                }
            },
        }
    return payload


def _make_bundle(tmp_path: Path) -> dict[str, object]:
    native_root = tmp_path / "data" / "research" / "model_runs"
    run_dir = native_root / MODEL_FAMILY_ID / MODEL_VERSION_ID / RUN_ID
    run_dir.mkdir(parents=True)

    rows = _base_rows()
    performance = _performance(rows)
    portfolio = _portfolio(rows)
    summary = {
        "schema_version": "2.0.0",
        "metrics": [],
        "research_only": True,
        "trade_ready": False,
    }
    lineage = {
        "schema_version": "2.0.0",
        "source_backtest_id": RUN_ID,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    sections = [
        _write_section(run_dir, "summary", summary),
        _write_section(run_dir, "performance", performance),
        _write_section(run_dir, "portfolio", portfolio),
        _write_section(run_dir, "lineage", lineage),
    ]
    manifest = {
        "schema_version": "2.0.0",
        "model_family_id": MODEL_FAMILY_ID,
        "model_version_id": MODEL_VERSION_ID,
        "run_id": RUN_ID,
        "bundle_id": "0" * 64,
        "model_kind": "rules_based_allocation",
        "publication_channel": "preview",
        "publication_status": "ci_validated_preview",
        "generated_at": "2026-11-14T00:00:00Z",
        "evidence_cutoff": "2026-11-13",
        "research_only": True,
        "trade_ready": False,
        "comparability_key": {
            "market": "us",
            "universe_id": "test_universe",
            "benchmark_id": "qqq",
            "start": rows[0]["date"],
            "end": rows[-1]["date"],
            "trace_frequency": "daily_open_to_open",
            "horizon": "retained_formal_source_horizon",
            "rebalance_contract_id": "daily_open_to_open",
            "cost_contract_id": "cost_10_bps",
        },
        "sections": sections,
    }
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    catalog_record = {
        "model_family_id": MODEL_FAMILY_ID,
        "model_version_id": MODEL_VERSION_ID,
        "run_id": RUN_ID,
        "bundle_id": manifest["bundle_id"],
        "model_kind": "rules_based_allocation",
        "publication_status": "ci_validated_preview",
        "manifest_path": f"{MODEL_FAMILY_ID}/{MODEL_VERSION_ID}/{RUN_ID}/manifest.json",
        "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        "evidence_cutoff": "2026-11-13",
    }
    catalog = {
        "schema_version": "2.0.0",
        "channel": "preview",
        "generated_at": "2026-11-14T00:00:00Z",
        "research_only": True,
        "trade_ready": False,
        "records": [catalog_record],
    }
    validate_catalog(catalog)
    (native_root / "catalog.json").write_bytes(canonical_json_bytes(catalog))
    return {
        "manifest": manifest,
        "performance": performance,
        "portfolio": portfolio,
        "catalog": catalog,
        "run_dir": run_dir,
        "manifest_path": manifest_path,
        "native_root": native_root,
        "rows": rows,
    }


def _resign_bundle(bundle: dict, *, section_ids: tuple[str, ...]) -> None:
    """Recompute manifest section digests/bundle id and the catalog digest in place."""

    run_dir = bundle["run_dir"]
    manifest = json.loads(bundle["manifest_path"].read_text())
    for section in manifest["sections"]:
        if section["section_id"] not in section_ids:
            continue
        body = (run_dir / section["path"]).read_bytes()
        section["sha256"] = sha256_bytes(body)
        section["byte_size"] = len(body)
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    bundle["manifest_path"].write_bytes(canonical_json_bytes(manifest))
    catalog_path = bundle["native_root"] / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["records"][0]["bundle_id"] = manifest["bundle_id"]
    catalog["records"][0]["manifest_sha256"] = sha256_bytes(
        bundle["manifest_path"].read_bytes()
    )
    validate_catalog(catalog)
    catalog_path.write_bytes(canonical_json_bytes(catalog))


def _mutate_portfolio(bundle: dict, mutate) -> None:
    path = bundle["run_dir"] / "portfolio.json"
    portfolio = json.loads(path.read_text())
    mutate(portfolio)
    path.write_bytes(canonical_json_bytes(portfolio))
    _resign_bundle(bundle, section_ids=("portfolio",))


def _apply(tmp_path: Path, replay: dict, *, dry_run: bool = False) -> dict:
    replay_path = tmp_path / "replay_performance.json"
    replay_path.write_bytes(canonical_json_bytes(replay))
    return correct_formal_baseline_prefix(
        repository_root=tmp_path,
        model_version_id=MODEL_VERSION_ID,
        policy_id=POLICY_ID,
        authorization=AUTHORIZATION,
        replay_performance=replay_path,
        corrected_at="2026-11-15T00:00:00Z",
        dry_run=dry_run,
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_applies_exactly_the_four_report_cells_and_two_position_cells(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    original_performance = bundle["performance"]
    original_portfolio = bundle["portfolio"]

    receipt = _apply(tmp_path, _replay(bundle["rows"]))

    assert receipt["status"] == "corrected"
    assert receipt["differences"] == [
        {"date": date, "field": field, "before": before, "after": after}
        for date, field, before, after in CORRECTIONS
    ]
    assert receipt["positions_corrections"] == [
        {
            "date": "2024-01-03",
            "field": "executed_reason",
            "before": "hold",
            "after": "defensive_price_or_vix_stress",
            "row_count": 1,
        },
        {
            "date": "2024-01-05",
            "field": "executed_reason",
            "before": "defensive_price_or_vix_stress",
            "after": "hold",
            "row_count": 1,
        },
    ]
    assert receipt["positions_changed"] is True

    run_dir = bundle["run_dir"]
    corrected = json.loads((run_dir / "performance.json").read_text())
    changed = []
    for old_row, new_row in zip(original_performance["report"], corrected["report"]):
        for field in old_row:
            if old_row[field] != new_row[field]:
                changed.append((old_row["date"], field, old_row[field], new_row[field]))
    assert changed == [
        (date, field, before, after) for date, field, before, after in CORRECTIONS
    ]

    positions = json.loads((run_dir / "portfolio.json").read_text())["positions"]
    by_date = {row["date"]: row for row in positions}
    assert by_date["2024-01-03"]["executed_reason"] == "defensive_price_or_vix_stress"
    assert by_date["2024-01-05"]["executed_reason"] == "hold"
    assert by_date["2024-01-02"]["executed_reason"] == "hold"
    assert by_date["2024-01-04"]["executed_reason"] == "hold"
    # Only the two executed_reason cells changed in positions.
    position_changes = [
        (old["date"], field, old[field], new[field])
        for old, new in zip(original_portfolio["positions"], positions)
        for field in old
        if old[field] != new[field]
    ]
    assert position_changes == [
        ("2024-01-03", "executed_reason", "hold", "defensive_price_or_vix_stress"),
        ("2024-01-05", "executed_reason", "defensive_price_or_vix_stress", "hold"),
    ]

    manifest = json.loads((run_dir / "manifest.json").read_text())
    validate_manifest(manifest)
    assert manifest["bundle_id"] == compute_bundle_id(manifest)
    for section in manifest["sections"]:
        if section["availability_status"] != "available":
            continue
        body = (run_dir / section["path"]).read_bytes()
        assert section["sha256"] == sha256_bytes(body)
        assert section["byte_size"] == len(body)

    lineage = json.loads((run_dir / "lineage.json").read_text())
    block = lineage["baseline_correction"]
    assert block["policy_id"] == POLICY_ID
    assert block["authorization"] == AUTHORIZATION
    assert block["corrections"] == receipt["differences"]
    assert block["positions_corrections"] == receipt["positions_corrections"]
    assert block["model_selection_reopened"] is False

    catalog = json.loads((bundle["native_root"] / "catalog.json").read_text())
    validate_catalog(catalog)
    record = catalog["records"][0]
    assert record["bundle_id"] == manifest["bundle_id"]
    assert record["manifest_sha256"] == sha256_bytes((run_dir / "manifest.json").read_bytes())


def test_corrected_bundle_is_internally_consistent(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    _apply(tmp_path, _replay(bundle["rows"]))

    run_dir = bundle["run_dir"]
    report = {
        row["date"]: row for row in json.loads((run_dir / "performance.json").read_text())["report"]
    }
    positions = json.loads((run_dir / "portfolio.json").read_text())["positions"]
    for date in ("2024-01-03", "2024-01-05"):
        matched = [row for row in positions if row["date"] == date]
        assert matched
        assert all(row["executed_reason"] == report[date]["executed_reason"] for row in matched)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda positions: positions[1].__setitem__("position_state", 2), id="state"
        ),
        pytest.param(lambda positions: positions[1].__setitem__("weight", 0.5), id="weight"),
        pytest.param(lambda positions: positions[1].__setitem__("price", -1.0), id="price"),
        pytest.param(
            lambda positions: positions[1].__setitem__("instrument", "SGOV"), id="instrument"
        ),
        pytest.param(
            lambda positions: positions[1].__setitem__("position_label", "attack"),
            id="label",
        ),
        pytest.param(
            lambda positions: positions[1].__setitem__("executed_reason", "other"),
            id="reason-neither-before-nor-after",
        ),
    ],
)
def test_refuses_unexpected_position_state(tmp_path: Path, mutate) -> None:
    bundle = _make_bundle(tmp_path)
    _mutate_portfolio(bundle, lambda portfolio: mutate(portfolio["positions"]))
    with pytest.raises(FormalBaselineCorrectionError):
        _apply(tmp_path, _replay(bundle["rows"]))


def test_refuses_absent_positions_section(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    run_dir = bundle["run_dir"]
    (run_dir / "portfolio.json").unlink()
    manifest = json.loads(bundle["manifest_path"].read_text())
    manifest["sections"] = [
        section for section in manifest["sections"] if section["section_id"] != "portfolio"
    ]
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    bundle["manifest_path"].write_bytes(canonical_json_bytes(manifest))
    catalog_path = bundle["native_root"] / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["records"][0]["bundle_id"] = manifest["bundle_id"]
    catalog["records"][0]["manifest_sha256"] = sha256_bytes(
        bundle["manifest_path"].read_bytes()
    )
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    with pytest.raises(FormalBaselineCorrectionError, match="positions section"):
        _apply(tmp_path, _replay(bundle["rows"]))


def test_refuses_partially_corrected_positions(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)

    def mutate(portfolio: dict) -> None:
        row = next(item for item in portfolio["positions"] if item["date"] == "2024-01-03")
        row["executed_reason"] = "defensive_price_or_vix_stress"

    _mutate_portfolio(bundle, mutate)
    with pytest.raises(FormalBaselineCorrectionError, match="partially corrected"):
        _apply(tmp_path, _replay(bundle["rows"]))


def test_dry_run_writes_nothing_and_is_byte_stable(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)

    first = _apply(tmp_path, _replay(bundle["rows"], with_filter=True), dry_run=True)
    before = _snapshot(tmp_path)
    second = _apply(tmp_path, _replay(bundle["rows"], with_filter=True), dry_run=True)

    assert first == second
    assert first["status"] == "dry_run"
    assert first["removed_non_session_dates"] == ["2024-11-28", "2025-01-09"]
    assert first["session_filter"]["policy_id"] == "us_equity_session_only_v1"
    assert first["replay_data_identity"]["bundle_id"] == "test_strategy_data_v1"
    assert [row["date"] for row in first["positions_corrections"]] == [
        "2024-01-03",
        "2024-01-05",
    ]
    assert any(
        entry["path"].endswith("portfolio.json") for entry in first["planned_writes"]
    )
    assert _snapshot(tmp_path) == before


def test_second_apply_is_idempotent(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    _apply(tmp_path, _replay(bundle["rows"]))
    corrected = _snapshot(tmp_path)

    again = _apply(tmp_path, _replay(bundle["rows"]))

    assert again["status"] == "already_corrected"
    assert again["differences"] == []
    assert again["positions_corrections"] == []
    assert _snapshot(tmp_path) == corrected


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda rows: rows[0].__setitem__("decision_state", 2), id="state"),
        pytest.param(lambda rows: rows[1].__setitem__("position_state", 1), id="position-state"),
        pytest.param(lambda rows: rows[0].__setitem__("position_label", "attack"), id="label"),
        pytest.param(lambda rows: rows[0].__setitem__("weight_QQQ", 0.5), id="weight"),
        pytest.param(
            lambda rows: rows[0].__setitem__("slow_bear_defense_active", True),
            id="overlay",
        ),
        pytest.param(lambda rows: rows[0].__setitem__("date", "2024-01-01"), id="date"),
        pytest.param(lambda rows: rows.pop(), id="row-count"),
    ],
)
def test_refuses_any_non_reason_report_difference(tmp_path: Path, mutate) -> None:
    bundle = _make_bundle(tmp_path)
    replay = _replay(bundle["rows"])
    mutate(replay["report"])
    with pytest.raises(FormalBaselineCorrectionError):
        _apply(tmp_path, replay)


def test_refuses_zero_differences(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with pytest.raises(FormalBaselineCorrectionError, match="nothing to correct"):
        _apply(tmp_path, _performance(copy.deepcopy(bundle["rows"])))


def test_refuses_more_than_eight_cells(tmp_path: Path) -> None:
    rows = _base_rows()
    for index in range(5):
        rows.append(
            {
                **copy.deepcopy(rows[0]),
                "date": f"2024-01-{10 + index:02d}",
                "decision_reason": "hold",
                "executed_reason": "hold",
            }
        )
    _make_bundle_with_rows(tmp_path, rows)
    replay = _replay(rows)
    for row in replay["report"]:
        row["decision_reason"] = "defensive_price_or_vix_stress"
        row["executed_reason"] = "defensive_price_or_vix_stress"
    replay["date_range"] = {"start": rows[0]["date"], "end": rows[-1]["date"]}
    with pytest.raises(FormalBaselineCorrectionError, match="sanity bound"):
        _apply(tmp_path, replay)


def _make_bundle_with_rows(tmp_path: Path, rows: list[dict]) -> dict:
    """Rebuild the synthetic preview bundle in-place with a custom row set."""

    bundle = _make_bundle(tmp_path)
    run_dir = bundle["run_dir"]
    performance = _performance(rows)
    portfolio = _portfolio(rows)
    lineage = json.loads((run_dir / "lineage.json").read_text())
    sections = [
        _write_section(run_dir, "summary", json.loads((run_dir / "summary.json").read_text())),
        _write_section(run_dir, "performance", performance),
        _write_section(run_dir, "portfolio", portfolio),
        _write_section(run_dir, "lineage", lineage),
    ]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    manifest["sections"] = sections
    manifest["comparability_key"]["start"] = rows[0]["date"]
    manifest["comparability_key"]["end"] = rows[-1]["date"]
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    (run_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    catalog_path = bundle["native_root"] / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    catalog["records"][0]["bundle_id"] = manifest["bundle_id"]
    catalog["records"][0]["manifest_sha256"] = sha256_bytes(
        (run_dir / "manifest.json").read_bytes()
    )
    validate_catalog(catalog)
    catalog_path.write_bytes(canonical_json_bytes(catalog))
    return {"manifest": manifest}


def _restore_preview_baseline(preview_run: Path, repository: Path) -> None:
    """Return a copied preview run to its pre-correction state deterministically."""

    performance_path = preview_run / "performance.json"
    performance = json.loads(performance_path.read_text())
    for date, field, before, _after in REAL_CORRECTIONS:
        row = next(item for item in performance["report"] if item["date"] == date)
        row[field] = before
    performance_path.write_bytes(canonical_json_bytes(performance))

    portfolio_path = preview_run / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text())
    executed = {
        date: before
        for date, field, before, _after in REAL_CORRECTIONS
        if field == "executed_reason"
    }
    for row in portfolio["positions"]:
        if row["date"] in executed:
            row["executed_reason"] = executed[row["date"]]
    portfolio_path.write_bytes(canonical_json_bytes(portfolio))

    lineage_path = preview_run / "lineage.json"
    lineage = json.loads(lineage_path.read_text())
    lineage.pop("baseline_correction", None)
    lineage_path.write_bytes(canonical_json_bytes(lineage))

    manifest_path = preview_run / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for section in manifest["sections"]:
        if section.get("availability_status") != "available":
            continue
        if section["section_id"] not in {"performance", "portfolio", "lineage"}:
            continue
        body = (preview_run / section["path"]).read_bytes()
        section["sha256"] = sha256_bytes(body)
        section["byte_size"] = len(body)
    manifest["bundle_id"] = compute_bundle_id(manifest)
    validate_manifest(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    catalog_path = repository / "data/research/model_runs/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    record = next(
        row for row in catalog["records"] if row["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    )
    record["bundle_id"] = manifest["bundle_id"]
    record["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
    validate_catalog(catalog)
    catalog_path.write_bytes(canonical_json_bytes(catalog))


def test_sync_promotes_corrected_report_and_positions(tmp_path: Path) -> None:
    """Integration: the governed sync promotes report and position corrections."""

    repository = Path.cwd().resolve()
    for relative in ("data/research/model_runs", "data/research/formal_model_runs", "configs"):
        shutil.copytree(repository / relative, tmp_path / relative)

    freshness_input = tmp_path / "artifacts" / "freshness-input"
    freshness_input.mkdir(parents=True)
    shutil.copy(
        tmp_path / "data/research/formal_model_runs/freshness.json",
        freshness_input / "freshness.json",
    )

    preview_run = (
        tmp_path
        / "data/research/model_runs/qqq_rotation/qqqi_qqq_tqqq_v4_3"
        / "qqqi_qqq_tqqq_v4_3-through-2026_11_13"
    )
    _restore_preview_baseline(preview_run, tmp_path)
    performance = json.loads((preview_run / "performance.json").read_text())
    replay = copy.deepcopy(performance)
    for date, field, before, after in REAL_CORRECTIONS:
        row = next(item for item in replay["report"] if item["date"] == date)
        assert row[field] == before
        row[field] = after
    replay_path = tmp_path / "replay.json"
    replay_path.write_bytes(canonical_json_bytes(replay))

    correct_formal_baseline_prefix(
        repository_root=tmp_path,
        model_version_id="qqqi_qqq_tqqq_v4_3",
        policy_id=POLICY_ID,
        authorization=AUTHORIZATION,
        replay_performance=replay_path,
        corrected_at="2026-11-15T00:00:00Z",
    )
    preview_manifest = json.loads((preview_run / "manifest.json").read_text())

    output_a = tmp_path / "artifacts" / "bundle-a"
    output_b = tmp_path / "artifacts" / "bundle-b"
    kwargs = dict(
        native_root=tmp_path / "data/research/model_runs",
        retained_root=tmp_path / "data/research/formal_model_runs",
        strategy_catalog=tmp_path / "configs/strategies/registry.json",
        repository_root=tmp_path,
    )
    sync(freshness_input, output_a, **kwargs)
    sync(freshness_input, output_b, **kwargs)

    formal_run = (
        output_a
        / "qqq_rotation/qqqi_qqq_tqqq_v4_3/qqqi_qqq_tqqq_v4_3-through-2026_11_13"
    )
    formal_performance = json.loads((formal_run / "performance.json").read_text())
    for date, field, _before, after in REAL_CORRECTIONS:
        row = next(item for item in formal_performance["report"] if item["date"] == date)
        assert row[field] == after
    assert len(formal_performance["report"]) == len(performance["report"])

    formal_positions = json.loads((formal_run / "portfolio.json").read_text())["positions"]
    report_by_date = {row["date"]: row for row in formal_performance["report"]}
    for date, field, _before, after in REAL_CORRECTIONS:
        if field != "executed_reason":
            continue
        matched = [row for row in formal_positions if row["date"] == date]
        assert matched
        assert all(row["executed_reason"] == after for row in matched)
        assert all(row["executed_reason"] == report_by_date[date][field] for row in matched)

    formal_manifest = json.loads((formal_run / "manifest.json").read_text())
    validate_manifest(formal_manifest)
    assert formal_manifest["publication_channel"] == "formal"
    formal_lineage = json.loads((formal_run / "lineage.json").read_text())
    assert formal_lineage["baseline_correction"]["policy_id"] == POLICY_ID
    assert formal_lineage["baseline_correction"]["positions_corrections"]
    assert formal_lineage["source_preview_bundle_id"] == preview_manifest["bundle_id"]

    catalog = json.loads((output_a / "catalog.json").read_text())
    validate_catalog(catalog)
    record = next(
        row for row in catalog["records"] if row["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    )
    assert record["bundle_id"] == formal_manifest["bundle_id"]
    assert record["manifest_sha256"] == sha256_bytes(
        (formal_run / "manifest.json").read_bytes()
    )

    # The sync is deterministic: two independent outputs are byte-identical.
    assert _snapshot(output_a) == _snapshot(output_b)
