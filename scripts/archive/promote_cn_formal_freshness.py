"""Promote accepted incremental CN freshness evidence into the formal release.

Only the existing ``2026H2_partial`` reporting extension may be replaced.
The accepted historical prefix, frozen model, universe, US package and QQQ
rotation package remain immutable.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class CnFormalFreshnessError(ValueError):
    """Incremental CN evidence is incomplete or inconsistent."""


TRACE_KEYS = (
    "candidate_name", "orientation", "forward_horizon_sessions", "top_n",
    "rebalance_days", "cost_bps", "points", "holdings",
    "name_contributions", "metrics", "research_only", "trade_ready",
)
PARTIAL = "2026H2_partial"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CnFormalFreshnessError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CnFormalFreshnessError(f"JSON root must be an object: {path}")
    return value


def _canonical(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _pretty(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_digest(value: object, *, prefixed: bool = False) -> bool:
    text = str(value or "").lower()
    if prefixed:
        if not text.startswith("sha256:"):
            return False
        text = text[7:]
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _trace_hash(trace: dict[str, Any]) -> str:
    try:
        payload = {key: trace[key] for key in TRACE_KEYS}
    except KeyError as exc:
        raise CnFormalFreshnessError(f"trace field missing: {exc.args[0]}") from exc
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _validate_source(source: dict[str, Any]) -> None:
    expected = {
        "schema_version": "1.0.0",
        "status": "accepted_reproducible_incremental_cn_freshness_evidence",
        "market": "cn",
        "model_id": "cn_x1_0",
        "cutoff": "2026-08-03",
        "previous_cutoff": "2026-07-31",
        "research_only": True,
        "trade_ready": False,
    }
    for key, value in expected.items():
        if source.get(key) != value:
            raise CnFormalFreshnessError(f"incremental source mismatch: {key}")
    for key in (
        "workflow_run_id", "artifact_id", "provider_workflow_run_id",
        "provider_artifact_id",
    ):
        if not isinstance(source.get(key), int) or int(source[key]) <= 0:
            raise CnFormalFreshnessError(f"invalid source integer: {key}")
    head = str(source.get("workflow_head_sha") or "")
    if len(head) != 40 or any(c not in "0123456789abcdef" for c in head):
        raise CnFormalFreshnessError("invalid source workflow head SHA")
    if not _valid_digest(source.get("artifact_digest"), prefixed=True):
        raise CnFormalFreshnessError("invalid candidate artifact digest")
    if not _valid_digest(source.get("provider_artifact_digest"), prefixed=True):
        raise CnFormalFreshnessError("invalid provider artifact digest")
    for key in ("provider_tar_sha256", "provider_identity_sha256"):
        if not _valid_digest(source.get(key)):
            raise CnFormalFreshnessError(f"invalid source digest: {key}")
    traces = source.get("trace_sha256")
    if not isinstance(traces, dict) or set(traces) != {"2026H2"}:
        raise CnFormalFreshnessError("trace allow-list mismatch")
    if not _valid_digest(traces["2026H2"]):
        raise CnFormalFreshnessError("invalid 2026H2 trace digest")


def _calendar(path: Path) -> list[str]:
    rows = [x.strip() for x in path.read_text().splitlines() if x.strip()]
    if not rows or rows != sorted(set(rows)):
        raise CnFormalFreshnessError("provider calendar is invalid")
    return rows


def _holding_end(calendar: list[str], signal: str, horizon: int = 10) -> str:
    try:
        index = calendar.index(signal)
    except ValueError as exc:
        raise CnFormalFreshnessError(f"signal missing from calendar: {signal}") from exc
    if index + horizon >= len(calendar):
        raise CnFormalFreshnessError(f"unrealized horizon: {signal}+{horizon}")
    return calendar[index + horizon]


def _load_trace(root: Path, cutoff: str) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = _read(root / "walk_forward_windows.json")
    if plan.get("requested_test_end") != cutoff or plan.get("available_end") != cutoff:
        raise CnFormalFreshnessError("walk-forward cutoff mismatch")
    rows = {
        str(row.get("label")): row
        for row in plan.get("windows", [])
        if isinstance(row, dict)
    }
    window = rows.get("2026H2")
    if not isinstance(window, dict):
        raise CnFormalFreshnessError("2026H2 window missing")
    if (
        window.get("status") != "included"
        or window.get("complete") is not False
        or window.get("counts_toward_min_windows") is not False
        or window.get("effective_test_end") != cutoff
    ):
        raise CnFormalFreshnessError("partial-window boundary weakened")
    experiment = str(plan.get("experiment_id") or "")
    payload = _read(root / "windows" / f"{experiment}_2026H2.json")
    traces = [
        row for row in payload.get("backtest_traces", [])
        if isinstance(row, dict)
        and row.get("orientation") == "original"
        and str(row.get("candidate_name", "")).startswith("xgb:daily_ranker")
    ]
    if len(traces) != 1:
        raise CnFormalFreshnessError("expected one frozen original trace")
    trace = traces[0]
    if trace.get("research_only") is not True or trace.get("trade_ready") is not False:
        raise CnFormalFreshnessError("trace research boundary weakened")
    if trace.get("forward_horizon_sessions") != 10:
        raise CnFormalFreshnessError("formal horizon changed")
    points, holdings, contributions = (
        trace.get("points"), trace.get("holdings"), trace.get("name_contributions")
    )
    metrics = trace.get("metrics")
    if not all(isinstance(x, list) for x in (points, holdings, contributions)):
        raise CnFormalFreshnessError("trace rows missing")
    if not isinstance(metrics, dict) or not (
        len(points) == len(holdings) == len(contributions)
        == int(metrics.get("n_periods", -1))
    ):
        raise CnFormalFreshnessError("trace dimensions differ")
    return window, trace


def _strip_partial(package: dict[str, Any]) -> dict[str, int]:
    removed: dict[str, int] = {}
    for field in ("report", "positions", "trades", "window_summary"):
        rows = package.get(field)
        if not isinstance(rows, list):
            raise CnFormalFreshnessError(f"formal field missing: {field}")
        kept = [
            row for row in rows
            if not isinstance(row, dict) or row.get("window") != PARTIAL
        ]
        removed[field] = len(rows) - len(kept)
        package[field] = kept
    if removed["report"] != 1 or removed["window_summary"] != 1:
        raise CnFormalFreshnessError("existing partial extension shape changed")
    if removed["positions"] <= 0:
        raise CnFormalFreshnessError("existing partial positions missing")
    if package["window_summary"][-1].get("window") != "2026H1":
        raise CnFormalFreshnessError("accepted historical window prefix changed")
    return removed


def _relative(strategy: float, benchmark: float) -> float:
    return (1 + strategy) / (1 + benchmark) - 1


def _append_partial(
    package: dict[str, Any], window: dict[str, Any], trace: dict[str, Any],
    calendar: list[str], source: dict[str, Any],
) -> None:
    metrics = trace["metrics"]
    points = trace["points"]
    holdings = trace["holdings"]
    benchmark_returns = [float(x) for x in metrics["benchmark_period_returns"]]
    if len(benchmark_returns) != len(points):
        raise CnFormalFreshnessError("benchmark trace length mismatch")
    account = float(package["report"][-1]["account"])
    bench = float(package["report"][-1]["bench_hs300"])
    peak = max(float(row["account"]) for row in package["report"])
    worst = min(
        [0.0]
        + [
            float(row[key])
            for row in package["report"] if isinstance(row, dict)
            for key in ("drawdown", "max_drawdown")
            if isinstance(row.get(key), (int, float))
        ]
    )
    for point, benchmark_return in zip(points, benchmark_returns, strict=True):
        net = float(point["net_period_return"])
        if not math.isfinite(net) or net <= -1:
            raise CnFormalFreshnessError("invalid period return")
        account *= 1 + net
        bench *= 1 + benchmark_return
        peak = max(peak, account)
        worst = min(worst, account / peak - 1)
    latest_end = max(_holding_end(calendar, str(row["signal_date"])) for row in points)
    package["report"].append({
        "date": str(metrics["test_end"]),
        "holding_end_date": latest_end,
        "account": account,
        "bench_hs300": bench,
        "period_return": float(metrics["total_return"]),
        "benchmark_return": float(metrics["benchmark_return"]),
        "excess_return": float(metrics["excess_return"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "turnover": float(metrics["turnover"]),
        "window": PARTIAL,
        "partial_window": True,
        "trace_frequency": "partial_half_year_window",
    })
    final_holding = holdings[-1]
    signal = str(final_holding["signal_date"])
    holding_end = _holding_end(calendar, signal)
    weights = {str(k): float(v) for k, v in dict(final_holding["weights"]).items()}
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise CnFormalFreshnessError("final weights do not sum to one")
    for instrument in sorted(weights):
        package["positions"].append({
            "date": signal,
            "holding_end_date": holding_end,
            "instrument": instrument,
            "weight": weights[instrument],
            "window": PARTIAL,
            "snapshot_semantics": "final_top15_for_partial_window",
            "rank_evidence": "not_retained",
        })
    package["window_summary"].append({
        "window": PARTIAL,
        "source_window": "2026H2",
        "complete": False,
        "counts_toward_model_selection": False,
        "start": str(metrics["test_start"]),
        "end": str(metrics["test_end"]),
        "latest_realized_holding_end": latest_end,
        "provider_cutoff": source["cutoff"],
        "n_periods": int(metrics["n_periods"]),
        "total_return": float(metrics["total_return"]),
        "benchmark_return": float(metrics["benchmark_return"]),
        "compounded_relative_excess_return": _relative(
            float(metrics["total_return"]), float(metrics["benchmark_return"])
        ),
        "max_drawdown": float(metrics["max_drawdown"]),
        "turnover": float(metrics["turnover"]),
        "horizon_eligible_sessions": int(window["horizon_eligible_sessions"]),
        "trace_sha256": source["trace_sha256"]["2026H2"],
        "benchmark_period_returns": benchmark_returns,
    })
    package["metrics"] = {
        **package["metrics"],
        "Total Return": account - 1,
        "Benchmark Return": bench - 1,
        "Compounded Relative Excess Return": account / bench - 1,
        "Max Drawdown": worst,
    }
    package["backtest_id"] = "cn_x1_0_through_2026_08_03"
    package["generated_at"] = source["generated_at"]
    package["evidence_cutoff"] = source["cutoff"]
    package["date_range"]["end"] = source["cutoff"]
    evidence = package.get("evidence")
    if not isinstance(evidence, dict):
        raise CnFormalFreshnessError("CN evidence missing")
    previous = evidence.get("freshness_evidence")
    previous_identity = previous.get("provider_identity_sha256") if isinstance(previous, dict) else None
    evidence["freshness_evidence"] = {
        "schema_version": "1.0.0",
        "source_status": source["status"],
        "workflow_run_id": str(source["workflow_run_id"]),
        "workflow_head_sha": source["workflow_head_sha"],
        "artifact_id": source["artifact_id"],
        "artifact_name": source["artifact_name"],
        "artifact_digest": source["artifact_digest"],
        "provider_workflow_run_id": source["provider_workflow_run_id"],
        "provider_artifact_id": source["provider_artifact_id"],
        "provider_artifact_name": source["provider_artifact_name"],
        "provider_artifact_digest": source["provider_artifact_digest"],
        "provider_tar_sha256": source["provider_tar_sha256"],
        "provider_identity_sha256": source["provider_identity_sha256"],
        "provider_cutoff": source["cutoff"],
        "independent_execution_count": 2,
        "trace_sha256": source["trace_sha256"],
        "model_selection_reopened": False,
        "automatic_promotion": False,
        "superseded_provider_identity_sha256": previous_identity,
        "provider_snapshot_revision_observed": bool(
            previous_identity and previous_identity != source["provider_identity_sha256"]
        ),
    }
    package["evidence"] = evidence
    package["freshness"] = {
        "schema_version": "1.0.0",
        "status": "current",
        "required_cutoff": source["cutoff"],
        "latest_completed_session": source["cutoff"],
        "latest_realized_holding_end": latest_end,
        "partial_final_window": PARTIAL,
        "model_selection_reopened": False,
    }
    completeness = package.get("evidence_completeness")
    if not isinstance(completeness, dict):
        raise CnFormalFreshnessError("evidence completeness missing")
    missing = {str(x) for x in completeness.get("missing", [])}
    missing.update({"historical_transaction_ledger", "historical_security_attribution"})
    completeness.update({
        "status": "partial",
        "latest_partial_window_trace": "retained_exact",
        "missing": sorted(missing),
    })
    package["evidence_completeness"] = completeness
    package["interpretation_notes"] = [
        "Formal accepted CN x1.0 history through 2026H1 is retained unchanged.",
        "2026H2_partial is a deterministic reporting extension of the frozen model.",
        "The partial window is excluded from model selection and automatic promotion.",
        "Historical transaction-ledger and security-attribution evidence remain unavailable; the frontend must continue to show that limitation.",
        f"Provider evidence is current through {source['cutoff']}; the latest realized ten-session holding ends {latest_end}.",
        "Research evidence only; not authorization for live or automated trading.",
        "Latest-window position ranks are not displayed because the retained trace contains equal-weight membership but no auditable rank ordering.",
        "The 2026-08-03 CN provider retains the accepted 2026-07-31 prefix and appends one independently verified completed session.",
    ]


def promote(root: Path, artifact_root: Path, source_path: Path) -> dict[str, Any]:
    source = _read(source_path)
    _validate_source(source)
    provider = _read(artifact_root / "provider" / "provider-receipt.json")
    if (
        provider.get("status") != "complete"
        or provider.get("cutoff") != source["cutoff"]
        or provider.get("provider_identity_sha256") != source["provider_identity_sha256"]
    ):
        raise CnFormalFreshnessError("provider receipt mismatch")
    calendar = _calendar(
        artifact_root / "provider" / "data" / "providers" / "cn"
        / "calendars" / "day.txt"
    )
    if len(calendar) != 1352 or calendar[-1] != source["cutoff"]:
        raise CnFormalFreshnessError("provider calendar mismatch")
    a = artifact_root / "freshness" / "cn-a" / "cn_x1_0_frozen_v1"
    b = artifact_root / "freshness" / "cn-b" / "cn_x1_0_frozen_v1"
    window, trace_a = _load_trace(a, source["cutoff"])
    _, trace_b = _load_trace(b, source["cutoff"])
    digest_a, digest_b = _trace_hash(trace_a), _trace_hash(trace_b)
    if digest_a != digest_b or digest_a != source["trace_sha256"]["2026H2"]:
        raise CnFormalFreshnessError("independent trace identity mismatch")

    cn_path = root / "cn_x1_0.json"
    catalog_path = root / "catalog.json"
    freshness_path = root / "freshness.json"
    qqq_path = root / "qqqi_qqq_tqqq_v4_2.json"
    us_path = root / "us_x1_1.json"
    immutable = {"qqq": _sha(qqq_path), "us": _sha(us_path)}
    package = _read(cn_path)
    if (
        package.get("model_id") != "cn_x1_0"
        or package.get("evidence_cutoff") != source["previous_cutoff"]
        or package.get("research_only") is not True
        or package.get("trade_ready") is not False
    ):
        raise CnFormalFreshnessError("previous CN formal release mismatch")
    prior = copy.deepcopy(package)
    removed = _strip_partial(package)
    prefix_hashes = {
        field: hashlib.sha256(
            json.dumps(package[field], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        for field in ("report", "positions", "trades", "attribution", "window_summary")
    }
    _append_partial(package, window, trace_a, calendar, source)
    _canonical(cn_path, package)

    catalog = _read(catalog_path)
    rows = catalog.get("records")
    if not isinstance(rows, list):
        raise CnFormalFreshnessError("catalog records missing")
    matches = [row for row in rows if isinstance(row, dict) and row.get("model_id") == "cn_x1_0"]
    if len(matches) != 1:
        raise CnFormalFreshnessError("catalog CN record mismatch")
    matches[0]["sha256"] = _sha(cn_path)
    catalog["published_at"] = source["generated_at"]
    _canonical(catalog_path, catalog)

    freshness = _read(freshness_path)
    markets = freshness.get("markets")
    closes = freshness.get("next_session_close_utc")
    if not isinstance(markets, dict) or not isinstance(closes, dict):
        raise CnFormalFreshnessError("freshness market maps missing")
    if markets.get("cn") != source["previous_cutoff"]:
        raise CnFormalFreshnessError("previous CN freshness cutoff mismatch")
    markets["cn"] = source["cutoff"]
    closes["cn"] = source["next_session_close_utc"]
    freshness["declared_at"] = source["generated_at"]
    _pretty(freshness_path, freshness)

    if immutable != {"qqq": _sha(qqq_path), "us": _sha(us_path)}:
        raise CnFormalFreshnessError("US or QQQ package changed")
    return {
        "schema_version": "1.0.0",
        "status": "promoted_incremental_cn_freshness",
        "cutoff": source["cutoff"],
        "previous_cutoff": source["previous_cutoff"],
        "source_artifact_id": source["artifact_id"],
        "provider_identity_sha256": source["provider_identity_sha256"],
        "trace_sha256": digest_a,
        "removed_previous_partial_rows": removed,
        "historical_prefix_sha256": prefix_hashes,
        "prior_package_sha256": hashlib.sha256(
            json.dumps(prior, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "package_sha256": _sha(cn_path),
        "catalog_sha256": _sha(catalog_path),
        "freshness_sha256": _sha(freshness_path),
        "immutable_package_sha256": immutable,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = promote(args.root, args.artifact_root, args.source)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
