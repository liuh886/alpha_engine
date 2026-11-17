/**
 * Bridge between the governed indicator registry (`indicators.ts`) and the
 * security chart extension API (`security-chart-extensions.ts`).
 *
 * This module owns no indicator math and no market data: it selects registry
 * entries, calls `computeIndicator` with the exact observed bars/series, clamps
 * the returned points to the visible window, and describes the resulting
 * overlays. Insufficient data is returned as an explicit unavailable item with
 * the formula module's reason; nothing is filled, interpolated or fabricated.
 *
 * Colour roles are assigned by indicator family, never by list position or rank,
 * and stay distinct from the model-series identity tokens.
 */

import {
  INDICATOR_REGISTRY,
  INDICATOR_REGISTRY_SOURCE,
  INDICATOR_REGISTRY_SOURCE_SHA256,
  computeIndicator,
  type IndicatorBar,
  type IndicatorEntry,
  type IndicatorPoint,
} from './indicators';
import type { OverlayColorRole, SecurityChartOverlay } from './security-chart-extensions';
import type { SecurityBar } from './security-evidence';

export type IndicatorMarket = 'us' | 'cn';
export type IndicatorGroup = 'price' | 'volume' | 'indicator';

export interface IndicatorOption {
  id: string;
  label: string;
  scope: 'instrument' | 'market';
  group: IndicatorGroup;
  description: string;
}

export interface IndicatorLegendItem {
  key: string;
  label: string;
  colorRole: OverlayColorRole;
  dashed: boolean;
  group: IndicatorGroup;
}

export interface IndicatorUnavailableItem {
  id: string;
  label: string;
  reason: string;
}

export interface IndicatorOverlaySet {
  overlays: SecurityChartOverlay[];
  legend: IndicatorLegendItem[];
  unavailable: IndicatorUnavailableItem[];
}

export type MarketSeriesStatus = 'idle' | 'loading' | 'ready' | 'unavailable';

/** Defaults: one fast instrument average on, every other indicator off. */
export const DEFAULT_INSTRUMENT_INDICATORS: readonly string[] = ['instrument_sma_20'];

export const INDICATOR_DISCLOSURE =
  'Browser-derived from observed bars; formula version from the governed registry; not a signal.';

export const INDICATOR_REGISTRY_LABEL = `${INDICATOR_REGISTRY_SOURCE} · SHA-256 ${INDICATOR_REGISTRY_SOURCE_SHA256.slice(0, 12)}`;

const EMPTY_SET: IndicatorOverlaySet = { overlays: [], legend: [], unavailable: [] };

function seriesSymbol(entry: IndicatorEntry): string {
  const id = entry.inputs.series_id;
  return id ? id.split(':')[1] ?? id : entry.indicator_id;
}

/** Human label derived from the registry formula and its exact parameters. */
export function indicatorLabel(entry: IndicatorEntry): string {
  const params = entry.params;
  if (entry.scope === 'market') {
    const symbol = seriesSymbol(entry);
    if (entry.formula === 'sma') return `${symbol} SMA ${params.period}`;
    if (entry.kind === 'series') return symbol;
    return entry.indicator_id;
  }
  switch (entry.formula) {
    case 'sma':
      return `SMA ${params.period}`;
    case 'ema':
      return `EMA ${params.period}`;
    case 'rsi':
      return `RSI ${params.period}`;
    case 'macd':
      return `MACD ${params.fast}/${params.slow}/${params.signal}`;
    case 'bollinger':
      return `Bollinger ${params.period}/${params.std_dev}`;
    case 'volume_sma':
      return `Volume SMA ${params.period}`;
    default:
      return entry.indicator_id;
  }
}

function groupFor(entry: IndicatorEntry): IndicatorGroup {
  if (entry.scope === 'market') return 'indicator';
  if (entry.formula === 'volume_sma') return 'volume';
  if (entry.formula === 'rsi' || entry.formula === 'macd') return 'indicator';
  return 'price';
}

