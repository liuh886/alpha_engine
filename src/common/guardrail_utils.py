import pandas as pd


def apply_amount_fallback(df: pd.DataFrame) -> pd.DataFrame:
    if "amount" not in df.columns:
        return df
    if "volume" not in df.columns or "close" not in df.columns:
        return df
    missing = df["amount"].isna()
    if missing.any():
        df.loc[missing, "amount"] = df.loc[missing, "volume"] * df.loc[missing, "close"]
    return df
