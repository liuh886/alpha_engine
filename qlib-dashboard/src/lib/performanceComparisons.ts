import type {
  MarketBar,
  MarketEvidenceCatalog,
  MarketEvidenceCatalogSymbol,
  MarketEvidenceMarket,
} from '@/lib/market-evidence';
import {
  normalizeBenchmarkSeries,
  type BenchmarkOption,
  type NormalizedSeries,
} from '@/lib/performanceBenchmarks';

export type ComparisonGroup = 'Benchmarks' | 'US stock pool' | 'CN stock pool';

export interface PerformanceComparisonOption {
  key: string;
  label: string;
  detail?: string;
  group: ComparisonGroup;
  source: 'report' | 'market';
  market?: MarketEvidenceMarket;
  series?: NormalizedSeries;
  marketSymbol?: MarketEvidenceCatalogSymbol;
}

const PRESET_ORDER = ['csi300', 'qqq', 'tqqq', 'cgdv'];

function compactIdentity(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

export function canonicalComparisonIdentity(value: string): string {
  const identity = compactIdentity(value);
  if (['csi300', '000300', '000300sh', 'sh000300'].includes(identity)) return 'csi300';
  return identity;
}

function comparisonLabel(symbol: MarketEvidenceCatalogSymbol): string {
  if (canonicalComparisonIdentity(symbol.symbol) === 'csi300') return 'CSI 300';
  return symbol.symbol;
}

export function marketComparisonKey(market: MarketEvidenceMarket, symbol: string): string {
  return `market_${market}_${symbol}`.replace(/[^A-Za-z0-9_]+/g, '_');
}

function optionOrder(option: PerformanceComparisonOption): [number, string] {
  const presetIndex = PRESET_ORDER.indexOf(canonicalComparisonIdentity(option.label));
  return [presetIndex >= 0 ? presetIndex : PRESET_ORDER.length, option.label];
}

export function buildPerformanceComparisonOptions(
  retained: BenchmarkOption[],
  catalogs: MarketEvidenceCatalog[],
): PerformanceComparisonOption[] {
  const reportOptions: PerformanceComparisonOption[] = retained.map(option => ({
    key: option.key,
    label: option.label,
    group: 'Benchmarks',
    source: 'report',
    series: option.series,
  }));
  const seenIdentities = new Set(reportOptions.map(option => canonicalComparisonIdentity(option.label)));
  const marketOptions: PerformanceComparisonOption[] = [];

  for (const catalog of catalogs) {
    for (const symbol of catalog.symbols) {
      const identity = canonicalComparisonIdentity(symbol.symbol);
      if (seenIdentities.has(identity)) continue;
      seenIdentities.add(identity);
      marketOptions.push({
        key: marketComparisonKey(catalog.market, symbol.symbol),
        label: comparisonLabel(symbol),
        detail: symbol.name !== symbol.symbol ? symbol.name : undefined,
        group: symbol.roles.includes('selected_pool_candidate')
          ? catalog.market === 'us' ? 'US stock pool' : 'CN stock pool'
          : 'Benchmarks',
        source: 'market',
        market: catalog.market,
        marketSymbol: symbol,
      });
    }
  }

  const benchmarks = [...reportOptions, ...marketOptions.filter(option => option.group === 'Benchmarks')]
    .sort((left, right) => {
      const [leftPreset, leftLabel] = optionOrder(left);
      const [rightPreset, rightLabel] = optionOrder(right);
      return leftPreset - rightPreset || leftLabel.localeCompare(rightLabel);
    });
  const usPool = marketOptions
    .filter(option => option.group === 'US stock pool')
    .sort((left, right) => left.label.localeCompare(right.label));
  const cnPool = marketOptions
    .filter(option => option.group === 'CN stock pool')
    .sort((left, right) => left.label.localeCompare(right.label));

  return [...benchmarks, ...usPool, ...cnPool];
}

export function alignMarketBarsToPerformanceDates(
  bars: MarketBar[],
  dates: string[],
): NormalizedSeries | null {
  if (!bars.length || !dates.length) return null;
  const orderedBars = [...bars].sort((left, right) => left.time.localeCompare(right.time));
  let cursor = 0;
  let lastClose: number | undefined;
  const levels = dates.map(date => {
    while (cursor < orderedBars.length && orderedBars[cursor].time <= date) {
      const close = Number(orderedBars[cursor].close);
      if (Number.isFinite(close) && close > 0) lastClose = close;
      cursor += 1;
    }
    return lastClose;
  });
  return normalizeBenchmarkSeries(levels);
}