function toOption(entry: IndicatorEntry): IndicatorOption {
  return {
    id: entry.indicator_id,
    label: indicatorLabel(entry),
    scope: entry.scope,
    group: groupFor(entry),
    description: entry.description,
  };
}

/** Governed instrument-scope entries, in registry order. */
export function instrumentIndicatorOptions(): IndicatorOption[] {
  return INDICATOR_REGISTRY
    .filter(entry => entry.scope === 'instrument' && entry.status === 'governed')
    .map(toOption);
}

/**
 * Governed market-scope entries for the chart's own market. Only US VIX is
 * registered today; a CN chart is offered nothing, so no cross-market series is
 * ever selectable.
 */
export function marketIndicatorOptions(market: IndicatorMarket): IndicatorOption[] {
  if (market !== 'us') return [];
  return INDICATOR_REGISTRY
    .filter(entry => entry.scope === 'market' && entry.market === market && entry.status === 'governed')
    .map(toOption);
}

/** DOM swatch colour for a role; canvas overlays resolve the same role in the chart. */
export function overlayRoleCssColor(role: OverlayColorRole): string {
  switch (role) {
    case 'indicator-1':
      return 'hsl(var(--indicator-1))';
    case 'indicator-2':
      return 'hsl(var(--indicator-2))';
    case 'indicator-3':
      return 'hsl(var(--indicator-3))';
    case 'indicator-4':
      return 'hsl(var(--indicator-4))';
    case 'positive':
      return 'hsl(var(--positive))';
    case 'negative':
      return 'hsl(var(--negative))';
    case 'muted':
      return 'hsl(var(--muted-foreground))';
  }
}

interface LineSpec {
  key: string;
  label: string;
  output: string;
  kind: 'line' | 'histogram';
  colorRole: OverlayColorRole;
  pane: 'price' | 'volume' | 'indicator';
  paneId?: string;
  lineStyle: 'solid' | 'dashed';
  lineWidth: 1 | 2 | 3 | 4;
  priceFormat?: SecurityChartOverlay['priceFormat'];
  sign?: 'positive' | 'negative';
}

const RSI_FORMAT = { type: 'price' as const, precision: 1, minMove: 0.1 };
const MACD_FORMAT = { type: 'price' as const, precision: 2, minMove: 0.01 };
const VIX_FORMAT = { type: 'price' as const, precision: 2, minMove: 0.01 };

function lineSpec(spec: Omit<LineSpec, 'kind'>): LineSpec {
  return { ...spec, kind: 'line' };
}

function instrumentSpecs(entry: IndicatorEntry, label: string): LineSpec[] {
  const params = entry.params;
  switch (entry.formula) {
    case 'sma': {
      const role: OverlayColorRole = params.period >= 200
        ? 'indicator-3'
        : params.period >= 50 ? 'indicator-2' : 'indicator-1';
      return [lineSpec({ key: 'value', label, output: 'value', colorRole: role, pane: 'price', lineStyle: 'solid', lineWidth: 2 })];
    }
    case 'ema':
      return [lineSpec({
        key: 'value',
        label,
        output: 'value',
        colorRole: 'indicator-4',
        pane: 'price',
        lineStyle: params.period >= 26 ? 'dashed' : 'solid',
        lineWidth: 2,
      })];
    case 'bollinger':
      return [
        lineSpec({ key: 'middle', label: `${label} middle`, output: 'middle', colorRole: 'indicator-1', pane: 'price', lineStyle: 'solid', lineWidth: 1 }),
        lineSpec({ key: 'upper', label: `${label} upper`, output: 'upper', colorRole: 'indicator-1', pane: 'price', lineStyle: 'dashed', lineWidth: 1 }),
        lineSpec({ key: 'lower', label: `${label} lower`, output: 'lower', colorRole: 'indicator-1', pane: 'price', lineStyle: 'dashed', lineWidth: 1 }),
      ];
    case 'rsi':
      return [lineSpec({ key: 'value', label, output: 'value', colorRole: 'indicator-1', pane: 'indicator', paneId: 'rsi', lineStyle: 'solid', lineWidth: 2, priceFormat: RSI_FORMAT })];
    case 'volume_sma':
      return [lineSpec({ key: 'value', label, output: 'value', colorRole: 'muted', pane: 'volume', lineStyle: 'dashed', lineWidth: 2 })];
    case 'macd':
      return [
        lineSpec({ key: 'macd', label: `${label} line`, output: 'macd', colorRole: 'indicator-3', pane: 'indicator', paneId: 'macd', lineStyle: 'solid', lineWidth: 2, priceFormat: MACD_FORMAT }),
        lineSpec({ key: 'signal', label: `${label} signal`, output: 'signal', colorRole: 'indicator-2', pane: 'indicator', paneId: 'macd', lineStyle: 'solid', lineWidth: 2, priceFormat: MACD_FORMAT }),
        { key: 'histogram:positive', label: `${label} histogram +`, output: 'histogram', kind: 'histogram', colorRole: 'positive', pane: 'indicator', paneId: 'macd', lineStyle: 'solid', lineWidth: 1, priceFormat: MACD_FORMAT, sign: 'positive' },
        { key: 'histogram:negative', label: `${label} histogram −`, output: 'histogram', kind: 'histogram', colorRole: 'negative', pane: 'indicator', paneId: 'macd', lineStyle: 'solid', lineWidth: 1, priceFormat: MACD_FORMAT, sign: 'negative' },
      ];
    default:
      return [];
  }
}

