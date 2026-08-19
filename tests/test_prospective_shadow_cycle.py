from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.decision_support import prospective_shadow_cycle as cycle
from src.research.factor_knowledge_registry import FactorKnowledgeRegistry

CUTOVER = Path("configs/operations/prospective_shadow_cutover_v1.yaml")
US_SPEC = Path(
    "configs/research_paradigms/us_structured_pool_hierarchical_rotation_v2.yaml"
)


def _prices(path: Path, *, last_date: str = "2026-07-31") -> Path:
    dates = pd.date_range("2024-01-02", last_date, freq="B")
    rows = []
    for symbol in ("AAA", "QQQ", "^SOX"):
        for index, day in enumerate(dates):
            close = 100.0 + index * 0.1
            rows.append(
                {
                    "date": day.date().isoformat(),
                    "symbol": symbol,
                    "open": close - 0.2,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 1000 + index,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _registry(path: Path) -> Path:
    FactorKnowledgeRegistry(path)
    return path


def _install_runtime_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_rotation(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "evidence_manifest.json").write_text(
            json.dumps({"manifest_identity_sha256": "rotation-manifest"}),
            encoding="utf-8",
        )
        return {
            "research_only": True,
            "trade_ready": False,
            "performance_evaluated": False,
            "market": "us",
        }

    def fake_ticket(**kwargs):
        ledger = Path(kwargs["ledger_dir"]) / kwargs["market"]
        ledger.mkdir(parents=True, exist_ok=True)
        ticket_path = ledger / f"{kwargs['as_of_date']}.json"
        payload = {
            "ticket_identity_sha256": "ticket-identity-001",
            "market": kwargs["market"],
            "as_of_date": kwargs["as_of_date"],
            "trade_ready": False,
        }
        ticket_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(cycle, "run_hierarchical_pool_rotation", fake_rotation)
    monkeypatch.setattr(cycle, "build_shadow_decision_ticket", fake_ticket)


def test_cutover_contract_explicitly_repurposes_prior_reserved_evidence() -> None:
    payload = cycle.load_cutover_contract(CUTOVER)
    disposition = payload["reserved_evidence_disposition"]

    assert payload["effective_as_of_date"] == "2026-07-31"
    assert payload["first_actionable_session"] == "2026-08-03"
    assert payload["truth_boundary"]["trade_ready"] is False
    assert set(payload["markets"]) == {"us"}
    assert disposition["previous_plan"]["start"] == "2026-07-01"
    assert disposition["repurposed_for_forward_shadow_use"] is True
    assert disposition[
        "independent_validation_claim_prohibited_for_existing_families"
    ] is True
    assert payload["future_multifactor_validation"][
        "requires_new_reserved_window_after_factor_and_portfolio_freeze"
    ] is True


def test_us_cycle_binds_inputs_and_remains_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runtime_stubs(monkeypatch)
    prices = _prices(tmp_path / "prices.csv")
    registry = _registry(tmp_path / "factor_registry.db")

    first = cycle.run_prospective_shadow_cycle(
        market="us",
        as_of_date="2026-07-31",
        prices_csv=prices,
        spec_path=US_SPEC,
        registry_db=registry,
        ledger_dir=tmp_path / "ledger",
        workspace_dir=tmp_path / "workspace",
        cutover_contract=CUTOVER,
    )
    second = cycle.run_prospective_shadow_cycle(
        market="us",
        as_of_date="2026-07-31",
        prices_csv=prices,
        spec_path=US_SPEC,
        registry_db=registry,
        ledger_dir=tmp_path / "ledger",
        workspace_dir=tmp_path / "workspace",
        cutover_contract=CUTOVER,
    )

    assert first["run_identity_sha256"] == second["run_identity_sha256"]
    assert first["mode"] == "diagnostic_only"
    assert first["research_only"] is True
    assert first["trade_ready"] is False
    assert first["automatic_order_routing"] is False
    assert first["performance_evaluated"] is False
    assert first["independent_validation_claim_allowed"] is False
    assert first["price_summary"]["last_date"] == "2026-07-31"
    assert first["ticket_identity_sha256"] == "ticket-identity-001"


def test_prices_must_not_extend_beyond_or_stop_before_as_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_runtime_stubs(monkeypatch)
    registry = _registry(tmp_path / "factor_registry.db")

    with pytest.raises(ValueError, match="future date"):
        cycle.run_prospective_shadow_cycle(
            market="us",
            as_of_date="2026-07-31",
            prices_csv=_prices(tmp_path / "future.csv", last_date="2026-08-03"),
            spec_path=US_SPEC,
            registry_db=registry,
            ledger_dir=tmp_path / "ledger-future",
            workspace_dir=tmp_path / "workspace-future",
            cutover_contract=CUTOVER,
        )

    with pytest.raises(ValueError, match="does not match as-of"):
        cycle.run_prospective_shadow_cycle(
            market="us",
            as_of_date="2026-07-31",
            prices_csv=_prices(tmp_path / "stale.csv", last_date="2026-07-30"),
            spec_path=US_SPEC,
            registry_db=registry,
            ledger_dir=tmp_path / "ledger-stale",
            workspace_dir=tmp_path / "workspace-stale",
            cutover_contract=CUTOVER,
        )


def test_missing_acknowledgement_or_independent_claim_prohibition_fails(
    tmp_path: Path,
) -> None:
    payload = yaml.safe_load(CUTOVER.read_text(encoding="utf-8"))
    payload["acknowledgement"]["recorded"] = False
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="acknowledgement"):
        cycle.load_cutover_contract(invalid)

    payload = yaml.safe_load(CUTOVER.read_text(encoding="utf-8"))
    payload["reserved_evidence_disposition"][
        "independent_validation_claim_prohibited_for_existing_families"
    ] = False
    invalid_claim = tmp_path / "invalid-claim.yaml"
    invalid_claim.write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="claim prohibition"):
        cycle.load_cutover_contract(invalid_claim)
