"""Static sector classification for watchlist instruments.

No external API calls — uses hardcoded mappings for US and CN universes,
cached to ``data/sector_map_{market}.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger()

CACHE_DIR = Path("data")


def get_sector_map(market: str) -> dict[str, str]:
    """Return ``{instrument: sector_name}`` mapping.

    Loads from cache file if available, otherwise builds from static data
    and persists the result.
    """
    market = market.lower().strip()
    cache_file = CACHE_DIR / f"sector_map_{market}.json"

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            log.debug("Sector map loaded from cache", market=market, n=len(data))
            return data
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt sector map cache; rebuilding", path=str(cache_file))

    if market == "us":
        mapping = _build_us_static_map()
    elif market == "cn":
        mapping = _build_cn_static_map()
    else:
        log.warning("Unknown market; returning empty sector map", market=market)
        return {}

    # Persist to cache
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8"
        )
        log.debug("Sector map cached", market=market, n=len(mapping))
    except OSError as exc:
        log.warning("Failed to cache sector map", error=str(exc))

    return mapping


def _build_us_static_map() -> dict[str, str]:
    """Hardcode sector assignments for major US watchlist stocks."""
    sectors: dict[str, list[str]] = {
        "Technology": [
            "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "INTC", "QCOM", "TXN",
            "AMAT", "LRCX", "KLAC", "MRVL", "ADI", "SNPS", "CDNS", "NXPI",
            "MCHP", "ON", "ASML", "TSM", "MU", "WDC", "STX", "HPQ", "DELL",
            "IBM", "CRM", "ADBE", "NOW", "INTU", "PANW", "CRWD", "FTNT",
            "ZS", "NET", "DDOG", "SNOW", "PLTR", "MDB", "WDAY", "ADP",
        ],
        "Healthcare": [
            "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT",
            "DHR", "BMY", "AMGN", "GILD", "ISRG", "MDT", "SYK", "BSX",
            "ZTS", "REGN", "VRTX", "BIIB", "ALNY", "HOLX", "IQV", "A",
            "DXCM", "IDXX", "MTD", "BIO", "RMD", "EW",
        ],
        "Financials": [
            "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "SPGI",
            "AXP", "BLK", "SCHW", "C", "USB", "PNC", "TFC", "COF",
            "AON", "MMC", "MET", "PRU", "AIG", "TRV", "ALL", "CB",
            "ICE", "CME", "MCO", "FIS", "FISV",
        ],
        "Consumer Discretionary": [
            "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX",
            "BKNG", "CMG", "ORLY", "AZO", "ROST", "DHI", "LEN", "GM",
            "F", "MAR", "HLT", "YUM", "LULU", "DPZ", "EBAY", "ETSY",
        ],
        "Communication Services": [
            "META", "GOOGL", "GOOG", "NFLX", "DIS", "CMCSA", "T", "VZ",
            "TMUS", "CHTR", "EA", "ATVI", "TTWO", "MTCH", "PINS", "SNAP",
            "ROKU", "PARA", "WBD", "OMC", "IPG",
        ],
        "Consumer Staples": [
            "PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "CL", "EL",
            "KMB", "GIS", "K", "HSY", "SYY", "ADM", "KHC", "MDLZ",
            "STZ", "KDP", "MNST", "CLX",
        ],
        "Energy": [
            "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO",
            "OXY", "HES", "DVN", "HAL", "BKR", "FANG", "PXD", "APA",
        ],
        "Industrials": [
            "CAT", "DE", "HON", "UNP", "RTX", "LMT", "BA", "GE", "MMM",
            "UPS", "FDX", "WM", "ETN", "EMR", "ITW", "ROK", "PH", "CMI",
            "GD", "NOC", "TDG", "CPRT", "GWW", "FAST",
        ],
        "Materials": [
            "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "DOW",
            "DD", "PPG", "ALB", "CE", "VMC", "MLM", "IFF", "CF",
        ],
        "Real Estate": [
            "PLD", "AMT", "CCI", "EQIX", "PSA", "SPG", "O", "WELL",
            "DLR", "AVB", "EQR", "ARE", "VICI", "EXR",
        ],
        "Utilities": [
            "NEE", "DUK", "SO", "D", "SRE", "AEP", "EXC", "XEL",
            "ED", "WEC", "ES", "AWK", "DTE", "FE", "PPL",
        ],
    }

    mapping: dict[str, str] = {}
    for sector, tickers in sectors.items():
        for ticker in tickers:
            mapping[ticker] = sector

    log.debug("Built US static sector map", n_stocks=len(mapping))
    return mapping


def _build_cn_static_map() -> dict[str, str]:
    """Hardcode sector assignments for CN watchlist stocks (CSI300-based)."""
    sectors: dict[str, list[str]] = {
        "金融": [
            "601398.SH", "601288.SH", "601939.SH", "601328.SH",
            "600036.SH", "601166.SH", "600016.SH", "600000.SH",
            "601318.SH", "601601.SH", "601628.SH", "601336.SH",
            "000001.SZ", "000166.SZ", "002142.SZ",
        ],
        "信息技术": [
            "002415.SZ", "600588.SH", "688981.SH", "688036.SH",
            "300750.SZ", "002475.SZ", "002371.SZ", "603501.SH",
            "300059.SZ", "300033.SZ", "600570.SH", "002236.SZ",
            "688012.SH", "688111.SH", "600183.SH", "002049.SZ",
        ],
        "医药卫生": [
            "600276.SH", "000661.SZ", "300760.SZ", "300015.SZ",
            "600196.SH", "000538.SZ", "002007.SZ", "300347.SZ",
            "603259.SH", "002001.SZ", "300122.SZ", "600867.SH",
        ],
        "主要消费": [
            "600519.SH", "000858.SZ", "000568.SZ", "002304.SZ",
            "603288.SH", "600887.SH", "002714.SZ", "600809.SH",
            "000596.SZ", "603369.SH",
        ],
        "可选消费": [
            "000333.SZ", "600690.SH", "000651.SZ", "601633.SH",
            "002032.SZ", "601888.SH", "002050.SZ", "600660.SH",
            "000725.SZ", "002241.SZ",
        ],
        "工业": [
            "601012.SH", "601668.SH", "601390.SH", "600031.SH",
            "000157.SZ", "601111.SH", "600585.SH", "002353.SZ",
            "300274.SZ", "601006.SH", "600900.SH", "000338.SZ",
        ],
        "能源": [
            "601857.SH", "600028.SH", "601088.SH", "600104.SH",
            "601808.SH", "002493.SZ", "600188.SH", "601225.SH",
        ],
        "原材料": [
            "600019.SH", "601899.SH", "600547.SH", "002460.SZ",
            "600309.SH", "000983.SZ", "002466.SZ", "600426.SH",
            "000876.SZ", "601005.SH",
        ],
        "电信业务": [
            "600941.SH", "601728.SH", "600050.SH",
        ],
        "公用事业": [
            "600900.SH", "601985.SH", "600886.SH", "000027.SZ",
            "600023.SH", "601669.SH",
        ],
        "房地产": [
            "001979.SZ", "600048.SH", "000002.SZ", "600606.SH",
            "601155.SH", "000069.SZ",
        ],
    }

    mapping: dict[str, str] = {}
    for sector, tickers in sectors.items():
        for ticker in tickers:
            mapping[ticker] = sector

    log.debug("Built CN static sector map", n_stocks=len(mapping))
    return mapping
