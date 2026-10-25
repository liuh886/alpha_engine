import { sha256Text } from './model-run-bundle-v2';
import type { GovernedRunSummary } from './governed-run';
import { periodStartIndex, type PerformancePeriod } from './performancePeriods';

export interface SecurityBar {
  time: string; open: number; high: number; low: number; close: number; volume: number;
}
export interface SecurityEvent {
  time: string; model_id: string; run_id: string; instrument_id: string;
  action: 'BUY' | 'SELL' | 'INCREASE' | 'DECREASE';
  previous_weight: number | null; target_weight: number | null; reason: string;
}
export interface SecuritySymbol {
  symbol: string; name: string; instrument_id: string; path: string; sha256: string;
  source_sha256: string; source_instruments: string[];
}
interface FormalBinding { model_version_id: string; run_id: string; bundle_id: string }
export interface SecurityCatalog {
  market: 'us' | 'cn'; cutoff: string; provider_manifest_sha256: string;
  symbols: SecuritySymbol[]; formal_bindings: FormalBinding[];
}
export interface SecurityEvidence {
  market: 'us' | 'cn'; symbol: string; name: string; cutoff: string;
  source_sha256: string; provider_manifest_sha256: string;
  bars: SecurityBar[]; events: SecurityEvent[]; bindings: FormalBinding[];
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid security evidence object.');
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== 'string' || !value) throw new Error('Missing security evidence field.');
  return value;
}
function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Invalid security numeric observation.');
  return value;
}
function hash(value: unknown): string {
  const result = text(value);
  if (!/^[a-f0-9]{64}$/.test(result)) throw new Error('Invalid security evidence digest.');
  return result;
}
function date(value: unknown): string {
  const result = text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || !Number.isFinite(Date.parse(result))
    || new Date(result).toISOString().slice(0, 10) !== result) throw new Error('Invalid security evidence date.');
  return result;
}
function boundary(value: Record<string, unknown>) {
  if (value.view !== 'security_detail_v1' || value.research_only !== true || value.trade_ready !== false) {
    throw new Error('Invalid security history research boundary.');
  }
}
function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('Missing security evidence rows.');
  return value;
}
const root = () => `${import.meta.env.BASE_URL}data/market-evidence/`;
async function read(path: string): Promise<string> {
  const response = await fetch(`${root()}${path}`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`Security history unavailable (${response.status}).`);
  return response.text();
}

export function parseSecurityCatalog(value: unknown, market: 'us' | 'cn'): SecurityCatalog {
  const raw = object(value);
  boundary(raw);
  if (raw.market !== market || raw.evidence_type !== 'market_evidence_catalog') throw new Error('Security market mismatch.');
  const symbols = array(raw.symbols).map(item => {
    const row = object(item);
    const symbol = text(row.symbol);
    const path = text(row.path);
    if (!/^[A-Za-z0-9._-]+$/.test(symbol) || path !== `symbols/${symbol}.json`
      || row.instrument_id !== `${market}:${symbol}`) throw new Error('Invalid security instrument identity.');
    return {
      symbol, path, name: text(row.name), instrument_id: text(row.instrument_id),
      sha256: hash(row.sha256), source_sha256: hash(row.source_sha256),
      source_instruments: array(row.source_instruments).map(text),
    };
  });
  if (new Set(symbols.map(row => row.symbol)).size !== symbols.length) throw new Error('Duplicate security identity.');
  const formal_bindings = array(raw.formal_bindings).map(item => {
    const row = object(item);
    return { model_version_id: text(row.model_version_id), run_id: text(row.run_id), bundle_id: hash(row.bundle_id) };
  });
  if (new Set(formal_bindings.map(row => row.model_version_id)).size !== formal_bindings.length) throw new Error('Duplicate model binding.');
  return { market, cutoff: date(raw.cutoff), symbols, formal_bindings, provider_manifest_sha256: hash(raw.provider_manifest_sha256) };
}

export function resolveSecurity(catalog: SecurityCatalog, requested: string): SecuritySymbol {
  const matches = catalog.symbols.filter(row => row.symbol === requested || row.instrument_id === requested
    || row.source_instruments.includes(requested));
  if (matches.length !== 1) throw new Error('This instrument has no unambiguous published price history in this market.');
  return matches[0];
}

