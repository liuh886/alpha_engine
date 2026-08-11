/// <reference types="node" />

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  formatCanonicalMetric,
  formatDeclaredValue,
} from './evidence-availability';
import { metricById } from './formal-run-evidence';
import type { CanonicalMetricV2 } from './model-run-bundle-v2';

const libDir = dirname(fileURLToPath(import.meta.url));
const dashboardRoot = resolve(libDir, '../..');
const formalRoot = resolve(dashboardRoot, 'public/data/formal-model-runs');

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>;
}

describe('formal evidence helpers', () => {
  it('returns null when a canonical metric is absent', () => {
    expect(metricById([], 'missing')).toBeNull();
  });

  it('keeps formal US x1.2 free of generic unavailable and undeclared placeholders', () => {
    const catalog = readJson(resolve(formalRoot, 'catalog.json'));
    const records = catalog.records as Array<Record<string, unknown>>;
    const record = records.find((row) => row.model_version_id === 'us_x1_2');
    expect(record).toBeTruthy();

    const manifestPath = String(record?.manifest_path);
    const runRoot = dirname(resolve(formalRoot, manifestPath));
    const summary = readJson(resolve(runRoot, 'summary.json'));
    const performance = readJson(resolve(runRoot, 'performance.json'));
    const metrics = summary.metrics as CanonicalMetricV2[];

    const requiredMetricIds = [
      'total_return',
      'annualized_return',
      'benchmark_return',
      'excess_return',
      'annualized_volatility',
      'sharpe_ratio',
      'information_ratio',
      'max_drawdown',
      'turnover',
      'transaction_cost',
      'ic',
      'rank_ic',
      'icir',
    ];
    const renderedMetrics = requiredMetricIds.map((metricId) => {
      const metric = metricById(metrics, metricId);
      expect(metric).not.toBeNull();
      return formatCanonicalMetric(metric);
    });
    expect(renderedMetrics).not.toContain('Unavailable');
    expect(renderedMetrics).not.toContain('Not declared');
    expect(renderedMetrics).not.toContain('Contract violation');

    const semantics = performance.performance_semantics as Record<string, unknown>;
    const cost = semantics.cost as Record<string, unknown>;
    const renderedMethodology = [
      semantics.signal_time,
      semantics.execution_time,
      semantics.return_measurement,
      semantics.price_basis,
      semantics.holding_end_offset_sessions,
      cost.rate_bps,
      cost.turnover_formula,
      cost.net_return_formula,
    ].map(formatDeclaredValue);
    expect(renderedMethodology).not.toContain('Unavailable');
    expect(renderedMethodology).not.toContain('Not declared');
    expect(renderedMethodology).not.toContain('Contract violation');
  });
});
