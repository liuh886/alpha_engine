import { describe, expect, it } from 'vitest';
import {
  FORMULAS,
  INDICATOR_FORMULA_CATALOG,
  INDICATOR_REGISTRY,
  INDICATOR_REGISTRY_SCHEMA_VERSION,
  INDICATOR_REGISTRY_SOURCE,
  INDICATOR_REGISTRY_SOURCE_SHA256,
  bollinger,
  computeIndicator,
  ema,
  macd,
  rsi,
  sma,
  validateFormulaParams,
  validateIndicatorRegistry,
  volumeSma,
  type IndicatorBar,
  type IndicatorEntry,
  type IndicatorPoint,
} from './indicators';

const DATE_MS = 86_400_000;
function dateAt(index: number): string {
  return new Date(Date.UTC(2026, 0, 1) + index * DATE_MS).toISOString().slice(0, 10);
}
function points(values: number[]): IndicatorPoint[] {
  return values.map((value, index) => ({ time: dateAt(index), value }));
}
function bars(closes: number[], volumes: number[] = closes.map(() => 100)): IndicatorBar[] {
  return closes.map((close, index) => ({ time: dateAt(index), close, volume: volumes[index] }));
}
function entry(id: string): IndicatorEntry {
  const found = INDICATOR_REGISTRY.find(candidate => candidate.indicator_id === id);
  if (!found) throw new Error(`Missing registry entry ${id}`);
  return found;
}
function valuesOf(series: IndicatorPoint[]): number[] {
  return series.map(point => point.value);
}
function clone(target: IndicatorEntry): IndicatorEntry {
  return JSON.parse(JSON.stringify(target)) as IndicatorEntry;
}
function expectSeries(series: IndicatorPoint[], expected: number[]): void {
  expect(valuesOf(series)).toHaveLength(expected.length);
  valuesOf(series).forEach((value, index) => expect(value).toBeCloseTo(expected[index], 10));
}

describe('governed indicator registry snapshot', () => {
  it('is valid against the formula contract', () => {
    expect(validateIndicatorRegistry()).toEqual([]);
  });

  it('binds the generated snapshot to the YAML authority', () => {
    expect(INDICATOR_REGISTRY_SOURCE).toBe('configs/indicators/indicator_registry_v1.yaml');
    expect(INDICATOR_REGISTRY_SOURCE_SHA256).toMatch(/^[a-f0-9]{64}$/);
    expect(INDICATOR_REGISTRY_SCHEMA_VERSION).toBe('1.0');
  });

  it('declares exactly the first governed indicator set', () => {
    expect(INDICATOR_REGISTRY.map(row => row.indicator_id).sort()).toEqual([
      'instrument_bollinger_20_2',
      'instrument_ema_12',
      'instrument_ema_26',
      'instrument_macd_12_26_9',
      'instrument_rsi_14',
      'instrument_sma_20',
      'instrument_sma_200',
      'instrument_sma_50',
      'instrument_volume_sma_20',
      'market_cn_rdi_reserved',
      'market_us_vix',
      'market_us_vix_sma_20',
    ]);
  });

  it('matches the registry formula catalog to the implementations', () => {
    expect(Object.keys(INDICATOR_FORMULA_CATALOG).sort()).toEqual(Object.keys(FORMULAS).sort());
    for (const implementation of Object.values(FORMULAS)) {
      const catalog = INDICATOR_FORMULA_CATALOG[implementation.id];
      expect(catalog.version).toBe(implementation.version);
      expect(catalog.params).toEqual(implementation.params);
      expect(catalog.outputs).toEqual(implementation.outputs);
    }
  });

  it('rejects an unknown formula, scope, status, param or provenance', () => {
    const sma20 = clone(entry('instrument_sma_20'));
    const unknownFormula = { ...sma20, formula: 'vwap' } as unknown as IndicatorEntry;
    const unknownScope = { ...clone(sma20), scope: 'global' } as unknown as IndicatorEntry;
    const unknownStatus = { ...clone(sma20), status: 'certified' } as unknown as IndicatorEntry;
    const badParams = { ...clone(sma20), params: {} } as IndicatorEntry;
    const badProvenance = {
      ...clone(sma20),
      provenance: { ...sma20.provenance, rationale: '' },
    } as IndicatorEntry;

    expect(validateIndicatorRegistry([unknownFormula])).toEqual(
      expect.arrayContaining([expect.stringContaining('unknown formula')]),
    );
    expect(validateIndicatorRegistry([unknownScope])).toEqual(
      expect.arrayContaining([expect.stringContaining('unknown scope')]),
    );
    expect(validateIndicatorRegistry([unknownStatus])).toEqual(
      expect.arrayContaining([expect.stringContaining('unknown status')]),
    );
    expect(validateIndicatorRegistry([badParams])).toEqual(
      expect.arrayContaining([expect.stringContaining('requires exactly period')]),
    );
    expect(validateIndicatorRegistry([badProvenance])).toEqual(
      expect.arrayContaining([expect.stringContaining('incomplete provenance')]),
    );
  });

  it('rejects scope mixing and formula/input mismatches', () => {
    const instrument = clone(entry('instrument_sma_20'));
    const instrumentWithMarket = { ...instrument, market: 'us' } as IndicatorEntry;
    const volumeAsClose = clone(entry('instrument_volume_sma_20'));
    volumeAsClose.inputs = { ...volumeAsClose.inputs, field: 'close' };
    const marketVolume = clone(entry('market_us_vix_sma_20'));
    marketVolume.formula = 'volume_sma';

    expect(validateIndicatorRegistry([instrumentWithMarket])).toEqual(
      expect.arrayContaining([expect.stringContaining('must not declare a market')]),
    );
    expect(validateIndicatorRegistry([volumeAsClose])).toEqual(
      expect.arrayContaining([expect.stringContaining('requires field volume')]),
    );
    expect(validateIndicatorRegistry([marketVolume])).toEqual(
      expect.arrayContaining([expect.stringContaining('volume_sma is instrument-only')]),
    );
  });

  it('keeps every market indicator inside its declared market', () => {
    for (const marketEntry of INDICATOR_REGISTRY.filter(row => row.scope === 'market')) {
      expect(marketEntry.market === 'us' || marketEntry.market === 'cn').toBe(true);
      expect(marketEntry.inputs.series_id?.startsWith(`${marketEntry.market}:`)).toBe(true);
    }
  });
});