function marketSpecs(entry: IndicatorEntry, label: string): LineSpec[] {
  const paneId = seriesSymbol(entry).toLowerCase();
  return [lineSpec({
    key: 'value',
    label,
    output: 'value',
    colorRole: entry.formula === 'sma' ? 'indicator-2' : 'indicator-3',
    pane: 'indicator',
    paneId,
    lineStyle: 'solid',
    lineWidth: 2,
    priceFormat: VIX_FORMAT,
  })];
}

function clampPoints(
  points: readonly IndicatorPoint[],
  first: string | undefined,
  last: string | undefined,
): IndicatorPoint[] {
  if (!first || !last) return [];
  return points.filter(point => point.time >= first && point.time <= last);
}

function materialize(
  entry: IndicatorEntry,
  specs: readonly LineSpec[],
  series: Readonly<Record<string, readonly IndicatorPoint[]>>,
  first: string | undefined,
  last: string | undefined,
): IndicatorOverlaySet {
  const overlays: SecurityChartOverlay[] = [];
  const legend: IndicatorLegendItem[] = [];
  for (const spec of specs) {
    const points = series[spec.output];
    if (!points) continue;
    const clipped = clampPoints(points, first, last).filter(point => (
      spec.sign === 'positive' ? point.value >= 0 : spec.sign === 'negative' ? point.value < 0 : true
    ));
    if (clipped.length === 0) continue;
    const id = `${entry.indicator_id}:${spec.key}`;
    overlays.push({
      id,
      label: spec.label,
      kind: spec.kind,
      data: clipped.map(point => ({ time: point.time, value: point.value })),
      pane: spec.pane,
      ...(spec.paneId ? { paneId: spec.paneId } : {}),
      colorRole: spec.colorRole,
      lineWidth: spec.lineWidth,
      ...(spec.kind === 'line' ? { lineStyle: spec.lineStyle } : {}),
      ...(spec.priceFormat ? { priceFormat: spec.priceFormat } : {}),
      ...(spec.pane === 'volume' ? { scaleMargins: { top: 0.8, bottom: 0 } } : {}),
    });
    legend.push({
      key: id,
      label: spec.label,
      colorRole: spec.colorRole,
      dashed: spec.kind === 'line' && spec.lineStyle === 'dashed',
      group: spec.pane === 'volume' ? 'volume' : spec.pane === 'indicator' ? 'indicator' : 'price',
    });
  }
  return { overlays, legend, unavailable: [] };
}

function unavailableItem(entry: IndicatorEntry, label: string, detail: string): IndicatorUnavailableItem {
  return { id: entry.indicator_id, label, reason: detail };
}

