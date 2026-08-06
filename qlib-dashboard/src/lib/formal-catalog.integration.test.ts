import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadFormalRunEvidence } from './formal-run-evidence';
import { loadFormalRuns } from './governed-run';

const publicRoot = path.resolve(process.cwd(), 'public');

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('published formal catalog', () => {
  it('loads every manifest and evidence section through the production parser', async () => {
    vi.stubGlobal('fetch', async (input: string | URL | Request) => {
      const requested = typeof input === 'string'
        ? input
        : input instanceof URL ? input.toString() : input.url;
      const relativePath = requested.replace(/^\.\//, '').replace(/^\//, '');
      try {
        const body = await readFile(path.join(publicRoot, relativePath), 'utf8');
        return new Response(body, { status: 200 });
      } catch {
        return new Response('not found', { status: 404 });
      }
    });

    const result = await loadFormalRuns();
    expect(result.errors).toEqual([]);
    expect(result.runs.map((run) => run.modelVersionId).sort()).toEqual([
      'byd_v1_2_convex_momentum_budget_v1',
      'cn_x1_1',
      'qqqi_qqq_tqqq_v4_2',
      'us_x1_1',
    ]);

    for (const run of result.runs) {
      const evidence = await loadFormalRunEvidence(run);
      expect(evidence.performance.report.length).toBeGreaterThan(0);
      expect(evidence.portfolio.positions.length).toBeGreaterThan(0);
    }
  });
});
