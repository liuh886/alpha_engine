"""Convert multi-factor portfolio outputs into shadow-ledger rotation artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

REQUIRED_HIERARCHICAL_FILES = (
    "pool_identity.json",
    "basket_score_history.json",
    "portfolio_state_history.json",
    "evidence_manifest.json",
)
REQUIRED_MULTIFACTOR_FILES = (
    "multifactor_scores.json",
    "portfolio_history.json",
    "decision.json",
    "evidence_manifest.json",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _verify_manifest(directory: Path, required_files: tuple[str, ...]) -> dict[str, Any]:
    for name in required_files:
        if not (directory / name).is_file():
            raise ValueError(f"artifact directory is missing {name}: {directory}")
    manifest = _load_json(directory / "evidence_manifest.json")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("artifact evidence manifest is missing outputs")
    for name, expected in outputs.items():
        path = directory / str(name)
        if not path.is_file() or _sha256_file(path) != expected:
            raise ValueError(f"artifact hash mismatch: {path}")
    return manifest


def _rows(payload: Mapping[str, Any], label: str) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} must contain object rows")
    return [dict(row) for row in rows]


def _latest_context(
    context_rows: list[dict[str, Any]],
    as_of: pd.Timestamp,
) -> dict[str, Any]:
    eligible = [
        row
        for row in context_rows
        if pd.Timestamp(str(row["date"])).normalize() <= as_of
    ]
    if not eligible:
        raise ValueError(f"no hierarchical market context on or before {as_of.date()}")
    return max(eligible, key=lambda row: str(row["date"]))


def build_multifactor_shadow_artifacts(
    *,
    hierarchical_dir: str | Path,
    multifactor_dir: str | Path,
    output_dir: str | Path,
    benchmark: str = "QQQ",
) -> dict[str, Any]:
    """Build a manifest-bound shadow artifact set using multi-factor positions."""

    hierarchical = Path(hierarchical_dir).resolve()
    multifactor = Path(multifactor_dir).resolve()
    output = Path(output_dir).resolve()
    hierarchical_manifest = _verify_manifest(
        hierarchical, REQUIRED_HIERARCHICAL_FILES
    )
    multifactor_manifest = _verify_manifest(multifactor, REQUIRED_MULTIFACTOR_FILES)
    multifactor_decision = _load_json(multifactor / "decision.json")
    if multifactor_decision.get("research_only") is not True:
        raise ValueError("multifactor decision must be research_only")
    if multifactor_decision.get("trade_ready") is not False:
        raise ValueError("multifactor decision must not claim trade readiness")
    if multifactor_decision.get("performance_evaluated") is not False:
        raise ValueError("multifactor decision must not include performance evaluation")

    pool_identity = _load_json(hierarchical / "pool_identity.json")
    basket_payload = _load_json(hierarchical / "basket_score_history.json")
    context_rows = _rows(
        _load_json(hierarchical / "portfolio_state_history.json"),
        "hierarchical portfolio history",
    )
    score_rows = _rows(
        _load_json(multifactor / "multifactor_scores.json"),
        "multifactor scores",
    )
    portfolio_rows = _rows(
        _load_json(multifactor / "portfolio_history.json"),
        "multifactor portfolio history",
    )
    score_by_date: dict[str, list[dict[str, Any]]] = {}
    for row in score_rows:
        score_by_date.setdefault(str(row["date"]), []).append(row)

    security_history: list[dict[str, Any]] = []
    rotation_history: list[dict[str, Any]] = []
    shadow_portfolio_history: list[dict[str, Any]] = []
    previous_selected: set[str] = set()
    for portfolio in sorted(portfolio_rows, key=lambda row: str(row["date"])):
        day = str(portfolio["date"])
        day_timestamp = pd.Timestamp(day).normalize()
        day_scores = score_by_date.get(day, [])
        if not day_scores:
            raise ValueError(f"multifactor portfolio date has no score rows: {day}")
        selected = set(str(symbol) for symbol in portfolio.get("selected_symbols", []))
        weights = {
            str(symbol): float(weight)
            for symbol, weight in dict(portfolio.get("weights", {})).items()
        }
        if selected != {symbol for symbol, weight in weights.items() if weight > 0}:
            raise ValueError(f"multifactor selected symbols and weights differ: {day}")
        score_map = {str(row["symbol"]): row for row in day_scores}
        if selected - set(score_map):
            raise ValueError(f"selected symbols are missing score rows: {day}")
        states: dict[str, str] = {}
        for symbol in score_map:
            if symbol in selected and symbol not in previous_selected:
                states[symbol] = "ENTER"
            elif symbol in selected:
                states[symbol] = "HOLD"
            elif symbol in previous_selected:
                states[symbol] = "EXIT"
            else:
                states[symbol] = "WATCH"
        for symbol, row in sorted(score_map.items()):
            reasons = list(row.get("reason_codes", []))
            reasons.append(f"MULTIFACTOR_STATE_{states[symbol]}")
            security_history.append(
                {
                    "date": day,
                    "basket": str(row.get("basket", "")),
                    "symbol": symbol,
                    "state": states[symbol],
                    "security_composite_percentile": row.get("percentile"),
                    "score_gate_passed": bool(row.get("eligible", False)),
                    "within_basket_selected": symbol in selected,
                    "portfolio_selected": symbol in selected,
                    "reason_codes": sorted(set(reasons)),
                }
            )
        context = _latest_context(context_rows, day_timestamp)
        selected_by_basket: dict[str, list[dict[str, Any]]] = {}
        positions: list[dict[str, Any]] = []
        for symbol in sorted(selected):
            row = score_map[symbol]
            basket = str(row.get("basket", ""))
            selected_entry = {
                "symbol": symbol,
                "state": states[symbol],
                "state_priority": 0,
                "security_composite_percentile": row.get("percentile"),
                "exposure_multiplier": 1.0,
                "state_reason_codes": ["MULTIFACTOR_PORTFOLIO_SELECTED"],
                "trailing_stop_3atr": None,
            }
            selected_by_basket.setdefault(basket, []).append(selected_entry)
            positions.append(
                {
                    "basket": basket,
                    "symbol": symbol,
                    "state": states[symbol],
                    "security_composite_percentile": row.get("percentile"),
                    "target_weight": weights[symbol],
                    "state_multiplier": 1.0,
                    "state_reason_codes": ["MULTIFACTOR_PORTFOLIO_SELECTED"],
                    "trailing_stop_3atr": None,
                }
            )
        selected_baskets = sorted(selected_by_basket)
        rotation_history.append(
            {
                "date": day,
                "actionable_from": None,
                "market": "us",
                "benchmark": benchmark,
                "risk_on": bool(context.get("risk_on", False)),
                "market_regime": context.get("market_regime"),
                "selected_baskets": selected_baskets,
                "selected_symbols_by_basket": selected_by_basket,
                "reason_codes": ["MULTIFACTOR_ROTATION_SELECTION_COMPLETED"],
            }
        )
        gross = float(sum(weights.values()))
        shadow_portfolio_history.append(
            {
                "date": day,
                "actionable_from": None,
                "market": "us",
                "benchmark": benchmark,
                "rotation_date": day,
                "risk_on": bool(context.get("risk_on", False)),
                "market_regime": context.get("market_regime"),
                "selected_baskets": selected_baskets,
                "positions": positions,
                "gross_exposure": gross,
                "cash_weight": float(1.0 - gross),
                "reason_codes": [
                    "MULTIFACTOR_PORTFOLIO_ACTIVE",
                    "HIERARCHICAL_MARKET_REGIME_CONTEXT_ONLY",
                ],
            }
        )
        previous_selected = selected

    output.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, dict[str, Any]] = {
        "pool_identity.json": pool_identity,
        "basket_score_history.json": basket_payload,
        "security_score_history.json": {
            "schema_version": "1.0",
            "experiment_id": multifactor_decision.get("combination_id"),
            "rows": security_history,
        },
        "rotation_history.json": {
            "schema_version": "1.0",
            "experiment_id": multifactor_decision.get("combination_id"),
            "rows": rotation_history,
        },
        "portfolio_state_history.json": {
            "schema_version": "1.0",
            "experiment_id": multifactor_decision.get("combination_id"),
            "rows": shadow_portfolio_history,
        },
    }
    for name, payload in payloads.items():
        _write_json(output / name, payload)
    decision = {
        "schema_version": "1.0",
        "decision": "multifactor_shadow_adapter_ready",
        "experiment_id": multifactor_decision.get("combination_id"),
        "market": "us",
        "benchmark": benchmark,
        "pool_id": pool_identity.get("pool_id"),
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
        "automatic_order_routing": False,
        "hierarchical_positions_used": False,
        "market_regime_context_only": True,
        "portfolio_row_count": len(shadow_portfolio_history),
        "security_score_row_count": len(security_history),
    }
    _write_json(output / "decision.json", decision)
    output_hashes = {
        name: _sha256_file(output / name)
        for name in [*payloads, "decision.json"]
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": multifactor_decision.get("combination_id"),
        "market": "us",
        "inputs": {
            "hierarchical_manifest_sha256": _sha256_file(
                hierarchical / "evidence_manifest.json"
            ),
            "hierarchical_manifest_identity": hierarchical_manifest.get(
                "manifest_identity_sha256"
            ),
            "multifactor_manifest_sha256": _sha256_file(
                multifactor / "evidence_manifest.json"
            ),
            "multifactor_manifest_identity": multifactor_manifest.get(
                "manifest_identity_sha256"
            ),
        },
        "outputs": output_hashes,
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(output / "evidence_manifest.json", manifest)
    return decision
