import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DerivedExcessError,
  loadDerivedExcess,
  type DerivedExcessErrorReason,
} from './derived-excess';
import type { GovernedRunSummary } from './governed-run';
import type { ModelRunBundleV2Manifest } from './model-run-bundle-v2';
import { sha256Text } from './model-run-bundle-v2';

const PERFORMANCE_SHA = 'a'.repeat(64);
const MANIFEST_SHA = 'b'.repeat(64);
const BUNDLE_ID = 'c'.repeat(64);
const PERFORMANCE_BYTE_SIZE = 389313;

interface FixtureIdentity {
  derivationId: string;
  modelVersionId: string;
  runId: string;
}

interface CatalogIdentity {
  derivation_id: string;
  model_version_id: string;
  run_id: string;
  manifest_sha256: string;
}

let sequence = 0;

function nextIdentity(): FixtureIdentity {
  sequence += 1;
  return {
    derivationId: `derived_excess_${sequence}`,
    modelVersionId: `derived_model_${sequence}`,
    runId: `derived_model_${sequence}-through-2026_11_11`,
  };
}

function entryIdentity(identity: FixtureIdentity): CatalogIdentity {
  return {
    derivation_id: identity.derivationId,
    model_version_id: identity.modelVersionId,
    run_id: identity.runId,
    manifest_sha256: MANIFEST_SHA,
  };
}

function runFixture(identity: FixtureIdentity): GovernedRunSummary {
  const manifest: ModelRunBundleV2Manifest = {
    schema_version: '2.0.0',
    model_family_id: 'qqq_rotation',
    model_version_id: identity.modelVersionId,
    run_id: identity.runId,
    bundle_id: BUNDLE_ID,
    model_kind: 'rules_based_allocation',
    publication_channel: 'formal',
    publication_status: 'accepted_formal_baseline',
    generated_at: '2026-11-12T04:01:28Z',
    evidence_cutoff: '2026-11-11',
    research_only: true,
    trade_ready: false,
    comparability_key: {
      market: 'us',
      universe_id: 'fixture_universe',
      benchmark_id: 'qqq',
      start: '2024-01-30',
      end: '2026-11-10',
      trace_frequency: 'daily_open_to_open',
      horizon: 'retained_formal_source_horizon',
      rebalance_contract_id: 'daily_open_to_open',
      cost_contract_id: 'cost_10_bps',
    },
    sections: [{
      section_id: 'performance',
      availability_status: 'available',
      required_for_model_kind: true,
      reason: null,
      path: 'performance.json',
      sha256: PERFORMANCE_SHA,
      byte_size: PERFORMANCE_BYTE_SIZE,
      media_type: 'application/json',
    }],
  };
  return {
    key: `formal:qqq_rotation:${identity.modelVersionId}:${identity.runId}`,
    modelFamilyId: 'qqq_rotation',
    modelVersionId: identity.modelVersionId,
    runId: identity.runId,
    bundleId: BUNDLE_ID,
    title: 'Derived excess fixture',
    modelKind: 'rules_based_allocation',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'qqq',
    generatedAt: '2026-11-12T04:01:28Z',
    evidenceCutoff: '2026-11-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: 'qqq_rotation/fixture/manifest.json',
    manifestSha256: MANIFEST_SHA,
    summary: {},
    manifest,
    loadWarnings: [],
  };
}

