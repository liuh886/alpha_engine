import { describe, expect, it } from 'vitest';
import type { ModelData } from './data-parser';
import { extractSignalExecutionRows, formatBytes, groupArtifacts, numericMetric } from './artifact-data';

describe('artifact evidence helpers', () => {
  it('groups manifest artifacts without losing required counts', () => {
    const groups = groupArtifacts([
      { artifact_id: 'a', kind: 'report', path: 'reports/a.md', media_type: 'text/markdown', byte_size: 100, sha256: '0'.repeat(64), required: false },
      { artifact_id: 'b', kind: 'report', path: 'reports/b.md', media_type: 'text/markdown', byte_size: 200, sha256: '1'.repeat(64), required: true },
      { artifact_id: 'c', kind: 'model_index', path: 'data/models.json', media_type: 'application/json', byte_size: 50, sha256: '2'.repeat(64), required: true },
    ]);
    expect(groups.find((group) => group.kind === 'report')).toEqual({ kind: 'report', count: 2, bytes: 300, required: 1 });
    expect(groups.find((group) => group.kind === 'model_index')?.required).toBe(1);
  });

  it('keeps signal and execution dates as distinct fields', () => {
    const model = {
      id: 'run-1',
      params: {
        signal_execution_ledger: [
          { symbol: 'QQQ', signal_date: '2026-07-30', execution_date: '2026-07-31', action: 'buy', weight: 1 },
        ],
      },
      metrics: { 'Sharpe Ratio': 1.23 },
      backtest: { metrics: {}, positions: [] },
    } as unknown as ModelData;
    const rows = extractSignalExecutionRows(model);
    expect(rows).toHaveLength(1);
    expect(rows[0].signalDate).toBe('2026-07-30');
    expect(rows[0].executionDate).toBe('2026-07-31');
    expect(rows[0].signalDate).not.toBe(rows[0].executionDate);
    expect(numericMetric(model, ['Sharpe Ratio'])).toBe(1.23);
  });

  it('formats artifact byte sizes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.0 MB');
  });
});
