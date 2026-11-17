// Generated from configs/indicators/indicator_registry_v1.yaml.
// Do not edit by hand; run `python -m src.governance.indicator_registry --write`.
import type { FormulaCatalogEntry, IndicatorEntry } from './indicators';

export const INDICATOR_REGISTRY_SOURCE = "configs/indicators/indicator_registry_v1.yaml";
export const INDICATOR_REGISTRY_SOURCE_SHA256 = "4b9902c1a65070f08ddd833b3ac42ca32b3c34f13ee84b51dcbb2b09ce078323";
export const INDICATOR_REGISTRY_SCHEMA_VERSION = "1.0";

export const INDICATOR_FORMULA_CATALOG: Readonly<Record<string, FormulaCatalogEntry>> = {
  "sma": {
    "version": "1",
    "params": [
      "period"
    ],
    "outputs": [
      "value"
    ]
  },
  "ema": {
    "version": "1",
    "params": [
      "period"
    ],
    "outputs": [
      "value"
    ]
  },
  "rsi": {
    "version": "1",
    "params": [
      "period"
    ],
    "outputs": [
      "value"
    ]
  },
  "macd": {
    "version": "1",
    "params": [
      "fast",
      "slow",
      "signal"
    ],
    "outputs": [
      "macd",
      "signal",
      "histogram"
    ]
  },
  "bollinger": {
    "version": "1",
    "params": [
      "period",
      "std_dev"
    ],
    "outputs": [
      "middle",
      "upper",
      "lower"
    ]
  },
  "volume_sma": {
    "version": "1",
    "params": [
      "period"
    ],
    "outputs": [
      "value"
    ]
  }
};

export const INDICATOR_REGISTRY: readonly IndicatorEntry[] =   [
    {
      "indicator_id": "instrument_sma_20",
      "scope": "instrument",
      "kind": "derived",
      "formula": "sma",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 20
      },
      "version": "1",
      "status": "governed",
      "description": "20-session simple moving average of the instrument close.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_sma_50",
      "scope": "instrument",
      "kind": "derived",
      "formula": "sma",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 50
      },
      "version": "1",
      "status": "governed",
      "description": "50-session simple moving average of the instrument close.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_sma_200",
      "scope": "instrument",
      "kind": "derived",
      "formula": "sma",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 200
      },
      "version": "1",
      "status": "governed",
      "description": "200-session simple moving average of the instrument close.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_ema_12",
      "scope": "instrument",
      "kind": "derived",
      "formula": "ema",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 12
      },
      "version": "1",
      "status": "governed",
      "description": "12-session exponential moving average, SMA-seeded.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_ema_26",
      "scope": "instrument",
      "kind": "derived",
      "formula": "ema",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 26
      },
      "version": "1",
      "status": "governed",
      "description": "26-session exponential moving average, SMA-seeded.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_rsi_14",
      "scope": "instrument",
      "kind": "derived",
      "formula": "rsi",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 14
      },
      "version": "1",
      "status": "governed",
      "description": "14-session Wilder relative strength index of the instrument close.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_macd_12_26_9",
      "scope": "instrument",
      "kind": "derived",
      "formula": "macd",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "fast": 12,
        "slow": 26,
        "signal": 9
      },
      "version": "1",
      "status": "governed",
      "description": "MACD line, signal line and histogram (12/26/9) of the instrument close.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_bollinger_20_2",
      "scope": "instrument",
      "kind": "derived",
      "formula": "bollinger",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "close"
      },
      "params": {
        "period": 20,
        "std_dev": 2
      },
      "version": "1",
      "status": "governed",
      "description": "20-session Bollinger bands at two population standard deviations of the instrument close.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: maintained chart indicators are governed like data updates.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "instrument_volume_sma_20",
      "scope": "instrument",
      "kind": "derived",
      "formula": "volume_sma",
      "formula_version": "1",
      "inputs": {
        "source": "instrument_bars",
        "field": "volume"
      },
      "params": {
        "period": 20
      },
      "version": "1",
      "status": "governed",
      "description": "20-session simple moving average of the instrument volume.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: volume moving average on the volume pane.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "market_us_vix",
      "scope": "market",
      "kind": "series",
      "market": "us",
      "formula": null,
      "formula_version": null,
      "inputs": {
        "source": "market_series",
        "series_id": "us:VIX"
      },
      "params": {},
      "version": "1",
      "status": "governed",
      "description": "Raw governed US VIX close series reference; no derived value is claimed.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: VIX overlay on US charts only, sourced from the governed VIX data plane.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "market_us_vix_sma_20",
      "scope": "market",
      "kind": "derived",
      "market": "us",
      "formula": "sma",
      "formula_version": "1",
      "inputs": {
        "source": "market_series",
        "series_id": "us:VIX"
      },
      "params": {
        "period": 20
      },
      "version": "1",
      "status": "governed",
      "description": "20-session simple moving average of the governed US VIX close series.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: VIX SMA overlay on US charts only.",
        "source": "docs/architecture/indicator_governance.md; chart/indicator slice brief 2026-11-17"
      }
    },
    {
      "indicator_id": "market_cn_rdi_reserved",
      "scope": "market",
      "kind": "reserved",
      "market": "cn",
      "formula": null,
      "formula_version": null,
      "inputs": {
        "source": "market_series",
        "series_id": "cn:RDI"
      },
      "params": {},
      "version": "0",
      "status": "research_only",
      "description": "Reserved CN A-share RDI risk-event family; unqualified and never computes values.",
      "provenance": {
        "authorized_by": "Owner, Alpha Engine",
        "authorized_on": "2026-11-17",
        "rationale": "Owner decision 2026-11-17: future mined indicators register explicitly and produce no values until qualified.",
        "source": "docs/architecture/indicator_governance.md; docs/architecture/investment_research_data_product_inventory_2026-10-26.md"
      }
    }
  ];