function artifactFixture(identity: FixtureIdentity) {
  return {
    benchmark: {
      comparability_id: 'qqq',
      declared_identity: 'QQQ',
      series_field: 'bench',
      series_semantics: 'adjusted_open_to_next_adjusted_open',
    },
    boundaries: {
      descriptive_historical_metric: true,
      formal_catalog_modified: false,
      live_signal: false,
      pit_certified: false,
      research_only: true,
      sealed_formal_evidence_rewritten: false,
      source_registry_pins_modified: false,
      trade_ready: false,
    },
    derivation_id: identity.derivationId,
    evidence_type: 'derived_formal_benchmark_excess',
    inputs: [
      {
        bytes: 3331,
        manifest_section: null,
        path: 'data/research/formal_model_runs/qqq_rotation/fixture/manifest.json',
        role: 'formal_manifest',
        sha256: MANIFEST_SHA,
      },
      {
        bytes: PERFORMANCE_BYTE_SIZE,
        manifest_section: 'performance',
        path: 'data/research/formal_model_runs/qqq_rotation/fixture/performance.json',
        role: 'formal_performance',
        sha256: PERFORMANCE_SHA,
      },
    ],
    method: {
      goal: 'compounded_relative_excess',
      method_id: 'compounded_relative_excess',
    },
    result: {
      benchmark_cumulative_return: 0.6323106782547736,
      excess_return: 0.16979364938155483,
      strategy_cumulative_return: 0.9094666652401326,
    },
    schema_version: '1.0',
    strategy: {
      bundle_id: BUNDLE_ID,
      generated_at: '2026-11-12T04:01:28Z',
      manifest_sha256: MANIFEST_SHA,
      model_family_id: 'qqq_rotation',
      model_kind: 'rules_based_allocation',
      model_version_id: identity.modelVersionId,
      run_id: identity.runId,
    },
    window: {
      declared_end: '2026-11-10',
      declared_start: '2024-01-30',
      evidence_cutoff: '2026-11-11',
      holding_end_offset_sessions: 1,
      observation_count: 699,
      observed_end: '2026-11-10',
      observed_start: '2024-01-30',
      trace_frequency: 'daily_open_to_open',
    },
  };
}

function artifactText(artifact: unknown): string {
  return `${JSON.stringify(artifact)}\n`;
}

async function catalogTextFor(text: string, identity: CatalogIdentity): Promise<string> {
  const sha256 = await sha256Text(text);
  return `${JSON.stringify({
    schema_version: 'derived_metric_catalog_v1',
    research_only: true,
    trade_ready: false,
    generated_at: '2026-11-12T04:01:28Z',
    entries: [{
      derivation_id: identity.derivation_id,
      evidence_type: 'derived_formal_benchmark_excess',
      model_version_id: identity.model_version_id,
      run_id: identity.run_id,
      manifest_sha256: identity.manifest_sha256,
      path: `derived-metrics/${identity.derivation_id}.json`,
      sha256,
      byte_size: new TextEncoder().encode(text).byteLength,
    }],
  })}\n`;
}

function stubFetch(routes: Record<string, string>) {
  const fetcher = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const body = routes[url];
    if (body === undefined) return new Response('', { status: 404 });
    return new Response(body, { status: 200 });
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

async function serve(identity: FixtureIdentity, text: string) {
  const catalog = await catalogTextFor(text, entryIdentity(identity));
  return stubFetch({
    '/data/derived-metrics/catalog.json': catalog,
    [`/data/derived-metrics/${identity.derivationId}.json`]: text,
  });
}

async function expectReason(promise: Promise<unknown>, reason: DerivedExcessErrorReason): Promise<void> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(DerivedExcessError);
    expect((error as DerivedExcessError).reason).toBe(reason);
    return;
  }
  throw new Error(`Expected DerivedExcessError with reason ${reason}`);
}

afterEach(() => vi.unstubAllGlobals());

