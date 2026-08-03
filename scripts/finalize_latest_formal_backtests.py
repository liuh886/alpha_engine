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


def _digest(value: object, *, label: str, prefixed: bool = False) -> str:
    text = str(value or "").lower()
    expected_length = 71 if prefixed else 64
    if len(text) != expected_length:
        raise LatestFormalFinalizationError(f"invalid {label}")
    body = text[7:] if prefixed and text.startswith("sha256:") else text
    if prefixed and not text.startswith("sha256:"):
        raise LatestFormalFinalizationError(f"invalid {label}")
    if any(char not in "0123456789abcdef" for char in body):
        raise LatestFormalFinalizationError(f"invalid {label}")
    return text


def _freshness_source(path: Path) -> dict[str, Any]:
    source = _read(path)
    if source.get("status") != "accepted_reproducible_freshness_evidence":
        raise LatestFormalFinalizationError("freshness source is not accepted")
    if source.get("research_only") is not True or source.get("trade_ready") is not False:
        raise LatestFormalFinalizationError("freshness source weakens research boundary")
    if source.get("cutoff") != "2026-07-31":
        raise LatestFormalFinalizationError("freshness source cutoff mismatch")
    run_id = source.get("workflow_run_id")
    artifact_id = source.get("artifact_id")
    if not isinstance(run_id, int) or run_id <= 0 or not isinstance(artifact_id, int) or artifact_id <= 0:
        raise LatestFormalFinalizationError("freshness source run/artifact identity is invalid")
    head = str(source.get("workflow_head_sha") or "")
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        raise LatestFormalFinalizationError("freshness source head SHA is invalid")
    _digest(source.get("artifact_digest"), label="freshness artifact digest", prefixed=True)
    models = source.get("models")
    if not isinstance(models, dict) or set(models) != {"us_x1_1", "cn_x1_0"}:
        raise LatestFormalFinalizationError("freshness source model allow-list mismatch")
    for model_id, row in models.items():
        if not isinstance(row, dict):
            raise LatestFormalFinalizationError(f"invalid freshness source row: {model_id}")
        _digest(row.get("provider_identity_sha256"), label=f"{model_id} provider identity")
        traces = row.get("trace_sha256")
        if not isinstance(traces, dict) or not traces:
            raise LatestFormalFinalizationError(f"{model_id} source traces are missing")
        for label, digest in traces.items():
            _digest(digest, label=f"{model_id}/{label} trace digest")
    return source


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
    package: dict[str, Any], accepted: dict[str, Any], *, label: str
) -> tuple[int, int]:
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


def _cross_window_cn_drawdown(package: dict[str, Any], trace: dict[str, Any]) -> float:
    report = package.get("report")
    metrics = package.get("metrics")
    points = trace.get("points")
    if not isinstance(report, list) or len(report) < 2:
        raise LatestFormalFinalizationError("CN formal report is incomplete")
    if not isinstance(metrics, dict) or not isinstance(points, list) or not points:
        raise LatestFormalFinalizationError("CN trace metrics are incomplete")
    historical_accounts = [float(row["account"]) for row in report[:-1]]
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
    if not math.isclose(account, float(report[-1]["account"]), rel_tol=0.0, abs_tol=1e-10):
        raise LatestFormalFinalizationError(
            "CN partial path does not reconcile to generated final account"
        )
    return worst


def _freshness(package: dict[str, Any], *, model_id: str) -> dict[str, Any]:
    evidence = package.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    freshness = evidence.get("freshness_evidence")
    if not isinstance(freshness, dict):
        freshness = {}
    evidence["freshness_evidence"] = freshness
    package["evidence"] = evidence
    if package.get("model_id") != model_id:
        raise LatestFormalFinalizationError(f"package identity mismatch: {model_id}")
    return freshness