describe('indicator formulas', () => {
  it('computes a simple moving average over exact observations', () => {
    expectSeries(sma(points([1, 2, 3, 4, 5, 6]), 3) ?? [], [2, 3, 4, 5]);
    expect(sma(points([1, 2]), 3)).toBeNull();
  });

  it('computes an SMA-seeded exponential moving average', () => {
    expectSeries(ema(points([2, 4, 6, 8, 10]), 3) ?? [], [4, 6, 8]);
  });

  it('computes Wilder RSI against a reference sequence', () => {
    const sequence = [44, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.1, 45.42, 45.84];
    expectSeries(rsi(points(sequence), 3) ?? [], [
      61.538461538461455,
      27.39726027397255,
      65.58441558441558,
      77.76612480335606,
      82.72032603158436,
      87.62314821571923,
      92.05899566896878,
    ]);
    expect(rsi(points(sequence.slice(0, 3)), 3)).toBeNull();
  });

  it('computes MACD line, signal and histogram with aligned first dates', () => {
    const sequence = [10, 12, 11, 13, 15, 14, 16, 18, 17, 19];
    const output = macd(points(sequence), 3, 5, 2);
    expect(output).not.toBeNull();
    expectSeries(output?.macd ?? [], [1.3, 0.95, 1.008333333333, 1.193055555556, 0.88912037037, 0.972955246914]);
    expectSeries(output?.signal ?? [], [1.125, 1.047222222222, 1.144444444444, 0.974228395062, 0.97337962963]);
    expectSeries(output?.histogram ?? [], [-0.175, -0.038888888889, 0.048611111111, -0.085108024691, -0.000424382716]);
    expect(output?.macd[0].time).toBe(dateAt(4));
    expect(output?.signal[0].time).toBe(dateAt(5));
    expect(output?.histogram[0].time).toBe(dateAt(5));
  });

  it('computes Bollinger bands with population standard deviation', () => {
    const output = bollinger(points([1, 2, 3, 4, 5]), 3, 2);
    expectSeries(output?.middle ?? [], [2, 3, 4]);
    expectSeries(output?.upper ?? [], [3.632993161855452, 4.6329931618554525, 5.6329931618554525]);
    expectSeries(output?.lower ?? [], [0.36700683814454793, 1.367006838144548, 2.367006838144548]);
  });

  it('computes a volume SMA from observed volume points', () => {
    expectSeries(volumeSma(points([100, 120, 90, 150]), 2) ?? [], [110, 105, 120]);
  });

  it('is deterministic for repeated identical inputs', () => {
    const sequence = points([10, 12, 11, 13, 15, 14, 16, 18, 17, 19]);
    expect(macd(sequence, 3, 5, 2)).toEqual(macd(sequence, 3, 5, 2));
    expect(bollinger(sequence, 3, 2)).toEqual(bollinger(sequence, 3, 2));
  });
});

