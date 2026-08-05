"""Build and audit CN130 primary buyback and restricted-unlock event streams."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.data.build_cn130_pit_event_families import (
    FAMILIES as PHASE1_FAMILIES,
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
from src.data.company_events.ashare_primary_announcements import (
    AsharePrimaryAnnouncementClient,
    cninfo_primary_announcements_to_events,
)
from src.data.company_events.event_store import CompanyInformationEvent

FAMILIES = ("buyback", "restricted_unlock")


def phase2_overlap_matrix(events: pd.DataFrame) -> pd.DataFrame:
    """Measure same-symbol/date overlap only across the Phase 2 families."""

    keys: dict[str, set[tuple[str, str]]] = {}
    for family in FAMILIES:
        family_rows = events.loc[events["event_family"] == family]
        keys[family] = set(
            zip(family_rows["symbol"], family_rows["announced_date"], strict=False)
        )
    rows: list[dict[str, Any]] = []
    for left in FAMILIES:
        for right in FAMILIES:
            intersection = keys[left] & keys[right]
            denominator = len(keys[left] | keys[right])
            rows.append(
                {
                    "left_family": left,
                    "right_family": right,
                    "overlap_count": len(intersection),
                    "jaccard": len(intersection) / denominator if denominator else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _cache_path(root: Path, family: str, symbol: str) -> Path:
    return root / f"cninfo_{family}" / f"{symbol}.json"


def _report(decision: dict[str, Any], summary: pd.DataFrame) -> str:
    lines = [
        "# CN130 primary event-family Phase 2 result",
        "",
        f"**Decision:** `{decision['decision']}`",
        "",
        "This phase audits primary CNINFO announcements only. It does not inspect returns or create a model candidate.",
        "",
        "## Family gates",
        "",
        "| Family | Events | Symbols | Fixed eligible | Event-driven eligible |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples():
        lines.append(
            f"| {row.event_family} | {int(row.unique_events)} | {int(row.unique_symbols)} | "
            f"{bool(row.fixed_rebalance_eligible)} | {bool(row.event_driven_eligible)} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "A passing data gate only authorizes a separately preregistered model experiment. Current-state buyback or unlock snapshots were not backfilled into history.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    pool_id, symbols = load_pool(args.pool_spec)
    sessions = load_sessions(args.provider_dir)
    ledger = load_r0_ledgers(args.ledger_dirs)
    top3 = build_r0_top3_rows(ledger)
    client = AsharePrimaryAnnouncementClient()

    receipts: list[dict[str, Any]] = []
    events: list[CompanyInformationEvent] = []
    for symbol in symbols:
        for family, method in (
            ("buyback", client.fetch_buyback),
            ("restricted_unlock", client.fetch_restricted_unlock),
        ):
            identity = {
                "provider": "akshare_cninfo",
                "family": family,
                "symbol": symbol,
                "start": args.start,
                "cutoff": args.cutoff,
                "keyword": "回购" if family == "buyback" else "限售",
            }
            frame, receipt = fetch_cached_frame(
                path=_cache_path(args.source_cache_root, family, symbol),
                identity=identity,
                fetcher=lambda m=method, s=symbol: m(
                    symbol=s,
                    start_date=args.start,
                    end_date=args.cutoff,
                ),
                execution_at=args.execution_at,
                refresh=args.refresh_source_cache,
            )
            receipts.append({key: value for key, value in receipt.items() if key != "frame_json"})
            if not frame.empty:
                events.extend(
                    cninfo_primary_announcements_to_events(
                        frame,
                        family=family,
                        sessions=sessions,
                        retrieved_at=str(receipt["retrieved_at"]),
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

    half_year_rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        half_year_rows.extend(
            audit_family(
                family=family,
                events=event_frame,
                top3=top3,
                sessions=sessions,
            )
        )
    half_year_frame = pd.DataFrame(half_year_rows).sort_values(
        ["event_family", "half_year"], kind="mergesort"
    )
    write_csv(output / "event_family_half_year.csv", half_year_frame)

    fixed_eligible: list[str] = []
    event_eligible: list[str] = []
    summary_rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        family_events = event_frame.loc[event_frame["event_family"] == family]
        family_half_year = half_year_frame.loc[half_year_frame["event_family"] == family]
        fixed, event_driven, reasons = eligibility(family_half_year)
        if family == "restricted_unlock":
            event_driven = False
            if "single_stage_family_event_driven_not_authorized" not in reasons:
                reasons.append("single_stage_family_event_driven_not_authorized")
        if fixed:
            fixed_eligible.append(family)
        if event_driven:
            event_eligible.append(family)
        summary_rows.append(
            {
                "event_family": family,
                "unique_events": int(family_events["event_id"].nunique()),
                "unique_symbols": int(family_events["symbol"].nunique()),
                "primary_source_ratio": (
                    float((family_events["reconciliation_status"] == "reconciled").mean())
                    if len(family_events)
                    else 0.0
                ),
                "first_session_mapping_ratio": (
                    float((family_events["first_eligible_session"] != "").mean())
                    if len(family_events)
                    else 0.0
                ),
                "fixed_rebalance_eligible": fixed,
                "event_driven_eligible": event_driven,
                "failure_reasons": "|".join(reasons),
            }
        )
    summary = pd.DataFrame(summary_rows)
    write_csv(output / "event_family_summary.csv", summary)
    write_csv(output / "overlap_matrix.csv", phase2_overlap_matrix(event_frame))

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
    eligible_union = set(fixed_eligible) | set(event_eligible)
    if not ordered_events and successful_sources == 0:
        decision_name = "event_population_data_blocked"
    elif len(eligible_union) > 1:
        decision_name = "multiple_independent_event_families_eligible"
    elif event_eligible:
        decision_name = "event_driven_family_eligible"
    elif fixed_eligible:
        decision_name = "fixed_rebalance_event_family_eligible"
    else:
        decision_name = "event_population_built_no_family_eligible"
    decision = {
        "schema_version": "cn130_pit_event_families_phase2_v1",
        "decision": decision_name,
        "fixed_rebalance_eligible_families": fixed_eligible,
        "event_driven_eligible_families": event_eligible,
        "validation_returns_inspected": False,
        "research_only": True,
        "trade_ready": False,
        "automatic_model_promotion": False,
    }
    write_json(output / "decision.json", decision)

    source_cache_files = sorted(args.source_cache_root.rglob("*.json"))
    source_cache_manifest = {
        "schema_version": "cn130_pit_primary_event_source_cache_v1",
        "execution_at": args.execution_at,
        "receipt_count": len(source_cache_files),
        "receipts": [
            {
                "path": str(path.relative_to(args.source_cache_root)),
                "sha256": sha256(path),
            }
            for path in source_cache_files
        ],
    }
    write_json(output / "source_cache_manifest.json", source_cache_manifest)

    manifest = {
        "schema_version": "cn130_pit_event_families_phase2_v1",
        "pool_id": pool_id,
        "pool_sha256": sha256(args.pool_spec),
        "provider_identity_sha256": json.loads(
            (args.provider_dir / "provider_manifest.json").read_text(encoding="utf-8")
        )["provider_identity_sha256"],
        "period_start": args.start,
        "cutoff": args.cutoff,
        "families": list(FAMILIES),
        "base_phase1_families": list(PHASE1_FAMILIES),
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
    (output / "report.md").write_text(_report(decision, summary), encoding="utf-8")
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