def _bind_cn_provider_identity(package: dict[str, Any], provider_identity: str) -> str | None:
    normalized = _digest(provider_identity, label="CN provider identity")
    freshness = _freshness(package, model_id="cn_x1_0")
    previous = freshness.get("provider_identity_sha256")
    previous_identity = str(previous) if previous else None
    freshness["provider_identity_sha256"] = normalized
    if previous_identity and previous_identity != normalized:
        freshness["superseded_provider_identity_sha256"] = previous_identity
        freshness["provider_snapshot_revision_observed"] = True
    return previous_identity


def _bind_freshness_source(
    package: dict[str, Any], *, model_id: str, source: dict[str, Any]
) -> None:
    if package.get("evidence_cutoff") != source["cutoff"]:
        raise LatestFormalFinalizationError(f"{model_id} cutoff/source mismatch")
    if package.get("generated_at") != source["generated_at"]:
        raise LatestFormalFinalizationError(f"{model_id} generated_at/source mismatch")
    model_source = source["models"][model_id]
    freshness = _freshness(package, model_id=model_id)
    if freshness.get("provider_identity_sha256") != model_source["provider_identity_sha256"]:
        raise LatestFormalFinalizationError(f"{model_id} provider/source mismatch")
    if freshness.get("trace_sha256") != model_source["trace_sha256"]:
        raise LatestFormalFinalizationError(f"{model_id} trace/source mismatch")
    freshness.update(
        {
            "source_status": source["status"],
            "workflow_run_id": str(source["workflow_run_id"]),
            "workflow_head_sha": source["workflow_head_sha"],
            "artifact_id": source["artifact_id"],
            "artifact_name": source["artifact_name"],
            "artifact_digest": source["artifact_digest"],
        }
    )


def finalize(
    generated_dir: Path,
    existing_dir: Path,
    cn_run_dir: Path,
    freshness_source_path: Path,
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
    source = _freshness_source(freshness_source_path)

    removed_us, us_prefix_length = _strip_inferred_extension_ranks(
        us, accepted_us, label="US x1.1"
    )
    removed_cn, cn_prefix_length = _strip_inferred_extension_ranks(
        cn, accepted_cn, label="CN x1.0"
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
    _bind_freshness_source(us, model_id="us_x1_1", source=source)
    _bind_freshness_source(cn, model_id="cn_x1_0", source=source)

    note = (
        "Latest-window position ranks are not displayed because the retained "
        "trace contains equal-weight membership but no auditable rank ordering."
    )
    for package in (us, cn):
        notes = package.get("interpretation_notes")
        if not isinstance(notes, list):
            notes = []
        if note not in notes:
            notes.append(note)
        package["interpretation_notes"] = notes
    revision_note = (
        "The 2026-07-31 CN provider was independently reconstructed from the "
        "current AkShare/Sina snapshot; its identity is retained explicitly."
    )
    cn_notes = cn["interpretation_notes"]
    if revision_note not in cn_notes:
        cn_notes.append(revision_note)

    _write(us_path, us)
    _write(cn_path, cn)
    records = catalog.get("records")
    if not isinstance(records, list):
        raise LatestFormalFinalizationError("formal catalog records are missing")
    by_id = {"us_x1_1": _sha256(us_path), "cn_x1_0": _sha256(cn_path)}
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
        "freshness_source": {
            "workflow_run_id": source["workflow_run_id"],
            "workflow_head_sha": source["workflow_head_sha"],
            "artifact_id": source["artifact_id"],
            "artifact_digest": source["artifact_digest"],
        },
        "package_sha256": {"us_x1_1": _sha256(us_path), "cn_x1_0": _sha256(cn_path)},
        "catalog_sha256": _sha256(catalog_path),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--existing-dir", type=Path, required=True)
    parser.add_argument("--cn-run-dir", type=Path, required=True)
    parser.add_argument("--freshness-source", type=Path, required=True)
    parser.add_argument("--cn-provider-identity", required=True)
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    receipt = finalize(
        args.generated_dir,
        args.existing_dir,
        args.cn_run_dir,
        args.freshness_source,
        cn_provider_identity=args.cn_provider_identity,
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
