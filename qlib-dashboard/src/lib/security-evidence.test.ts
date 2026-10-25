import { describe, expect, it } from 'vitest';
import { boundSecurityEvents, parseSecurityCatalog, parseSecurityEvidence, resolveSecurity, securityBarsForPeriod, securityHref } from './security-evidence';
import type { GovernedRunSummary } from './governed-run';
import { securityMarkers } from '@/components/SecurityHistoryChart';

const sha = 'a'.repeat(64);
const boundary = { view: 'security_detail_v1', research_only: true, trade_ready: false };
const symbol = { symbol: '002594', name: 'BYD', instrument_id: 'cn:002594', path: 'symbols/002594.json', sha256: sha, source_sha256: sha, source_instruments: ['BYD', '002594'] };
const binding = { model_version_id: 'byd', run_id: 'formal-run', bundle_id: sha };
const catalog = () => parseSecurityCatalog({ ...boundary, market: 'cn', evidence_type: 'market_evidence_catalog', cutoff: '2026-03-01', provider_manifest_sha256: sha, symbols: [symbol], formal_bindings: [binding] }, 'cn');
const bars = [
  { time: '2026-01-01', open: 10, high: 12, low: 9, close: 11, volume: 10 },
  { time: '2026-03-01', open: 11, high: 14, low: 10, close: 12, volume: 20 },
];
const event = { time: '2026-03-01', model_id: 'byd', run_id: 'formal-run', instrument_id: 'cn:002594', action: 'BUY' as const,
  previous_weight: 0, target_weight: 1, reason: 'frozen rule', research_only: true, trade_ready: false };
const payload = () => ({ ...boundary, market: 'cn', symbol: '002594', instrument_id: 'cn:002594', cutoff: '2026-03-01', source_sha256: sha, provider_manifest_sha256: sha, bars, formal_model_events: [event] });
const evidence = () => parseSecurityEvidence(payload(), catalog(), symbol);

describe('instrument history evidence', () => {
  it('resolves governed aliases within their market and rejects unsafe paths', () => {
    expect(resolveSecurity(catalog(), 'BYD').symbol).toBe('002594');
    expect(resolveSecurity(catalog(), 'cn:002594').symbol).toBe('002594');
    expect(() => resolveSecurity(catalog(), 'us:002594')).toThrow(/unambiguous/);
    expect(() => parseSecurityCatalog({ ...catalog(), ...boundary, evidence_type: 'market_evidence_catalog', symbols: [{ ...symbol, path: '../other.json' }] }, 'cn')).toThrow(/identity/);
  });
  it('rejects conflicting aliases instead of substituting an instrument', () => {
    const source = catalog();
    source.symbols.push({ ...symbol, symbol: 'OTHER', instrument_id: 'cn:OTHER' });
    expect(() => resolveSecurity(source, 'BYD')).toThrow(/unambiguous/);
  });
  it('rejects identity, research-boundary, provider and price conflicts', () => {
    for (const patch of [{ market: 'us' }, { trade_ready: true }, { provider_manifest_sha256: 'b'.repeat(64) },
      { bars: [bars[1], bars[0]] }, { bars: [{ ...bars[0], high: 8 }] }, { bars: [{ ...bars[0], time: '2026-02-30' }] },
      { bars: [{ ...bars[0], time: '2026-04-01' }] }, { formal_model_events: [{ ...event, instrument_id: 'us:002594' }] }]) {
      expect(() => parseSecurityEvidence({ ...payload(), ...patch }, catalog(), symbol)).toThrow();
    }
  });
  it('binds markers to exact active model, run and bundle, including retirement', () => {
    const value = evidence();
    const run = { channel: 'formal', market: 'cn', modelVersionId: 'byd', runId: 'formal-run', bundleId: sha } as GovernedRunSummary;
    expect(boundSecurityEvents(value, [run])).toHaveLength(1);
    expect(boundSecurityEvents(value, [])).toHaveLength(0);
    expect(boundSecurityEvents(value, [{ ...run, bundleId: 'b'.repeat(64) }])).toHaveLength(0);
    expect(boundSecurityEvents(value, [{ ...run, runId: 'new-run' }])).toHaveLength(0);
    expect(boundSecurityEvents(value, [{ ...run, market: 'us' }])).toHaveLength(0);
  });
  it('uses actual price observations for period selection and never moves event dates', () => {
    expect(securityBarsForPeriod(bars, '1m')).toEqual([bars[1]]);
    const events = [event, { ...event, model_id: 'another-model' }, { ...event, time: '2026-02-28' }, { ...event, action: 'SELL' as const }];
    const markers = securityMarkers(bars, events);
    expect(markers).toHaveLength(2);
    expect(markers[0].events).toHaveLength(2);
    expect(markers[0].time).toBe('2026-03-01');
    expect(markers[1].positive).toBe(false);
    expect(events[2].time).toBe('2026-02-28');
  });
  it('constructs bounded historical links without a current-signal fallback', () => {
    expect(securityHref('cn', 'BYD', 'byd')).toBe('#/securities/cn/BYD?model=byd');
    expect(securityHref('hk', 'BYD')).toBeNull();
    expect(securityHref('us', '../QQQ')).toContain('..%2FQQQ');
  });
});
