"""Build and audit CN130 PIT earnings-event families without inspecting returns."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd
import yaml

from src.data.company_events.ashare_earnings_events import (
    AshareEarningsEventClient,
    cninfo_disclosure_index,
    eastmoney_earnings_forecast_to_events,
    eastmoney_preliminary_earnings_to_events,
)
from src.data.company_events.event_store import CompanyInformationEvent

CALIBRATION_HALF_YEARS = ("2022H2", "2023H1", "2023H2")
FAMILIES = ("earnings_forecast", "preliminary_earnings")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML must be a mapping: {path}")
    return payload


def load_pool(path: Path) -> tuple[str, list[str]]:
    payload = load_yaml(path)
    pool_id = str(payload.get("pool_id", ""))
    symbols = [str(value).zfill(6) for value in payload.get("symbols", [])]
    expected = int(payload.get("candidate_count", 0))
    if pool_id != "cn_selected_equities_v3":
        raise ValueError("pool_id must be cn_selected_equities_v3")
    if len(symbols) != expected or len(set(symbols)) != expected or expected != 130:
        raise ValueError("CN130 pool identity is not exact")
    return pool_id, symbols


def quarter_ends(start: str, cutoff: str) -> list[str]:
    start_date = date.fromisoformat(start)
    cutoff_date = date.fromisoformat(cutoff)
    rows: list[str] = []
    for year in range(start_date.year, cutoff_date.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = date(year, month, day)
            if start_date <= value <= cutoff_date:
                rows.append(value.isoformat())
    return rows


def half_year(value: str) -> str:
    parsed = date.fromisoformat(str(value)[:10])
    return f"{parsed.year}H{1 if parsed.month <= 6 else 2}"


def load_sessions(provider_dir: Path) -> list[str]:
    path = provider_dir / "calendars/day.txt"
    rows = [line.strip()[:10] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if rows != sorted(set(rows)):
        raise ValueError("provider trading calendar must be unique and sorted")
    return rows


def _cache_path(root: Path, family: str, key: str) -> Path:
    return root / family / f"{key}.json"


def _frame_to_json(frame: pd.DataFrame) -> str:
    return frame.to_json(orient="table", date_format="iso", force_ascii=False, index=False)


def _frame_from_json(value: str) -> pd.DataFrame:
    return pd.read_json(io.StringIO(value), orient="table")


def fetch_cached_frame(
    *,
    path: Path,
    identity: Mapping[str, Any],
    fetcher: Callable[[], pd.DataFrame],
    execution_at: str,
    refresh: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    canonical_identity = json.loads(json.dumps(dict(identity), sort_keys=True))
    if path.exists() and not refresh:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("identity") != canonical_identity:
            raise ValueError(f"source-cache identity mismatch: {path}")
        if receipt.get("status") == "success":
            return _frame_from_json(str(receipt["frame_json"])), receipt
        return pd.DataFrame(), receipt
    try:
        frame = fetcher()
        if frame is None:
            frame = pd.DataFrame()
        receipt = {
            "schema_version": "exact_frame_receipt_v1",
            "identity": canonical_identity,
            "retrieved_at": execution_at,
            "status": "success",
            "row_count": int(len(frame)),
            "columns": [str(value) for value in frame.columns],
            "frame_json": _frame_to_json(frame),
            "error_type": "",
            "error": "",
        }
    except Exception as exc:  # provider failures are evidence, not silent drops
        receipt = {
            "schema_version": "exact_frame_receipt_v1",
            "identity": canonical_identity,
            "retrieved_at": execution_at,
            "status": "failed",
            "row_count": 0,
            "columns": [],
            "frame_json": "",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        frame = pd.DataFrame()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, receipt)
    return frame, receipt


def load_r0_ledgers(roots: Sequence[Path]) -> pd.DataFrame:
    paths: list[Path] = []
    for root in roots:
        paths.extend(sorted(root.glob("*__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz")))
    if not paths:
        raise ValueError("no frozen R0 score ledgers found")
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(
            path,
            compression="gzip",
            dtype={"instrument": str},
            parse_dates=["datetime"],
        )
        required = {"datetime", "instrument", "score", "sector", "window"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"R0 ledger missing columns {missing}: {path}")
        frame["instrument"] = frame["instrument"].str.zfill(6)
        frame["source_path"] = path.name
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(["window", "datetime", "instrument"], keep="last")
    return combined.sort_values(["window", "datetime", "instrument"], kind="mergesort")


def build_r0_top3_rows(ledger: pd.DataFrame) -> pd.DataFrame:
    output: list[pd.DataFrame] = []
    for (window, timestamp), day in ledger.groupby(["window", "datetime"], sort=True):
        ranked = day.dropna(subset=["score", "sector"]).copy()
        if ranked.empty:
            continue
        ranked["global_score_pct"] = ranked["score"].rank(method="average", pct=True)
        sector_scores = (
            ranked.groupby("sector", sort=True)["global_score_pct"]
            .apply(lambda values: float(values.nlargest(min(3, len(values))).mean()))
            .sort_values(ascending=False, kind="mergesort")
        )
        selected = set(sector_scores.head(4).index)
        shortlisted = ranked.loc[ranked["sector"].isin(selected)].copy()
        shortlisted["sector_rank"] = shortlisted.groupby("sector", sort=True)["score"].rank(
            method="first", ascending=False
        )
        shortlisted = shortlisted.loc[shortlisted["sector_rank"] <= 3].copy()
        shortlisted["window"] = str(window)
        shortlisted["date"] = pd.Timestamp(timestamp).date().isoformat()
        output.append(shortlisted[["window", "date", "instrument", "sector", "sector_rank"]])
    if not output:
        return pd.DataFrame(columns=["window", "date", "instrument", "sector", "sector_rank"])
    result = pd.concat(output, ignore_index=True)
    result["is_rebalance"] = False
    for window, group in result[["window", "date"]].drop_duplicates().groupby("window", sort=True):
        dates = sorted(group["date"].unique())
        rebalance_dates = set(dates[::10])
        result.loc[(result["window"] == window) & result["date"].isin(rebalance_dates), "is_rebalance"] = True
    return result.sort_values(["window", "date", "sector", "sector_rank"], kind="mergesort")


def events_to_frame(events: Sequence[CompanyInformationEvent]) -> pd.DataFrame:
    rows = [event.to_dict() for event in events]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "event_id",
                "symbol",
                "event_family",
                "event_stage",
                "fiscal_period_end",
                "announced_at",
                "first_eligible_session",
                "revision_sequence",
                "reconciliation_status",
                "availability_status",
                "announced_date",
                "half_year",
            ]
        )
    frame["announced_date"] = frame["announced_at"].str[:10]
    frame["half_year"] = frame["announced_date"].map(half_year)
    return frame


def _latest_recent_event(
    events: pd.DataFrame,
    *,
    row_date: str,
    session_index: Mapping[str, int],
    max_age: int,
) -> str:
    if events.empty or row_date not in session_index:
        return ""
    eligible = events.loc[
        (events["availability_status"] == "usable")
        & (events["first_eligible_session"] != "")
        & (events["first_eligible_session"] <= row_date)
    ].copy()
    if eligible.empty:
        return ""
    eligible["age"] = eligible["first_eligible_session"].map(
        lambda value: session_index[row_date] - session_index.get(str(value), -10_000)
    )
    eligible = eligible.loc[(eligible["age"] >= 0) & (eligible["age"] <= max_age)]
    if eligible.empty:
        return ""
    chosen = eligible.sort_values(
        ["first_eligible_session", "announced_at", "revision_sequence", "event_id"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).iloc[0]
    return str(chosen["event_id"])


def _max_share(values: Iterable[str]) -> float:
    series = pd.Series(list(values), dtype="object")
    if series.empty:
        return 0.0
    counts = series.value_counts(dropna=False)
    return float(counts.iloc[0] / counts.sum())


def audit_family(
    *,
    family: str,
    events: pd.DataFrame,
    top3: pd.DataFrame,
    sessions: Sequence[str],
) -> list[dict[str, Any]]:
    family_events = events.loc[events["event_family"] == family].copy()
    session_index = {value: index for index, value in enumerate(sessions)}
    daily_keys = set(zip(top3["date"], top3["instrument"], strict=False))
    event_driven = family_events.loc[
        (family_events["availability_status"] == "usable")
        & (family_events["first_eligible_session"] != "")
    ].copy()
    event_driven["top3_aligned"] = [
        (str(row.first_eligible_session), str(row.symbol)) in daily_keys
        for row in event_driven.itertuples()
    ]
    sector_by_symbol = (
        top3.sort_values(["date", "instrument"], kind="mergesort")
        .drop_duplicates("instrument", keep="last")
        .set_index("instrument")["sector"]
        .to_dict()
    )
    event_driven["sector"] = event_driven["symbol"].map(sector_by_symbol).fillna("UNKNOWN")

    rows: list[dict[str, Any]] = []
    half_years = sorted(set(top3["window"]) | set(family_events.get("half_year", [])))
    for window in half_years:
        announced = family_events.loc[family_events["half_year"] == window].copy()
        rebalance = top3.loc[(top3["window"] == window) & top3["is_rebalance"]].copy()
        matched_ids: list[str] = []
        if not rebalance.empty:
            grouped = {
                symbol: group for symbol, group in family_events.groupby("symbol", sort=True)
            }
            for row in rebalance.itertuples():
                event_id = _latest_recent_event(
                    grouped.get(str(row.instrument), family_events.iloc[0:0]),
                    row_date=str(row.date),
                    session_index=session_index,
                    max_age=20,
                )
                matched_ids.append(event_id)
            rebalance["matched_event_id"] = matched_ids
        aligned = event_driven.loc[
            (event_driven["first_eligible_session"].map(half_year) == window)
            & event_driven["top3_aligned"]
        ].copy()
        if "matched_event_id" not in rebalance.columns:
            rebalance["matched_event_id"] = ""
        matched = rebalance.loc[
            rebalance["matched_event_id"].fillna("") != ""
        ].copy()
        matched_event_rows = family_events.loc[
            family_events["event_id"].isin(set(matched.get("matched_event_id", [])))
        ].copy()
        matched_sectors = matched_event_rows["symbol"].map(sector_by_symbol).fillna("UNKNOWN")
        rows.append(
            {
                "event_family": family,
                "half_year": window,
                "unique_events": int(announced["event_id"].nunique()),
                "unique_symbols": int(announced["symbol"].nunique()),
                "revision_rate": (
                    float((announced["revision_sequence"] > 0).mean()) if len(announced) else 0.0
                ),
                "announcement_timestamp_completeness": (
                    float((announced["announced_at"] != "").mean()) if len(announced) else 0.0
                ),
                "first_session_mapping_ratio": (
                    float((announced["first_eligible_session"] != "").mean())
                    if len(announced)
                    else 0.0
                ),
                "primary_reconciliation_ratio": (
                    float((announced["reconciliation_status"] == "reconciled").mean())
                    if len(announced)
                    else 0.0
                ),
                "fixed_top3_rows": int(len(rebalance)),
                "fixed_recent_top3_rows": int(len(matched)),
                "fixed_recent_top3_coverage": (
                    float(len(matched) / len(rebalance)) if len(rebalance) else 0.0
                ),
                "fixed_distinct_top3_events": int(matched["matched_event_id"].nunique())
                if len(matched)
                else 0,
                "fixed_max_sector_share": _max_share(matched_sectors),
                "event_driven_top3_events": int(aligned["event_id"].nunique()),
                "event_driven_symbols": int(aligned["symbol"].nunique()),
                "event_driven_sectors": int(aligned["sector"].nunique()),
                "event_driven_max_sector_share": _max_share(aligned["sector"]),
                "event_driven_max_stage_share": _max_share(aligned["event_stage"]),
            }
        )
    return rows


def eligibility(family_rows: pd.DataFrame) -> tuple[bool, bool, list[str]]:
    calibration = family_rows.loc[family_rows["half_year"].isin(CALIBRATION_HALF_YEARS)].copy()
    reasons: list[str] = []
    if set(calibration["half_year"]) != set(CALIBRATION_HALF_YEARS):
        return False, False, ["missing_calibration_half_year"]
    fixed = bool(
        (calibration["fixed_recent_top3_coverage"] >= 0.15).all()
        and (calibration["fixed_distinct_top3_events"] >= 30).all()
        and (calibration["fixed_max_sector_share"] <= 0.45).all()
        and (calibration["primary_reconciliation_ratio"] >= 0.95).all()
        and (calibration["first_session_mapping_ratio"] >= 0.95).all()
    )
    event_driven = bool(
        (calibration["event_driven_top3_events"] >= 60).all()
        and (calibration["event_driven_symbols"] >= 20).all()
        and (calibration["event_driven_sectors"] >= 6).all()
        and (calibration["announcement_timestamp_completeness"] >= 0.95).all()
        and (calibration["first_session_mapping_ratio"] >= 0.95).all()
        and (calibration["primary_reconciliation_ratio"] >= 0.95).all()
        and (calibration["event_driven_max_stage_share"] <= 0.70).all()
    )
    if not fixed:
        reasons.append("fixed_rebalance_gate_failed")
    if not event_driven:
        reasons.append("event_driven_gate_failed")
    return fixed, event_driven, reasons


def overlap_matrix(events: pd.DataFrame) -> pd.DataFrame:
    keys: dict[str, set[tuple[str, str]]] = {}
    for family in FAMILIES:
        family_rows = events.loc[events["event_family"] == family]
        keys[family] = set(zip(family_rows["symbol"], family_rows["announced_date"], strict=False))
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


def build_report(decision: Mapping[str, Any], family_summary: pd.DataFrame) -> str:
    lines = [
        "# CN130 PIT event-family Phase 0 result",
        "",
        f"**Decision:** `{decision['decision']}`",
        "",
        "This phase builds and audits event data only. It does not inspect validation-period returns or create a model candidate.",
        "",
        "## Family gates",
        "",
        "| Family | Events | Reconciled | Fixed eligible | Event-driven eligible |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in family_summary.itertuples():
        lines.append(
            f"| {row.event_family} | {int(row.unique_events)} | {row.primary_reconciliation_ratio:.1%} | "
            f"{bool(row.fixed_rebalance_eligible)} | {bool(row.event_driven_eligible)} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Families that fail remain research metadata. Passing a data gate would only authorize a separately preregistered model experiment.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    pool_id, symbols = load_pool(args.pool_spec)
    sessions = load_sessions(args.provider_dir)
    ledger = load_r0_ledgers(args.ledger_dirs)
    top3 = build_r0_top3_rows(ledger)
    client = AshareEarningsEventClient()
    receipts: list[dict[str, Any]] = []

    cninfo_frames: dict[str, list[pd.DataFrame]] = defaultdict(list)
    for symbol in symbols:
        for family, method in (
            ("earnings_forecast", client.fetch_cninfo_forecasts),
            ("preliminary_earnings", client.fetch_cninfo_preliminary),
        ):
            identity = {
                "provider": "akshare_cninfo",
                "family": family,
                "symbol": symbol,
                "start": args.start,
                "cutoff": args.cutoff,
            }
            frame, receipt = fetch_cached_frame(
                path=_cache_path(args.source_cache_root, f"cninfo_{family}", symbol),
                identity=identity,
                fetcher=lambda m=method, s=symbol: m(
                    symbol=s, start_date=args.start, end_date=args.cutoff
                ),
                execution_at=args.execution_at,
                refresh=args.refresh_source_cache,
            )
            receipts.append({k: v for k, v in receipt.items() if k != "frame_json"})
            if not frame.empty:
                cninfo_frames[family].append(frame)

    disclosure_indexes = {
        family: cninfo_disclosure_index(
            pd.concat(cninfo_frames[family], ignore_index=True)
            if cninfo_frames[family]
            else pd.DataFrame(),
            family=family,
        )
        for family in FAMILIES
    }

    all_events: list[CompanyInformationEvent] = []
    for period in quarter_ends(args.period_start, args.cutoff):
        for family, method, adapter in (
            ("earnings_forecast", client.fetch_forecast, eastmoney_earnings_forecast_to_events),
            (
                "preliminary_earnings",
                client.fetch_preliminary,
                eastmoney_preliminary_earnings_to_events,
            ),
        ):
            identity = {
                "provider": "akshare_eastmoney",
                "family": family,
                "fiscal_period_end": period,
                "cutoff": args.cutoff,
            }
            frame, receipt = fetch_cached_frame(
                path=_cache_path(args.source_cache_root, family, period.replace("-", "")),
                identity=identity,
                fetcher=lambda m=method, p=period: m(period=p),
                execution_at=args.execution_at,
                refresh=args.refresh_source_cache,
            )
            receipts.append({k: v for k, v in receipt.items() if k != "frame_json"})
            if not frame.empty:
                all_events.extend(
                    adapter(
                        frame,
                        fiscal_period_end=period,
                        disclosures=disclosure_indexes[family],
                        sessions=sessions,
                        retrieved_at=str(receipt["retrieved_at"]),
                        allowed_symbols=symbols,
                    )
                )

    unique = {event.event_id: event for event in all_events if event.announced_at[:10] <= args.cutoff}
    ordered_events = sorted(unique.values(), key=lambda event: (event.announced_at, event.symbol, event.event_id))
    event_frame = events_to_frame(ordered_events)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    events_path = output / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as handle:
        for event in ordered_events:
            handle.write(
                json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)
                + "\n"
            )

    half_year_rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        half_year_rows.extend(
            audit_family(family=family, events=event_frame, top3=top3, sessions=sessions)
        )
    half_year_frame = pd.DataFrame(half_year_rows).sort_values(
        ["event_family", "half_year"], kind="mergesort"
    )
    write_csv(output / "event_family_half_year.csv", half_year_frame)

    summary_rows: list[dict[str, Any]] = []
    fixed_eligible: list[str] = []
    event_eligible: list[str] = []
    for family in FAMILIES:
        family_events = event_frame.loc[event_frame["event_family"] == family]
        family_half_year = half_year_frame.loc[half_year_frame["event_family"] == family]
        fixed, event_driven, reasons = eligibility(family_half_year)
        if fixed:
            fixed_eligible.append(family)
        if event_driven:
            event_eligible.append(family)
        summary_rows.append(
            {
                "event_family": family,
                "unique_events": int(family_events["event_id"].nunique()),
                "unique_symbols": int(family_events["symbol"].nunique()),
                "primary_reconciliation_ratio": (
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
    family_summary = pd.DataFrame(summary_rows)
    write_csv(output / "event_family_summary.csv", family_summary)
    write_csv(output / "overlap_matrix.csv", overlap_matrix(event_frame))

    provider_status = pd.DataFrame(receipts)
    if not provider_status.empty:
        provider_status["identity"] = provider_status["identity"].map(
            lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    write_csv(output / "provider_status.csv", provider_status)

    successful_sources = sum(str(row.get("status")) == "success" for row in receipts)
    if not ordered_events and successful_sources == 0:
        decision_name = "event_population_data_blocked"
    elif len(set(fixed_eligible) | set(event_eligible)) > 1:
        decision_name = "multiple_independent_event_families_eligible"
    elif event_eligible:
        decision_name = "event_driven_family_eligible"
    elif fixed_eligible:
        decision_name = "fixed_rebalance_event_family_eligible"
    else:
        decision_name = "event_population_built_no_family_eligible"
    decision = {
        "schema_version": "cn130_pit_event_families_phase0_v1",
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
    source_manifest = {
        "schema_version": "cn130_pit_event_source_cache_v1",
        "execution_at": args.execution_at,
        "receipt_count": len(source_cache_files),
        "receipts": [
            {"path": str(path.relative_to(args.source_cache_root)), "sha256": sha256(path)}
            for path in source_cache_files
        ],
    }
    write_json(output / "source_cache_manifest.json", source_manifest)

    manifest = {
        "schema_version": "cn130_pit_event_families_phase0_v1",
        "pool_id": pool_id,
        "pool_sha256": sha256(args.pool_spec),
        "provider_identity_sha256": json.loads(
            (args.provider_dir / "provider_manifest.json").read_text(encoding="utf-8")
        )["provider_identity_sha256"],
        "cutoff": args.cutoff,
        "period_start": args.period_start,
        "families": list(FAMILIES),
        "event_count": len(ordered_events),
        "events_sha256": sha256(events_path),
        "source_cache_manifest_sha256": sha256(output / "source_cache_manifest.json"),
        "ledger_files": [
            {"path": str(path), "sha256": sha256(path)}
            for root in args.ledger_dirs
            for path in sorted(root.glob("*__r0_cn_x1_0_raw_return_rank__current_cn_ohlcv.csv.gz"))
        ],
        "validation_returns_inspected": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output / "manifest.json", manifest)
    (output / "report.md").write_text(
        build_report(decision, family_summary), encoding="utf-8"
    )
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool-spec",
        type=Path,
        default=Path("configs/research_universes/cn_selected_equities_v3.yaml"),
    )
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--ledger-dir", dest="ledger_dirs", type=Path, action="append", required=True)
    parser.add_argument("--source-cache-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--period-start", default="2022-06-30")
    parser.add_argument("--cutoff", default="2026-08-03")
    parser.add_argument("--execution-at", required=True)
    parser.add_argument("--refresh-source-cache", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
