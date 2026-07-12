import argparse
import copy
import sys
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.data_snapshot import (
    read_latest_calendar_day,
    write_latest_manifest_file,
    write_latest_snapshot_file,
)
from src.assistant.data_snapshot_index import DataSnapshotIndex
from src.assistant.metadata_db import resolve_metadata_db_path
from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.adapters.efinance_adapter import EFinanceAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.quality import generate_data_quality_summary
from src.data.provider_evidence import (
    build_universe_evidence,
    provider_attempts_evidence,
    read_effective_provider_universe,
)
from src.data.router import MarketDataRouter
from src.data.snapshot import DataSnapshot
from src.data.update_accounting import (
    DataUpdateFailure,
)
from src.data.update_accounting import (
    UpdateAccountingReport as UpdateAccounting,
)
from src.data.validation.schema import validate_market_data


def _validate_quality_report(
    quality_report: dict,
    *,
    configured_universe: dict[str, list[str]],
    effective_universe: dict[str, list[str]],
    quality_policy: dict,
) -> None:
    """Validate quality against actual provider membership, not configured intent."""

    if not isinstance(quality_report, dict) or not quality_report.get("ok"):
        raise DataUpdateFailure(
            str((quality_report or {}).get("error") or "quality validation failed")
        )
    warnings = quality_report.get("warnings") or []
    if warnings and not quality_policy.get("allow_warnings", False):
        raise DataUpdateFailure(f"quality warnings are not allowed: {warnings}")
    markets = quality_report.get("markets")
    if not isinstance(markets, dict):
        raise DataUpdateFailure("quality report markets are missing")

    for market, configured_symbols in configured_universe.items():
        report = markets.get(market)
        if not isinstance(report, dict) or report.get("error"):
            raise DataUpdateFailure(f"quality report missing for market={market}")
        effective_symbols = effective_universe.get(market, [])
        if int(report.get("instruments", -1)) != len(effective_symbols):
            raise DataUpdateFailure(
                f"quality/provider mismatch for market={market}: "
                f"effective={len(effective_symbols)} reported={report.get('instruments')}"
            )
        extra = sorted(set(effective_symbols) - set(configured_symbols))
        if extra:
            raise DataUpdateFailure(
                f"provider contains unconfigured symbols for market={market}: {extra[:20]}"
            )
        for field_name in (
            "stale_instruments",
            "csv_missing",
            "csv_parse_errors",
            "csv_stale",
        ):
            if int(report.get(field_name, 0) or 0) != 0:
                raise DataUpdateFailure(
                    f"quality failure for market={market}: {field_name}={report.get(field_name)}"
                )


def _quality_identity_payload(report: dict) -> dict:
    payload = copy.deepcopy(report)
    for key in ("generated_at", "provider_uri", "csv_dir", "snapshot_id"):
        payload.pop(key, None)
    return payload


