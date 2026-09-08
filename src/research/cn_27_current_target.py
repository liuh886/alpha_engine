"""Governed current-target publisher for the CN_27 V1.3 allocation model.

Dormant by frozen contract: ``configs/models/cn_27_v1_3.yaml`` declares
``current_target_activation: not_applicable_until_governed_prospective_source_is_available``.
Until a sealed refreshed formal run extends beyond the frozen evidence cutoff,
every call fails closed with ``status="data_blocked"`` and no weights are
produced. Once governed fan-in advances the active formal run, the same code
path publishes the recomputed frozen-recipe target with no contract change.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.artifacts.formal_bundle_reader import FormalBundleReadError, load_formal_run
from src.research.ranker_current_target import (
    _canonical_sha,
    _signal_payload,
    _turnover,
    load_previous_state,
)

MODEL_ID = "cn_27_v1_3"
MODEL_FAMILY_ID = "cn_27_rotation"
MODEL_KIND = "rules_based_allocation"
MODEL_CONTRACT = Path("configs/models/cn_27_v1_3.yaml")
ADAPTER_ID = "cn_27_current_target_v1"
BENCHMARK = "000300"
DEFENSIVE_SLEEVE = "515180"
FROZEN_EVIDENCE_CUTOFF = "2026-09-04"
REBALANCE_SESSIONS = 30


class CN27CurrentTargetError(ValueError):
    """Raised when the CN_27 V1.3 current target cannot be published."""

    def __init__(self, message: str, *, status: str) -> None:
        super().__init__(message)
        self.status = status


def _blocked(message: str) -> CN27CurrentTargetError:
    return CN27CurrentTargetError(message, status="data_blocked")


def _invalid(message: str) -> CN27CurrentTargetError:
    return CN27CurrentTargetError(message, status="invalid_evidence")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_model_contract(repository_root: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(
            (repository_root / MODEL_CONTRACT).read_text(encoding="utf-8")
        )
    except (OSError, yaml.YAMLError) as exc:
        raise _invalid(f"CN_27 model contract is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise _invalid("CN_27 model contract must be an object")
    for field, expected in (
        ("model_id", MODEL_ID),
        ("market", "cn"),
        ("research_only", True),
        ("trade_ready", False),
    ):
        if payload.get(field) != expected:
            raise _invalid(f"CN_27 model contract drifted: {field}")
    return payload


def _activation_reason(contract: Mapping[str, Any]) -> str:
    publication = contract.get("formal_publication")
    activation = (
        publication.get("current_target_activation")
        if isinstance(publication, Mapping)
        else None
    )
    if not isinstance(activation, str) or not activation:
        raise _invalid("CN_27 model contract current-target activation is missing")
    return activation


def _target_at_cutoff(
    positions: list[dict[str, Any]], signal_date: str
) -> dict[str, float]:
    rows = [
        row
        for row in positions
        if isinstance(row, dict) and str(row.get("date", "")) == signal_date
    ]
    if not rows:
        raise _invalid(f"CN_27 refreshed positions do not cover {signal_date}")
    target = {str(row["instrument"]): float(row["weight"]) for row in rows}
    if len(target) != len(rows):
        raise _invalid("CN_27 target instruments are not unique")
    if any(weight < 0.0 for weight in target.values()):
        raise _invalid("CN_27 forbids short sleeves in the current target")
    if abs(sum(target.values()) - 1.0) > 1e-9:
        raise _invalid("CN_27 target weights do not sum to one")
    return dict(sorted(target.items()))


def _asymmetric_cost(
    *, previous: Mapping[str, float], target: Mapping[str, float], contract: Mapping[str, Any]
) -> tuple[float, str]:
    costs = contract.get("costs")
    if not isinstance(costs, Mapping):
        raise _invalid("CN_27 model contract costs block is missing")
    try:
        stock_buy = float(costs["stock_buy_rate"])
        stock_sell = float(costs["stock_sell_rate"])
        etf_buy = float(costs["etf_buy_rate"])
        etf_sell = float(costs["etf_sell_rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid(f"CN_27 model contract cost rates are invalid: {exc}") from exc
    total = 0.0
    for name in set(previous) | set(target):
        delta = target.get(name, 0.0) - previous.get(name, 0.0)
        if name in (DEFENSIVE_SLEEVE, "CASH"):
            buy, sell = (etf_buy, etf_sell) if name == DEFENSIVE_SLEEVE else (0.0, 0.0)
        else:
            buy, sell = stock_buy, stock_sell
        total += max(delta, 0.0) * buy + max(-delta, 0.0) * sell
    return total, "asymmetric instrument-level buy/sell weight change"


def score_cn_27_current_target(
    *,
    formal_root: Path,
    ledger_dir: Path,
    signal_date: str,
    market_cutoff: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Publish the frozen-recipe CN_27 target, or fail closed as data_blocked."""

    root = repository_root.resolve()
    contract = _load_model_contract(root)
    activation = _activation_reason(contract)

    formal_dir = Path(formal_root).resolve()
    try:
        relative_root = formal_dir.relative_to(root)
    except ValueError as exc:
        raise _invalid(f"CN_27 formal root escapes repository: {formal_dir}") from exc
    try:
        active = load_formal_run(root, MODEL_ID, relative_root=relative_root)
    except FormalBundleReadError as exc:
        raise _invalid(f"CN_27 active formal run is unreadable: {exc}") from exc
    manifest = active.manifest
    if (
        manifest.get("model_version_id") != MODEL_ID
        or manifest.get("model_family_id") != MODEL_FAMILY_ID
        or manifest.get("model_kind") != MODEL_KIND
        or manifest.get("publication_channel") != "formal"
        or manifest.get("publication_status") != "accepted_formal_baseline"
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        raise _invalid("CN_27 active formal run identity changed")

    prospective_cutoff = active.evidence_cutoff
    if not prospective_cutoff > FROZEN_EVIDENCE_CUTOFF:
        raise _blocked(
            "CN_27 current target is dormant: no governed prospective source "
            f"beyond {FROZEN_EVIDENCE_CUTOFF} "
            f"(formal_publication.current_target_activation={activation})"
        )
    if signal_date != prospective_cutoff:
        if signal_date > prospective_cutoff:
            raise _blocked(
                f"CN_27 signal {signal_date} is beyond the governed prospective "
                f"cutoff {prospective_cutoff}"
            )
        raise _invalid(
            f"CN_27 signal {signal_date} predates the governed prospective "
            f"cutoff {prospective_cutoff}"
        )

    try:
        state = active.refresh_state()
    except FormalBundleReadError as exc:
        raise _invalid(f"CN_27 refreshed state is incomplete: {exc}") from exc
    if not isinstance(state, Mapping):
        raise _invalid("CN_27 refreshed state is invalid")
    lineage = state.get("freshness")
    if not isinstance(lineage, Mapping) or lineage.get("model_selection_reopened") is not False:
        raise _invalid("CN_27 refreshed run reopened model selection")
    positions = state.get("positions")
    if not isinstance(positions, list) or not positions:
        raise _invalid("CN_27 refreshed positions are unavailable")
    target = _target_at_cutoff(positions, signal_date)

    portfolio_file = active.manifest_path.parent / "portfolio.json"
    if not portfolio_file.is_file():
        raise _invalid("CN_27 sealed portfolio file is missing")
    try:
        previous_date, previous = load_previous_state(
            formal_package=portfolio_file,
            ledger_dir=Path(ledger_dir),
        )
    except ValueError as exc:
        raise _invalid(f"CN_27 previous state is invalid: {exc}") from exc

    combination = contract.get("factor_model", {}).get("combination", {})
    factor_evidence = {
        "model_family_id": MODEL_FAMILY_ID,
        "signal_date": signal_date,
        "factors": dict(combination) if isinstance(combination, Mapping) else {},
        "normalization": contract.get("factor_model", {}).get("normalization"),
        "freshness": "frozen_contract",
        "library_sources": [f"{MODEL_CONTRACT.as_posix()}#factor_model"],
    }
    cost, cost_formula = _asymmetric_cost(
        previous=previous, target=target, contract=contract
    )
    report = state.get("report")
    pending_execution = False
    if isinstance(report, list):
        pending_execution = any(
            isinstance(row, Mapping)
            and str(row.get("date", "")) == signal_date
            and bool(row.get("pending_execution"))
            for row in report
        )
    payload = _signal_payload(
        model_version_id=MODEL_ID,
        model_family_id=MODEL_FAMILY_ID,
        signal_date=signal_date,
        market_cutoff=market_cutoff,
        previous_weights=previous,
        target_weights=target,
        factor_evidence=factor_evidence,
        model_identity={
            "formal_bundle_id": manifest.get("bundle_id"),
            "formal_run_id": active.run_id,
            "frozen_evidence_cutoff": FROZEN_EVIDENCE_CUTOFF,
            "prospective_evidence_cutoff": prospective_cutoff,
            "formal_manifest_sha256": _sha256(active.manifest_path),
            "model_config_path": MODEL_CONTRACT.as_posix(),
            "model_config_sha256": _sha256(root / MODEL_CONTRACT),
            "current_target_activation": activation,
        },
        reason_code="cn_27_v1_3_scheduled_monthly_target",
        diagnostics={
            "previous_signal_date": previous_date,
            "frozen_evidence_cutoff": FROZEN_EVIDENCE_CUTOFF,
            "prospective_evidence_cutoff": prospective_cutoff,
            "rebalance_sessions": REBALANCE_SESSIONS,
            "holding_count": len(target),
            "defensive_sleeve_weight": target.get(DEFENSIVE_SLEEVE, 0.0),
            "cash_weight": target.get("CASH", 0.0),
            "pending_execution_retry": pending_execution,
            "cost_formula": cost_formula,
            "model_selection_reopened": False,
        },
    )
    payload["estimated_transaction_cost"] = cost
    payload["estimated_transaction_cost_bps"] = None
    payload["turnover_units"] = _turnover(previous, target)
    payload["fingerprint"] = _canonical_sha(
        {key: value for key, value in payload.items() if key != "fingerprint"}
    )
    return payload


def prospective_source_status(
    *, formal_root: Path, repository_root: Path
) -> dict[str, Any]:
    """Report whether a governed prospective source exists, without publishing."""

    root = repository_root.resolve()
    contract = _load_model_contract(root)
    activation = _activation_reason(contract)
    formal_dir = Path(formal_root).resolve()
    try:
        relative_root = formal_dir.relative_to(root)
    except ValueError as exc:
        raise _invalid(f"CN_27 formal root escapes repository: {formal_dir}") from exc
    try:
        active = load_formal_run(root, MODEL_ID, relative_root=relative_root)
    except FormalBundleReadError as exc:
        raise _invalid(f"CN_27 active formal run is unreadable: {exc}") from exc
    available = bool(active.evidence_cutoff > FROZEN_EVIDENCE_CUTOFF)
    return {
        "model_version_id": MODEL_ID,
        "adapter_id": ADAPTER_ID,
        "frozen_evidence_cutoff": FROZEN_EVIDENCE_CUTOFF,
        "active_evidence_cutoff": active.evidence_cutoff,
        "prospective_source_available": available,
        "current_target_activation": activation,
        "research_only": True,
        "trade_ready": False,
    }