export function parseSecurityEvidence(value: unknown, catalog: SecurityCatalog, symbol: SecuritySymbol): SecurityEvidence {
  const raw = object(value);
  boundary(raw);
  if (raw.market !== catalog.market || raw.symbol !== symbol.symbol || raw.instrument_id !== symbol.instrument_id
    || raw.provider_manifest_sha256 !== catalog.provider_manifest_sha256 || raw.source_sha256 !== symbol.source_sha256) {
    throw new Error('Security price/source identity mismatch.');
  }
  const cutoff = date(raw.cutoff);
  if (cutoff > catalog.cutoff) throw new Error('Security cutoff exceeds its catalog.');
  let previous = '';
  const bars = array(raw.bars).map(item => {
    const row = object(item);
    const time = date(row.time);
    const bar = { time, open: number(row.open), high: number(row.high), low: number(row.low), close: number(row.close), volume: number(row.volume) };
    if (time <= previous || time > cutoff || bar.low <= 0 || bar.volume < 0
      || bar.high < Math.max(bar.open, bar.close, bar.low) || bar.low > Math.min(bar.open, bar.close)) {
      throw new Error('Invalid or unordered security OHLCV evidence.');
    }
    previous = time;
    return bar;
  });
  if (!bars.length) throw new Error('No published security price observations.');
  const events = array(raw.formal_model_events).map(item => {
    const row = object(item);
    if (row.research_only !== true || row.trade_ready !== false || row.instrument_id !== symbol.instrument_id
      || !['BUY', 'SELL', 'INCREASE', 'DECREASE'].includes(String(row.action))) throw new Error('Invalid model event boundary.');
    return {
      time: date(row.time), model_id: text(row.model_id), run_id: text(row.run_id), instrument_id: symbol.instrument_id,
      action: row.action as SecurityEvent['action'], reason: typeof row.reason === 'string' ? row.reason : '',
      previous_weight: row.previous_weight == null ? null : number(row.previous_weight),
      target_weight: row.target_weight == null ? null : number(row.target_weight),
    };
  });
  return { market: catalog.market, symbol: symbol.symbol, name: symbol.name, cutoff, bars, events,
    source_sha256: symbol.source_sha256, provider_manifest_sha256: catalog.provider_manifest_sha256, bindings: catalog.formal_bindings };
}

export async function loadSecurityEvidence(market: 'us' | 'cn', requested: string): Promise<SecurityEvidence> {
  const catalog = parseSecurityCatalog(JSON.parse(await read(`${market}/catalog.json`)), market);
  const symbol = resolveSecurity(catalog, requested);
  const body = await read(`${market}/${symbol.path}`);
  if (await sha256Text(body) !== symbol.sha256) throw new Error('Security history checksum mismatch.');
  return parseSecurityEvidence(JSON.parse(body), catalog, symbol);
}

export function securityHref(market: string, instrument: string, model?: string): string | null {
  if (!['us', 'cn'].includes(market) || !instrument) return null;
  return `#/securities/${market}/${encodeURIComponent(instrument)}${model ? `?model=${encodeURIComponent(model)}` : ''}`;
}
export function securityBarsForPeriod(bars: SecurityBar[], period: PerformancePeriod): SecurityBar[] {
  const index = periodStartIndex(bars.map(row => ({ date: row.time, account: row.close })), period);
  return index < 0 ? [] : bars.slice(index);
}
export function boundSecurityEvents(evidence: SecurityEvidence, runs: GovernedRunSummary[]): SecurityEvent[] {
  const accepted = new Map(runs.filter(run => run.market === evidence.market && run.channel === 'formal').map(run => [run.modelVersionId, run]));
  return evidence.events.filter(event => {
    const run = accepted.get(event.model_id);
    return run && event.run_id === run.runId && evidence.bindings.some(binding => binding.model_version_id === event.model_id
      && binding.run_id === run.runId && binding.bundle_id === run.bundleId);
  });
}