describe('computeIndicator availability', () => {
  it('computes a governed instrument indicator from its own bars', () => {
    const closes = Array.from({ length: 25 }, (_, index) => index + 1);
    const result = computeIndicator(entry('instrument_sma_20'), {
      scope: 'instrument',
      market: 'us',
      bars: bars(closes),
    });
    expect(result).toMatchObject({
      available: true,
      indicator_id: 'instrument_sma_20',
      scope: 'instrument',
      market: 'us',
    });
    if (!result.available) throw new Error('expected available');
    expectSeries(result.series.value, [10.5, 11.5, 12.5, 13.5, 14.5, 15.5]);
  });

  it('reads volume only for the governed volume indicator', () => {
    const closes = Array.from({ length: 22 }, (_, index) => 100 + index);
    const volumes = Array.from({ length: 22 }, (_, index) => 1000 + index * 10);
    const result = computeIndicator(entry('instrument_volume_sma_20'), {
      scope: 'instrument',
      market: 'cn',
      bars: bars(closes, volumes),
    });
    if (!result.available) throw new Error('expected available');
    expectSeries(result.series.value, [1095, 1105, 1115]);
  });

  it('returns explicit insufficient-data states and never a partial value', () => {
    const result = computeIndicator(entry('instrument_sma_20'), {
      scope: 'instrument',
      market: 'us',
      bars: bars(Array.from({ length: 19 }, (_, index) => index + 1)),
    });
    expect(result).toMatchObject({
      available: false,
      reason: 'insufficient_observations',
      observations: 19,
      required: 20,
    });
    expect('series' in result).toBe(false);
  });

  it('rejects invalid or unordered observations', () => {
    const duplicateDate = bars([1, 2, 3]);
    duplicateDate[1].time = duplicateDate[0].time;
    const invalidClose = bars([1, 0, 3]);
    const negativeVolume = bars([1, 2, 3], [10, -1, 12]);
    const nanMarket = points([1, Number.NaN, 3]);

    expect(computeIndicator(entry('instrument_sma_20'), {
      scope: 'instrument', market: 'us', bars: duplicateDate,
    })).toMatchObject({ available: false, reason: 'invalid_observations' });
    expect(computeIndicator(entry('instrument_sma_20'), {
      scope: 'instrument', market: 'us', bars: invalidClose,
    })).toMatchObject({ available: false, reason: 'invalid_observations' });
    expect(computeIndicator(entry('instrument_volume_sma_20'), {
      scope: 'instrument', market: 'us', bars: negativeVolume,
    })).toMatchObject({ available: false, reason: 'invalid_observations' });
    expect(computeIndicator(entry('market_us_vix'), {
      scope: 'market', market: 'us', series_id: 'us:VIX', series: nanMarket,
    })).toMatchObject({ available: false, reason: 'invalid_observations' });
  });

  it('rejects a formula version that does not match the implementation', () => {
    const mismatched = clone(entry('instrument_sma_20'));
    mismatched.formula_version = '2';
    const result = computeIndicator(mismatched, {
      scope: 'instrument',
      market: 'us',
      bars: bars(Array.from({ length: 20 }, (_, index) => index + 1)),
    });
    expect(result).toMatchObject({ available: false, reason: 'unsupported_formula_version' });
  });

  it('rejects invalid params before computing', () => {
    const invalid = clone(entry('instrument_sma_20'));
    invalid.params = { period: 0 };
    const result = computeIndicator(invalid, {
      scope: 'instrument',
      market: 'us',
      bars: bars(Array.from({ length: 20 }, (_, index) => index + 1)),
    });
    expect(result).toMatchObject({ available: false, reason: 'invalid_params' });
  });

  it('rejects an unknown formula at runtime', () => {
    const unknown = { ...clone(entry('instrument_sma_20')), formula: 'vwap' } as unknown as IndicatorEntry;
    const result = computeIndicator(unknown, {
      scope: 'instrument',
      market: 'us',
      bars: bars(Array.from({ length: 20 }, (_, index) => index + 1)),
    });
    expect(result).toMatchObject({ available: false, reason: 'unsupported_formula' });
  });

  it('rejects a scope mismatch', () => {
    const result = computeIndicator(entry('instrument_sma_20'), {
      scope: 'market', market: 'us', series_id: 'us:VIX', series: points([1, 2, 3]),
    });
    expect(result).toMatchObject({ available: false, reason: 'scope_mismatch' });
  });
});

