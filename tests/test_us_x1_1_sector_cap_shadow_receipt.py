from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.research.us87_sector_style import load_pool_symbols
from src.research.us_x1_1_sector_cap_shadow_receipt import (
    append_receipt_index,
    create_receipt,
)

CONTRACT = Path("configs/research_experiments/us_x1_1_sector_cap_shadow_v1.yaml")
SCHEMA = Path("schemas/research/us_x1_1_sector_cap_shadow_receipt_v1.schema.json")
POOL = Path("configs/research_universes/us_selected_equities_v2.yaml")


def _snapshot(path: Path, signal_date: str = "2026-08-04") -> Path:
    symbols = load_pool_symbols(POOL)
    frame = pd.DataFrame(
        {
            "datetime": [signal_date] * len(symbols),
            "instrument": symbols,
            "score": [float(len(symbols) - index) for index in range(len(symbols))],
            "listed": [True] * len(symbols),
            "tradable": [True] * len(symbols),
            "suspended": [False] * len(symbols),
            "price_available": [True] * len(symbols),
        }
    )
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def _create(tmp_path: Path, suffix: str = "a") -> dict[str, object]:
    return create_receipt(
        contract_path=CONTRACT.resolve(),
        score_snapshot_path=_snapshot(tmp_path / f"scores_{suffix}.csv").resolve(),
        provider_snapshot_identity="provider_snapshot_test_v1",
        source_data_cutoff="2026-08-04",
        receipt_created_at_utc="2026-08-04T22:30:00Z",
        repository_commit="abcdef1234567890",
        workflow_run_id="synthetic-contract-test",
        output_root=(tmp_path / f"receipts_{suffix}").resolve(),
        index_path=(tmp_path / f"index_{suffix}.jsonl").resolve(),
    )


def test_receipt_is_schema_valid_and_pre_outcome(tmp_path: Path) -> None:
    result = _create(tmp_path)
    receipt = result["receipt"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)

    assert receipt["outcomes_available"] is False
    assert receipt["summary"]["score_rows"] == 87
    assert receipt["summary"]["baseline_names"] == 15
    assert receipt["summary"]["challenger_names"] == 15
    assert receipt["summary"]["challenger_max_sector_weight"] <= 4 / 15 + 1e-12
    assert math.isclose(
        float(receipt["summary"]["baseline_expected_turnover"]),
        0.5,
        rel_tol=0,
        abs_tol=1e-12,
    )
    assert math.isclose(
        float(receipt["summary"]["challenger_expected_turnover"]),
        0.5,
        rel_tol=0,
        abs_tol=1e-12,
    )

    receipt_root = Path(str(result["receipt_root"]))
    audit = pd.read_csv(receipt_root / "scores_and_selections.csv")
    assert len(audit) == 87
    assert int(audit["baseline_selected"].sum()) == 15
    assert int(audit["challenger_selected"].sum()) == 15
    challenger = pd.read_csv(receipt_root / "challenger_holdings.csv")
    assert int(challenger.groupby("sector").size().max()) <= 4


def test_receipt_materialization_is_exact_for_identical_inputs(tmp_path: Path) -> None:
    first = _create(tmp_path, "a")
    second = _create(tmp_path, "b")
    assert first["receipt"] == second["receipt"]
    assert first["manifest"] == second["manifest"]
    first_root = Path(str(first["receipt_root"]))
    second_root = Path(str(second["receipt_root"]))
    first_files = {
        path.name: path.read_bytes()
        for path in first_root.iterdir()
        if path.is_file()
    }
    second_files = {
        path.name: path.read_bytes()
        for path in second_root.iterdir()
        if path.is_file()
    }
    assert first_files == second_files


def test_receipt_rejects_non_prospective_signal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not prospective"):
        create_receipt(
            contract_path=CONTRACT.resolve(),
            score_snapshot_path=_snapshot(
                tmp_path / "past.csv", "2026-08-03"
            ).resolve(),
            provider_snapshot_identity="provider_snapshot_test_v1",
            source_data_cutoff="2026-08-03",
            receipt_created_at_utc="2026-08-03T22:30:00Z",
            repository_commit="abcdef1234567890",
            workflow_run_id="synthetic-contract-test",
            output_root=(tmp_path / "past_receipts").resolve(),
            index_path=(tmp_path / "past_index.jsonl").resolve(),
        )


def test_receipt_rejects_incomplete_or_outcome_bearing_snapshot(
    tmp_path: Path,
) -> None:
    path = _snapshot(tmp_path / "invalid.csv")
    frame = pd.read_csv(path)
    frame["forward_return"] = 0.10
    frame.to_csv(path, index=False, lineterminator="\n")
    with pytest.raises(ValueError, match="columns must be exactly"):
        create_receipt(
            contract_path=CONTRACT.resolve(),
            score_snapshot_path=path.resolve(),
            provider_snapshot_identity="provider_snapshot_test_v1",
            source_data_cutoff="2026-08-04",
            receipt_created_at_utc="2026-08-04T22:30:00Z",
            repository_commit="abcdef1234567890",
            workflow_run_id="synthetic-contract-test",
            output_root=(tmp_path / "invalid_receipts").resolve(),
            index_path=(tmp_path / "invalid_index.jsonl").resolve(),
        )


def test_ineligible_names_are_audited_not_silently_removed(tmp_path: Path) -> None:
    path = _snapshot(tmp_path / "eligibility.csv")
    frame = pd.read_csv(path)
    top_name = str(frame.iloc[0]["instrument"])
    frame.loc[0, "suspended"] = True
    frame.loc[0, "tradable"] = False
    frame.to_csv(path, index=False, lineterminator="\n")
    result = create_receipt(
        contract_path=CONTRACT.resolve(),
        score_snapshot_path=path.resolve(),
        provider_snapshot_identity="provider_snapshot_test_v1",
        source_data_cutoff="2026-08-04",
        receipt_created_at_utc="2026-08-04T22:30:00Z",
        repository_commit="abcdef1234567890",
        workflow_run_id="synthetic-contract-test",
        output_root=(tmp_path / "eligibility_receipts").resolve(),
        index_path=(tmp_path / "eligibility_index.jsonl").resolve(),
    )
    receipt_root = Path(str(result["receipt_root"]))
    audit = pd.read_csv(receipt_root / "scores_and_selections.csv")
    row = audit.loc[audit["instrument"] == top_name].iloc[0]
    assert not bool(row["eligible"])
    assert row["challenger_selection_reason"] == "ineligible"
    assert result["receipt"]["summary"]["eligible_score_rows"] == 86


def test_append_only_index_rejects_duplicate_signal_date(tmp_path: Path) -> None:
    index = tmp_path / "index.jsonl"
    entry = {
        "receipt_id": "receipt-a",
        "signal_session_date": "2026-08-04",
    }
    append_receipt_index(index, entry)
    with pytest.raises(ValueError, match="receipt identity already exists"):
        append_receipt_index(index, entry)
    with pytest.raises(ValueError, match="signal session already"):
        append_receipt_index(
            index,
            {
                "receipt_id": "receipt-b",
                "signal_session_date": "2026-08-04",
            },
        )
