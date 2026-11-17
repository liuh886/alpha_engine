import { describe, expect, it } from 'vitest';
import type { SecurityBar } from './security-evidence';
import {
  DEFAULT_INSTRUMENT_INDICATORS,
  buildInstrumentIndicatorOverlays,
  buildMarketIndicatorOverlays,
  indicatorLabel,
  instrumentIndicatorOptions,
  marketIndicatorOptions,
  overlayRoleCssColor,
} from './indicator-overlays';
import { INDICATOR_REGISTRY, type IndicatorPoint } from './indicators';

function makeBars(count: number): SecurityBar[] {
  return Array.from({ length: count }, (_, index) => {
    const time = new Date(Date.UTC(2025, 0, 1 + index)).toISOString().slice(0, 10);
    const close = 100 + Math.sin(index / 3) * 10;
    return {
      time,
      open: close,
      high: close + 1,
      low: close - 1,
      close,
      volume: 1000 + index,
    };
  });
}

function entry(id: string) {
  const found = INDICATOR_REGISTRY.find(candidate => candidate.indicator_id === id);
  if (!found) throw new Error(`missing fixture entry ${id}`);
  return found;
}

describe('indicator catalog', () => {
  it('lists exactly the governed instrument entries with formula-derived labels', () => {
    const options = instrumentIndicatorOptions();
    expect(options.map(option => option.label)).toEqual([
      'SMA 20', 'SMA 50', 'SMA 200', 'EMA 12', 'EMA 26', 'RSI 14',
      'MACD 12/26/9', 'Bollinger 20/2', 'Volume SMA 20',
    ]);
    expect(options.every(option => option.scope === 'instrument')).toBe(true);
    expect(options.find(option => option.label === 'Volume SMA 20')?.group).toBe('volume');
    expect(options.find(option => option.label === 'RSI 14')?.group).toBe('indicator');
  });

  it('offers VIX market indicators only on US charts', () => {
    expect(marketIndicatorOptions('us').map(option => option.label)).toEqual(['VIX', 'VIX SMA 20']);
    expect(marketIndicatorOptions('cn')).toEqual([]);
  });

  it('derives labels from the registry rather than hardcoded component copy', () => {
    expect(indicatorLabel(entry('instrument_macd_12_26_9'))).toBe('MACD 12/26/9');
    expect(indicatorLabel(entry('instrument_bollinger_20_2'))).toBe('Bollinger 20/2');
    expect(indicatorLabel(entry('market_us_vix'))).toBe('VIX');
    expect(indicatorLabel(entry('market_us_vix_sma_20'))).toBe('VIX SMA 20');
  });

  it('maps every colour role to a CSS token swatch', () => {
    for (const role of ['indicator-1', 'indicator-2', 'indicator-3', 'indicator-4', 'positive', 'negative', 'muted'] as const) {
      expect(overlayRoleCssColor(role)).toMatch(/^hsl\(var\(--/);
    }
  });
});

describe('instrument indicator overlays', () => {
  it('defaults to SMA 20 as a price-pane line with enough observations', () => {
    const bars = makeBars(60);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars: bars,
      enabled: [...DEFAULT_INSTRUMENT_INDICATORS],
    });
    expect(set.overlays).toHaveLength(1);
    expect(set.overlays[0]).toMatchObject({
      id: 'instrument_sma_20:value',
      label: 'SMA 20',
      kind: 'line',
      pane: 'price',
      colorRole: 'indicator-1',
    });
    expect(set.overlays[0].data).toHaveLength(41);
    expect(set.unavailable).toEqual([]);
    expect(set.legend).toHaveLength(1);
  });

  it('omits an indicator with a visible insufficient-data reason instead of fabricating', () => {
    const bars = makeBars(30);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars: bars,
      enabled: ['instrument_sma_200'],
    });
    expect(set.overlays).toEqual([]);
    expect(set.legend).toEqual([]);
    expect(set.unavailable).toEqual([
      expect.objectContaining({
        id: 'instrument_sma_200',
        label: 'SMA 200',
        reason: 'Indicator needs 200 observations but received 30.',
      }),
    ]);
  });

  it('emits three Bollinger lines on the price pane', () => {
    const bars = makeBars(40);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars: bars,
      enabled: ['instrument_bollinger_20_2'],
    });
    expect(set.overlays.map(overlay => overlay.id)).toEqual([
      'instrument_bollinger_20_2:middle',
      'instrument_bollinger_20_2:upper',
      'instrument_bollinger_20_2:lower',
    ]);
    expect(set.overlays.every(overlay => overlay.pane === 'price')).toBe(true);
  });

  it('renders RSI in its own indicator pane and volume SMA on the volume pane', () => {
    const bars = makeBars(60);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars: bars,
      enabled: ['instrument_rsi_14', 'instrument_volume_sma_20'],
    });
    const rsi = set.overlays.find(overlay => overlay.id === 'instrument_rsi_14:value');
    const volume = set.overlays.find(overlay => overlay.id === 'instrument_volume_sma_20:value');
    expect(rsi).toMatchObject({ pane: 'indicator', paneId: 'rsi', colorRole: 'indicator-1' });
    expect(volume).toMatchObject({ pane: 'volume', colorRole: 'muted', scaleMargins: { top: 0.8, bottom: 0 } });
  });

  it('splits the MACD histogram by sign into positive and negative series', () => {
    const bars = makeBars(80);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars: bars,
      enabled: ['instrument_macd_12_26_9'],
    });
    const line = set.overlays.find(overlay => overlay.id === 'instrument_macd_12_26_9:macd');
    const signal = set.overlays.find(overlay => overlay.id === 'instrument_macd_12_26_9:signal');
    const positive = set.overlays.find(overlay => overlay.id === 'instrument_macd_12_26_9:histogram:positive');
    const negative = set.overlays.find(overlay => overlay.id === 'instrument_macd_12_26_9:histogram:negative');
    expect(line).toMatchObject({ kind: 'line', paneId: 'macd', colorRole: 'indicator-3' });
    expect(signal).toMatchObject({ kind: 'line', paneId: 'macd', colorRole: 'indicator-2' });
    expect(positive).toMatchObject({ kind: 'histogram', colorRole: 'positive' });
    expect(negative).toMatchObject({ kind: 'histogram', colorRole: 'negative' });
    expect(positive?.data.every(point => point.value >= 0)).toBe(true);
    expect(negative?.data.every(point => point.value < 0)).toBe(true);
  });

  it('clamps emitted values to the visible window while using full history for warm-up', () => {
    const bars = makeBars(60);
    const visibleBars = bars.slice(-10);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars,
      enabled: ['instrument_sma_20'],
    });
    expect(set.overlays[0].data).toHaveLength(10);
    expect(set.overlays[0].data[0].time).toBe(visibleBars[0].time);
  });

  it('reports when no computed value falls inside the visible window', () => {
    const bars = makeBars(60);
    const set = buildInstrumentIndicatorOverlays({
      market: 'us',
      bars,
      visibleBars: [{ ...bars[0], time: '2030-01-01' }],
      enabled: ['instrument_sma_20'],
    });
    expect(set.overlays).toEqual([]);
    expect(set.unavailable[0].reason).toBe('No computed value falls inside the visible range.');
  });
});