def publish_provider_snapshot(
    *,
    provider_dir: str | Path,
    snapshot_store: str | Path,
    marker_path: str | Path,
    db_path: str | Path,
    dataset_key: str,
    universe: dict[str, list[str]],
    selected_markets: set[str],
    source_policy: dict,
    adjustment_policy: dict,
    quality_policy: dict,
    quality_report: dict,
    accounting: UpdateAccounting,
    frequency: str = "day",
    strict: bool = False,
    max_missing_pct: float = 0.05,
    max_missing_count: int = 20,
    provider_attempts_path: str | Path | None = None,
) -> DataSnapshot:
    """Persist all mandatory evidence and move the authoritative pointer last."""
    warnings = accounting.validate_for_publish(
        selected_markets=selected_markets,
        strict=strict,
        max_missing_pct=max_missing_pct,
        max_missing_count=max_missing_count,
    )
    if warnings:
        quality_report.setdefault("warnings", []).extend(warnings)
    provider_dir = Path(provider_dir)
    effective_universe = read_effective_provider_universe(
        provider_dir,
        list(universe),
    )
    universe_evidence = build_universe_evidence(
        configured=universe,
        effective=effective_universe,
    )
    attempts_evidence = provider_attempts_evidence(provider_attempts_path)
    quality_report["universe"] = universe_evidence
    quality_report["provider_attempts"] = attempts_evidence
    _validate_quality_report(
        quality_report,
        configured_universe=universe,
        effective_universe=effective_universe,
        quality_policy=quality_policy,
    )
    has_missing = any(
        universe_evidence["missing"].get(market)
        for market in selected_markets
    )
    quality_verdict = (
        "pass_with_warnings"
        if has_missing or bool(quality_report.get("warnings"))
        else "pass"
    )
    update_summary = accounting.to_dict()
    update_summary["provider_attempts"] = attempts_evidence
    update_summary["universe_identity"] = {
        "configured_sha256": universe_evidence["configured_sha256"],
        "effective_sha256": universe_evidence["effective_sha256"],
    }
    calendar_path = provider_dir / "calendars" / f"{frequency}.txt"
    if not calendar_path.exists():
        raise DataUpdateFailure(f"calendar is missing: {calendar_path}")
    calendar_days = [
        line.strip()
        for line in calendar_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not calendar_days:
        raise DataUpdateFailure("calendar is empty")

    snapshot = DataSnapshot.create_snapshot(
        provider_dir,
        store=snapshot_store,
        source_adapter="market_data_router",
        source_policy=source_policy,
        schema_version="qlib-provider-v1",
        universe=universe_evidence,
        calendar={
            "frequency": frequency,
            "path": f"calendars/{frequency}.txt",
            "first_day": calendar_days[0],
            "latest_day": calendar_days[-1],
        },
        date_range={"start": calendar_days[0], "end": calendar_days[-1]},
        frequency=frequency,
        adjustment_policy=adjustment_policy,
        quality_policy=quality_policy,
        quality_report=_quality_identity_payload(quality_report),
        update_summary=update_summary,
        quality_verdict=quality_verdict,
    )

    persisted_quality = copy.deepcopy(quality_report)
    persisted_quality["snapshot_id"] = snapshot.snapshot_id
    persisted_quality["dataset_key"] = dataset_key
    persisted_quality["freq"] = frequency
    persisted_quality["latest_calendar_day"] = calendar_days[-1]
    quality_index = DataQualityIndex(db_path=db_path)
    quality_index.upsert(
        snapshot_id=snapshot.snapshot_id,
        dataset_key=dataset_key,
        freq=frequency,
        market="all",
        latest_calendar_day=calendar_days[-1],
        summary=persisted_quality,
    )
    for market, report in sorted((quality_report.get("markets") or {}).items()):
        quality_index.upsert(
            snapshot_id=snapshot.snapshot_id,
            dataset_key=dataset_key,
            freq=frequency,
            market=market,
            latest_calendar_day=calendar_days[-1],
            summary=report,
        )

    DataSnapshotIndex(db_path=db_path).upsert_manifest(snapshot.manifest, dataset_key=dataset_key)
    write_latest_manifest_file(
        output_path=marker_path, dataset_key=dataset_key, manifest=snapshot.manifest
    )
    DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=snapshot_store)
    return snapshot


def filter_regions_for_market(regions: dict, market: str) -> dict:
    market = str(market or "all").lower()
    if market == "all":
        return regions
    if market not in regions:
        raise ValueError(f"Unsupported market: {market}")
    return {k: (v if k == market else []) for k, v in regions.items()}


