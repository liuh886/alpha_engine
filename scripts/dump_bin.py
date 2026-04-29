from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _parse_fields(include_fields) -> list[str]:
    if include_fields is None:
        return []
    if isinstance(include_fields, (list, tuple)):
        return [str(x).strip().lower() for x in include_fields if str(x).strip()]
    text = str(include_fields).strip()
    if not text:
        return []
    return [x.strip().lower() for x in text.split(",") if x.strip()]


def dump_all(
    data_path: str,
    qlib_dir: str,
    include_fields: str | list[str] | None = None,
    date_field_name: str = "date",
    symbol_field_name: str = "symbol",  # reserved for compatibility; files are per-symbol
):
    csv_dir = Path(data_path)
    output_dir = Path(qlib_dir)

    if not csv_dir.exists():
        raise FileNotFoundError(f"CSV directory not found: {csv_dir}")

    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in: {csv_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    calendars_dir = output_dir / "calendars"
    instruments_dir = output_dir / "instruments"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)

    desired_fields = _parse_fields(include_fields)
    date_col = str(date_field_name or "date").strip().lower()

    all_dates: set[pd.Timestamp] = set()
    data_cache: dict[str, pd.DataFrame] = {}

    for csv_file in csv_files:
        symbol = csv_file.stem
        df = pd.read_csv(csv_file)
        df.columns = [str(c).strip().lower() for c in df.columns]

        if date_col not in df.columns:
            if "date" in df.columns:
                date_col = "date"
            elif "datetime" in df.columns:
                date_col = "datetime"
            elif "day" in df.columns:
                date_col = "day"
            else:
                raise ValueError(f"Missing date column '{date_field_name}' in {csv_file}")

        df = df.rename(columns={date_col: "date"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = (
            df.dropna(subset=["date"])
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
        )

        if df.empty:
            continue

        # Normalize amount/money for guardrails compatibility
        if "amount" not in df.columns:
            if "money" in df.columns:
                df["amount"] = df["money"]
            elif "close" in df.columns and "volume" in df.columns:
                df["amount"] = df["close"] * df["volume"]

        if desired_fields:
            for field in desired_fields:
                if field == "date":
                    continue
                if field not in df.columns:
                    if field == "factor":
                        df[field] = 1.0
                    else:
                        df[field] = np.nan
            keep_cols = ["date"] + [f for f in desired_fields if f != "date"]
            df = df[keep_cols]
        else:
            # Default: keep everything except a symbol column if present
            df = df.drop(columns=[symbol_field_name], errors="ignore")

        all_dates.update(df["date"].tolist())
        data_cache[symbol] = df

    if not data_cache:
        raise RuntimeError(f"No valid CSV content found under: {csv_dir}")

    sorted_dates = sorted(all_dates)
    date_map = {d: i for i, d in enumerate(sorted_dates)}
    n_days = len(sorted_dates)

    # Calendar
    with open(calendars_dir / "day.txt", "w", encoding="utf-8") as f:
        for d in sorted_dates:
            f.write(f"{d.strftime('%Y-%m-%d')}\n")

    # Qlib uses `future=True` calendars for backtests and requires an extra boundary day.
    # We generate a minimal `day_future.txt` by appending one extra calendar day.
    if sorted_dates:
        future_last = sorted_dates[-1] + pd.Timedelta(days=1)
        with open(calendars_dir / "day_future.txt", "w", encoding="utf-8") as f:
            for d in sorted_dates:
                f.write(f"{d.strftime('%Y-%m-%d')}\n")
            f.write(f"{future_last.strftime('%Y-%m-%d')}\n")

    # Instruments + Features
    with open(instruments_dir / "all.txt", "w", encoding="utf-8") as f_inst:
        for symbol, df in data_cache.items():
            start_date = df["date"].iloc[0]
            end_date = df["date"].iloc[-1]
            f_inst.write(
                f"{symbol}\t{start_date.strftime('%Y-%m-%d')}\t{end_date.strftime('%Y-%m-%d')}\n"
            )

            feature_dir = output_dir / "features" / symbol
            feature_dir.mkdir(parents=True, exist_ok=True)

            df_by_date = df.set_index("date")

            fields = [c for c in df.columns if c != "date"]
            for field in fields:
                full_arr = np.full(n_days, np.nan, dtype=np.float32)
                series = df_by_date[field]
                for ts, value in series.items():
                    if ts not in date_map:
                        continue
                    idx = date_map[ts]
                    if pd.isna(value):
                        continue
                    try:
                        full_arr[idx] = float(value)
                    except Exception:
                        continue

                bin_path = feature_dir / f"{field}.day.bin"
                with open(bin_path, "wb") as f_bin:
                    # Qlib expects a 4-byte header start_index (int32). Using 0 since we dump full calendar.
                    np.array([0], dtype=np.int32).tofile(f_bin)
                    full_arr.tofile(f_bin)

    print(f"Dump complete: {len(data_cache)} instruments -> {output_dir}")


if __name__ == "__main__":
    import fire

    fire.Fire({"dump_all": dump_all})
