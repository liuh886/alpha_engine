import { describe, expect, it } from 'vitest';
import type { ModelData } from './data-parser';
import { adaptLocalRuns, governedRunQuery, selectRunFromQuery } from './governed-run';

describe('governed run identity helpers', () => {
  it('keeps local research isolated from formal publication semantics', () => {
    const model = {
      id: 'fixture_local_model',
      name: 'Fixture local model',
      market: 'us',
      model_type: 'lgbm',
      run_id: 'fixture-local-run',
      created_at: '2026-08-03T00:00:00Z',
    } as ModelData;
    const [run] = adaptLocalRuns([model]);
    expect(run.channel).toBe('local');
    expect(run.publicationStatus).toBe('local_only');
    expect(run.evidenceStatus).toBe('partial');
    expect(run.bundleId).toBeNull();
    expect(run.formalPackage).toBeNull();
    expect(run.modelData).toBe(model);
  });

  it('round-trips channel, family, version and run deep links', () => {
    const model = {
      id: 'fixture_local_model',
      name: 'Fixture local model',
      market: 'us',
      run_id: 'fixture-local-run',
    } as ModelData;
    const [run] = adaptLocalRuns([model]);
    const query = governedRunQuery(run);
    expect(selectRunFromQuery([run], `?${query}`)?.key).toBe(run.key);
    expect(selectRunFromQuery([run], '?channel=formal&family=x&version=y&run=z')).toBeNull();
  });
});
