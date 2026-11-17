import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SecurityEvent } from './security-evidence';
import type { GovernedRunSummary } from './governed-run';
import {
  buildRelatedModelEntries,
  holdingAliases,
  holdingForSnapshot,
  parseLatestPortfolioSnapshot,
  readRelatedTradeInstruments,
  summarizeModelEvents,
  summarizeTradeInstruments,
} from './related-entities';

const mocks = vi.hoisted(() => ({ loadRunSection: vi.fn() }));

vi.mock('./governed-run', async importOriginal => {
  const actual = await importOriginal<typeof import('./governed-run')>();
  return { ...actual, loadRunSection: mocks.loadRunSection };
});

beforeEach(() => {
  mocks.loadRunSection.mockReset();
});

function event(overrides: Partial<SecurityEvent> = {}): SecurityEvent {
  return {
    time: '2026-01-05',
    model_id: 'model_a',
    run_id: 'run-a',
    instrument_id: 'us:AAA',
    action: 'BUY',
    previous_weight: 0,
    target_weight: 0.5,
    reason: 'frozen_rule',
    ...overrides,
  };
}

function run(overrides: Partial<GovernedRunSummary> = {}): GovernedRunSummary {
  return {
    key: 'formal:family:model_a:run-a',
    modelFamilyId: 'family',
    modelVersionId: 'model_a',
    runId: 'run-a',
    bundleId: 'a'.repeat(64),
    title: 'Model A',
    modelKind: 'cross_sectional_ranker',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-01-12T00:00:00Z',
    evidenceCutoff: '2026-01-31',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: null,
    manifestSha256: null,
    summary: {},
    manifest: null,
    loadWarnings: [],
    ...overrides,
  };
}

function portfolio(rows: Array<{ date: string; instrument: string; weight: number }>) {
  return { research_only: true, trade_ready: false, positions: rows };
}

describe('summarizeModelEvents', () => {
  it('counts exact events per model and keeps the latest action and date', () => {
    const summaries = summarizeModelEvents([
      event({ time: '2026-01-05', action: 'BUY' }),
      event({ time: '2026-01-09', action: 'DECREASE' }),
      event({ time: '2026-01-07', action: 'INCREASE', model_id: 'model_b' }),
    ]);
    expect(summaries.get('model_a')).toEqual({ eventCount: 2, lastAction: 'DECREASE', lastEventDate: '2026-01-09' });
    expect(summaries.get('model_b')).toEqual({ eventCount: 1, lastAction: 'INCREASE', lastEventDate: '2026-01-07' });
  });

  it('lets the last retained row win an exact-date tie without inventing an order', () => {
    const summaries = summarizeModelEvents([
      event({ time: '2026-01-09', action: 'BUY' }),
      event({ time: '2026-01-09', action: 'SELL' }),
    ]);
    expect(summaries.get('model_a')?.lastAction).toBe('SELL');
  });
});

describe('holding aliases', () => {
  it('keeps the catalog symbol, display name and published aliases unique and case-insensitive', () => {
    expect(holdingAliases({
      symbol: '002594',
      name: 'BYD',
      source_instruments: ['002594', 'BYD', 'byd'],
    })).toEqual(['002594', 'byd']);
  });
});

describe('parseLatestPortfolioSnapshot', () => {
  it('uses the latest published date and resolves a published alias to its weight', () => {
    const snapshot = parseLatestPortfolioSnapshot(portfolio([
      { date: '2026-01-02', instrument: 'BYD', weight: 0.5 },
      { date: '2026-01-02', instrument: '515180.SH', weight: 0.5 },
      { date: '2026-01-09', instrument: '515180.SH', weight: 0.25 },
      { date: '2026-01-09', instrument: 'BYD', weight: 0.75 },
    ]));
    expect(snapshot.asOf).toBe('2026-01-09');
    expect(holdingForSnapshot(snapshot, ['byd'])).toEqual({ instrument: 'BYD', weight: 0.75 });
    expect(holdingForSnapshot(snapshot, ['515180.sh'])).toEqual({ instrument: '515180.SH', weight: 0.25 });
    expect(holdingForSnapshot(snapshot, ['AAPL'])).toBeNull();
  });

  it('fails closed on a missing research boundary, duplicate holding or non-unit weight', () => {
    expect(() => parseLatestPortfolioSnapshot({ positions: [] })).toThrow(/research-only boundary/);
    expect(() => parseLatestPortfolioSnapshot(portfolio([
      { date: '2026-01-09', instrument: 'BYD', weight: 0.5 },
      { date: '2026-01-09', instrument: 'byd', weight: 0.5 },
    ]))).toThrow(/twice/);
    expect(() => parseLatestPortfolioSnapshot(portfolio([
      { date: '2026-01-09', instrument: 'BYD', weight: 0.4 },
    ]))).toThrow(/expected 1/);
  });
});

