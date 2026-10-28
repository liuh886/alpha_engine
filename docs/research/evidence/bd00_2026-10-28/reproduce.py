"""Reproduce BD-00's dated metadata survey; no model, labels or provider refresh."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import importlib.metadata
import subprocess
import sys
from pathlib import Path

import exchange_calendars as xcals
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.data.research_slice import DataSliceRequest, get_research_data_slice
from src.research.study_workspace import study_catalog

START, CUTOFF = "2021-01-01", "2026-10-27"
SOURCE_COMMIT = "ba5418e048e0f20d8d8dc6eb5ba1ff72e76b2515"
POOL = "us_selected_equities_v2"
FIELDS = ("open", "high", "low", "close", "volume")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output: Path) -> None:
    pool_path = ROOT / f"configs/research_universes/{POOL}.yaml"
    symbols = yaml.safe_load(pool_path.read_text(encoding="utf-8"))["symbols"]
    assert len(symbols) == len(set(symbols)) == 87
    catalog_path = ROOT / "data/research/market_evidence/us/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    registered = {item["symbol"]: item for item in catalog["symbols"]}
    sessions = [str(day.date()) for day in xcals.get_calendar("XNYS").sessions_in_range(START, CUTOFF)]
    output.mkdir(parents=True, exist_ok=True)
    receipts = {}
    for name, requested in [("us87", tuple(symbols)), ("qqq_reference", ("QQQ",))]:
        request = DataSliceRequest("us", POOL, requested, START, CUTOFF, CUTOFF)
        receipt = get_research_data_slice(request, root=ROOT).receipt
        (output / f"{name}_slice.json").write_text(json.dumps({"request": request.to_dict(),
            "receipt": receipt}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipts[name] = {"status": receipt["status"], "data_hash": receipt.get("data_hash"),
            "total_rows": receipt["total_rows"], "receipt_file": f"{name}_slice.json"}
    rows = []
    for symbol in [*symbols, "QQQ"]:
        path = ROOT / f"data/research/market_evidence/us/symbols/{symbol}.json"
        blockers = []
        row = {"symbol": symbol, "role": "candidate" if symbol in symbols else "benchmark_reference",
               "source_path": path.relative_to(ROOT).as_posix()}
        if not path.exists():
            row["blockers"] = ["source_missing"]
            rows.append(row)
            continue
        source = json.loads(path.read_text(encoding="utf-8"))
        bars = [bar for bar in source.get("bars", []) if START <= bar["time"] <= CUTOFF]
        dates = [bar["time"] for bar in bars]
        if not bars:
            blockers.append("no_observations_in_survey_range")
        sha = digest(path)
        if registered.get(symbol, {}).get("sha256") != sha:
            blockers.append("catalog_source_hash_mismatch")
        if dates != sorted(set(dates)):
            blockers.append("unordered_or_duplicate_dates")
        invalid_fields = sum(not all(isinstance(bar.get(f), (int, float))
            and not isinstance(bar.get(f), bool) and math.isfinite(bar[f])
            and bar[f] >= (0 if f == "volume" else 1e-12) for f in FIELDS) for bar in bars)
        if invalid_fields:
            blockers.append("invalid_required_ohlcv")
        observed = set(dates)
        missing = [d for d in sessions if dates and d >= dates[0] and d not in observed]
        if missing:
            blockers.append("missing_sessions_since_first_observation")
        row.update(source_sha256=sha, catalog_hash_matches="catalog_source_hash_mismatch" not in blockers,
            provider_manifest_sha256=source.get("provider_manifest_sha256"),
            source_csv_sha256=source.get("source_csv_sha256"), bar_count=len(bars),
            first_observation=min(dates) if dates else None, last_observation=max(dates) if dates else None,
            sessions_before_first_observation=sum(d < dates[0] for d in sessions) if dates else len(sessions),
            missing_sessions_since_first_observation=missing, invalid_ohlcv_rows=invalid_fields,
            zero_range_rows=sum(bar.get("high") is not None and bar.get("high") == bar.get("low") for bar in bars),
            zero_volume_rows=sum(bar.get("volume") == 0 for bar in bars), blockers=blockers)
        rows.append(row)
    identities = [pool_path, catalog_path, ROOT / "configs/pools/selected_pool_registry_v1.yaml",
        ROOT / "configs/pools/reference_instrument_registry_v1.yaml", ROOT / "src/data/research_slice.py",
        ROOT / "src/research/study_workspace.py", ROOT / "src/research/walkforward/pipeline.py",
        Path(__file__).resolve()]
    components = {}
    for kind in ["corporate_actions", "fundamentals"]:
        path = ROOT / f"data/research/model_data_bundle_v1/sources/us_events/{kind}/component_manifest.json"
        if path.exists():
            identities.append(path)
            value = json.loads(path.read_text(encoding="utf-8"))
            components[kind] = {key: value.get(key) for key in ["component_id", "status", "evidence_cutoff",
                "expected_symbol_count", "ready_symbol_count", "coverage_ratio", "missing_symbols"]}
            components[kind]["details"] = value.get("details", {})
            components[kind]["payload_presence"] = {part: (path.parent.parent / value["details"][f"{part}_path"]).is_file()
                for part in ["coverage", "events"]}
            components[kind]["payload_integrity_validated"] = False
        else:
            components[kind] = {"status": "manifest_missing"}
    # A moving remote ref must not re-label a dated survey. Require the exact
    # tracked source/config/code bytes at the stated baseline; docs may evolve.
    tracked_inputs = [p for p in identities if p != Path(__file__).resolve()]
    tracked_inputs.extend(ROOT / row["source_path"] for row in rows)
    subprocess.run(["git", "diff", "--quiet", SOURCE_COMMIT, "--",
        *(p.relative_to(ROOT).as_posix() for p in tracked_inputs)], cwd=ROOT, check=True)
    report = {"schema_version": "bd00_metadata_survey_v1", "survey_start": START, "as_of_cutoff": CUTOFF,
        "source_tree_commit": SOURCE_COMMIT,
        "pool_id": POOL, "candidate_count": len(symbols), "reference_symbols": ["QQQ"],
        "calendar_version": importlib.metadata.version("exchange_calendars"),
        "study_templates": [item["id"] for item in study_catalog(root=ROOT)["studies"]],
        "slice_receipts": receipts, "component_observations": components, "symbols": rows,
        "input_sha256": {p.relative_to(ROOT).as_posix(): digest(p) for p in identities},
        "experiment_ready": False, "pit_certified": False, "research_only": True, "trade_ready": False,
        "limitations": ["Survey dates are inventory bounds, not training/OOS choices.",
            "First observed bar is not certified listing date; missing sessions are not inferred halts.",
            "Slice ready verifies readability/cutoff, not complete sessions, vintage availability or revisions.",
            "Existing corporate-action/fundamental components require separate source/availability validation at the experiment cutoff.",
            "Earnings/sector/regime/veto requirements and owner A-D preregistration remain unresolved.",
            "No raw bars, formal model events, targets, account data, performance or forward labels are exported."]}
    (output / "survey.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"candidates": len(symbols), "references": 1, "slice_receipts": receipts,
        "symbols_with_blockers": {r["symbol"]: r["blockers"] for r in rows if r["blockers"]},
        "pit_certified": False, "experiment_ready": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Fresh local directory for metadata-only receipts")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a new directory to preserve prior evidence")
    run(args.output.resolve())
