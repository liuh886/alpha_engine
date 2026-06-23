import pandas as pd
import pandera as pa

OHLC_COMPARISON_TOLERANCE = 1e-8

# ---------------------------------------------------------
# Roadmap Item 11/14/77: Data Melt-down Protection
# ---------------------------------------------------------

market_bars_schema = pa.DataFrameSchema(
    {
        "date": pa.Column(pa.DateTime),
        "open": pa.Column(pa.Float, pa.Check.ge(0.0), coerce=True),
        "high": pa.Column(pa.Float, pa.Check.ge(0.0), coerce=True),
        "low": pa.Column(pa.Float, pa.Check.ge(0.0), coerce=True),
        "close": pa.Column(pa.Float, pa.Check.ge(0.0), coerce=True),
        "volume": pa.Column(pa.Float, pa.Check.ge(0.0), nullable=True, coerce=True),
        "amount": pa.Column(pa.Float, pa.Check.ge(0.0), nullable=True, coerce=True),
    },
    checks=[
        pa.Check(
            lambda df: df["high"] + OHLC_COMPARISON_TOLERANCE >= df["low"],
            name="high_ge_low",
        ),
        pa.Check(
            lambda df: df["high"] + OHLC_COMPARISON_TOLERANCE >= df["open"],
            name="high_ge_open",
        ),
        pa.Check(
            lambda df: df["high"] + OHLC_COMPARISON_TOLERANCE >= df["close"],
            name="high_ge_close",
        ),
        pa.Check(
            lambda df: df["low"] <= df["open"] + OHLC_COMPARISON_TOLERANCE,
            name="low_le_open",
        ),
        pa.Check(
            lambda df: df["low"] <= df["close"] + OHLC_COMPARISON_TOLERANCE,
            name="low_le_close",
        ),
        # Broad Market Crash Filter: Reject a bar if it dropped more than 50% in one day (likely generic split issue not handled correctly)
        pa.Check(
            lambda df: (df["close"] / df["open"]) >= 0.5,
            name="no_unadjusted_splits",
            ignore_na=True,
        ),
    ],
    strict=False,  # allow extra columns like factor
)


def validate_market_data(
    df: pd.DataFrame, ticker: str
) -> tuple[bool, pd.DataFrame | None, list[str]]:
    """
    Validates a DataFrame against the Market Bars schema.
    Returns: (is_valid, validated_dataframe, list_of_error_messages)
    """
    if df is None or df.empty:
        return False, df, [f"[{ticker}] DataFrame is empty or None."]

    try:
        validated_df = market_bars_schema.validate(df, lazy=True)
        return True, validated_df, []
    except pa.errors.SchemaErrors as err:
        error_msgs = [
            f"[{ticker}] Schema Error: {failure.check} failed." for failure in err.schema_errors
        ]
        return False, df, error_msgs
    except Exception as e:
        return False, df, [f"[{ticker}] Extreme Validation Fatal Error: {str(e)}"]