describe('market indicator overlays', () => {
  const bars = makeBars(60);
  const series: IndicatorPoint[] = bars.map(bar => ({ time: bar.time, value: bar.close }));

  it('never offers or computes a market indicator on a CN chart', () => {
    const set = buildMarketIndicatorOverlays({
      market: 'cn',
      status: 'ready',
      series,
      visibleBars: bars,
      enabled: ['market_us_vix', 'market_us_vix_sma_20'],
    });
    expect(set).toEqual({ overlays: [], legend: [], unavailable: [] });
  });

  it('reports the governed VIX series unavailable with the supplied reason', () => {
    const set = buildMarketIndicatorOverlays({
      market: 'us',
      status: 'unavailable',
      unavailableReason: 'This instrument has no published price history in this market.',
      visibleBars: bars,
      enabled: ['market_us_vix', 'market_us_vix_sma_20'],
    });
    expect(set.overlays).toEqual([]);
    expect(set.unavailable.map(item => item.label)).toEqual(['VIX', 'VIX SMA 20']);
    expect(set.unavailable.every(item => item.reason.includes('no published price history'))).toBe(true);
  });

  it('does not render while the series is loading', () => {
    const set = buildMarketIndicatorOverlays({
      market: 'us',
      status: 'loading',
      visibleBars: bars,
      enabled: ['market_us_vix'],
    });
    expect(set).toEqual({ overlays: [], legend: [], unavailable: [] });
  });

  it('renders VIX and its SMA on one indicator pane when the series is published', () => {
    const set = buildMarketIndicatorOverlays({
      market: 'us',
      status: 'ready',
      series,
      visibleBars: bars,
      enabled: ['market_us_vix', 'market_us_vix_sma_20'],
    });
    expect(set.overlays.map(overlay => overlay.id)).toEqual([
      'market_us_vix:value',
      'market_us_vix_sma_20:value',
    ]);
    expect(set.overlays.every(overlay => overlay.pane === 'indicator' && overlay.paneId === 'vix')).toBe(true);
    expect(set.unavailable).toEqual([]);
  });
});
