"""Deterministic comparison of immutable selected-pool provider snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


FINAL_DECISIONS = {
    "append_only_reproducible",
    "legitimate_historical_revision_explained",
    "pipeline_nondeterminism_fixed",
    "unexplained_provider_drift_blocking",
}


class ProviderSnapshotComparisonError(ValueError):
    """Raised when provider snapshot evidence is missing or inconsistent."""


@dataclass(frozen=True)
class SymbolSnapshotDiff:
    symbol: str
    old_provider: str | None
    new_provider: str | None
    old_first_date: str | None
    new_first_date: str | None
    old_last_date: str | None
    new_last_date: str | None
    old_rows: int | None
    new_rows: int | None
    row_delta: int | None
    old_output_sha256: str | None
    new_output_sha256: str | None
    full_file_hash_equal: bool
    historical_prefix_sha256_equal: bool | None
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ProviderSnapshotComparisonError(f"JSON evidence is missing: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProviderSnapshotComparisonError(f"JSON evidence must be a mapping: {source}")
    return payload


def _record_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records = manifest.get("records", [])
    if not isinstance(records, list):
        raise ProviderSnapshotComparisonError("refresh manifest records must be a list")
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        symbol = str(record.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        if symbol in result:
            raise ProviderSnapshotComparisonError(f"duplicate symbol record: {symbol}")
        result[symbol] = record
    return result


def _prefix_hashes(manifest: Mapping[str, Any]) -> dict[str, str]:
    raw = manifest.get("historical_prefix_sha256", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ProviderSnapshotComparisonError(
            "historical_prefix_sha256 must be a symbol-to-hash mapping"
        )
    return {
        str(symbol).strip().upper(): str(value).strip().lower()
        for symbol, value in raw.items()
        if str(symbol).strip() and str(value).strip()
    }


def compare_refresh_manifests(
    old_manifest: Mapping[str, Any],
    new_manifest: Mapping[str, Any],
) -> tuple[list[SymbolSnapshotDiff], dict[str, Any]]:
    """Compare refresh manifests without pretending full-file hashes prove prefixes."""

    if str(old_manifest.get("market", "")) != str(new_manifest.get("market", "")):
        raise ProviderSnapshotComparisonError("snapshot market mismatch")
    if str(old_manifest.get("pool_id", "")) != str(new_manifest.get("pool_id", "")):
        raise ProviderSnapshotComparisonError("snapshot pool identity mismatch")

    old_records = _record_map(old_manifest)
    new_records = _record_map(new_manifest)
    old_prefix = _prefix_hashes(old_manifest)
    new_prefix = _prefix_hashes(new_manifest)
    symbols = sorted(set(old_records) | set(new_records))
    rows: list[SymbolSnapshotDiff] = []

    for symbol in symbols:
        old = old_records.get(symbol, {})
        new = new_records.get(symbol, {})
        old_rows = int(old["rows"]) if old.get("rows") is not None else None
        new_rows = int(new["rows"]) if new.get("rows") is not None else None
        row_delta = new_rows - old_rows if old_rows is not None and new_rows is not None else None
        old_hash = str(old.get("output_sha256") or "").strip().lower() or None
        new_hash = str(new.get("output_sha256") or "").strip().lower() or None
        prefix_equal: bool | None = None
        if symbol in old_prefix and symbol in new_prefix:
            prefix_equal = old_prefix[symbol] == new_prefix[symbol]

        same_identity = (
            str(old.get("provider") or "") == str(new.get("provider") or "")
            and str(old.get("provider_symbol") or "") == str(new.get("provider_symbol") or "")
            and str(old.get("first_date") or "") == str(new.get("first_date") or "")
        )
        if not old or not new:
            classification = "symbol_set_changed"
        elif prefix_equal is True and row_delta is not None and row_delta >= 0:
            classification = "appended_only"
        elif prefix_equal is False:
            classification = "historical_prefix_changed"
        elif old_hash == new_hash and row_delta == 0 and same_identity:
            classification = "identical"
        elif same_identity and row_delta is not None and row_delta >= 0:
            classification = "prefix_evidence_missing"
        else:
            classification = "identity_or_history_changed"

        rows.append(
            SymbolSnapshotDiff(
                symbol=symbol,
                old_provider=str(old.get("provider")) if old.get("provider") else None,
                new_provider=str(new.get("provider")) if new.get("provider") else None,
                old_first_date=str(old.get("first_date")) if old.get("first_date") else None,
                new_first_date=str(new.get("first_date")) if new.get("first_date") else None,
                old_last_date=str(old.get("last_date")) if old.get("last_date") else None,
                new_last_date=str(new.get("last_date")) if new.get("last_date") else None,
                old_rows=old_rows,
                new_rows=new_rows,
                row_delta=row_delta,
                old_output_sha256=old_hash,
                new_output_sha256=new_hash,
                full_file_hash_equal=bool(old_hash and old_hash == new_hash),
                historical_prefix_sha256_equal=prefix_equal,
                classification=classification,
            )
        )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.classification] = counts.get(row.classification, 0) + 1
    summary = {
        "market": old_manifest.get("market"),
        "pool_id": old_manifest.get("pool_id"),
        "old_cutoff": old_manifest.get("cutoff"),
        "new_cutoff": new_manifest.get("cutoff"),
        "old_provider_identity_sha256": old_manifest.get("provider_identity_sha256"),
        "new_provider_identity_sha256": new_manifest.get("provider_identity_sha256"),
        "symbol_count_old": len(old_records),
        "symbol_count_new": len(new_records),
        "symbol_sets_equal": set(old_records) == set(new_records),
        "before_snapshots_equal": old_manifest.get("before") == new_manifest.get("before"),
        "selected_providers_equal": old_manifest.get("selected_providers")
        == new_manifest.get("selected_providers"),
        "classification_counts": counts,
        "historical_prefix_evidence_complete": bool(rows)
        and all(row.historical_prefix_sha256_equal is not None for row in rows),
    }
    return rows, summary


def _candidate_by_id(evidence: Mapping[str, Any], candidate_id: str) -> Mapping[str, Any]:
    candidates = evidence.get("candidates", [])
    if not isinstance(candidates, list):
        raise ProviderSnapshotComparisonError("stability candidates must be a list")
    matches = [
        row
        for row in candidates
        if isinstance(row, dict) and str(row.get("candidate")) == candidate_id
    ]
    if len(matches) != 1:
        raise ProviderSnapshotComparisonError(
            f"candidate must resolve exactly once: {candidate_id}; matches={len(matches)}"
        )
    return matches[0]


def compare_candidate_evidence(
    old_evidence: Mapping[str, Any],
    new_evidence: Mapping[str, Any],
    *,
    candidate_id: str,
) -> dict[str, Any]:
    old = _candidate_by_id(old_evidence, candidate_id)
    new = _candidate_by_id(new_evidence, candidate_id)
    metrics = (
        "compounded_total_return",
        "compounded_benchmark_return",
        "compounded_relative_excess_return",
        "mean_icir",
        "mean_rank_ic",
        "mean_spread",
        "worst_drawdown",
        "positive_excess_ratio",
    )
    deltas: dict[str, Any] = {}
    for metric in metrics:
        old_value = old.get(metric)
        new_value = new.get(metric)
        deltas[metric] = {
            "old": old_value,
            "new": new_value,
            "delta": (
                float(new_value) - float(old_value)
                if old_value is not None and new_value is not None
                else None
            ),
        }
    return {
        "candidate_id": candidate_id,
        "old_windows": old.get("n_windows"),
        "new_windows": new.get("n_windows"),
        "metrics": deltas,
    }


def decide_snapshot_drift(
    symbol_diffs: list[SymbolSnapshotDiff],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one issue-approved decision, fail-closed on missing prefix evidence."""

    classifications = {row.classification for row in symbol_diffs}
    if not symbol_diffs or not bool(summary.get("symbol_sets_equal")):
        decision = "unexplained_provider_drift_blocking"
        reason = "symbol membership differs or snapshot evidence is empty"
    elif classifications <= {"identical", "appended_only"} and bool(
        summary.get("historical_prefix_evidence_complete")
    ):
        decision = "append_only_reproducible"
        reason = "every overlapping historical prefix is hash-identical"
    elif "historical_prefix_changed" in classifications:
        decision = "legitimate_historical_revision_explained"
        reason = (
            "historical prefixes changed; an external revision/corporate-action "
            "classification must accompany this decision"
        )
    else:
        decision = "unexplained_provider_drift_blocking"
        reason = (
            "full-file hashes and row counts cannot prove that the overlapping "
            "historical prefix is unchanged"
        )
    if decision not in FINAL_DECISIONS:
        raise ProviderSnapshotComparisonError(f"unsupported final decision: {decision}")
    return {
        "decision": decision,
        "reason": reason,
        "further_cn_model_search_authorized": decision
        in {"append_only_reproducible", "legitimate_historical_revision_explained"},
        "historical_results_are_snapshot_specific": True,
        "automatic_restatement_authorized": False,
        "research_only": True,
        "trade_ready": False,
    }
