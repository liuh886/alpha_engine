"""Build and audit CN130 shareholder and insider holding-change events."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.data.build_cn130_pit_event_families import (
    audit_family,
    build_r0_top3_rows,
    eligibility,
    events_to_frame,
    fetch_cached_frame,
    load_pool,
    load_r0_ledgers,
    load_sessions,
    sha256,
    write_csv,
    write_json,
)
from src.data.company_events.ashare_holding_change_events import (
    AshareHoldingChangeClient,
    cninfo_holding_change_to_events,
)
from src.data.company_events.event_store import CompanyInformationEvent

FAMILY = "holding_change"
KEYWORDS = ("增持", "减持")


def _cache_path(root: Path, keyword: str, symbol: str) -> Path:
    slug = "increase" if keyword == "增持" else "decrease"
    return root / f"cninfo_holding_{slug}" / f"{symbol}.json"


def _stage_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["event_stage", "event_count", "symbol_count", "share"])
    grouped = (
        events.groupby("event_stage", sort=True)
        .agg(event_count=("event_id", "nunique"), symbol_count=("symbol", "nunique"))
        .reset_index()
    )
    grouped["share"] = grouped["event_count"] / grouped["event_count"].sum()
    return grouped


def _report(decision: dict[str, Any], summary: pd.DataFrame, stages: pd.DataFrame) -> str:
    row = summary.iloc[0]
    lines = [
        "# CN130 holding-change event-family Phase 3 result",
        "",
        f"**Decision:** `{decision['decision']}`",
        "",
        "This phase audits primary CNINFO announcements only. It does not inspect returns or create a model candidate.",
        "",
        "## Family gate",
        "",
        "| Events | Symbols | Fixed eligible | Event-driven eligible |",
        "|---:|---:|---:|---:|",
        f"| {int(row['unique_events'])} | {int(row['unique_symbols'])} | {bool(row['fixed_rebalance_eligible'])} | {bool(row['event_driven_eligible'])} |",
        "",
        "## Stage distribution",
        "",
        "| Stage | Events | Symbols | Share |",
        "|---|---:|---:|---:|",
    ]
    for stage in stages.itertuples():
        lines.append(
            f"| {stage.event_stage} | {int(stage.event_count)} | {int(stage.symbol_count)} | {stage.share:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "A passing data gate only authorizes a separately preregistered model experiment. Current shareholder balances were not used to backfill historical availability.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    pool_id, symbols = load_pool(args.pool_spec)
    sessions = load_sessions(args.provider_dir)
    ledger = load_r0_ledgers(args.ledger_dirs)
    top3 = build_r0_top3_rows(ledger)
    client = AshareHoldingChangeClient()

    receipts: list[dict[str, Any]] = []
    events: list[CompanyInformationEvent] = []
    for symbol in symbols:
        frames: list[pd.DataFrame] = []
        retrieval_times: list[str] = []
        for keyword in KEYWORDS:
            identity = {
                "provider": "akshare_cninfo",
                "family": FAMILY,
                "keyword": keyword,
                "symbol": symbol,
                "start": args.start,
                "cutoff": args.cutoff,
            }
            frame, receipt = fetch_cached_frame(
                path=_cache_path(args.source_cache_root, keyword, symbol),
                identity=identity,
                fetcher=lambda s=symbol, k=keyword: client.fetch(
                    symbol=s,
                    keyword=k,
                    start_date=args.start,
                    end_date=args.cutoff,
                ),
                execution_at=args.execution_at,
                refresh=args.refresh_source_cache,
            )
            receipts.append({key: value for key, value in receipt.items() if key != "frame_json"})
            frames.append(frame)
            retrieval_times.append(str(receipt["retrieved_at"]))
        events.extend(
            cninfo_holding_change_to_events(
                frames,
                sessions=sessions,
                retrieved_at=max(retrieval_times),
                allowed_symbols=[symbol],
            )
        )

    unique = {
        event.event_id: event
        for event in events
        if event.announced_at[:10] <= args.cutoff
    }
    ordered_events = sorted(
        unique.values(), key=lambda event: (event.announced_at, event.symbol, event.event_id)
    )
    event_frame = events_to_frame(ordered_events)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    events_path = output / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as handle:
        for event in ordered_events:
            handle.write(
                json.dumps(
                    event.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )

    half_year_frame = pd.DataFrame(
        audit_family(
            family=FAMILY,
            events=event_frame,
            top3=top3,
            sessions=sessions,
        )
    ).sort_values(["event_family", "half_year"], kind="mergesort")
    write_csv(output / "event_family_half_year.csv", half_year_frame)

    fixed, event_driven, reasons = eligibility(half_year_frame)
    summary = pd.DataFrame(
        [
            {
                "event_family": FAMILY,
                "unique_events": int(event_frame["event_id"].nunique()),
                "unique_symbols": int(event_frame["symbol"].nunique()),
                "primary_source_ratio": (
                    float((event_frame["reconciliation_status"] == "reconciled").mean())
                    if len(event_frame)
                    else 0.0
                ),
                "first_session_mapping_ratio": (
                    float((event_frame["first_eligible_session"] != "").mean())
                    if len(event_frame)
                    else 0.0
                ),
                "fixed_rebalance_eligible": fixed,
                "event_driven_eligible": event_driven,
                "failure_reasons": "|".join(reasons),
            }
        ]
    )
    write_csv(output / "event_family_summary.csv", summary)
    stages = _stage_summary(event_frame)
    write_csv(output / "event_stage_summary.csv", stages)

    provider_status = pd.DataFrame(receipts)
    if not provider_status.empty:
        provider_status["identity"] = provider_status["identity"].map(
            lambda value: json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    write_csv(output / "provider_status.csv", provider_status)

    successful_sources = sum(str(row.get("status")) == "success" for row in receipts)
    if not ordered_events and successful_sources == 0:
        decision_name = "event_population_data_blocked"
    elif fixed and event_driven:
        decision_name = "multiple_model_paths_eligible"
    elif event_driven:
        decision_name = "event_driven_family_eligible"
    elif fixed:
        decision_name = "fixed_rebalance_event_family_eligible"
    else:
        decision_name = "event_population_built_no_family_eligible"
    decision = {
        "schema_version": "cn130_pit_event_families_phase3_v1",
        "decision": decision_name,
        "fixed_rebalance_eligible_families": [FAMILY] if fixed else [],
        "event_driven_eligible_families": [FAMILY] if event_driven else [],
        "validation_returns_inspected": False,
        "research_only": True,
        "trade_ready": False,
        "automatic_model_promotion": False,
    }
    write_json(output / "decision.json", decision)

    source_cache_files = sorted(args.source_cache_root.rglob("*.json"))
    source_cache_manifest = {
        "schema_version": "cn130_pit_holding_change_source_cache_v1",
        "execution_at": args.execution_at,
        "receipt_count": len(source_cache_files),
        "receipts": [
            {"path": str(path.relative_to(args.source_cache_root)), "sha256": sha256(path)}
            for path in source_cache_files
        ],
    }
    write_json(output / "source_cache_manifest.json", source_cache_manifest)

    manifest = {
        "schema_version": "cn130_pit_event_families_phase3_v1",
        "pool_id": pool_id,
        "pool_sha256": sha256(args.pool_spec),
        "provider_identity_sha256": json.loads(
            (args.provider_dir / "provider_manifest.json").read_text(encoding="utf-8")
        )["provider_identity_sha256"],
        "period_start": args.start,
        "cutoff": args.cutoff,
        "family": FAMILY,
        "keywords": list(KEYWORDS),
        "event_count": len(ordered_events),
        "events_sha256": sha256(events_path),
        "source_cache_manifest_sha256": sha256(output / "source_cache_manifest.json"),
        "ledger_files": [
            {"path": str(path), "sha256": sha256(path)}
            for root in args.ledger_dirs
            for path in sorted(
                root.glob("*__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz")
            )
        ],
        "validation_returns_inspected": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output / "manifest.json", manifest)
    (output / "report.md").write_text(_report(decision, summary, stages), encoding="utf-8")
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-spec",
        type=Path,
        default=Path("configs/research_universes/cn_selected_equities_v3.yaml"),
    )
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument(
        "--ledger-dir", dest="ledger_dirs", type=Path, action="append", required=True
    )
    parser.add_argument("--source-cache-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--cutoff", default="2026-08-03")
    parser.add_argument("--execution-at", required=True)
    parser.add_argument("--refresh-source-cache", action="store_true")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
