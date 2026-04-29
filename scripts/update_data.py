import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.data_snapshot import read_latest_calendar_day, write_latest_snapshot_file
from src.assistant.data_snapshot_index import DataSnapshotIndex
from src.assistant.metadata_db import resolve_metadata_db_path
from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.adapters.efinance_adapter import EFinanceAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.quality import generate_data_quality_summary
from src.data.router import MarketDataRouter
from src.data.validation.schema import validate_market_data


def filter_regions_for_market(regions: dict, market: str) -> dict:
    market = str(market or "all").lower()
    if market == "all":
        return regions
    if market not in regions:
        raise ValueError(f"Unsupported market: {market}")
    return {k: (v if k == market else []) for k, v in regions.items()}


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


def main():
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
    args = parser.parse_args()

    print("=== Updating Data via router (providers + fallback) ===")

    from src.common.paths import DATA_DIR

    watchlist = load_watchlist()
    source_dir = DATA_DIR / "csv_source"
    source_dir.mkdir(parents=True, exist_ok=True)

    policy = load_router_policy()
    router = MarketDataRouter(
        adapters=[EFinanceAdapter(), AkShareAdapter(), BaoStockAdapter(), YFinanceAdapter()],
        policy=policy,
    )

    # 1. Download Data
    all_tickers = []

    regions = {
        "cn": watchlist.get("cn", []),
        "us": watchlist.get("us", []),
        "hk": watchlist.get("hk", []),
    }
    regions = filter_regions_for_market(regions, args.market)

    from src.data.validation.consistency_check import ConsistencyChecker

    checker = ConsistencyChecker(threshold=0.02)
    consistency_reports = []

    for reg, tickers in regions.items():
        if not tickers:
            continue
        print(f"Processing {reg.upper()} ({len(tickers)} tickers)...")

        spot_check_done = False

        for t in tickers:
            qlib_ticker = str(t).upper()  # Qlib symbol format

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
                    symbol=qlib_ticker, market=reg, start=start, end=None
                )

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
                        error_code=error_code,
                    )
                except Exception:
                    pass

                if not resp.ok or not resp.result:
                    errs = "; ".join(
                        [f"{a.provider}: {a.error}" for a in resp.attempts if not a.ok and a.error]
                    )
                    print(f"    [!] Failed: {errs or 'unknown error'}")
                    continue
                df_processed = resp.result.df

                # Apply Roadmap Item 11/14/77 Data Melt-down Protection
                is_valid, validated_df, schema_errors = validate_market_data(
                    df_processed, qlib_ticker
                )

                if not is_valid:
                    print(
                        f"    [!] Data Melt-down Protection activated for {qlib_ticker}. Dropping invalid payload."
                    )
                    for e in schema_errors:
                        print(f"        -> {e}")
                    continue

                merged = _merge_existing(existing, validated_df)
                merged.to_csv(csv_path, index=False)
                all_tickers.append(qlib_ticker)

            except Exception as e:
                print(f"    [!] Failed: {e}")

    print(f"Downloaded {len(all_tickers)} CSVs.")

    # 2. Dump to Qlib Bin
    from src.common.paths import ARTIFACTS_DIR, DATA_DIR, SCRIPTS_DIR

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

    # Record a lightweight data snapshot marker for reproducibility.
    try:
        payload = record_latest_snapshot_marker(
            provider_dir=qlib_dir,
            output_path=ARTIFACTS_DIR / "snapshots" / "watchlist_latest.json",
        )
        if payload:
            upsert_snapshot_payload_to_metadata_db(
                payload=payload,
                db_path=resolve_metadata_db_path(PROJECT_ROOT),
            )
    except Exception:
        pass

    # Best-effort: compute data quality summary and persist to the metadata DB.
    try:
        q = generate_data_quality_summary(
            dataset_key="watchlist",
            freq="day",
            provider_uri=qlib_dir,
            csv_dir=source_dir,
            markets=[k for k, v in regions.items() if v],
        )
        if q.get("ok") and q.get("snapshot_id") and q.get("latest_calendar_day"):
            # --- PROACTIVE MONITORING ---
            warnings = q.get("warnings") or []
            if warnings:
                print("\n[!] DATA QUALITY WARNINGS DETECTED:")
                for w in warnings:
                    print(f"  - {w}")
            else:
                print("\n[OK] Data quality looks good (0 warnings).")
            # ----------------------------

            idx = DataQualityIndex(db_path=resolve_metadata_db_path(Path(".")))
            snapshot_id = str(q.get("snapshot_id"))
            latest_day = str(q.get("latest_calendar_day"))

            # Include consistency warnings if any
            if consistency_reports:
                all_consistency_warnings = []
                for rep in consistency_reports:
                    if not rep["ok"]:
                        all_consistency_warnings.extend(
                            [f"[{rep['symbol']}] {w}" for w in rep["warnings"]]
                        )
                if all_consistency_warnings:
                    q["warnings"] = list(set((q.get("warnings") or []) + all_consistency_warnings))

            idx.upsert(
                snapshot_id=snapshot_id,
                dataset_key="watchlist",
                freq="day",
                market="all",
                latest_calendar_day=latest_day,
                summary=q,
            )
            markets_q = q.get("markets") or {}
            if isinstance(markets_q, dict):
                for m, summary in markets_q.items():
                    if not isinstance(summary, dict):
                        continue
                    idx.upsert(
                        snapshot_id=snapshot_id,
                        dataset_key="watchlist",
                        freq="day",
                        market=str(m),
                        latest_calendar_day=latest_day,
                        summary=summary,
                    )
    except Exception:
        pass

    print("\nUpdate Complete. New data is in data/watchlist")


if __name__ == "__main__":
    main()