describe('market-scope governed series', () => {
  it('returns the raw governed VIX series without deriving extra values', () => {
    const series = points([14, 15.5, 13.2]);
    const result = computeIndicator(entry('market_us_vix'), {
      scope: 'market', market: 'us', series_id: 'us:VIX', series,
    });
    expect(result).toMatchObject({ available: true, indicator_id: 'market_us_vix', market: 'us' });
    if (!result.available) throw new Error('expected available');
    expect(result.series.value).toEqual(series);
  });

  it('returns market_series_unavailable until us:VIX is published', () => {
    const result = computeIndicator(entry('market_us_vix'), {
      scope: 'market', market: 'us', series_id: 'us:VIX',
    });
    expect(result).toMatchObject({ available: false, reason: 'market_series_unavailable' });
  });

  it('computes VIX SMA 20 only from a governed us:VIX series', () => {
    const series = points(Array.from({ length: 20 }, (_, index) => index + 1));
    const result = computeIndicator(entry('market_us_vix_sma_20'), {
      scope: 'market', market: 'us', series_id: 'us:VIX', series,
    });
    expect(result).toMatchObject({ available: true, indicator_id: 'market_us_vix_sma_20' });
    if (!result.available) throw new Error('expected available');
    expect(result.series.value).toEqual([{ time: dateAt(19), value: 10.5 }]);

    const short = computeIndicator(entry('market_us_vix_sma_20'), {
      scope: 'market', market: 'us', series_id: 'us:VIX', series: series.slice(0, 19),
    });
    expect(short).toMatchObject({
      available: false, reason: 'insufficient_observations', observations: 19, required: 20,
    });
  });

  it('never computes a US market indicator for another market', () => {
    const series = points(Array.from({ length: 20 }, (_, index) => index + 1));
    const result = computeIndicator(entry('market_us_vix_sma_20'), {
      scope: 'market', market: 'cn', series_id: 'us:VIX', series,
    });
    expect(result).toMatchObject({ available: false, reason: 'cross_market_mismatch' });
  });

  it('rejects a series identity other than the declared governed series', () => {
    const result = computeIndicator(entry('market_us_vix_sma_20'), {
      scope: 'market', market: 'us', series_id: 'us:VXN', series: points([1, 2, 3]),
    });
    expect(result).toMatchObject({ available: false, reason: 'series_identity_mismatch' });
  });

  it('refuses every market indicator for the opposite market', () => {
    for (const marketEntry of INDICATOR_REGISTRY.filter(
      row => row.scope === 'market' && row.status === 'governed',
    )) {
      const declared = marketEntry.market === 'us' ? 'us' : 'cn';
      const opposite = declared === 'us' ? 'cn' : 'us';
      const result = computeIndicator(marketEntry, {
        scope: 'market',
        market: opposite,
        series_id: marketEntry.inputs.series_id ?? `${declared}:UNKNOWN`,
        series: points([1, 2, 3]),
      });
      expect(result).toMatchObject({ available: false, reason: 'cross_market_mismatch' });
    }
  });
});

describe('reserved mined indicator families', () => {
  it('registers RDI as a non-executable CN market placeholder', () => {
    const rdi = entry('market_cn_rdi_reserved');
    expect(rdi).toMatchObject({
      scope: 'market',
      market: 'cn',
      kind: 'reserved',
      status: 'research_only',
      formula: null,
      formula_version: null,
    });
    expect(rdi.inputs.series_id).toBe('cn:RDI');
    expect(validateIndicatorRegistry([rdi])).toEqual([]);
  });

  it('never emits RDI values even when a series is supplied', () => {
    const result = computeIndicator(entry('market_cn_rdi_reserved'), {
      scope: 'market', market: 'cn', series_id: 'cn:RDI', series: points([1, 2, 3]),
    });
    expect(result).toMatchObject({ available: false, reason: 'not_computable_status' });
    expect('series' in result).toBe(false);
  });
});

describe('formula parameter contract', () => {
  it('accepts only the exact governed parameter set', () => {
    expect(validateFormulaParams('sma', { period: 20 })).toBeNull();
    expect(validateFormulaParams('sma', {})).not.toBeNull();
    expect(validateFormulaParams('sma', { period: 20, extra: 1 })).not.toBeNull();
    expect(validateFormulaParams('sma', { period: 0 })).not.toBeNull();
    expect(validateFormulaParams('macd', { fast: 26, slow: 12, signal: 9 })).not.toBeNull();
    expect(validateFormulaParams('bollinger', { period: 20, std_dev: 0 })).not.toBeNull();
    expect(validateFormulaParams('unknown', { period: 1 })).not.toBeNull();
  });
});
