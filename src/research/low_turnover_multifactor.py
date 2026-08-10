"""Compose the first frozen, low-turnover, multi-family diagnostic candidate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.factor_knowledge_registry import FactorKnowledgeRegistry

REQUIRED_FUNDAMENTAL_FIELDS = {
    "date",
    "symbol",
    "stable_factor_key",
    "percentile",
}
REQUIRED_BASKET_FIELDS = {"date", "basket"}
REQUIRED_PRICE_FIELDS = {"date", "symbol", "close"}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
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


def _repository_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise ValueError(f"unable to resolve repository root from {path}")


def _verify_sibling_manifest(artifact_path: Path) -> tuple[dict[str, Any], str]:
    manifest_path = artifact_path.parent / "evidence_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"missing sibling evidence manifest: {artifact_path}")
    manifest = _load_json(manifest_path)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError(f"evidence manifest outputs are missing: {manifest_path}")
    expected = outputs.get(artifact_path.name)
    if expected != _sha256_file(artifact_path):
        raise ValueError(f"artifact hash mismatch: {artifact_path.name}")
    return manifest, _sha256_file(manifest_path)


def load_multifactor_contract(
    path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    resolved = Path(path).resolve()
    contract = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("multifactor contract must be a YAML mapping")
    if contract.get("status") != "frozen_pre_evaluation":
        raise ValueError("multifactor contract is not frozen")
    truth = contract.get("truth_boundary", {})
    if truth.get("research_only") is not True or truth.get("trade_ready") is not False:
        raise ValueError("multifactor truth boundary is invalid")
    factors = contract.get("factors")
    if not isinstance(factors, list) or not factors:
        raise ValueError("multifactor contract has no factors")
    maximum = int(contract["selection_contract"]["maximum_primary_factors"])
    if len(factors) > maximum:
        raise ValueError("multifactor contract exceeds maximum factor count")
    keys = [str(row["stable_factor_key"]) for row in factors]
    if len(keys) != len(set(keys)):
        raise ValueError("multifactor contract contains duplicate factor keys")
    families = {str(row["information_family"]) for row in factors}
    if len(families) < int(contract["selection_contract"]["minimum_information_families"]):
        raise ValueError("multifactor contract has insufficient information families")
    weights = [float(row["weight"]) for row in factors]
    if abs(sum(weights) - 1.0) > 1e-12:
        raise ValueError("multifactor weights must sum to one")
    if contract["selection_contract"].get("equal_weight_only") is True:
        expected = 1.0 / len(weights)
        if any(abs(weight - expected) > 1e-12 for weight in weights):
            raise ValueError("multifactor contract requires equal weights")
    root = _repository_root(resolved)
    pool_path = root / str(contract["pool_spec"])
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict):
        raise ValueError("multifactor pool must be a YAML mapping")
    return contract, pool, resolved, pool_path


def _pool_membership(pool: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    basket_by_symbol: dict[str, str] = {}
    for basket, meta in pool.get("baskets", {}).items():
        for symbol in meta.get("symbols", []):
            canonical = str(symbol).upper()
            if canonical in basket_by_symbol:
                raise ValueError(f"duplicate pool symbol: {canonical}")
            basket_by_symbol[canonical] = str(basket)
    references = [str(symbol).upper() for symbol in pool.get("references", {})]
    return basket_by_symbol, references


def _load_fundamental_scores(path: Path, factor_keys: set[str]) -> pd.DataFrame:
    payload = _load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("fundamental score artifact must contain rows")
    frame = pd.DataFrame(rows)
    missing = sorted(REQUIRED_FUNDAMENTAL_FIELDS - set(frame.columns))
    if missing:
        raise ValueError("fundamental score artifact missing fields: " + ", ".join(missing))
    frame = frame[list(REQUIRED_FUNDAMENTAL_FIELDS | {"eligible"} & set(frame.columns))].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["stable_factor_key"] = frame["stable_factor_key"].astype(str).str.strip()
    frame["percentile"] = pd.to_numeric(frame["percentile"], errors="coerce")
    frame = frame[frame["stable_factor_key"].isin(factor_keys)].copy()
    if frame.empty:
        raise ValueError("fundamental score artifact has no configured factor rows")
    if frame.duplicated(["date", "symbol", "stable_factor_key"]).any():
        raise ValueError("fundamental score artifact contains duplicate identities")
    if "eligible" not in frame:
        frame["eligible"] = frame["percentile"].notna()
    else:
        frame["eligible"] = frame["eligible"].fillna(False).astype(bool)
    return frame.sort_values(["date", "symbol", "stable_factor_key"])


def _load_basket_scores(path: Path, factors: list[Mapping[str, Any]]) -> pd.DataFrame:
    payload = _load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError("basket score artifact must contain rows")
    frame = pd.DataFrame(rows)
    missing = sorted(REQUIRED_BASKET_FIELDS - set(frame.columns))
    if missing:
        raise ValueError("basket score artifact missing fields: " + ", ".join(missing))
    required_fields = [str(row["source_percentile_field"]) for row in factors]
    missing_fields = sorted(set(required_fields) - set(frame.columns))
    if missing_fields:
        raise ValueError(
            "basket score artifact missing percentile fields: " + ", ".join(missing_fields)
        )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["basket"] = frame["basket"].astype(str).str.strip()
    if frame.duplicated(["date", "basket"]).any():
        raise ValueError("basket score artifact contains duplicate identities")
    for field in required_fields:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame.sort_values(["date", "basket"])


def _load_prices(path: Path, required_symbols: set[str]) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": "string"})
    missing = sorted(REQUIRED_PRICE_FIELDS - set(frame.columns))
    if missing:
        raise ValueError("prices missing fields: " + ", ".join(missing))
    frame = frame[["date", "symbol", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame[["date", "close"]].isna().any().any() or (frame["close"] <= 0).any():
        raise ValueError("prices contain invalid dates or closes")
    frame = frame[frame["symbol"].isin(required_symbols)].copy()
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("prices contain duplicate date-symbol identities")
    missing_symbols = sorted(required_symbols - set(frame["symbol"].unique()))
    if missing_symbols:
        raise ValueError("prices missing frozen symbols: " + ", ".join(missing_symbols))
    return frame.sort_values(["symbol", "date"])


def _relationship_gate(
    path: Path,
    factor_keys: list[str],
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    payload = _load_json(path)
    if (
        payload.get("relationship_contract_id")
        != contract["relationship_gate"]["relationship_contract_id"]
    ):
        raise ValueError("relationship contract identity mismatch")
    factors = {
        str(row["stable_factor_key"]): row
        for row in payload.get("factors", [])
        if isinstance(row, dict) and row.get("stable_factor_key")
    }
    missing = sorted(set(factor_keys) - set(factors))
    if missing:
        raise ValueError("relationship map missing configured factors: " + ", ".join(missing))
    clusters: dict[str, list[str]] = {}
    for key in factor_keys:
        cluster = str(factors[key].get("redundancy_cluster", ""))
        if cluster:
            clusters.setdefault(cluster, []).append(key)
    duplicate_clusters = {key: values for key, values in clusters.items() if len(values) > 1}
    if duplicate_clusters:
        raise ValueError(f"configured factors share redundancy clusters: {duplicate_clusters}")
    pair_keys = {
        tuple(sorted((str(row.get("left")), str(row.get("right")))))
        for row in payload.get("pairs", [])
        if isinstance(row, dict)
    }
    required_pairs = {
        tuple(sorted((left, right)))
        for index, left in enumerate(factor_keys)
        for right in factor_keys[index + 1 :]
    }
    coverage = len(required_pairs & pair_keys) / len(required_pairs) if required_pairs else 1.0
    if coverage < float(contract["relationship_gate"]["minimum_pair_coverage_ratio"]):
        raise ValueError("relationship map pair coverage is incomplete")
    return payload, _sha256_file(path)


def _latest_rows(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    eligible = frame[frame["date"] <= as_of]
    if eligible.empty:
        return eligible
    latest = eligible["date"].max()
    return eligible[eligible["date"] == latest].copy()


def _rank_percentile(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(index=series.index, dtype="float64")
    if len(series) == 1:
        return pd.Series(1.0, index=series.index, dtype="float64")
    return series.rank(method="average", pct=True)


@dataclass(frozen=True)
class Holding:
    symbol: str
    basket: str
    entry_session_index: int


def _build_scores_for_date(
    *,
    as_of: pd.Timestamp,
    contract: Mapping[str, Any],
    basket_by_symbol: Mapping[str, str],
    fundamental_scores: pd.DataFrame,
    basket_scores: pd.DataFrame,
) -> pd.DataFrame:
    security_factors = [row for row in contract["factors"] if str(row["scope"]) == "security"]
    basket_factors = [row for row in contract["factors"] if str(row["scope"]) == "basket"]
    latest_fundamental = _latest_rows(fundamental_scores, as_of)
    latest_basket = _latest_rows(basket_scores, as_of)
    rows = [
        {"date": as_of, "symbol": symbol, "basket": basket}
        for symbol, basket in sorted(basket_by_symbol.items())
    ]
    output = pd.DataFrame(rows)
    for factor in security_factors:
        key = str(factor["stable_factor_key"])
        subset = latest_fundamental[
            (latest_fundamental["stable_factor_key"] == key) & latest_fundamental["eligible"]
        ][["symbol", "percentile"]].rename(columns={"percentile": key})
        output = output.merge(subset, on="symbol", how="left", validate="one_to_one")
    for factor in basket_factors:
        key = str(factor["stable_factor_key"])
        source_field = str(factor["source_percentile_field"])
        subset = latest_basket[["basket", source_field]].rename(columns={source_field: key})
        output = output.merge(subset, on="basket", how="left", validate="many_to_one")
    factor_keys = [str(row["stable_factor_key"]) for row in contract["factors"]]
    weights = {str(row["stable_factor_key"]): float(row["weight"]) for row in contract["factors"]}
    output["component_complete"] = output[factor_keys].notna().all(axis=1)
    output["composite_score"] = sum(
        pd.to_numeric(output[key], errors="coerce") * weights[key] for key in factor_keys
    )
    output.loc[~output["component_complete"], "composite_score"] = pd.NA
    output["selection_percentile"] = pd.NA
    for _, basket_frame in output.groupby("basket", sort=True):
        eligible_index = basket_frame.index[basket_frame["component_complete"]]
        output.loc[eligible_index, "selection_percentile"] = _rank_percentile(
            pd.to_numeric(output.loc[eligible_index, "composite_score"], errors="coerce")
        )
    return output


def _portfolio_history(
    *,
    contract: Mapping[str, Any],
    basket_by_symbol: Mapping[str, str],
    benchmark_dates: pd.DatetimeIndex,
    fundamental_scores: pd.DataFrame,
    basket_scores: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    policy = contract["portfolio"]
    interval = int(policy["evaluation_interval_sessions"])
    dates = list(benchmark_dates[::interval])
    if dates[-1] != benchmark_dates[-1]:
        dates.append(benchmark_dates[-1])
    session_index = {day: index for index, day in enumerate(benchmark_dates)}
    minimum_holding = int(policy["minimum_holding_sessions"])
    entry_threshold = 1.0 - float(policy["entry_top_fraction"])
    retention_threshold = float(policy["retention_min_percentile"])
    max_replacements = int(policy["maximum_replacements_per_basket_per_evaluation"])
    max_holdings = int(policy["maximum_holdings_per_basket"])
    holdings: dict[str, Holding] = {}
    previous_weights: dict[str, float] = {}
    score_rows: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] = []
    completed_holding_sessions: list[int] = []
    turnover_by_year: dict[int, float] = {}

    for as_of in dates:
        scores = _build_scores_for_date(
            as_of=as_of,
            contract=contract,
            basket_by_symbol=basket_by_symbol,
            fundamental_scores=fundamental_scores,
            basket_scores=basket_scores,
        )
        by_symbol = scores.set_index("symbol", drop=False)
        changes_by_basket: dict[str, dict[str, list[str]]] = {}
        for basket in sorted(set(basket_by_symbol.values())):
            kept: list[str] = []
            removed: list[str] = []
            current_session = session_index[as_of]
            for symbol, holding in list(holdings.items()):
                if holding.basket != basket:
                    continue
                row = by_symbol.loc[symbol]
                held = current_session - holding.entry_session_index
                percentile = row["selection_percentile"]
                hard_invalid = not bool(row["component_complete"])
                retention_failed = pd.isna(percentile) or float(percentile) < retention_threshold
                if hard_invalid or (retention_failed and held >= minimum_holding):
                    completed_holding_sessions.append(held)
                    removed.append(symbol)
                    holdings.pop(symbol)
                else:
                    kept.append(symbol)
            slots = max(0, max_holdings - len(kept))
            additions_allowed = min(max_replacements, slots)
            candidates = scores[
                (scores["basket"] == basket)
                & scores["component_complete"]
                & ~scores["symbol"].isin(holdings)
                & (scores["selection_percentile"] >= entry_threshold)
            ].sort_values(["selection_percentile", "symbol"], ascending=[False, True])
            added = list(candidates.head(additions_allowed)["symbol"])
            for symbol in added:
                holdings[symbol] = Holding(symbol, basket, current_session)
            changes_by_basket[basket] = {
                "kept": sorted(kept),
                "added": sorted(added),
                "removed": sorted(removed),
            }

        active_baskets = sorted({holding.basket for holding in holdings.values()})
        weights: dict[str, float] = {}
        for basket in active_baskets:
            symbols = sorted(
                symbol for symbol, holding in holdings.items() if holding.basket == basket
            )
            basket_weight = 1.0 / len(active_baskets)
            for symbol in symbols:
                weights[symbol] = basket_weight / len(symbols)
        all_symbols = set(weights) | set(previous_weights)
        turnover = float(
            sum(
                abs(weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0))
                for symbol in all_symbols
            )
        )
        turnover_by_year[as_of.year] = turnover_by_year.get(as_of.year, 0.0) + turnover
        previous_weights = weights
        for row in scores.to_dict(orient="records"):
            row["date"] = as_of.date().isoformat()
            row["selected"] = row["symbol"] in holdings
            row["target_weight"] = weights.get(row["symbol"], 0.0)
            row["stable_factor_key"] = str(contract["combination_id"])
            score_rows.append(row)
        portfolio_rows.append(
            {
                "date": as_of.date().isoformat(),
                "selected_symbols": sorted(holdings),
                "weights": weights,
                "changes_by_basket": changes_by_basket,
                "ticket_turnover": turnover,
                "year_to_date_turnover": turnover_by_year[as_of.year],
                "within_annual_turnover_budget": (
                    turnover_by_year[as_of.year] <= float(policy["annual_turnover_ceiling"]) + 1e-12
                ),
            }
        )
    diagnostics = {
        "annual_turnover": {str(year): value for year, value in sorted(turnover_by_year.items())},
        "maximum_annual_turnover": max(turnover_by_year.values(), default=0.0),
        "annual_turnover_ceiling": float(policy["annual_turnover_ceiling"]),
        "turnover_gate_passed": max(turnover_by_year.values(), default=0.0)
        <= float(policy["annual_turnover_ceiling"]) + 1e-12,
        "completed_holding_count": len(completed_holding_sessions),
        "average_completed_holding_sessions": (
            None
            if not completed_holding_sessions
            else float(sum(completed_holding_sessions) / len(completed_holding_sessions))
        ),
    }
    return score_rows, portfolio_rows, diagnostics


def run_low_turnover_multifactor(
    *,
    contract_path: str | Path,
    fundamental_scores_path: str | Path,
    basket_scores_path: str | Path,
    relationship_map_path: str | Path,
    prices_csv: str | Path,
    registry_db: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    contract, pool, resolved_contract, pool_path = load_multifactor_contract(contract_path)
    basket_by_symbol, references = _pool_membership(pool)
    factor_rows = list(contract["factors"])
    factor_keys = [str(row["stable_factor_key"]) for row in factor_rows]
    security_factor_keys = {
        str(row["stable_factor_key"]) for row in factor_rows if str(row["scope"]) == "security"
    }
    basket_factor_rows = [row for row in factor_rows if str(row["scope"]) == "basket"]

    fundamental_path = Path(fundamental_scores_path).resolve()
    basket_path = Path(basket_scores_path).resolve()
    relationship_path = Path(relationship_map_path).resolve()
    prices_path = Path(prices_csv).resolve()
    fundamental_manifest, fundamental_manifest_hash = _verify_sibling_manifest(fundamental_path)
    basket_manifest, basket_manifest_hash = _verify_sibling_manifest(basket_path)
    relationship_payload, relationship_hash = _relationship_gate(
        relationship_path, factor_keys, contract
    )
    fundamental_scores = _load_fundamental_scores(fundamental_path, security_factor_keys)
    basket_scores = _load_basket_scores(basket_path, basket_factor_rows)
    prices = _load_prices(prices_path, set(basket_by_symbol) | set(references))
    benchmark = str(contract["benchmark"]).upper()
    benchmark_dates = pd.DatetimeIndex(
        prices.loc[prices["symbol"] == benchmark, "date"].sort_values().unique()
    )
    if benchmark_dates.empty:
        raise ValueError("benchmark has no price dates")

    registry = FactorKnowledgeRegistry(registry_db)
    cards = {str(card["stable_factor_key"]): card for card in registry.list_cards()}
    missing_cards = sorted(set(factor_keys) - set(cards))
    if missing_cards:
        raise ValueError("configured factors missing from registry: " + ", ".join(missing_cards))
    allowed_statuses = set(contract["selection_contract"]["admissible_card_statuses"])
    inadmissible = {
        key: cards[key]["status"]
        for key in factor_keys
        if cards[key]["status"] not in allowed_statuses
    }
    if inadmissible:
        raise ValueError(f"configured factors have inadmissible statuses: {inadmissible}")
    incomplete_statuses = {
        key: cards[key]["status"] for key in factor_keys if cards[key]["status"] == "data_blocked"
    }

    score_rows, portfolio_rows, diagnostics = _portfolio_history(
        contract=contract,
        basket_by_symbol=basket_by_symbol,
        benchmark_dates=benchmark_dates,
        fundamental_scores=fundamental_scores,
        basket_scores=basket_scores,
    )
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    composite_payload = {
        "schema_version": "1.0",
        "combination_id": contract["combination_id"],
        "market": contract["market"],
        "research_only": True,
        "trade_ready": False,
        "rows": score_rows,
    }
    portfolio_payload = {
        "schema_version": "1.0",
        "combination_id": contract["combination_id"],
        "rows": portfolio_rows,
        "diagnostics": diagnostics,
    }
    _write_json(output / "multifactor_scores.json", composite_payload)
    _write_json(output / "portfolio_history.json", portfolio_payload)

    input_identity = {
        "contract": _sha256_file(resolved_contract),
        "pool": _sha256_file(pool_path),
        "fundamental_manifest": fundamental_manifest_hash,
        "fundamental_manifest_identity": fundamental_manifest.get("manifest_identity_sha256"),
        "basket_manifest": basket_manifest_hash,
        "basket_manifest_identity": basket_manifest.get("manifest_identity_sha256"),
        "relationship_map": relationship_hash,
        "relationship_scope": relationship_payload.get("scope"),
        "prices": _sha256_file(prices_path),
    }
    evidence_identity = _canonical_hash(input_identity)
    usage_ids = [
        registry.record_combination_usage(
            str(cards[key]["card_id"]),
            combination_id=str(contract["combination_id"]),
            weight=float(
                next(row["weight"] for row in factor_rows if row["stable_factor_key"] == key)
            ),
            role="primary_equal_weight",
            evidence_manifest_hash=evidence_identity,
        )
        for key in factor_keys
    ]
    status = (
        "multifactor_diagnostic_scores_ready_registry_evidence_incomplete"
        if incomplete_statuses
        else "multifactor_diagnostic_candidate_ready"
    )
    if not diagnostics["turnover_gate_passed"]:
        status = "multifactor_candidate_failed_turnover_contract"
    decision = {
        "schema_version": "1.0",
        "decision": status,
        "combination_id": contract["combination_id"],
        "research_only": True,
        "diagnostic_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "independent_validation_completed": False,
        "factor_keys": factor_keys,
        "information_family_count": len({str(row["information_family"]) for row in factor_rows}),
        "relationship_gate_passed": True,
        "registry_incomplete_statuses": incomplete_statuses,
        "turnover_diagnostics": diagnostics,
        "combination_usage_ids": usage_ids,
        "score_row_count": len(score_rows),
        "portfolio_row_count": len(portfolio_rows),
    }
    _write_json(output / "decision.json", decision)
    outputs = {
        name: _sha256_file(output / name)
        for name in ("multifactor_scores.json", "portfolio_history.json", "decision.json")
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "combination_id": contract["combination_id"],
        "inputs": input_identity,
        "input_identity_sha256": evidence_identity,
        "outputs": outputs,
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(output / "evidence_manifest.json", manifest)
    return decision