def build_selected_universe(regions: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return only markets that contain symbols after market filtering."""
    return {
        market: [str(symbol).upper() for symbol in symbols]
        for market, symbols in regions.items()
        if symbols
    }


def load_watchlist():
    from src.common.paths import CONFIG_DIR

    config_path = CONFIG_DIR / "watchlist.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_router_policy(path: str | Path | None = None) -> dict:
    from src.common.paths import CONFIG_DIR

    if path is None:
        path = CONFIG_DIR / "data_router_policy.yaml"
    path = Path(path)
    if not path.exists():
        return {
            "us": ["yfinance"],
            "cn": ["efinance", "akshare", "baostock", "yfinance"],
            "hk": ["yfinance"],
        }
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        raw = {}
    if isinstance(raw, dict) and isinstance(raw.get("policy"), dict):
        raw = raw.get("policy") or {}
    if not isinstance(raw, dict):
        return {
            "us": ["yfinance"],
            "cn": ["efinance", "akshare", "baostock", "yfinance"],
            "hk": ["yfinance"],
        }
    return raw


def _load_existing_csv(csv_path: Path) -> pd.DataFrame | None:
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return None
    if df.empty:
        return None
    if "date" not in df.columns:
        return None
    try:
        df["date"] = pd.to_datetime(df["date"])
    except Exception:
        return None
    return df


def _merge_existing(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        out = incoming.copy()
        out["date"] = pd.to_datetime(out["date"])
        return out.sort_values("date")

    inc = incoming.copy()
    inc["date"] = pd.to_datetime(inc["date"])

    # Keep only known columns to avoid schema drift.
    cols = ["date", "open", "high", "low", "close", "volume", "amount", "factor"]
    for c in cols:
        if c not in existing.columns:
            existing[c] = pd.NA
        if c not in inc.columns:
            inc[c] = pd.NA

    both = pd.concat([existing[cols], inc[cols]], ignore_index=True)
    both = both.dropna(subset=["date"])
    both = both.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return both.reset_index(drop=True)


def record_latest_snapshot_marker(
    *,
    provider_dir: str | Path,
    output_path: str | Path,
    dataset_key: str = "watchlist",
    freq: str = "day",
) -> dict | None:
    latest = read_latest_calendar_day(provider_dir, freq=freq)
    if not latest:
        return None
    return write_latest_snapshot_file(
        output_path=output_path,
        dataset_key=dataset_key,
        provider_uri=str(provider_dir),
        freq=freq,
        latest_calendar_day=latest,
    )


def upsert_snapshot_payload_to_metadata_db(*, payload: dict, db_path: str | Path) -> None:
    DataSnapshotIndex(db_path=db_path).upsert(payload)


def build_provider_stage(
    *,
    csv_stage: Path,
    provider_stage: Path,
    universe: dict[str, list[str]],
) -> None:
    """Convert CSV source data into a Qlib provider directory structure."""
    provider_stage.mkdir(parents=True, exist_ok=True)

    cal_dir = provider_stage / "calendars"
    cal_dir.mkdir(exist_ok=True)

    all_dates: set[str] = set()

    for market, symbols in universe.items():
        instruments: list[str] = []
        for symbol in symbols:
            csv_path = csv_stage / f"{symbol}.csv"
            if not csv_path.exists():
                continue
            df = pd.read_csv(csv_path)
            if df.empty or "date" not in df.columns:
                continue

            dates = sorted(df["date"].astype(str).tolist())
            all_dates.update(dates)

            feat_dir = provider_stage / "features" / symbol
            feat_dir.mkdir(parents=True, exist_ok=True)

            for field in ("open", "high", "low", "close", "volume", "amount", "factor"):
                if field in df.columns:
                    values = df[field].fillna(0).values.astype("float32")
                    (feat_dir / f"{field}.day.bin").write_bytes(values.tobytes())

            instruments.append(f"{symbol}\t{dates[0]}\t{dates[-1]}")

        inst_dir = provider_stage / "instruments"
        inst_dir.mkdir(exist_ok=True)
        (inst_dir / f"{market}.txt").write_text("\n".join(instruments) + "\n", encoding="utf-8")

    sorted_dates = sorted(all_dates)
    (cal_dir / "day.txt").write_text("\n".join(sorted_dates) + "\n", encoding="utf-8")


def _write_provider_diagnostics(diagnostics: list[dict], artifacts_dir: Path) -> Path:
    """Write immutable and latest per-symbol provider attempt evidence."""

    import json
    from datetime import datetime, timezone

    diag_dir = artifacts_dir / "data_update_diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc)
    output = {
        "schema_version": "2.0",
        "generated_at": generated_at.isoformat(),
        "total_symbols": len(diagnostics),
        "succeeded": sum(1 for item in diagnostics if item["ok"]),
        "failed": sum(1 for item in diagnostics if not item["ok"]),
        "symbols": diagnostics,
    }
    encoded = json.dumps(output, indent=2, ensure_ascii=False)
    timestamp = generated_at.strftime("%Y%m%d_%H%M%S_%f")
    immutable_path = diag_dir / f"provider_attempts_{timestamp}.json"
    immutable_path.write_text(encoded, encoding="utf-8")
    latest_path = diag_dir / "latest_provider_attempts.json"
    latest_path.write_text(encoded, encoding="utf-8")
    print(f"\n[diagnostic] Provider attempts written to {immutable_path}")
    return immutable_path


def run_data_update(args) -> DataSnapshot:
    """Execute a full data-update cycle with accounting and immutable publish.

    Raises :class:`DataUpdateFailure` on any symbol-level or quality failure.
    """
    from src.common.paths import ARTIFACTS_DIR, DATA_DIR, SCRIPTS_DIR

    print("=== Updating Data via router (providers + fallback) ===")

    # Provider diagnostics collector
    provider_diagnostics = []

    watchlist = load_watchlist()
    source_dir = DATA_DIR / "csv_source"
    source_dir.mkdir(parents=True, exist_ok=True)

    policy = load_router_policy()
    router = MarketDataRouter(
        adapters=[EFinanceAdapter(), AkShareAdapter(), BaoStockAdapter(), YFinanceAdapter()],
        policy=policy,
    )

    # ------------------------------------------------------------------
    # 1. Download Data with full accounting
    # ------------------------------------------------------------------
    regions = {
        "cn": watchlist.get("cn", []),
        "us": watchlist.get("us", []),
        "hk": watchlist.get("hk", []),
    }
    regions = filter_regions_for_market(regions, args.market)

    selected_markets = {k for k, v in regions.items() if v}
    universe = build_selected_universe(regions)

    accounting = UpdateAccounting(configured=universe)

    # Non-selected markets are excluded and their existing bytes are reused.
    for market, symbols in universe.items():
        if market in selected_markets:
            continue
        for symbol in symbols:
            accounting.add("excluded", market, symbol)
            accounting.add("reused", market, symbol)

    from src.data.validation.consistency_check import ConsistencyChecker

    checker = ConsistencyChecker(threshold=0.02)
    consistency_reports: list[dict] = []

    for reg, tickers in regions.items():
        if not tickers:
            continue
        print(f"Processing {reg.upper()} ({len(tickers)} tickers)...")

        spot_check_done = False

        for t in tickers:
            qlib_ticker = str(t).upper()
            accounting.add("attempted", reg, qlib_ticker)

            print(f"  Fetching {t} ...")
            try:
                csv_path = source_dir / f"{qlib_ticker}.csv"
                existing = None if args.full else _load_existing_csv(csv_path)

                start = args.start
                if existing is not None:
                    last = existing["date"].max()
                    lookback = max(int(args.lookback_days), 0)
                    start = (pd.Timestamp(last) - pd.Timedelta(days=lookback)).strftime("%Y-%m-%d")

                # Spot consistency check
                if not spot_check_done:
                    multi_res = router.fetch_multi_source_bars(
                        symbol=qlib_ticker, market=reg, start=start, limit=2
                    )
                    if len(multi_res) >= 2:
                        p_name, f_name = list(multi_res.keys())[:2]
                        report = checker.check(
                            multi_res[p_name].df.set_index("date"),
                            multi_res[f_name].df.set_index("date"),
                            qlib_ticker,
                        )
                        report["providers"] = [p_name, f_name]
                        consistency_reports.append(report)
                        if not report["ok"]:
                            print(f"    [!] Consistency Warning for {t}: {report['warnings']}")
                        else:
                            print(
                                f"    [OK] Consistency check passed for {t} ({p_name} vs {f_name})"
                            )
                        spot_check_done = True

                resp = router.fetch_daily_bars(
                    symbol=qlib_ticker, market=reg, start=start, end=None,
                    validate=True,  # trigger fallback if data fails OHLCV schema
                )

                # Record provider diagnostics
                selected_attempt = resp.attempts[-1] if resp.ok and resp.attempts else None
                symbol_diag = {
                    "symbol": qlib_ticker,
                    "market": reg,
                    "ok": resp.ok,
                    "final_state": "updated" if resp.ok else "failed",
                    "selected_provider": (
                        None if resp.result is None else resp.result.provider
                    ),
                    "selected_provider_symbol": (
                        None if resp.result is None else resp.result.provider_symbol
                    ),
                    "selected_rows": 0 if selected_attempt is None else selected_attempt.rows,
                    "selected_first_date": (
                        None if selected_attempt is None else selected_attempt.first_date
                    ),
                    "selected_last_date": (
                        None if selected_attempt is None else selected_attempt.last_date
                    ),
                    "attempts": [attempt.to_dict() for attempt in resp.attempts],
                }
                provider_diagnostics.append(symbol_diag)

                # Record provenance
                try:
                    from src.assistant.data_provenance_index import DataProvenanceIndex

                    prov = DataProvenanceIndex(db_path=resolve_metadata_db_path(Path(".")))

                    source_used = ""
                    fallback_used = False
                    error_code = ""

                    if resp.ok and resp.attempts:
                        source_used = resp.attempts[-1].provider
                        fallback_used = len(resp.attempts) > 1
                    elif resp.attempts:
                        source_used = resp.attempts[-1].provider
                        error_code = resp.attempts[-1].error or "failed"
                        fallback_used = len(resp.attempts) > 1

                    prov.record(
                        symbol=qlib_ticker,
                        market=reg,
                        source_used=source_used,
                        fallback_used=fallback_used,
                        code=error_code,
                    )
                except Exception:
                    pass

                if not resp.ok or not resp.result:
                    errs = "; ".join(
                        [f"{a.provider}: {a.error}" for a in resp.attempts if not a.ok and a.error]
                    )
                    print(f"    [!] Failed: {errs or 'unknown error'}")
                    accounting.add("failed", reg, qlib_ticker, reason=errs or "fetch failed")
                    continue

                df_processed = resp.result.df

                # Apply Data Melt-down Protection
                is_valid, validated_df, schema_errors = validate_market_data(
                    df_processed, qlib_ticker
                )

                if not is_valid:
                    print(
                        f"    [!] Data Melt-down Protection activated for {qlib_ticker}. "
                        "Dropping invalid payload."
                    )
                    for e in schema_errors:
                        print(f"        -> {e}")
                    # Update provider diagnostics with schema failure
                    symbol_diag["final_state"] = "schema_failed"
                    symbol_diag["ok"] = False
                    symbol_diag["validation_error"] = "schema validation failed"
                    symbol_diag["schema_errors"] = schema_errors
                    accounting.add("failed", reg, qlib_ticker, reason="schema validation failed")
                    continue

                merged = _merge_existing(existing, validated_df)
                merged.to_csv(csv_path, index=False)
                accounting.add("updated", reg, qlib_ticker)

            except Exception as e:
                print(f"    [!] Failed: {e}")
                accounting.add("failed", reg, qlib_ticker, reason=str(e))

    # Write provider diagnostics immediately after the download loop,
    # before dump_bin, so diagnostics are available even if dump_bin fails.
    provider_attempts_path = _write_provider_diagnostics(
        provider_diagnostics, ARTIFACTS_DIR
    )

    # ------------------------------------------------------------------
    # 2. Dump to Qlib Binary
    # ------------------------------------------------------------------
    qlib_dir = DATA_DIR / "watchlist"

    print("Converting to Qlib Binary Format...")

    import subprocess

    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "dump_bin.py"),
        "dump_all",
        "--data_path",
        str(source_dir),
        "--qlib_dir",
        str(qlib_dir),
        "--include_fields",
        "open,high,low,close,volume,amount,factor",
        "--date_field_name",
        "date",
        "--symbol_field_name",
        "symbol",
    ]

    print(f"Executing: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    # ------------------------------------------------------------------
    # 3. Generate quality report (BEFORE snapshot creation)
    # ------------------------------------------------------------------
    q = generate_data_quality_summary(
        dataset_key="watchlist",
        freq="day",
        provider_uri=qlib_dir,
        csv_dir=source_dir,
        markets=[k for k, v in regions.items() if v],
    )

    # Merge consistency warnings into quality report
    if consistency_reports:
        all_consistency_warnings = []
        for rep in consistency_reports:
            if not rep["ok"]:
                all_consistency_warnings.extend([f"[{rep['symbol']}] {w}" for w in rep["warnings"]])
        if all_consistency_warnings:
            q["warnings"] = list(set((q.get("warnings") or []) + all_consistency_warnings))

    # Proactive monitoring
    quality_warnings = q.get("warnings") or []
    if quality_warnings:
        print("\n[!] DATA QUALITY WARNINGS DETECTED:")
        for w in quality_warnings:
            print(f"  - {w}")
    else:
        print("\n[OK] Data quality looks good (0 warnings).")

    # ------------------------------------------------------------------
    # 4. Publish immutable snapshot (replaces lightweight marker)
    # ------------------------------------------------------------------
    try:
        snapshot = publish_provider_snapshot(
            provider_dir=qlib_dir,
            snapshot_store=ARTIFACTS_DIR / "snapshots",
            marker_path=ARTIFACTS_DIR / "snapshots" / "watchlist_latest.json",
            db_path=resolve_metadata_db_path(PROJECT_ROOT),
            dataset_key="watchlist",
            universe=universe,
            selected_markets=selected_markets,
            source_policy=load_router_policy(),
            adjustment_policy={"method": "none"},
            quality_policy={"max_stale_pct": 0.1, "max_csv_parse_errors": 0, "allow_warnings": True},
            quality_report=q,
            accounting=accounting,
            strict=args.strict,
            max_missing_pct=args.max_missing_pct,
            max_missing_count=args.max_missing_count,
            provider_attempts_path=provider_attempts_path,
        )
    except DataUpdateFailure:
        raise

    print(f"\n[published] snapshot_id={snapshot.snapshot_id}")

    # Write provider diagnostics
    _write_provider_diagnostics(provider_diagnostics, ARTIFACTS_DIR)

    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Update watchlist data via yfinance and dump to Qlib bin format."
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full rebuild: ignore existing CSV cache and download from --start for every ticker.",
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-01",
        help="Start date for full rebuild (default: 2020-01-01).",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        help="Incremental mode: re-download this many calendar days back from the last cached date (default: 30).",
    )
    parser.add_argument(
        "--market",
        type=str,
        default="all",
        choices=["all", "cn", "us", "hk"],
        help="Limit updates to a single market (default: all).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: fail if any selected symbol fails or is missing.",
    )
    parser.add_argument(
        "--max-missing-pct",
        type=float,
        default=0.30,
        help="Fraction of core symbols allowed missing without failing. Default: 0.30 (30%%)",
    )
    parser.add_argument(
        "--max-missing-count",
        type=int,
        default=60,
        help="Maximum absolute number of missing core symbols allowed. Default: 60",
    )
    args = parser.parse_args(argv)

    try:
        snapshot = run_data_update(args)
        print("\nUpdate Complete.")

        # Check if we succeeded but had warnings
        warnings = []
        if hasattr(snapshot, "manifest") and snapshot.manifest:
            warnings = snapshot.manifest.quality_report.get("warnings") or []

        if warnings:
            print("\n[!] Exiting with warnings (Exit code 2).")
            return 2

        return 0
    except DataUpdateFailure as exc:
        print(f"\n[!] Data update failed: {exc}")
        # Print provider diagnostics if accounting is available
        try:
            # Try to access the accounting from the exception context
            if hasattr(exc, 'accounting'):
                print_provider_diagnostic(exc.accounting)
        except Exception:
            pass
        return 1
    except Exception as exc:
        print(f"\n[!] Unexpected error: {exc}")
        return 1


def print_provider_diagnostic(accounting: UpdateAccounting) -> None:
    """Print per-symbol provider attempt diagnostics."""
    print("\n" + "=" * 60)
    print("PROVIDER DIAGNOSTIC REPORT")
    print("=" * 60)

    for market, symbols in accounting.configured.items():
        market_upper = market.upper()
        print(f"\n[{market_upper}]")

        for symbol in symbols:
            # Determine status
            if symbol in accounting.updated.get(market, set()):
                status = "UPDATED"
            elif symbol in accounting.reused.get(market, set()):
                status = "REUSED"
            elif symbol in accounting.failed.get(market, set()):
                status = "FAILED"
            elif symbol in accounting.excluded.get(market, set()):
                status = "EXCLUDED"
            elif symbol in accounting.stale.get(market, set()):
                status = "STALE"
            else:
                status = "NOT ATTEMPTED"

            # Get failure reason if any
            reason = accounting.reasons.get("failed", {}).get(f"{market}:{symbol}", "")
            if reason:
                print(f"  {symbol}: {status} (error={reason})")
            else:
                print(f"  {symbol}: {status}")

    # Summary
    summary = accounting.summary_dict()
    print(f"\n{'=' * 60}")
    for market, counts in summary.get("markets", {}).items():
        print(f"[{market.upper()}] {counts.get('updated', 0)} updated, "
              f"{counts.get('failed', 0)} failed, "
              f"{counts.get('reused', 0)} reused")
    print("=" * 60)


if __name__ == "__main__":
    raise SystemExit(main())
