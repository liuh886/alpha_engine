import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadFormalRunEvidence } from '../src/lib/formal-run-evidence';
import { loadFormalRuns } from '../src/lib/governed-run';

const publicRoot = path.resolve(process.cwd(), 'public');
const BYD_V13 = 'byd_v1_3_recovery_event_low_vol_confirmation_v1';

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
      BYD_V13,
      'cn_x1_1',
      'qqqi_qqq_tqqq_v4_3',
      'us_x1_2',
    ]);

    const evidenceByModel = new Map<string, Awaited<ReturnType<typeof loadFormalRunEvidence>>>();
    for (const run of result.runs) {
      const evidence = await loadFormalRunEvidence(run);
      expect(evidence.performance.report.length).toBeGreaterThan(0);
      expect(evidence.portfolio.positions.length).toBeGreaterThan(0);
      evidenceByModel.set(run.modelVersionId, evidence);
    }

    const byd = evidenceByModel.get(BYD_V13);
    expect(byd).toBeDefined();
    const bydWeights = byd?.portfolio.positions.map((position) => position.weight) ?? [];
    expect(bydWeights.some((weight) => weight > 1)).toBe(true);
    expect(bydWeights.some((weight) => weight < 0)).toBe(true);
  });
});