describe('loadDerivedExcess', () => {
  it('loads and binds a published derived excess artifact to its run', async () => {
    const identity = nextIdentity();
    const run = runFixture(identity);
    const artifact = artifactFixture(identity);
    const fetcher = await serve(identity, artifactText(artifact));

    const derived = await loadDerivedExcess(run);

    expect(derived).not.toBeNull();
    expect(derived).toMatchObject({
      derivationId: identity.derivationId,
      evidenceType: 'derived_formal_benchmark_excess',
      schemaVersion: '1.0',
      boundaries: {
        research_only: true,
        trade_ready: false,
        descriptive_historical_metric: true,
        live_signal: false,
      },
      modelFamilyId: 'qqq_rotation',
      modelVersionId: identity.modelVersionId,
      runId: identity.runId,
      manifestSha256: MANIFEST_SHA,
      methodId: 'compounded_relative_excess',
      result: artifact.result,
      window: {
        declared_start: '2024-01-30',
        declared_end: '2026-11-10',
        observed_start: '2024-01-30',
        observed_end: '2026-11-10',
        evidence_cutoff: '2026-11-11',
        observation_count: 699,
      },
      benchmark: {
        comparability_id: 'qqq',
        declared_identity: 'QQQ',
        series_semantics: 'adjusted_open_to_next_adjusted_open',
      },
      label: 'Derived · vs QQQ · 2024-01-30 → 2026-11-10 · 699 observations',
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][0]).toBe('/data/derived-metrics/catalog.json');
    expect(fetcher.mock.calls[1][0]).toBe(`/data/derived-metrics/${identity.derivationId}.json`);
    expect(fetcher.mock.calls[0][1]).toEqual({ cache: 'no-cache' });
  });

  it('returns null when the catalog is absent', async () => {
    stubFetch({});
    await expect(loadDerivedExcess(runFixture(nextIdentity()))).resolves.toBeNull();
  });

  it('returns null when the catalog has no derivation for the run', async () => {
    const identity = nextIdentity();
    const catalog = `${JSON.stringify({
      schema_version: 'derived_metric_catalog_v1',
      research_only: true,
      trade_ready: false,
      generated_at: '2026-11-12T04:01:28Z',
      entries: [],
    })}\n`;
    stubFetch({ '/data/derived-metrics/catalog.json': catalog });
    await expect(loadDerivedExcess(runFixture(identity))).resolves.toBeNull();
  });

  it('rejects a malformed research boundary', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    artifact.boundaries.trade_ready = true;
    await serve(identity, artifactText(artifact));
    await expectReason(loadDerivedExcess(runFixture(identity)), 'boundary_mismatch');
  });

  it('rejects an identity mismatch against the governed run', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    artifact.strategy.run_id = 'other-run';
    // The catalog still binds the run under test; only the artifact identity drifts.
    const text = artifactText(artifact);
    const catalog = await catalogTextFor(text, entryIdentity(identity));
    stubFetch({
      '/data/derived-metrics/catalog.json': catalog,
      [`/data/derived-metrics/${identity.derivationId}.json`]: text,
    });
    await expectReason(loadDerivedExcess(runFixture(identity)), 'identity_mismatch');
  });

  it('rejects a performance input SHA that does not match the run manifest', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    artifact.inputs[1].sha256 = 'd'.repeat(64);
    await serve(identity, artifactText(artifact));
    await expectReason(loadDerivedExcess(runFixture(identity)), 'performance_sha_mismatch');
  });

  it('rejects a compounded excess that does not reconcile', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    artifact.result.excess_return += 1e-6;
    await serve(identity, artifactText(artifact));
    await expectReason(loadDerivedExcess(runFixture(identity)), 'reconciliation_mismatch');
  });

  it('rejects non-finite results', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    artifact.result.excess_return = Number.POSITIVE_INFINITY;
    await serve(identity, artifactText(artifact));
    await expectReason(loadDerivedExcess(runFixture(identity)), 'result_invalid');
  });

  it('rejects a window without a positive observation count', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    artifact.window.observation_count = 0;
    await serve(identity, artifactText(artifact));
    await expectReason(loadDerivedExcess(runFixture(identity)), 'window_invalid');
  });

  it('rejects private operational fields in published bytes', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity) as ReturnType<typeof artifactFixture> & {
      benchmark: Record<string, unknown>;
    };
    artifact.benchmark.current_weights = { QQQ: 0.42 };
    await serve(identity, artifactText(artifact));
    await expectReason(loadDerivedExcess(runFixture(identity)), 'private_field');
  });

  it('rejects artifact bytes that changed after catalog publication', async () => {
    const identity = nextIdentity();
    const artifact = artifactFixture(identity);
    const text = artifactText(artifact);
    const catalog = await catalogTextFor(text, entryIdentity(identity));
    const tampered = artifactText({ ...artifact, boundaries: { ...artifact.boundaries, live_signal: true } });
    stubFetch({
      '/data/derived-metrics/catalog.json': catalog,
      [`/data/derived-metrics/${identity.derivationId}.json`]: tampered,
    });
    await expectReason(loadDerivedExcess(runFixture(identity)), 'artifact_hash_mismatch');
  });

  it('caches one catalog and artifact read per run identity', async () => {
    const identity = nextIdentity();
    const run = runFixture(identity);
    const fetcher = await serve(identity, artifactText(artifactFixture(identity)));

    const [first, second] = await Promise.all([loadDerivedExcess(run), loadDerivedExcess(run)]);
    expect(first).not.toBeNull();
    expect(first).toBe(second);
    expect(await loadDerivedExcess(run)).toBe(first);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
