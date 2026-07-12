from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.data.symbol_identity import infer_data_market, normalize_data_symbol


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
    market_by_symbol: dict[str, str] = {}

    for csv_file in csv_files:
        source_symbol = csv_file.stem
        market = infer_data_market(source_symbol)
        symbol = normalize_data_symbol(market, source_symbol)
        if symbol in data_cache:
            raise ValueError(
                "CSV symbol identities collide after normalization: "
                f"{source_symbol} -> {symbol}"
            )

        df = pd.read_csv(csv_file)
        df.columns = [str(column).strip().lower() for column in df.columns]

        selected_date_col = date_col
        if selected_date_col not in df.columns:
            if "date" in df.columns:
                selected_date_col = "date"
            elif "datetime" in df.columns:
                selected_date_col = "datetime"
            elif "day" in df.columns:
                selected_date_col = "day"
            else:
                raise ValueError(f"Missing date column '{date_field_name}' in {csv_file}")

        df = df.rename(columns={selected_date_col: "date"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_localize(None)
        df = (
            df.dropna(subset=["date"])
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
        )

        if df.empty:
            continue

        # Normalize amount/money for guardrails compatibility.
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
            keep_cols = ["date"] + [field for field in desired_fields if field != "date"]
            df = df[keep_cols]
        else:
            # Default: keep everything except a symbol column if present.
            df = df.drop(columns=[symbol_field_name], errors="ignore")

        all_dates.update(df["date"].tolist())
        data_cache[symbol] = df
        market_by_symbol[symbol] = market

    if not data_cache:
        raise RuntimeError(f"No valid CSV content found under: {csv_dir}")

    sorted_dates = sorted(all_dates)
    date_map = {date: index for index, date in enumerate(sorted_dates)}
    n_days = len(sorted_dates)

    # Calendar.
    with open(calendars_dir / "day.txt", "w", encoding="utf-8") as calendar_file:
        for date in sorted_dates:
            calendar_file.write(f"{date.strftime('%Y-%m-%d')}\n")

    # Qlib uses `future=True` calendars for backtests and requires an extra boundary day.
    # Generate a minimal `day_future.txt` by appending one extra calendar day.
    if sorted_dates:
        future_last = sorted_dates[-1] + pd.Timedelta(days=1)
        with open(calendars_dir / "day_future.txt", "w", encoding="utf-8") as future_file:
            for date in sorted_dates:
                future_file.write(f"{date.strftime('%Y-%m-%d')}\n")
            future_file.write(f"{future_last.strftime('%Y-%m-%d')}\n")

    instrument_rows: dict[str, list[str]] = {"all": []}

    # Instruments + features.
    for symbol, df in data_cache.items():
        start_date = df["date"].iloc[0]
        end_date = df["date"].iloc[-1]
        row = f"{symbol}\t{start_date.strftime('%Y-%m-%d')}\t{end_date.strftime('%Y-%m-%d')}"
        instrument_rows["all"].append(row)
        instrument_rows.setdefault(market_by_symbol[symbol], []).append(row)

        # Qlib's file storage resolves instrument feature keys in lowercase even
        # when the public instrument identity remains uppercase in instruments/*.txt.
        feature_dir = output_dir / "features" / symbol.lower()
        feature_dir.mkdir(parents=True, exist_ok=True)
        df_by_date = df.set_index("date")

        fields = [column for column in df.columns if column != "date"]
        for field in fields:
            full_arr = np.full(n_days, np.nan, dtype=np.float32)
            series = df_by_date[field]
            for timestamp, value in series.items():
                if timestamp not in date_map:
                    continue
                index = date_map[timestamp]
                if pd.isna(value):
                    continue
                try:
                    full_arr[index] = float(value)
                except Exception:
                    continue

            bin_path = feature_dir / f"{field}.day.bin"
            with open(bin_path, "wb") as binary_file:
                # Qlib expects a 4-byte header start_index (int32). Using 0 since
                # the dump is aligned to the complete generated calendar.
                np.array([0], dtype=np.int32).tofile(binary_file)
                full_arr.tofile(binary_file)

    for market, rows in sorted(instrument_rows.items()):
        if rows:
            (instruments_dir / f"{market}.txt").write_text(
                "\n".join(rows) + "\n",
                encoding="utf-8",
            )

    market_counts = {
        market: len(rows)
        for market, rows in instrument_rows.items()
        if market != "all" and rows
    }
    print(
        f"Dump complete: {len(data_cache)} instruments -> {output_dir} "
        f"(markets={market_counts})"
    )


if __name__ == "__main__":
    import fire

    fire.Fire({"dump_all": dump_all})
