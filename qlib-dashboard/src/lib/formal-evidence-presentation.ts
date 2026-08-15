const WINDOW_COLUMN_PRIORITY = [
  'window',
  'rebalance_count',
  'periods',
  'positive_periods',
  'total_return',
  'net_strategy_return',
  'benchmark_return',
  'qqq_return',
  'relative_excess',
  'simple_excess_return',
  'max_drawdown',
  'risk_on_share',
  'all_period_hit_rate',
  'turnover',
  'transaction_cost',
  'cost_bps',
] as const;

export function visibleWindowColumns(rows: Array<Record<string, unknown>>): string[] {
  const declared = new Set(
    rows.flatMap((row) => Object.entries(row)
      .filter(([, value]) => value === null || ['string', 'number', 'boolean'].includes(typeof value))
      .map(([key]) => key)),
  );
  const prioritized = WINDOW_COLUMN_PRIORITY.filter((column) => declared.has(column));
  const extras = [...declared]
    .filter((column) => !WINDOW_COLUMN_PRIORITY.includes(column as typeof WINDOW_COLUMN_PRIORITY[number]))
    .sort();
  return [...prioritized, ...extras];
}
