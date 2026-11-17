import { describe, expect, it } from 'vitest';
import { baselineOptionsFor, defaultBaselineKindFor, type BaselineOptionSource } from './baseline-options';

describe('typed baseline option source', () => {
  const strategy: BaselineOptionSource = {
    view: 'strategy',
    run: { benchmark: 'QQQ', market: 'us' },
    rows: [
      { date: '2026-01-02', account: 100, bench_qqq: 200 },
      { date: '2026-01-05', account: 101, bench_qqq: 202 },
    ],
  };
  const security: BaselineOptionSource = { view: 'security', market: 'cn', isSelf: false };
  const self: BaselineOptionSource = { view: 'security', market: 'us', isSelf: true };

  it('returns declared, market and none for a strategy run', () => {
    const options = baselineOptionsFor(strategy);
    expect(options.map(option => option.kind)).toEqual(['declared', 'market', 'none']);
    expect(options[0]).toMatchObject({ label: 'QQQ', source: 'formal_report', available: true });
    expect(options[1]).toMatchObject({ label: 'QQQ', source: 'market_bars', available: true });
  });

  it('returns only the governed market baseline and none for a security', () => {
    expect(baselineOptionsFor(security)).toMatchObject([
      { key: 'market:000300', kind: 'market', source: 'market_bars', available: true },
      { key: 'none', kind: 'none', available: true },
    ]);
  });

  it('applies the page-appropriate default without inventing a security baseline', () => {
    expect(defaultBaselineKindFor(strategy, baselineOptionsFor(strategy), 'declared')).toBe('declared');
    expect(defaultBaselineKindFor(strategy, baselineOptionsFor(strategy), 'market')).toBe('market');
    expect(defaultBaselineKindFor(security, baselineOptionsFor(security), 'declared')).toBe('none');
    expect(defaultBaselineKindFor(security, baselineOptionsFor(security), 'market')).toBe('market');
    expect(defaultBaselineKindFor(self, baselineOptionsFor(self), 'market')).toBe('none');
  });
});
