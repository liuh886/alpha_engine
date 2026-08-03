"""Finalize freshly extended formal packages without inventing missing evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class LatestFormalFinalizationError(ValueError):
    """Raised when generated formal packages cannot be finalized safely."""


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LatestFormalFinalizationError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LatestFormalFinalizationError(f"JSON root must be an object: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cn_partial_trace(run_dir: Path) -> dict[str, Any]:
    plan = _read(run_dir / "walk_forward_windows.json")
    experiment_id = str(plan.get("experiment_id") or "")
    if not experiment_id:
        raise LatestFormalFinalizationError("CN experiment identity is missing")
    payload = _read(run_dir / "windows" / f"{experiment_id}_2026H2.json")
    traces = [
        row
        for row in payload.get("backtest_traces", [])
        if isinstance(row, dict)
        and row.get("orientation") == "original"
        and str(row.get("candidate_name", "")).startswith("xgb:daily_ranker")
    ]
    if len(traces) != 1:
        raise LatestFormalFinalizationError(
            "CN partial window does not contain one frozen original trace"
        )
    return traces[0]


def _position_rows(package: dict[str, Any], *, label: str) -> list[dict[str, Any]]:
    positions = package.get("positions")
    if not isinstance(positions, list):
        raise LatestFormalFinalizationError(f"{label} formal positions are missing")
    rows: list[dict[str, Any]] = []
    for row in positions:
        if not isinstance(row, dict):
            raise LatestFormalFinalizationError(f"{label} formal position row is invalid")
        rows.append(row)
    return rows


def _strip_inferred_extension_ranks(
    package: dict[str, Any],
    accepted: dict[str, Any],
    *,
    label: str,
) -> tuple[int, int]:
    """Remove inferred ranks only from rows appended after the accepted prefix."""

    generated_rows = _position_rows(package, label=label)
    accepted_rows = _position_rows(accepted, label=f"accepted {label}")
    prefix_length = len(accepted_rows)
    if len(generated_rows) < prefix_length:
        raise LatestFormalFinalizationError(
            f"{label} generated positions are shorter than the accepted prefix"
        )
    if generated_rows[:prefix_length] != accepted_rows:
        raise LatestFormalFinalizationError(
            f"{label} accepted position prefix was rewritten before finalization"
        )

    removed = 0
    for row in generated_rows[prefix_length:]:
        if "rank" in row:
            row.pop("rank")
            row["rank_evidence"] = "not_retained"
            removed += 1
    return removed, prefix_length


def _cross_window_cn_drawdown(
    package: dict[str, Any], trace: dict[str, Any]
) -> float:
    report = package.get("report")
    metrics = package.get("metrics")
    points = trace.get("points")
    if not isinstance(report, list) or len(report) < 2:
        raise LatestFormalFinalizationError("CN formal report is incomplete")
    if not isinstance(metrics, dict) or not isinstance(points, list) or not points:
        raise LatestFormalFinalizationError("CN trace metrics are incomplete")

    historical = report[:-1]
    historical_accounts = [float(row["account"]) for row in historical]
    if any(not math.isfinite(value) or value <= 0 for value in historical_accounts):
        raise LatestFormalFinalizationError("CN historical account path is invalid")
    account = historical_accounts[-1]
    peak = max(historical_accounts)
    worst = float(metrics.get("Max Drawdown", 0.0))
    for point in points:
        if not isinstance(point, dict):
            raise LatestFormalFinalizationError("CN partial trace point is invalid")
        period_return = float(point.get("net_period_return"))
        if not math.isfinite(period_return) or period_return <= -1.0:
            raise LatestFormalFinalizationError("CN partial return is invalid")
        account *= 1.0 + period_return
        peak = max(peak, account)
        worst = min(worst, account / peak - 1.0)

    final_account = float(report[-1]["account"])
    if not math.isclose(account, final_account, rel_tol=0.0, abs_tol=1e-10):
        raise LatestFormalFinalizationError(
            "CN partial path does not reconcile to generated final account"
        )
    return worst


def _bind_cn_provider_identity(
    package: dict[str, Any], provider_identity: str
) -> str | None:
    normalized = provider_identity.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise LatestFormalFinalizationError("invalid CN provider identity")
    evidence = package.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    freshness = evidence.get("freshness_evidence")
    if not isinstance(freshness, dict):
        freshness = {}
    previous = freshness.get("provider_identity_sha256")
    previous_identity = str(previous) if previous else None
    freshness["provider_identity_sha256"] = normalized
    if previous_identity and previous_identity != normalized:
        freshness["superseded_provider_identity_sha256"] = previous_identity
        freshness["provider_snapshot_revision_observed"] = True
    evidence["freshness_evidence"] = freshness
    package["evidence"] = evidence
    return previous_identity


def finalize(
    generated_dir: Path,
    existing_dir: Path,
    cn_run_dir: Path,
    *,
    cn_provider_identity: str,
) -> dict[str, Any]:
    us_path = generated_dir / "us_x1_1.json"
    cn_path = generated_dir / "cn_x1_0.json"
    catalog_path = generated_dir / "catalog.json"
    us = _read(us_path)
    cn = _read(cn_path)
    accepted_us = _read(existing_dir / "us_x1_1.json")
    accepted_cn = _read(existing_dir / "cn_x1_0.json")
    catalog = _read(catalog_path)

    removed_us, us_prefix_length = _strip_inferred_extension_ranks(
        us,
        accepted_us,
        label="US x1.1",
    )
    removed_cn, cn_prefix_length = _strip_inferred_extension_ranks(
        cn,
        accepted_cn,
        label="CN x1.0",
    )
    if removed_us == 0 or removed_cn == 0:
        raise LatestFormalFinalizationError(
            "expected inferred ranks were not present in generated extensions"
        )

    trace = _cn_partial_trace(cn_run_dir)
    worst = _cross_window_cn_drawdown(cn, trace)
    metrics = cn.get("metrics")
    if not isinstance(metrics, dict):
        raise LatestFormalFinalizationError("CN metrics are missing")
    metrics["Max Drawdown"] = worst
    cn["metrics"] = metrics
    previous_cn_identity = _bind_cn_provider_identity(cn, cn_provider_identity)

    notes = cn.get("interpretation_notes")
    if not isinstance(notes, list):
        notes = []
    note = (
        "Latest-window position ranks are not displayed because the retained "
        "trace contains equal-weight membership but no auditable rank ordering."
    )
    if note not in notes:
        notes.append(note)
    revision_note = (
        "The 2026-07-31 CN provider was independently reconstructed from the "
        "current AkShare/Sina snapshot; its identity is retained explicitly."
    )
    if revision_note not in notes:
        notes.append(revision_note)
    cn["interpretation_notes"] = notes

    us_notes = us.get("interpretation_notes")
    if not isinstance(us_notes, list):
        us_notes = []
    if note not in us_notes:
        us_notes.append(note)
    us["interpretation_notes"] = us_notes

    _write(us_path, us)
    _write(cn_path, cn)

    records = catalog.get("records")
    if not isinstance(records, list):
        raise LatestFormalFinalizationError("formal catalog records are missing")
    by_id = {
        "us_x1_1": _sha256(us_path),
        "cn_x1_0": _sha256(cn_path),
    }
    for row in records:
        if not isinstance(row, dict):
            raise LatestFormalFinalizationError("formal catalog row is invalid")
        model_id = str(row.get("model_id") or "")
        if model_id in by_id:
            row["sha256"] = by_id[model_id]
    _write(catalog_path, catalog)

    return {
        "schema_version": "1.0.0",
        "status": "finalized",
        "accepted_position_prefix_lengths": {
            "us_x1_1": us_prefix_length,
            "cn_x1_0": cn_prefix_length,
        },
        "removed_inferred_ranks": {"us_x1_1": removed_us, "cn_x1_0": removed_cn},
        "cn_cross_window_max_drawdown": worst,
        "cn_provider_identity_sha256": cn_provider_identity,
        "superseded_cn_provider_identity_sha256": previous_cn_identity,
        "package_sha256": {
            "us_x1_1": _sha256(us_path),
            "cn_x1_0": _sha256(cn_path),
        },
        "catalog_sha256": _sha256(catalog_path),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--existing-dir", type=Path, required=True)
    parser.add_argument("--cn-run-dir", type=Path, required=True)
    parser.add_argument("--cn-provider-identity", required=True)
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    receipt = finalize(
        args.generated_dir,
        args.existing_dir,
        args.cn_run_dir,
        cn_provider_identity=args.cn_provider_identity,
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