/**
 * Compute every enabled instrument-scope indicator from the instrument's own
 * bars. Warm-up uses the full observed history, then the emitted points are
 * clamped to the visible window; a series with no value in the window is omitted
 * with a visible reason.
 */
export function buildInstrumentIndicatorOverlays({
  market,
  bars,
  visibleBars,
  enabled,
}: {
  market: IndicatorMarket;
  bars: readonly SecurityBar[];
  visibleBars: readonly SecurityBar[];
  enabled: readonly string[];
}): IndicatorOverlaySet {
  if (visibleBars.length === 0) return EMPTY_SET;
  const first = visibleBars[0]?.time;
  const last = visibleBars[visibleBars.length - 1]?.time;
  if (!first || !last) return EMPTY_SET;
  const enabledIds = new Set(enabled);
  const instrumentBars: IndicatorBar[] = bars.map(bar => ({
    time: bar.time,
    close: bar.close,
    volume: bar.volume,
  }));

  const result: IndicatorOverlaySet = { overlays: [], legend: [], unavailable: [] };
  for (const entry of INDICATOR_REGISTRY) {
    if (entry.scope !== 'instrument' || !enabledIds.has(entry.indicator_id)) continue;
    const label = indicatorLabel(entry);
    const computed = computeIndicator(entry, { scope: 'instrument', market, bars: instrumentBars });
    if (!computed.available) {
      result.unavailable.push(unavailableItem(entry, label, computed.detail));
      continue;
    }
    const materialized = materialize(entry, instrumentSpecs(entry, label), computed.series, first, last);
    if (materialized.overlays.length === 0) {
      result.unavailable.push(unavailableItem(entry, label, 'No computed value falls inside the visible range.'));
      continue;
    }
    result.overlays.push(...materialized.overlays);
    result.legend.push(...materialized.legend);
  }
  return result;
}

/**
 * Compute every enabled market-scope indicator for this chart's market. A CN
 * chart is offered no market indicators at all. When the US governed series has
 * not been published the entries are reported unavailable with the caller's
 * reason and never receive invented or substitute values.
 */
export function buildMarketIndicatorOverlays({
  market,
  status,
  series,
  unavailableReason,
  visibleBars,
  enabled,
}: {
  market: IndicatorMarket;
  status: MarketSeriesStatus;
  series?: readonly IndicatorPoint[];
  unavailableReason?: string;
  visibleBars: readonly SecurityBar[];
  enabled: readonly string[];
}): IndicatorOverlaySet {
  if (market !== 'us') return EMPTY_SET;
  if (visibleBars.length === 0 || status === 'idle' || status === 'loading') return EMPTY_SET;
  const first = visibleBars[0]?.time;
  const last = visibleBars[visibleBars.length - 1]?.time;
  if (!first || !last) return EMPTY_SET;
  const enabledIds = new Set(enabled);

  const result: IndicatorOverlaySet = { overlays: [], legend: [], unavailable: [] };
  for (const entry of INDICATOR_REGISTRY) {
    if (entry.scope !== 'market' || entry.market !== market || !enabledIds.has(entry.indicator_id)) continue;
    const label = indicatorLabel(entry);
    if (!series) {
      result.unavailable.push(unavailableItem(
        entry,
        label,
        unavailableReason ?? `Governed series ${entry.inputs.series_id ?? 'us:VIX'} has not been published.`,
      ));
      continue;
    }
    const computed = computeIndicator(entry, {
      scope: 'market',
      market,
      series_id: entry.inputs.series_id ?? '',
      series,
    });
    if (!computed.available) {
      result.unavailable.push(unavailableItem(entry, label, computed.detail));
      continue;
    }
    const materialized = materialize(entry, marketSpecs(entry, label), computed.series, first, last);
    if (materialized.overlays.length === 0) {
      result.unavailable.push(unavailableItem(entry, label, 'No computed value falls inside the visible range.'));
      continue;
    }
    result.overlays.push(...materialized.overlays);
    result.legend.push(...materialized.legend);
  }
  return result;
}
