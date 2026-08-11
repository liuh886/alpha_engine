"""Build immutable research-only daily decision-support tickets.

The shadow desk consumes manifest-bound hierarchical-rotation artifacts and the
FactorRegistry v2 catalog. It never routes orders and never upgrades a research
finding to trade-ready status.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.research.factor_knowledge_registry import FactorKnowledgeRegistry

DECISION_ELIGIBLE_STATUSES = {
    "candidate",
    "market_specific_clue",
    "independent_validation_required",
}
EXCLUDED_STATUSES = {
    "legacy_unverified",
    "data_blocked",
    "rejected",
    "redundant",
    "retired",
}
ACTIONS = {
    "WATCH",
    "ENTER_CANDIDATE",
    "HOLD",
    "REDUCE_CANDIDATE",
    "EXIT_RISK",
}
REQUIRED_ROTATION_FILES = (
    "decision.json",
    "evidence_manifest.json",
    "pool_identity.json",
    "basket_score_history.json",
    "security_score_history.json",
    "rotation_history.json",
    "portfolio_state_history.json",
)


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _rows(payload: Mapping[str, Any], *, label: str) -> list[dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} must contain an object rows list")
    return rows


def _validate_date_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: date,
    label: str,
) -> None:
    for row in rows:
        raw = row.get("date")
        if not raw:
            raise ValueError(f"{label} row is missing date")
        row_date = date.fromisoformat(str(raw))
        if row_date > as_of:
            raise ValueError(f"{label} contains future row {row_date} beyond as-of {as_of}")


def _latest_rows(
    rows: list[dict[str, Any]],
    *,
    as_of: date,
) -> tuple[date, list[dict[str, Any]]]:
    eligible = [row for row in rows if date.fromisoformat(str(row["date"])) <= as_of]
    if not eligible:
        raise ValueError(f"no rows are available on or before {as_of}")
    latest = max(date.fromisoformat(str(row["date"])) for row in eligible)
    return latest, [row for row in eligible if date.fromisoformat(str(row["date"])) == latest]


def _verify_rotation_artifacts(rotation_dir: Path) -> dict[str, dict[str, Any]]:
    missing = [name for name in REQUIRED_ROTATION_FILES if not (rotation_dir / name).exists()]
    if missing:
        raise ValueError("rotation artifact set is incomplete: " + ", ".join(missing))

    payloads = {name: _load_json(rotation_dir / name) for name in REQUIRED_ROTATION_FILES}
    decision = payloads["decision.json"]
    if decision.get("research_only") is not True:
        raise ValueError("shadow desk requires research_only rotation artifacts")
    if decision.get("trade_ready") is not False:
        raise ValueError("shadow desk refuses a rotation artifact claiming trade readiness")
    if decision.get("performance_evaluated") is not False:
        raise ValueError("shadow desk requires a non-performance rotation artifact")

    output_hashes = payloads["evidence_manifest.json"].get("outputs")
    if not isinstance(output_hashes, dict):
        raise ValueError("rotation evidence manifest is missing output hashes")
    for filename, expected in output_hashes.items():
        path = rotation_dir / str(filename)
        if not path.exists():
            raise ValueError(f"manifest output is missing: {filename}")
        if _sha256_file(path) != expected:
            raise ValueError(f"rotation artifact hash mismatch: {filename}")
    return payloads


def _load_factor_context(
    registry: FactorKnowledgeRegistry,
    factor_scores_path: Path | None,
    *,
    as_of: date,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[str]]:
    cards = registry.list_cards()
    cards_by_key = {str(card["stable_factor_key"]): card for card in cards}
    catalog = [
        {
            "card_id": card["card_id"],
            "stable_factor_key": card["stable_factor_key"],
            "factor_version": card["factor_version"],
            "information_family": card["information_family"],
            "status": card["status"],
            "decision_eligible": card["status"] in DECISION_ELIGIBLE_STATUSES,
            "source_report_path": card["source_report_path"],
        }
        for card in cards
    ]
    if factor_scores_path is None:
        return catalog, {}, ["FACTOR_SCORE_INPUT_NOT_PROVIDED"]

    score_rows = _rows(_load_json(factor_scores_path), label="factor score artifact")
    _validate_date_rows(score_rows, as_of=as_of, label="factor score artifact")
    latest_date, latest_rows = _latest_rows(score_rows, as_of=as_of)
    warnings: list[str] = []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in latest_rows:
        key = str(row.get("stable_factor_key", ""))
        symbol = str(row.get("symbol", ""))
        if not key or not symbol:
            raise ValueError("factor score row requires stable_factor_key and symbol")
        card = cards_by_key.get(key)
        if card is None:
            warnings.append(f"UNKNOWN_FACTOR_CARD:{key}")
            continue
        status = str(card["status"])
        by_symbol.setdefault(symbol, []).append(
            {
                "as_of_date": latest_date.isoformat(),
                "card_id": card["card_id"],
                "stable_factor_key": key,
                "factor_version": card["factor_version"],
                "information_family": card["information_family"],
                "status": status,
                "decision_eligible": status in DECISION_ELIGIBLE_STATUSES,
                "score": row.get("score"),
                "percentile": row.get("percentile"),
                "reason_codes": list(row.get("reason_codes", [])),
            }
        )
    return catalog, by_symbol, sorted(set(warnings))


def _load_previous_ticket(ledger_market_dir: Path, as_of: date) -> dict[str, Any] | None:
    candidates: list[tuple[date, Path]] = []
    if not ledger_market_dir.exists():
        return None
    for path in ledger_market_dir.glob("????-??-??.json"):
        try:
            ticket_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if ticket_date < as_of:
            candidates.append((ticket_date, path))
    if not candidates:
        return None
    return _load_json(max(candidates, key=lambda item: item[0])[1])


def _weights_from_ticket(ticket: Mapping[str, Any] | None) -> dict[str, float]:
    if ticket is None:
        return {}
    return {
        str(row["symbol"]): float(row.get("target_weight", 0.0))
        for row in ticket.get("securities", [])
        if isinstance(row, dict) and row.get("symbol")
    }


def _action_for_security(
    *,
    state: str,
    current_weight: float,
    previous_weight: float,
) -> str:
    if state == "EXIT":
        return "EXIT_RISK"
    if state == "REDUCE" or current_weight + 1e-12 < previous_weight:
        return "REDUCE_CANDIDATE"
    if current_weight > 0 and previous_weight <= 0:
        return "ENTER_CANDIDATE"
    if current_weight > 0:
        return "HOLD"
    return "WATCH"


def _build_markdown(ticket: Mapping[str, Any]) -> str:
    market = str(ticket["market"]).upper()
    lines = [
        f"# Alpha Engine Shadow Decision Ticket — {market}",
        "",
        f"**As of:** {ticket['as_of_date']}",
        "**Mode:** diagnostic_only · trade_ready=false",
        f"**Benchmark:** {ticket['market_context']['benchmark']}",
        f"**Market regime:** {ticket['market_context']['market_regime']}",
        f"**Gross exposure:** {ticket['market_context']['gross_exposure']:.2%}",
        f"**Daily exposure change:** {ticket['turnover_budget']['ticket_turnover']:.2f}x",
        f"**Remaining annual turnover budget:** {ticket['turnover_budget']['remaining']:.2f}x",
        "",
        "## Basket attention",
        "",
        "| Basket | Selected | Composite | Breadth |",
        "|---|---:|---:|---:|",
    ]
    for row in ticket["baskets"]:
        composite = row.get("composite_percentile")
        breadth = row.get("breadth_above_sma50")
        composite_text = "" if composite is None else f"{float(composite):.2f}"
        breadth_text = "" if breadth is None else f"{float(breadth):.0%}"
        selected = "yes" if row.get("selected") else "no"
        lines.append(f"| {row['basket']} | {selected} | {composite_text} | {breadth_text} |")
    lines.extend(
        [
            "",
            "## Security states",
            "",
            "| Symbol | Basket | State | Action | Target | Prior | Factor agreement |",
            "|---|---|---|---|---:|---:|---:|",
        ]
    )
    for row in ticket["securities"]:
        lines.append(
            f"| {row['symbol']} | {row.get('basket', '')} | {row['state']} | "
            f"{row['action']} | {row['target_weight']:.2%} | "
            f"{row['previous_weight']:.2%} | {row['eligible_factor_count']} |"
        )
    if ticket["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in ticket["warnings"])
    lines.extend(
        [
            "",
            "---",
            "This is a forward shadow record for research and manual review. "
            "It is not an order, broker instruction, or independently validated "
            "trading recommendation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_immutable(path: Path, payload: str, identity: str) -> None:
    if not path.exists():
        path.write_bytes(payload.encode("utf-8"))
        return
    if path.suffix == ".json":
        if _load_json(path).get("ticket_identity_sha256") != identity:
            raise ValueError(f"immutable shadow ledger conflict: {path}")
        return
    if path.read_text(encoding="utf-8") != payload:
        raise ValueError(f"immutable shadow ledger conflict: {path}")


def _update_ledger_manifest(ledger_market_dir: Path, market: str) -> None:
    entries = []
    for path in sorted(ledger_market_dir.glob("????-??-??.json")):
        ticket = _load_json(path)
        entries.append(
            {
                "as_of_date": ticket["as_of_date"],
                "ticket_identity_sha256": ticket["ticket_identity_sha256"],
                "file_sha256": _sha256_file(path),
                "filename": path.name,
            }
        )
    payload = {
        "schema_version": "1.0",
        "market": market,
        "research_only": True,
        "trade_ready": False,
        "ticket_count": len(entries),
        "tickets": entries,
    }
    (ledger_market_dir / "ledger_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def build_shadow_decision_ticket(
    *,
    rotation_dir: str | Path,
    registry_db: str | Path,
    ledger_dir: str | Path,
    market: str,
    as_of_date: str,
    factor_scores_path: str | Path | None = None,
    annual_turnover_budget: float = 4.0,
) -> dict[str, Any]:
    """Build and persist one immutable daily shadow decision ticket."""

    as_of = date.fromisoformat(as_of_date)
    if annual_turnover_budget <= 0:
        raise ValueError("annual_turnover_budget must be positive")
    rotation_path = Path(rotation_dir).resolve()
    payloads = _verify_rotation_artifacts(rotation_path)
    decision = payloads["decision.json"]
    manifest = payloads["evidence_manifest.json"]
    pool_identity = payloads["pool_identity.json"]
    artifact_market = str(decision.get("market", ""))
    if artifact_market != market:
        raise ValueError(f"market mismatch: artifact={artifact_market}, requested={market}")

    basket_rows = _rows(payloads["basket_score_history.json"], label="basket score history")
    security_rows = _rows(payloads["security_score_history.json"], label="security score history")
    rotation_rows = _rows(payloads["rotation_history.json"], label="rotation history")
    portfolio_rows = _rows(
        payloads["portfolio_state_history.json"], label="portfolio state history"
    )
    for label, rows in (
        ("basket score history", basket_rows),
        ("security score history", security_rows),
        ("rotation history", rotation_rows),
        ("portfolio state history", portfolio_rows),
    ):
        _validate_date_rows(rows, as_of=as_of, label=label)

    basket_date, latest_baskets = _latest_rows(basket_rows, as_of=as_of)
    security_date, latest_security = _latest_rows(security_rows, as_of=as_of)
    rotation_date, latest_rotations = _latest_rows(rotation_rows, as_of=as_of)
    portfolio_date, latest_portfolios = _latest_rows(portfolio_rows, as_of=as_of)
    if len(latest_rotations) != 1 or len(latest_portfolios) != 1:
        raise ValueError("rotation and portfolio histories require one latest row per date")
    portfolio = latest_portfolios[0]

    registry = FactorKnowledgeRegistry(registry_db)
    score_path = None if factor_scores_path is None else Path(factor_scores_path).resolve()
    factor_catalog, scores_by_symbol, factor_warnings = _load_factor_context(
        registry,
        score_path,
        as_of=as_of,
    )

    ledger_market_dir = Path(ledger_dir).resolve() / market
    ledger_market_dir.mkdir(parents=True, exist_ok=True)
    previous_ticket = _load_previous_ticket(ledger_market_dir, as_of)
    previous_weights = _weights_from_ticket(previous_ticket)
    previous_cumulative = float(
        (previous_ticket or {}).get("turnover_budget", {}).get("cumulative", 0.0)
    )

    positions = {
        str(row["symbol"]): dict(row)
        for row in portfolio.get("positions", [])
        if isinstance(row, dict) and row.get("symbol")
    }
    security_by_symbol = {
        str(row["symbol"]): dict(row) for row in latest_security if row.get("symbol")
    }
    symbols = sorted(set(positions) | set(previous_weights) | set(security_by_symbol))
    current_weights: dict[str, float] = {}
    securities: list[dict[str, Any]] = []
    for symbol in symbols:
        position = positions.get(symbol, {})
        score_row = security_by_symbol.get(symbol, {})
        state = str(position.get("state", score_row.get("state", "MISSING")))
        current_weight = float(position.get("target_weight", 0.0))
        previous_weight = float(previous_weights.get(symbol, 0.0))
        current_weights[symbol] = current_weight
        factor_rows = scores_by_symbol.get(symbol, [])
        eligible_factors = [row for row in factor_rows if row["decision_eligible"]]
        excluded_factors = [row for row in factor_rows if not row["decision_eligible"]]
        action = _action_for_security(
            state=state,
            current_weight=current_weight,
            previous_weight=previous_weight,
        )
        if action not in ACTIONS:
            raise AssertionError(action)
        reasons = sorted(
            set(
                list(score_row.get("reason_codes", []))
                + list(position.get("state_reason_codes", []))
                + list(portfolio.get("reason_codes", []))
            )
        )
        securities.append(
            {
                "symbol": symbol,
                "basket": str(position.get("basket", score_row.get("basket", ""))),
                "state": state,
                "action": action,
                "target_weight": current_weight,
                "previous_weight": previous_weight,
                "weight_change": current_weight - previous_weight,
                "security_composite_percentile": score_row.get("security_composite_percentile"),
                "eligible_factor_count": len(eligible_factors),
                "excluded_factor_count": len(excluded_factors),
                "factor_scores": factor_rows,
                "reason_codes": reasons,
            }
        )

    all_weight_symbols = set(current_weights) | set(previous_weights)
    ticket_turnover = float(
        sum(
            abs(current_weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0))
            for symbol in all_weight_symbols
        )
    )
    cumulative = previous_cumulative + ticket_turnover
    warnings = list(factor_warnings)
    if cumulative > annual_turnover_budget + 1e-12:
        warnings.append("ANNUAL_TURNOVER_BUDGET_EXCEEDED")
    if not factor_catalog:
        warnings.append("FACTOR_REGISTRY_EMPTY")
    if any(card["status"] in EXCLUDED_STATUSES for card in factor_catalog):
        warnings.append("EXCLUDED_FACTOR_CARDS_PRESENT_FOR_CONTEXT_ONLY")

    baskets = sorted(
        [
            {
                "basket": str(row["basket"]),
                "selected": bool(row.get("selected", False)),
                "composite_percentile": row.get("composite_percentile"),
                "breadth_above_sma50": row.get("breadth_above_sma50"),
                "median_relative_momentum_63_vs_benchmark": row.get(
                    "median_relative_momentum_63_vs_benchmark"
                ),
                "reason_codes": list(row.get("reason_codes", [])),
            }
            for row in latest_baskets
        ],
        key=lambda row: (
            not row["selected"],
            -float(row["composite_percentile"] or 0.0),
            row["basket"],
        ),
    )

    identity_payload = {
        "schema_version": "1.0",
        "market": market,
        "as_of_date": as_of.isoformat(),
        "rotation_manifest_identity_sha256": manifest.get("manifest_identity_sha256"),
        "rotation_output_hashes": manifest.get("outputs"),
        "pool_membership_identity_sha256": pool_identity.get("membership_identity_sha256"),
        "basket_snapshot_date": basket_date.isoformat(),
        "security_snapshot_date": security_date.isoformat(),
        "rotation_snapshot_date": rotation_date.isoformat(),
        "portfolio_snapshot_date": portfolio_date.isoformat(),
        "previous_ticket_identity_sha256": (
            None if previous_ticket is None else previous_ticket["ticket_identity_sha256"]
        ),
        "annual_turnover_budget": annual_turnover_budget,
        "factor_score_sha256": None if score_path is None else _sha256_file(score_path),
        "factor_cards": [
            {
                "card_id": row["card_id"],
                "factor_version": row["factor_version"],
                "status": row["status"],
            }
            for row in factor_catalog
        ],
        "baskets": baskets,
        "securities": securities,
    }
    ticket_identity = _sha256_bytes(_canonical_json(identity_payload).encode("utf-8"))
    ticket = {
        "schema_version": "1.0",
        "ticket_identity_sha256": ticket_identity,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "as_of_date": as_of.isoformat(),
        "actionable_from": portfolio.get("actionable_from"),
        "mode": "diagnostic_only",
        "research_only": True,
        "trade_ready": False,
        "automatic_order_routing": False,
        "performance_evaluated": False,
        "rotation_manifest_identity_sha256": manifest.get("manifest_identity_sha256"),
        "pool": {
            "pool_id": pool_identity.get("pool_id"),
            "candidate_count": pool_identity.get("candidate_count"),
            "basket_count": pool_identity.get("basket_count"),
            "membership_identity_sha256": pool_identity.get("membership_identity_sha256"),
        },
        "market_context": {
            "benchmark": portfolio.get("benchmark"),
            "risk_on": bool(portfolio.get("risk_on", False)),
            "market_regime": portfolio.get("market_regime"),
            "selected_baskets": list(portfolio.get("selected_baskets", [])),
            "gross_exposure": float(portfolio.get("gross_exposure", 0.0)),
            "cash_weight": float(portfolio.get("cash_weight", 1.0)),
        },
        "snapshot_dates": {
            "basket": basket_date.isoformat(),
            "security": security_date.isoformat(),
            "rotation": rotation_date.isoformat(),
            "portfolio": portfolio_date.isoformat(),
        },
        "factor_catalog": factor_catalog,
        "baskets": baskets,
        "securities": securities,
        "turnover_budget": {
            "annual_budget": float(annual_turnover_budget),
            "previous_cumulative": previous_cumulative,
            "ticket_turnover": ticket_turnover,
            "cumulative": cumulative,
            "remaining": max(0.0, float(annual_turnover_budget) - cumulative),
            "within_budget": cumulative <= annual_turnover_budget + 1e-12,
        },
        "warnings": sorted(set(warnings)),
        "disclaimer": (
            "Forward shadow record for research and manual review only; not an "
            "order, broker instruction, or independently validated trading recommendation."
        ),
    }

    json_path = ledger_market_dir / f"{as_of.isoformat()}.json"
    markdown_path = ledger_market_dir / f"{as_of.isoformat()}.md"
    _write_immutable(
        json_path,
        json.dumps(ticket, ensure_ascii=False, indent=2, sort_keys=True),
        ticket_identity,
    )
    existing_ticket = _load_json(json_path)
    _write_immutable(markdown_path, _build_markdown(existing_ticket), ticket_identity)
    _update_ledger_manifest(ledger_market_dir, market)
    return existing_ticket
