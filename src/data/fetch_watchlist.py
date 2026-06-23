from pathlib import Path

import pandas as pd
import yfinance as yf

from src.common.config_utils import load_watchlist
from src.common.logging import get_logger

logger = get_logger(__name__)


def format_ticker(ticker, market):
    ticker = str(ticker).strip()
    if market == 'us':
        return ticker.upper()
    elif market == 'hk':
        clean_ticker = ticker.upper().replace('.HK', '')
        if len(clean_ticker) == 5 and clean_ticker.startswith('0'):
            clean_ticker = clean_ticker[1:]
        return f"{clean_ticker}.HK"
    elif market == 'cn':
        if ticker.startswith(('60', '68', '51', '50', '52', '56', '58', '90')):
            return f"{ticker}.SS"
        elif ticker.startswith(('00', '30', '15', '39', '16', '18')):
            return f"{ticker}.SZ"
        else:
            logger.warning("Unknown suffix for CN ticker, defaulting to .SS", ticker=ticker)
            return f"{ticker}.SS"
    return ticker

def fetch_data(watchlist, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_tickers = []

    if 'us' in watchlist and watchlist['us']:
        all_tickers.extend([(t, 'us') for t in watchlist['us']])
    if 'cn' in watchlist and watchlist['cn']:
        all_tickers.extend([(t, 'cn') for t in watchlist['cn']])
    if 'hk' in watchlist and watchlist['hk']:
        all_tickers.extend([(t, 'hk') for t in watchlist['hk']])

    logger.info("Fetching data", ticker_count=len(all_tickers))

    for ticker_raw, market in all_tickers:
        yf_ticker = format_ticker(ticker_raw, market)
        logger.info("Processing ticker", ticker_raw=ticker_raw, yf_ticker=yf_ticker)

        try:
            logger.info("Downloading ticker", yf_ticker=yf_ticker, start="2018-01-01")
            df = yf.download(yf_ticker, start="2018-01-01", interval="1d", progress=False, multi_level_index=False)

            if df.empty:
                logger.warning("No data found for ticker", yf_ticker=yf_ticker)
                continue

            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]

            if 'vwap' not in df.columns:
                df['vwap'] = (df['high'] + df['low'] + df['close']) / 3

            df['date'] = pd.to_datetime(df['date'])

            if 'adj close' in df.columns:
                df = df.rename(columns={'adj close': 'adj_close'})

            safe_name = str(ticker_raw).replace('.', '_')
            csv_path = output_dir / f"{safe_name}.csv"
            df.to_csv(csv_path, index=False)
            logger.info("Saved ticker data", path=str(csv_path), rows=len(df))

        except Exception as e:
            logger.error("Error fetching ticker", yf_ticker=yf_ticker, error=str(e))

if __name__ == "__main__":
    import fire
    fire.Fire(lambda config="configs/watchlist.yaml", out="data/watchlist_source":
              fetch_data(load_watchlist(config), out))