describe('buildRelatedModelEntries', () => {
  it('shows an event model with its exact summary and a held-only model without inferring events', () => {
    const entries = buildRelatedModelEntries(
      [run(), run({ modelVersionId: 'model_b', title: 'Model B' }), run({ modelVersionId: 'model_c', title: 'Model C' })],
      [event({ model_id: 'model_a' })],
      {
        model_a: { status: 'held', weight: 0.75, asOf: '2026-01-09', cutoff: '2026-01-31', instrument: 'AAA' },
        model_b: { status: 'held', weight: 0.25, asOf: '2026-01-09', cutoff: '2026-01-31', instrument: 'AAA' },
        model_c: { status: 'not_held', asOf: '2026-01-09', cutoff: '2026-01-31' },
      },
    );
    expect(entries.map(entry => entry.modelVersionId)).toEqual(['model_a', 'model_b']);
    expect(entries[0].events).toEqual({ eventCount: 1, lastAction: 'BUY', lastEventDate: '2026-01-05' });
    expect(entries[1].events).toBeNull();
    expect(entries[1].holding.status).toBe('held');
  });

  it('returns nothing when no bound model traded or held the instrument', () => {
    expect(buildRelatedModelEntries(
      [run()],
      [],
      { model_a: { status: 'not_held', asOf: '2026-01-09', cutoff: '2026-01-31' } },
    )).toEqual([]);
  });
});

describe('trade instrument summaries', () => {
  it('groups the retained ledger by instrument with count and latest action', () => {
    const rows = summarizeTradeInstruments([
      { date: '2026-08-04', action: 'SELL', instrument: 'BYD' },
      { date: '2026-08-04', action: 'BUY', instrument: '515180.SH' },
      { date: '2026-07-31', action: 'BUY', instrument: 'BYD' },
      { date: '2026-07-31', action: 'SELL', instrument: '515180.SH' },
      { date: '2026-01-01', action: 'BUY', instrument: 'CASH' },
    ]);
    expect(rows.map(row => row.instrument)).toEqual(['515180.SH', 'BYD', 'CASH']);
    expect(rows.find(row => row.instrument === 'BYD')).toEqual({
      instrument: 'BYD', tradeCount: 2, lastAction: 'SELL', lastDate: '2026-08-04',
    });
    expect(rows.find(row => row.instrument === '515180.SH')).toEqual({
      instrument: '515180.SH', tradeCount: 2, lastAction: 'BUY', lastDate: '2026-08-04',
    });
  });

  it('ignores rows without an instrument or a valid trade date', () => {
    expect(summarizeTradeInstruments([
      { date: '2026-08-04', action: 'SELL', instrument: null },
      { date: '', action: 'BUY', instrument: 'BYD' },
      { date: '2026-08-05', action: 'BUY', instrument: '515180.SH' },
    ])).toEqual([{ instrument: '515180.SH', tradeCount: 1, lastAction: 'BUY', lastDate: '2026-08-05' }]);
  });

  it('reads the retained trade ledger and states an unavailable section instead of inventing rows', async () => {
    mocks.loadRunSection.mockResolvedValueOnce([{ date: '2026-08-04', action: 'SELL', instrument: 'BYD' }]);
    await expect(readRelatedTradeInstruments(run())).resolves.toEqual({
      status: 'ready',
      instruments: [{ instrument: 'BYD', tradeCount: 1, lastAction: 'SELL', lastDate: '2026-08-04' }],
    });
    expect(mocks.loadRunSection).toHaveBeenCalledWith(expect.objectContaining({ modelVersionId: 'model_a' }), 'trades');

    mocks.loadRunSection.mockRejectedValueOnce(new Error('trades is not_retained'));
    await expect(readRelatedTradeInstruments(run())).resolves.toEqual({
      status: 'unavailable', reason: 'trades is not_retained',
    });
  });
});
