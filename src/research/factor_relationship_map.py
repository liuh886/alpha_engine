"""Build manifest-bound factor correlations, overlaps, and redundancy clusters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.factor_knowledge_registry import FactorKnowledgeRegistry

REQUIRED_SCOPE_FIELDS = (
    "market",
    "universe_version",
    "benchmark",
    "start_date",
    "end_date",
    "provider_identity",
    "evidence_manifest_hash",
)
ARTIFACT_COLUMNS = {
    "scores": {"date", "symbol", "stable_factor_key", "score"},
    "returns": {"date", "stable_factor_key", "return"},
    "selections": {"date", "stable_factor_key", "symbol", "selected"},
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def load_relationship_contract(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("relationship contract must be a YAML mapping")
    if payload.get("status") != "frozen_pre_observation":
        raise ValueError("relationship contract is not frozen")
    truth = payload.get("truth_boundary", {})
    if truth.get("research_only") is not True or truth.get("trade_ready") is not False:
        raise ValueError("relationship contract truth boundary is invalid")
    if truth.get("cross_market_alignment_allowed") is not False:
        raise ValueError("cross-market alignment must remain prohibited")
    return payload, resolved


def load_input_manifest(path: str | Path) -> tuple[dict[str, Any], Path]:
    resolved = Path(path).resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("relationship input manifest must be a JSON object")
    scope = payload.get("scope")
    artifacts = payload.get("artifacts")
    if not isinstance(scope, dict) or not isinstance(artifacts, dict):
        raise ValueError("relationship input manifest requires scope and artifacts")
    missing_scope = [field for field in REQUIRED_SCOPE_FIELDS if not scope.get(field)]
    if missing_scope:
        raise ValueError("relationship scope missing fields: " + ", ".join(missing_scope))
    start = pd.Timestamp(scope["start_date"])
    end = pd.Timestamp(scope["end_date"])
    if start > end:
        raise ValueError("relationship scope start_date exceeds end_date")
    for kind in ARTIFACT_COLUMNS:
        row = artifacts.get(kind)
        if not isinstance(row, dict) or not row.get("path") or not row.get("sha256"):
            raise ValueError(f"relationship manifest missing {kind} artifact identity")
    return payload, resolved


def _resolve_artifact(manifest_path: Path, identity: Mapping[str, Any], kind: str) -> Path:
    path = Path(str(identity["path"]))
    if not path.is_absolute():
        path = manifest_path.parent / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    if _sha256_file(resolved) != str(identity["sha256"]):
        raise ValueError(f"{kind} artifact hash mismatch")
    return resolved


def _coerce_selected(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)) and value in (0, 1):
        return bool(int(value))
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid selected value: {value!r}")


def _load_artifact(
    path: Path,
    *,
    kind: str,
    scope: Mapping[str, Any],
) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": "string", "stable_factor_key": "string"})
    missing = sorted(ARTIFACT_COLUMNS[kind] - set(frame.columns))
    if missing:
        raise ValueError(f"{kind} artifact missing columns: {missing}")
    frame = frame[list(ARTIFACT_COLUMNS[kind])].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["stable_factor_key"] = frame["stable_factor_key"].astype(str).str.strip()
    if "symbol" in frame:
        frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    if frame["date"].isna().any() or (frame["stable_factor_key"] == "").any():
        raise ValueError(f"{kind} artifact contains invalid dates or factor identities")
    start = pd.Timestamp(scope["start_date"])
    end = pd.Timestamp(scope["end_date"])
    outside = frame[(frame["date"] < start) | (frame["date"] > end)]
    if not outside.empty:
        raise ValueError(f"{kind} artifact contains rows outside declared scope")
    if kind == "scores":
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
        frame = frame.dropna(subset=["score"])
        keys = ["date", "symbol", "stable_factor_key"]
    elif kind == "returns":
        frame["return"] = pd.to_numeric(frame["return"], errors="coerce")
        frame = frame.dropna(subset=["return"])
        keys = ["date", "stable_factor_key"]
    else:
        frame["selected"] = [_coerce_selected(value) for value in frame["selected"]]
        keys = ["date", "stable_factor_key", "symbol"]
    if frame.duplicated(keys).any():
        raise ValueError(f"{kind} artifact contains duplicate identities")
    if frame.empty:
        raise ValueError(f"{kind} artifact has no usable rows")
    return frame.sort_values(keys).reset_index(drop=True)


def _factor_keys(*frames: pd.DataFrame) -> list[str]:
    sets = [set(frame["stable_factor_key"].unique()) for frame in frames]
    factors = sorted(set.intersection(*sets))
    if len(factors) < 2:
        raise ValueError("relationship map requires at least two common factors")
    return factors


def _pairwise_score_correlation(
    scores: pd.DataFrame,
    left: str,
    right: str,
    *,
    minimum: int,
) -> tuple[float | None, int]:
    subset = scores[scores["stable_factor_key"].isin({left, right})]
    wide = subset.pivot(index=["date", "symbol"], columns="stable_factor_key", values="score")
    aligned = wide[[left, right]].dropna()
    if len(aligned) < minimum:
        return None, len(aligned)
    value = aligned[left].corr(aligned[right], method="spearman")
    return (None if pd.isna(value) else float(value)), len(aligned)


def _pairwise_return_correlation(
    returns: pd.DataFrame,
    left: str,
    right: str,
    *,
    minimum: int,
) -> tuple[float | None, int]:
    subset = returns[returns["stable_factor_key"].isin({left, right})]
    wide = subset.pivot(index="date", columns="stable_factor_key", values="return")
    aligned = wide[[left, right]].dropna()
    if len(aligned) < minimum:
        return None, len(aligned)
    value = aligned[left].corr(aligned[right], method="pearson")
    return (None if pd.isna(value) else float(value)), len(aligned)


def _sets_by_date(selections: pd.DataFrame, factor: str) -> dict[pd.Timestamp, set[str]]:
    factor_rows = selections[(selections["stable_factor_key"] == factor) & selections["selected"]]
    return {date: set(group["symbol"]) for date, group in factor_rows.groupby("date", sort=True)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def _selection_metrics(
    selections: pd.DataFrame,
    left: str,
    right: str,
    *,
    minimum: int,
) -> tuple[float | None, float | None, int]:
    left_sets = _sets_by_date(selections, left)
    right_sets = _sets_by_date(selections, right)
    dates = sorted(set(left_sets) | set(right_sets))
    if len(dates) < minimum:
        return None, None, len(dates)
    overlaps = [_jaccard(left_sets.get(day, set()), right_sets.get(day, set())) for day in dates]
    left_changes: dict[pd.Timestamp, set[str]] = {}
    right_changes: dict[pd.Timestamp, set[str]] = {}
    previous_left: set[str] = set()
    previous_right: set[str] = set()
    for day in dates:
        current_left = left_sets.get(day, set())
        current_right = right_sets.get(day, set())
        left_changes[day] = current_left ^ previous_left
        right_changes[day] = current_right ^ previous_right
        previous_left = current_left
        previous_right = current_right
    turnover_overlaps = [_jaccard(left_changes[day], right_changes[day]) for day in dates]
    return float(np.mean(overlaps)), float(np.mean(turnover_overlaps)), len(dates)


def _is_redundant(
    *,
    score_correlation: float | None,
    return_correlation: float | None,
    selection_overlap: float | None,
    contract: Mapping[str, Any],
) -> bool:
    rules = contract["correlation"]
    score_redundant = score_correlation is not None and abs(score_correlation) >= float(
        rules["absolute_score_redundancy_threshold"]
    )
    return_redundant = (
        return_correlation is not None
        and selection_overlap is not None
        and abs(return_correlation) >= float(rules["absolute_return_redundancy_threshold"])
        and selection_overlap >= float(rules["selection_overlap_threshold"])
    )
    return score_redundant or return_redundant


def _connected_components(factors: list[str], edges: list[tuple[str, str]]) -> dict[str, str]:
    parent = {factor: factor for factor in factors}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for left, right in edges:
        union(left, right)
    groups: dict[str, list[str]] = {}
    for factor in factors:
        groups.setdefault(find(factor), []).append(factor)
    labels: dict[str, str] = {}
    cluster_index = 1
    for members in sorted(groups.values(), key=lambda values: values[0]):
        if len(members) < 2:
            labels[members[0]] = ""
            continue
        label = f"redundancy_cluster_{cluster_index:02d}"
        cluster_index += 1
        for factor in members:
            labels[factor] = label
    return labels


def build_factor_relationship_map(
    *,
    contract_path: str | Path,
    input_manifest_path: str | Path,
    registry_db: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    contract, resolved_contract = load_relationship_contract(contract_path)
    manifest, resolved_manifest = load_input_manifest(input_manifest_path)
    scope = manifest["scope"]
    artifact_paths = {
        kind: _resolve_artifact(resolved_manifest, manifest["artifacts"][kind], kind)
        for kind in ARTIFACT_COLUMNS
    }
    frames = {
        kind: _load_artifact(path, kind=kind, scope=scope) for kind, path in artifact_paths.items()
    }
    factors = _factor_keys(frames["scores"], frames["returns"], frames["selections"])
    registry = FactorKnowledgeRegistry(registry_db)
    cards = {str(card["stable_factor_key"]): card for card in registry.list_cards()}
    missing_cards = sorted(set(factors) - set(cards))
    if missing_cards:
        raise ValueError("relationship factors missing from registry: " + ", ".join(missing_cards))

    minimum = contract["minimum_observations"]
    pairs: list[dict[str, Any]] = []
    redundant_edges: list[tuple[str, str]] = []
    for left_index, left in enumerate(factors):
        for right in factors[left_index + 1 :]:
            score_correlation, score_count = _pairwise_score_correlation(
                frames["scores"], left, right, minimum=int(minimum["score_pairs"])
            )
            return_correlation, return_count = _pairwise_return_correlation(
                frames["returns"], left, right, minimum=int(minimum["return_dates"])
            )
            selection_overlap, turnover_overlap, selection_count = _selection_metrics(
                frames["selections"],
                left,
                right,
                minimum=int(minimum["selection_dates"]),
            )
            redundant = _is_redundant(
                score_correlation=score_correlation,
                return_correlation=return_correlation,
                selection_overlap=selection_overlap,
                contract=contract,
            )
            if redundant:
                redundant_edges.append((left, right))
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "score_correlation": score_correlation,
                    "return_correlation": return_correlation,
                    "selection_overlap": selection_overlap,
                    "turnover_overlap": turnover_overlap,
                    "score_observation_count": score_count,
                    "return_observation_count": return_count,
                    "selection_date_count": selection_count,
                    "redundant": redundant,
                }
            )
    cluster_by_factor = _connected_components(factors, redundant_edges)
    scope_hash = _canonical_hash(scope)
    source_manifest_hash = _sha256_file(resolved_manifest)
    relationship_ids = []
    for pair in pairs:
        left_cluster = cluster_by_factor[pair["left"]]
        right_cluster = cluster_by_factor[pair["right"]]
        cluster = left_cluster if left_cluster and left_cluster == right_cluster else ""
        pair["redundancy_cluster"] = cluster
        relationship_ids.append(
            registry.record_relationship(
                str(cards[pair["left"]]["card_id"]),
                str(cards[pair["right"]]["card_id"]),
                evidence_scope_hash=scope_hash,
                source_manifest_hash=source_manifest_hash,
                score_correlation=pair["score_correlation"],
                return_correlation=pair["return_correlation"],
                selection_overlap=pair["selection_overlap"],
                turnover_overlap=pair["turnover_overlap"],
                redundancy_cluster=cluster,
            )
        )

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    relationship_payload = {
        "schema_version": "1.0",
        "relationship_contract_id": contract["relationship_contract_id"],
        "scope": scope,
        "research_only": True,
        "trade_ready": False,
        "factor_count": len(factors),
        "pair_count": len(pairs),
        "factors": [
            {
                "stable_factor_key": factor,
                "card_id": cards[factor]["card_id"],
                "information_family": cards[factor]["information_family"],
                "status": cards[factor]["status"],
                "redundancy_cluster": cluster_by_factor[factor],
            }
            for factor in factors
        ],
        "pairs": pairs,
        "relationship_ids": relationship_ids,
    }
    _write_json(output / "factor_relationships.json", relationship_payload)
    decision = {
        "schema_version": "1.0",
        "decision": "factor_relationship_map_ready",
        "research_only": True,
        "trade_ready": False,
        "factor_count": len(factors),
        "pair_count": len(pairs),
        "redundancy_cluster_count": len({value for value in cluster_by_factor.values() if value}),
        "insufficient_score_pairs": sum(pair["score_correlation"] is None for pair in pairs),
        "insufficient_return_pairs": sum(pair["return_correlation"] is None for pair in pairs),
    }
    _write_json(output / "decision.json", decision)
    outputs = {
        name: _sha256_file(output / name) for name in ("factor_relationships.json", "decision.json")
    }
    output_manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "relationship_contract_id": contract["relationship_contract_id"],
        "scope_hash": scope_hash,
        "inputs": {
            "contract": _sha256_file(resolved_contract),
            "input_manifest": source_manifest_hash,
            **{kind: _sha256_file(path) for kind, path in artifact_paths.items()},
        },
        "outputs": outputs,
    }
    output_manifest["manifest_identity_sha256"] = _canonical_hash(output_manifest)
    _write_json(output / "evidence_manifest.json", output_manifest)
    return decision
